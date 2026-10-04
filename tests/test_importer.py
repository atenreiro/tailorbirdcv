"""First-run import: any resume → a draft profile the user reviews before saving (fictional data only)."""

import base64
import io
import shutil
from pathlib import Path

import pytest

from autocv import importer
from autocv.api import create_app
from autocv.engine import FakeEngine
from autocv.schema import MasterProfile
from autocv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"

RESUME = """Jordan Rivera
Senior Product Designer
Lisbon, Portugal · +351 900 000 000 · jordan@example.com · jordanrivera.design

SUMMARY
Product designer with 9 years in consumer apps. Led design for a 4M-user banking app.

EXPERIENCE
Northwind Bank, Lisbon            2021 – Present
Lead Product Designer
Design lead for the mobile app.
• Redesigned onboarding, raising completion from 61% to 78%.
• Built the design system used by 5 product teams.

EDUCATION
• BA Design — University of Porto (2014)

SKILLS
Design: Figma · Prototyping · User research
"""

TRANSCRIPTION = {
    "contact": {"name": "Jordan Rivera", "location": "Lisbon, Portugal", "phone": "+351 900 000 000",
                "email": "jordan@example.com", "links": [{"text": "jordanrivera.design", "url": "https://jordanrivera.design"}]},
    "headline": "Senior Product Designer",
    "summary": "Product designer with 9 years in consumer apps. Led design for a 4M-user banking app.",
    "highlights": [],
    "skills": [{"category": "Design", "items": ["Figma", "Prototyping", "User research"]}],
    "roles": [{"employer": "Northwind Bank", "location": "Lisbon", "title": "Lead Product Designer",
               "dates": "2021 – Present", "scope": "Design lead for the mobile app.",
               "achievements": ["Redesigned onboarding, raising completion from 61% to 78%.",
                                "Built the design system used by 5 product teams, cutting UI bugs by 40%."],
               "sub_roles": []}],
    "projects": [], "education": [{"label": "BA Design", "text": "University of Porto (2014)"}], "extras": [],
}


def test_the_ai_only_transcribes_and_autocv_assigns_ids():
    profile = importer.build_profile(TRANSCRIPTION)
    MasterProfile.model_validate(profile)  # valid as is
    role = profile["roles"][0]
    assert role["id"] == "northwind-bank" and role["scope"]["id"] == "northwind-bank.scope"
    assert [a["id"] for a in role["achievements"]] == ["northwind-bank.a1", "northwind-bank.a2"]
    assert [f["id"] for f in profile["summary_facts"]] == ["summary.s1", "summary.s2"]
    assert profile["education"][0]["id"] == "edu.ba-design"
    assert profile["headlines"][0] == {"id": "h.main", "text": "Senior Product Designer", "tracks": ["manager", "ic", "hybrid"]}


def test_text_that_isnt_in_the_original_is_flagged_for_review():
    profile = importer.build_profile(TRANSCRIPTION)
    # the second bullet gained "cutting UI bugs by 40%", which the resume never says
    assert importer.unverified(profile, RESUME) == ["northwind-bank.a2"]


def test_duplicate_ids_get_suffixes():
    raw = {**TRANSCRIPTION, "roles": [TRANSCRIPTION["roles"][0], {**TRANSCRIPTION["roles"][0], "dates": "2018 – 2021"}]}
    ids = [r["id"] for r in importer.build_profile(raw)["roles"]]
    assert ids == ["northwind-bank", "northwind-bank-2"]
    MasterProfile.model_validate(importer.build_profile(raw))


def test_text_is_read_from_docx_pdf_and_plain_text():
    from docx import Document
    doc = Document()
    for line in RESUME.splitlines():
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    assert "Northwind Bank" in importer.extract_text("cv.docx", buf.getvalue())
    assert "Northwind Bank" in importer.extract_text("cv.txt", RESUME.encode())
    with pytest.raises(importer.ImportError_, match=r"\.docx"):
        importer.extract_text("cv.doc", b"x" * 200)
    with pytest.raises(importer.ImportError_, match="Paste the text"):
        importer.extract_text("scan.txt", b"   ")


@pytest.fixture
def new_user(tmp_path):
    engine = FakeEngine({"import": TRANSCRIPTION})
    return client_for(create_app(Store(tmp_path / "private"), engine)), tmp_path / "private", engine


def test_import_returns_a_draft_and_saves_nothing(new_user):
    client, private, engine = new_user
    assert client.get("/api/setup").json()["has_profile"] is False
    r = client.post("/api/profile/import", json={"filename": "cv.txt", "data": base64.b64encode(RESUME.encode()).decode()})
    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["contact"]["name"] == "Jordan Rivera" and body["unverified"] == ["northwind-bank.a2"]
    assert not (private / "profile.yaml").exists()
    assert "RESUME:" in engine.calls[0][1] and "Northwind Bank" in engine.calls[0][1]


