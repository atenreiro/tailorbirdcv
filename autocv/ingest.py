"""Parse the base resume .docx into a draft MasterProfile + the TailoredResume that
reproduces it. Paragraphs are classified by the same direct formatting render.py
writes, so ingest → render round-trips.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.text.paragraph import Paragraph

from .render import SECTION_TITLES

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_SECTION_KEYS = {v: k for k, v in SECTION_TITLES.items()}


@dataclass
class Run:
    text: str
    bold: bool
    italic: bool
    color: str | None
    size: int | None
    font: str | None


@dataclass
class Para:
    runs: list[Run]
    text: str
    has_rule: bool
    has_tab_stop: bool
    links: dict[str, str]  # visible text → url

    @property
    def first(self) -> Run:
        return next((r for r in self.runs if r.text.strip()), self.runs[0])


def _runs(p: Paragraph) -> list[Run]:
    out = []
    for r in p._p.iter(f"{W}r"):
        rpr = r.find(f"{W}rPr")

        def val(tag, attr="val"):
            el = rpr.find(f"{W}{tag}") if rpr is not None else None
            return el.get(f"{W}{attr}") if el is not None else None

        has = lambda tag: rpr is not None and rpr.find(f"{W}{tag}") is not None  # noqa: E731
        text = "".join(t.text or "" if t.tag == f"{W}t" else "\t" for t in r if t.tag in (f"{W}t", f"{W}tab"))
        size = val("sz")
        out.append(Run(text, has("b"), has("i"), val("color"), int(size) if size else None, val("rFonts", "ascii")))
    return out


def _paras(path: Path) -> list[Para]:
    doc = Document(str(path))
    paras = []
    for p in doc.paragraphs:
        runs = _runs(p)
        text = "".join(r.text for r in runs)
        if not text.strip():
            continue
        ppr = p._p.pPr
        links = {h.text: h.url for h in p.hyperlinks}
        paras.append(Para(
            runs=runs,
            text=text,
            has_rule=ppr is not None and ppr.find(f"{W}pBdr") is not None,
            has_tab_stop=ppr is not None and ppr.find(f"{W}tabs") is not None,
            links=links,
        ))
    return paras


def _slug(text: str, words: int = 3) -> str:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(tokens[:words])


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=\.)\s+(?=[A-Z])", text) if s.strip()]


def _lead(p: Para) -> tuple[str, str]:
    """Split a bold-lead-in bullet into (label, remainder)."""
    runs = [r for r in p.runs if r.text]
    label_parts, rest_parts, seen_label = [], [], False
    for r in runs:
        if not seen_label and r.text.strip() in ("•", ""):
            continue
        if r.bold and not rest_parts:
            label_parts.append(r.text)
            seen_label = True
        else:
            rest_parts.append(r.text)
    return "".join(label_parts).strip(), "".join(rest_parts).strip()


def ingest(path: Path) -> tuple[dict, dict]:
    paras = _paras(path)
    profile: dict = {
        "contact": {}, "headlines": [], "summary_facts": [], "highlights": [], "skills": [],
        "roles": [], "projects": [], "education": [], "extras": [],
        "synonyms": [], "vocabulary": [],
    }
    base: dict = {
        "headline": None, "summary": None, "highlights": [], "competencies": [],
        "experience": [], "projects": [], "education": [], "extras": [],
    }

    section = None
    role = None
    trole = None
    for i, p in enumerate(paras):
        f = p.first
        is_bullet = p.text.lstrip().startswith("•")
        bullet_text = p.text.lstrip().lstrip("•").strip()

        if i == 0:
            profile["contact"]["name"] = p.text.strip()
            continue
        if i == 1:
            profile["headlines"].append({"id": "h.leader", "text": p.text.strip(), "tracks": ["manager", "hybrid"]})
            base["headline"] = "h.leader"
            continue
        if section is None and not p.has_rule:
            parts = [x.strip() for x in p.text.split("·")]
            contact = profile["contact"]
            contact["location"] = parts[0]
            contact["links"] = []
            for part in parts[1:]:
                if "@" in part:
                    contact["email"] = part
                elif re.match(r"^\+?[\d\s()-]+$", part):
                    contact["phone"] = part
                else:
                    contact["links"].append({"text": part, "url": p.links.get(part, f"https://{part}")})
            continue
        if p.has_rule and f.bold and p.text.strip() in _SECTION_KEYS:
            section = _SECTION_KEYS[p.text.strip()]
            continue

        if section == "summary":
            ids = []
            for n, sentence in enumerate(_split_sentences(p.text), 1):
                profile["summary_facts"].append({"id": f"summary.s{n}", "text": sentence})
                ids.append(f"summary.s{n}")
            base["summary"] = {"text": p.text.strip(), "sources": ids}

        elif section == "highlights" and is_bullet:
            hid = f"highlight.h{len(profile['highlights']) + 1}"
            profile["highlights"].append({"id": hid, "text": bullet_text})
            base["highlights"].append({"text": bullet_text, "sources": [hid]})

        elif section == "competencies" and is_bullet:
            label, rest = _lead(p)
            items = [x.strip() for x in rest.split("·") if x.strip()]
            profile["skills"].append({"category": label.rstrip(":").strip(), "items": items})
            base["competencies"].append({"label": label.rstrip(":").strip(), "items": items})

        elif section == "experience":
            if p.has_tab_stop:
                left, _, dates = p.text.partition("\t")
                employer, _, location = left.partition(", ")
                rid = _slug(employer, 2)
                role = {"id": rid, "employer": employer.strip(), "location": location.strip(),
                        "title": None, "dates": dates.strip(), "scope": None,
                        "achievements": [], "sub_roles": []}
                profile["roles"].append(role)
                trole = {"role": rid, "scope": None, "bullets": [], "sub_roles": []}
                base["experience"].append(trole)
            elif role is None:
                continue
            elif role["title"] is None and f.bold:
                role["title"] = p.text.strip()
            elif not is_bullet:
                sid = f"{role['id']}.scope"
                role["scope"] = {"id": sid, "text": p.text.strip(), "italic": f.italic}
                trole["scope"] = {"text": p.text.strip(), "sources": [sid]}
            elif any(r.bold for r in p.runs):
                label, rest = _lead(p)
                sid = f"{role['id']}.sub{len(role['sub_roles']) + 1}"
                role["sub_roles"].append({"id": sid, "label": label, "text": rest})
                trole["sub_roles"].append({"id": sid})
            else:
                aid = f"{role['id']}.a{len(role['achievements']) + 1}"
                role["achievements"].append({"id": aid, "text": bullet_text})
                trole["bullets"].append({"text": bullet_text, "sources": [aid]})

        elif section in ("projects", "education", "extras") and is_bullet:
            label, rest = _lead(p)
            prefix = {"projects": "project", "education": "edu", "extras": "extra"}[section]
            item = {"id": f"{prefix}.{_slug(label)}", "label": label, "text": rest}
            profile[section].append(item)
            base[section].append({"id": item["id"]} if section == "projects" else item["id"])

    return profile, base
