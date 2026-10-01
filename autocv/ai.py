"""AI tasks behind the web UI: analyse a JD, turn gap answers into proposed evidence,
compose a tailored resume, and repair it until the fact-check passes.

The model never writes to the profile. Proposed evidence is returned to the user for
approval; only approved items are added (by `add_evidence`). JSON schemas constrain
every id the model can cite to ids that exist in the profile.
"""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from . import factcheck
from .engine import Engine
from .render import docx_text, render
from .schema import Claim, Knowledge, MasterProfile, Preference, TailoredResume

ROOT = Path(__file__).resolve().parent.parent
INDUSTRIES = ["banking", "tech", "quant", "fintech", "telco", "consulting"]
TRACKS = ["manager", "ic", "hybrid"]
MAX_REPAIR_ROUNDS = 3
MAX_TRIM_ROUNDS = 2
LINE_CHARS = 100          # rough characters per rendered line (calibrated on the base resume)
DEFAULT_BUDGET = 110      # estimated lines for 2 pages when there's no base resume to measure

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


def analysis_schema(evidence_ids: list[str], knowledge_ids: list[str] | None = None) -> dict:
    ids = {"type": "array", "items": {"type": "string", "enum": evidence_ids}}
    kid = {"type": "string", "enum": [*(knowledge_ids or []), ""]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["company", "role", "industry", "track", "seniority", "location", "summary",
                     "requirements", "keywords", "questions", "known_gaps"],
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
                "required": ["id", "requirement", "question", "prefill_from"],
                "properties": {
                    "id": {"type": "string"},
                    "requirement": {"type": "string"},
                    "question": {"type": "string"},
                    "prefill_from": {**kid, "description": "id of a related past answer to pre-fill, or empty"},
                }}},
            "known_gaps": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["requirement", "knowledge_id"],
                "properties": {"requirement": {"type": "string"}, "knowledge_id": kid}}},
        },
    }


def _knowledge_text(knowledge: Knowledge | None) -> str:
    if not knowledge or not knowledge.answers:
        return "(none yet)"
    return _yaml([{"id": k.id, "topic": k.topic, "question": k.question, "kind": k.kind,
                   "answer": k.answer or None, "date": k.date} for k in knowledge.answers])


async def analyze(engine: Engine, profile: MasterProfile, jd: str, knowledge: Knowledge | None = None) -> dict:
    ids = list(factcheck.evidence_index(profile))
    kids = [k.id for k in knowledge.answers] if knowledge else []
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
- PAST ANSWERS are the candidate's answers on earlier applications (not evidence, never cite them):
  - kind no_experience on the SAME topic → do NOT ask again; mark that requirement status gap with \
note "Known gap — you answered no real experience on <date>", and list it in known_gaps with its id.
  - a related but not identical past answer → still ask, and set prefill_from to that answer's id so \
the candidate can confirm or update it. Otherwise prefill_from is "".

