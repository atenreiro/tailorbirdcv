"""Fitting the page: measuring the real PDF, learning lines-per-page per design, the length budget,
and "Fill the page" (relevant unused evidence, proposed for review, never saved)."""

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from tailorbirdcv import ai, fit, themes
from tailorbirdcv import pdf as pdfmod
from tailorbirdcv.api import create_app
from tailorbirdcv.engine import FakeEngine
from tailorbirdcv.render import use_design
from tailorbirdcv.schema import load_profile, load_tailored
from tailorbirdcv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
TAILORED = yaml.safe_load((FIX / "tailored.yaml").read_text(encoding="utf-8"))
A4_H = 841.89
TOP = BOTTOM = 850 / 20  # Classic's margins, in points
USABLE = A4_H - TOP - BOTTOM


def make_pdf(path: Path, pages: list[float]) -> Path:
    """A PDF whose text on each page reaches the given share of Classic's usable height."""
    w = PdfWriter()
    for depth in pages:
        page = w.add_blank_page(595.28, A4_H)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
        stream = DecodedStreamObject()
        lowest = A4_H - TOP - depth * USABLE
        stream.set_data(f"BT /F1 10 Tf 72 {A4_H - TOP - 12:.2f} Td (top) Tj ET\n"
                        f"BT /F1 10 Tf 72 {lowest:.2f} Td (last line) Tj ET\n".encode())
        page[NameObject("/Contents")] = w._add_object(stream)
    with open(path, "wb") as f:
        w.write(f)
    return path


def test_page_fill_measures_how_far_down_the_text_reaches(tmp_path):
    fills = fit.page_fill(make_pdf(tmp_path / "r.pdf", [0.95, 0.5]), themes.CLASSIC)
    assert fills == [pytest.approx(0.95, abs=0.01), pytest.approx(0.5, abs=0.01)]


def test_each_design_learns_its_own_lines_per_page(tmp_path):
    classic = themes.CLASSIC
    assert fit.lines_factor(tmp_path, classic, "a4") == 1.0  # nothing measured yet
    nominal = classic.lines_per_page("a4")
    fit.record(tmp_path, classic, "a4", 110, [1.0, 0.76])  # 110 estimated lines took 1.76 pages
    first = 110 / 1.76 / nominal
    assert fit.lines_factor(tmp_path, classic, "a4") == pytest.approx(first, abs=1e-3)
    fit.record(tmp_path, classic, "a4", 100, [1.0, 1.0])  # a second build moves it part of the way
    assert fit.lines_factor(tmp_path, classic, "a4") == pytest.approx(0.6 * first + 0.4 * (50 / nominal), abs=1e-3)
    assert fit.lines_factor(tmp_path, classic, "letter") == 1.0          # other designs are untouched
    assert fit.lines_factor(tmp_path, themes.COMPACT, "a4") == 1.0
    fit.record(tmp_path, themes.COMPACT, "a4", 10, [0.2])                # too little text to learn from
    assert fit.lines_factor(tmp_path, themes.COMPACT, "a4") == 1.0
    fit.record(tmp_path, themes.COMPACT, "a4", 500, [1.0])               # absurd samples are clamped
    assert fit.lines_factor(tmp_path, themes.COMPACT, "a4") == 1.3
    data = json.loads((tmp_path / "calibration.json").read_text(encoding="utf-8"))
    assert data["classic/a4"]["builds"] == 2


def test_room_on_the_last_page():
    assert fit.room_lines([1.0, 0.5], 60) == int((fit.FILL_GOAL - 0.5) * 60)
    assert fit.room_lines([1.0, 0.95], 60) == 0 and fit.room_lines([], 60) == 0


def test_the_budget_is_what_the_design_holds_not_the_base_resume_length(tmp_path):
    """A short base resume used to shrink the budget for every design; now the page limit in the active
    design sets the lines, and the base only calibrates words per line. Real PDFs correct it further."""
    profile, base = load_profile(FIX / "profile.yaml"), load_tailored(FIX / "tailored.yaml")
    ai.use_context(ai.Context(pages=2, private=tmp_path))
    use_design("compact", "a4")
    try:
        budget = ai.length_budget(profile, base)
        assert budget["lines"] == ai.default_budget()["lines"] == themes.COMPACT.lines_per_page("a4") * 2
        assert budget["measured"] and budget["words"] > 0
        fit.record(tmp_path, themes.COMPACT, "a4", 151, [1.0, 1.0])  # Word fits ~20% more than estimated
        assert ai.length_budget(profile, base)["lines"] > budget["lines"]
    finally:
        use_design(None, None)
        ai.use_context(ai.Context())


