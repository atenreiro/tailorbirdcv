"""docx → PDF through Microsoft Word (faithful pagination), plus page counting.

Word is driven quietly: it's launched hidden and in the background (never activated), only our
own document is opened and closed, and Word is quit afterwards only if it wasn't already running.
Conversions always happen in one fixed working folder, so Word's sandbox asks for file access
("Grant File Access") at most once, not once per application folder.

The conversion runs in its own process group with a time limit: if Word stalls (e.g. waiting on
a permission dialog), the helper processes are killed and a clear error is raised instead of hanging.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import uuid
from pathlib import Path

from pypdf import PdfReader

PDF_TIMEOUT = float(os.environ.get("AUTOCV_PDF_TIMEOUT", "120"))

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


def work_dir() -> Path:
    """The one folder Word reads from and writes to (inside private/, so it's never committed)."""
    root = Path(os.environ.get("AUTOCV_PRIVATE", Path(__file__).resolve().parent.parent / "private"))
    return Path(os.environ.get("AUTOCV_WORD_DIR", root / "word"))


def _command(src: Path, dst: Path) -> list[str]:
    return ["/usr/bin/osascript", "-l", "JavaScript", "-e", _WORD_JXA, str(src), str(dst)]


def to_pdf(docx: Path, pdf: Path | None = None, timeout: float = PDF_TIMEOUT) -> Path:
    pdf = pdf or docx.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)
    work = work_dir().resolve()
    work.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:12]
    src, dst = work / f"autocv-{tag}.docx", work / f"autocv-{tag}.pdf"
    shutil.copyfile(docx, src)
    try:
        proc = subprocess.Popen(_command(src, dst), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                start_new_session=True)
        try:
            _, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)  # osascript and anything it started
            proc.wait()
            raise RuntimeError(
                f"Word didn't finish within {int(timeout)} s. It may be waiting on a dialog: the first "
                f"time, macOS asks Word for access to {work} (“Grant File Access”, click Select), or "
                "to allow AutoCV to control Word. Answer it in Word, then rebuild.")
        if not dst.exists():
            lines = [ln.strip() for ln in (err or b"").decode(errors="replace").splitlines() if ln.strip()]
            detail = lines[-1] if lines else (f"Word may be showing a dialog (e.g. “Grant File Access” for "
                                              f"{work}). Answer it in Word, then rebuild.")
            raise RuntimeError(f"Word did not produce the PDF: {detail}")
        shutil.move(dst, pdf)
        return pdf
    finally:
        src.unlink(missing_ok=True)
        dst.unlink(missing_ok=True)


def page_count(pdf: Path) -> int:
    return len(PdfReader(str(pdf)).pages)
