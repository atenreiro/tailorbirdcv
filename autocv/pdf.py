"""docx → PDF through Microsoft Word or LibreOffice, plus page counting, on macOS, Windows and Linux.

Either engine converts in one fixed working folder (`private/word/`) and one conversion runs at a
time (a thread lock plus a file lock, so the CLI and a running server take turns). `resolve()`
picks the engine: the user's choice when it's installed, otherwise Word, then LibreOffice (so Word
is the default whenever both are installed).

- **Word** is driven quietly and never touches the user's own documents:
  - macOS: AppleScript (JXA) through `osascript`. Word is launched hidden in the background,
    our document is addressed only by its unique name, and Word is quit only if AutoCV started
    it and nothing else is open. One fixed folder means Word's sandbox asks for file access
    ("Grant File Access") at most once.
  - Windows: PowerShell COM automation. Our document opens in an invisible window, is closed
    through its own object, and Word is quit only if AutoCV created that Word instance and
    nothing else is open in it.
  - Linux: not available.
- **LibreOffice** runs headless (no window) with its own profile (`private/libreoffice/`), so it
  never touches a LibreOffice the user has open. The fonts the resume names (Georgia, Calibri,
  Aptos…) are linked into that profile (from the system and, on macOS, from inside Word), and when
  one is missing a metric-compatible open font stands in (Georgia → Gelasio, Calibri → Carlito, both
  shipped with AutoCV), so line breaks and page counts match Word's.
  Number ranges ("2–4") are glued in LibreOffice's copy only, because it would otherwise break a
  line inside them where Word doesn't.

Each conversion runs in its own process group with a time limit: if the engine stalls (e.g. Word
waiting on a dialog), the whole process tree is killed and a clear error is raised instead of hanging.
"""

from __future__ import annotations

import base64
import os
import plistlib
import re
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from pathlib import Path

from pypdf import PdfReader

from . import oscompat, paths
from .oscompat import IS_MAC, IS_WINDOWS

PDF_TIMEOUT = float(os.environ.get("AUTOCV_PDF_TIMEOUT", "120"))
ENGINES = ("word", "libreoffice")  # order = default preference
NAMES = {"word": "Microsoft Word", "libreoffice": "LibreOffice"}
WORD_ID = "com.microsoft.Word"
DATA = Path(__file__).resolve().parent / "data"
_APPS = [Path("/Applications"), Path.home() / "Applications"]
_lock = threading.Lock()  # one conversion at a time (Word is shared; a LibreOffice profile is single-user);
# a file lock in the work folder does the same across processes (server + CLI)

# macOS: JXA run by osascript with argv = [docx, pdf]. Never calls activate(), never touches other documents.
_WORD_JXA = r"""
// Our document is always addressed by its unique name, never by position: a document the user
// opens meanwhile shifts positions, and closing "document 1" could then close theirs.
// Word's document count is reliable; names it reports for other documents can go stale.
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
  const ours = word.documents.byName(base);
  const isOpen = () => { try { return ours.name() === base; } catch (e) { return false; } };
  try {
    word.open(Path(src), {addToRecentFiles: false, readOnly: true});
    for (let i = 0; i < 100 && !isOpen(); i++) delay(0.1);
    if (!isOpen()) throw new Error('Word did not open the document');
    ours.saveAs({fileName: dst, fileFormat: 'format PDF', addToRecentFiles: false});
  } finally {
    if (isOpen()) ours.close({saving: 'no'});
    word.displayAlerts = alerts;
    // Quit only a Word we started, and only when nothing else is open in it ("ask" as a backstop).
    if (!wasRunning && word.documents.length === 0) word.quit({saving: 'ask'});
  }
}
"""

