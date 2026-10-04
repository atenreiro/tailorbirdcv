"""The Codex CLI engine (ChatGPT subscription): runs locked down, reads the schema-shaped answer, never sees an
API key, and reports its login status (a fake `codex` script stands in for the real one)."""

import asyncio
import json
import sys

import pytest

from autocv import doctor
from autocv.engine import CODEX_ISOLATION, CodexCLIEngine, EngineError

FAKE = """
import json, os, sys, time
args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "")
if args[:2] == ["login", "status"]:
    if mode == "nonode":
        print("env: node: No such file or directory", file=sys.stderr); sys.exit(127)
    msg = {{"": "Logged in using ChatGPT", "key": "Logged in using an API key - sk-...", "out": "Not logged in"}}[mode if mode in ("key", "out") else ""]
    print(msg, file=sys.stderr); sys.exit(1 if mode == "out" else 0)
prompt = sys.stdin.read()
cfg = [args[i + 1] for i, a in enumerate(args) if a == "-c"]
instr = next(c.split("=", 1)[1] for c in cfg if c.startswith("model_instructions_file="))
schema_path = args[args.index("--output-schema") + 1]
json.dump({{"args": args, "cwd_files": os.listdir("."), "prompt": prompt,
           "system": open(json.loads(instr), encoding="utf-8").read(),
           "schema": json.load(open(schema_path, encoding="utf-8")),
           "keys": [k for k in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY") if os.environ.get(k)]}},
          open({log!r}, "w"))
if mode == "fail":
    print(json.dumps({{"type": "turn.failed", "error": {{"message": "usage limit reached"}}}})); sys.exit(1)
if mode == "slow":
    time.sleep(30)
out = args[args.index("-o") + 1]
open(out, "w", encoding="utf-8").write(json.dumps({{"status": "OK", "note": None}}))
print(json.dumps({{"type": "turn.completed"}}))
"""


@pytest.fixture
def fake_codex(tmp_path):
    log = tmp_path / "call.json"
    script = tmp_path / "fake_codex.py"
    script.write_text(FAKE.format(log=str(log)), encoding="utf-8")
    return [sys.executable, str(script)], log


SCHEMA = {"type": "object", "properties": {"status": {"type": "string"}, "note": {"type": "string"}},
          "required": ["status"]}


def test_codex_runs_locked_down_and_returns_the_answer(fake_codex, monkeypatch):
    command, log = fake_codex
    for var in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(var, "sk-should-not-reach-codex")
    out = asyncio.run(CodexCLIEngine(command=command, model="gpt-6.1-sol").complete("SYS", "TASK: x\nsecret profile", SCHEMA))
    assert out == {"status": "OK"}                     # the null optional is dropped
    call = json.loads(log.read_text(encoding="utf-8"))
    args = call["args"]
    assert args[:2] == ["exec", "-"] and args[args.index("-m") + 1] == "gpt-6.1-sol"
    for flag in ("--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules"):
        assert flag in args
    assert args[args.index("-s") + 1] == "read-only"
    cfg = {c.split("=", 1)[0]: c.split("=", 1)[1] for i, c in enumerate(args) if i and args[i - 1] == "-c"}
    assert cfg["approval_policy"] == '"never"' and cfg["web_search"] == '"disabled"' and cfg["mcp_servers"] == "{}"
    for feature in ("shell_tool", "unified_exec", "browser_use", "computer_use", "image_generation", "plugins"):
        assert cfg[f"features.{feature}"] == "false"
    assert call["cwd_files"] == []                     # empty working directory: no AGENTS.md
    assert "secret profile" not in " ".join(args) and call["prompt"].endswith("secret profile")
    assert call["system"] == "SYS" and "SYS" not in args
    assert call["schema"]["required"] == ["status", "note"]  # strict form for --output-schema
    assert call["keys"] == []                          # the ChatGPT login is used, never a key


def test_codex_failures_are_reported(fake_codex, monkeypatch):
    command, _ = fake_codex
    monkeypatch.setenv("FAKE_MODE", "fail")
    with pytest.raises(EngineError, match="usage limit reached"):
        asyncio.run(CodexCLIEngine(command=command).complete("S", "TASK: x", SCHEMA))


def test_codex_timeout_stops_it(fake_codex, monkeypatch):
    command, _ = fake_codex
    monkeypatch.setenv("FAKE_MODE", "slow")
    with pytest.raises(EngineError, match="timed out"):
        asyncio.run(CodexCLIEngine(command=command, timeout=1).complete("S", "TASK: x", SCHEMA))


@pytest.mark.parametrize("mode,ready,needle", [("", True, "ChatGPT"), ("key", False, "API key"),
                                                ("out", False, "codex login"), ("nonode", False, "Node.js")])
def test_codex_login_status(fake_codex, monkeypatch, mode, ready, needle):
    command, _ = fake_codex
    monkeypatch.setenv("FAKE_MODE", mode)
    st = asyncio.run(CodexCLIEngine(command=command).status())
    assert st["ready"] is ready and needle in st["detail"]


def test_isolation_list_is_well_formed():
    flags = [a for i, a in enumerate(CODEX_ISOLATION) if CODEX_ISOLATION[i - 1] == "-c"]
    assert all("=" in f for f in flags) and len(flags) == len(set(flags))


def test_doctor_reports_an_old_codex(monkeypatch):
    monkeypatch.setattr(doctor, "codex_version", lambda binary=None: (0, 120, 0))
    assert doctor._codex("codex-cli")["status"] == "warn"
    monkeypatch.setattr(doctor, "codex_version", lambda binary=None: (0, 160, 0))
    assert doctor._codex("codex-cli")["status"] == "ok"
    assert doctor._codex("claude-cli") is None


def test_codex_refuses_to_run_on_an_api_key_login(fake_codex, monkeypatch):
    command, log = fake_codex
    eng = CodexCLIEngine(command=command)
    eng.command = None  # behave like a real install: check the login first…
    monkeypatch.setattr(CodexCLIEngine, "_argv", lambda self: command)
    monkeypatch.setattr("autocv.engine.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr("autocv.engine.cli_version", lambda binary: (0, 160, 0))
    monkeypatch.setenv("FAKE_MODE", "key")
    with pytest.raises(EngineError, match="API key"):
        asyncio.run(eng.complete("S", "TASK: x", SCHEMA))
    assert not log.exists()  # …and never started the real call


def test_codex_too_old_is_not_ready(fake_codex, monkeypatch):
    command, _ = fake_codex
    eng = CodexCLIEngine(command=command)
    eng.command = None
    monkeypatch.setattr(CodexCLIEngine, "_argv", lambda self: command)
    monkeypatch.setattr("autocv.engine.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr("autocv.engine.cli_version", lambda binary: (0, 100, 0))
    st = asyncio.run(eng.status())
    assert not st["ready"] and "too old" in st["detail"]
