"""Resume themes: Classic is the original design byte-for-byte; others change only the look."""

import re
import shutil
import zipfile
from pathlib import Path

import pytest

from autocv import ai, themes
from autocv.api import create_app
from autocv.engine import FakeEngine
from autocv.render import docx_text, render, use_design
from autocv.schema import load_profile, load_tailored
from autocv.store import Store
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