INDUSTRY LENSES:
{_yaml({k: v["signals"] for k, v in _config("industries.yaml").items()})}
PAST ANSWERS:
{_knowledge_text(knowledge)}
PROFILE:
{_profile_text(profile)}
JOB DESCRIPTION:
{jd}
"""
    result = await engine.complete(SYSTEM, prompt, analysis_schema(ids, kids))
    known, known_k = set(ids), set(kids)
    for req in result.get("requirements", []):
        req["evidence"] = [e for e in req.get("evidence", []) if e in known]
    for q in result.get("questions", []):
        if q.get("prefill_from") not in known_k:
            q["prefill_from"] = ""
    result["known_gaps"] = [g for g in result.get("known_gaps", []) if g.get("knowledge_id") in known_k]
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
    existing = set(profile.all_ids()) | set(profile.retired_ids)  # never reuse a deleted id
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


def estimate_lines(profile: MasterProfile, tailored: TailoredResume) -> int:
    """Approximate rendered line count — a fast proxy for page count (Word is the truth)."""
    with tempfile.TemporaryDirectory() as tmp:
        lines = docx_text(render(profile, tailored, Path(tmp) / "r.docx"))
    return sum(max(1, -(-len(line) // LINE_CHARS)) for line in lines)


def length_budget(profile: MasterProfile, base: TailoredResume | None) -> dict:
    """The candidate's own 2-page resume sets the budget."""
    if base is None:
        return {"lines": DEFAULT_BUDGET, "words": 1000}
    with tempfile.TemporaryDirectory() as tmp:
        lines = docx_text(render(profile, base, Path(tmp) / "r.docx"))
    est = sum(max(1, -(-len(line) // LINE_CHARS)) for line in lines)
    return {"lines": est, "words": len(" ".join(lines).split())}


def _compose_prompt(profile: MasterProfile, analysis: dict, base: TailoredResume | None,
                    guidance: str, preferences: list[Preference] | None = None,
                    budget: dict | None = None) -> str:
    budget = budget or {"lines": DEFAULT_BUDGET, "words": 1000}
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
- Length: HARD LIMIT of 2 pages — at most {budget["words"] - 60} words in total (the base resume is \
{budget["words"]} words and already fills 2 pages). Prefer fewer, stronger bullets: 3-4 highlights, \
4-5 bullets for the current role, fewer for older roles.
- Every claim's sources must cover every number, tool, framework and proper noun in it.

INDUSTRY LENS ({industry}) — emphasis only, never facts:
{_yaml(lens)}
TRACK ({track}) — emphasis only:
{_yaml(track_rules)}
EXTRA GUIDANCE FROM THE CANDIDATE (for this role):
{guidance or "(none)"}
STYLE PREFERENCES THE CANDIDATE APPROVED (apply them; they never override the rules or the facts):
{chr(10).join(f"- {p.text}" for p in preferences or []) or "(none)"}
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
The tailored resume below failed the fact-check. Fix every error by rewording the claim to match its \
cited evidence, or removing the unsupported part (or the whole claim). Never add facts. Never cite evidence \
from a different role to make a bullet pass. Keep everything else as is.

ERRORS:
{errors}
PROFILE:
{_profile_text(profile)}
TAILORED RESUME:
{json.dumps(tailored, indent=1, ensure_ascii=False)}
"""


def _trim_prompt(profile: MasterProfile, tailored: dict, lines: int, budget: int, analysis: dict) -> str:
    over = lines - budget
    return f"""TASK: trim
This tailored resume is too long for 2 pages: about {lines} lines against a budget of {budget}. Cut at \
least {over + 4} lines. In order of preference: drop the least relevant bullets of the OLDEST roles, merge \
overlapping bullets, shorten long bullets, cut highlights to 3, shorten the summary to 2 sentences. Keep \
every role (a scope line is enough for old roles) and the facts that match the job's must-haves. Only \
remove or shorten — never add facts or sources. Keep each remaining claim's sources accurate.

JOB MUST-HAVES:
{_yaml([r["text"] for r in analysis.get("requirements", []) if r.get("priority") == "must"])}
TAILORED RESUME:
{json.dumps(tailored, indent=1, ensure_ascii=False)}
"""


async def _validated(engine: Engine, profile: MasterProfile, schema: dict, raw) -> tuple[TailoredResume, factcheck.Report, int]:
    """Validate + fact-check, asking the model to repair up to MAX_REPAIR_ROUNDS times."""
    rounds = 0
    while True:
        tailored = TailoredResume.model_validate(raw)
        report = factcheck.check(profile, tailored)
        if report.ok or rounds >= MAX_REPAIR_ROUNDS:
            return tailored, report, rounds
        rounds += 1
        raw = await engine.complete(SYSTEM, _repair_prompt(profile, raw, report), schema)


async def fit_to_length(engine: Engine, profile: MasterProfile, tailored: TailoredResume, analysis: dict,
                        budget: int, max_rounds: int = MAX_TRIM_ROUNDS) -> dict:
    """Trim until the estimate fits the budget. A trim that breaks the fact-check is discarded."""
    schema = tailored_schema(profile, analysis.get("track"))
    lines, trims, rounds = estimate_lines(profile, tailored), 0, 0
    while lines > budget and trims < max_rounds:
        trims += 1
        raw = await engine.complete(SYSTEM, _trim_prompt(profile, tailored.model_dump(exclude_none=True), lines,
                                                         budget, analysis), schema)
        try:
            candidate, report, r = await _validated(engine, profile, schema, raw)
        except ValidationError:
            break
        rounds += r
        if not report.ok:
            break  # keep the last version that passed
        tailored, lines = candidate, estimate_lines(profile, candidate)
    return {"tailored": tailored, "trim_rounds": trims, "repair_rounds": rounds,
            "length": {"lines": lines, "budget": budget, "fits": lines <= budget}}


async def compose(engine: Engine, profile: MasterProfile, analysis: dict,
                  base: TailoredResume | None = None, guidance: str = "",
                  preferences: list[Preference] | None = None) -> dict:
    schema = tailored_schema(profile, analysis.get("track"))
    budget = length_budget(profile, base)
    raw = await engine.complete(SYSTEM, _compose_prompt(profile, analysis, base, guidance, preferences, budget),
                                schema)
    tailored, report, rounds = await _validated(engine, profile, schema, raw)
    result = {"tailored": tailored, "report": report, "repair_rounds": rounds, "trim_rounds": 0,
              "length": {"lines": estimate_lines(profile, tailored), "budget": budget["lines"]}}
    if report.ok:
        fitted = await fit_to_length(engine, profile, tailored, analysis, budget["lines"])
        result.update(tailored=fitted["tailored"], trim_rounds=fitted["trim_rounds"], length=fitted["length"],
                      repair_rounds=rounds + fitted["repair_rounds"],
                      report=factcheck.check(profile, fitted["tailored"]))
    return result


# --------------------------------------------------------------------------- learn style preferences


def _claims(t: TailoredResume) -> list[tuple[str, Claim]]:
    out: list[tuple[str, Claim]] = []
    if t.summary:
        out.append(("summary", t.summary))
    out += [(f"highlight {i + 1}", c) for i, c in enumerate(t.highlights)]
    for r in t.experience:
        if r.scope:
            out.append((f"{r.role} scope", r.scope))
        out += [(f"{r.role} bullet", c) for c in r.bullets]
    return out


def edited_claims(ai_draft: TailoredResume, current: TailoredResume) -> list[dict]:
    """What the user changed relative to the AI's draft, matching claims by the evidence
    they cite (robust to reordering): edited, removed and user-added claims."""
    remaining = _claims(current)
    edits: list[dict] = []
    for where, before in _claims(ai_draft):
        match = next((i for i, (_, c) in enumerate(remaining) if set(c.sources) == set(before.sources)), None)
        if match is None:
            edits.append({"where": where, "before": before.text, "after": "(removed)"})
            continue
        _, after = remaining.pop(match)
        if " ".join(after.text.split()) != " ".join(before.text.split()):
            edits.append({"where": where, "before": before.text, "after": after.text})
    edits += [{"where": where, "before": "(added by the candidate)", "after": c.text} for where, c in remaining]
    if ai_draft.headline != current.headline:
        edits.append({"where": "headline", "before": ai_draft.headline, "after": current.headline})
    return edits


def preferences_schema() -> dict:
    return {
        "type": "object", "additionalProperties": False, "required": ["preferences"],
        "properties": {"preferences": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["text", "rationale"],
            "properties": {
                "text": {"type": "string", "description": "one short, reusable style rule"},
                "rationale": {"type": "string", "description": "which edits/guidance show it"},
            }}}},
    }


async def learn_preferences(engine: Engine, edits: list[dict], guidance: list[str],
                            existing: list[Preference], rejected: list[dict] | None = None) -> list[dict]:
    """Propose reusable writing-style preferences from the candidate's edits, guidance and
    the review suggestions they rejected."""
    rejected = rejected or []
    if not edits and not rejected and not any(g.strip() for g in guidance):
        return []
    prompt = f"""TASK: learn_preferences
The candidate reviewed AI-written resume drafts. Below are their edits (AI draft → their version) and \
the guidance they gave. Infer at most 5 REUSABLE writing-style preferences that would make future drafts \
need fewer edits — e.g. word choice, tone, sentence length, what to lead with, what to cut, formatting \
habits. Rules:
- Style only. Never a fact, number, employer, tool or claim about experience.
- Only propose a preference with clear support in the edits or guidance; fewer is better than weak ones.
- Skip anything already covered by the existing preferences.
- Ignore edits that only fix facts or citations (those are not style).

EXISTING PREFERENCES:
{chr(10).join(f"- {p.text}" for p in existing) or "(none)"}
GUIDANCE GIVEN:
{chr(10).join(f"- {g}" for g in guidance if g.strip()) or "(none)"}
EDITS (accepted review fixes show up here too):
{_yaml(edits) if edits else "(none)"}
REVIEW SUGGESTIONS THE CANDIDATE REJECTED (learn what they DON'T want):
{_yaml(rejected) if rejected else "(none)"}
"""
    result = await engine.complete(SYSTEM, prompt, preferences_schema())
    return [p for p in result.get("preferences", []) if p.get("text", "").strip()][:5]
