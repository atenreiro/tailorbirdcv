"""AI tasks behind the web UI: analyse a JD, turn gap answers into proposed evidence,
compose a tailored resume, and repair it until the fact-check passes.

The model never writes to the profile. Proposed evidence is returned to the user for
approval; only approved items are added (by `add_evidence`). JSON schemas constrain
every id the model can cite to ids that exist in the profile.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from . import factcheck
from .engine import Engine
from .schema import MasterProfile, TailoredResume

ROOT = Path(__file__).resolve().parent.parent
INDUSTRIES = ["banking", "tech", "quant", "fintech", "telco", "consulting"]
TRACKS = ["manager", "ic", "hybrid"]
MAX_REPAIR_ROUNDS = 3

SYSTEM = """You are AutoCV, a meticulous resume strategist for a senior cybersecurity professional \
(targets: senior IC and manager roles in banking, tech, quant/trading, fintech; Singapore/APAC).

Absolute rules:
- Never invent. Only use facts present in the candidate's PROFILE. No new numbers, tools, employers, \
scope, outcomes, certifications, or implied experience ("familiar with", "exposure to").
- Never inflate: keep verbs and scope as strong as the source and no stronger \
("supported" must not become "led"; "team" must not become "organization").
- Rephrasing, reordering, merging, trimming and mirroring the job description's vocabulary are allowed \
when the meaning is unchanged.
- Every claim cites the profile evidence ids it relies on (all numbers, tools and names in it).
- US English spelling. Concise, achievement-first bullets. Answer only with JSON matching the schema."""


def _yaml(data) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


def _config(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


def _profile_text(profile: MasterProfile) -> str:
    return _yaml(profile.model_dump(exclude_none=True))


# --------------------------------------------------------------------------- analyze


def analysis_schema(evidence_ids: list[str]) -> dict:
    ids = {"type": "array", "items": {"type": "string", "enum": evidence_ids}}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["company", "role", "industry", "track", "seniority", "location", "summary",
                     "requirements", "keywords", "questions"],
        "properties": {
            "company": {"type": "string"},
            "role": {"type": "string"},
            "industry": {"type": "string", "enum": INDUSTRIES},
            "track": {"type": "string", "enum": TRACKS},
            "seniority": {"type": "string"},
            "location": {"type": "string"},
            "summary": {"type": "string", "description": "2-3 sentences: what the role really needs"},
            "requirements": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["text", "priority", "status", "evidence", "note"],
                "properties": {
                    "text": {"type": "string"},
                    "priority": {"type": "string", "enum": ["must", "nice"]},
                    "status": {"type": "string", "enum": ["strong", "partial", "gap"]},
                    "evidence": ids,
                    "note": {"type": "string", "description": "why this status, briefly"},
                }}},
            "keywords": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["term", "priority", "aliases"],
                "properties": {
                    "term": {"type": "string"},
                    "priority": {"type": "string", "enum": ["must", "nice"]},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                }}},
            "questions": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "requirement", "question"],
                "properties": {
                    "id": {"type": "string"},
                    "requirement": {"type": "string"},
                    "question": {"type": "string"},
                }}},
        },
    }


async def analyze(engine: Engine, profile: MasterProfile, jd: str) -> dict:
    ids = list(factcheck.evidence_index(profile))
    prompt = f"""TASK: analyze
Analyze this job description against the candidate's profile.

- industry: pick the closest lens from {INDUSTRIES} (lenses below).
- track: manager (people leadership is the core), ic (hands-on depth is the core), or hybrid (player-coach).
- requirements: every distinct requirement in JD order. status: strong = clear profile evidence; \
partial = adjacent evidence; gap = none. Cite the evidence ids.
- keywords: 15-30 ATS terms exactly as the JD writes them, with common aliases.
- questions: for each must-have gap or weak partial (max 6), one concrete question asking whether the \
candidate has real experience the profile does not show (where, what, scale). Ids q1, q2, ... \
Do not ask about things the profile already evidences.

