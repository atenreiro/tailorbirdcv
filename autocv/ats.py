"""JD keyword coverage. Keywords come from analysis.yaml (written by /tailor):

    keywords:
      - {term: detection engineering, priority: must, aliases: [detection logic]}
      - {term: Kubernetes, priority: nice}

Each keyword is classed as:
  in_resume   — appears in the rendered tailored resume
  unused      — not in the resume, but the profile has evidence (consider surfacing it)
  gap         — nowhere in the profile; never add it without new confirmed evidence
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .factcheck import normalize, evidence_index
from .schema import MasterProfile


@dataclass
class KeywordResult:
    term: str
    priority: str
    status: str  # in_resume | unused | gap


@dataclass
class AtsReport:
    results: list[KeywordResult] = field(default_factory=list)
    words: int = 0

    def coverage(self, priority: str) -> tuple[int, int]:
        rows = [r for r in self.results if r.priority == priority]
        return sum(r.status == "in_resume" for r in rows), len(rows)

    def lines(self) -> list[str]:
        out = []
        for prio in ("must", "nice"):
            hit, total = self.coverage(prio)
            if total:
                out.append(f"{prio}-have keywords in resume: {hit}/{total} ({100 * hit // total}%)")
        for status, title in (("unused", "evidence exists but not used"), ("gap", "real gaps (no evidence)")):
            terms = [f"{r.term} [{r.priority}]" for r in self.results if r.status == status]
            if terms:
                out.append(f"{title}: " + ", ".join(terms))
        out.append(f"word count: {self.words}")
        return out


def _present(term: str, text: str) -> bool:
    n = normalize(term).strip()
    if not n:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", text) is not None


def analyze(keywords: list[dict], resume_lines: list[str], profile: MasterProfile) -> AtsReport:
    resume = normalize("\n".join(resume_lines))
    profile_text = normalize("\n".join(
        list(evidence_index(profile).values())
        + [i for g in profile.skills for i in g.items]
        + profile.vocabulary
    ))
    report = AtsReport(words=len(" ".join(resume_lines).split()))
    for kw in keywords:
        names = [kw["term"], *kw.get("aliases", [])]
        if any(_present(n, resume) for n in names):
            status = "in_resume"
        elif any(_present(n, profile_text) for n in names):
            status = "unused"
        else:
            status = "gap"
        report.results.append(KeywordResult(kw["term"], kw.get("priority", "nice"), status))
    return report
