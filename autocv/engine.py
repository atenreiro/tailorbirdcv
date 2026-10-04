"""AI engines, chosen in Settings → AI engine (ENGINES):

- subscriptions, through a local app's login (no API key, no per-call billing):
  the Claude Code CLI (`claude -p`) or OpenAI's Codex CLI (`codex exec`, ChatGPT login);
- API keys (kept in the OS keychain, billed per use): Anthropic, OpenAI, or OpenRouter.

CLI calls are isolated (see ISOLATION_ARGS / CODEX_ISOLATION): no tools, MCP servers, plugins, hooks,
skills or saved sessions, from an empty working directory, with every API key removed from the
environment. Either way the model only sees the prompt AutoCV builds, and must answer with JSON
matching the schema (OpenAI-style APIs get it in strict form: see openai_schema).

Set AUTOCV_ENGINE=fake to run the UI with canned responses (tests / demos).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
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


_NPM_SCRIPTS = {"claude": ("@anthropic-ai/claude-code/cli.js", "Claude Code", "claude.exe", "AUTOCV_CLAUDE_BIN"),
                "codex": ("@openai/codex/bin/codex.js", "Codex", "codex.exe", "AUTOCV_CODEX_BIN")}


def _windows_command(binary: str, tool: str = "claude") -> list[str]:
    """On Windows an npm install gives `claude.cmd` / `codex.cmd`, which run through cmd.exe and mangle
    arguments with quotes or newlines. Run the script it wraps with node directly instead."""
    if not (oscompat.IS_WINDOWS and binary.lower().endswith((".cmd", ".bat"))):
        return [binary]
    script_path, product, exe, env = _NPM_SCRIPTS[tool]
    script = Path(binary).parent / "node_modules" / Path(script_path)
    node = shutil.which("node")
    if script.is_file() and node:
        return [node, str(script)]
    raise EngineError(f"Found {Path(binary).name} but not the {product} script it wraps. Install the native {product} "
                      f"for Windows ({exe}), or set {env} to {exe}.")


# A subscription CLI must never see an API key: in `claude -p` ANTHROPIC_API_KEY always wins over the
# subscription login, and Codex prefers CODEX_API_KEY over the ChatGPT login — either would silently
# bill a key. Every provider's key is removed from both CLIs' environments.
_API_CREDENTIALS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
                    "CODEX_API_KEY", "CODEX_ACCESS_TOKEN")


def cli_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _API_CREDENTIALS}


def find_cli(tool: str) -> str | None:
    """`tool` on PATH, or in the folders installers put it in. A server started before the install has an
    old PATH (installers add their folder in shell start-up files), so look there too."""
    if found := shutil.which(tool):
        return found
    home = Path.home()
    folders = [home / ".local" / "bin", home / ".claude" / "local", home / ".npm-global" / "bin",
               home / ".volta" / "bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    if oscompat.IS_WINDOWS:  # pragma: no cover
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        folders = [home / ".local" / "bin", appdata / "npm", home / ".claude" / "local"]
    names = [f"{tool}.exe", f"{tool}.cmd"] if oscompat.IS_WINDOWS else [tool]
    for folder in folders:
        for name in names:
            if (folder / name).is_file():
                return str(folder / name)
    return None


def cli_version(binary: str) -> tuple[int, ...] | None:
    """`<binary> --version` as numbers, e.g. (0, 160, 0); None when it doesn't say."""
    import re
    import subprocess
    try:
        out = subprocess.run([*_windows_command(binary, "codex" if "codex" in Path(binary).name.lower() else "claude"),
                              "--version"], capture_output=True, text=True, timeout=15, env=cli_env()).stdout
    except (OSError, subprocess.SubprocessError, EngineError):
        return None
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", out)
    return tuple(int(x) for x in m.groups() if x is not None) if m else None


