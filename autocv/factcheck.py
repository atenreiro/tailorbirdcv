"""Blocking fact-check: every free-text claim in a TailoredResume must be traceable to
the MasterProfile evidence it cites.

Checks (errors block the build):
  * structure — referenced headline/role/project/education/extra ids exist and belong
    where they are used; every claim cites at least one existing evidence id; claims
    under a role cite only that role's evidence; role headers are not citable
  * numbers — every number in a claim (incl. "six", "US$1.7M", "65%", "3x", "3rd") and
    every magnitude word ("hundreds", "doubled", "tenfold") appears in its cited sources
  * entities — every capitalised / acronym / alphanumeric term (e.g. "Kubernetes",
    "SOC 2", "AWS", "24x7") appears in its cited sources (whole-word match), an approved
    synonym, or the profile vocabulary. A capitalised word starting a clause passes only
    if it is an ordinary dictionary word or appears in the sources ("Built" ok,
    "Microsoft" not)
  * risky lowercase words — technologies, credentials and scope/inflation words
    ("kubernetes", "certified", "global", "organization", "single-handedly"…) must
    appear in the cited sources
  * competencies — every listed skill is a profile skill, an approved synonym, or a
    whole-word sub-phrase of one profile skill; group labels only use skill vocabulary
  * characters — no non-Latin letters (homoglyph tricks)

Limitations (covered by Claude's self-review + the candidate's read-through): ordinary
lowercase rewording is not verified semantically, and the units/meaning attached to a
number ("six a month" vs "six a week") are not compared.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .schema import Claim, MasterProfile, TailoredResume

NUMBER_WORDS = {
    "zero": 0, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000, "dozen": 12,
}
# Vague magnitudes / multipliers: allowed only if the same word is in the sources.
MAGNITUDE_RE = re.compile(
    r"\b(dozens|hundreds|thousands|millions|billions|twice|double[ds]?|doubling|triple[ds]?|tripling|"
    r"quadrupled|halved|halving|\w+fold|multiple-fold)\b", re.I)
_MULT = {"k": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
# possessive quantifiers: "1.5x" must not backtrack into a bare "1"
_NUM_RE = re.compile(r"(?<![\w.])(\d[\d,]*+(?:\.\d++)?)\s?(k|m|bn|b|million|billion)?(?![a-z0-9])", re.I)
_ORDINAL_RE = re.compile(r"(?<![\w.])(\d+)(?:st|nd|rd|th)\b", re.I)
_MULTIPLIER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?x\b", re.I)
_WORD_RE = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.I)
_CLAUSE_END = re.compile(r"[.;:!?]$")
_DASHES = {"—", "–", "-", "|", "·"}
STOPWORDS = {"&", "and", "of", "the", "for", "a", "an", "in", "on", "to", "with", "-", "/"}

# Lowercase words that change what a claim asserts. Each must appear in the cited sources.
RISKY_WORDS = {
    # scope / inflation
    "global", "globally", "worldwide", "enterprise-wide", "bank-wide", "company-wide", "firm-wide",
    "group-wide", "organization-wide", "organisation-wide", "organization", "organisation",
    "sole", "solely", "single-handedly", "entire", "entirely", "head", "director", "chief",
    "board", "c-suite", "regional", "nationwide", "national",
    # credentials
    "certified", "certification", "certificate", "accredited", "licensed", "degree", "masters",
    "master's", "phd", "doctorate", "mba", "award", "award-winning", "patent", "patented",
    "founder", "co-founder", "founded", "co-founded", "invented", "inventor", "published", "author",
    # technologies / domains often written in lowercase
    "kubernetes", "k8s", "terraform", "docker", "containers", "container", "serverless", "devsecops",
    "siem", "soar", "edr", "xdr", "mdr", "iam", "pam", "dlp", "casb", "sase", "ztna", "cspm", "cnapp",
    "zero-trust", "zero trust", "oauth", "saml", "oidc", "kerberos", "pki", "hsm", "kms", "vault",
    "machine learning", "deep learning", "threat hunting", "red team", "red teaming", "purple team",
    "penetration testing", "pentest", "pentesting", "malware", "reverse engineering", "forensics",
    "blockchain", "smart contract", "smart contracts", "crypto", "cryptography", "quantum",
    "gdpr", "hipaa", "pci", "pci-dss", "sox", "soc2", "iso27001", "fedramp", "dora", "nis2",
    "azure", "gcp", "kafka", "golang", "rust", "java", "javascript", "typescript", "c++",
}
# Hyphen suffixes that don't change a claim ("Splunk-based"); never credentials.
HYPHEN_SUFFIXES = {"based", "driven", "native", "wide", "facing", "level", "grade", "scale", "time",
                   "class", "led", "owned", "first", "aware", "centric", "focused", "enabled", "powered"}
# Common resume/domain words absent from the 1934 system dictionary.
BUNDLED_WORDS = """
cybersecurity security cyber escalation escalations automation automated automating detection detections
governance compliance remediation onboarding offboarding stakeholder stakeholders roadmap roadmaps
operationalized operationalised spearheaded architected orchestrated streamlined championed mentored
mentoring upskilled benchmarked productionized hardened scaled partnered owned delivered drove driving
promoted recruited represented reduced redesigned rebuilt rearchitected coached briefed negotiated
authored co-authored chaired hired hiring managed leading led built building building designed
implemented deployed migrated consolidated standardized standardised modernized modernised secured
defended protected monitored triaged investigated responded contained recovered audited assessed
evaluated prioritized prioritised sequenced launched established founded co-founded presented
translated converted correlated analyzed analysed reported informed advised supported enabled
end-to-end cross-functional hands-on follow-the-sun first-line second-line third-line in-house
real-time near-real-time data-driven risk-based
""".split()


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
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[–—‑−]", "-", text)
    text = re.sub(r"[   ​‌‍⁠﻿]", " ", text)
    return text.lower()


def has(term: str, text: str) -> bool:
    """Whole-word (alphanumeric-boundary) match of an already-normalised term."""
    term = term.strip()
    if not term:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def numbers(text: str) -> set[float]:
    text = normalize(text)
    found: set[float] = set()
    for m in _NUM_RE.finditer(text):
        value = float(m.group(1).replace(",", ""))
        found.add(value * _MULT.get((m.group(2) or "").lower(), 1))
    for m in _ORDINAL_RE.finditer(text):
        found.add(float(m.group(1)))
    for m in _WORD_RE.finditer(text):
        found.add(float(NUMBER_WORDS[m.group(1).lower()]))
    return found


def _contains_number(pool: set[float], value: float) -> bool:
    return any(abs(p - value) <= 1e-9 * max(1.0, abs(value)) for p in pool)


@lru_cache(maxsize=1)
def _dictionary() -> frozenset[str]:
    words = set(BUNDLED_WORDS)
    path = Path("/usr/share/dict/words")
    if path.exists():
        words.update(w for w in path.read_text(errors="ignore").split() if w[:1].islower())
    return frozenset(words)


def is_common_word(word: str) -> bool:
    """An ordinary English word (not a product/company/proper noun)."""
    w = word.lower().strip("'")
    if not w.replace("-", "").isalpha():
        return False
    parts = w.split("-") if "-" in w else [w]
    return all(_common(p) for p in parts if p)


def _common(w: str) -> bool:
    d = _dictionary()
    if w in d:
        return True
    for suffix, repl in (("ied", "y"), ("ies", "y"), ("ing", ""), ("ing", "e"), ("ed", ""), ("ed", "e"),
                         ("d", ""), ("es", ""), ("s", ""), ("ly", ""), ("ment", ""), ("ation", "ate")):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3 and (w[: -len(suffix)] + repl) in d:
            return True
    if len(w) > 6 and w.endswith("ed") and len(w) >= 5 and w[-3] == w[-4] and w[:-3] in d:  # "planned"
        return True
    return False


def entity_terms(text: str) -> list[tuple[str, bool]]:
    """(term, clause_initial) for capitalised, acronym or alphanumeric tokens."""
    tokens = text.split()
    terms = []
    for i, raw in enumerate(tokens):
        prev = tokens[i - 1] if i else ""
        clause_initial = i == 0 or bool(_CLAUSE_END.search(prev)) or prev in _DASHES or prev.endswith(("(", "\""))
        tok = raw.strip("()[]{},.;:!?\"'“”‘’")
        tok = re.sub(r"(['’]s)$", "", tok)
        if not tok or tok in _DASHES:
            continue
        if not re.search(r"[A-Z]", tok) and not re.search(r"\d", tok):
            continue
        if not re.search(r"[A-Za-z]", tok):
            continue  # pure numbers are handled by the number check
        if _NUM_RE.fullmatch(tok.lower()) or _ORDINAL_RE.fullmatch(tok) or _MULTIPLIER_RE.fullmatch(tok):
            continue  # "3k", "3rd", "2x" are numbers
        terms.append((tok, clause_initial))
    return terms


def _non_latin_letters(text: str) -> list[str]:
    bad = []
    for ch in text:
        if ch.isalpha() and not (ch.isascii() or "À" <= ch <= "ɏ"):
            bad.append(ch)
    return bad


# --------------------------------------------------------------------------- evidence


def evidence_index(profile: MasterProfile) -> dict[str, str]:
    """Citable id → text. Role-bound evidence includes the role's locked fields so a
    bullet may name its own employer/title. Role headers themselves are not citable."""
    idx: dict[str, str] = {}
    for e in profile.summary_facts + profile.highlights:
        idx[e.id] = e.text
    for r in profile.roles:
        locked = f"{r.employer}, {r.location} — {r.title} ({r.dates})"
        if r.scope:
            idx[r.scope.id] = f"{r.scope.text}\n{locked}"
        for a in r.achievements:
            idx[a.id] = f"{a.text}\n{locked}"
        for s in r.sub_roles:
            idx[s.id] = f"{s.label} {s.text}\n{locked}"
    for i in profile.projects + profile.education + profile.extras:
        idx[i.id] = f"{i.label} {i.text}"
    return idx


def evidence_owner(profile: MasterProfile) -> dict[str, str]:
    """Evidence id → role id, for role-bound evidence."""
    owner: dict[str, str] = {}
    for r in profile.roles:
        if r.scope:
            owner[r.scope.id] = r.id
        for x in [*r.achievements, *r.sub_roles]:
            owner[x.id] = r.id
    return owner


class FactChecker:
    def __init__(self, profile: MasterProfile):
        self.profile = profile
        self.index = evidence_index(profile)
        self.owner = evidence_owner(profile)
        self.role_ids = {r.id for r in profile.roles}
        self.vocabulary = [normalize(v) for v in profile.vocabulary]
        self.synonyms = [[normalize(t) for t in group] for group in profile.synonyms]
        self.skill_items = [normalize(i) for g in profile.skills for i in g.items]
        self.skill_corpus = normalize("\n".join(
            [g.category for g in profile.skills] + [i for g in profile.skills for i in g.items]
            + [t for group in profile.synonyms for t in group] + list(profile.vocabulary)))

    # -- claims ------------------------------------------------------------------
    def check_claim(self, claim: Claim, where: str, report: Report, role: str | None = None) -> None:
        if not claim.text.strip():
            report.error(where, "empty text")
            return
        if not claim.sources:
            report.error(where, "no sources cited — every claim must cite profile evidence ids")
            return
        headers = [s for s in claim.sources if s in self.role_ids]
        if headers:
            report.error(where, f"role header id(s) {', '.join(headers)} can't be cited — cite the "
                                "achievement or scope ids that state the fact")
            return
        missing = [s for s in claim.sources if s not in self.index]
        if missing:
            report.error(where, f"unknown source id(s): {', '.join(missing)}")
            return
        if role:
            foreign = [s for s in claim.sources if self.owner.get(s) not in (None, role)]
            if foreign:
                report.error(where, f"cites evidence from another role ({', '.join(foreign)}) — a bullet "
                                    "may only use facts from its own role; remove that part of the claim")
                return
        bad = _non_latin_letters(claim.text)
        if bad:
            report.error(where, f"contains non-Latin letters ({''.join(sorted(set(bad)))}) — retype them")
            return

        corpus = normalize("\n".join(self.index[s] for s in claim.sources))
        pool = numbers(corpus)
        text = normalize(claim.text)

        for value in sorted(numbers(claim.text)):
            if not _contains_number(pool, value):
                shown = int(value) if value.is_integer() else value
                report.error(where, f"number {shown:,} not found in cited sources {claim.sources}")
        for m in [*MAGNITUDE_RE.finditer(text), *_MULTIPLIER_RE.finditer(text)]:
            if not has(m.group(0), corpus):
                report.error(where, f'"{m.group(0)}" is a magnitude/multiplier not stated in cited sources')

        stripped = self._strip_approved_phrases(claim.text, corpus)
        for term, initial in entity_terms(stripped):
            if self._term_supported(term, corpus):
                continue
            if initial and re.fullmatch(r"[A-Z][a-z]+(-[a-z]+)*", term) and is_common_word(term) \
                    and normalize(term) not in RISKY_WORDS:
                continue  # ordinary capitalised first word, e.g. "Built", "Cross-functional"
            report.error(where, f'term "{term}" not found in cited sources {claim.sources} — rephrase to '
                                "match the evidence, or remove it")

        stripped_n = normalize(stripped)
        for word in sorted(RISKY_WORDS):
            if has(word, stripped_n) and not self._word_supported(word, corpus):
                report.error(where, f'"{word}" is not stated in cited sources {claim.sources} — '
                                    "don't add scope, credentials or technologies")

    def _strip_approved_phrases(self, text: str, corpus: str) -> str:
        """Remove multi-word synonyms/vocabulary (e.g. "Web Application Firewall") whose
        meaning is supported, so they are not checked word by word."""
        phrases = [v for v in self.profile.vocabulary if " " in v]
        for group, raw in zip(self.synonyms, self.profile.synonyms):
            if any(has(alt, corpus) for alt in group):
                phrases += [m for m in raw if " " in m]
        for phrase in sorted(phrases, key=len, reverse=True):
            text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(phrase) + r"(?![A-Za-z0-9])", "approved", text,
                          flags=re.I)
        return text

    def _word_supported(self, n: str, corpus: str) -> bool:
        if has(n, corpus) or any(has(n, v) for v in self.vocabulary):
            return True
        return any(n in group and any(has(alt, corpus) for alt in group) for group in self.synonyms)

    def _term_supported(self, term: str, corpus: str) -> bool:
        for part in (p for p in term.split("/") if p):
            n = normalize(part)
            if self._word_supported(n, corpus):
                continue
            # "Splunk-based": every capitalised piece supported, every other piece a harmless suffix
            pieces = part.split("-")
            if len(pieces) > 1 and all(
                self._word_supported(normalize(x), corpus) if re.search(r"[A-Z0-9]", x)
                else x.lower() in HYPHEN_SUFFIXES
                for x in pieces if x
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
        tokens = [t for t in re.findall(r"[a-z0-9+#.$&]+(?:[-/][a-z0-9+#.$&]+)*", n) if t not in STOPWORDS]
        expanded = [{t} | {alt for g in self.synonyms if t in g for alt in g} for t in tokens]
        for skill in self.skill_items:
            if tokens and all(any(has(alt, skill) for alt in options) for options in expanded):
                if numbers(item) <= numbers(skill):
                    return
        report.error(where, f'skill "{item}" is not in the profile skills (or an approved synonym)')

    def check_label(self, label: str, where: str, report: Report) -> None:
        for term, _ in entity_terms(label):
            for part in re.split(r"[/&-]", term):
                if part and not has(normalize(part), self.skill_corpus) and not is_common_word(part):
                    report.error(where, f'group label term "{part}" is not in your skills vocabulary')
        for word in RISKY_WORDS:
            if has(word, normalize(label)) and not has(word, self.skill_corpus):
                report.error(where, f'group label term "{word}" is not in your skills vocabulary')

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
            self.check_label(comp.label, f"competencies[{i}].label", report)
            if not comp.items:
                report.error(f"competencies[{i}]", f'competency group "{comp.label}" is empty — remove it')
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
                self.check_claim(tr.scope, f"{where}.scope", report, role=tr.role)
            for j, b in enumerate(tr.bullets):
                self.check_claim(b, f"{where}.bullets[{j}]", report, role=tr.role)
            sub_ids = {s.id for s in role.sub_roles}
            for j, sr in enumerate(tr.sub_roles):
                if sr.id not in sub_ids:
                    report.error(f"{where}.sub_roles[{j}]", f"'{sr.id}' is not a sub-role of {tr.role}")
                elif sr.text:
                    self.check_claim(sr.text, f"{where}.sub_roles[{j}]", report, role=tr.role)
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
