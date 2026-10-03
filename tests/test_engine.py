"""The CLI engine runs fully isolated and parses structured output (fake `claude` binary)."""

import asyncio
import json
import sys

import pytest

from autocv.engine import ClaudeCLIEngine, EngineError

FAKE = """
import json, os, sys
args = sys.argv[1:]
prompt = sys.stdin.read()
system = open(args[args.index("--system-prompt-file") + 1], encoding="utf-8").read() if "--system-prompt-file" in args else None
json.dump({{"args": args, "cwd_files": os.listdir("."), "prompt": prompt, "system": system}}, open({log!r}, "w"))
if os.environ.get("FAKE_MODE") == "error":
    print(json.dumps({{"is_error": True, "result": "Failed to authenticate"}}))
else:
    print(json.dumps({{"is_error": False, "structured_output": {{"status": "OK"}}}}))
"""


@pytest.fixture
def fake_claude(tmp_path):
    log = tmp_path / "call.json"
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE.format(log=str(log)), encoding="utf-8")
    return [sys.executable, str(script)], log  # runs the same on every OS (no shebang/chmod)


def test_engine_runs_isolated_and_returns_structured_output(fake_claude):
    binary, log = fake_claude
    out = asyncio.run(ClaudeCLIEngine(command=binary).complete("SYS", "TASK: x\nsecret profile", {"type": "object"}))
    assert out == {"status": "OK"}
    call = json.loads(log.read_text(encoding="utf-8"))
    args = call["args"]
    for flag in ("--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
        assert flag in args
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--setting-sources") + 1] == "project"
    assert json.loads(args[args.index("--settings") + 1]) == {"disableAllHooks": True}
    assert call["cwd_files"] == []                       # empty working directory: no CLAUDE.md
    assert "secret profile" not in " ".join(args)        # the prompt goes over stdin, not argv
    assert call["prompt"].endswith("secret profile")
    assert call["system"] == "SYS"                       # system prompt from a file, not the command line
    assert "SYS" not in args


def test_engine_surfaces_cli_errors(fake_claude, monkeypatch):
    binary, _ = fake_claude
    monkeypatch.setenv("FAKE_MODE", "error")
    with pytest.raises(EngineError, match="Failed to authenticate"):
        asyncio.run(ClaudeCLIEngine(command=binary).complete("SYS", "TASK: x", {}))
