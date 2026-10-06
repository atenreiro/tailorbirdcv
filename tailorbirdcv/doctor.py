"""`tailorbirdcv doctor`: what TailorbirdCV needs on this machine, what's missing, and how to fix it.

Shared by the CLI, the Settings page and the setup wizard (`GET /api/doctor`, `?phase=setup` for the
wizard's "Your computer" step). Nothing here changes anything.
Each check is {id, label, status: ok | warn | error, detail, fix, level, action?, items?}:
- level: how much it matters, independent of status — "required" | "recommended" | "optional" | "info";
- action: what the UI can offer — {"kind": "install-browser" | "test-pdf" | "test-ai" | "settings", "label"};
- items: sub-rows (the AI options: each engine's state).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths, pdf
from .engine import Engine
from .oscompat import IS_MAC, IS_WINDOWS


# How to install Codex here: Homebrew on macOS (npm -g often fails there with EACCES), npm elsewhere.
CODEX_INSTALL = "brew install --cask codex" if IS_MAC else "npm i -g @openai/codex"


def _check(id_: str, label: str, status: str, detail: str, fix: str = "", level: str = "required",
           action: dict | None = None, items: list[dict] | None = None) -> dict:
    out = {"id": id_, "label": label, "status": status, "detail": detail, "fix": fix, "level": level}
    if action:
        out["action"] = action
    if items is not None:
        out["items"] = items
    return out


def _writable(folder: Path) -> bool:
    """Can TailorbirdCV create files here? On Windows os.access ignores permissions (ACLs, Controlled Folder Access),
    so try it with a temporary file that's removed at once."""
    if not IS_WINDOWS:
        return os.access(folder, os.W_OK)
    import tempfile  # pragma: no cover
    try:  # pragma: no cover
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".tailorbirdcv-check-"):
            return True
    except OSError:  # pragma: no cover
        return False


def _data(private: Path) -> dict:
    target = next((p for p in [private, *private.parents] if p.exists()), None)
    if target is None or not _writable(target):
        return _check("data", "Data folder", "error", f"{private} isn't writable.",
                      "Set TAILORBIRDCV_PRIVATE to a folder you can write to, then restart TailorbirdCV.")
    if IS_WINDOWS and not _private_by_default(private):  # pragma: no cover
        return _check("data", "Data folder", "warn", f"{private} — outside your user folders, so other accounts on "
                      "this PC may be able to read it.", "Unless you need it there, leave TAILORBIRDCV_PRIVATE unset (TailorbirdCV "
                      "then uses your private AppData folder).", level="recommended")
    return _check("data", "Data folder", "ok", str(private))


def _private_by_default(folder: Path) -> bool:  # pragma: no cover - Windows only
    """Under the user's own profile (where Windows gives other accounts no access by default)."""
    try:
        return folder.resolve().is_relative_to(Path.home().resolve())
    except OSError:
        return True


def _profile(private: Path) -> dict:
    if (private / "profile.yaml").is_file():
        return _check("profile", "Master profile", "ok", "Found.")
    return _check("profile", "Master profile", "warn", "Not created yet.",
                  "Open TailorbirdCV and import your resume (or start a blank profile).", level="info")


async def _engine(engine: Engine) -> dict:
    try:
        st = await engine.status()
    except Exception as e:  # noqa: BLE001 — a status check must never crash the report
        return _check("ai", "AI engine", "error", str(e), "Check Settings → AI engine.",
                      action={"kind": "settings", "label": "AI settings"})
    if st.get("ready"):
        model = f" · {st['model']}" if st.get("model") else ""
        return _check("ai", "AI engine", "ok", f"{st.get('engine')}{model}: {st.get('detail', 'ready')}",
                      action={"kind": "test-ai", "label": "Test AI"})
    fix = {
        "claude-cli": "Install Claude Code and log in (`claude`, then /login), or choose another engine or an API key in Settings.",
        "codex-cli": f"Install Codex (`{CODEX_INSTALL}`) and sign in with ChatGPT (`codex login`), "
                     "or choose another engine in Settings.",
    }.get(st.get("engine")) or ("Add or fix the API key in Settings → AI engine." if "key" in (st.get("detail") or "").lower()
                                else "Check the model and your connection in Settings → AI engine, or choose another engine.")
    return _check("ai", "AI engine", "error", st.get("detail") or "Not ready.", fix,
                  action={"kind": "settings", "label": "AI settings"})