async def _run_cli(command: list[str], args, *, stdin: str | None, timeout: float, product: str,
                   files: dict[str, str] | None = None, collect: tuple[str, ...] = ()) -> tuple[int, str, str, dict]:
    """Run a CLI from an empty temp folder (`work`). `files` are written to a sibling folder (`in`) first.
    `args` is a list in which "{name}" becomes that file's path, or a callable(inputs, work) -> list.
    Returns (exit code, stdout, stderr, {name: text} for each name in `collect` that the CLI wrote to `in`)."""
    with tempfile.TemporaryDirectory(prefix="autocv-engine-") as root:
        cwd, inputs = Path(root, "work"), Path(root, "in")
        cwd.mkdir()
        inputs.mkdir()
        for name, text in (files or {}).items():
            (inputs / name).write_text(text, encoding="utf-8")
        if callable(args):
            args = args(inputs, cwd)
        else:
            args = [str(inputs / a[1:-1]) if a[:1] == "{" and a[1:-1] in (files or {}) else a for a in args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *command, *args, cwd=cwd, env=cli_env(),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, **oscompat.group_kwargs(),
            )
        except FileNotFoundError as e:
            raise EngineError(f"{product} not found — install it, or set its path in the environment") from e
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin.encode() if stdin is not None else None), timeout)
        except TimeoutError as e:
            oscompat.kill_tree(proc.pid)  # the CLI and its node/helper processes
            await proc.wait()  # before the temp folder is removed (Windows can't delete it in use)
            raise EngineError(f"{product} timed out") from e
        collected = {n: (inputs / n).read_text(encoding="utf-8") for n in collect if (inputs / n).is_file()}
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace"), collected


class ClaudeCLIEngine:
    name = "claude-cli"

    def __init__(self, binary: str | None = None, model: str | None = None, timeout: float = 600,
                 command: list[str] | None = None):
        self._binary = binary
        self.model = model or os.environ.get("AUTOCV_MODEL")
        self.timeout = timeout
        self.command = command  # the argv prefix to run instead of the binary (tests)

    @property
    def binary(self) -> str:  # looked up each time, so a Claude Code installed after AutoCV started is found
        return self._binary or os.environ.get("AUTOCV_CLAUDE_BIN") or find_cli("claude") or "claude"

    async def _run(self, args: list[str], stdin: str | None = None, timeout: float | None = None,
                   files: dict[str, str] | None = None) -> str:
        """Run the CLI from an empty temp folder (long texts go in `files`, not on the command line,
        which Windows limits and cmd.exe mangles)."""
        try:
            code, out, err, _ = await _run_cli(self.command or _windows_command(self.binary), args, stdin=stdin,
                                               timeout=timeout or self.timeout, files=files, product="Claude CLI")
        except EngineError as e:
            if "not found" in str(e):
                raise EngineError("Claude Code CLI not found — install it or set AUTOCV_CLAUDE_BIN") from e
            raise
        if code and not out:
            raise EngineError(err.strip() or f"claude exited {code}")
        return out

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
    """Claude through the Anthropic API with the user's own key (pay per use), answering through
    structured outputs (JSON matching AutoCV's schema). Forced tool choice isn't used: current models
    (Opus 5.5, Sonnet 5.5, Fable 5.1) reject it."""

    name = "anthropic-api"

    def __init__(self, model: str | None = None, timeout: float = 600, key=None, client_factory=None):
        from . import apikey
        self.model = model or DEFAULT_API_MODEL
        self.timeout = timeout
        self._key = key or (lambda: apikey.get()[0])
        self._client_factory = client_factory
        self._checked: tuple[str, float, dict] | None = None  # (key, when, status) — status is cached briefly
        self._tool_fallback: set[str] = set()  # schemas the API couldn't compile for structured outputs
        self._clients: dict = {}

    def _client(self, key: str):
        """One client (and connection pool) per key, reused across calls."""
        if self._client_factory:
            return self._client_factory(key)
        if self._clients.get("key") != key:
            import anthropic
            self._clients = {"key": key,
                             "client": anthropic.AsyncAnthropic(api_key=key, timeout=self.timeout, max_retries=2)}
        return self._clients["client"]

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
        """Checks the key with a one-token request (cached: 5 minutes when it works, 15 s when not)."""
        import time
        key = await asyncio.to_thread(self._key)
        base = {"engine": self.name, "model": self.model}
        if not key:
            return {**base, "ready": False, "detail": "No API key yet — add one in Settings → AI engine."}
        if self._checked and self._checked[0] == key and time.monotonic() - self._checked[1] < \
                (300 if self._checked[2]["ready"] else 15):
            return self._checked[2]
        try:
            await self._client(key).messages.create(model=self.model, max_tokens=1,
                                                    messages=[{"role": "user", "content": "ping"}])
            result = {**base, "ready": True, "detail": "API key works"}
        except Exception as e:  # noqa: BLE001
            result = {**base, "ready": False, "detail": self._explain(e)}
        self._checked = (key, time.monotonic(), result)
        return result

    async def complete(self, system: str, prompt: str, schema: dict) -> Any:
        """Structured outputs (the response is JSON matching the schema). A schema the API can't
        compile falls back to an ordinary tool call; AutoCV validates every answer either way."""
        key = await asyncio.to_thread(self._key)
        if not key:
            raise EngineError("No Anthropic API key — add one in Settings → AI engine.")
        client, strict = self._client(key), api_schema(schema)
        signature = json.dumps(strict, sort_keys=True)
        if signature not in self._tool_fallback:
            try:
                msg = await client.messages.create(
                    model=self.model, max_tokens=16000, system=system,
                    messages=[{"role": "user", "content": prompt}],
                    output_config={"format": {"type": "json_schema", "schema": strict}})
                return _structured(msg)
            except EngineError:
                raise
            except Exception as e:  # noqa: BLE001
                if not _schema_rejected(e):
                    raise EngineError(self._explain(e)) from e
                self._tool_fallback.add(signature)
        try:
            msg = await client.messages.create(
                model=self.model, max_tokens=16000,
                system=system + "\n\nAnswer by calling the `answer` tool exactly once with the complete result.",
                messages=[{"role": "user", "content": prompt}],
                tools=[{"name": "answer", "description": "Return the complete result as JSON matching the schema.",
                        "input_schema": schema}],
                tool_choice={"type": "auto"})
        except Exception as e:  # noqa: BLE001
            raise EngineError(self._explain(e)) from e
        _check_stop(msg)
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use":
                return block.input
        raise EngineError("The model did not return structured output. Try again.")


