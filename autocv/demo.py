"""Canned engine responses so the UI can be exercised without the Claude CLI
(AUTOCV_ENGINE=fake). Responses are derived from the user's profile and contain no
new facts: compose returns the base resume layout (or the whole profile) unchanged."""

from __future__ import annotations

import re

import yaml

from .engine import FakeEngine
from .store import Store


def _analyze(prompt: str) -> dict:
    profile = Store.default().profile()
    evidence = [a.id for r in profile.roles for a in r.achievements][:2]
    title = re.search(r"JOB DESCRIPTION:\n(.+)", prompt)
    return {
        "company": "Demo Company",
        "role": (title.group(1).strip("# ").strip() if title else "Demo Role")[:80],
        "industry": "tech", "track": "hybrid", "seniority": "Senior", "location": "",
        "summary": "Demo analysis (fake engine) — connect the Claude CLI or an API key for a real one.",
        "requirements": [
            {"text": "Proven results in the core area of the role", "priority": "must",
             "status": "strong" if evidence else "gap", "evidence": evidence, "note": "demo"},
            {"text": DEMO_GAP, "priority": "nice", "status": "gap", "evidence": [], "note": "demo"},
        ],
        "keywords": [
            {"term": "stakeholder management", "priority": "must", "aliases": ["stakeholders"]},
            {"term": "delivery", "priority": "must", "aliases": []},
            {"term": "public speaking", "priority": "nice", "aliases": []},
        ],
        **_gap_questions(),
    }


DEMO_GAP = "Public speaking at industry events"


def _gap_questions() -> dict:
    """Mimic the real analysis' use of past answers: known gap → not asked; related answer → pre-fill."""
    topic = DEMO_GAP
    past = [k for k in Store.default().knowledge().answers if "speaking" in k.topic.lower()]
    gap = next((k for k in past if k.kind == "no_experience"), None)
    if gap:
        return {"questions": [], "known_gaps": [{"requirement": topic, "knowledge_id": gap.id}]}
    return {"questions": [{"id": "q1", "requirement": topic,
                           "question": "Have you spoken at industry events or conferences? Which ones, and on what?",
                           "prefill_from": past[0].id if past else ""}],
            "known_gaps": []}


def _propose(prompt: str) -> dict:
    answers = yaml.safe_load(prompt.split("ANSWERS:\n", 1)[1]) or []
    role = Store.default().profile().roles[0].id
    return {"proposals": [{"question_id": a["question_id"], "target": role, "text": a["answer"].strip(),
                           "skills": []} for a in answers]}


def _compose(prompt: str) -> dict:
    from .ai import default_layout
    store = Store.default()
    base = store.base_tailored() or default_layout(store.profile())
    return base.model_dump(exclude_none=True)


def _trim(prompt: str) -> dict:
    """Demo trim: drop the last bullet of the oldest role that has more than one (only removes)."""
    import json as _json
    draft = _json.loads(prompt.split("TAILORED RESUME:\n", 1)[1])
    for role in reversed(draft.get("experience", [])):
        if len(role.get("bullets", [])) > 1:
            role["bullets"] = role["bullets"][:-1]
            break
    return draft


def _learn(prompt: str) -> dict:
    return {"preferences": [{"text": "Demo preference: prefer plain verbs over buzzwords.",
                             "rationale": "demo (fake engine)"}]}


def _critique(prompt: str) -> dict:
    """Canned review built from the draft in the prompt (demo only; no AI involved)."""
    import json as _json

    from .factcheck import evidence_index
    draft = _json.loads(prompt.split("DRAFT CLAIMS BY PATH:\n", 1)[1])
    index = evidence_index(Store.default().profile())
    issues = []
    bullet = next((p for p in draft if p.startswith("experience[0].bullets[")), None)
    if bullet:
        src = draft[bullet]["sources"][0]
        issues.append({"where": bullet, "kind": "duty_not_outcome", "severity": "high",
                       "problem": "Demo: lead with the outcome rather than the activity.", "action": "rewrite",
                       "rewrite": {"text": index[src].split("\n")[0], "sources": [src]},
                       "question": None, "note_for": None})
    if "highlights[1]" in draft:
        issues.append({"where": "highlights[1]", "kind": "buried_must_have", "severity": "medium",
                       "problem": "Demo: this is the strongest match for the role. Move it up.",
                       "action": "move_to_top", "rewrite": None, "question": None, "note_for": None})
    if "highlights[0]" in draft:
        issues.append({"where": "highlights[0]", "kind": "weak_opening", "severity": "medium",
                       "problem": "Demo: an invented rewrite, which the fact-check gate must block.", "action": "rewrite",
                       "rewrite": {"text": "Cut alerts by 95% across 40 platforms.", "sources": draft["highlights[0]"]["sources"]},
                       "question": None, "note_for": None})
    second = next((p for p in draft if p.startswith("experience[0].bullets[") and p != bullet), None)
    if second:
        issues.append({"where": second, "kind": "duty_not_outcome", "severity": "low",
                       "problem": "Demo: no measurable result.", "action": "advice", "rewrite": None,
                       "question": "Did this work have a measurable result (time saved, revenue, quality, coverage)?",
                       "note_for": None})
    issues.append({"where": "length", "kind": "too_long", "severity": "low", "problem": "Demo: the oldest role is long.",
                   "action": "advice", "rewrite": None, "question": None, "note_for": "interview"})
    return {"verdict": {"decision": "borderline", "reason": "Demo verdict (fake engine)."},
            "scores": {k: {"score": v, "why": "demo"} for k, v in
                       {"fit": 7, "impact": 6, "clarity": 8, "seniority": 7}.items()},
            "skim": {"takeaway": "Demo: experienced candidate with relevant depth.", "lands": ["Demo: scale of the current role"],
                     "misses": ["Demo: the role's must-have isn't visible in the top third"]},
            "strengths": [{"where": "summary", "why": "Demo: clear seniority and scope."}],
            "issues": issues}


def _import(prompt: str) -> dict:
    """Demo import: the first lines become name and headline, bullets become one role's achievements.
    Placeholders are marked "(demo)" so they show up as unverified in the review."""
    lines = [ln.strip() for ln in prompt.split("RESUME:\n", 1)[1].splitlines() if ln.strip()]
    bullets = [ln.lstrip("•·-* ").strip() for ln in lines if ln[:1] in "•·-*"]
    return {"contact": {"name": lines[0] if lines else "(demo) Your name", "location": "", "phone": "", "email": "",
                        "links": []},
            "headline": lines[1] if len(lines) > 1 else "", "summary": "", "highlights": [], "skills": [],
            "roles": [{"employer": "(demo) Employer", "location": "", "title": lines[1] if len(lines) > 1 else "(demo) Title",
                       "dates": "", "scope": "", "achievements": bullets[:6], "sub_roles": []}],
            "projects": [], "education": [], "extras": [],
            "suggested_targets": {"field": "", "seniority": "", "roles": lines[1] + " roles" if len(lines) > 1 else "",
                                  "region": "", "spelling": "US"}}


def demo_engine() -> FakeEngine:
    return FakeEngine({"analyze": _analyze, "propose_evidence": _propose, "compose": _compose,
                       "repair": _compose, "trim": _trim, "learn_preferences": _learn, "critique": _critique,
                       "import": _import})
