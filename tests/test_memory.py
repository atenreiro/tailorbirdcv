"""Cross-application memory: saved answers, knowledge base, learned style preferences."""

import shutil
from pathlib import Path

import pytest
import yaml
from conftest import client_for

from autocv import ai
from autocv.api import create_app
from autocv.engine import FakeEngine
from autocv.schema import AppAnswer, Knowledge, KnowledgeAnswer, TailoredResume
from autocv.store import Store

FIX = Path(__file__).parent / "fixtures"
JD = "# Detection Lead — Example Capital\n\n" + "We need a hands-on detection engineering lead. " * 10
TAILORED = yaml.safe_load((FIX / "tailored.yaml").read_text(encoding="utf-8"))


def analysis(**extra):
    return {"company": "Example Capital", "role": "Detection Lead", "industry": "quant", "track": "ic",
            "seniority": "Senior", "location": "SG", "summary": "x",
            "requirements": [{"text": "Kubernetes", "priority": "must", "status": "gap", "evidence": [], "note": ""}],
            "keywords": [], "questions": [], "known_gaps": [], **extra}


@pytest.fixture
def env(tmp_path):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    store = Store(private)
    engine = FakeEngine({"analyze": analysis(), "compose": TAILORED, "repair": TAILORED,
                         "learn_preferences": {"preferences": [{"text": "Prefer 'led' over 'spearheaded'.",
                                                                "rationale": "edits"}]}})
    return client_for(create_app(store, engine)), store, engine


def new_app(client):
    return client.post("/api/applications", json={"jd": JD, "company": "Example Capital", "role": "Lead"}).json()["id"]


# ---- (1) answers persist per application --------------------------------------------------

def test_answers_persist_and_drafts_are_not_remembered(env):
    client, store, _ = env
    app_id = new_app(client)
    draft = [{"question_id": "q1", "requirement": "Kubernetes", "question": "Any K8s?", "answer": "hmm"}]
    assert client.put(f"/api/applications/{app_id}/answers", json=draft).status_code == 200
    assert client.get(f"/api/applications/{app_id}").json()["answers"][0]["answer"] == "hmm"
    assert store.knowledge().answers == []  # drafts stay local to the application


# ---- (2) knowledge base ---------------------------------------------------------------------

def test_finalized_answers_become_knowledge_and_can_be_retracted(env):
    client, store, _ = env
    app_id = new_app(client)
    put = lambda answers: client.put(f"/api/applications/{app_id}/answers", json=answers)  # noqa: E731
    put([{"question_id": "q1", "requirement": "Kubernetes", "question": "Any K8s?", "status": "no_experience"},
         {"question_id": "q2", "requirement": "SOAR", "question": "Any SOAR?", "answer": "Built playbooks at Acme",
          "status": "approved", "evidence_id": "acme-bank.a3"}])
    k = {a.topic: a for a in store.knowledge().answers}
    assert k["Kubernetes"].kind == "no_experience" and k["Kubernetes"].company == "Example Capital"
    assert (k["SOAR"].kind, k["SOAR"].evidence_id) == ("experience", "acme-bank.a3")

    # unticking "no experience" (back to draft) forgets the gap; ids stay stable on update
    soar_id = k["SOAR"].id
    put([{"question_id": "q1", "requirement": "Kubernetes", "question": "Any K8s?", "answer": "", "status": "draft"},
         {"question_id": "q2", "requirement": "SOAR", "question": "Any SOAR?", "answer": "Built playbooks at Acme (v2)",
          "status": "approved", "evidence_id": "acme-bank.a3"}])
    k = store.knowledge().answers
    assert [a.topic for a in k] == ["SOAR"] and k[0].id == soar_id and k[0].answer.endswith("(v2)")


def test_rejected_answer_is_remembered_but_never_evidence(env):
    client, store, _ = env
    app_id = new_app(client)
    client.put(f"/api/applications/{app_id}/answers", json=[
        {"question_id": "q1", "requirement": "Kubernetes", "question": "Any K8s?", "answer": "Some labs", "status": "rejected"}])
    (entry,) = store.knowledge().answers
    assert entry.kind == "experience" and entry.evidence_id is None
    assert "Some labs" not in store.profile_path.read_text(encoding="utf-8")


def test_analysis_sees_past_answers_and_ids_are_sanitised(env, tmp_path):
    client, store, engine = env
    store.save_knowledge(Knowledge(answers=[KnowledgeAnswer(
        id="k1", topic="Kubernetes", question="Any K8s?", kind="no_experience", date="2026-10-01")]))
    engine.responses["analyze"] = analysis(
        known_gaps=[{"requirement": "Kubernetes", "knowledge_id": "k1"}, {"requirement": "x", "knowledge_id": "k99"}],
        questions=[{"id": "q1", "requirement": "Containers", "question": "?", "prefill_from": "k99"}])
    app_id = new_app(client)
    data = client.post(f"/api/applications/{app_id}/analyze").json()
    prompt = engine.calls[-1][1]
    assert "PAST ANSWERS" in prompt and "id: k1" in prompt and "no_experience" in prompt
    assert data["analysis"]["known_gaps"] == [{"requirement": "Kubernetes", "knowledge_id": "k1"}]
    assert data["analysis"]["questions"][0]["prefill_from"] == ""  # unknown id dropped


