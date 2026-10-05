"""Is a newer AutoCV out, and upgrading to it.

The version is the repo's VERSION file; bumping it on main publishes that version to PyPI (release.yml). The app
asks PyPI (and only PyPI) for the latest version: at most once a day, and never when Settings → "Check for updates"
is off. Installs made by the one-line installer (`uv tool`) can upgrade with one click: the server stops, `uv tool
upgrade autocv-app` runs, and AutoCV starts again on the same port (cli.restart_after_upgrade). Checkouts and other
installs get the command to run instead.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import sys
from pathlib import Path

PACKAGE = "autocv-app"
PYPI_URL = "https://pypi.org/pypi/autocv-app/json"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
CHECK_EVERY = dt.timedelta(hours=24)
TIMEOUT = 5.0

COMMANDS = {  # how to upgrade by hand, per install kind (None: the Upgrade button does it)
    "uv-tool": None,
    "uv-tool-local": "uv tool install --upgrade autocv-app",  # installed from a file: switch to PyPI's
    "checkout": "git pull --ff-only && uv sync && npm --prefix web run build, then restart autocv serve",
    "other": "Upgrade it the way you installed it, e.g. uv tool upgrade autocv-app or pipx upgrade autocv-app",
}


def current() -> str:
    from .doctor import version
    return version()


def parse(version: str | None) -> tuple[int, int, int] | None:
    if not version or not VERSION_RE.match(version):
        return None
    a, b, c = version.split(".")
    return int(a), int(b), int(c)


def newer(latest: str | None, installed: str | None) -> bool:
    """`latest` is a later release than `installed` (never true for a "dev" or unreadable version)."""
    lt, cur = parse(latest), parse(installed)
    return bool(lt and cur and lt > cur)


def install_kind(prefix: str | Path | None = None) -> str:
    """"uv-tool" (one-line installer, from PyPI: one-click upgrades), "uv-tool-local" (uv tool, but from a file),
    "checkout" (a git clone run with `uv run`) or "other" (pip, pipx…)."""
    import tomllib

    from . import paths
    receipt = Path(prefix or sys.prefix) / "uv-receipt.toml"
    if receipt.is_file():
        try:
            data = tomllib.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        reqs = [r for r in (data.get("tool") or {}).get("requirements") or []
                if isinstance(r, dict) and r.get("name") == PACKAGE]
        if reqs:
            local = any(k in r for r in reqs for k in ("path", "url", "git", "directory", "editable"))
            return "uv-tool-local" if local else "uv-tool"
    return "checkout" if paths.is_checkout() else "other"


def find_uv() -> str | None:
    """The uv that installed AutoCV: on the PATH, or where the installers put it."""
    found = shutil.which("uv")
    if found:
        return found
    exe = "uv.exe" if os.name == "nt" else "uv"
    homes = [os.environ.get("XDG_BIN_HOME"), Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin"]
    for d in homes:
        if d and (Path(d) / exe).is_file():
            return str(Path(d) / exe)
    return None


def upgrade_command(uv: str) -> list[str]:
    return [uv, "tool", "upgrade", PACKAGE]


def upgrade_env() -> dict:
    """The installer's uv settings: uv-managed Pythons only, and the system's certificates (company proxies)."""
    env = dict(os.environ)
    env.setdefault("UV_SYSTEM_CERTS", "1")
    env.setdefault("UV_NATIVE_TLS", "1")
    env["UV_MANAGED_PYTHON"] = "1"
    return env


# ---------------------------------------------------------------------------------------- the update.json cache
def _path(private: Path) -> Path:
    return private / "update.json"


def load(private: Path) -> dict:
    try:
        data = json.loads(_path(private).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(private: Path, data: dict) -> None:
    from .store import _write_json_atomic
    private.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(_path(private), data)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _stale(checked_at: str | None) -> bool:
    try:
        return _now() - dt.datetime.fromisoformat(checked_at) > CHECK_EVERY  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True


def _ssl_context():
    try:
        import ssl

        import truststore  # the OS trust store: works behind company proxies that inspect HTTPS
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return True


async def fetch_latest(transport=None) -> str:
    """The latest release on PyPI. Raises on any problem (network, odd answer)."""
    import httpx
    url = os.environ.get("AUTOCV_UPDATE_URL") or PYPI_URL  # tests and the end-to-end check only
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=True, verify=_ssl_context(), transport=transport,
                                 follow_redirects=False,
                                 headers={"User-Agent": f"AutoCV/{current()}", "Accept": "application/json"}) as c:
        r = await c.get(url)
    r.raise_for_status()
    body = r.json()
    info = body.get("info") if isinstance(body, dict) else None
    version = str((info or {}).get("version") or "").strip()
    if not VERSION_RE.match(version):
        raise ValueError("PyPI's answer has no usable version")
    return version


async def refresh(private: Path, enabled: bool, force: bool = False, transport=None) -> dict:
    """The cache, refetched when it's older than a day (or `force`). Never fetches when checks are off."""
    cache = load(private)
    if enabled and (force or _stale(cache.get("checked_at"))):
        try:
            latest = await fetch_latest(transport)
            cache, cache["latest"], cache["error"] = load(private), latest, None  # re-read: keep pending/last_upgrade
        except Exception as e:  # noqa: BLE001 — offline, proxy, PyPI down: say so quietly, keep the last answer
            cache = load(private)
            cache["error"] = f"Couldn't reach PyPI ({type(e).__name__})."
        cache["checked_at"] = _now().isoformat(timespec="seconds")
        save(private, cache)
    return cache


