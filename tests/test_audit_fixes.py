"""Regression tests for the pre-launch audit findings (each test reproduces the original failure)."""

import copy
import shutil
import threading
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from autocv.api import create_app
from autocv.engine import FakeEngine
from autocv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
JD = "# Detection Lead — Example Capital\n\n" + "We need a hands-on detection engineering lead. " * 10
TAILORED = yaml.safe_load((FIX / "tailored.yaml").read_text())
ANALYSIS = {"company": "Example Capital", "role": "Lead", "industry": "quant", "track": "ic", "seniority": "S",
            "location": "SG", "summary": "x", "requirements": [], "keywords": [], "known_gaps": [],
            "questions": [{"id": "q1", "requirement": "Kubernetes", "question": "Any Kubernetes?", "prefill_from": ""}]}


def long_tailored():
    """Valid but far too long: every bullet repeated many times."""
    t = copy.deepcopy(TAILORED)
    t["experience"][0]["bullets"] = t["experience"][0]["bullets"] * 25
    return t


@pytest.fixture
def env(tmp_path):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    shutil.copy(FIX / "tailored.yaml", private / "source" / "base_tailored.yaml")
    engine = FakeEngine({"analyze": ANALYSIS, "compose": TAILORED, "repair": TAILORED, "trim": TAILORED})
    store = Store(private)
    return client_for(create_app(store, engine)), store, engine


def new_app(client, **body):
    return client.post("/api/applications", json={"jd": JD, "company": "Example Capital", "role": "Lead", **body}).json()["id"]


def composed_app(client):
    app_id = new_app(client)
    client.post(f"/api/applications/{app_id}/analyze")
    client.post(f"/api/applications/{app_id}/compose", json={})
    return app_id


# ---- 9: cross-site requests -------------------------------------------------------------

def test_cross_site_post_without_header_is_refused(env):
    _, store, engine = env
    raw = TestClient(create_app(store, engine), base_url="http://127.0.0.1")  # no X-AutoCV header
    res = raw.post("/api/applications", json={"jd": JD})
    assert res.status_code == 403 and "cross-site" in res.json()["detail"]
    assert raw.get("/api/applications").status_code == 200          # reading is fine
    headers = raw.get("/api/applications").headers
    assert headers["X-Frame-Options"] == "SAMEORIGIN"                 # own PDF preview may frame…
    assert headers["Content-Security-Policy"] == "frame-ancestors 'self'"  # …other sites may not
    assert engine.calls == []


def test_test_host_is_not_allowed_in_production(env):
    _, store, engine = env
    assert TestClient(create_app(store, engine)).get("/api/engine").status_code == 400  # Host: testserver


# ---- 3: an application must always open ---------------------------------------------------

@pytest.mark.parametrize("breakage", ["empty_competency", "unknown_headline", "deleted_role", "control_chars"])
def test_application_still_opens_after_bad_edits(env, breakage):
    client, store, _ = env
    app_id = composed_app(client)
    t = client.get(f"/api/applications/{app_id}").json()["tailored"]
    if breakage == "empty_competency":
        t["competencies"][0]["items"] = []
    elif breakage == "unknown_headline":
        t["headline"] = "h.deleted"
    elif breakage == "deleted_role":
        t["experience"][0]["role"] = "gone-co"
    else:
        t["highlights"][0]["text"] = "Pasted\x0cfrom a PDF\x07"
    assert client.put(f"/api/applications/{app_id}/tailored", json=t).status_code == 200
    data = client.get(f"/api/applications/{app_id}").json()
    assert data["tailored"] is not None
    if breakage != "control_chars":
        assert not data["report"]["ok"]


# ---- 4: no corruption, no lost updates ------------------------------------------------------

