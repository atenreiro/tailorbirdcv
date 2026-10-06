"""Laying a resume out on pages from the .docx (layout.py): the fonts' real metrics, Word's spacing and page
breaks, and no text smaller than 9.5 pt (except Classic as originally drawn). Fictional data."""

import re
import zipfile
from pathlib import Path

import pytest

from tailorbirdcv import ai, layout, pdf, themes
from tailorbirdcv.layout import _Para, paginate
from tailorbirdcv.render import render, use_design
from tailorbirdcv.schema import Claim, load_profile, load_tailored

FIX = Path(__file__).parent / "fixtures"
PROFILE, TAILORED = load_profile(FIX / "profile.yaml"), load_tailored(FIX / "tailored.yaml")


def test_font_metrics_are_the_real_fonts():
    calibri, georgia = layout.font("Calibri"), layout.font("Georgia", bold=True)
    assert calibri.line == pytest.approx(1.2207, abs=1e-4)  # Word's single line height for Calibri
    assert georgia.line == pytest.approx(1.1362, abs=1e-4)  # Georgia's, not its stand-in's (1.66)
    assert calibri.width("M", 10) > calibri.width("i", 10) > 0
    assert calibri.width("mm", 10) == pytest.approx(2 * calibri.width("m", 10))
    for c in "•–—·’é":  # characters the renderer and resumes use are all known to the font
        assert ord(c) in calibri.cmap


def test_space_between_paragraphs_is_the_larger_of_after_and_before():
    assert paginate([_Para(0, 10, 6, False), _Para(7, 10, 0, False)], 100) == [27]  # 10 + max(6, 7) + 10
    assert paginate([_Para(5, 10, 0, False)], 100) == [15]  # space before counts at the top of the page


def test_a_heading_moves_to_the_next_page_with_what_follows_it():
    paras = [_Para(0, 80, 0, False), _Para(0, 10, 0, True), _Para(0, 15, 0, False)]
    assert paginate(paras, 100) == [80, 25]  # the heading would fit on page 1, but not with its text
    tall = [_Para(0, 60, 0, True), _Para(0, 60, 0, False)]
    assert paginate(tall, 100) == [60, 60]  # a group taller than a page breaks where it must


def resume(bullets: int):
    """The fixture resume with `bullets` extra bullets on the current role (layout only: never fact-checked)."""
    t = TAILORED.model_copy(deep=True)
    text = "Rebuilt the alerting pipeline and its runbooks, cutting false positives by over 65% across three teams."
    t.experience[0].bullets += [Claim(text=text, sources=["acme-bank.a1"]) for _ in range(bullets)]
    return t


def test_longer_resumes_measure_longer_and_break_onto_more_pages(tmp_path):
    short = layout.measure(render(PROFILE, resume(0), tmp_path / "a.docx"), themes.CLASSIC, "letter")
    longer = layout.measure(render(PROFILE, resume(10), tmp_path / "b.docx"), themes.CLASSIC, "letter")
    long = layout.measure(render(PROFILE, resume(60), tmp_path / "c.docx"), themes.CLASSIC, "letter")
    assert short.pages == 1 and short.lines < longer.lines < long.lines
    line = layout.body_line(themes.CLASSIC)
    assert longer.lines - short.lines == pytest.approx(10 * (line + 1.5) / line, abs=0.1)  # 1 line + 1.5 pt each
    assert long.pages >= 2 and long.fills[0] > 0.9
    assert short.per_page == pytest.approx(themes.CLASSIC.lines_per_page("letter"))


def test_budgets_follow_the_layout(tmp_path):
    use_design("compact", "a4")
    try:
        assert ai.estimate_lines(PROFILE, resume(10)) == round(
            layout.measure(render(PROFILE, resume(10), tmp_path / "r.docx"), themes.COMPACT, "a4").lines)
        assert ai.default_budget(1)["lines"] < themes.COMPACT.lines_per_page("a4")  # aims a little under
    finally:
        use_design(None, None)


def sizes(docx: Path) -> set[int]:
    return {int(s) for s in re.findall(r'<w:sz w:val="(\d+)"', zipfile.ZipFile(docx).read("word/document.xml").decode())}


@pytest.mark.parametrize("theme", sorted(themes.THEMES))
@pytest.mark.parametrize("size", themes.TEXT_SIZES)
def test_no_text_is_smaller_than_9_5_pt_except_classic_as_drawn(tmp_path, theme, size):
    t = themes.get(theme, size)
    smallest = min(sizes(render(PROFILE, TAILORED, tmp_path / "r.docx", theme=t)))
    if (theme, size) == ("classic", "standard"):
        assert smallest == 17  # the original design's 8.5 pt contact line and dates, byte for byte
    else:
        assert smallest >= themes.MIN_SIZE == 19


def test_a_long_contact_line_wraps_between_items_only(tmp_path):
    long = PROFILE.model_copy(deep=True)
    long.contact.phone = "+65 0000 0000 ext 1234"
    long.contact.location = "Singapore, Republic of Singapore"
    long.contact.links = long.contact.links * 6
    docx = render(long, TAILORED, tmp_path / "r.docx", theme="modern")
    xml = zipfile.ZipFile(docx).read("word/document.xml").decode()
    assert "+65\u00a00000\u00a00000\u00a0ext\u00a01234" in xml and "\u00a0·" in xml  # no break inside an item
    contact = layout.paragraphs(docx, themes.MODERN, "letter")[2]
    lines = contact.body / (9.5 * layout.font("Calibri").line)
    assert lines >= 2 and lines == pytest.approx(round(lines))  # wrapped onto whole extra lines, and measured so
    classic = zipfile.ZipFile(render(long, TAILORED, tmp_path / "c.docx")).read("word/document.xml").decode()
    assert "\u00a0" not in classic  # Classic as drawn is untouched


def test_word_is_asked_again_after_a_startup_hiccup(tmp_path, monkeypatch):
    calls = []

    def run(cmd, timeout, dst, engine, work, env=None, pidfile=None):
        calls.append(engine)
        if len(calls) == 1:
            raise RuntimeError("Microsoft Word did not produce the PDF: execution error: Message not understood. (-1708)")
        dst.write_bytes(b"%PDF-1.4\n%%EOF\n")
    monkeypatch.setattr(pdf, "_run", run)
    monkeypatch.setattr(pdf, "IS_MAC", True)
    monkeypatch.setattr(pdf, "resolve", lambda engine=None, engines=None: "word")
    monkeypatch.setenv("TAILORBIRDCV_WORD_DIR", str(tmp_path / "work"))
    docx = tmp_path / "r.docx"
    docx.write_bytes(b"x")
    assert pdf.to_pdf(docx, engine="word").exists() and calls == ["word", "word"]