# ---- the API: build measures, /fill proposes ----------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    profile = yaml.safe_load((FIX / "profile.yaml").read_text(encoding="utf-8"))
    profile["roles"][0]["achievements"].append(  # fictional, unused by the tailored fixture
        {"id": "acme-bank.a3", "text": "Wrote Python tooling that triages Splunk alerts automatically."})
    (private / "profile.yaml").write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    shutil.copy(FIX / "tailored.yaml", private / "source" / "base_tailored.yaml")
    depth = {"last": 0.4}

    def fake_to_pdf(docx, pdf=None, timeout=0, engine=None):  # stands in for Word/LibreOffice
        return make_pdf(pdf or docx.with_suffix(".pdf"), [1.0, depth["last"]])
    monkeypatch.setattr(pdfmod, "to_pdf", fake_to_pdf)
    monkeypatch.setattr(pdfmod, "resolve", lambda preferred=None, engines=None: preferred or "word")

    def filled(prompt):
        t = copy.deepcopy(TAILORED)
        t["experience"][0]["bullets"].append(
            {"text": "Wrote Python tooling that triages Splunk alerts automatically.", "sources": ["acme-bank.a3"]})
        return t
    analysis = {"company": "Example Capital", "role": "Lead", "industry": "quant", "track": "ic", "seniority": "S",
                "location": "SG", "summary": "x", "requirements": [], "keywords": [], "known_gaps": [], "questions": []}
    engine = FakeEngine({"analyze": analysis, "compose": TAILORED, "repair": TAILORED, "trim": TAILORED,
                         "fill": filled})
    store = Store(private)
    store.save_settings({"paper": "a4"})
    return client_for(create_app(store, engine)), store, engine, depth


def composed(client):
    jd = "# Detection Lead — Example Capital\n\n" + "We need a hands-on detection engineering lead. " * 10
    app_id = client.post("/api/applications", json={"jd": jd, "company": "Example Capital", "role": "Lead"}).json()["id"]
    client.post(f"/api/applications/{app_id}/analyze")
    client.post(f"/api/applications/{app_id}/compose", json={})
    return app_id


def test_a_build_measures_the_pdf_and_fill_proposes_relevant_unused_evidence(env):
    client, store, engine, _ = env
    app_id = composed(client)
    assert client.post(f"/api/applications/{app_id}/fill").status_code == 409  # build first
    data = client.post(f"/api/applications/{app_id}/build").json()
    fill = data["meta"]["fill"]
    assert fill["pages"] == [pytest.approx(1.0, abs=0.01), pytest.approx(0.4, abs=0.01)]
    assert fill["room"] >= fit.ROOM_MIN_LINES
    assert (store.private / "calibration.json").exists()  # the design learned from this PDF

    before = client.get(f"/api/applications/{app_id}").json()["tailored"]
    res = client.post(f"/api/applications/{app_id}/fill").json()
    proposal = res["fill_proposal"]
    texts = [b["text"] for b in proposal["tailored"]["experience"][0]["bullets"]]
    assert "Wrote Python tooling that triages Splunk alerts automatically." in texts
    assert 0 < proposal["added_lines"] <= proposal["room"]
    assert res["tailored"] == before  # proposed, never saved
    prompt = next(p for task, p in engine.calls if task == "fill")
    assert f"about {fill['room']} more lines" in prompt


def test_fill_is_refused_when_the_last_page_is_full_or_the_files_are_stale(env):
    client, store, _, depth = env
    app_id = composed(client)
    depth["last"] = 0.95
    client.post(f"/api/applications/{app_id}/build")
    r = client.post(f"/api/applications/{app_id}/fill")
    assert r.status_code == 409 and "full enough" in r.json()["detail"]
    depth["last"] = 0.3
    client.post(f"/api/applications/{app_id}/build")
    t = client.get(f"/api/applications/{app_id}").json()["tailored"]
    t["summary"]["text"] = "Security VP with 15 years across banking and telecom."
    client.put(f"/api/applications/{app_id}/tailored", json={**t, "highlights": t["highlights"][:0]})
    r = client.post(f"/api/applications/{app_id}/fill")
    assert r.status_code == 409 and "Build the PDF first" in r.json()["detail"]


def test_fill_never_drops_existing_lines_or_brings_back_removed_ones(env):
    client, store, engine, _ = env
    app_id = composed(client)
    client.post(f"/api/applications/{app_id}/build")

    def drops_a_bullet(prompt):
        t = copy.deepcopy(TAILORED)
        t["experience"][0]["bullets"] = t["experience"][0]["bullets"][:1] + [
            {"text": "Wrote Python tooling that triages Splunk alerts automatically.", "sources": ["acme-bank.a3"]}]
        return t
    engine.responses["fill"] = drops_a_bullet
    assert client.post(f"/api/applications/{app_id}/fill").json()["fill_proposal"] is None

    # the candidate removed a bullet from the AI's draft; a fill that re-adds it is refused
    t = client.get(f"/api/applications/{app_id}").json()["tailored"]
    removed = t["experience"][0]["bullets"].pop()
    client.put(f"/api/applications/{app_id}/tailored", json=t)
    client.post(f"/api/applications/{app_id}/build")

    def re_adds(prompt):
        t2 = copy.deepcopy(t)
        t2["experience"][0]["bullets"].append(removed)
        return t2
    engine.responses["fill"] = re_adds
    assert client.post(f"/api/applications/{app_id}/fill").json()["fill_proposal"] is None
    assert removed["sources"][0] in next(p for task, p in engine.calls if task == "fill").split("removed")[1]


def test_fill_needs_a_build_in_the_current_design_and_within_the_limit(env):
    client, store, _, depth = env
    app_id = composed(client)
    client.post(f"/api/applications/{app_id}/build")
    assert client.get(f"/api/applications/{app_id}").json()["meta"]["fill"]["design"] == "classic+comfortable/a4"
    store.save_settings({"paper": "letter"})  # measured on A4: no longer meaningful
    assert client.get(f"/api/applications/{app_id}").json()["meta"]["fill"] is None
    assert client.post(f"/api/applications/{app_id}/fill").status_code == 409
