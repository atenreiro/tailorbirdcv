"""Resume themes: Classic is the original design byte-for-byte; others change only the look."""

import re
import shutil
import zipfile
from pathlib import Path

import pytest

from tailorbirdcv import ai, themes
from tailorbirdcv.api import create_app
from tailorbirdcv.engine import FakeEngine
from tailorbirdcv.render import docx_text, render, use_design
from tailorbirdcv.schema import load_profile, load_tailored
from tailorbirdcv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
PROFILE, TAILORED = load_profile(FIX / "profile.yaml"), load_tailored(FIX / "tailored.yaml")


def xml(path: Path) -> str:
    return zipfile.ZipFile(path).read("word/document.xml").decode()


def test_classic_is_the_original_design_byte_for_byte(tmp_path):
    out = render(PROFILE, TAILORED, tmp_path / "r.docx")  # default: Classic on Letter
    assert xml(out).encode() == (FIX / "golden_classic_document.xml").read_bytes()
    assert xml(render(PROFILE, TAILORED, tmp_path / "c.docx", theme="classic", paper="letter")) == xml(out)


@pytest.mark.parametrize("theme", ["modern", "compact"])
def test_other_themes_change_the_look_not_the_content(tmp_path, theme):
    classic = render(PROFILE, TAILORED, tmp_path / "classic.docx")
    other = render(PROFILE, TAILORED, tmp_path / f"{theme}.docx", theme=theme)
    assert docx_text(other) == docx_text(classic)  # same words, same order
    assert xml(other) != xml(classic)
    t = themes.get(theme)
    assert f'w:color w:val="{t.accent}"' in xml(other)
    assert f'w:ascii="{t.name_font}"' in xml(other)


def test_a4_sets_the_page_and_the_right_tab_stop(tmp_path):
    a4 = xml(render(PROFILE, TAILORED, tmp_path / "a4.docx", paper="a4"))
    assert '<w:pgSz w:w="11906" w:h="16838"/>' in a4
    assert f'w:pos="{11906 - 1080 - 1080}"' in a4  # dates align to the A4 right margin
    compact = xml(render(PROFILE, TAILORED, tmp_path / "c.docx", theme="compact", paper="a4"))
    assert re.search(r'<w:pgMar w:top="720" w:right="900" w:bottom="720" w:left="900"', compact)


def test_the_active_design_drives_renders_and_length_estimates(tmp_path):
    use_design("compact", "a4")
    try:
        assert 'w:pgSz w:w="11906"' in xml(render(PROFILE, TAILORED, tmp_path / "x.docx"))
        assert ai.default_budget(1)["lines"] == themes.COMPACT.lines_per_page("a4")
    finally:
        use_design(None, None)
    assert ai.default_budget(2) == {"lines": 110, "words": 1000, "measured": False}  # Classic on Letter


def test_theme_and_paper_are_settings(tmp_path):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    client = client_for(create_app(Store(private), FakeEngine()))
    s = client.get("/api/settings").json()
    assert s["theme"] == "classic" and [t["id"] for t in s["themes"]] == ["classic", "modern", "compact"]
    assert client.put("/api/settings", json={"theme": "modern", "paper": "a4"}).json()["paper"] == "a4"
    assert Store(private).settings()["theme"] == "modern"
    assert client.put("/api/settings", json={"theme": "fancy"}).status_code == 422
    assert client.put("/api/settings", json={"paper": "legal"}).status_code == 422


@pytest.mark.parametrize("theme", sorted(themes.THEMES))
def test_headings_stay_with_the_text_under_them(tmp_path, theme):
    """Section titles, company lines, job titles and scope lines are kept on the page of what follows,
    so a heading is never stranded at the bottom of a page. Bullets aren't (pages can break between them)."""
    doc = xml(render(PROFILE, TAILORED, tmp_path / "r.docx", theme=theme))
    paras = re.findall(r"<w:p\b[^>]*>(.*?)</w:p>", doc)
    keep = lambda needle: next("<w:keepNext/>" in p for p in paras if needle in p)  # noqa: E731
    assert keep("PROFESSIONAL EXPERIENCE") and keep("Acme Bank") and keep("Vice President | Detection Lead")
    assert keep("Led a team of 5 engineers protecting 20M+ customers.")
    assert not keep("Rebuilt Splunk detection logic")


def test_a_role_without_bullets_does_not_glue_itself_to_the_next_role(tmp_path):
    t = TAILORED.model_copy(deep=True)
    t.experience[0].bullets, t.experience[0].sub_roles = [], []  # Acme: title + scope only
    doc = xml(render(PROFILE, t, tmp_path / "r.docx"))
    paras = re.findall(r"<w:p\b[^>]*>(.*?)</w:p>", doc)
    keep = lambda needle: next("<w:keepNext/>" in p for p in paras if needle in p)  # noqa: E731
    assert keep("Acme Bank") and keep("Vice President | Detection Lead")  # company → title → scope stay together
    assert not keep("Led a team of 5 engineers protecting 20M+ customers.")  # …but the scope doesn't pull Telco


def test_comfortable_text_is_one_point_larger_and_standard_is_untouched(tmp_path):
    comfy = themes.get("classic", "comfortable")
    assert (comfy.body_size, comfy.date_size) == (21, 19)  # 10.5 pt body, 9.5 pt dates
    assert comfy.contact_size == themes.CLASSIC.contact_size  # the contact line stays on one line
    assert themes.get("classic", "standard") is themes.CLASSIC and themes.get("classic") is themes.CLASSIC
    assert comfy.lines_per_page("a4") < themes.CLASSIC.lines_per_page("a4")  # estimates follow the size
    use_design("classic", "a4", "comfortable")
    try:
        doc = xml(render(PROFILE, TAILORED, tmp_path / "c.docx"))
    finally:
        use_design(None, None)
    bullet = re.search(r'<w:sz w:val="(\d+)"/></w:rPr><w:t xml:space="preserve">•  Rebuilt Splunk', doc)
    assert bullet and bullet.group(1) == "21"  # bullets at 10.5 pt


def test_text_size_is_a_setting_with_comfortable_as_default(tmp_path):
    store = Store(tmp_path)
    client = client_for(create_app(store, FakeEngine({})))
    assert client.get("/api/settings").json()["text_size"] == "comfortable"
    assert client.put("/api/settings", json={"text_size": "standard"}).json()["text_size"] == "standard"
    assert client.put("/api/settings", json={"text_size": "huge"}).status_code == 422
