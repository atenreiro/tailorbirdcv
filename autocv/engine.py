"""AI engine: the local Claude Code CLI in headless mode (`claude -p`).

Uses the CLI's own login (your Claude subscription), so there is no API key and no
per-call billing. Calls are fully isolated (see ISOLATION_ARGS): no tools, MCP servers,
plugins, hooks, skills or saved sessions, from an empty working directory — the model
only sees the prompt AutoCV builds, and must answer with JSON matching the schema.

Set AUTOCV_ENGINE=fake to run the UI with canned responses (tests / demos).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from typing import Any, Protocol


class EngineError(RuntimeError):
    pass


class Engine(Protocol):
    name: str

    async def status(self) -> dict: ...

    async def complete(self, system: str, prompt: str, schema: dict) -> Any: ...


# Run the model with nothing from the user's Claude Code setup: no tools, no MCP servers,
# no user/local settings (so no plugins), no hooks, no skills/slash commands, no saved
# session. The working directory is an empty temp dir, so "project" settings are empty
# too. Prompts carry the candidate's profile — none of it should reach hooks or plugins.
ISOLATION_ARGS = [
    "--tools", "", "--strict-mcp-config", "--no-session-persistence",
    "--setting-sources", "project", "--settings", json.dumps({"disableAllHooks": True}),
    "--disable-slash-commands",
]


class ClaudeCLIEngine:
    name = "claude-cli"

    def __init__(self, binary: str | None = None, model: str | None = None, timeout: float = 600):
        self.binary = binary or os.environ.get("AUTOCV_CLAUDE_BIN") or shutil.which("claude") or "claude"
        self.model = model or os.environ.get("AUTOCV_MODEL")
        self.timeout = timeout

    async def _run(self, args: list[str], stdin: str | None = None, timeout: float | None = None) -> str:
        with tempfile.TemporaryDirectory(prefix="autocv-engine-") as cwd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    self.binary, *args, cwd=cwd,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as e:
                raise EngineError("Claude Code CLI not found — install it or set AUTOCV_CLAUDE_BIN") from e
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(stdin.encode() if stdin is not None else None),
                    timeout or self.timeout,
                )
            except TimeoutError as e:
                proc.kill()
                raise EngineError("Claude CLI timed out") from e
        if proc.returncode and not out:
            raise EngineError(err.decode(errors="replace").strip() or f"claude exited {proc.returncode}")
        return out.decode(errors="replace")

    async def status(self) -> dict:
        if not shutil.which(self.binary) and not os.path.exists(self.binary):
            return {"engine": self.name, "ready": False, "detail": "Claude Code CLI not found"}
        try:
            raw = await self._run(["auth", "status"], timeout=20)
            info = json.loads(raw)
        except (EngineError, json.JSONDecodeError) as e:
            return {"engine": self.name, "ready": False, "detail": str(e)}
        ready = bool(info.get("loggedIn"))
        return {
            "engine": self.name, "ready": ready, "model": self.model or "CLI default",
            "detail": "logged in" if ready else "Not logged in — run `claude` in a terminal and use /login",
        }

    async def complete(self, system: str, prompt: str, schema: dict) -> Any:
        args = [
            "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
            "--system-prompt", system, *ISOLATION_ARGS,
        ]
        if self.model:
            args += ["--model", self.model]
        raw = await self._run(args, stdin=prompt)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise EngineError(f"unexpected CLI output: {raw[:300]}") from e
        if data.get("is_error"):
            raise EngineError(str(data.get("result") or data.get("subtype") or "Claude CLI error"))
        if data.get("structured_output") is not None:
            return data["structured_output"]
        result = data.get("result")
        if isinstance(result, str):
            text = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            try:
                return json.loads(text)
            except json.JSONDecodeError as e:
                raise EngineError(f"model did not return JSON: {result[:300]}") from e
        return result


class FakeEngine:
    """Deterministic stand-in. `responses` maps a task name (first line of the
    prompt, e.g. "TASK: analyze") to a value or a callable(prompt) -> value."""

    name = "fake"

    def __init__(self, responses: dict[str, Any] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, str]] = []

    async def status(self) -> dict:
        return {"engine": self.name, "ready": True, "model": "fake", "detail": "canned responses"}

    async def complete(self, system: str, prompt: str, schema: dict) -> Any:
        task = prompt.splitlines()[0].removeprefix("TASK:").strip()
        self.calls.append((task, prompt))
        if task not in self.responses:
            raise EngineError(f"fake engine has no response for task '{task}'")
        value = self.responses[task]
        return value(prompt) if callable(value) else value


def default_engine() -> Engine:
    if os.environ.get("AUTOCV_ENGINE") == "fake":
        from .demo import demo_engine
        return demo_engine()
    return ClaudeCLIEngine()
