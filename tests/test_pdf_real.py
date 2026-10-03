"""A real LibreOffice conversion of the fictional fixture resume (skipped where LibreOffice isn't
installed; CI installs it on Linux and Windows). Covers the platform paths end to end: finding
soffice, the profile, fonts or their open stand-ins, process handling, the file lock."""

import os
from pathlib import Path

import pytest

from autocv import pdf
from autocv.render import render
from autocv.schema import load_profile, load_tailored

FIX = Path(__file__).parent / "fixtures"

# CI sets AUTOCV_EXPECT_LIBREOFFICE=1 where it installed LibreOffice: not finding it is then a failure.
pytestmark = pytest.mark.skipif(pdf.soffice() is None and not os.environ.get("AUTOCV_EXPECT_LIBREOFFICE"),
                                reason="LibreOffice isn't installed")


def test_libreoffice_converts_the_fixture_resume(tmp_path, monkeypatch):
    assert pdf.soffice() is not None, "LibreOffice was installed but AutoCV didn't find it"
    monkeypatch.setenv("AUTOCV_WORD_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("AUTOCV_LO_PROFILE", str(tmp_path / "lo-profile"))
    profile = load_profile(FIX / "profile.yaml")
    docx = render(profile, load_tailored(FIX / "tailored.yaml"), tmp_path / "app" / "Resume.docx")
    out = pdf.to_pdf(docx, engine="libreoffice", timeout=240)
    assert out == docx.with_suffix(".pdf") and 1 <= pdf.page_count(out) <= 2
    from pypdf import PdfReader
    text = "".join(page.extract_text() for page in PdfReader(str(out)).pages)
    assert profile.contact.name in text
    assert "\N{WORD JOINER}" not in text  # the glue never leaks into the PDF's text
    fonts = {f.name for f in (tmp_path / "lo-profile" / "user" / "fonts").iterdir()}
    if not pdf.installed("Georgia"):
        assert "Gelasio-Bold.ttf" in fonts  # the open stand-in is there when Georgia isn't
    assert [p.name for p in (tmp_path / "work").iterdir()] == [".lock"]