def view(private: Path, enabled: bool, cache: dict | None = None) -> dict:
    cache = load(private) if cache is None else cache
    installed, kind = current(), install_kind()
    latest = cache.get("latest") if enabled else None
    return {"enabled": enabled, "current": installed, "latest": latest, "newer": newer(latest, installed),
            "kind": kind, "command": COMMANDS.get(kind), "checked_at": cache.get("checked_at") if enabled else None,
            "error": cache.get("error") if enabled else None, "last_upgrade": cache.get("last_upgrade")}


# ------------------------------------------------------------------------------------- around a restart
def mark_pending(private: Path, target: str) -> None:
    cache = load(private)
    cache["pending"] = {"target": target, "from": current(), "at": _now().isoformat(timespec="seconds")}
    cache.pop("last_upgrade", None)
    save(private, cache)


def settle(private: Path) -> None:
    """On start: did the upgrade that restarted us take? Records `last_upgrade` for the UI."""
    cache = load(private)
    pending = cache.pop("pending", None)
    if not isinstance(pending, dict):
        return
    target, installed = pending.get("target"), current()
    ok = installed == target or newer(installed, target)
    cache["last_upgrade"] = {"target": target, "ok": ok, "at": _now().isoformat(timespec="seconds"),
                             "error": None if ok else f"AutoCV {installed} is still running; the upgrade log says why."}
    save(private, cache)


def log_path(private: Path) -> Path:
    return private / "update" / "last-upgrade.log"


WINDOWS_SCRIPT = r"""# AutoCV upgrade helper, written by AutoCV. Every value comes from an environment variable.
$ErrorActionPreference = 'Continue'
$Host.UI.RawUI.WindowTitle = 'AutoCV'
Write-Host "Upgrading AutoCV to $env:AUTOCV_UPGRADE_TARGET..."
foreach ($id in @($env:AUTOCV_UPGRADE_PID, $env:AUTOCV_UPGRADE_PPID)) {
    if ($id) { Wait-Process -Id ([int]$id) -Timeout 30 -ErrorAction SilentlyContinue }
}
Start-Sleep -Seconds 1
& $env:AUTOCV_UPGRADE_UV tool upgrade autocv-app *>&1 | Tee-Object -FilePath $env:AUTOCV_UPGRADE_LOG
if ($LASTEXITCODE -eq 0) { Write-Host 'Upgraded.' }
else { Write-Host "The upgrade failed (exit code $LASTEXITCODE): starting the version you had." -ForegroundColor Red }
& $env:AUTOCV_UPGRADE_AUTOCV serve --port ([int]$env:AUTOCV_UPGRADE_PORT) --no-browser
"""
