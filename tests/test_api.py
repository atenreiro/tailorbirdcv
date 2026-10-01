"""Web API flow on the fictional fixture profile with a fake AI engine."""

import shutil
from pathlib import Path

import pytest
import yaml
from conftest import client_for

from autocv.api import create_app
from autocv.engine import FakeEngine
from autocv.store import Store

FIX = Path(__file__).parent / "fixtures"
JD = "# Detection Lead — Example Capital\n\n" + "We need a hands-on detection engineering lead. " * 10
TAILORED = yaml.safe_load((FIX / "tailored.yaml").read_text())

ANALYSIS = {
    "company": "Example Capital", "role": "Detection Lead", "industry": "quant", "track": "ic",
    "seniority": "Senior", "location": "Singapore", "summary": "Hands-on detection role.",
    "requirements": [{"text": "Detection engineering", "priority": "must", "status": "strong",
                      "evidence": ["acme-bank.a1", "not.an.id"], "note": ""}],
    "keywords": [{"term": "detection engineering", "priority": "must", "aliases": []},
                 {"term": "Kubernetes", "priority": "nice", "aliases": []}],
    "questions": [{"id": "q1", "requirement": "Kubernetes", "question": "Any Kubernetes work?", "prefill_from": ""}],
    "known_gaps": [],
}


def _bad_then_good():
    calls = {"n": 0}

    def compose(_prompt):
        calls["n"] += 1
        bad = yaml.safe_load(yaml.safe_dump(TAILORED))
        bad["highlights"][0]["text"] = "Cut false positives by 95% with Kubernetes."
        return bad

    return compose


@pytest.fixture
def env(tmp_path):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    shutil.copy(FIX / "tailored.yaml", private / "source" / "base_tailored.yaml")
    engine = FakeEngine({
        "analyze": ANALYSIS,
        "propose_evidence": {"proposals": [{"question_id": "q1", "target": "acme-bank",
                                            "text": "Hardened Kubernetes clusters.",
                                            "skills": [{"category": "Platforms", "item": "Kubernetes"}]}]},
        "compose": _bad_then_good(),
        "repair": TAILORED,
    })
    store = Store(private)
    return client_for(create_app(store, engine)), store, engine


def test_full_flow(env):
    client, store, engine = env
    assert client.get("/api/engine").json()["ready"]

    app_id = client.post("/api/applications", json={"jd": JD}).json()["id"]
    data = client.post(f"/api/applications/{app_id}/analyze").json()
    assert data["id"].endswith("_example-capital_detection-lead")  # folder renamed once company is known
    app_id = data["id"]
    assert data["meta"]["company"] == "Example Capital"
    assert data["meta"]["status"] == "analyzed"
    assert data["analysis"]["requirements"][0]["evidence"] == ["acme-bank.a1"]  # unknown id dropped

    # compose: first draft fails the fact-check, the repair round fixes it
    data = client.post(f"/api/applications/{app_id}/compose", json={}).json()
    assert data["report"]["ok"], data["report"]
    assert data["meta"]["repair_rounds"] == 1
    assert [c[0] for c in engine.calls] == ["analyze", "compose", "repair"]
    assert data["ats"]["coverage"]["must"] == {"hit": 1, "total": 1}

    # a manual edit that invents a number is reported, and blocks the build
    edited = data["tailored"]
    edited["highlights"][0]["text"] = "Cut false positives by 99%."
    data = client.put(f"/api/applications/{app_id}/tailored", json=edited).json()
    assert not data["report"]["ok"]
    assert client.post(f"/api/applications/{app_id}/build?pdf=false").status_code == 409

    edited["highlights"][0]["text"] = "Cut false positives by over 65%."
    client.put(f"/api/applications/{app_id}/tailored", json=edited)
    data = client.post(f"/api/applications/{app_id}/build?pdf=false").json()
    assert data["meta"]["status"] == "built"
    assert data["files"] == ["Jane_Example_Resume.docx"]
    assert client.get(f"/api/applications/{app_id}/files/{data['files'][0]}").status_code == 200

    # applying freezes the sent files, so it needs a PDF (builds here skip Word)
    assert client.patch(f"/api/applications/{app_id}", json={"status": "applied"}).status_code == 409
    (store.app_path(app_id) / "Jane_Example_Resume.pdf").write_bytes(b"%PDF-1.4 stand-in")
    assert client.patch(f"/api/applications/{app_id}", json={"status": "applied"}).json()["status"] == "applied"
    assert client.get("/api/applications").json()[0]["status"] == "applied"


