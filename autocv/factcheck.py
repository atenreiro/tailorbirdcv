"""Blocking fact-check: every free-text claim in a TailoredResume must be traceable to
the MasterProfile evidence it cites.

Checks (errors block the build):
  * structure — referenced headline/role/project/education/extra ids exist and belong
    where they are used; every claim cites at least one existing evidence id; role
    headers are not citable. Who may cite what:
      - summary / highlights: any citable evidence (they summarise the whole career)
      - a role's scope and bullets: only that role's own scope/achievements/sub-roles
        (not another role's, and not summary/highlight/project/education/extra ids)
      - a sub-role's text: only that sub-role's own id
      - a project's text: only that project's own id
  * characters — no invisible/format/control characters (soft hyphen, zero-width,
    bidi controls… they would survive into the .docx), no non-Latin letters, and no
    unusual symbols or accented letters (e.g. Roman numeral "Ⅿ") unless the cited
    evidence contains that exact character. Dash variants are read as "-".
  * numbers — every number in a claim (incl. "six", "eighty-six", "a million", "half",
    "third", "US$1.7M", "65%", "3x", "3rd") and every magnitude word ("hundreds",
    "tens of", "doubled", "tenfold") appears in its cited sources
  * entities — every capitalised (any script-Latin uppercase, e.g. "Ørsted") / acronym /
    alphanumeric term (e.g. "Kubernetes", "SOC 2", "AWS", "24x7") appears in its cited
    sources (whole-word match), an approved synonym, or the profile vocabulary. A
    capitalised word starting a clause passes only if it is an ordinary dictionary word
    or appears in the sources ("Built" ok, "Microsoft" not)
  * unknown words — any lowercase word that is not an ordinary English word (product
    and tool names such as "splunk", "okta", "aws") must appear in the cited sources
    (plural/possessive forms allowed), the profile vocabulary or an approved synonym
  * risky words — technologies that are also dictionary words ("python", "oracle"),
    credentials and scope/inflation words ("certified", "global", "single-handedly"…)
    must appear in the cited sources
  * competencies — every listed skill is a profile skill, an approved synonym, or a
    whole-word sub-phrase of one profile skill; group labels only use skills vocabulary,
    words found in the profile, or generic category words, and no numbers/magnitudes the
    skills don't state

Limitations (covered by Claude's self-review + the candidate's read-through): ordinary
lowercase rewording is not verified semantically, and the units/meaning attached to a
number ("six a month" vs "six a week") are not compared. The unknown-word check needs
the system word list (/usr/share/dict/words, standard on macOS); without it the check
is skipped and the report carries a warning.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .schema import Claim, MasterProfile, TailoredResume

# --------------------------------------------------------------------------- number words

_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9}
_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_ORD_UNITS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
              "eighth": 8, "ninth": 9}
_ORD_TEENS = {"tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
              "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19}
_ORD_TENS = {"twentieth": 20, "thirtieth": 30, "fortieth": 40, "fiftieth": 50, "sixtieth": 60,
             "seventieth": 70, "eightieth": 80, "ninetieth": 90}
_HUNDRED = {"hundred", "hundredth"}
_SCALES = {"thousand": 1e3, "thousandth": 1e3, "million": 1e6, "millionth": 1e6, "billion": 1e9,
           "billionth": 1e9, "trillion": 1e12}
_DENOMS = {"halves": 2, "thirds": 3, "quarters": 4, "fourths": 4, "fifths": 5, "sixths": 6,
           "sevenths": 7, "eighths": 8, "ninths": 9, "tenths": 10}
_UNIT_LIKE = {**_UNITS, **_ORD_UNITS}
_TEEN_LIKE = {**_TEENS, **_ORD_TEENS}
_TENS_LIKE = {**_TENS, **_ORD_TENS}
_CORE = {**_UNIT_LIKE, **_TEEN_LIKE, **_TENS_LIKE}
_ORDINALS = {**_ORD_UNITS, **_ORD_TEENS, **_ORD_TENS}
_NUMBER_TOKENS = set(_CORE) | _HUNDRED | set(_SCALES) | set(_DENOMS) | {"dozen", "half", "quarter"}
# Kept for callers that import it: every single word that denotes a number.
NUMBER_WORDS = {**_CORE, "hundred": 100, "thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000,
                "dozen": 12}

# Phrases where a number word isn't a count ("first line of defense", "per second").
_NUMBER_IDIOMS = re.compile(
    r"\b(?:first|second|third)[ -]line\b|\b(?:first|second)[ -]half\b|\bper second\b|\bsplit[ -]second\b"
    r"|\bfirst[ -]hand\b|\bat first\b|\bsecond[ -]hand\b|\beleventh[ -]hour\b")

# Vague magnitudes / multipliers: allowed only if the same word is in the sources.
MAGNITUDE_RE = re.compile(
    r"\b(tens|dozens|hundreds|thousands|millions|billions|twice|double[ds]?|doubling|triple[ds]?|tripling|"
    r"quadruple[ds]?|quadrupling|halved|halving|\w+fold|multiple-fold)\b", re.I)
_MULT = {"k": 1e3, "m": 1e6, "million": 1e6, "mn": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9,
         "thousand": 1e3, "hundred": 1e2, "dozen": 12, "trillion": 1e12, "tn": 1e12}
# possessive quantifiers: "1.5x" must not backtrack into a bare "1"
_NUM_RE = re.compile(r"(?<![\w.])(\d[\d,]*+(?:\.\d++)?)\s?(k|mn|m|bn|b|tn|million|billion|trillion|thousand|"
                     r"hundred|dozen)?(?![a-z0-9])", re.I)
_ORDINAL_RE = re.compile(r"(?<![\w.])(\d+)(?:st|nd|rd|th)\b", re.I)
_MULTIPLIER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?x\b", re.I)
_CLAUSE_END = re.compile(r"[.;:!?]$")
_DASHES = {"—", "–", "-", "|", "·"}
STOPWORDS = {"&", "and", "of", "the", "for", "a", "an", "in", "on", "to", "with", "-", "/", "at", "or", "by"}

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
    # products / languages that are also dictionary words
    "python", "ruby", "swift", "spark", "chef", "puppet", "snowflake", "oracle", "tableau", "confluence",
    "sentinel", "falcon", "consul", "cisco", "juniper", "cortex", "apache", "flask", "scala", "cobalt",
    "git", "wiz", "arbor", "sap", "burp", "ai",
}
# Company/product names that are also dictionary words: never accepted as an "ordinary
# capitalised first word" or as a generic group-label word (lowercase use is fine).
BRAND_WORDS = {"apple", "amazon", "visa", "shell", "meta", "alphabet", "stripe", "ripple", "windows", "outlook",
               "office", "citadel", "jump", "virtu", "optiver", "oracle", "sentinel", "defender", "prisma"}
# Abbreviations that are ordinary prose.
_ABBREVIATIONS = {"e.g", "i.e", "eg", "ie", "etc", "vs", "approx", "incl", "cf", "yoy", "qoq", "p.a"}
# Hyphen suffixes that don't change a claim ("Splunk-based"); never credentials.
HYPHEN_SUFFIXES = {"based", "driven", "native", "wide", "facing", "level", "grade", "scale", "time",
                   "class", "led", "owned", "first", "aware", "centric", "focused", "enabled", "powered"}
# Prefixes that combine with an ordinary word ("re-architected", "multi-cloud").
_PREFIXES = ("re", "un", "non", "pre", "post", "co", "multi", "cross", "sub", "de", "over", "under", "out",
             "self", "inter", "intra", "anti", "cyber", "mis", "semi", "counter")
# Prefixes also accepted when written solid ("rearchitected", "unmanaged"); kept short because
# brand names are often prefix + word ("Overwatch", "CyberArk").
_JOINED_PREFIXES = ("re", "un", "non", "pre", "mis")
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
email emails online offline website websites internet intranet database databases workflow workflows
endpoint endpoints phishing ransomware botnet botnets runbook runbooks playbook playbooks rollout rollouts
app apps cyberattack cyberattacks cybercrime cybercriminals datacenter datacenters uptime downtime
fintech fintechs telco telcos telecom telecoms upskilling reskilling outsourcing outsourced insourced
headcount toolchain toolchains toolset toolsets tooling codebase frontend backend microservice microservices
timeline timelines workstream workstreams patching alerting triaging onboarded offboarded programme
programmes realtime anomalies baseline baselines benchmark benchmarks benchmarking hacker hackers hacking
scammer scammers vulnerabilities pentesters bot bots proactive proactively prioritization prioritisation
operationalize operationalise operationalizing optimized optimised optimization optimisation optimizing
leveraged leveraging stakeholder's escalated mentored managing manages incidents rearchitecting
observability resilience scalability scalable workload workloads takedown takedowns exfiltration
misconfiguration misconfigurations hardening logging telemetry dashboard dashboards analytics metrics
upskill tradeoff tradeoffs trade-off trade-offs walkthrough walkthroughs onsite offsite nearshore offshore
onshore inbound outbound shortlisted shortlist stakeholdered deduplicated deduplication enrichment
geo geolocation multi non pre post cross sub de self anti counter fraudsters ecosystem ecosystems
mindset skillset skillsets know-how setup setups signup login logins logon password passwords passwordless
username usernames hostname hostnames whitelist whitelists allowlist allowlists blocklist blocklists
denylist denylists sandbox sandboxing sandboxed spoofing spoofed typosquatting typosquat lookalike
lookalikes impersonation takeover takeovers jailbreak jailbreaking chatbot chatbots
broadband chargeback chargebacks colocation cybercriminal cybercriminals hacktivist hacktivists kanban
runtime runtimes lifecycle lifecycles tabletop tabletops coordinate coordinated coordinating coordination
has does was were been being became begun began bent bound bred brought built bought caught chose chosen
came dealt dug did done drew drawn drove driven fell fallen fed felt fought found fled flew flown forgot
forgotten froze frozen got gotten gave given went gone grew grown hung had heard hid hidden held kept knew
known laid led left lent lost made meant met paid proved proven quit read rode ran rang rose risen said saw
seen sought sold sent shook shaken shone shot showed shown shrank shut sang sank sat slept slid spoke spoken
sped spent spun spread sprang stood stole stolen stuck struck strove swore swept swung took taken taught tore
torn told thought threw thrown understood undertook undertaken upheld upset woke wore worn won withdrew
withdrawn withheld wrote written oversaw overseen overtook outgrew rebuilt rewrote rewritten reran
keyword keywords pixel pixels demo demos info max min plugin plugins config configs blog blogs podcast
podcasts webinar webinars smartphone smartphones laptop laptops startup startups scaleup scaleups
""".split()

