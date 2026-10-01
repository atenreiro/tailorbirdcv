"""Canned engine responses so the UI can be exercised without the Claude CLI
(AUTOCV_ENGINE=fake). Responses are derived from the real profile and contain no
new facts: compose returns the base resume layout unchanged."""

from __future__ import annotations

import re

import yaml

from .engine import FakeEngine
from .store import Store


def _analyze(prompt: str) -> dict:
    profile = Store.default().profile()
    first_role = profile.roles[0]
    title = re.search(r"JOB DESCRIPTION:\n(.+)", prompt)
    return {
        "company": "Demo Company",
        "role": (title.group(1).strip("# ").strip() if title else "Demo Role")[:80],
        "industry": "banking", "track": "hybrid", "seniority": "VP / Senior", "location": "Singapore",
        "summary": "Demo analysis (fake engine) — connect the Claude CLI for a real one.",
        "requirements": [
            {"text": "Lead detection & response for internet-facing services", "priority": "must",
             "status": "strong", "evidence": [a.id for a in first_role.achievements[:2]], "note": "demo"},
            {"text": "Kubernetes / container security", "priority": "nice", "status": "gap",
             "evidence": [], "note": "demo"},
        ],
        "keywords": [
            {"term": "detection engineering", "priority": "must", "aliases": ["detection logic"]},
            {"term": "incident response", "priority": "must", "aliases": []},
            {"term": "Kubernetes", "priority": "nice", "aliases": []},
        ],
        **_gap_questions(),
    }


def _gap_questions() -> dict:
    """Mimic the real analysis' use of past answers: known gap → not asked; related answer → pre-fill."""
    topic = "Kubernetes / container security"
    past = [k for k in Store.default().knowledge().answers if "kubernetes" in k.topic.lower()]
    gap = next((k for k in past if k.kind == "no_experience"), None)
    if gap:
        return {"questions": [], "known_gaps": [{"requirement": topic, "knowledge_id": gap.id}]}
    return {"questions": [{"id": "q1", "requirement": topic,
                           "question": "Have you done hands-on Kubernetes or container security work? Where, and what?",
                           "prefill_from": past[0].id if past else ""}],
            "known_gaps": []}


def _propose(prompt: str) -> dict:
    answers = yaml.safe_load(prompt.split("ANSWERS:\n", 1)[1]) or []
    role = Store.default().profile().roles[0].id
    return {"proposals": [{"question_id": a["question_id"], "target": role, "text": a["answer"].strip(),
                           "skills": []} for a in answers]}


def _compose(prompt: str) -> dict:
    base = Store.default().base_tailored()
    return base.model_dump(exclude_none=True) if base else {}


def _learn(prompt: str) -> dict:
    return {"preferences": [{"text": "Demo preference: prefer plain verbs over buzzwords.",
                             "rationale": "demo (fake engine)"}]}


def demo_engine() -> FakeEngine:
    return FakeEngine({"analyze": _analyze, "propose_evidence": _propose, "compose": _compose,
                       "repair": _compose, "learn_preferences": _learn})
