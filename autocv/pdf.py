"""docx → PDF through Microsoft Word (faithful pagination), plus page counting."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

from pypdf import PdfReader


def to_pdf(docx: Path, pdf: Path | None = None) -> Path:
    from docx2pdf import convert  # imported lazily: drives Word via AppleScript

    pdf = pdf or docx.with_suffix(".pdf")
    with contextlib.redirect_stderr(io.StringIO()):  # silence tqdm progress bar
        convert(str(docx.resolve()), str(pdf.resolve()))
    if not pdf.exists():
        raise RuntimeError(f"Word did not produce {pdf}")
    return pdf


def page_count(pdf: Path) -> int:
    return len(PdfReader(str(pdf)).pages)
