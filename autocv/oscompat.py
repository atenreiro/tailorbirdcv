"""The few things that differ between macOS, Linux and Windows, in one place.

- `FileLock`: an exclusive lock on a file, across processes (fcntl on POSIX, msvcrt on Windows).
- `group_kwargs()` / `kill_tree()`: start a helper in its own process group and kill it together
  with everything it started (Word's or LibreOffice's helpers, the Claude CLI's node process).
- `rmtree()`: delete a folder even when it holds read-only files (Windows refuses otherwise).
- `replace()`: atomic rename that retries briefly while Windows reports the target as in use
  (an antivirus scan or a viewer holding the file).
- `reveal()`: show a file in Finder / Explorer / the file manager.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
PLATFORM = "windows" if IS_WINDOWS else "macos" if IS_MAC else "linux"

if IS_WINDOWS:  # pragma: no cover - exercised on Windows CI
    import msvcrt
else:
    import fcntl
    import signal


class FileLock:
    """`with FileLock(path):` holds an exclusive lock on `path` (created if needed)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._file = None

    def __enter__(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "a+b")  # noqa: SIM115 - closed in __exit__
        if IS_WINDOWS:  # pragma: no cover
            while True:
                try:
                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.1)
        else:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc) -> None:
        try:
            if IS_WINDOWS:  # pragma: no cover
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()


def group_kwargs() -> dict:
    """Popen / create_subprocess_exec arguments that start the child in its own process group."""
    if IS_WINDOWS:  # pragma: no cover
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(pid: int) -> None:
    """Kill a process started with group_kwargs() and everything it started."""
    if IS_WINDOWS:  # pragma: no cover
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, check=False)
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _writable_then_retry(func, path, _exc) -> None:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    func(path)


def rmtree(path: Path, ignore_errors: bool = False) -> None:
    """shutil.rmtree that also removes read-only files (sent copies are read-only on purpose)."""
    if ignore_errors:
        shutil.rmtree(path, ignore_errors=True)
    elif sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_writable_then_retry)
    else:  # pragma: no cover - Python 3.11
        shutil.rmtree(path, onerror=_writable_then_retry)


def replace(src: str | Path, dst: str | Path, attempts: int = 20) -> None:
    """os.replace, retried for up to ~2 s while Windows reports the target as in use."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if not IS_WINDOWS or i == attempts - 1:
                raise
            time.sleep(0.1)  # pragma: no cover


def read_bytes(path: str | Path, attempts: int = 20) -> bytes:
    """Path.read_bytes, retried for up to ~2 s while Windows refuses to open a file that another
    thread is replacing at that moment (a read that races `replace` gets "Permission denied")."""
    for i in range(attempts):
        try:
            return Path(path).read_bytes()
        except PermissionError:
            if not IS_WINDOWS or i == attempts - 1:
                raise
            time.sleep(0.1)  # pragma: no cover
    raise AssertionError("unreachable")  # pragma: no cover


def read_text(path: str | Path) -> str:
    """UTF-8 text through `read_bytes` (same retry); newlines normalised like open() in text mode
    (\r\n and a lone \r both become \n)."""
    return read_bytes(path).decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def reveal_command(target: Path | None, folder: Path) -> list[str] | str:
    """The command that shows `target` selected in its folder (or just opens `folder`)."""
    if IS_MAC:
        return ["open", "-R", str(target)] if target else ["open", str(folder)]
    if IS_WINDOWS:  # pragma: no cover
        # One command string: explorer needs the path quoted *after* "/select,".
        return f'explorer /select,"{target}"' if target else ["explorer", str(folder)]
    if target and shutil.which("dbus-send"):  # most Linux file managers can highlight the file
        return ["dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.FileManager1",
                "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1.ShowItems",
                f"array:string:{target.resolve().as_uri()}", "string:"]
    return ["xdg-open", str(folder)]


def reveal(target: Path | None, folder: Path) -> None:
    """Show the file in Finder / Explorer / the file manager. Raises OSError if that fails."""
    cmd = reveal_command(target, folder)
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=10, check=False)
    except subprocess.TimeoutExpired as e:
        raise OSError("the file manager didn't respond") from e
    # explorer.exe returns 1 even on success; a failed D-Bus call falls back to opening the folder.
    if done.returncode and not IS_WINDOWS:
        if isinstance(cmd, list) and cmd[0] == "dbus-send":
            fallback = subprocess.run(["xdg-open", str(folder)], capture_output=True, timeout=10, check=False)
            if fallback.returncode == 0:
                return
        detail = (done.stderr or b"").decode(errors="replace").strip()
        raise OSError(detail or f"{cmd[0] if isinstance(cmd, list) else 'explorer'} exited {done.returncode}")
