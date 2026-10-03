"""docx → PDF through Microsoft Word or LibreOffice, plus page counting.

Either engine converts in one fixed working folder (`private/word/`) and one conversion runs at a
time. `resolve()` picks the engine: the user's choice when it's installed, otherwise Word, then
LibreOffice (so Word is the default whenever both are installed).

- **Word** is driven quietly: launched hidden and in the background (never activated), only our
  own document is opened and closed, and Word is quit afterwards only if it wasn't already
  running. Using one folder means Word's sandbox asks for file access ("Grant File Access") at
  most once.
- **LibreOffice** runs headless (no window) with its own profile (`private/libreoffice/`), so it
  never touches a LibreOffice the user has open. The fonts the resume names (Georgia, Calibri,
  Aptos…) are linked into that profile from the system and from Word, if installed, so the layout
  matches Word's. Number ranges ("2–4") are glued in LibreOffice's copy only, because it would
  otherwise break a line inside them where Word doesn't.

Each conversion runs in its own process group with a time limit: if the engine stalls (e.g. Word
waiting on a permission dialog), it's killed and a clear error is raised instead of hanging.
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import threading
import uuid
import zipfile
from pathlib import Path

from pypdf import PdfReader

PDF_TIMEOUT = float(os.environ.get("AUTOCV_PDF_TIMEOUT", "120"))
ENGINES = ("word", "libreoffice")  # order = default preference
NAMES = {"word": "Microsoft Word", "libreoffice": "LibreOffice"}
WORD_ID = "com.microsoft.Word"
_APPS = [Path("/Applications"), Path.home() / "Applications"]
_lock = threading.Lock()  # one conversion at a time (Word is shared; a LibreOffice profile is single-user)

# JXA run by osascript with argv = [docx, pdf]. Never calls activate(), never touches other documents.
_WORD_JXA = r"""
function run(argv) {
  const src = argv[0], dst = argv[1], base = src.split('/').pop();
  const me = Application.currentApplication();
  me.includeStandardAdditions = true;
  const word = Application('com.microsoft.Word');
  const wasRunning = word.running();
  if (!wasRunning) {
    me.doShellScript('/usr/bin/open -g -j -b com.microsoft.Word');  // background + hidden
    for (let i = 0; i < 600 && !word.running(); i++) delay(0.1);
  }
  const alerts = word.displayAlerts();
  word.displayAlerts = 'alerts none';
  let doc = null;
  try {
    word.open(Path(src), {addToRecentFiles: false, readOnly: true});
    for (let i = 0; i < 100 && !doc; i++) {
      doc = word.documents().find((d) => d.name() === base) || null;
      if (!doc) delay(0.1);
    }
    if (!doc) throw new Error('Word did not open the document');
    doc.saveAs({fileName: dst, fileFormat: 'format PDF', addToRecentFiles: false});
  } finally {
    if (doc) doc.close({saving: 'no'});
    word.displayAlerts = alerts;
    if (!wasRunning) word.quit({saving: 'no'});
  }
}
"""


# -- locations ------------------------------------------------------------------------
def _private() -> Path:
    return Path(os.environ.get("AUTOCV_PRIVATE", Path(__file__).resolve().parent.parent / "private"))


def work_dir() -> Path:
    """The one folder the engines read from and write to (inside private/, so it's never committed)."""
    return Path(os.environ.get("AUTOCV_WORD_DIR", _private() / "word"))


def lo_profile() -> Path:
    return Path(os.environ.get("AUTOCV_LO_PROFILE", _private() / "libreoffice"))


# -- detection ------------------------------------------------------------------------
def word_app() -> Path | None:
    if sys.platform != "darwin":
        return None  # driven through AppleScript
    for base in _APPS:
        if (app := base / "Microsoft Word.app").is_dir():
            return app
    try:
        out = subprocess.run(["/usr/bin/mdfind", f"kMDItemCFBundleIdentifier == '{WORD_ID}'"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return next((Path(p) for p in out.splitlines() if p.endswith(".app") and Path(p).is_dir()), None)


def soffice() -> Path | None:
    if env := os.environ.get("AUTOCV_SOFFICE"):
        return Path(env) if Path(env).is_file() else None
    for base in _APPS:
        if (exe := base / "LibreOffice.app" / "Contents" / "MacOS" / "soffice").is_file():
            return exe
    found = shutil.which("soffice") or shutil.which("libreoffice")
    return Path(found) if found else None


def _version(path: Path | None) -> str | None:
    app = next((p for p in ([path] + list(path.parents) if path else []) if p.suffix == ".app"), None)
    try:
        return plistlib.loads((app / "Contents" / "Info.plist").read_bytes()).get("CFBundleShortVersionString")
    except (OSError, TypeError, AttributeError, plistlib.InvalidFileException):
        return None


def detect() -> list[dict]:
    """Which engines are installed (cheap: nothing is launched)."""
    found = {"word": word_app(), "libreoffice": soffice()}
    return [{"id": e, "name": NAMES[e], "available": found[e] is not None,
             "path": str(found[e]) if found[e] else None, "version": _version(found[e])} for e in ENGINES]


def resolve(preferred: str | None = None, engines: list[dict] | None = None) -> str:
    """The engine to use: the preferred one if installed, else the first installed (Word first)."""
    available = [e["id"] for e in (engines if engines is not None else detect()) if e["available"]]
    if preferred in available:
        return preferred
    if not available:
        raise RuntimeError("No PDF engine found: install Microsoft Word or LibreOffice (libreoffice.org), "
                           "or build the .docx only.")
    return available[0]


# -- conversion -----------------------------------------------------------------------
def to_pdf(docx: Path, pdf: Path | None = None, timeout: float = PDF_TIMEOUT, engine: str | None = None) -> Path:
    """Convert with `engine` (a preference, see resolve()); returns the PDF path next to the docx."""
    pdf = pdf or docx.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)
    with _lock:
        engine = resolve(engine)
        work = work_dir().resolve()
        work.mkdir(parents=True, exist_ok=True)
        tag = uuid.uuid4().hex[:12]
        src, dst = work / f"autocv-{tag}.docx", work / f"autocv-{tag}.pdf"
        try:
            if engine == "word":
                shutil.copyfile(docx, src)
                _run(_command(src, dst), timeout, dst, engine, work)
            else:
                _lo_copy(docx, src)
                _run(_lo_command(src, work), timeout, dst, engine, work)
            shutil.move(dst, pdf)
            return pdf
        finally:
            src.unlink(missing_ok=True)
            dst.unlink(missing_ok=True)


def _run(cmd: list[str], timeout: float, dst: Path, engine: str, work: Path) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)  # the helper and anything it started
        proc.wait()
        if engine == "word":
            raise RuntimeError(
                f"Word didn't finish within {int(timeout)} s. It may be waiting on a dialog: the first "
                f"time, macOS asks Word for access to {work} (“Grant File Access”, click Select), or "
                "to allow AutoCV to control Word. Answer it in Word, then rebuild.")
        raise RuntimeError(f"LibreOffice didn't finish within {int(timeout)} s and was stopped. Try again, "
                           "or switch the PDF engine to Microsoft Word in Settings.")
    if not dst.exists():
        lines = [ln.strip() for ln in (out or b"").decode(errors="replace").splitlines() if ln.strip()]
        if engine == "word":
            detail = lines[-1] if lines else (f"Word may be showing a dialog (e.g. “Grant File Access” for "
                                              f"{work}). Answer it in Word, then rebuild.")
        else:
            detail = lines[-1] if lines else "no output was produced."
        raise RuntimeError(f"{NAMES[engine]} did not produce the PDF: {detail}")


def _command(src: Path, dst: Path) -> list[str]:
    return ["/usr/bin/osascript", "-l", "JavaScript", "-e", _WORD_JXA, str(src), str(dst)]


def _lo_command(src: Path, outdir: Path) -> list[str]:
    exe = soffice()
    if exe is None:
        raise RuntimeError("LibreOffice is not installed.")
    profile = lo_profile().resolve()
    sync_fonts(profile, _fonts_in(src))
    return [str(exe), f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore", "--nologo",
            "--nodefault", "--nolockcheck", "--convert-to", "pdf", "--outdir", str(outdir), str(src)]


# Digit–digit ranges ("2–4", "2019-2021"): LibreOffice may break a line inside them, Word doesn't.
_RANGE = re.compile(r"(?<=\d)([–—-])(?=\d)")
_WJ = "⁠"  # WORD JOINER: invisible, forbids a line break, and isn't extracted as text


def glue_ranges(xml: str) -> str:
    return _RANGE.sub(f"{_WJ}\\1{_WJ}", xml)


def _lo_copy(docx: Path, dst: Path) -> None:
    """LibreOffice's private copy of the docx, with number ranges glued. The user's file is untouched."""
    with zipfile.ZipFile(docx) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = glue_ranges(data.decode("utf-8")).encode("utf-8")
            zout.writestr(item, data)


# -- fonts for LibreOffice -------------------------------------------------------------
def font_dirs() -> list[Path]:
    dirs = [Path.home() / "Library" / "Fonts", Path("/Library/Fonts"),
            Path("/System/Library/Fonts/Supplemental"), Path("/System/Library/Fonts")]
    if app := word_app():
        dirs.append(app / "Contents" / "Resources" / "DFonts")  # Calibri, Aptos… ship inside Word
    return dirs


def _fonts_in(docx: Path) -> set[str]:
    """Font families the document names (its font table and theme)."""
    names: set[str] = set()
    with zipfile.ZipFile(docx) as z:
        for part in ("word/fontTable.xml", "word/document.xml", "word/styles.xml", "word/theme/theme1.xml"):
            try:
                xml = z.read(part).decode("utf-8", "replace")
            except KeyError:
                continue
            names |= set(re.findall(r'w:(?:name|ascii|hAnsi)="([^"]+)"', xml))
            names |= set(re.findall(r'<a:latin typeface="([^"]+)"', xml))
    return {n for n in names if n and not n.startswith("+")}


_STYLE = re.compile(r"(regular|bold|italic|oblique|light|semibold|[bizl]{1,2})*")
_norm = lambda s: re.sub(r"[\s_-]+", "", s.lower())  # noqa: E731


def _matches(file: Path, families: set[str]) -> bool:
    stem = _norm(file.stem)
    return any(stem.startswith(f) and _STYLE.fullmatch(stem[len(f):]) for f in map(_norm, families))


def sync_fonts(profile: Path, families: set[str]) -> None:
    """Link the font files for `families` into the profile's user/fonts (LibreOffice loads them)."""
    dest = profile / "user" / "fonts"
    dest.mkdir(parents=True, exist_ok=True)
    for folder in font_dirs():
        try:
            files = [f for f in folder.iterdir() if f.suffix.lower() in (".ttf", ".otf", ".ttc")]
        except OSError:
            continue
        for f in files:
            link = dest / f.name
            if _matches(f, families) and not link.exists():
                link.unlink(missing_ok=True)  # a dangling link left by a moved font
                link.symlink_to(f)


def page_count(pdf: Path) -> int:
    return len(PdfReader(str(pdf)).pages)
