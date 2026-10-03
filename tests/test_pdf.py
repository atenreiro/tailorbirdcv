import shutil
import sys
import time
import zipfile
from pathlib import Path

import pytest

from autocv import pdf
from autocv.api import create_app
from autocv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"


def engines(word=True, libreoffice=True):
    return [{"id": "word", "name": "Microsoft Word", "available": word, "path": None, "version": None},
            {"id": "libreoffice", "name": "LibreOffice", "available": libreoffice, "path": None, "version": None}]


def make_docx(path: Path, text="returning 2–4 hours in 2019-2021", fonts=("Georgia", "Calibri")) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<w:document><w:t>{text}</w:t></w:document>')
        z.writestr("word/fontTable.xml", "".join(f'<w:font w:name="{f}"/>' for f in fonts))
        z.writestr("word/theme/theme1.xml", '<a:latin typeface="Aptos"/><a:font script="Thai" typeface="Leelawadee"/>')
    return path


@pytest.fixture
def docx(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCV_WORD_DIR", str(tmp_path / "word"))
    monkeypatch.setenv("AUTOCV_LO_PROFILE", str(tmp_path / "lo-profile"))
    monkeypatch.setattr(pdf, "detect", lambda: engines())
    return make_docx(tmp_path / "app" / "r.docx")


def fake_word(monkeypatch, code):
    """Stand in for osascript + Word: `code` runs with argv = [docx, pdf] in the work folder."""
    monkeypatch.setattr(pdf, "_command", lambda src, dst: [sys.executable, "-c", code, str(src), str(dst)])


# -- choosing the engine --------------------------------------------------------------
def test_word_is_the_default_when_both_are_installed():
    assert pdf.resolve(None, engines()) == "word"
    assert pdf.resolve("libreoffice", engines()) == "libreoffice"
    assert pdf.resolve("word", engines()) == "word"


def test_falls_back_to_whichever_is_installed():
    assert pdf.resolve(None, engines(word=False)) == "libreoffice"
    assert pdf.resolve("word", engines(word=False)) == "libreoffice"
    assert pdf.resolve("libreoffice", engines(libreoffice=False)) == "word"
    with pytest.raises(RuntimeError, match="install Microsoft Word or LibreOffice"):
        pdf.resolve(None, engines(False, False))


# -- Word -----------------------------------------------------------------------------
def test_stalled_word_is_killed_with_a_clear_message(docx, monkeypatch):
    fake_word(monkeypatch, "import time; time.sleep(30)")  # stand-in for a Word dialog
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="waiting on a dialog"):
        pdf.to_pdf(docx, timeout=1, engine="word")
    assert time.monotonic() - start < 5


def test_missing_output_is_reported(docx, monkeypatch):
    fake_word(monkeypatch, "import sys; sys.exit('no Word here')")
    with pytest.raises(RuntimeError, match="no Word here"):
        pdf.to_pdf(docx, timeout=10, engine="word")


def test_word_converts_in_one_fixed_folder_and_cleans_up(docx, monkeypatch, tmp_path):
    seen = tmp_path / "seen.txt"
    fake_word(monkeypatch, "import sys, shutil, pathlib; s, d = map(pathlib.Path, sys.argv[1:]);"
                           f"pathlib.Path({str(seen)!r}).write_text(str(s.parent));"
                           "shutil.copyfile(s, d)")
    out = pdf.to_pdf(docx, timeout=10)  # no preference → Word
    assert out == docx.with_suffix(".pdf") and out.read_bytes() == docx.read_bytes()  # Word gets the docx as is
    assert seen.read_text() == str((tmp_path / "word").resolve())  # Word only ever sees this folder
    assert [p.name for p in (tmp_path / "word").iterdir()] == [".lock"]  # staged copies removed


def test_word_script_never_activates_or_touches_other_documents():
    s = pdf._WORD_JXA
    assert "activate" not in s and "activeDocument" not in s
    assert "open -g -j" in s and "if (!wasRunning" in s


# -- LibreOffice ----------------------------------------------------------------------
FAKE_SOFFICE = """#!{python}
import sys, pathlib, json, zipfile
args = sys.argv[1:]
src = pathlib.Path(args[-1]); out = pathlib.Path(args[args.index("--outdir") + 1])
xml = zipfile.ZipFile(src).read("word/document.xml").decode()
pathlib.Path({log!r}).write_text(json.dumps({{"args": args, "xml": xml}}))
(out / (src.stem + ".pdf")).write_text("%PDF stand-in")
"""


@pytest.fixture
def soffice(tmp_path, monkeypatch):
    log = tmp_path / "soffice.json"
    exe = tmp_path / "bin" / "soffice"
    exe.parent.mkdir()
    exe.write_text(FAKE_SOFFICE.format(python=sys.executable, log=str(log)))
    exe.chmod(0o755)
    monkeypatch.setattr(pdf, "soffice", lambda: exe)
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    for name in ["Georgia Bold.ttf", "Calibri.ttf", "Calibrib.ttf", "Aptos-Bold-Italic.ttf",
                 "Aptos-Black.ttf", "Arial.ttf", "Leelawadee.ttf", "notes.txt"]:
        (fonts / name).write_bytes(b"font")
    monkeypatch.setattr(pdf, "font_dirs", lambda: [fonts, tmp_path / "missing"])
    return log


