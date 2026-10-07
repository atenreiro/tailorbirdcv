"""Cross-application memory: saved answers, knowledge base, learned style preferences."""

import shutil
from pathlib import Path

import pytest
import yaml
from conftest import client_for

from tailorbirdcv import ai
from tailorbirdcv.api import create_app
from tailorbirdcv.engine import FakeEngine
from tailorbirdcv.schema import AppAnswer, Knowledge, KnowledgeAnswer, TailoredResume
from tailorbirdcv.store import Store

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
    edited.experience[0].bullets[0].text = "Led vendor spend across four platforms."  # was index 1
    edited.highlights = []
    edits = ai.edited_claims(draft, edited)
    assert {"where": "acme-bank bullet", "before": draft.experience[0].bullets[1].text,
            "after": "Led vendor spend across four platforms."} in edits
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


# ---- (5) learning style by itself when an application is marked applied --------------------

def wait_for(cond, seconds=5.0):
    import time
    deadline = time.monotonic() + seconds
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.05)
    return cond()


@pytest.fixture
def applying(env, monkeypatch):
    from tailorbirdcv import pdf as pdfmod

    def fake_to_pdf(docx, pdf=None, timeout=0, engine=None):  # stands in for Word/LibreOffice
        out = pdf or docx.with_suffix(".pdf")
        out.write_bytes(b"%PDF-1.4 stand-in")
        return out
    monkeypatch.setattr(pdfmod, "to_pdf", fake_to_pdf)
    monkeypatch.setattr(pdfmod, "resolve", lambda preferred=None, engines=None: preferred or "word")
    monkeypatch.setattr(pdfmod, "page_count", lambda p: 1)
    client, store, engine = env
    app_id = new_app(client)
    client.post(f"/api/applications/{app_id}/analyze")
    client.post(f"/api/applications/{app_id}/compose", json={})
    edited = client.get(f"/api/applications/{app_id}").json()["tailored"]
    edited["highlights"][0]["text"] = "Cut false positives by over 65%."
    client.put(f"/api/applications/{app_id}/tailored", json=edited)
    return client, store, engine, app_id


def learned(engine):
    return [t for t, _ in engine.calls].count("learn_preferences")


def test_applying_suggests_style_preferences_in_the_background_once(applying):
    client, store, engine, app_id = applying
    with client:  # keeps the event loop running for the background learning
        client.post(f"/api/applications/{app_id}/freeze?build=true&mark_applied=true")
        assert wait_for(lambda: any(p.source_app == app_id for p in store.knowledge().preferences))
        (pref,) = store.knowledge().preferences
        assert pref.status == "proposed"  # never used until approved
        assert wait_for(lambda: not client.get(f"/api/applications/{app_id}").json()["learning_style"])
        # Applied again later (after an interview, say) with the same edits: not studied twice.
        client.patch(f"/api/applications/{app_id}", json={"status": "interview"})
        client.patch(f"/api/applications/{app_id}", json={"status": "applied"})
        import time
        time.sleep(0.3)
    assert learned(engine) == 1 and len(store.knowledge().preferences) == 1


def test_learning_when_applying_can_be_turned_off(applying):
    client, store, engine, app_id = applying
    client.put("/api/settings", json={"learn_style": False})
    with client:
        client.post(f"/api/applications/{app_id}/freeze?build=true&mark_applied=true")
        import time
        time.sleep(0.3)
    assert learned(engine) == 0 and store.knowledge().preferences == []


def test_cover_letter_edits_are_learned_from_too():
    from tailorbirdcv.schema import CoverLetter
    sentence = lambda text, kind="link": {"text": text, "kind": kind, "sources": []}  # noqa: E731
    draft = CoverLetter.model_validate({"tone": "formal", "paragraphs": [
        {"sentences": [sentence("I am writing to apply."), sentence("It would be a privilege to join.")]},
        {"sentences": [sentence("Thank you for your time.")]}]})
    sent = CoverLetter.model_validate({"tone": "direct", "paragraphs": [
        {"sentences": [sentence("I am writing to apply.")]},
        {"sentences": [sentence("Thanks for reading."), sentence("I would welcome a call.")]}]})
    edits = ai.edited_letter(draft, sent)
    assert {"where": "cover letter ¶1", "before": "It would be a privilege to join.", "after": "Thanks for reading."} in edits
    assert {"where": "cover letter ¶2", "before": "Thank you for your time.", "after": "I would welcome a call."} in edits
    assert {"where": "cover letter tone", "before": "formal", "after": "direct"} in edits
    assert ai.edited_letter(draft, draft) == []


# ---- (6) one remembered answer per topic ----------------------------------------------------

