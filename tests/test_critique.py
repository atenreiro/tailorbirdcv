"""Hiring-manager review: safety gate, applying fixes, persistence, questions, learning."""

import shutil
from pathlib import Path

import pytest
import yaml

from autocv import critique as hm
from autocv import factcheck
from autocv.api import create_app
from autocv.engine import FakeEngine
from autocv.schema import TailoredResume, load_profile
from autocv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
JD = "# Detection Lead — Example Capital\n\n" + "We need a hands-on detection engineering lead. " * 10
TAILORED = yaml.safe_load((FIX / "tailored.yaml").read_text(encoding="utf-8"))
ANALYSIS = {"company": "Example Capital", "role": "Lead", "industry": "quant", "track": "ic", "seniority": "S",
            "location": "SG", "summary": "x", "keywords": [], "known_gaps": [], "questions": [],
            "requirements": [{"text": "Vendor management", "priority": "must", "status": "strong",
                              "evidence": ["acme-bank.a2"], "note": ""}]}


def issue(where, action="advice", rewrite=None, question=None, note_for=None, kind="unclear"):
    return {"where": where, "kind": kind, "severity": "high", "problem": f"problem at {where}", "action": action,
            "rewrite": rewrite, "question": question, "note_for": note_for}


REVIEW = {
    "verdict": {"decision": "borderline", "reason": "Strong detection work, weak vendor story."},
    "scores": {k: {"score": 7, "why": "ok"} for k in ("fit", "impact", "clarity", "seniority")},
    "skim": {"takeaway": "Detection lead", "lands": ["65%"], "misses": ["vendor scope"]},
    "strengths": [{"where": "summary", "why": "clear"}, {"where": "experience[9].bullets[9]", "why": "ghost"}],
    "issues": [
        issue("experience[0].bullets[0]", "rewrite",
              {"text": "Cut false positives by over 65%, to roughly nine a month, by rebuilding Splunk detection logic.",
               "sources": ["acme-bank.a1"]}),                                                     # valid → kept
        issue("highlights[0]", "rewrite", {"text": "Cut false positives by 95%.", "sources": ["highlight.h1"]}),  # invented
        issue("experience[1].bullets[0]", "rewrite",
              {"text": "Saved US$1.7M in Fastly renegotiations.", "sources": ["telco.a1", "acme-bank.a2"]}),  # other role
        issue("experience[0].bullets[1]", "move_to_top"),
        issue("experience[7].bullets[0]", "rewrite", {"text": "x", "sources": ["acme-bank.a1"]}),  # unknown path
        issue("experience[0].scope", question="How many alerts per day did the team handle?"),
        issue("headline", "rewrite", {"text": "x", "sources": ["summary.s1"]}),                 # non-claim → advice
        issue("length", note_for="interview"),
    ],
}


@pytest.fixture
def profile():
    return load_profile(FIX / "profile.yaml")


@pytest.fixture
def tailored():
    return TailoredResume.model_validate(TAILORED)


# ---- safety gate ------------------------------------------------------------------------------

def test_sanitize_keeps_only_fact_safe_rewrites(profile, tailored):
    out = hm._sanitize(profile, tailored, REVIEW, run_no=1)
    by_where = {i["where"]: i for i in out["issues"]}
    assert by_where["experience[0].bullets[0]"]["action"] == "rewrite"
    assert by_where["highlights[0]"]["action"] == "advice" and "fact-check" in by_where["highlights[0]"]["blocked"]
    assert by_where["experience[1].bullets[0]"]["action"] == "advice"        # cross-role citation blocked
    assert "experience[7].bullets[0]" not in by_where                           # unknown path dropped
    assert by_where["headline"]["action"] == "advice" and by_where["headline"]["rewrite"] is None
    assert by_where["experience[0].scope"]["question"].startswith("How many")
    assert by_where["length"]["note_for"] == "interview"
    assert [s["where"] for s in out["strengths"]] == ["summary"]
    assert all(i["id"].startswith("r1-i") for i in out["issues"])
    assert by_where["experience[0].bullets[0]"]["original"]["sources"] == ["acme-bank.a1"]


def test_every_surfaced_rewrite_passes_the_fact_check(profile, tailored):
    out = hm._sanitize(profile, tailored, REVIEW, run_no=1)
    for i in out["issues"]:
        if i["action"] == "rewrite":
            assert factcheck.check(profile, hm.apply_issue(tailored, i)).ok


# ---- applying fixes -----------------------------------------------------------------------------

