"""The first-run setup wizard: progress and the imported draft survive a refresh; the profile is saved
only after every line that doesn't match the CV word-for-word is fixed, removed or confirmed."""

import copy
import json
import shutil
from pathlib import Path

import pytest

from tailorbirdcv import importer
from tailorbirdcv.api import create_app
from tailorbirdcv.engine import FakeEngine
from tailorbirdcv.store import Store
from conftest import client_for
from test_importer import RESUME, TRANSCRIPTION

FIX = Path(__file__).parent / "fixtures"
TRANSCRIPTION = {**TRANSCRIPTION, "suggested_targets": {"field": "product design", "seniority": "senior",
                                                          "roles": "design lead roles", "region": "Lisbon",
                                                          "spelling": "UK"}}


@pytest.fixture
def wizard(tmp_path):
    private = tmp_path / "private"
    client = client_for(create_app(Store(private), FakeEngine({"import": TRANSCRIPTION})))
    return client, Store(private)


def test_a_new_install_starts_the_wizard_and_an_existing_one_never_does(wizard, tmp_path):
    client, _ = wizard
    s = client.get("/api/setup").json()
    assert s["has_profile"] is False and s["completed"] is False and s["step"] == "welcome"
    old = tmp_path / "old"
    shutil.copytree(FIX, old, ignore=shutil.ignore_patterns("tailored.yaml", "*.xml"))
    assert Store(old).setup_state() == {"completed": True, "step": "welcome"}  # predates the wizard


def test_progress_and_the_draft_survive_a_refresh(wizard):
    client, store = wizard
    assert client.put("/api/setup", json={"step": "upload"}).json()["step"] == "upload"
    assert client.put("/api/setup", json={"step": "nowhere"}).status_code == 422
    imported = client.post("/api/profile/import", json={"text": RESUME}).json()
    assert imported["suggested_targets"]["field"] == "product design" and imported["pages"] is None
    s = client.get("/api/setup").json()  # "refresh"
    assert s["step"] == "review" and s["draft"]["profile"] == imported["profile"]
    assert s["draft"]["unverified"] == ["northwind-bank.a2"] and "source" not in s["draft"]
    assert not store.profile_path.exists()  # nothing saved by the import


def test_flagged_lines_must_be_fixed_removed_or_confirmed(wizard):
    client, store = wizard
    draft = client.post("/api/profile/import", json={"text": RESUME}).json()["profile"]
    bullet = draft["roles"][0]["achievements"][1]
    assert client.post("/api/profile/create", json={"profile": draft}).status_code == 422

    fixed = copy.deepcopy(draft)  # fixed to the CV's own words: no confirmation needed
    fixed["roles"][0]["achievements"][1]["text"] = "Built the design system used by 5 product teams."
    assert client.post("/api/profile/create", json={"profile": fixed}).status_code == 200
    store.profile_path.unlink()

    edited = copy.deepcopy(draft)  # edited, but still not the CV's words: must be confirmed
    edited["roles"][0]["achievements"][1]["text"] = "Built a design system for 5 teams."
    r = client.post("/api/profile/create", json={"profile": edited})
    assert r.status_code == 422 and r.json()["detail"]["paths"] == [bullet["id"]]
    assert client.post("/api/profile/create", json={"profile": edited, "confirmed": [bullet["id"]]}).status_code == 200
    saved = store.profile().roles[0].achievements[1]
    assert saved.note == importer.CONFIRMED_NOTE  # provenance kept
    store.profile_path.unlink()

    removed = copy.deepcopy(draft)
    del removed["roles"][0]["achievements"][1]
    assert client.post("/api/profile/create", json={"profile": removed}).status_code == 200


def test_a_save_without_an_import_is_refused(tmp_path):
    client = client_for(create_app(Store(tmp_path / "p"), FakeEngine()))
    profile = importer.build_profile(TRANSCRIPTION)
    assert client.post("/api/profile/create", json={"profile": profile}).status_code == 409


def test_matching_is_whole_words_and_covers_every_field():
    source = "Jordan Rivera · Lisbon · jordan@example.com · jordanrivera.design\nGood laws. Northwind Bank 2021 – Present"
    profile = importer.build_profile({
        **TRANSCRIPTION,
        "contact": {"name": "Jordan Rivera", "location": "New York", "phone": "", "email": "jordan@evil.com",
                    "links": [{"text": "jordanrivera.design", "url": "https://jordanrivera.design/"},
                              {"text": "github", "url": "https://github.com/jrivera"}]},
        "skills": [{"category": "Languages", "items": ["Go", "AWS"]}],
        "roles": [{**TRANSCRIPTION["roles"][0], "location": "Lisbon", "dates": "2019 – Present", "achievements": [],
                   "scope": ""}],
        "education": [], "headline": "Senior Product Designer"})
    flagged = importer.unverified(profile, source)
    for path in ("contact.location", "contact.email", "contact.links[1].text", "contact.links[1].url",
                 "skills[0].category", "skills[0].items[0]", "skills[0].items[1]", "northwind-bank.dates",
                 "headlines[0]", "northwind-bank.title"):
        assert path in flagged, path
    for path in ("contact.name", "contact.links[0].text", "contact.links[0].url", "northwind-bank.employer",
                 "northwind-bank.location"):
        assert path not in flagged, path


def test_long_items_split_at_pdf_line_ends_still_match():
    profile = importer.build_profile({**TRANSCRIPTION, "roles": [{**TRANSCRIPTION["roles"][0], "achievements": [
        "Redesigned onboarding, raising completion from 61% to 78%."]}]})
    source = RESUME.replace("Redesigned onboarding", "Rede-\nsigned onboarding")
    assert "northwind-bank.a1" not in importer.unverified(profile, source)


def test_finishing_marks_setup_done_and_forgets_the_draft(wizard):
    client, store = wizard
    draft = client.post("/api/profile/import", json={"text": RESUME}).json()
    client.post("/api/profile/create", json={"profile": draft["profile"], "confirmed": draft["unverified"]})
    client.put("/api/settings", json={"theme": "modern"})  # saving settings keeps the wizard's progress
    assert client.get("/api/setup").json()["step"] == "targets"
    done = client.post("/api/setup/finish").json()
    assert done["completed"] is True and store.setup_draft() is None
    assert json.loads(store.settings_path.read_text(encoding="utf-8"))["setup"]["completed"] is True


def test_starting_over_forgets_the_draft(wizard):
    client, store = wizard
    client.post("/api/profile/import", json={"text": RESUME})
    assert "draft" not in client.delete("/api/setup/draft").json()


def test_encrypted_or_broken_pdfs_get_a_friendly_error(wizard):
    import base64
    client, _ = wizard
    r = client.post("/api/profile/import", json={"filename": "cv.pdf", "data": base64.b64encode(b"%PDF-1.7 broken").decode()})
    assert r.status_code == 422 and "Paste the text" in r.json()["detail"]


def test_the_browser_install_reports_its_state(wizard, monkeypatch):
    from tailorbirdcv import doctor
    client, _ = wizard
    monkeypatch.setattr(doctor, "browser_installed", lambda: True)
    assert client.get("/api/setup/browser").json()["state"] == "done"