# Generic words a competency group label may use even if the profile doesn't.
LABEL_WORDS = set("""
security cyber cybersecurity information data cloud network networks infrastructure application applications
platform platforms tool tools tooling technology technologies engineering operations leadership management
governance risk risks compliance regulatory strategy strategic architecture detection response incident
incidents threat threats intelligence identity access privacy resilience continuity assurance audit controls
control frameworks framework standards programs program programmes programme delivery people team teams
talent stakeholder stakeholders vendor vendors budget communication core key technical business domain
expertise skills competencies capabilities practices methods languages programming automation analytics
monitoring testing offensive defensive product products digital transformation modernization other
additional general emerging edge perimeter operational policy policies secure software development
endpoint endpoints systems services service enterprise investigations forensics engagement executive
advisory consulting oversight planning design research reporting training awareness
""".split())

# Typographic characters always allowed in claim text (dashes/quotes are canonicalised).
_ALLOWED_SYMBOLS = set(
    " ¢£¥§©®°±·«»×"
    "‐‑‒–—―‘’‚‛“”„‟"
    "•…′″™←↑→↓−≈≤≥ "
    "€₹₩₫₦₱₽₺﹘﹣－"
) | {chr(c) for c in range(0x2000, 0x200B)}
_DASH_RE = re.compile("[‐‑‒–—―−﹘﹣－]")


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


