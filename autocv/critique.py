"""Hiring-manager review: reads a tailored resume the way the role's hiring manager
(deep read) and a recruiter (6-second skim of the top third) would, and returns a
verdict, scores and specific fixes.

Safety: the model may only rephrase, merge, cut or reorder what the draft already says.
Every proposed rewrite is fact-checked here before the user sees it; a rewrite that
fails becomes advice only. Fixes that need information the profile doesn't have come
back as questions (answered through the normal Gaps → approval flow), and things that
can't be fixed truthfully become notes for the cover letter or interview.
"""

from __future__ import annotations

import copy
import json
import re

from . import factcheck
from .ai import SYSTEM, _profile_text, _yaml
from .engine import Engine
from .schema import Claim, Knowledge, MasterProfile, TailoredResume

MAX_ISSUES = 8
KINDS = ["buried_must_have", "weak_opening", "duty_not_outcome", "redundant", "jargon", "too_long",
         "unused_evidence", "unclear", "seniority_signal", "ordering"]
ACTIONS = ["rewrite", "remove", "move_to_top", "advice"]
NON_CLAIM_TARGETS = ["headline", "competencies", "order", "length"]
_PATH_RE = re.compile(r"^(summary|highlights\[(\d+)\]|experience\[(\d+)\]\.(scope|bullets\[(\d+)\]))$")


# --------------------------------------------------------------------------- claim paths


def claim_paths(t: TailoredResume) -> dict[str, tuple[Claim, str | None]]:
    """Path (fact-check notation) → (claim, owning role id)."""
    out: dict[str, tuple[Claim, str | None]] = {}
    if t.summary:
        out["summary"] = (t.summary, None)
    for i, c in enumerate(t.highlights):
        out[f"highlights[{i}]"] = (c, None)
    for i, r in enumerate(t.experience):
        if r.scope:
            out[f"experience[{i}].scope"] = (r.scope, r.role)
        for j, c in enumerate(r.bullets):
            out[f"experience[{i}].bullets[{j}]"] = (c, r.role)
    return out


def _same(a: Claim, original: dict) -> bool:
    return " ".join(a.text.split()) == " ".join(original["text"].split())


def _locate(t: TailoredResume, issue: dict) -> tuple[list[Claim] | None, int | None, str]:
    """Find the issue's target in the *current* draft by its original text (robust to
    earlier accepted fixes shifting indices). Returns (container list, index, kind)."""
    m = _PATH_RE.match(issue["where"])
    original = issue.get("original")
    if not m or not original:
        return None, None, ""
    if m.group(1) == "summary":
        return (None, None, "summary") if t.summary and _same(t.summary, original) else (None, None, "")
    if m.group(2) is not None:
        lists = [t.highlights]
        kind = "highlights"
    else:
        lists = [r.bullets for r in t.experience]
        kind = "bullets"
        if m.group(4) == "scope":
            for r in t.experience:
                if r.scope and _same(r.scope, original):
                    return [r], 0, "scope"
            return None, None, ""
    for lst in lists:
        for idx, c in enumerate(lst):
            if _same(c, original):
                return lst, idx, kind
    return None, None, ""


def apply_issue(tailored: TailoredResume, issue: dict) -> TailoredResume:
    """Apply an accepted issue to a copy of the draft. Raises ValueError if the target
    line has changed since the review (so a stale fix is never misapplied)."""
    t = tailored.model_copy(deep=True)
    action = issue.get("action")
    if action == "advice":
        return t
    container, idx, kind = _locate(t, issue)
    if not kind:
        raise ValueError("That line has changed since the review — re-run the review.")
    if kind == "summary":
        if action == "rewrite":
            t.summary = Claim.model_validate(issue["rewrite"])
        elif action == "remove":
            t.summary = None
        return t
    if kind == "scope":
        role = container[0]
        if action == "rewrite":
            role.scope = Claim.model_validate(issue["rewrite"])
        elif action == "remove":
            role.scope = None
        return t
    if action == "rewrite":
        container[idx] = Claim.model_validate(issue["rewrite"])
    elif action == "remove":
        container.pop(idx)
    elif action == "move_to_top":
        container.insert(0, container.pop(idx))
    return t