INDUSTRY LENSES:
{_yaml({k: v["signals"] for k, v in _config("industries.yaml").items()})}
PROFILE:
{_profile_text(profile)}
JOB DESCRIPTION:
{jd}
"""
    result = await engine.complete(SYSTEM, prompt, analysis_schema(ids))
    known = set(ids)
    for req in result.get("requirements", []):
        req["evidence"] = [e for e in req.get("evidence", []) if e in known]
    return result


# --------------------------------------------------------------------------- gap answers → evidence


def proposals_schema(role_ids: list[str], categories: list[str]) -> dict:
    return {
        "type": "object", "additionalProperties": False, "required": ["proposals"],
        "properties": {"proposals": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["question_id", "target", "text", "skills"],
            "properties": {
                "question_id": {"type": "string"},
                "target": {"type": "string", "enum": [*role_ids, "general"],
                           "description": "role the experience belongs to, or general"},
                "text": {"type": "string", "description": "one resume-ready evidence sentence"},
                "skills": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["category", "item"],
                    "properties": {"category": {"type": "string", "enum": categories},
                                   "item": {"type": "string"}}}},
            }}}},
    }


async def propose_evidence(engine: Engine, profile: MasterProfile, answers: list[dict]) -> list[dict]:
    """answers: [{question_id, question, answer}] — only answers claiming real experience."""
    if not answers:
        return []
    prompt = f"""TASK: propose_evidence