def codex_version(binary: str | None = None) -> tuple[int, ...] | None:
    """Codex CLI's version (e.g. (0, 160, 0)), or None when it isn't installed or doesn't say."""
    from .engine import cli_version, find_cli
    exe = binary or os.environ.get("TAILORBIRDCV_CODEX_BIN") or find_cli("codex")
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
        return _check("codex", "Codex CLI version", "warn", f"Codex {shown} is older than TailorbirdCV was tested with.",
                      ("Update it: `brew upgrade --cask codex`" if IS_MAC else "Update it: `npm i -g @openai/codex`")
                      + " (or your installer's update command).")
    return _check("codex", "Codex CLI version", "ok", f"Codex {shown}.")


def _pdf(preferred: str | None) -> dict:
    engines = pdf.detect()
    try:
        chosen = pdf.resolve(preferred, engines)
    except RuntimeError:
        hint = ("Install LibreOffice with your package manager (e.g. sudo apt install libreoffice-writer), "
                "then Check again." if not (IS_MAC or IS_WINDOWS) else
                "Install Microsoft Word, or LibreOffice (free, libreoffice.org), then Check again.")
        return _check("pdf", "PDF engine", "error", "Neither Microsoft Word nor LibreOffice was found; "
                      "only the Word document can be built.", hint, level="recommended")
    test = {"kind": "test-pdf", "label": "Test PDF",
            "hint": "" if chosen != "word" else ("Word runs hidden. The first time, look for a macOS prompt to let TailorbirdCV control Word, and for "
                     "Word's “Grant File Access” window (click Select). Word must be activated." if IS_MAC else
                     "Word runs hidden. If Word has never been opened on this PC, open it once, sign in and close "
                     "its first-run prompts." if IS_WINDOWS else "")}
    found = ", ".join(f"{e['name']}{' ' + e['version'] if e['version'] else ''}" for e in engines if e["available"])
    lo = next((e for e in engines if e["id"] == "libreoffice"), {})
    sandboxed = next((k for k in ("/snap/", "/flatpak/") if k in (lo.get("path") or "")), None)
    hidden = any(part.startswith(".") for part in pdf.work_dir().parts)
    if chosen == "libreoffice" and sandboxed and hidden:
        kind = "Snap" if sandboxed == "/snap/" else "Flatpak"
        return _check("pdf", "PDF engine", "warn", f"Using LibreOffice from a {kind} (found: {found}). {kind}s may "
                      "not be able to read hidden folders such as TailorbirdCV's data folder, so PDFs may fail.",
                      "Test PDF to be sure. If it fails, install LibreOffice from your distribution's packages "
                      "(e.g. apt install libreoffice-writer), or set TAILORBIRDCV_PRIVATE to a non-hidden folder.",
                      level="recommended", action=test)
    return _check("pdf", "PDF engine", "ok", f"Using {pdf.NAMES[chosen]} (found: {found}).",
                  "Test PDF converts a sample page now (the first Word run may ask for permissions).",
                  level="recommended", action=test)


def _fonts(preferred: str | None) -> dict:
    try:
        chosen = pdf.resolve(preferred)
    except RuntimeError:
        chosen = None
    if chosen != "libreoffice":
        return _check("fonts", "Resume fonts", "ok", "Word brings its own fonts." if chosen else "No PDF engine yet.",
                      level="info")
    missing = [f for f in ("Georgia", "Calibri") if not pdf.installed(f)]
    if not missing:
        return _check("fonts", "Resume fonts", "ok", "Georgia and Calibri are installed.", level="info")
    stand_ins = ", ".join(f"{f} → {pdf.SUBSTITUTES[f]}" for f in missing)
    return _check("fonts", "Resume fonts", "ok",
                  f"Using free look-alikes with identical letter widths ({stand_ins}), so page breaks match Word's.",
                  level="info")


