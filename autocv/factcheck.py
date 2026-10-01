"""Blocking fact-check: every free-text claim in a TailoredResume must be traceable to
the MasterProfile evidence it cites.

Checks (errors block the build):
  * structure — referenced headline/role/project/education/extra ids exist and belong
    where they are used; every claim cites at least one existing evidence id
  * numbers — every number in a claim (incl. "six", "US$1.7M", "65%") appears in its
    cited sources
  * entities — every capitalised / acronym / alphanumeric term (e.g. "Kubernetes",
    "SOC 2", "AWS") appears in its cited sources, an approved synonym, or the
    profile vocabulary
  * competencies — every listed skill is a profile skill, an approved synonym, or a
    sub-phrase of one profile skill

Limitations (covered by Claude's review + the candidate's read-through): qualifiers
such as "over"/"roughly" are not compared, and lowercase claims ("led a team") are not
verified semantically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schema import Claim, MasterProfile, TailoredResume

NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
}
_MULT = {"k": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
_NUM_RE = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s?(k|m|bn|b|million|billion)?(?![a-z])", re.I
)
_WORD_RE = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.I)
_CLAUSE_END = re.compile(r"[.;:!?]$")
_DASHES = {"—", "–", "-", "|", "·"}
STOPWORDS = {"&", "and", "of", "the", "for", "a", "an", "in", "on", "to", "with", "-", "/"}


@dataclass
class Issue:
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


@dataclass
class Report:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, where: str, msg: str) -> None:
        self.errors.append(Issue(where, msg))

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(Issue(where, msg))


# --------------------------------------------------------------------------- text utils


def normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[–—‑]", "-", text).replace(" ", " ")
    return text.lower()


def numbers(text: str) -> set[float]:
    text = normalize(text)
    found: set[float] = set()
    for m in _NUM_RE.finditer(text):
        value = float(m.group(1).replace(",", ""))
        found.add(value * _MULT.get((m.group(2) or "").lower(), 1))
    for m in _WORD_RE.finditer(text):
        found.add(float(NUMBER_WORDS[m.group(1).lower()]))
    return found


def _contains_number(pool: set[float], value: float) -> bool:
    return any(abs(p - value) <= 1e-9 * max(1.0, abs(value)) for p in pool)


def entity_terms(text: str) -> list[str]:
    """Capitalised, acronym or alphanumeric terms that are not clause-initial."""
    tokens = text.split()
    terms = []
    for i, raw in enumerate(tokens):
        prev = tokens[i - 1] if i else ""
        clause_initial = i == 0 or bool(_CLAUSE_END.search(prev)) or prev in _DASHES
        tok = raw.strip("()[]{},.;:!?\"'“”‘’")
        tok = re.sub(r"(['’]s)$", "", tok)
        if not tok or tok in _DASHES:
            continue
        if not re.search(r"[A-Z]", tok):
            continue
        if clause_initial and re.fullmatch(r"[A-Z][a-z]+(-[a-z]+)*", tok):
            continue  # ordinary capitalised first word, e.g. "Built", "Cross-functional"
        terms.append(tok)
    return terms


def _term_parts(term: str) -> list[str]:
    return [p for p in term.split("/") if p]


# --------------------------------------------------------------------------- evidence


def evidence_index(profile: MasterProfile) -> dict[str, str]:
    """id → citable text. Role-bound evidence includes the role's locked fields so
    a bullet may name its own employer/title."""
    idx: dict[str, str] = {}
    for e in profile.summary_facts + profile.highlights:
        idx[e.id] = e.text
    for r in profile.roles:
        locked = f"{r.employer}, {r.location} — {r.title} ({r.dates})"
        idx[r.id] = locked
        if r.scope:
            idx[r.scope.id] = f"{r.scope.text}\n{locked}"
        for a in r.achievements:
            idx[a.id] = f"{a.text}\n{locked}"
        for s in r.sub_roles:
            idx[s.id] = f"{s.label} {s.text}\n{locked}"
    for i in profile.projects + profile.education + profile.extras:
        idx[i.id] = f"{i.label} {i.text}"
    return idx


class FactChecker:
    def __init__(self, profile: MasterProfile):
        self.profile = profile
        self.index = evidence_index(profile)
        self.vocabulary = normalize(" \n ".join(profile.vocabulary))
        self.synonyms = [[normalize(t) for t in group] for group in profile.synonyms]
        self.skill_items = [normalize(i) for g in profile.skills for i in g.items]

    # -- claims ------------------------------------------------------------------
    def check_claim(self, claim: Claim, where: str, report: Report) -> None:
        if not claim.text.strip():
            report.error(where, "empty text")
            return
        if not claim.sources:
            report.error(where, "no sources cited — every claim must cite profile evidence ids")
            return
        missing = [s for s in claim.sources if s not in self.index]
        if missing:
            report.error(where, f"unknown source id(s): {', '.join(missing)}")
            return
        corpus = normalize("\n".join(self.index[s] for s in claim.sources))
        pool = numbers(corpus)

        for value in sorted(numbers(claim.text)):
            if not _contains_number(pool, value):
                shown = int(value) if value.is_integer() else value
                report.error(where, f"number {shown:,} not found in cited sources {claim.sources}")

        for term in entity_terms(self._strip_approved_phrases(claim.text, corpus)):
            if not self._term_supported(term, corpus):
                report.error(where, f'term "{term}" not found in cited sources {claim.sources} '
                                    "(cite the right evidence, rephrase, or add it to the profile)")

    def _strip_approved_phrases(self, text: str, corpus: str) -> str:
        """Remove multi-word synonyms/vocabulary (e.g. "Web Application Firewall") whose
        meaning is supported, so they are not checked word by word."""
        phrases = [v for v in self.profile.vocabulary if " " in v]
        for group in self.synonyms:
            if any(alt in corpus for alt in group):
                phrases += [m for m in group if " " in m]
        for phrase in sorted(phrases, key=len, reverse=True):
            text = re.sub(re.escape(phrase), "approved", text, flags=re.I)
        return text

    def _term_supported(self, term: str, corpus: str) -> bool:
        for part in _term_parts(term):
            n = normalize(part)
            if n in corpus or n in self.vocabulary:
                continue
            if any(n in group and any(alt in corpus for alt in group) for group in self.synonyms):
                continue
            # "Splunk-based", "edge-to-application": accept if each capitalised piece is supported
            pieces = [x for x in part.split("-") if re.search(r"[A-Z0-9]", x)]
            if len(pieces) and len(pieces) < len(part.split("-")) and all(
                normalize(x) in corpus or normalize(x) in self.vocabulary for x in pieces
            ):
                continue
            return False
        return True

    # -- competencies --------------------------------------------------------------
    def check_skill(self, item: str, where: str, report: Report) -> None:
        n = normalize(item).strip()
        if n in self.skill_items:
            return
        for group in self.synonyms:
            if n in group and any(alt in self.skill_items for alt in group):
                return
        tokens = [t for t in re.findall(r"[a-z0-9+#.$/&-]+", n) if t not in STOPWORDS]
        expanded = [{t} | {alt for g in self.synonyms if t in g for alt in g} for t in tokens]
        for skill in self.skill_items:
            if tokens and all(any(alt in skill for alt in options) for options in expanded):
                if numbers(item) <= numbers(skill):
                    return
        report.error(where, f'skill "{item}" is not in the profile skills (or an approved synonym)')

    # -- whole resume --------------------------------------------------------------
    def check(self, t: TailoredResume) -> Report:
        p, report = self.profile, Report()

        if t.headline not in {h.id for h in p.headlines}:
            report.error("headline", f"unknown headline id '{t.headline}' (choose from the approved list)")

        if t.summary:
            self.check_claim(t.summary, "summary", report)
        else:
            report.warn("summary", "no summary")

        for i, h in enumerate(t.highlights):
            self.check_claim(h, f"highlights[{i}]", report)

        for i, comp in enumerate(t.competencies):
            for j, item in enumerate(comp.items):
                self.check_skill(item, f"competencies[{i}].items[{j}]", report)

        role_ids = [r.id for r in p.roles]
        used = []
        for i, tr in enumerate(t.experience):
            where = f"experience[{i}]"
            if tr.role not in role_ids:
                report.error(where, f"unknown role id '{tr.role}'")
                continue
            used.append(tr.role)
            role = p.role(tr.role)
            if tr.scope:
                self.check_claim(tr.scope, f"{where}.scope", report)
            for j, b in enumerate(tr.bullets):
                self.check_claim(b, f"{where}.bullets[{j}]", report)
            sub_ids = {s.id for s in role.sub_roles}
            for j, sr in enumerate(tr.sub_roles):
                if sr.id not in sub_ids:
                    report.error(f"{where}.sub_roles[{j}]", f"'{sr.id}' is not a sub-role of {tr.role}")
                elif sr.text:
                    self.check_claim(sr.text, f"{where}.sub_roles[{j}]", report)
            if not tr.bullets and not tr.scope and not tr.sub_roles:
                report.warn(where, "role has no content beyond the header")

        if used != [r for r in role_ids if r in used]:
            report.warn("experience", "roles are not in reverse-chronological (profile) order")
        dropped = [r for r in role_ids if r not in used]
        if dropped:
            report.warn("experience", f"roles omitted (creates a visible gap): {', '.join(dropped)}")

        for key, pool in (("projects", p.projects), ("education", p.education), ("extras", p.extras)):
            ids = {x.id for x in pool}
            for j, entry in enumerate(getattr(t, key)):
                item_id = entry.id if key == "projects" else entry
                if item_id not in ids:
                    report.error(f"{key}[{j}]", f"unknown {key} id '{item_id}'")
                elif key == "projects" and entry.text:
                    self.check_claim(entry.text, f"{key}[{j}]", report)

        return report


def check(profile: MasterProfile, tailored: TailoredResume) -> Report:
    return FactChecker(profile).check(tailored)