def canon(text: str) -> str:
    """NFKC + every dash variant → "-", curly quotes → straight, "×" → "x"; case kept."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = _DASH_RE.sub("-", text).replace("×", "x")
    text = re.sub(r"[  -‍ ⁠﻿]", " ", text)
    return text


def normalize(text: str) -> str:
    return canon(text).lower()


def has(term: str, text: str) -> bool:
    """Whole-word (letter/digit-boundary) match of an already-normalised term."""
    term = term.strip()
    if not term:
        return False
    return re.search(r"(?<![^\W_])" + re.escape(term) + r"(?![^\W_])", text) is not None


def _number_word_values(text: str) -> list[float]:
    """Values of spelled-out numbers in normalised text: "eighty-six" → 86, "a million" → 1e6,
    "half a dozen" → 6, "two-thirds" → 0.667, "third" → 3. A lone "one" is not counted
    ("one of the…", "in one year")."""
    text = _NUMBER_IDIOMS.sub(" ", text)
    toks = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[a-z]+", text)]
    joinable = lambda a, b: re.fullmatch(r"\s*-?\s*", text[toks[a][2]:toks[b][1]]) is not None  # noqa: E731
    out: list[float] = []
    i = 0
    while i < len(toks):
        run = _number_run(toks, i, joinable)
        if not run:
            i += 1
            continue
        words = [toks[k][0] for k in run]
        start, end = toks[run[0]][1], toks[run[-1]][2]
        i = run[-1] + 1
        before, after = text[:start], text[end:]
        followed_by_of = re.match(r"\s+of\b", after) is not None
        if words[0] in _HUNDRED | set(_SCALES) | {"dozen"} and re.search(r"\d\s*$", before):
            continue  # "3 thousand" is read by _NUM_RE
        if words == ["one"]:
            continue
        if words == ["first"] and re.search(r"[a-z]-$", before):
            continue  # "cloud-first"
        if words[-1] in ("quarter", "quarters") and not followed_by_of:
            continue  # "each quarter", "two quarters" are periods of time
        if len(words) == 2 and words[1] in _ORDINALS and (words[0] == "one" or followed_by_of):
            out.append(1 / _ORDINALS[words[1]])  # "a third of", "one-fifth"
            continue
        out.append(_evaluate(words))
    return out


def _number_run(toks, i, joinable) -> list[int]:
    """Indices of the number-word phrase starting at token i (empty if none)."""
    def word(k):
        return toks[k][0] if k < len(toks) else ""

    def article_ok(k):  # "a"/"an" counts only before a scale/fraction word
        return word(k) in ("a", "an") and k + 1 < len(toks) and joinable(k, k + 1) and \
            word(k + 1) in _HUNDRED | set(_SCALES) | set(_ORDINALS) | {"dozen", "half", "quarter"}

    if not (word(i) in _NUMBER_TOKENS or article_ok(i)):
        return []
    run = [i]
    while True:
        k = run[-1] + 1
        if k >= len(toks) or not joinable(run[-1], k):
            break
        p, n = word(run[-1]), word(k)
        if n == "and":
            nxt = word(k + 1)
            if k + 1 < len(toks) and joinable(k, k + 1) and (
                    (p in _HUNDRED | set(_SCALES) and nxt in _CORE)
                    or (p in _CORE and nxt in ("a", "an") and word(k + 2) == "half")):
                run.append(k)
                continue
            break
        if n in ("a", "an"):
            if p in ("and", "half") and article_ok(k):
                run.append(k)
                continue
            break
        if n in _ORDINALS and p in ("a", "an", "one") and len(run) == 1:
            ok = n not in ("first", "second")  # "a third", "one-fifth"
        elif n in _UNIT_LIKE:
            ok = p in _TENS or p in _HUNDRED | set(_SCALES) | {"and"}
        elif n in _TEEN_LIKE or n in _TENS_LIKE:
            ok = p in _HUNDRED | set(_SCALES) | {"and"}
        elif n in _HUNDRED:
            ok = p in _UNITS or p in _TEENS or p in _TENS or p in ("a", "an")
        elif n in _SCALES:
            ok = p in _UNITS or p in _TEENS or p in _TENS or p in _HUNDRED | {"a", "an", "half", "dozen"}
        elif n == "dozen":
            ok = p in _UNITS or p in _TEENS or p in _TENS or p in ("a", "an", "half")
        elif n == "half":
            ok = p in ("a", "an")
        elif n in _DENOMS or n == "quarter":
            ok = p in _UNITS or p in _TEENS or p in _TENS or p in ("a", "an")
        else:
            ok = False
        if not ok:
            break
        run.append(k)
    # an article that isn't followed by anything numeric is not a number
    if word(run[-1]) in ("a", "an", "and"):
        run = run[:-1]
    return run


def _evaluate(words: list[str]) -> float:
    total, cur = 0.0, 0.0
    for w in words:
        if w in ("a", "an", "and"):
            continue
        if w in _CORE:
            cur += _CORE[w]
        elif w == "half":
            cur += 0.5
        elif w in _HUNDRED:
            cur = (cur or 1) * 100
        elif w == "dozen":
            cur = (cur or 1) * 12
        elif w in _SCALES:
            total += (cur or 1) * _SCALES[w]
            cur = 0.0
        elif w in _DENOMS:
            cur = (cur or 1) / _DENOMS[w]
        elif w == "quarter":
            cur = (cur or 1) / 4
    return total + cur


def numbers(text: str) -> set[float]:
    text = normalize(text)
    found: set[float] = set()
    for m in _NUM_RE.finditer(text):
        value = float(m.group(1).replace(",", ""))
        found.add(value * _MULT.get((m.group(2) or "").lower(), 1))
    for m in _ORDINAL_RE.finditer(text):
        found.add(float(m.group(1)))
    found.update(_number_word_values(text))
    if re.search(r"\b(halved|halving|halve)\b", text):
        found.add(0.5)  # "halved" supports "cut by half"
    return found


def _contains_number(pool: set[float], value: float) -> bool:
    return any(abs(p - value) <= 1e-9 * max(1.0, abs(value)) for p in pool)


def _shown(value: float) -> str:
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:.3g}"


@lru_cache(maxsize=1)
def _system_words() -> frozenset[str]:
    path = Path("/usr/share/dict/words")
    if not path.exists():
        return frozenset()
    return frozenset(w for w in path.read_text(errors="ignore").split() if w[:1].islower())


@lru_cache(maxsize=1)
def _dictionary() -> frozenset[str]:
    return frozenset(set(BUNDLED_WORDS) | _system_words())


def is_common_word(word: str) -> bool:
    """An ordinary English word (not a product/company/proper noun)."""
    w = word.lower().strip("'")
    if not w.replace("-", "").isalpha() or not w.replace("-", "").isascii():
        return False
    if w in _dictionary():
        return True
    parts = w.split("-") if "-" in w else [w]
    return all(_common(p) or (p in _PREFIXES and i < len(parts) - 1) for i, p in enumerate(parts) if p)


_SUFFIXES = (("ied", "y"), ("ies", "y"), ("ier", "y"), ("iest", "y"), ("ily", "y"), ("ing", ""), ("ing", "e"),
             ("ed", ""), ("ed", "e"), ("d", ""), ("es", ""), ("s", ""), ("ly", ""), ("ment", ""),
             ("ments", ""), ("ation", "ate"), ("ations", "ate"), ("ation", "e"), ("ation", ""), ("er", ""),
             ("er", "e"), ("est", ""), ("est", "e"), ("ers", ""), ("ers", "e"), ("ness", ""), ("ity", ""), ("ability", "able"),
             ("ize", ""), ("ized", ""), ("izing", ""), ("ization", ""), ("izations", ""), ("ise", ""),
             ("ised", ""), ("al", ""), ("ally", ""), ("ive", "e"), ("ively", "e"), ("able", ""),
             ("able", "e"), ("ful", ""), ("less", ""))


def _common(w: str) -> bool:
    d = _dictionary()
    if w in d:
        return True
    for suffix, repl in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= (2 if repl else 3):
            stem = w[: -len(suffix)]
            if stem + repl in d:
                return True
            # doubled consonant: "planned", "cutting", "scrapped"
            if suffix in ("ed", "ing", "er", "ers") and len(stem) >= 4 and stem[-1] == stem[-2] and stem[:-1] in d:
                return True
    for prefix in _JOINED_PREFIXES:
        if w.startswith(prefix) and len(w) - len(prefix) >= 4 and _common_no_prefix(w[len(prefix):]):
            return True
    return False


def _common_no_prefix(w: str) -> bool:
    d = _dictionary()
    if w in d:
        return True
    for suffix, repl in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            stem = w[: -len(suffix)]
            if stem + repl in d or (suffix in ("ed", "ing") and len(stem) >= 4 and stem[-1] == stem[-2]
                                    and stem[:-1] in d):
                return True
    return False


def _has_upper(tok: str) -> bool:
    return any(c.isupper() for c in tok)


def entity_terms(text: str) -> list[tuple[str, bool]]:
    """(term, clause_initial) for capitalised, acronym or alphanumeric tokens."""
    tokens = canon(text).split()
    terms = []
    for i, raw in enumerate(tokens):
        prev = tokens[i - 1] if i else ""
        clause_initial = i == 0 or bool(_CLAUSE_END.search(prev)) or prev in _DASHES or prev.endswith(("(", "\""))
        tok = raw.strip("()[]{},.;:!?\"'“”‘’")
        tok = re.sub(r"('s)$", "", tok)
        if not tok or tok in _DASHES:
            continue
        if not _has_upper(tok) and not re.search(r"\d", tok):
            continue
        if not any(c.isalpha() for c in tok):
            continue  # pure numbers are handled by the number check
        if _NUM_RE.fullmatch(tok.lower()) or _ORDINAL_RE.fullmatch(tok) or _MULTIPLIER_RE.fullmatch(tok):
            continue  # "3k", "3rd", "2x" are numbers
        terms.append((tok, clause_initial))
    return terms


def _is_capitalized_word(term: str) -> bool:
    """"Built", "Cross-functional" — one capital letter, then lowercase letters."""
    parts = term.split("-")
    first, rest = parts[0], parts[1:]
    return (len(first) >= 1 and first.isalpha() and first[0].isupper() and (first[1:] == "" or first[1:].islower())
            and all(p.isalpha() and p.islower() for p in rest))


def lowercase_words(text: str) -> list[str]:
    """Lowercase word tokens (no capitals, no digits) of canonical text, possessives/contractions
    removed; hyphenated words are kept whole."""
    out = []
    for raw in canon(text).split():
        tok = raw.strip("()[]{},.;:!?\"'*")
        tok = re.sub(r"('s|s'|n't|'re|'ve|'ll|'d|'m)$", "", tok)
        if not tok or _has_upper(tok) or re.search(r"\d", tok):
            continue
        for part in tok.split("/"):
            part = part.strip("-'")
            if part and any(c.isalpha() for c in part):
                out.append(part)
    return out


def _non_latin_letters(text: str) -> list[str]:
    bad = []
    for ch in text:
        if ch.isalpha() and not (ch.isascii() or "À" <= ch <= "ɏ"):
            bad.append(ch)
    return bad


def _char_name(ch: str) -> str:
    return f"U+{ord(ch):04X} {unicodedata.name(ch, 'unnamed')}"


def character_problems(text: str, allowed_text: str) -> list[str]:
    """Messages for characters that must not appear in resume text: invisible/format/control
    characters (always), non-Latin letters (always), and any other non-ASCII character that
    isn't common typography unless `allowed_text` (the cited evidence) contains it."""
    text = unicodedata.normalize("NFC", text)
    allowed = set(unicodedata.normalize("NFC", allowed_text))
    problems: list[str] = []
    invisible = sorted({ch for ch in text if unicodedata.category(ch) in ("Cf", "Co", "Cs", "Cn")
                        or (unicodedata.category(ch) == "Cc" and ch not in "\t\n\r")})
    if invisible:
        problems.append("contains invisible/control character(s) " + ", ".join(_char_name(c) for c in invisible)
                        + " — retype the text without them")
    bad = _non_latin_letters(text)
    if bad:
        problems.append(f"contains non-Latin letters ({''.join(sorted(set(bad)))}) — retype them")
    odd = sorted({ch for ch in text if not ch.isascii() and ch not in _ALLOWED_SYMBOLS and ch not in allowed
                  and ch not in invisible and ch not in bad})
    if odd:
        problems.append("contains unusual character(s) " + ", ".join(f"'{c}' ({_char_name(c)})" for c in odd)
                        + " not found in the cited sources — use plain letters, digits and punctuation")
    return problems


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
        self.skill_raw = "\n".join(
            [g.category for g in profile.skills] + [i for g in profile.skills for i in g.items]
            + [t for group in profile.synonyms for t in group] + list(profile.vocabulary))
        self.skill_corpus = normalize(self.skill_raw)
        self.vocab_raw = "\n".join([t for group in profile.synonyms for t in group] + list(profile.vocabulary))
        self.profile_corpus = normalize("\n".join(
            [*self.index.values(), self.skill_raw, *(h.text for h in profile.headlines)]))
        self.dictionary_available = bool(_system_words())

    # -- claims ------------------------------------------------------------------
    def check_claim(self, claim: Claim, where: str, report: Report, role: str | None = None,
                    allowed: set[str] | None = None) -> None:
        """Check one claim. `role`: a role's scope/bullet — may cite only that role's
        evidence. `allowed`: explicit set of citable ids (a sub-role's or project's own
        id). Neither: summary/highlights — any citable evidence."""
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
            foreign = [s for s in claim.sources if self.owner.get(s) != role]
            if foreign:
                report.error(where, f"cites evidence from another role or section ({', '.join(foreign)}) — a "
                                    f"bullet may only use facts from its own role ({role}); remove that part "
                                    "of the claim")
                return
        if allowed is not None:
            foreign = [s for s in claim.sources if s not in allowed]
            if foreign:
                report.error(where, f"cites evidence from another entry ({', '.join(foreign)}) — this line may "
                                    f"only cite {', '.join(sorted(allowed))}")
                return

        raw_sources = "\n".join(self.index[s] for s in claim.sources)
        problems = character_problems(claim.text, raw_sources + "\n" + self.vocab_raw)
        for msg in problems:
            report.error(where, msg)
        if problems:
            return

        corpus = normalize(raw_sources)
        pool = numbers(corpus)
        text = normalize(claim.text)

        for value in sorted(numbers(claim.text)):
            if not _contains_number(pool, value):
                report.error(where, f"number {_shown(value)} not found in cited sources {claim.sources}")
        for m in [*MAGNITUDE_RE.finditer(text), *_MULTIPLIER_RE.finditer(text)]:
            if not has(m.group(0), corpus):
                report.error(where, f'"{m.group(0)}" is a magnitude/multiplier not stated in cited sources')

        stripped = self._strip_approved_phrases(canon(claim.text), corpus)
        for term, initial in entity_terms(stripped):
            if self._term_supported(term, corpus):
                continue
            if initial and _is_capitalized_word(term) and is_common_word(term) \
                    and normalize(term) not in RISKY_WORDS | BRAND_WORDS:
                continue  # ordinary capitalised first word, e.g. "Built", "Cross-functional"
            report.error(where, f'term "{term}" not found in cited sources {claim.sources} — rephrase to '
                                "match the evidence, or remove it")

        stripped_n = normalize(stripped)
        for word in sorted(RISKY_WORDS):
            if has(word, stripped_n) and not self._word_supported(word, corpus):
                report.error(where, f'"{word}" is not stated in cited sources {claim.sources} — '
                                    "don't add scope, credentials or technologies")

        if self.dictionary_available:
            flagged: list[str] = []
            for word in lowercase_words(stripped):
                if word in flagged or self._lower_word_ok(word, corpus):
                    continue
                flagged.append(word)
                report.error(where, f'"{word}" is not an ordinary English word and isn\'t in cited sources '
                                    f"{claim.sources} — tools, products and names must come from the evidence")
        elif not any(w.message.startswith("system dictionary") for w in report.warnings):
            report.warn("factcheck", "system dictionary (/usr/share/dict/words) not found — lowercase "
                                     "tool/product names were not checked")

    def _lower_word_ok(self, word: str, corpus: str) -> bool:
        if word in STOPWORDS or word in RISKY_WORDS or word in _ABBREVIATIONS:
            return True  # risky words have their own check
        if self._supported_variant(word, corpus):
            return True
        if is_common_word(word):
            return True
        pieces = [p for p in word.split("-") if p]
        if len(pieces) > 1 and all(
                p in STOPWORDS or p in HYPHEN_SUFFIXES or self._supported_variant(p, corpus) or is_common_word(p)
                or (p in _PREFIXES and i < len(pieces) - 1) for i, p in enumerate(pieces)):
            return True
        return False

    def _supported_variant(self, word: str, corpus: str) -> bool:
        variants = {word, word + "s", word + "es"}
        for suffix in ("es", "s"):
            if word.endswith(suffix) and len(word) > len(suffix) + 1:
                variants.add(word[: -len(suffix)])
        return any(self._word_supported(v, corpus) for v in variants)

    def _strip_approved_phrases(self, text: str, corpus: str) -> str:
        """Remove multi-word synonyms/vocabulary (e.g. "Web Application Firewall") whose
        meaning is supported, so they are not checked word by word."""
        phrases = [canon(v) for v in self.profile.vocabulary if " " in v]
        for group, raw in zip(self.synonyms, self.profile.synonyms):
            if any(has(alt, corpus) for alt in group):
                phrases += [canon(m) for m in raw if " " in m]
        for phrase in sorted(phrases, key=len, reverse=True):
            text = re.sub(r"(?<![^\W_])" + re.escape(phrase) + r"(?![^\W_])", "approved", text, flags=re.I)
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
                self._word_supported(normalize(x), corpus) if (_has_upper(x) or re.search(r"\d", x))
                else x.lower() in HYPHEN_SUFFIXES
                for x in pieces if x
            ):
                continue
            return False
        return True

    # -- competencies --------------------------------------------------------------
    def check_skill(self, item: str, where: str, report: Report) -> None:
        problems = character_problems(item, self.skill_raw)
        if problems:
            for msg in problems:
                report.error(where, f'skill "{item}" {msg}')
            return
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
        """Group labels are free text, so they get the claim checks against the skills
        vocabulary: characters, numbers/magnitudes, and every word must be in the skills
        vocabulary, somewhere in the profile, or a generic category word."""
        problems = character_problems(label, self.skill_raw)
        for msg in problems:
            report.error(where, f"group label {msg}")
        if problems:
            return
        n = normalize(label)
        pool = numbers(self.skill_corpus)
        for value in sorted(numbers(label)):
            if not _contains_number(pool, value):
                report.error(where, f"group label number {_shown(value)} is not in your skills")
        for m in [*MAGNITUDE_RE.finditer(n), *_MULTIPLIER_RE.finditer(n)]:
            if not has(m.group(0), self.skill_corpus):
                report.error(where, f'group label magnitude "{m.group(0)}" is not in your skills')
        flagged: set[str] = set()
        for tok in re.findall(r"[^\W_]+(?:'[^\W_]+)?", canon(label)):
            w = re.sub(r"'s$", "", tok).lower()
            if w in flagged or w in STOPWORDS or w.isdigit() or _NUM_RE.fullmatch(w):
                continue
            if self._label_word_ok(w):
                continue
            flagged.add(w)
            shown = tok if _has_upper(tok) or not any(c.isalpha() for c in tok) else w
            report.error(where, f'group label term "{shown}" is not in your skills vocabulary')
        for word in RISKY_WORDS:
            if has(word, n) and not has(word, self.skill_corpus) and word not in flagged:
                report.error(where, f'group label term "{word}" is not in your skills vocabulary')

    def _label_word_ok(self, w: str) -> bool:
        variants = {w, w + "s", w.removesuffix("s"), w.removesuffix("es")} - {""}
        if any(has(v, self.skill_corpus) for v in variants):
            return True
        if w in RISKY_WORDS or w in BRAND_WORDS:
            return False
        if any(v in LABEL_WORDS for v in variants):
            return True
        return is_common_word(w) and any(has(v, self.profile_corpus) for v in variants)

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
                    self.check_claim(sr.text, f"{where}.sub_roles[{j}]", report, role=tr.role, allowed={sr.id})
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
                    self.check_claim(entry.text, f"{key}[{j}]", report, allowed={entry.id})

        return report


def check(profile: MasterProfile, tailored: TailoredResume) -> Report:
    return FactChecker(profile).check(tailored)