def test_concurrent_profile_saves_never_corrupt(env):
    _, store, _ = env
    data = store.profile().model_dump(exclude_none=True)
    data["summary_facts"][0]["text"] += " " + "padding " * 2000  # > 8 KB, like the real profile
    errors = []

    def writer():
        for _ in range(30):
            store.save_profile(copy.deepcopy(data))

    def reader():
        for _ in range(60):
            try:
                store.profile()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(4)] + [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert store.profile().summary_facts[0].text.endswith("padding ")


def test_stale_profile_write_is_rejected(env):
    client, _, _ = env
    loaded = client.get("/api/profile").json()
    client.post("/api/profile/evidence", json={"target": "acme-bank", "text": "Approved meanwhile."})
    res = client.put("/api/profile", json=loaded["profile"], headers={"If-Match": loaded["version"]})
    assert res.status_code == 409
    fresh = client.get("/api/profile").json()
    assert client.put("/api/profile", json=fresh["profile"], headers={"If-Match": fresh["version"]}).status_code == 200


def test_stale_knowledge_write_is_rejected(env):
    client, _, _ = env
    loaded = client.get("/api/knowledge").json()
    app_id = new_app(client)
    client.put(f"/api/applications/{app_id}/answers", json=[
        {"question_id": "q1", "requirement": "K8s", "question": "Any K8s?", "status": "no_experience"}])
    res = client.put("/api/knowledge", json=loaded, headers={"If-Match": loaded["version"]})
    assert res.status_code == 409


def test_suggest_preferences_keeps_answers_saved_during_the_ai_call(env):
    client, store, engine = env
    app_id = composed_app(client)
    t = client.get(f"/api/applications/{app_id}").json()["tailored"]
    t["highlights"][0]["text"] = "Cut false positives by over 65%."
    client.put(f"/api/applications/{app_id}/tailored", json=t)

    def learn(_prompt):  # while the "AI" thinks, the user answers a gap question elsewhere
        client.put(f"/api/applications/{app_id}/answers", json=[
            {"question_id": "q1", "requirement": "K8s", "question": "Any K8s?", "status": "no_experience"}])
        return {"preferences": [{"text": "Prefer plain verbs.", "rationale": "edits"}]}
    engine.responses["learn_preferences"] = learn
    client.post(f"/api/applications/{app_id}/preferences")
    k = store.knowledge()
    assert len(k.answers) == 1 and len(k.preferences) == 1


# ---- 6: ids are never reused ---------------------------------------------------------------

def test_deleted_evidence_id_is_never_reused(env):
    client, store, _ = env
    loaded = client.get("/api/profile").json()
    profile = loaded["profile"]
    profile["roles"][0]["achievements"] = [a for a in profile["roles"][0]["achievements"] if a["id"] != "acme-bank.a2"]
    client.put("/api/profile", json=profile, headers={"If-Match": loaded["version"]})
    assert "acme-bank.a2" in store.profile().retired_ids
    new = client.post("/api/profile/evidence", json={"target": "acme-bank", "text": "New fact."}).json()["id"]
    assert new == "acme-bank.a3"


def test_forgotten_knowledge_id_is_never_reused(env):
    client, store, _ = env
    app_id = new_app(client)
    put = lambda s: client.put(f"/api/applications/{app_id}/answers", json=[  # noqa: E731
        {"question_id": "q1", "requirement": "K8s", "question": "Any K8s?", "status": s}])
    put("no_experience")
    put("draft")           # retracted → k1 retired
    put("no_experience")
    assert [k.id for k in store.knowledge().answers] == ["k2"]


# ---- 7: tracking status ----------------------------------------------------------------------

def test_status_only_moves_forward_and_respects_user_status(env):
    client, store, _ = env
    app_id = composed_app(client)
    assert store.meta(app_id)["status"] == "composed"
    client.post(f"/api/applications/{app_id}/build?pdf=false")
    (store.app_path(app_id) / "Jane_Example_Resume.pdf").write_bytes(b"%PDF-1.4 stand-in")
    client.patch(f"/api/applications/{app_id}", json={"status": "applied"})
    client.post(f"/api/applications/{app_id}/analyze")
    client.post(f"/api/applications/{app_id}/compose", json={})
    client.post(f"/api/applications/{app_id}/build?pdf=false")
    assert store.meta(app_id)["status"] == "applied"


# ---- 8: stale or duplicate downloads ---------------------------------------------------------

def test_build_replaces_old_files_and_edits_mark_them_stale(env):
    client, store, _ = env
    app_id = composed_app(client)
    client.post(f"/api/applications/{app_id}/build?pdf=false")
    client.patch(f"/api/applications/{app_id}", json={"company": "Renamed Co"})
    data = client.post(f"/api/applications/{app_id}/build?pdf=false").json()
    assert data["files"] == ["Jane_Example_Resume.docx"] and not data["outputs_stale"]

    t = data["tailored"]
    t["highlights"][0]["text"] = "Cut false positives by over 65%."
    assert client.put(f"/api/applications/{app_id}/tailored", json=t).json()["outputs_stale"]
    assert not client.post(f"/api/applications/{app_id}/build?pdf=false").json()["outputs_stale"]


# ---- 2: re-analyze must not attach old answers to new questions ------------------------------

def test_reanalyze_keeps_only_matching_answers(env):
    client, store, engine = env
    app_id = new_app(client)
    client.post(f"/api/applications/{app_id}/analyze")
    client.put(f"/api/applications/{app_id}/answers", json=[
        {"question_id": "q1", "requirement": "Kubernetes", "question": "Any Kubernetes?", "answer": "draft text"},
        {"question_id": "kg-k9", "requirement": "SOAR", "question": "Has that changed?", "answer": ""}])
    engine.responses["analyze"] = {**ANALYSIS, "questions": [
        {"id": "q1", "requirement": "PCI", "question": "Any PCI DSS?", "prefill_from": ""},
        {"id": "q2", "requirement": "Kubernetes", "question": "Any Kubernetes?", "prefill_from": ""}]}
    answers = client.post(f"/api/applications/{app_id}/analyze").json()["answers"]
    by_q = {a["question"]: a for a in answers}
    assert by_q["Any Kubernetes?"]["question_id"] == "q2" and by_q["Any Kubernetes?"]["answer"] == "draft text"
    assert "Any PCI DSS?" not in by_q and "Has that changed?" in by_q


# ---- 1: length ------------------------------------------------------------------------------

def test_compose_trims_a_draft_that_is_too_long(env):
    client, store, engine = env
    engine.responses["compose"] = long_tailored()
    app_id = new_app(client)
    client.post(f"/api/applications/{app_id}/analyze")
    data = client.post(f"/api/applications/{app_id}/compose", json={}).json()
    assert "trim" in [task for task, _ in engine.calls]
    assert data["meta"]["trim_rounds"] == 1 and data["report"]["ok"]
    assert data["length"]["lines"] <= data["length"]["budget"]


def test_a_trim_that_breaks_the_fact_check_is_discarded(env):
    client, store, engine = env
    long = long_tailored()
    bad = copy.deepcopy(TAILORED)
    bad["highlights"][0]["text"] = "Cut false positives by 99%."
    engine.responses.update({"compose": long, "trim": bad, "repair": bad})
    app_id = new_app(client)
    client.post(f"/api/applications/{app_id}/analyze")
    data = client.post(f"/api/applications/{app_id}/compose", json={}).json()
    assert data["report"]["ok"]                                   # the valid long draft is kept…
    assert len(data["tailored"]["experience"][0]["bullets"]) == len(long["experience"][0]["bullets"])
    assert data["length"]["lines"] > data["length"]["budget"]     # …and reported as still too long


def test_trim_endpoint_shortens_the_current_resume(env):
    client, store, engine = env
    app_id = composed_app(client)
    t = client.get(f"/api/applications/{app_id}").json()["tailored"]
    client.put(f"/api/applications/{app_id}/tailored", json={**t, "experience": long_tailored()["experience"]})
    before = client.get(f"/api/applications/{app_id}").json()
    data = client.post(f"/api/applications/{app_id}/trim").json()
    # a proposal only: the saved draft is unchanged until the user saves it (PUT /tailored)
    assert data["tailored"] == before["tailored"] and data["length"]["lines"] == before["length"]["lines"]
    proposal = data["trim_proposal"]
    assert proposal["lines"] < before["length"]["lines"] and proposal["trim_rounds"] == 1
    assert proposal["budget"] == before["length"]["budget"]
    saved = client.put(f"/api/applications/{app_id}/tailored", json=proposal["tailored"]).json()
    assert saved["length"]["lines"] == proposal["lines"] and saved["report"]["ok"]



def test_file_name_never_includes_the_company(env):
    client, store, _ = env
    app_id = composed_app(client)
    files = client.post(f"/api/applications/{app_id}/build?pdf=false").json()["files"]
    assert files == ["Jane_Example_Resume.docx"]


def test_reveal_opens_only_this_applications_folder(env, monkeypatch):
    import subprocess
    client, store, _ = env
    app_id = composed_app(client)
    client.post(f"/api/applications/{app_id}/build?pdf=false")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    assert client.post(f"/api/applications/{app_id}/reveal").status_code == 204
    assert str(store.app_path(app_id)) in calls[0][-1]
    assert client.post("/api/applications/..%2F..%2Fetc/reveal").status_code == 404
    assert calls[1:] == []