_UNSUPPORTED = ("maxItems", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
                "exclusiveMaximum", "multipleOf", "maxProperties", "minProperties")


def api_schema(schema: Any) -> Any:
    """AutoCV's JSON schema adapted to structured outputs: unsupported constraints dropped (AutoCV
    validates the answer itself) and every object closed with additionalProperties: false."""
    if isinstance(schema, list):
        return [api_schema(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: api_schema(v) for k, v in schema.items() if k not in _UNSUPPORTED}
    if out.get("minItems", 0) > 1:
        out["minItems"] = 1
    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
    return out


def _check_stop(msg) -> None:
    reason = getattr(msg, "stop_reason", None)
    if reason == "refusal":
        raise EngineError("Claude declined this request (its safety checks flagged it). Try again, or switch "
                          "engines in Settings → AI engine.")
    if reason == "max_tokens":
        raise EngineError("The answer was cut off (too long). Try again, or shorten the job description.")


def _structured(msg) -> Any:
    _check_stop(msg)
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", None) == "text").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise EngineError("The model's answer wasn't valid JSON. Try again.") from e


def _schema_rejected(e: Exception) -> bool:
    """A 400 about the schema itself (too complex, unsupported keyword): retry with a tool call."""
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        return False
    return isinstance(e, anthropic.BadRequestError) and "schema" in str(e).lower()


# ---------------------------------------------------------------- OpenAI-style strict schemas

_DROP = ("title", "default", "examples", "$defs", "definitions", "minItems", "$schema")


def _deref(node: Any, defs: dict, seen: int = 0) -> Any:
    while isinstance(node, dict) and "$ref" in node and seen < 50:
        name = node["$ref"].rsplit("/", 1)[-1]
        node = {**defs.get(name, {}), **{k: v for k, v in node.items() if k != "$ref"}}
        seen += 1
    return node


def _nullable(node: dict) -> dict:
    t = node.get("type")
    if t == "null" or (isinstance(t, list) and "null" in t):
        return node
    if any(isinstance(b, dict) and b.get("type") == "null" for b in node.get("anyOf", [])):
        return node
    if isinstance(t, str) and "enum" not in node and "properties" not in node and "items" not in node \
            and "$ref" not in node:
        return {**node, "type": [t, "null"]}
    return {"anyOf": [node, {"type": "null"}]}


def openai_schema(schema: dict) -> dict:
    """AutoCV's JSON schema in OpenAI's strict form (OpenAI API, OpenRouter, Codex --output-schema):
    titles, defaults and unsupported constraints dropped; every object closed with every property required,
    the ones that were optional made nullable (the answer goes through strip_nulls). Shared definitions
    ($defs) stay shared, each converted once, so big enums (evidence ids) aren't copied into every use."""
    defs = schema.get("$defs") or schema.get("definitions") or {}

    def conv(node: Any, depth: int = 0) -> Any:
        if depth > 40:
            raise EngineError("The schema is nested too deeply for strict structured outputs.")
        if isinstance(node, list):
            return [conv(x, depth + 1) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:  # a shared definition: keep the reference (siblings like description are dropped)
            return {"$ref": "#/$defs/" + node["$ref"].rsplit("/", 1)[-1]}
        out = {k: conv(v, depth + 1) for k, v in node.items()
               if k not in _DROP and k not in _UNSUPPORTED and k not in ("properties", "required")}
        if "properties" in node or node.get("type") == "object":
            props = node.get("properties", {})
            required = set(node.get("required", []))
            out["properties"] = {k: (conv(v, depth + 1) if k in required else _nullable(conv(v, depth + 1)))
                                 for k, v in props.items()}
            out["required"] = list(props)
            out["additionalProperties"] = False
            out.setdefault("type", "object")
        return out

    out = conv(schema)
    if defs:
        out["$defs"] = {name: conv(d, 1) for name, d in defs.items()}
    return out


def _branch(node: Any, kind: str, defs: dict) -> dict | None:
    node = _deref(node, defs)
    if not isinstance(node, dict):
        return None
    t = node.get("type")
    if t == kind or (isinstance(t, list) and kind in t) or (kind == "object" and "properties" in node):
        return node
    for b in node.get("anyOf", []) + node.get("oneOf", []):
        if found := _branch(b, kind, defs):
            return found
    return None


def strip_nulls(value: Any, schema: dict, _defs: dict | None = None) -> Any:
    """Undo openai_schema's nullable optionals: a null for a property the original schema didn't require
    is dropped, so the answer validates exactly as it would from Claude."""
    defs = _defs if _defs is not None else (schema.get("$defs") or schema.get("definitions") or {})
    if isinstance(value, dict):
        obj = _branch(schema, "object", defs)
        if not obj:
            return value
        required, props = set(obj.get("required", [])), obj.get("properties", {})
        return {k: strip_nulls(v, props.get(k, {}), defs) for k, v in value.items()
                if not (v is None and k not in required)}
    if isinstance(value, list):
        arr = _branch(schema, "array", defs)
        items = arr.get("items", {}) if arr else {}
        return [strip_nulls(v, items, defs) for v in value]
    return value


# ---------------------------------------------------------------- API-key engines on the openai SDK

class _OpenAIStyleEngine:
    """Shared by the OpenAI and OpenRouter engines: the key from the keychain (per provider), one client
    per key, and a briefly cached status check."""

    name = ""
    provider = ""
    default_model = ""
    product = ""

    def __init__(self, model: str | None = None, timeout: float = 600, key=None, client_factory=None):
        from . import apikey
        self.model = model or self.default_model
        self.timeout = timeout
        self._key = key or (lambda: apikey.get(self.provider)[0])
        self._client_factory = client_factory
        self._checked: tuple[str, float, dict] | None = None
        self._clients: dict = {}

    def _make_client(self, key: str):
        raise NotImplementedError

    def _client(self, key: str):
        if self._client_factory:
            return self._client_factory(key)
        if self._clients.get("key") != key:
            self._clients = {"key": key, "client": self._make_client(key)}
        return self._clients["client"]

    def _explain(self, e: Exception) -> str:
        import openai
        p = self.product
        if isinstance(e, openai.AuthenticationError):
            return f"The {p} API key was rejected. Check it in Settings → AI engine."
        if isinstance(e, openai.PermissionDeniedError):
            return f"This {p} API key isn't allowed to use that model."
        if isinstance(e, openai.NotFoundError):
            return f"That model isn't available on {p}. Choose another model in Settings → AI engine."
        if isinstance(e, openai.RateLimitError):
            return f"The {p} rate limit or quota was reached. Wait a minute and try again, or check your plan."
        if isinstance(e, (openai.APIConnectionError, openai.APITimeoutError)):
            return f"Couldn't reach {p}. Check your internet connection."
        if isinstance(e, openai.APIStatusError):
            return f"{p} returned an error ({e.status_code}): {_api_message(e)}"
        return str(e)

    async def _ping(self, client) -> dict:
        raise NotImplementedError

    async def status(self) -> dict:
        import time
        key = await asyncio.to_thread(self._key)
        base = {"engine": self.name, "model": self.model}
        if not key:
            return {**base, "ready": False, "detail": "No API key yet — add one in Settings → AI engine."}
        if self._checked and self._checked[0] == key and time.monotonic() - self._checked[1] < \
                (300 if self._checked[2]["ready"] else 15):
            return self._checked[2]
        try:
            result = {**base, "ready": True, **(await self._ping(self._client(key)))}
        except Exception as e:  # noqa: BLE001
            result = {**base, "ready": False, "detail": self._explain(e)}
        self._checked = (key, time.monotonic(), result)
        return result

    async def _key_or_fail(self) -> str:
        key = await asyncio.to_thread(self._key)
        if not key:
            raise EngineError(f"No {self.product} API key — add one in Settings → AI engine.")
        return key


def _api_message(e: Exception) -> str:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:300]
    return str(getattr(e, "message", e))[:300]


def _json_answer(text: str | None, schema: dict) -> Any:
    try:
        return strip_nulls(json.loads((text or "").strip()), schema)
    except json.JSONDecodeError as e:
        raise EngineError("The model's answer wasn't valid JSON. Try again.") from e


DEFAULT_OPENAI_MODEL = "gpt-6.1-sol"


class OpenAIAPIEngine(_OpenAIStyleEngine):
    """OpenAI's Responses API with the user's key: strict structured outputs, nothing stored (store=False)."""

    name, provider, default_model, product = "openai-api", "openai", DEFAULT_OPENAI_MODEL, "OpenAI"

    def _make_client(self, key: str):
        import openai
        return openai.AsyncOpenAI(api_key=key, timeout=self.timeout, max_retries=2)

    async def _ping(self, client) -> dict:
        await client.models.retrieve(self.model)  # free; checks both the key and the model
        return {"detail": "API key works"}

    async def complete(self, system: str, prompt: str, schema: dict) -> Any:
        client = self._client(await self._key_or_fail())
        try:
            r = await client.responses.create(
                model=self.model, instructions=system, input=prompt, store=False, max_output_tokens=32000,
                text={"format": {"type": "json_schema", "name": "result", "schema": openai_schema(schema),
                                 "strict": True}})
        except Exception as e:  # noqa: BLE001
            raise EngineError(self._explain(e)) from e
        for item in getattr(r, "output", None) or []:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    raise EngineError("The model declined this request. Try again, or switch engines in "
                                      "Settings → AI engine.")
        if getattr(r, "status", None) == "incomplete":
            reason = getattr(getattr(r, "incomplete_details", None), "reason", None)
            raise EngineError("The answer was cut off (too long). Try again, or shorten the job description."
                              if reason == "max_output_tokens" else f"The model stopped early ({reason}). Try again.")
        return _json_answer(getattr(r, "output_text", None), schema)


DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-5.5"  # the same Claude model as DEFAULT_API_MODEL
OPENROUTER_URL = "https://openrouter.ai/api/v1"


class OpenRouterEngine(_OpenAIStyleEngine):
    """OpenRouter with the user's key (Chat Completions, structured outputs). By default only providers
    with zero data retention and no data collection serve the request; `zdr=False` routes to Anthropic
    itself instead (still with data collection denied)."""

    name, provider, default_model, product = "openrouter-api", "openrouter", DEFAULT_OPENROUTER_MODEL, "OpenRouter"

    def __init__(self, model: str | None = None, timeout: float = 600, key=None, client_factory=None,
                 zdr: bool = True):
        super().__init__(model, timeout, key, client_factory)
        self.zdr = zdr
        self._tool_fallback: set[str] = set()

    def _make_client(self, key: str):
        import openai
        return openai.AsyncOpenAI(api_key=key, base_url=OPENROUTER_URL, timeout=self.timeout, max_retries=2,
                                  default_headers={"X-OpenRouter-Title": "AutoCV",
                                                   "HTTP-Referer": "https://github.com/atenreiro/autocv"})

    def routing(self) -> dict:
        provider = {"require_parameters": True, "data_collection": "deny"}
        if self.zdr:
            provider.update({"zdr": True, "allow_fallbacks": True})
        elif self.model.startswith("anthropic/"):  # Claude: served by Anthropic itself
            provider.update({"only": ["anthropic"], "allow_fallbacks": False})
        return {"provider": provider}

    def _explain(self, e: Exception) -> str:
        import openai
        code = getattr(e, "status_code", None)
        if isinstance(e, openai.APIStatusError) and code == 402:
            return "Your OpenRouter credit has run out. Add credits at openrouter.ai, then try again."
        if isinstance(e, openai.APIStatusError) and code == 403:
            return f"OpenRouter's moderation blocked this request: {_api_message(e)}"
        if isinstance(e, openai.APIStatusError) and code == 503:
            return ("No OpenRouter provider can serve this model with these privacy settings right now. Try again, "
                    "or allow Anthropic-hosted in Settings → AI engine." if self.zdr else
                    "OpenRouter has no provider available for this model right now. Try again shortly.")
        return super()._explain(e)

    async def _ping(self, client) -> dict:
        await client.get(f"/models/{self.model}/endpoints", cast_to=object)  # free: the model exists
        info = await client.get("/key", cast_to=object)
        data = info.get("data", info) if isinstance(info, dict) else {}
        left = data.get("limit_remaining") if isinstance(data, dict) else None
        return {"detail": "API key works" + (f" · ${left:.2f} credit left" if isinstance(left, (int, float)) else "")}

    async def complete(self, system: str, prompt: str, schema: dict) -> Any:
        client = self._client(await self._key_or_fail())
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        strict = openai_schema(schema)
        signature = json.dumps(strict, sort_keys=True)
        if signature not in self._tool_fallback:
            try:
                r = await client.chat.completions.create(
                    model=self.model, messages=messages, max_tokens=16000,
                    response_format={"type": "json_schema",
                                     "json_schema": {"name": "result", "strict": True, "schema": strict}},
                    extra_body={**self.routing(), "plugins": [{"id": "response-healing"}]})
                return _json_answer(self._content(r), schema)
            except EngineError:
                raise
            except Exception as e:  # noqa: BLE001
                if not (_schema_rejected_openai(e) or _no_structured_endpoint(e)):
                    raise EngineError(self._explain(e)) from e
                self._tool_fallback.add(signature)
        try:  # the model or provider can't take this schema: one ordinary tool call instead
            r = await client.chat.completions.create(
                model=self.model, max_tokens=16000, extra_body=self.routing(),
                messages=[{"role": "system", "content": system + "\n\nAnswer by calling the `answer` tool exactly "
                                                                  "once with the complete result."},
                          {"role": "user", "content": prompt}],
                tools=[{"type": "function", "function": {"name": "answer", "parameters": schema,
                                                         "description": "Return the complete result."}}],
                tool_choice="auto")
        except Exception as e:  # noqa: BLE001
            raise EngineError(self._explain(e)) from e
        self._check(r)
        for call in getattr(r.choices[0].message, "tool_calls", None) or []:
            if call.function.name == "answer":
                return _json_answer(call.function.arguments, schema)
        raise EngineError("The model did not return structured output. Try again.")

    @staticmethod
    def _check(r) -> None:
        if not getattr(r, "choices", None):
            raise EngineError("OpenRouter returned no answer. Try again.")
        choice = r.choices[0]
        if getattr(choice.message, "refusal", None):
            raise EngineError("The model declined this request. Try again, or switch engines in Settings → AI engine.")
        reason = getattr(choice, "finish_reason", None)
        if reason == "length":
            raise EngineError("The answer was cut off (too long). Try again, or shorten the job description.")
        if reason == "content_filter":
            raise EngineError("The provider's content filter stopped this answer. Try again, or switch engines.")
        if reason == "error":
            raise EngineError("The provider failed while answering. Try again.")

    def _content(self, r) -> str | None:
        self._check(r)
        return r.choices[0].message.content


def _no_structured_endpoint(e: Exception) -> bool:
    """OpenRouter has the model, but no provider for it supports structured outputs (require_parameters)."""
    try:
        import openai
    except ImportError:  # pragma: no cover
        return False
    text = str(e).lower()
    return isinstance(e, openai.NotFoundError) and "endpoint" in text and ("parameter" in text or "support" in text)


def _schema_rejected_openai(e: Exception) -> bool:
    try:
        import openai
    except ImportError:  # pragma: no cover
        return False
    return isinstance(e, openai.BadRequestError) and "schema" in str(e).lower()


# ---------------------------------------------------------------- Codex CLI (ChatGPT subscription)

# `codex exec` is a coding agent: everything that isn't answering from the prompt is switched off. Its
# file-editing tool can't be removed, only sandboxed (read-only, in an empty folder, approvals never).
CODEX_ISOLATION = [
    "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
    "-s", "read-only", "--color", "never", "--json",
    "-c", 'approval_policy="never"', "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"',
    "-c", 'history.persistence="none"', "-c", "features.shell_tool=false", "-c", "features.unified_exec=false",
    "-c", "features.multi_agent=false", "-c", "features.apps=false", "-c", "features.remote_plugin=false",
    "-c", "features.memories=false", "-c", "features.hooks=false", "-c", "mcp_servers={}",
    # Tools that are on by default in Codex 0.160 (see `codex features list`); unknown names are ignored.
    *[a for f in ("view_image", "image_generation", "browser_use", "browser_use_external", "browser_use_full_cdp_access",
                  "computer_use", "code_mode_host", "in_app_browser", "in_app_local_automation", "plugins",
                  "skill_search", "skill_mcp_dependency_install", "tool_suggest", "sleep_tool", "shell_snapshot",
                  "workspace_dependencies", "worktrees", "goals")
      for a in ("-c", f"features.{f}=false")],
]
CODEX_MIN_VERSION = (0, 160)  # the flags above were checked against this version


class CodexCLIEngine:
    name = "codex-cli"

    def __init__(self, binary: str | None = None, model: str | None = None, timeout: float = 600,
                 command: list[str] | None = None):
        self._binary = binary
        self.model = model
        self.timeout = timeout
        self.command = command  # the argv prefix to run instead of the binary (tests)
        self._login: tuple[float, dict] | None = None  # the last login check (when, status)

    @property
    def binary(self) -> str:  # looked up each time, so a Codex installed after AutoCV started is found
        return self._binary or os.environ.get("AUTOCV_CODEX_BIN") or find_cli("codex") or "codex"

    def _argv(self) -> list[str]:
        return self.command or _windows_command(self.binary, "codex")

    async def status(self) -> dict:
        model = self.model or "Codex default"
        base = {"engine": self.name, "model": model}
        if not self.command and not shutil.which(self.binary) and not os.path.exists(self.binary):
            return {**base, "ready": False, "detail": "Codex CLI not found"}
        try:
            code, out, err, _ = await _run_cli(self._argv(), ["login", "status"], stdin=None, timeout=20,
                                               product="Codex CLI")
        except EngineError as e:
            return {**base, "ready": False, "detail": str(e)}
        text = f"{out}\n{err}".lower()
        if code == 0 and "chatgpt" in text:
            if not self.command:
                version = await asyncio.to_thread(cli_version, self.binary)
                if version and version[:2] < CODEX_MIN_VERSION:
                    shown = ".".join(map(str, version))
                    return {**base, "ready": False, "detail": f"Codex {shown} is too old for AutoCV — update it: "
                                                              "npm i -g @openai/codex"}
            return {**base, "ready": True, "detail": "logged in with ChatGPT"}
        if code == 0 and "api key" in text:
            return {**base, "ready": False,
                    "detail": "Codex is logged in with an API key, which would be billed. Run `codex login` and sign "
                              "in with ChatGPT, or choose the OpenAI API key engine instead."}
        if code == 0 and "not logged in" not in text:
            return {**base, "ready": False,
                    "detail": "Codex is logged in some other way (not ChatGPT). Run `codex login` and sign in with "
                              "ChatGPT to use your subscription."}
        return {**base, "ready": False, "detail": "Not logged in — run `codex login` in a terminal and sign in with ChatGPT"}

    async def _require_chatgpt(self) -> None:
        """Never run on an API-key login (it would bill the key): checked before calls, cached for a minute."""
        import time
        if self.command:  # tests drive a fake binary
            return
        if not self._login or time.monotonic() - self._login[0] > 60 or not self._login[1]["ready"]:
            self._login = (time.monotonic(), await self.status())
        if not self._login[1]["ready"]:
            raise EngineError(self._login[1]["detail"])

    async def complete(self, system: str, prompt: str, schema: dict) -> Any:
        await self._require_chatgpt()

        def args(inputs: Path, work: Path) -> list[str]:
            argv = ["exec", "-", *CODEX_ISOLATION, "-C", str(work),
                    "--output-schema", str(inputs / "schema.json"), "-o", str(inputs / "last.json"),
                    "-c", f"model_instructions_file={json.dumps(str(inputs / 'system.md'), ensure_ascii=False)}"]
            return argv + (["-m", self.model] if self.model else [])

        code, out, err, got = await _run_cli(
            self._argv(), args, stdin=prompt, timeout=self.timeout, product="Codex CLI",
            files={"system.md": system, "schema.json": json.dumps(openai_schema(schema))}, collect=("last.json",))
        failure = _codex_failure(out)
        if "last.json" not in got or not got["last.json"].strip():
            raise EngineError(failure or err.strip()[-300:] or f"Codex exited {code} without an answer")
        return _json_answer(got["last.json"], schema)


def _codex_failure(events: str) -> str | None:
    """The error message from `codex exec --json` events (turn.failed / error), if any."""
    for line in events.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("type") in ("turn.failed", "error"):
            err = ev.get("error") if isinstance(ev.get("error"), dict) else ev
            return str(err.get("message") or ev)[:300]
    return None


# ---------------------------------------------------------------- the engine chosen in Settings

@dataclass(frozen=True)
class EngineSpec:
    label: str
    kind: str                 # "subscription" | "api"
    model_setting: str | None  # the settings key holding this engine's model
    default_model: str | None
    provider: str | None = None  # apikey provider for API engines


ENGINES: dict[str, EngineSpec] = {
    "claude-cli": EngineSpec("Claude Code", "subscription", None, None),
    "codex-cli": EngineSpec("Codex (ChatGPT)", "subscription", "codex_model", None),
    "anthropic-api": EngineSpec("Anthropic API", "api", "api_model", DEFAULT_API_MODEL, "anthropic"),
    "openai-api": EngineSpec("OpenAI API", "api", "openai_model", DEFAULT_OPENAI_MODEL, "openai"),
    "openrouter-api": EngineSpec("OpenRouter", "api", "openrouter_model", DEFAULT_OPENROUTER_MODEL, "openrouter"),
}


class SwitchingEngine:
    """The engine chosen in Settings → AI engine, looked up on every call (so switching takes effect
    without a restart)."""

    def __init__(self, store):
        self.store = store
        self._engines: dict[tuple, Engine] = {}

    def current(self) -> Engine:
        settings = self.store.settings()
        engine_id = settings.get("ai_engine")
        if engine_id not in ENGINES:
            engine_id = "claude-cli"
        spec = ENGINES[engine_id]
        model = (settings.get(spec.model_setting) if spec.model_setting else None) or spec.default_model
        zdr = bool(settings.get("openrouter_zdr", True))
        key = (engine_id, model, zdr if engine_id == "openrouter-api" else None)
        if key not in self._engines:
            self._engines[key] = {
                "claude-cli": lambda: ClaudeCLIEngine(),
                "codex-cli": lambda: CodexCLIEngine(model=model),
                "anthropic-api": lambda: AnthropicAPIEngine(model=model),
                "openai-api": lambda: OpenAIAPIEngine(model=model),
                "openrouter-api": lambda: OpenRouterEngine(model=model, zdr=zdr),
            }[engine_id]()
        return self._engines[key]

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
