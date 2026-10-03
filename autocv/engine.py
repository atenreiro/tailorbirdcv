"""AI engines, chosen in Settings → AI engine:

- the local Claude Code CLI in headless mode (`claude -p`), on the CLI's own login (your Claude
  subscription: no API key, no per-call billing), or
- the Anthropic API with your own key (kept in the OS keychain), billed per use.

CLI calls are fully isolated (see ISOLATION_ARGS): no tools, MCP servers, plugins, hooks,
skills or saved sessions, from an empty working directory. Either way the model only sees the
prompt AutoCV builds, and must answer with JSON matching the schema.

Set AUTOCV_ENGINE=fake to run the UI with canned responses (tests / demos).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Protocol

from . import oscompat


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


def _windows_command(binary: str) -> list[str]:
    """On Windows an npm install gives `claude.cmd`, which runs through cmd.exe and mangles
    arguments with quotes or newlines. Run its script with node directly instead."""
    if not (oscompat.IS_WINDOWS and binary.lower().endswith((".cmd", ".bat"))):
        return [binary]
    script = Path(binary).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    node = shutil.which("node")
    if script.is_file() and node:
        return [node, str(script)]
    raise EngineError("Found claude.cmd but not the Claude Code script it wraps. Install the native Claude Code "
                      "for Windows (claude.exe), or set AUTOCV_CLAUDE_BIN to claude.exe.")


class ClaudeCLIEngine:
    name = "claude-cli"

    def __init__(self, binary: str | None = None, model: str | None = None, timeout: float = 600,
                 command: list[str] | None = None):
        self.binary = binary or os.environ.get("AUTOCV_CLAUDE_BIN") or shutil.which("claude") or "claude"
        self.model = model or os.environ.get("AUTOCV_MODEL")
        self.timeout = timeout
        self.command = command  # the argv prefix to run instead of the binary (tests)

    async def _run(self, args: list[str], stdin: str | None = None, timeout: float | None = None,
                   files: dict[str, str] | None = None) -> str:
        """Run the CLI from an empty temp folder. `files` are written to a sibling folder first, and
        "{name}" in `args` becomes that file's path (long texts go in files, not on the command line,
        which Windows limits and cmd.exe mangles)."""
        with tempfile.TemporaryDirectory(prefix="autocv-engine-") as root:
            cwd, inputs = Path(root, "work"), Path(root, "in")
            cwd.mkdir()
            inputs.mkdir()
            for name, text in (files or {}).items():
                (inputs / name).write_text(text, encoding="utf-8")
            args = [str(inputs / a[1:-1]) if a[:1] == "{" and a[1:-1] in (files or {}) else a for a in args]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *(self.command or _windows_command(self.binary)), *args, cwd=cwd,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE, **oscompat.group_kwargs(),
                )
            except FileNotFoundError as e:
                raise EngineError("Claude Code CLI not found — install it or set AUTOCV_CLAUDE_BIN") from e
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(stdin.encode() if stdin is not None else None),
                    timeout or self.timeout,
                )
            except TimeoutError as e:
                oscompat.kill_tree(proc.pid)  # the CLI and its node/helper processes
                await proc.wait()  # before the temp folder is removed (Windows can't delete it in use)
                raise EngineError("Claude CLI timed out") from e
        if proc.returncode and not out:
            raise EngineError(err.decode(errors="replace").strip() or f"claude exited {proc.returncode}")
        return out.decode(errors="replace")

    async def status(self) -> dict:
        if not self.command and not shutil.which(self.binary) and not os.path.exists(self.binary):
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
            "--system-prompt-file", "{system.md}", *ISOLATION_ARGS,
        ]
        if self.model:
            args += ["--model", self.model]
        raw = await self._run(args, stdin=prompt, files={"system.md": system})
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


DEFAULT_API_MODEL = "claude-sonnet-5-5"


class AnthropicAPIEngine:
    """Claude through the Anthropic API with the user's own key (pay per use). Structured output via
    a forced tool call whose input schema is AutoCV's JSON schema."""

    name = "anthropic-api"

    def __init__(self, model: str | None = None, timeout: float = 600, key=None, client_factory=None):
        from . import apikey
        self.model = model or DEFAULT_API_MODEL
        self.timeout = timeout
        self._key = key or (lambda: apikey.get()[0])
        self._client_factory = client_factory
        self._checked: tuple[str, float, dict] | None = None  # (key, when, status) — status is cached briefly

    def _client(self, key: str):
        if self._client_factory:
            return self._client_factory(key)
        import anthropic
        return anthropic.AsyncAnthropic(api_key=key, timeout=self.timeout, max_retries=2)

    @staticmethod
    def _explain(e: Exception) -> str:
        import anthropic
        if isinstance(e, anthropic.AuthenticationError):
            return "The Anthropic API key was rejected. Check it in Settings → AI engine."
        if isinstance(e, anthropic.PermissionDeniedError):
            return "This API key isn't allowed to use that model."
        if isinstance(e, anthropic.NotFoundError):
            return "That model isn't available to this API key. Choose another model in Settings → AI engine."
        if isinstance(e, anthropic.RateLimitError):
            return "The Anthropic API rate limit was reached. Wait a minute and try again."
        if isinstance(e, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
            return "Couldn't reach the Anthropic API. Check your internet connection."
        if isinstance(e, anthropic.APIStatusError):
            return f"The Anthropic API returned an error ({e.status_code})."
        return str(e)

    async def status(self) -> dict:
        import time
        key = self._key()
        base = {"engine": self.name, "model": self.model}
        if not key:
            return {**base, "ready": False, "detail": "No API key yet — add one in Settings → AI engine."}
        if self._checked and self._checked[0] == key and time.monotonic() - self._checked[1] < 300:
            return self._checked[2]
        try:
            await self._client(key).models.retrieve(self.model)
            result = {**base, "ready": True, "detail": "API key works"}
        except Exception as e:  # noqa: BLE001
            result = {**base, "ready": False, "detail": self._explain(e)}
        self._checked = (key, time.monotonic(), result)
        return result

    async def complete(self, system: str, prompt: str, schema: dict) -> Any:
        key = self._key()
        if not key:
            raise EngineError("No Anthropic API key — add one in Settings → AI engine.")
        try:
            msg = await self._client(key).messages.create(
                model=self.model, max_tokens=16000, system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[{"name": "answer", "description": "Return the result as JSON matching the schema.",
                        "input_schema": schema}],
                tool_choice={"type": "tool", "name": "answer"},
            )
        except Exception as e:  # noqa: BLE001
            raise EngineError(self._explain(e)) from e
        if getattr(msg, "stop_reason", None) == "max_tokens":
            raise EngineError("The answer was cut off (too long). Try again, or shorten the job description.")
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use":
                return block.input
        raise EngineError("The model did not return structured output.")


class SwitchingEngine:
    """The engine chosen in Settings → AI engine, looked up on every call (so switching takes effect
    without a restart)."""

    def __init__(self, store):
        self.store = store
        self._cli: ClaudeCLIEngine | None = None
        self._api: dict[str, AnthropicAPIEngine] = {}

    def current(self) -> Engine:
        settings = self.store.settings()
        if settings.get("ai_engine") == "anthropic-api":
            model = settings.get("api_model") or DEFAULT_API_MODEL
            return self._api.setdefault(model, AnthropicAPIEngine(model=model))
        self._cli = self._cli or ClaudeCLIEngine()
        return self._cli

    @property
    def name(self) -> str:
        return self.current().name

    async def status(self) -> dict:
        return await self.current().status()

    async def complete(self, system: str, prompt: str, schema: dict) -> Any:
        return await self.current().complete(system, prompt, schema)


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


def default_engine(store=None) -> Engine:
    if os.environ.get("AUTOCV_ENGINE") == "fake":
        from .demo import demo_engine
        return demo_engine()
    if store is None:
        from .store import Store
        store = Store.default()
    return SwitchingEngine(store)
