"""OS differences: locks, read-only folders, reserved names, the Windows claude.cmd wrapper."""

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
    cmd.write_text("@echo off")
    script.write_text("")
    monkeypatch.setattr(engine.shutil, "which", lambda name: "C:/node/node.exe" if name == "node" else None)
    assert engine._windows_command(str(cmd)) == ["C:/node/node.exe", str(script)]
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
