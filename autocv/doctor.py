"""`autocv doctor`: what AutoCV needs on this machine, what's missing, and how to fix it.

Shared by the CLI and the Settings page (`GET /api/doctor`). Nothing here changes anything.
Each check is {id, label, status: ok | warn | error, detail, fix}.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from . import paths, pdf
from .engine import Engine
from .oscompat import IS_MAC, IS_WINDOWS


def _check(id_: str, label: str, status: str, detail: str, fix: str = "") -> dict:
    return {"id": id_, "label": label, "status": status, "detail": detail, "fix": fix}


def _data(private: Path) -> dict:
    try:
        private.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=private, prefix=".doctor-"):
            pass
    except OSError as e:
        return _check("data", "Data folder", "error", f"{private} isn't writable ({e}).",
                      "Set AUTOCV_PRIVATE to a folder you can write to.")
    return _check("data", "Data folder", "ok", str(private))


def _profile(private: Path) -> dict:
    if (private / "profile.yaml").is_file():
        return _check("profile", "Master profile", "ok", "Found.")
    return _check("profile", "Master profile", "warn", "Not created yet.",
                  "Open AutoCV and import your resume (or start a blank profile).")


async def _engine(engine: Engine) -> dict:
    try:
        st = await engine.status()
    except Exception as e:  # noqa: BLE001 — a status check must never crash the report
        return _check("ai", "AI engine", "error", str(e), "Check Settings → AI engine.")
    if st.get("ready"):
        model = f" · {st['model']}" if st.get("model") else ""
        return _check("ai", "AI engine", "ok", f"{st.get('engine')}{model}: {st.get('detail', 'ready')}")
    fix = {
        "claude-cli": "Install Claude Code and log in (`claude`, then /login), or choose another engine or an API key in Settings.",
        "codex-cli": "Install Codex (`npm i -g @openai/codex`) and sign in with ChatGPT (`codex login`), "
                     "or choose another engine in Settings.",
    }.get(st.get("engine")) or ("Add or fix the API key in Settings → AI engine." if "key" in (st.get("detail") or "").lower()
                                else "Check the model and your connection in Settings → AI engine, or choose another engine.")
    return _check("ai", "AI engine", "error", st.get("detail") or "Not ready.", fix)


def codex_version(binary: str | None = None) -> tuple[int, ...] | None:
    """Codex CLI's version (e.g. (0, 160, 0)), or None when it isn't installed or doesn't say."""
    from .engine import cli_version, find_cli
    exe = binary or os.environ.get("AUTOCV_CODEX_BIN") or find_cli("codex")
    return cli_version(exe) if exe else None


def _codex(engine_name: str | None) -> dict | None:
    """Only when Codex is the chosen engine: its flags change between versions."""
    from .engine import CODEX_MIN_VERSION
    if engine_name != "codex-cli":
        return None
    version = codex_version()
    if version is None:
        return None  # the AI engine check already says it's missing
    shown = ".".join(map(str, version))
    if version[:2] < CODEX_MIN_VERSION:
        return _check("codex", "Codex CLI version", "warn", f"Codex {shown} is older than AutoCV was tested with.",
                      "Update it: `npm i -g @openai/codex` (or your installer's update command).")
    return _check("codex", "Codex CLI version", "ok", f"Codex {shown}.")


def _pdf(preferred: str | None) -> dict:
    engines = pdf.detect()
    try:
        chosen = pdf.resolve(preferred, engines)
    except RuntimeError:
        hint = ("Install LibreOffice with your package manager (e.g. libreoffice-writer)."
                if not (IS_MAC or IS_WINDOWS) else "Install Microsoft Word, or LibreOffice (free, libreoffice.org).")
        return _check("pdf", "PDF engine", "error", "Neither Microsoft Word nor LibreOffice was found; "
                      "only the .docx can be built.", hint)
    found = ", ".join(f"{e['name']}{' ' + e['version'] if e['version'] else ''}" for e in engines if e["available"])
    lo = next((e for e in engines if e["id"] == "libreoffice"), {})
    if chosen == "libreoffice" and "/snap/" in (lo.get("path") or ""):
        return _check("pdf", "PDF engine", "warn", f"Using LibreOffice from a Snap (found: {found}). Snaps can't read "
                      "hidden folders such as AutoCV's data folder, so PDFs may fail.",
                      "Install LibreOffice from your distribution's packages (e.g. apt install libreoffice-writer), "
                      "or set AUTOCV_PRIVATE to a non-hidden folder.")
    return _check("pdf", "PDF engine", "ok", f"Using {pdf.NAMES[chosen]} (found: {found}).")


def _fonts(preferred: str | None) -> dict:
    try:
        chosen = pdf.resolve(preferred)
    except RuntimeError:
        chosen = None
    if chosen != "libreoffice":
        return _check("fonts", "Resume fonts", "ok", "Word brings its own fonts." if chosen else "No PDF engine yet.")
    missing = [f for f in ("Georgia", "Calibri") if not pdf.installed(f)]
    if not missing:
        return _check("fonts", "Resume fonts", "ok", "Georgia and Calibri are installed.")
    stand_ins = ", ".join(f"{f} → {pdf.SUBSTITUTES[f]}" for f in missing)
    return _check("fonts", "Resume fonts", "ok",
                  f"Using free look-alikes with identical letter widths ({stand_ins}), so page breaks match Word's.")


def browser_installed() -> bool:
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    caches = [Path(base)] if base and base != "0" else [
        Path.home() / "Library" / "Caches" / "ms-playwright", Path.home() / ".cache" / "ms-playwright",
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"]
    return any(list(c.glob("chromium*")) for c in caches if c.is_dir())


def _browser() -> dict:
    if browser_installed():
        return _check("browser", "Headless browser", "ok", "Installed (for job pages that need JavaScript).")
    return _check("browser", "Headless browser", "warn",
                  "Not installed: job pages that only render with JavaScript can't be fetched (paste the text instead).",
                  "Run `autocv install-browser` (about 100 MB).")


def _web() -> dict:
    if paths.web_dir():
        return _check("web", "Web interface", "ok", "Built.")
    return _check("web", "Web interface", "error", "Not built: only the API is served.",
                  "Run `npm --prefix web ci && npm --prefix web run build` in the source folder.")


async def run_checks(engine: Engine, private: Path, preferred_pdf: str | None) -> list[dict]:
    import asyncio

    def local() -> list[dict]:  # file system and app detection (mdfind, font folders): off the event loop
        return [_data(private), _profile(private), _pdf(preferred_pdf), _fonts(preferred_pdf), _browser(), _web()]
    ai_check, others = await asyncio.gather(_engine(engine), asyncio.to_thread(local))
    codex = await asyncio.to_thread(_codex, getattr(engine, "name", None))
    return [*others[:2], ai_check, *([codex] if codex else []), *others[2:]]


def render(checks: list[dict]) -> str:
    mark = {"ok": "✓", "warn": "!", "error": "✗"}
    lines = [f"AutoCV {version()} · Python {sys.version.split()[0]} · {sys.platform}"]
    for c in checks:
        lines.append(f"  {mark[c['status']]} {c['label']}: {c['detail']}")
        if c["fix"] and c["status"] != "ok":
            lines.append(f"      → {c['fix']}")
    return "\n".join(lines)


def version() -> str:
    from importlib.metadata import PackageNotFoundError, version as pkg_version
    try:
        return pkg_version("autocv-app")
    except PackageNotFoundError:
        return "dev"