# Windows: Windows PowerShell 5.1 (.NET Framework, which has GetActiveObject) driving Word over COM.
# Paths arrive in environment variables (no quoting, whatever characters they contain). When the script
# starts its own Word, it writes that process id to AUTOCV_PIDFILE so a timeout can stop exactly that
# hidden instance (COM starts it outside our process tree). Errors are printed as one plain line.
_WORD_PS = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
  $src = $env:AUTOCV_SRC
  $dst = $env:AUTOCV_DST
  $missing = [System.Reflection.Missing]::Value
  $word = $null
  $created = $false
  try { $word = [Runtime.InteropServices.Marshal]::GetActiveObject('Word.Application') } catch { }
  if ($null -eq $word) {
    $before = @(Get-Process WINWORD -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    $word = New-Object -ComObject Word.Application
    $created = $true
    $new = @(Get-Process WINWORD -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | ForEach-Object { $_.Id })
    if ($new.Count -eq 1) { Set-Content -LiteralPath $env:AUTOCV_PIDFILE -Value $new[0] -Encoding ascii }
    $word.Visible = $false
  }
  $alerts = $word.DisplayAlerts
  $word.DisplayAlerts = 0
  $doc = $null
  try {
    # Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles, ..., Visible=$false): never shown
    $doc = $word.Documents.Open($src, $false, $true, $false, $missing, $missing, $missing, $missing,
                                $missing, $missing, $missing, $false)
    $doc.ExportAsFixedFormat($dst, 17)  # wdExportFormatPDF
  } finally {
    if ($null -ne $doc) { $doc.Close(0) }  # our document, by its own object; wdDoNotSaveChanges
    $word.DisplayAlerts = $alerts
    # Quit only a Word we created, and only when nothing else is open in it (-2: ask to save).
    if ($created -and $word.Documents.Count -eq 0) { $word.Quit(-2) }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
  }
} catch {
  [Console]::Out.WriteLine('Word error: ' + $_.Exception.Message)
  exit 1
}
"""


# -- locations ------------------------------------------------------------------------
def _private() -> Path:
    return paths.private_dir()


def work_dir() -> Path:
    """The one folder the engines read from and write to (inside private/, so it's never committed)."""
    return Path(os.environ.get("AUTOCV_WORD_DIR", _private() / "word"))


def lo_profile() -> Path:
    return Path(os.environ.get("AUTOCV_LO_PROFILE", _private() / "libreoffice"))


# -- detection ------------------------------------------------------------------------
def _winreg_value(path: str, name: str = "") -> str | None:
    """A value from HKCU or HKLM (Windows only)."""
    if not IS_WINDOWS:
        return None
    import winreg  # pragma: no cover - Windows only
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):  # pragma: no cover
        try:
            with winreg.OpenKey(hive, path) as key:
                return str(winreg.QueryValueEx(key, name)[0])
        except OSError:
            continue
    return None  # pragma: no cover