def test_knowledge_edit_is_validated(env):
    client, store, _ = env
    version = {"If-Match": client.get("/api/knowledge").json()["version"]}
    assert client.put("/api/knowledge", json={"answers": [{"id": "k1", "topic": "t", "question": "q",
                                                           "kind": "maybe", "date": "2026-10-01"}]},
                      headers=version).status_code == 422
    assert client.put("/api/knowledge", json={"answers": [], "preferences": []}).status_code == 428  # no version
    ok = client.put("/api/knowledge", json={"answers": [], "preferences": []}, headers=version)
    assert ok.status_code == 200


# ---- (4) style preferences ------------------------------------------------------------------

def test_edits_are_detected_by_cited_evidence():
    draft = TailoredResume.model_validate(TAILORED)
    edited = TailoredResume.model_validate(TAILORED)
    edited.experience[0].bullets.reverse()  # reordering alone is not an edit
    assert ai.edited_claims(draft, edited) == []
    edited.experience[0].bullets[0].text = "Led vendor spend across five platforms."  # was index 1
    edited.highlights = []
    edits = ai.edited_claims(draft, edited)
    assert {"where": "acme-bank bullet", "before": draft.experience[0].bullets[1].text,
            "after": "Led vendor spend across five platforms."} in edits
    assert any(e["after"] == "(removed)" and e["where"] == "highlight 1" for e in edits)


def test_preferences_learned_only_apply_once_approved(env):
    client, store, engine = env
    app_id = new_app(client)
    client.post(f"/api/applications/{app_id}/analyze")
    client.post(f"/api/applications/{app_id}/compose", json={"guidance": "keep it hands-on"})
    assert store.meta(app_id)["guidance"] == "keep it hands-on"

    edited = client.get(f"/api/applications/{app_id}").json()["tailored"]
    edited["highlights"][0]["text"] = "Cut false positives by over 65%."
    assert client.put(f"/api/applications/{app_id}/tailored", json=edited).json()["edits"] == 1

    res = client.post(f"/api/applications/{app_id}/preferences").json()
    assert res["edits"] == 1 and res["proposed"] == 1
    learn_prompt = engine.calls[-1][1]
    assert "keep it hands-on" in learn_prompt and "Cut false positives by over 65%." in learn_prompt

    # proposed → not used when composing
    client.post(f"/api/applications/{app_id}/compose", json={})
    assert "spearheaded" not in engine.calls[-1][1]

    knowledge = res["knowledge"]
    knowledge["preferences"][0]["status"] = "active"
    client.put("/api/knowledge", json=knowledge, headers={"If-Match": client.get("/api/knowledge").json()["version"]})
    client.post(f"/api/applications/{app_id}/compose", json={})
    compose_prompt = next(p for t, p in reversed(engine.calls) if t == "compose")
    assert "- Prefer 'led' over 'spearheaded'." in compose_prompt


def test_no_edits_and_no_guidance_means_nothing_to_learn(env):
    client, store, engine = env
    app_id = new_app(client)
    client.post(f"/api/applications/{app_id}/analyze")
    client.post(f"/api/applications/{app_id}/compose", json={})
    res = client.post(f"/api/applications/{app_id}/preferences").json()
    assert res["proposed"] == 0 and "learn_preferences" not in [t for t, _ in engine.calls]


def test_answering_a_reopened_gap_replaces_the_old_entry(env):
    client, store, _ = env
    first, second = new_app(client), client.post("/api/applications", json={
        "jd": JD, "company": "Other Co", "role": "Lead"}).json()["id"]
    client.put(f"/api/applications/{first}/answers", json=[
        {"question_id": "q1", "requirement": "Kubernetes", "question": "Any K8s?", "status": "no_experience"}])
    (gap,) = store.knowledge().answers
    reopened = {"question_id": f"kg-{gap.id}", "requirement": "Kubernetes", "question": "Has that changed?"}
    client.put(f"/api/applications/{second}/answers", json=[{**reopened, "answer": "", "status": "draft"}])
    assert [k.id for k in store.knowledge().answers] == [gap.id]  # still a draft: old gap kept
    client.put(f"/api/applications/{second}/answers", json=[
        {**reopened, "answer": "Hardened EKS at Acme", "status": "approved", "evidence_id": "acme-bank.a3"}])
    (entry,) = store.knowledge().answers
    assert entry.kind == "experience" and entry.app_id == second and entry.id != gap.id