def test_the_reviewed_draft_becomes_the_profile(new_user):
    client, private, _ = new_user
    draft = client.post("/api/profile/import", json={"text": RESUME}).json()["profile"]
    refused = client.post("/api/profile/create", json={"profile": draft})  # a2 says "40%", the CV doesn't
    assert refused.status_code == 422 and refused.json()["detail"]["paths"] == ["northwind-bank.a2"]
    assert not (private / "profile.yaml").exists()
    saved = client.post("/api/profile/create", json={"profile": draft, "confirmed": ["northwind-bank.a2"]})
    assert saved.status_code == 200 and (private / "profile.yaml").exists()
    assert client.get("/api/setup").json()["has_profile"] is True
    assert client.post("/api/profile/create", json={"profile": draft}).status_code == 409   # never overwrites
    assert client.post("/api/profile/import", json={"text": RESUME}).status_code == 409


def test_a_blank_profile_can_be_started(new_user):
    client, private, _ = new_user
    assert client.post("/api/profile/create", json={"blank": {"name": "Sam Lee", "location": "Toronto"}}).status_code == 422
    r = client.post("/api/profile/create", json={"blank": {"name": "Sam Lee", "location": "Toronto", "headline": "Data Analyst"}})
    assert r.status_code == 200 and r.json()["profile"]["contact"]["name"] == "Sam Lee"
    assert r.json()["profile"]["headlines"][0]["text"] == "Data Analyst"  # every resume needs a headline
    assert client.get("/api/profile").status_code == 200


def test_an_existing_profile_is_never_replaced_by_an_import(tmp_path):
    private = tmp_path / "private"
    shutil.copytree(FIX, private, ignore=shutil.ignore_patterns("tailored.yaml"))
    client = client_for(create_app(Store(private), FakeEngine({"import": TRANSCRIPTION})))
    assert client.post("/api/profile/import", json={"text": RESUME}).status_code == 409


def test_without_a_headline_line_the_latest_title_is_used():
    raw = {**TRANSCRIPTION, "headline": ""}
    assert importer.build_profile(raw)["headlines"][0]["text"] == "Lead Product Designer"


def test_the_demo_engine_works_for_a_brand_new_user(tmp_path, monkeypatch):
    from autocv.demo import demo_engine
    monkeypatch.setenv("AUTOCV_PRIVATE", str(tmp_path / "private"))
    client = client_for(create_app(Store(tmp_path / "private"), demo_engine()))
    draft = client.post("/api/profile/import", json={"text": RESUME}).json()
    assert draft["profile"]["contact"]["name"] == "Jordan Rivera"
    saved = client.post("/api/profile/create", json={"profile": draft["profile"], "confirmed": draft["unverified"]})
    assert saved.status_code == 200
    app_id = client.post("/api/applications", json={"jd": "Designer — Contoso\n" + "x " * 80}).json()["id"]
    assert client.post(f"/api/applications/{app_id}/analyze").status_code == 200
    composed = client.post(f"/api/applications/{app_id}/compose", json={}).json()
    assert composed["report"]["ok"], composed["report"]


# ---- second audit: verification gaps ------------------------------------------------------------

SOURCE2 = """Jane Example
Acme Bank — Singapore
Vice President, Jan 2022 – Present
• Saved US$12M by consolidating vendors.
• Built C++ tooling for 40 engineers.
• Stayed ahead of security deadlines across 12M+ accounts.
Telco Co — Leeds
Head of Network, Jan 2012 – Dec 2021
• Negotiated vendor contracts saving US$1.7M in a single year.
"""


def _two_roles(acme_bullets, telco_bullets, acme_title="Vice President", telco_title="Head of Network"):
    ach = lambda rid, items: [{"id": f"{rid}.a{i + 1}", "text": t} for i, t in enumerate(items)]  # noqa: E731
    return {"contact": {"name": "Jane Example"}, "headlines": [], "roles": [
        {"id": "acme", "employer": "Acme Bank", "location": "Singapore", "title": acme_title,
         "dates": "Jan 2022 – Present", "achievements": ach("acme", acme_bullets), "sub_roles": []},
        {"id": "telco", "employer": "Telco Co", "location": "Leeds", "title": telco_title,
         "dates": "Jan 2012 – Dec 2021", "achievements": ach("telco", telco_bullets), "sub_roles": []}]}


@pytest.mark.parametrize("bullet", ["Saved US$1.2M by consolidating vendors.", "Built C# tooling for 40 engineers.",
                                    "Built C++ tooling for 40% engineers.", "Stayed ahead of security deadlines across 12M accounts."])
def test_symbols_and_decimals_must_match(bullet):
    p = _two_roles([bullet], ["Negotiated vendor contracts saving US$1.7M in a single year."])
    assert "acme.a1" in importer.unverified(p, SOURCE2), bullet


def test_the_joined_fallback_needs_word_boundaries():
    p = _two_roles(["Saved US$12M by consolidating vendors."], [], acme_title="Head of Security")
    assert "acme.title" in importer.unverified(p, SOURCE2)  # not "ahead of security"


def test_facts_cannot_move_between_employers():
    swapped = _two_roles(["Negotiated vendor contracts saving US$1.7M in a single year."],
                         ["Saved US$12M by consolidating vendors."])
    assert {"acme.a1", "telco.a1"} <= set(importer.unverified(swapped, SOURCE2))
    right = _two_roles(["Saved US$12M by consolidating vendors."],
                       ["Negotiated vendor contracts saving US$1.7M in a single year."])
    assert importer.unverified(right, SOURCE2) == []