def _browser_caches() -> list[Path]:
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if base == "0":  # browsers kept inside the playwright package
        try:
            import playwright
            return [Path(playwright.__file__).parent / "driver" / "package" / ".local-browsers"]
        except ImportError:
            return []
    if base:
        return [Path(base)]
    return [Path.home() / "Library" / "Caches" / "ms-playwright", Path.home() / ".cache" / "ms-playwright",
            Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"]


def _chromium_revision() -> str | None:
    """The headless Chromium build this Playwright version runs (from its browsers.json)."""
    import json
    try:
        import playwright
        manifest = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
        browsers = {b["name"]: b["revision"] for b in json.loads(manifest.read_text(encoding="utf-8"))["browsers"]}
        return browsers.get("chromium-headless-shell") or browsers["chromium"]
    except (ImportError, OSError, ValueError, StopIteration, KeyError):
        return None


def browser_installed() -> bool:
    """The exact headless Chromium this Playwright version runs is fully installed (a partial download,
    another version, or only the full Chromium, which headless pages never use, doesn't count)."""
    revision = _chromium_revision()
    names = [f"chromium_headless_shell-{revision}"] if revision else []
    for cache in _browser_caches():
        if not cache.is_dir():
            continue
        if not names:  # unknown Playwright layout: any complete Chromium will do
            if any((d / "INSTALLATION_COMPLETE").exists() for d in cache.glob("chromium_headless_shell*")):
                return True
        elif any((cache / n / "INSTALLATION_COMPLETE").exists() for n in names):
            return True
    return False


def _browser() -> dict:
    action = {"kind": "install-browser", "label": "Install"}
    if browser_installed():
        return _check("browser", "Headless browser", "ok", "Installed (for job pages that need JavaScript).",
                      level="optional")
    linux = "" if (IS_MAC or IS_WINDOWS) else (" On Linux it may also need system libraries: "
                                                 f"sudo {sys.executable} -m playwright install-deps chromium")
    return _check("browser", "Headless browser", "warn",
                  "Not installed: job pages that only render with JavaScript can't be fetched (paste the text instead).",
                  "Install it (about 200 MB), or run `tailorbirdcv install-browser`." + linux, level="optional",
                  action=action)


def _node() -> dict:
    from .engine import find_node
    exe = find_node()
    if not exe:
        return _check("node", "Node.js", "warn", "Not installed.",
                      "Only needed to install Codex with npm (nodejs.org), or to build TailorbirdCV from source.",
                      level="optional")
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return _check("node", "Node.js", "ok", out or "Installed.", level="optional")


def _keychain(needed: bool) -> dict:
    from . import apikey
    st = apikey.backend_status()
    if st["available"]:
        return _check("keychain", "Keychain for API keys", "ok", f"{st['backend']} is available.", level="optional")
    fix = ("Install a Secret Service keychain (GNOME Keyring or KWallet) and log in again, or start TailorbirdCV with the "
           "key in an environment variable, e.g. OPENAI_API_KEY=… tailorbirdcv serve."
           if not (IS_MAC or IS_WINDOWS) else
           'Start TailorbirdCV with the key in an environment variable instead: in PowerShell, $env:ANTHROPIC_API_KEY="…"; '
           "tailorbirdcv serve" if IS_WINDOWS else
           "Start TailorbirdCV with the key in an environment variable instead, e.g. ANTHROPIC_API_KEY=… tailorbirdcv serve.")
    return _check("keychain", "Keychain for API keys", "warn" if needed else "ok",
                  "No system keychain is available, so API keys can't be saved from the app.", fix,
                  level="recommended" if needed else "optional")


async def _ai_options() -> dict:
    """Every way to run the AI on this computer and its state (no paid calls: CLIs report their login,
    API keys are only checked for presence)."""
    from . import apikey
    from .engine import ENGINES, ClaudeCLIEngine, CodexCLIEngine
    claude, codex = await asyncio.gather(ClaudeCLIEngine().status(), CodexCLIEngine().status())
    items = []
    for engine_id, st, install in (("claude-cli", claude, "Install Claude Code, then run claude and /login"),
                                   ("codex-cli", codex, f"{CODEX_INSTALL}, then codex login")):
        missing = "not found" in (st.get("detail") or "").lower()
        items.append({"id": engine_id, "label": ENGINES[engine_id].label,
                      "state": "ready" if st.get("ready") else "missing" if missing else "needs-login",
                      "detail": "Ready — logged in." if st.get("ready") else install if missing else st.get("detail")})
    for engine_id, spec in ENGINES.items():
        if spec.kind != "api":
            continue
        key, source = await asyncio.to_thread(apikey.get, spec.provider)  # may wait on a keychain prompt
        items.append({"id": engine_id, "label": spec.label, "state": "ready" if key else "no-key",
                      "detail": ("Key saved." if source == "keychain" else f"Key from {apikey.PROVIDERS[spec.provider].env}.")
                      if key else "Can't read the keychain (locked, or access denied) — unlock it or allow access, then "
                                  "Check again." if source == "locked" else "No key yet (pay per use)."})
    usable = [i for i in items if i["state"] == "ready"]
    if usable:
        return _check("ai_options", "AI", "ok", f"Ready to use: {', '.join(i['label'] for i in usable)}.",
                      "Choose one in the next step.", level="required", items=items)
    return _check("ai_options", "AI", "warn", "Nothing set up yet. TailorbirdCV needs one of these.",
                  "Install and log in to Claude Code or Codex (your subscription), or add an API key in the next step.",
                  level="required", items=items)


def _web() -> dict:
    if paths.web_dir():
        return _check("web", "Web interface", "ok", "Built.", level="info")
    return _check("web", "Web interface", "error", "Not built: only the API is served.",
                  "Run `npm --prefix web ci && npm --prefix web run build` in the source folder.", level="info")


async def run_checks(engine: Engine, private: Path, preferred_pdf: str | None, phase: str = "all") -> list[dict]:
    """phase "all" (CLI, Settings): everything, with the chosen AI engine. phase "setup" (the wizard's first
    step): what to have or install before starting — every AI option, keychain, PDF, browser, Node."""
    api_engine = getattr(engine, "name", "").endswith("-api")

    if phase == "setup":
        def local_setup() -> list[dict]:
            return [_data(private), _pdf(preferred_pdf), _keychain(needed=True), _browser(), _node()]
        ai, others = await asyncio.gather(_ai_options(), asyncio.to_thread(local_setup))
        return [others[0], ai, *others[1:]]

    def local() -> list[dict]:  # file system and app detection (mdfind, font folders): off the event loop
        return [_data(private), _profile(private), _pdf(preferred_pdf), _fonts(preferred_pdf),
                _keychain(needed=api_engine), _browser(), _web()]
    ai_check, others = await asyncio.gather(_engine(engine), asyncio.to_thread(local))
    codex = await asyncio.to_thread(_codex, getattr(engine, "name", None))
    return [*others[:2], ai_check, *([codex] if codex else []), *others[2:]]


def render(checks: list[dict]) -> str:
    mark = {"ok": "✓", "warn": "!", "error": "✗"}
    lines = [f"TailorbirdCV {version()} · Python {sys.version.split()[0]} · {sys.platform}"]
    for c in checks:
        lines.append(f"  {mark[c['status']]} {c['label']}: {c['detail']}")
        if c["fix"] and c["status"] != "ok":
            lines.append(f"      → {c['fix']}")
    return "\n".join(lines)


def version() -> str:
    from importlib.metadata import PackageNotFoundError, version as pkg_version
    try:
        return pkg_version("tailorbirdcv")
    except PackageNotFoundError:
        return "dev"