The candidate answered questions about experience missing from the profile. Turn each answer into \
ONE concise, resume-ready evidence sentence that states only what the candidate wrote — no added \
numbers, tools, scope or outcomes, no strengthening. If an answer describes no real hands-on \
experience (only learning, exposure or interest), return no proposal for it. Assign the role it \
happened in (by id, using the roles' dates and employers) or "general". List skills only when the \
answer shows hands-on use, using an existing category.

ROLES:
{_yaml([{"id": r.id, "employer": r.employer, "title": r.title, "dates": r.dates} for r in profile.roles])}
ANSWERS:
{_yaml(answers)}
"""
    schema = proposals_schema([r.id for r in profile.roles], [g.category for g in profile.skills] or ["Other"])
    result = await engine.complete(SYSTEM, prompt, schema)
    return result.get("proposals", [])


def add_evidence(profile: MasterProfile, target: str, text: str,
                 skills: list[dict] | None = None, note: str | None = None) -> tuple[MasterProfile, str]:
    """Append user-approved evidence. Returns the new profile and the new evidence id."""
    data = profile.model_dump(exclude_none=True)
    item = {"text": text.strip(), "source": "interview", "in_base_resume": False}
    if note:
        item["note"] = note
    existing = set(profile.all_ids())
    if target == "general":
        n = 1
        while f"summary.s{n}" in existing:
            n += 1
        item["id"] = f"summary.s{n}"
        data["summary_facts"].append(item)
    else:
        role = next((r for r in data["roles"] if r["id"] == target), None)
        if role is None:
            raise KeyError(target)
        n = 1
        while f"{target}.a{n}" in existing:
            n += 1
        item["id"] = f"{target}.a{n}"
        role["achievements"].append(item)
    for skill in skills or []:
        group = next((g for g in data["skills"] if g["category"] == skill["category"]), None)
        if group is None:
            group = {"category": skill["category"], "items": []}
            data["skills"].append(group)
        if skill["item"] not in group["items"]:
            group["items"].append(skill["item"])
    return MasterProfile.model_validate(data), item["id"]


# --------------------------------------------------------------------------- compose + repair


def tailored_schema(profile: MasterProfile, track: str | None) -> dict:
    schema = copy.deepcopy(TailoredResume.model_json_schema())
    defs = schema["$defs"]
    ids = list(factcheck.evidence_index(profile))
    defs["Claim"]["properties"]["sources"] = {"type": "array", "minItems": 1,
                                              "items": {"type": "string", "enum": ids}}
    headlines = [h.id for h in profile.headlines if not track or track in h.tracks] or \
        [h.id for h in profile.headlines]
    schema["properties"]["headline"] = {"type": "string", "enum": headlines}
    defs["TailoredRole"]["properties"]["role"] = {"type": "string", "enum": [r.id for r in profile.roles]}
    sub_ids = [s.id for r in profile.roles for s in r.sub_roles]
    if sub_ids:
        defs["TailoredSubRole"]["properties"]["id"] = {"type": "string", "enum": sub_ids}
    if profile.projects:
        defs["TailoredProject"]["properties"]["id"] = {"type": "string", "enum": [p.id for p in profile.projects]}
    for key, pool in (("education", profile.education), ("extras", profile.extras)):
        if pool:
            schema["properties"][key] = {"type": "array", "items": {"type": "string", "enum": [i.id for i in pool]}}
    return schema


def _compose_prompt(profile: MasterProfile, analysis: dict, base: TailoredResume | None,
                    guidance: str) -> str:
    industry, track = analysis.get("industry"), analysis.get("track")
    lens = _config("industries.yaml").get(industry, {})
    track_rules = _config("tracks.yaml").get(track, {})
    base_text = _yaml(base.model_dump(exclude_none=True)) if base else "(none)"
    brief = {k: analysis.get(k) for k in ("company", "role", "industry", "track", "seniority", "summary",
                                          "requirements", "keywords")}
    return f"""TASK: compose
Write the tailored resume for this job as JSON.

How:
- headline: the approved headline id that best fits the track.
- summary: 2-3 sentences rewritten for this job; cite every evidence id used.
- highlights: 3-5, most relevant first.
- competencies: reorder groups/items so the job's priorities lead. Items must be existing profile \
skills (exact text, an approved synonym, or a sub-phrase of one skill). Group labels may change.
- experience: include EVERY role in profile order. Reorder bullets by relevance, rephrase in the \
job's vocabulary where meaning is identical, merge or drop weak ones; you may surface evidence with \
in_base_resume: false. Older roles get fewer bullets. Keep the scope line for each role (cite it).
- projects, education, extras: choose and order ids (education/extras are rendered verbatim).
- Length: must fit 2 pages — stay at or below the base resume's total length (≈1,000 words).
- Every claim's sources must cover every number, tool, framework and proper noun in it.

INDUSTRY LENS ({industry}) — emphasis only, never facts:
{_yaml(lens)}
TRACK ({track}) — emphasis only:
{_yaml(track_rules)}
EXTRA GUIDANCE FROM THE CANDIDATE:
{guidance or "(none)"}
JOB ANALYSIS:
{_yaml(brief)}
PROFILE (the only source of facts):
{_profile_text(profile)}
BASE RESUME LAYOUT (the candidate's current resume, for format and default content):
{base_text}
"""


def _repair_prompt(profile: MasterProfile, tailored: dict, report: factcheck.Report) -> str:
    errors = "\n".join(f"- {e}" for e in report.errors)
    return f"""TASK: repair
The tailored resume below failed the fact-check. Fix every error by citing the right evidence, \
rewording to match the source, or removing the claim. Never add facts. Keep everything else as is.

ERRORS:
{errors}
PROFILE:
{_profile_text(profile)}
TAILORED RESUME:
{json.dumps(tailored, indent=1, ensure_ascii=False)}
"""


async def compose(engine: Engine, profile: MasterProfile, analysis: dict,
                  base: TailoredResume | None = None, guidance: str = "") -> dict:
    schema = tailored_schema(profile, analysis.get("track"))
    raw = await engine.complete(SYSTEM, _compose_prompt(profile, analysis, base, guidance), schema)
    rounds = 0
    while True:
        tailored = TailoredResume.model_validate(raw)
        report = factcheck.check(profile, tailored)
        if report.ok or rounds >= MAX_REPAIR_ROUNDS:
            return {"tailored": tailored, "report": report, "repair_rounds": rounds}
        rounds += 1
        raw = await engine.complete(SYSTEM, _repair_prompt(profile, raw, report), schema)
