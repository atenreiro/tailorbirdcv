"""A real LibreOffice conversion of the fictional fixture resume (skipped where LibreOffice isn't
installed; CI installs it on Linux and Windows). Covers the platform paths end to end: finding
soffice, the profile, fonts or their open stand-ins, process handling, the file lock."""

import os
from pathlib import Path

import pytest

from tailorbirdcv import pdf
from tailorbirdcv.render import render
from tailorbirdcv.schema import load_profile, load_tailored

FIX = Path(__file__).parent / "fixtures"

# CI sets TAILORBIRDCV_EXPECT_LIBREOFFICE=1 where it installed LibreOffice: not finding it is then a failure.
pytestmark = pytest.mark.skipif(pdf.soffice() is None and not os.environ.get("TAILORBIRDCV_EXPECT_LIBREOFFICE"),
                                reason="LibreOffice isn't installed")


def test_libreoffice_converts_the_fixture_resume(tmp_path, monkeypatch):
    assert pdf.soffice() is not None, "LibreOffice was installed but TailorbirdCV didn't find it"
    monkeypatch.setenv("TAILORBIRDCV_WORD_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("TAILORBIRDCV_LO_PROFILE", str(tmp_path / "lo-profile"))
    profile = load_profile(FIX / "profile.yaml")
    docx = render(profile, load_tailored(FIX / "tailored.yaml"), tmp_path / "app" / "Resume.docx")
    out = pdf.to_pdf(docx, engine="libreoffice", timeout=240)
    assert out == docx.with_suffix(".pdf") and 1 <= pdf.page_count(out) <= 2
    from pypdf import PdfReader
    text = "".join(page.extract_text() for page in PdfReader(str(out)).pages)
    assert profile.contact.name in text
    assert "\N{WORD JOINER}" not in text  # the glue never leaks into the PDF's text
    fonts = {f.name for f in (tmp_path / "lo-profile" / "user" / "fonts").iterdir()}
    embedded = {font for page in PdfReader(str(out)).pages
                for font in (page.get("/Resources", {}).get("/Font", {}) or {}).values()
                for font in [str(font.get_object().get("/BaseFont", ""))]}
    for family, stand_in in pdf.SUBSTITUTES.items():  # missing fonts are replaced by the shipped look-alikes
        if not pdf.installed(family):
            assert f"{stand_in}-Regular.ttf" in fonts
            assert any(stand_in in f for f in embedded), (family, embedded)
    assert [p.name for p in (tmp_path / "work").iterdir()] == [".lock"]


@pytest.mark.parametrize("pages", [1, 2])
def test_a_resume_at_its_length_budget_fits_the_page_limit(tmp_path, monkeypatch, pages):
    """The length budget (what the AI is told, and what trims aim at) really fits: grown to its budget, the
    resume converts to exactly the page limit, with its last page well filled."""
    from tailorbirdcv import ai, fit, themes
    from tailorbirdcv.schema import Claim
    monkeypatch.setenv("TAILORBIRDCV_WORD_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("TAILORBIRDCV_LO_PROFILE", str(tmp_path / "lo-profile"))
    profile, tailored = load_profile(FIX / "profile.yaml"), load_tailored(FIX / "tailored.yaml")
    budget = ai.default_budget(pages)["lines"]
    text = "Rebuilt the alerting pipeline and its runbooks with the platform team, cutting false positives by over 65%."
    while True:
        grown = tailored.model_copy(deep=True)
        grown.experience[0].bullets.append(Claim(text=text, sources=["acme-bank.a1"]))
        if ai.estimate_lines(profile, grown) > budget:
            break
        tailored = grown
    out = pdf.to_pdf(render(profile, tailored, tmp_path / "r.docx"), engine="libreoffice", timeout=240)
    fills = fit.page_fill(out, themes.CLASSIC)
    assert len(fills) == pages and fills[-1] > 0.8, fills