# --------------------------------------------------------------------------- the model call


def critique_schema(paths: list[str], evidence_ids: list[str]) -> dict:
    score = {"type": "object", "additionalProperties": False, "required": ["score", "why"],
             "properties": {"score": {"type": "integer", "minimum": 1, "maximum": 10}, "why": {"type": "string"}}}
    return {
        "type": "object", "additionalProperties": False,
        "required": ["verdict", "scores", "skim", "strengths", "issues"],
        "properties": {
            "verdict": {"type": "object", "additionalProperties": False, "required": ["decision", "reason"],
                        "properties": {"decision": {"type": "string", "enum": ["interview", "borderline", "pass"]},
                                       "reason": {"type": "string"}}},
            "scores": {"type": "object", "additionalProperties": False,
                       "required": ["fit", "impact", "clarity", "seniority"],
                       "properties": {k: score for k in ("fit", "impact", "clarity", "seniority")}},
            "skim": {"type": "object", "additionalProperties": False, "required": ["takeaway", "lands", "misses"],
                     "properties": {"takeaway": {"type": "string"},
                                    "lands": {"type": "array", "items": {"type": "string"}},
                                    "misses": {"type": "array", "items": {"type": "string"}}}},
            "strengths": {"type": "array", "maxItems": 3, "items": {
                "type": "object", "additionalProperties": False, "required": ["where", "why"],
                "properties": {"where": {"type": "string", "enum": [*paths, *NON_CLAIM_TARGETS]},
                               "why": {"type": "string"}}}},
            "issues": {"type": "array", "maxItems": MAX_ISSUES, "items": {
                "type": "object", "additionalProperties": False,
                "required": ["where", "kind", "severity", "problem", "action", "rewrite", "question", "note_for"],
                "properties": {
                    "where": {"type": "string", "enum": [*paths, *NON_CLAIM_TARGETS]},
                    "kind": {"type": "string", "enum": KINDS},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "problem": {"type": "string"},
                    "action": {"type": "string", "enum": ACTIONS},
                    "rewrite": {"anyOf": [{"type": "null"}, {
                        "type": "object", "additionalProperties": False, "required": ["text", "sources"],
                        "properties": {"text": {"type": "string"},
                                       "sources": {"type": "array", "minItems": 1,
                                                   "items": {"type": "string", "enum": evidence_ids}}}}]},
                    "question": {"type": ["string", "null"],
                                 "description": "ask the candidate when the fix needs information not in the profile"},
                    "note_for": {"type": ["string", "null"], "enum": ["cover_letter", "interview", None]},
                }}},
        },
    }


def unused_must_have_evidence(profile: MasterProfile, tailored: TailoredResume, analysis: dict) -> list[dict]:
    """Evidence the analysis matched to a must-have that the draft doesn't cite."""
    cited = {s for c, _ in claim_paths(tailored).values() for s in c.sources}
    index = factcheck.evidence_index(profile)
    out = []
    for req in analysis.get("requirements", []):
        if req.get("priority") != "must":
            continue
        for eid in req.get("evidence", []):
            if eid not in cited and eid in index:
                out.append({"requirement": req["text"], "evidence_id": eid, "evidence": index[eid].split("\n")[0]})
    return out


