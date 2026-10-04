"""OS differences: locks, read-only folders, reserved names, the Windows claude.cmd wrapper."""

import os
import stat
import threading
import time
from pathlib import Path

import pytest

from autocv import engine, oscompat
from autocv.store import slug


def test_rmtree_removes_read_only_files(tmp_path):
    folder = tmp_path / "sent" / "copy"
    folder.mkdir(parents=True)
    f = folder / "resume.pdf"
    f.write_bytes(b"x")
    f.chmod(stat.S_IREAD)  # sent copies are read-only (Windows then refuses a plain rmtree)
    oscompat.rmtree(tmp_path / "sent")
    assert not (tmp_path / "sent").exists()


def test_file_lock_is_exclusive(tmp_path):
    order = []

    def hold(name):
        with oscompat.FileLock(tmp_path / ".lock"):
            order.append(f"{name}+")
            time.sleep(0.2)
            order.append(f"{name}-")

    with oscompat.FileLock(tmp_path / ".lock"):
        t = threading.Thread(target=hold, args=("b",))
        t.start()
        time.sleep(0.1)
        order.append("a-")
    t.join()
    assert order == ["a-", "b+", "b-"]


@pytest.mark.parametrize("name, expected", [("Con", "con-co"), ("COM1", "com1-co"), ("Nul", "nul-co"),
                                            ("Console", "console"), ("Acme Bank", "acme-bank")])
def test_windows_reserved_names_never_become_folder_names(name, expected):
    assert slug(name) == expected


def test_windows_claude_cmd_runs_its_script_with_node(tmp_path, monkeypatch):
    monkeypatch.setattr(oscompat, "IS_WINDOWS", True)
    cmd = tmp_path / "npm" / "claude.cmd"
    script = tmp_path / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    script.parent.mkdir(parents=True)
    cmd.write_text("@echo off", encoding="utf-8")
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr(engine, "find_node", lambda: "C:/node/node.exe")
    assert engine._windows_command(str(cmd)) == ["C:/node/node.exe", str(script)]  # older Claude Code: cli.js
    assert engine._windows_command("C:/claude/claude.exe") == ["C:/claude/claude.exe"]
    script.unlink()
    with pytest.raises(engine.EngineError, match="claude.exe"):
        engine._windows_command(str(cmd))


def test_reveal_command_per_os(monkeypatch, tmp_path):
    target = tmp_path / "Résumé file.pdf"
    monkeypatch.setattr(oscompat, "IS_MAC", True)
    assert oscompat.reveal_command(target, tmp_path) == ["open", "-R", str(target)]
    monkeypatch.setattr(oscompat, "IS_MAC", False)
    monkeypatch.setattr(oscompat, "IS_WINDOWS", True)
    assert oscompat.reveal_command(target, tmp_path) == f'explorer /select,"{target}"'
    monkeypatch.setattr(oscompat, "IS_WINDOWS", False)
    monkeypatch.setattr(oscompat.shutil, "which", lambda name: None)
    assert oscompat.reveal_command(target, tmp_path) == ["xdg-open", str(tmp_path)]
    monkeypatch.setattr(oscompat.shutil, "which", lambda name: "/usr/bin/dbus-send")
    cmd = oscompat.reveal_command(target, tmp_path)
    assert cmd[0] == "dbus-send" and f"array:string:{Path(target).resolve().as_uri()}" in cmd


def test_reads_retry_while_windows_has_the_file_mid_replace(tmp_path, monkeypatch):
    """On Windows, opening a file another thread is replacing raises PermissionError for a moment."""
    from autocv import oscompat
    f = tmp_path / "profile.yaml"
    f.write_bytes(b"a: 1\r\nb: 2\r")  # exact bytes on every OS (text mode would add \r on Windows)
    real, calls = Path.read_bytes, {"n": 0}

    def flaky(self):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(13, "Permission denied")
        return real(self)
    monkeypatch.setattr(oscompat, "IS_WINDOWS", True)
    monkeypatch.setattr(oscompat.time, "sleep", lambda s: None)
    monkeypatch.setattr(Path, "read_bytes", flaky)
    assert oscompat.read_text(f) == "a: 1\nb: 2\n" and calls["n"] == 3
    monkeypatch.setattr(oscompat, "IS_WINDOWS", False)  # elsewhere it's a real error
    calls["n"] = 0
    with pytest.raises(PermissionError):
        oscompat.read_bytes(f)


def _shim(folder, name, target_rel, node_runs=False):
    """A Windows .cmd shim like npm writes: runs %dp0%\\<target> (with node first for scripts)."""
    folder.mkdir(parents=True, exist_ok=True)
    win_rel = target_rel.replace("/", "\\")
    body = (f'@ECHO off\r\nSET dp0=%~dp0\r\n"%_prog%"  "%dp0%\\{win_rel}" %*\r\n' if node_runs
            else f'@ECHO off\r\n"%dp0%\\{win_rel}"   %*\r\n')
    (folder / name).write_text(body, encoding="utf-8")
    target = folder / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("", encoding="utf-8")
    return folder / name, target


def test_windows_npm_claude_runs_its_native_exe(tmp_path, monkeypatch):
    """Claude Code's npm package now ships bin/claude.exe (no cli.js): run it directly."""
    monkeypatch.setattr(oscompat, "IS_WINDOWS", True)
    cmd, exe = _shim(tmp_path / "npm", "claude.cmd", "node_modules/@anthropic-ai/claude-code/bin/claude.exe")
    assert engine._windows_command(str(cmd)) == [str(exe.resolve())]


def test_windows_pnpm_shim_runs_its_script_with_node(tmp_path, monkeypatch):
    monkeypatch.setattr(oscompat, "IS_WINDOWS", True)
    cmd, js = _shim(tmp_path / "pnpm", "codex.cmd", "global/5/node_modules/@openai/codex/bin/codex.js", node_runs=True)
    monkeypatch.setattr(engine, "find_node", lambda: "C:/node/node.exe")
    assert engine._windows_command(str(cmd), "codex") == ["C:/node/node.exe", str(js.resolve())]
    monkeypatch.setattr(engine, "find_node", lambda: None)
    with pytest.raises(engine.EngineError, match="needs Node.js"):
        engine._windows_command(str(cmd), "codex")


def test_cli_env_puts_the_cli_and_node_first_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "find_node", lambda: str(tmp_path / "node" / "bin" / "node"))
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    env = engine.cli_env(str(tmp_path / "brew" / "bin" / "codex"))
    parts = env["PATH"].split(os.pathsep)
    assert parts[0] == str(tmp_path / "brew" / "bin") and str(tmp_path / "node" / "bin") in parts and parts[-1] == "/usr/bin"
    assert "CLAUDE_CODE_USE_BEDROCK" not in env