def k(id_, topic, kind="no_experience", app="a~1", date="2026-10-01", question=None, answer=""):
    return KnowledgeAnswer(id=id_, topic=topic, question=question or f"Any {topic}?", kind=kind, app_id=app,
                           date=date, answer=answer)


def test_a_newer_answer_replaces_older_ones_on_the_same_topic():
    from tailorbirdcv.store import merge_answers
    answers = [k("k1", "Kubernetes security", date="2026-09-01"),
               k("k2", "kubernetes  Security!", kind="experience", app="b~2", date="2026-10-02", answer="EKS at Acme"),
               k("k3", "Kubernetes security", app="b~2", question="Which clusters?", date="2026-10-02"),  # same app: kept
               k("k4", "SOAR")]
    assert [x.id for x in merge_answers(answers)] == ["k2", "k3", "k4"]


def test_an_answer_to_a_prefilled_question_replaces_the_one_it_came_from():
    from tailorbirdcv.store import merge_answers
    answers = [k("k1", "Cloud security posture"), k("k2", "CSPM tooling", app="b~2", date="2026-10-03")]
    assert [x.id for x in merge_answers(answers, {"k2": "k1"})] == ["k2"]
    assert [x.id for x in merge_answers(answers, {"k1": "k2"})] == ["k1", "k2"]  # a link never drops a newer answer
    # "Some experience" on a related topic, then "no experience" on the new one: both kept (detail survives).
    mixed = [k("k1", "Workload identity", kind="experience", answer="Only IAM roles"),
             k("k2", "Cloud platforms", app="b~2", date="2026-10-03")]
    assert [x.id for x in merge_answers(mixed, {"k2": "k1"})] == ["k1", "k2"]


def test_finalizing_merges_and_startup_tidies_old_duplicates(env, tmp_path):
    client, store, engine = env
    first = new_app(client)
    second = client.post("/api/applications", json={"jd": JD, "company": "Other Co", "role": "Lead"}).json()["id"]
    client.put(f"/api/applications/{first}/answers", json=[
        {"question_id": "q1", "requirement": "Kubernetes", "question": "Any K8s?", "status": "no_experience"}])
    (old,) = store.knowledge().answers
    client.put(f"/api/applications/{second}/answers", json=[
        {"question_id": "q1", "requirement": "Container orchestration", "question": "Run containers in production?",
         "answer": "Hardened EKS at Acme", "status": "approved", "evidence_id": "acme-bank.a3", "prefill_from": old.id}])
    (entry,) = store.knowledge().answers
    assert entry.app_id == second and old.id in store.knowledge().retired_ids

    # A file from before merging existed (duplicates written by hand here) is tidied when the app starts.
    store.save_knowledge(Knowledge(answers=[k("k10", "SIEM", date="2026-09-01"),
                                            k("k11", "SIEM", app="c~3", date="2026-09-05")]))
    create_app(store, engine)
    assert [x.id for x in store.knowledge().answers] == ["k11"]
    assert len(list(store.history_dir("knowledge").glob("*.yaml"))) >= 1  # the previous version is kept


# ---- (7) known gaps are asked about again after six months ----------------------------------

def test_an_old_known_gap_is_asked_again_with_the_old_answer_prefilled(env):
    import datetime as dt
    client, store, engine = env
    old = (dt.date.today() - dt.timedelta(days=ai.KNOWN_GAP_DAYS + 5)).isoformat()
    recent = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    store.save_knowledge(Knowledge(answers=[k("k1", "Kubernetes", date=old), k("k2", "SOAR", date=recent)]))
    engine.responses["analyze"] = analysis(known_gaps=[{"requirement": "Kubernetes", "knowledge_id": "k1"},
                                                       {"requirement": "SOAR", "knowledge_id": "k2"}])
    app_id = new_app(client)
    data = client.post(f"/api/applications/{app_id}/analyze").json()["analysis"]
    prompt = next(p for t, p in reversed(engine.calls) if t == "analyze")
    assert "stale: true" in prompt and prompt.count("stale: true") == 1
    assert data["known_gaps"] == [{"requirement": "SOAR", "knowledge_id": "k2"}]  # recent: still not asked
    (q,) = data["questions"]
    assert q["id"] == "q1" and q["prefill_from"] == "k1" and "still true" in q["question"]


def test_stale_gap_rule():
    import datetime as dt
    today = dt.date(2027, 6, 1)
    assert ai.stale_gap(k("k1", "x", date="2026-11-01"), today)
    assert not ai.stale_gap(k("k1", "x", date="2027-01-01"), today)
    assert not ai.stale_gap(k("k1", "x", kind="experience", date="2020-01-01"), today)
    assert not ai.stale_gap(k("k1", "x", date="not a date"), today)