def _prompt(profile: MasterProfile, tailored: TailoredResume, analysis: dict, knowledge: Knowledge | None) -> str:
    brief = {k: analysis.get(k) for k in ("company", "role", "industry", "track", "seniority", "summary")}
    brief["must_haves"] = [r["text"] for r in analysis.get("requirements", []) if r.get("priority") == "must"]
    prefs = [p.text for p in (knowledge.active_preferences() if knowledge else [])]
    numbered = {path: {"text": c.text, "sources": c.sources}
                for path, (c, _) in claim_paths(tailored).items()}
    return f"""TASK: critique
Review this tailored resume twice:
1. As the HIRING MANAGER for this exact role: a deep read. Does it prove the must-haves? Is impact shown \
as outcomes (not duties)? Does it signal the right seniority for the track? Is anything redundant, vague, \
jargon-heavy or too long?
2. As a RECRUITER doing a 6-second skim of the headline, summary and first highlights only: what is the \
takeaway, what lands, what is missed?

Then list at most {MAX_ISSUES} issues, most important first. For each, pick ONE action:
- rewrite: a better version of that exact line. It may only rephrase, merge or cut what its sources say — \
no new numbers, tools, employers, scope or outcomes; keep or narrow its sources; a bullet under a role may \
only cite that role's evidence (ids starting with that role id). Prefer leading with the outcome.
- remove: the line is weak or redundant. - move_to_top: a strong line is buried in its list.
- advice: no direct edit (use for headline/competencies/order/length, or when a fix needs information).
If the honest fix needs information the profile lacks (e.g. a metric), use action advice and put a short, \
specific question for the candidate in "question". If something can't be fixed truthfully in the resume, \
set note_for to cover_letter or interview. Never invent facts. Also give up to 3 strengths to keep.
Be specific and blunt; generic advice ("add more metrics") without a target line is useless.

ROLE BRIEF:
{_yaml(brief)}
MUST-HAVE EVIDENCE THE DRAFT DOESN'T USE (consider surfacing it):
{_yaml(unused_must_have_evidence(profile, tailored, analysis)) or "(none)"}
CANDIDATE'S APPROVED STYLE PREFERENCES:
{chr(10).join(f"- {p}" for p in prefs) or "(none)"}
HEADLINE: {profile.headline(tailored.headline).text if tailored.headline in {h.id for h in profile.headlines} else tailored.headline}
COMPETENCIES:
{_yaml([c.model_dump() for c in tailored.competencies])}
PROFILE (the only source of facts):
{_profile_text(profile)}
DRAFT CLAIMS BY PATH:
{json.dumps(numbered, indent=1, ensure_ascii=False)}
"""


def _sanitize(profile: MasterProfile, tailored: TailoredResume, raw: dict, run_no: int) -> dict:
    """Validate the model's issues and fact-check every rewrite before anyone sees it."""
    paths = claim_paths(tailored)
    checker = factcheck.FactChecker(profile)
    issues = []
    for n, issue in enumerate(raw.get("issues", [])[:MAX_ISSUES], 1):
        issue = dict(issue)
        where = issue.get("where", "")
        if where not in paths and where not in NON_CLAIM_TARGETS:
            continue
        issue["id"] = f"r{run_no}-i{n}"
        if where in paths:
            claim, role = paths[where]
            issue["original"] = {"text": claim.text, "sources": list(claim.sources)}
        else:
            role = None
            if issue.get("action") != "advice":
                issue["action"] = "advice"  # only claim lines can be edited directly
        if issue.get("action") == "rewrite":
            rewrite = issue.get("rewrite") or {}
            if not rewrite.get("text", "").strip() or not rewrite.get("sources"):
                issue.update(action="advice", rewrite=None)
            else:
                report = factcheck.Report()
                checker.check_claim(Claim(text=rewrite["text"], sources=rewrite["sources"]), where, report, role=role)
                if not report.ok:
                    issue.update(action="advice", rewrite=None,
                                 blocked=f"The suggested rewrite failed the fact-check ({report.errors[0].message})")
        else:
            issue["rewrite"] = None
        if issue.get("action") in ("remove", "move_to_top") and where not in paths:
            issue["action"] = "advice"
        issues.append(issue)
    strengths = [s for s in raw.get("strengths", []) if s.get("where") in paths or s.get("where") in NON_CLAIM_TARGETS]
    return {**{k: raw.get(k) for k in ("verdict", "scores", "skim")}, "strengths": strengths[:3], "issues": issues}


async def critique(engine: Engine, profile: MasterProfile, tailored: TailoredResume, analysis: dict,
                   knowledge: Knowledge | None = None, run_no: int = 1) -> dict:
    paths = list(claim_paths(tailored))
    schema = critique_schema(paths, list(factcheck.evidence_index(profile)))
    raw = await engine.complete(SYSTEM, _prompt(profile, tailored, analysis, knowledge), schema)
    return _sanitize(profile, tailored, copy.deepcopy(raw), run_no)