def test_apply_rewrite_remove_and_move(profile, tailored):
    out = {i["where"]: i for i in hm._sanitize(profile, tailored, REVIEW, run_no=1)["issues"]}
    t = hm.apply_issue(tailored, out["experience[0].bullets[0]"])
    assert t.experience[0].bullets[0].text.startswith("Cut false positives")
    moved = hm.apply_issue(t, out["experience[0].bullets[1]"])                   # still found after the rewrite
    assert moved.experience[0].bullets[0].text == tailored.experience[0].bullets[1].text
    removal = {**out["experience[0].bullets[1]"], "action": "remove"}
    assert len(hm.apply_issue(tailored, removal).experience[0].bullets) == 1
    assert hm.apply_issue(tailored, out["length"]) == tailored                    # advice changes nothing


def test_stale_target_is_never_misapplied(profile, tailored):
    out = {i["where"]: i for i in hm._sanitize(profile, tailored, REVIEW, run_no=1)["issues"]}
    tailored.experience[0].bullets[1].text = "Edited by the candidate since the review."
    with pytest.raises(ValueError, match="changed"):
        hm.apply_issue(tailored, out["experience[0].bullets[1]"])


def test_unused_must_have_evidence_is_hinted(profile, tailored):
    tailored.experience[0].bullets = tailored.experience[0].bullets[:1]  # drop the vendor bullet (acme-bank.a2)
    hints = hm.unused_must_have_evidence(profile, tailored, ANALYSIS)
    assert [h["evidence_id"] for h in hints] == ["acme-bank.a2"]


# ---- API: runs, decisions, staleness, questions, learning --------------------------------------

@pytest.fixture
def env(tmp_path):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    shutil.copy(FIX / "tailored.yaml", private / "source" / "base_tailored.yaml")
    engine = FakeEngine({"analyze": ANALYSIS, "compose": TAILORED, "repair": TAILORED, "critique": REVIEW,
                         "learn_preferences": {"preferences": []}})
    store = Store(private)
    client = client_for(create_app(store, engine))
    app_id = client.post("/api/applications", json={"jd": JD, "company": "Example Capital", "role": "Lead"}).json()["id"]
    client.post(f"/api/applications/{app_id}/analyze")
    client.post(f"/api/applications/{app_id}/compose", json={})
    return client, store, engine, app_id


def test_critique_run_decisions_and_staleness(env):
    client, store, engine, app_id = env
    data = client.post(f"/api/applications/{app_id}/critique").json()
    c = data["critique"]
    assert c["latest"]["verdict"]["decision"] == "borderline" and not c["stale"] and c["previous_scores"] is None
    prompt = next(p for t, p in engine.calls if t == "critique")
    assert "acme-bank.a2" not in prompt.split("MUST-HAVE EVIDENCE THE DRAFT DOESN'T USE")[1].split("CANDIDATE'S")[0]

    first = c["latest"]["issues"][0]["id"]
    saved = client.put(f"/api/applications/{app_id}/critique/decisions", json={"decisions": {first: "accepted"}}).json()
    assert saved["decisions"] == {first: "accepted"}

    t = data["tailored"]
    t["highlights"][0]["text"] = "Cut false positives by over 65%."
    assert client.put(f"/api/applications/{app_id}/tailored", json=t).json()["critique"]["stale"]

    again = client.post(f"/api/applications/{app_id}/critique").json()["critique"]
    assert again["previous_scores"]["fit"]["score"] == 7 and not again["stale"]
    assert again["latest"]["issues"][0]["id"].startswith("r2-")


def test_critique_requires_a_passing_draft(env):
    client, store, engine, app_id = env
    t = client.get(f"/api/applications/{app_id}").json()["tailored"]
    t["highlights"][0]["text"] = "Cut false positives by 99%."
    client.put(f"/api/applications/{app_id}/tailored", json=t)
    assert client.post(f"/api/applications/{app_id}/critique").status_code == 409


def test_review_question_becomes_a_gap_answer_that_survives_reanalysis(env):
    client, store, engine, app_id = env
    client.put(f"/api/applications/{app_id}/answers", json=[
        {"question_id": "hm-r1-i6", "requirement": "Review", "question": "How many alerts per day?", "answer": ""}])
    client.post(f"/api/applications/{app_id}/analyze")
    assert [a.question_id for a in store.answers(app_id)] == ["hm-r1-i6"]


def test_rejected_suggestions_teach_style(env):
    client, store, engine, app_id = env
    c = client.post(f"/api/applications/{app_id}/critique").json()["critique"]
    rewrite = next(i for i in c["latest"]["issues"] if i["action"] == "rewrite")
    client.put(f"/api/applications/{app_id}/critique/decisions", json={"decisions": {rewrite["id"]: "rejected"}})
    client.post(f"/api/applications/{app_id}/preferences")
    prompt = next(p for t, p in reversed(engine.calls) if t == "learn_preferences")
    assert rewrite["rewrite"]["text"] in prompt.split("REJECTED")[1]