def test_gap_answer_becomes_evidence_only_when_approved(env):
    client, store, _ = env
    app_id = client.post("/api/applications", json={"jd": JD}).json()["id"]
    proposals = client.post(f"/api/applications/{app_id}/proposals", json=[
        {"question_id": "q1", "question": "Any Kubernetes work?", "answer": "Hardened clusters at Acme."}]).json()
    assert proposals[0]["text"] == "Hardened Kubernetes clusters."
    assert "Kubernetes" not in store.profile_path.read_text()  # nothing saved yet

    p = proposals[0]
    res = client.post("/api/profile/evidence", json={"target": p["target"], "text": p["text"], "skills": p["skills"]}).json()
    assert res["id"] == "acme-bank.a3"
    profile = store.profile()
    added = profile.role("acme-bank").achievements[-1]
    assert (added.source, added.in_base_resume) == ("interview", False)
    assert "Kubernetes" in profile.skills[1].items


def test_profile_yaml_validation(env):
    client, _, _ = env
    text = client.get("/api/profile/yaml").json()["yaml"]
    bad = text.replace("id: acme-bank.a2", "id: acme-bank.a1")  # duplicate id
    assert client.put("/api/profile/yaml", json={"yaml": bad}).status_code == 422


def test_short_jd_and_unknown_app(env):
    client, _, _ = env
    assert client.post("/api/applications", json={"jd": "too short"}).status_code == 422
    assert client.get("/api/applications/nope").status_code == 404
    assert client.get("/api/applications/..%2F..%2Fetc").status_code == 404


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/api/profile",
    "http://localhost/",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.1/admin",
    "http://[::1]/",
    "file:///etc/passwd",
    "ftp://example.com/jd.txt",
])
def test_url_fetch_refuses_non_public_targets(env, url):
    client, _, _ = env
    res = client.post("/api/applications", json={"jd": "", "url": url})
    assert res.status_code == 422
    assert "private or local" in res.json()["detail"] or "http" in res.json()["detail"]


def test_foreign_host_header_is_rejected(env):
    client, _, _ = env
    assert client.get("/api/engine", headers={"host": "evil.example.com"}).status_code == 400


@pytest.mark.skipif(not (Path(__file__).parents[1] / "web" / "dist" / "index.html").exists(), reason="web UI not built")
def test_ui_page_is_never_served_stale(env):
    client, _, _ = env
    res = client.get("/profile")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-cache"


def test_tracker_progress_reflects_real_state(env):
    client, store, engine = env
    app_id = client.post("/api/applications", json={"jd": JD}).json()["id"]
    (row,) = client.get("/api/applications").json()
    assert row["progress"] == {"seniority": None, "requirements": 0, "gaps_open": 0, "drafted": False,
                               "verified": None, "critique": None}
    app_id = client.post(f"/api/applications/{app_id}/analyze").json()["id"]
    progress = lambda: client.get("/api/applications").json()[0]["progress"]  # noqa: E731
    assert progress()["gaps_open"] == 1 and progress()["requirements"] == 1 and progress()["seniority"] == "Senior"
    client.put(f"/api/applications/{app_id}/answers", json=[
        {"question_id": "q1", "requirement": "Kubernetes", "question": "Any Kubernetes work?", "status": "no_experience"}])
    assert progress()["gaps_open"] == 0
    client.post(f"/api/applications/{app_id}/compose", json={})
    assert progress()["drafted"] and progress()["verified"] is True
    t = client.get(f"/api/applications/{app_id}").json()["tailored"]
    t["highlights"][0]["text"] = "Cut false positives by 99%."
    client.put(f"/api/applications/{app_id}/tailored", json=t)
    assert progress()["verified"] is False