def _program_dirs() -> list[Path]:
    return [Path(p) for p in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")) if p]


def word_app() -> Path | None:
    """Word's app bundle (macOS) or WINWORD.EXE (Windows); never on Linux."""
    if IS_MAC:
        for base in _APPS:
            if (app := base / "Microsoft Word.app").is_dir():
                return app
        try:
            out = subprocess.run(["/usr/bin/mdfind", f"kMDItemCFBundleIdentifier == '{WORD_ID}'"],
                                 capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        return next((Path(p) for p in out.splitlines() if p.endswith(".app") and Path(p).is_dir()), None)
    if IS_WINDOWS:  # pragma: no cover - Windows only
        if (exe := _winreg_value(r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Winword.exe")) \
                and Path(exe).is_file():
            return Path(exe)
        for base in _program_dirs():
            for sub in ("Microsoft Office/root/Office16", "Microsoft Office/Office16"):
                if (exe := base / sub / "WINWORD.EXE").is_file():
                    return exe
    return None


def soffice() -> Path | None:
    """The LibreOffice executable (soffice.com on Windows, which waits and reports errors)."""
    if env := os.environ.get("AUTOCV_SOFFICE"):
        return Path(env) if Path(env).is_file() else None
    candidates: list[Path] = []
    if IS_MAC:
        candidates += [base / "LibreOffice.app" / "Contents" / "MacOS" / "soffice" for base in _APPS]
    elif IS_WINDOWS:  # pragma: no cover - Windows only
        if program := _winreg_value(r"SOFTWARE\LibreOffice\UNO\InstallPath"):
            candidates.append(Path(program) / "soffice.com")
        candidates += [base / "LibreOffice" / "program" / "soffice.com" for base in _program_dirs()]
    else:
        candidates += [Path("/usr/lib/libreoffice/program/soffice"), Path("/usr/lib64/libreoffice/program/soffice")]
        candidates += sorted(Path("/opt").glob("libreoffice*/program/soffice"), reverse=True)
        flatpak = "flatpak/exports/bin/org.libreoffice.LibreOffice"  # Flatpak's launcher takes soffice's arguments
        candidates += [Path("/var/lib") / flatpak, Path.home() / ".local/share" / flatpak]
    for exe in candidates:
        if exe.is_file():
            return exe
    found = shutil.which("soffice") or shutil.which("libreoffice")
    return Path(found) if found else None


def _version(path: Path | None) -> str | None:
    if path is None:
        return None
    app = next((p for p in [path, *path.parents] if p.suffix == ".app"), None)
    if app:  # macOS bundle
        try:
            return plistlib.loads((app / "Contents" / "Info.plist").read_bytes()).get("CFBundleShortVersionString")
        except (OSError, plistlib.InvalidFileException):
            return None
    for name in ("version.ini", "versionrc"):  # LibreOffice on Windows / Linux
        try:
            text = (path.parent / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if m := re.search(r"^(?:MsiProductVersion|ProductVersion)=(.+)$", text, re.M):
            return m[1].strip()
    if IS_WINDOWS and path.name.upper() == "WINWORD.EXE":  # pragma: no cover
        return _winreg_value(r"SOFTWARE\Microsoft\Office\ClickToRun\Configuration", "VersionToReport")
    return None


def test_conversion(engine: str | None = None) -> dict:
    """Convert a one-page document now, so a problem (Word not activated, a permission prompt, LibreOffice
    failing) shows up during setup rather than at the first real build. Returns {ok, engine, seconds, detail}."""
    import tempfile
    import time
    from docx import Document
    try:
        chosen = resolve(engine)
    except RuntimeError as e:
        return {"ok": False, "engine": None, "seconds": 0, "detail": str(e)}
    with tempfile.TemporaryDirectory(prefix="autocv-pdftest-") as tmp:
        docx = Path(tmp) / "AutoCV test.docx"
        doc = Document()
        doc.add_paragraph("AutoCV PDF test — this page can be deleted.")
        doc.save(str(docx))
        start = time.monotonic()
        try:
            out = to_pdf(docx, engine=chosen, timeout=180)
            ok = out.is_file() and out.stat().st_size > 0
            detail = "A test page converted fine." if ok else "No PDF came back."
        except Exception as e:  # noqa: BLE001 — report any failure as text
            ok, detail = False, str(e)
    return {"ok": ok, "engine": NAMES.get(chosen, chosen), "seconds": round(time.monotonic() - start, 1),
            "detail": detail}


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
    _remove_output(pdf)
    work = work_dir().resolve()
    work.mkdir(parents=True, exist_ok=True)
    with _lock, oscompat.FileLock(work / ".lock"):  # also serializes the CLI with a running server
        engine = resolve(engine)
        tag = uuid.uuid4().hex[:12]
        src, dst = work / f"autocv-{tag}.docx", work / f"autocv-{tag}.pdf"
        try:
            if engine == "word":
                shutil.copyfile(docx, src)
                pidfile = work / f"autocv-{tag}.pid"
                try:
                    _run(_command(src, dst), timeout, dst, engine, work,
                         env={**os.environ, "AUTOCV_SRC": str(src), "AUTOCV_DST": str(dst), "AUTOCV_PIDFILE": str(pidfile)},
                         pidfile=pidfile)
                finally:
                    pidfile.unlink(missing_ok=True)
            else:
                _lo_copy(docx, src)
                _run(_lo_command(src, work), timeout, dst, engine, work)
            try:
                shutil.move(dst, pdf)
            except PermissionError as e:  # Windows: the old PDF is open in a viewer
                raise RuntimeError(f"Couldn't save {pdf.name}: it's open in another app. "
                                   "Close it in your PDF viewer, then rebuild.") from e
            return pdf
        finally:
            for f in (src, dst):
                try:
                    f.unlink(missing_ok=True)
                except OSError:  # Windows: still held by a helper that is exiting
                    pass


def _remove_output(pdf: Path) -> None:
    try:
        pdf.unlink(missing_ok=True)
    except PermissionError as e:  # Windows locks files open in a viewer
        raise RuntimeError(f"Couldn't replace {pdf.name}: it's open in another app. "
                           "Close it in your PDF viewer, then rebuild.") from e


def _run(cmd: list[str], timeout: float, dst: Path, engine: str, work: Path, env: dict | None = None,
         pidfile: Path | None = None) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, **oscompat.group_kwargs())
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        oscompat.kill_tree(proc.pid)  # the helper and anything it started
        proc.wait()
        _kill_started_word(pidfile)
        if engine == "word":
            raise RuntimeError(f"Word didn't finish within {int(timeout)} s. {_word_dialog_hint(work)}")
        raise RuntimeError(f"LibreOffice didn't finish within {int(timeout)} s and was stopped. Try again, "
                           "or switch the PDF engine in Settings.")
    if not dst.exists():
        lines = [ln.strip() for ln in (out or b"").decode(errors="replace").splitlines() if ln.strip()]
        if engine == "word":
            detail = lines[-1] if lines else _word_dialog_hint(work)
        else:
            detail = lines[-1] if lines else "no output was produced."
        raise RuntimeError(f"{NAMES[engine]} did not produce the PDF: {detail}")


def _word_dialog_hint(work: Path) -> str:
    if IS_MAC:
        return (f"It may be waiting on a dialog: the first time, macOS asks Word for access to {work} "
                "(“Grant File Access”, click Select), or to allow AutoCV to control Word. Answer it in Word, "
                "then rebuild.")
    return ("It may be waiting on a dialog (activation, sign-in or a repair prompt). Open Word once, "
            "answer it, then rebuild.")


def _kill_started_word(pidfile: Path | None) -> None:
    """After a timeout on Windows: stop the hidden Word that this conversion started (and only that one)."""
    if not (IS_WINDOWS and pidfile):
        return
    try:
        pid = int(pidfile.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return  # Word was already running (the user's), or didn't start
    oscompat.kill_tree(pid)  # pragma: no cover - Windows only


def _command(src: Path, dst: Path) -> list[str]:
    """The Word command; on Windows the paths travel in AUTOCV_SRC / AUTOCV_DST (see to_pdf)."""
    if IS_WINDOWS:
        script = _WORD_PS
        root = os.environ.get("SystemRoot", r"C:\Windows")
        powershell = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        return [str(powershell) if powershell.is_file() else "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text", "-EncodedCommand",
                base64.b64encode(script.encode("utf-16-le")).decode("ascii")]
    if IS_MAC:
        return ["/usr/bin/osascript", "-l", "JavaScript", "-e", _WORD_JXA, str(src), str(dst)]
    raise RuntimeError("Microsoft Word isn't available on Linux. Use LibreOffice.")


def _lo_command(src: Path, outdir: Path) -> list[str]:
    exe = soffice()
    if exe is None:
        raise RuntimeError("LibreOffice is not installed.")
    profile = lo_profile().resolve()
    families = _fonts_in(src)
    sync_fonts(profile, families)
    configure_substitutes(profile, families)
    launcher = [sys.executable, str(exe)] if exe.suffix == ".py" else [str(exe)]  # .py: a stand-in (tests)
    return [*launcher, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore", "--nologo",
            "--nodefault", "--nolockcheck", "--convert-to", "pdf", "--outdir", str(outdir), str(src)]


# Digit–digit ranges ("2–4", "2019-2021"): LibreOffice may break a line inside them, Word doesn't.
_RANGE = re.compile(r"(?<=\d)([\N{EN DASH}\N{EM DASH}-])(?=\d)")
_WJ = "\N{WORD JOINER}"  # invisible, forbids a line break, and isn't extracted as text
_TEXT = re.compile(r"(<w:t(?:\s[^>]*)?>)([^<]*)(</w:t>)")


def glue_ranges(xml: str) -> str:
    """Glue ranges inside text runs only (never attributes, field codes or other markup)."""
    return _TEXT.sub(lambda m: m[1] + _RANGE.sub(f"{_WJ}\\1{_WJ}", m[2]) + m[3], xml)


def _lo_copy(docx: Path, dst: Path) -> None:
    """LibreOffice's private copy of the docx, with number ranges glued. The user's file is untouched."""
    with zipfile.ZipFile(docx) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = glue_ranges(data.decode("utf-8")).encode("utf-8")
            zout.writestr(item, data)


# -- fonts for LibreOffice -------------------------------------------------------------
# Metric-compatible open fonts: same character widths, so line breaks and page counts don't move.
SUBSTITUTES = {"Georgia": "Gelasio", "Calibri": "Carlito"}  # both shipped in data/fonts


def system_font_dirs() -> list[Path]:
    """Where this OS keeps fonts (searched recursively)."""
    if IS_MAC:
        dirs = [Path.home() / "Library" / "Fonts", Path("/Library/Fonts"),
                Path("/System/Library/Fonts/Supplemental"), Path("/System/Library/Fonts")]
        if app := word_app():
            dirs.append(app / "Contents" / "Resources" / "DFonts")  # Calibri, Aptos… ship inside Word
        return dirs
    if IS_WINDOWS:  # pragma: no cover - Windows only
        return [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
                Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Microsoft" / "Windows" / "Fonts"]
    return [Path.home() / ".local" / "share" / "fonts", Path.home() / ".fonts",
            Path("/usr/local/share/fonts"), Path("/usr/share/fonts")]


def font_dirs() -> list[Path]:
    """Folders whose matching fonts are linked into the LibreOffice profile.

    On macOS LibreOffice doesn't see the Supplemental fonts or the ones inside Word, so they're
    linked in; on Windows and Linux it already sees the system fonts. AutoCV's own open fonts
    (the substitutes) are linked everywhere."""
    return (system_font_dirs() if IS_MAC else []) + [DATA / "fonts"]


def _font_files(folder: Path) -> list[Path]:
    try:
        return [f for f in folder.rglob("*") if f.suffix.lower() in (".ttf", ".otf", ".ttc")]
    except OSError:
        return []


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


def installed(family: str) -> bool:
    """Whether LibreOffice will find `family` (in the system font folders)."""
    return any(_matches(f, {family}) for d in system_font_dirs() for f in _font_files(d))


def sync_fonts(profile: Path, families: set[str]) -> None:
    """Link the font files for `families` (and their substitutes) into the profile's user/fonts,
    where LibreOffice loads them. Copies instead where symlinks aren't allowed (Windows)."""
    families = families | {SUBSTITUTES[f] for f in families if f in SUBSTITUTES}
    dest = profile / "user" / "fonts"
    dest.mkdir(parents=True, exist_ok=True)
    for folder in font_dirs():
        for f in _font_files(folder):
            link = dest / f.name
            if not _matches(f, families) or link.exists():
                continue
            link.unlink(missing_ok=True)  # a dangling link left by a moved font
            try:
                link.symlink_to(f)
            except OSError:  # Windows without Developer Mode
                shutil.copy2(f, link)


_XCU = "registrymodifications.xcu"
_XCU_EMPTY = ('<?xml version="1.0" encoding="UTF-8"?>\n<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
              'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
              '</oor:items>\n')
_SUBST_PATH = "/org.openoffice.Office.Common/Font/Substitution"
_OURS = re.compile(r'<item oor:path="' + re.escape(_SUBST_PATH) + r'(?:/FontPairs"><node oor:name="autocv-[^"]*"'
                   r'|"><prop oor:name="Replacement")[^\n]*?</item>\n?')


def configure_substitutes(profile: Path, families: set[str]) -> None:
    """LibreOffice replacement rules for fonts the document names but this machine lacks.

    A rule is only added for a missing font (it applies "always", so it must never replace a
    font that is installed). Rules are rewritten each time, so installing the real font later
    removes the stand-in."""
    rules = {f: s for f, s in SUBSTITUTES.items() if f in families and not installed(f)}
    path = profile / "user" / _XCU
    try:
        old = path.read_text(encoding="utf-8")
    except OSError:
        old = _XCU_EMPTY if rules else ""
    if not old:
        return
    text = _OURS.sub("", old)
    if rules:
        items = [f'<item oor:path="{_SUBST_PATH}"><prop oor:name="Replacement" oor:op="fuse"><value>true</value>'
                 "</prop></item>\n"]
        for family, sub in sorted(rules.items()):
            items.append(
                f'<item oor:path="{_SUBST_PATH}/FontPairs"><node oor:name="autocv-{family.lower()}" oor:op="replace">'
                '<prop oor:name="Always" oor:op="fuse"><value>true</value></prop>'
                '<prop oor:name="OnScreenOnly" oor:op="fuse"><value>false</value></prop>'
                f'<prop oor:name="ReplaceFont" oor:op="fuse"><value>{family}</value></prop>'
                f'<prop oor:name="SubstituteFont" oor:op="fuse"><value>{sub}</value></prop></node></item>\n')
        text = text.replace("</oor:items>", "".join(items) + "</oor:items>")
    if text != old:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        oscompat.replace(tmp, path)


def page_count(pdf: Path) -> int:
    return len(PdfReader(str(pdf)).pages)
