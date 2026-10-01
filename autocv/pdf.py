"""docx → PDF through Microsoft Word (faithful pagination), plus page counting.

The conversion runs in its own process group with a time limit: if Word stalls
(e.g. waiting on a "Grant File Access" or automation-permission dialog), the
helper processes are killed and a clear error is raised instead of hanging.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from pypdf import PdfReader

PDF_TIMEOUT = float(os.environ.get("AUTOCV_PDF_TIMEOUT", "120"))
_CONVERT = "import sys; from docx2pdf import convert; convert(sys.argv[1], sys.argv[2])"


def to_pdf(docx: Path, pdf: Path | None = None, timeout: float = PDF_TIMEOUT) -> Path:
    pdf = pdf or docx.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)
    proc = subprocess.Popen([sys.executable, "-c", _CONVERT, str(docx.resolve()), str(pdf.resolve())],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    try:
        _, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)  # the helper and its osascript child
        proc.wait()
        raise RuntimeError(
            f"Word didn't finish within {int(timeout)} s. It may be waiting on a dialog (e.g. "
            "“Grant File Access” or permission to be controlled). Switch to Word, answer it, then rebuild.")
    if not pdf.exists():
        # docx2pdf prints a progress bar on stderr; keep only real error lines
        lines = [ln for ln in (err or b"").decode(errors="replace").splitlines() if ln.strip() and "it/s]" not in ln]
        detail = lines[-1].strip() if lines else ("Word may be showing a dialog (e.g. “Grant File Access”). "
                                                  "Switch to Word, answer it, then rebuild.")
        raise RuntimeError(f"Word did not produce the PDF: {detail}")
    return pdf


def page_count(pdf: Path) -> int:
    return len(PdfReader(str(pdf)).pages)