def test_libreoffice_runs_headless_with_its_own_profile(docx, soffice, tmp_path):
    import json
    out = pdf.to_pdf(docx, timeout=10, engine="libreoffice")
    assert out.read_text() == "%PDF stand-in"
    run = json.loads(soffice.read_text())
    profile = (tmp_path / "lo-profile").resolve()
    assert f"-env:UserInstallation={profile.as_uri()}" in run["args"] and "--headless" in run["args"]
    assert run["args"][run["args"].index("--convert-to") + 1] == "pdf"
    assert [p.name for p in (tmp_path / "word").iterdir()] == [".lock"]


def test_libreoffice_gets_glued_ranges_but_the_users_docx_is_untouched(docx, soffice):
    import json
    original = docx.read_bytes()
    pdf.to_pdf(docx, timeout=10, engine="libreoffice")
    xml = json.loads(soffice.read_text())["xml"]
    assert "2\u2060–\u20604" in xml and "2019\u2060-\u20602021" in xml
    assert docx.read_bytes() == original


def test_libreoffice_links_only_the_fonts_the_document_uses(docx, soffice, tmp_path):
    pdf.to_pdf(docx, timeout=10, engine="libreoffice")
    linked = tmp_path / "lo-profile" / "user" / "fonts"
    assert sorted(p.name for p in linked.iterdir()) == ["Aptos-Bold-Italic.ttf", "Calibri.ttf", "Calibrib.ttf",
                                                        "Georgia Bold.ttf"]  # not Black, Arial or script fonts
    assert all(p.is_symlink() for p in linked.iterdir())
    pdf.to_pdf(docx, timeout=10, engine="libreoffice")  # idempotent


def test_libreoffice_failure_is_reported(docx, soffice, monkeypatch, tmp_path):
    bad = tmp_path / "bin" / "bad"
    bad.write_text(f"#!{sys.executable}\nprint('Error: source file could not be loaded')\n")
    bad.chmod(0o755)
    monkeypatch.setattr(pdf, "soffice", lambda: bad)
    with pytest.raises(RuntimeError, match="LibreOffice did not produce the PDF: Error: source file could not be loaded"):
        pdf.to_pdf(docx, timeout=10, engine="libreoffice")


def test_glue_ranges_leaves_other_dashes_alone():
    xml = '<w:t xml:space="preserve">2–4, 2019-2021, ISO-27001, A–Z, 5 – 6</w:t>'
    assert pdf.glue_ranges(xml) == \
        '<w:t xml:space="preserve">2\u2060–\u20604, 2019\u2060-\u20602021, ISO-27001, A–Z, 5 – 6</w:t>'


def test_glue_ranges_only_touches_text_runs():
    xml = ('<w:p w14:paraId="1-2"><w:instrText>HYPERLINK "https://x.io/2-4"</w:instrText>'
           '<w:t>1-3</w:t><w:tbl w:w="10-20"/></w:p>')
    assert pdf.glue_ranges(xml) == xml.replace("<w:t>1-3</w:t>", "<w:t>1\u2060-\u20603</w:t>")


def test_word_is_only_quit_when_nothing_else_is_open():
    s = pdf._WORD_JXA
    assert "if (!wasRunning && word.documents.length === 0) word.quit({saving: 'ask'})" in s


def test_word_only_ever_addresses_our_document_by_name():
    s = pdf._WORD_JXA
    assert "word.documents.byName(base)" in s and "ours.close(" in s and "ours.saveAs(" in s
    assert "documents[" not in s and "documents()" not in s  # positions shift when the user opens a file


# -- settings -------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    found = {"engines": engines()}
    monkeypatch.setattr(pdf, "detect", lambda: found["engines"])
    c = client_for(create_app(Store(private)))
    c.found = found
    return c


def test_settings_default_to_word_when_both_are_installed(client):
    s = client.get("/api/settings").json()
    assert s["pdf_engine"] is None and s["pdf_effective"] == "word"
    assert [e["id"] for e in s["pdf_engines"] if e["available"]] == ["word", "libreoffice"]


def test_choosing_libreoffice_persists(client, tmp_path):
    s = client.put("/api/settings", json={"pdf_engine": "libreoffice"}).json()
    assert s["pdf_engine"] == "libreoffice" and s["pdf_effective"] == "libreoffice"
    assert Store(tmp_path / "private").settings()["pdf_engine"] == "libreoffice"
    assert client.get("/api/settings").json()["pdf_effective"] == "libreoffice"


def test_an_engine_that_isnt_installed_cant_be_chosen(client):
    client.found["engines"] = engines(libreoffice=False)
    r = client.put("/api/settings", json={"pdf_engine": "libreoffice"})
    assert r.status_code == 400 and "isn't installed" in r.json()["detail"]
    assert client.put("/api/settings", json={"pdf_engine": "pages"}).status_code == 422


def test_a_chosen_engine_that_disappears_falls_back(client):
    client.put("/api/settings", json={"pdf_engine": "libreoffice"})
    client.found["engines"] = engines(libreoffice=False)
    s = client.get("/api/settings").json()
    assert s["pdf_engine"] == "libreoffice" and s["pdf_effective"] == "word"


def test_settings_need_the_autocv_header(client):
    from fastapi.testclient import TestClient
    bare = TestClient(client.app, base_url="http://127.0.0.1")
    assert bare.put("/api/settings", json={"pdf_engine": "word"}).status_code == 403

