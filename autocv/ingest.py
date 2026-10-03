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


# --------------------------------------------------------------------------- re-ingest (--force)


def _items(profile: dict):
    """(container, item) for every citable item with an id and text."""
    for key in ("headlines", "summary_facts", "highlights", "projects", "education", "extras"):
        for item in profile.get(key) or []:
            yield key, item
    for role in profile.get("roles") or []:
        if role.get("scope"):
            yield f"{role['id']}/scope", role["scope"]
        for key in ("achievements", "sub_roles"):
            for item in role.get(key) or []:
                yield f"{role['id']}/{key}", item


def _content(item: dict) -> tuple:
    return item.get("label"), " ".join(str(item.get("text", "")).split())


def _fresh(gen: str, taken: set[str]) -> str:
    """A new id in the same family as `gen` (acme.a3 → acme.a4…, edu.bsc → edu.bsc-2…)."""
    m = re.match(r"^(.*?)(\d+)$", gen)
    stem, n = (m.group(1), int(m.group(2)) + 1) if m else (f"{gen}-", 2)
    while f"{stem}{n}" in taken:
        n += 1
    return f"{stem}{n}"


def _container_list(profile: dict, container: str) -> list | None:
    if "/" not in container:
        return profile.setdefault(container, [])
    role_id, _, key = container.partition("/")
    role = next((r for r in profile.get("roles") or [] if r["id"] == role_id), None)
    if role is None:
        return None
    if key == "scope":
        return None
    return role.setdefault(key, [])


def merge_reingest(old: dict, new: dict, base: dict) -> tuple[dict, dict]:
    """Merge a fresh ingest of the base resume into the existing (curated) profile.

    - An id keeps its meaning forever: an item whose text is unchanged keeps its old id
      (even if it moved), a changed or new item gets an id never used before, and ids of
      facts that changed or disappeared are retired (by save_profile).
    - Evidence that didn't come from the resume (interview / prep guide, in_base_resume:
      false), approved headlines, skills, synonyms and vocabulary are kept.
    Returns (profile, base_tailored) with the base layout pointing at the final ids."""
    old_roles = {r["id"]: r for r in old.get("roles") or []}
    for role in new.get("roles") or []:
        prev = old_roles.get(role["id"])
        if prev and prev.get("employer") != role.get("employer"):
            raise ValueError(f"role id {role['id']!r} now belongs to a different employer "
                             f"({prev.get('employer')!r} → {role.get('employer')!r}); edit the profile by hand")

    old_ids = {item["id"] for _, item in _items(old)} | set(old_roles)
    blocked = old_ids | set(old.get("retired_ids") or [])
    pools: dict[str, list[dict]] = {}
    for container, item in _items(old):
        pools.setdefault(container, []).append(item)

    used: set[str] = {r["id"] for r in new.get("roles") or []}
    rename: dict[str, str] = {}
    for container, item in _items(new):
        gen = item["id"]
        match = next((o for o in pools.get(container, []) if _content(o) == _content(item) and o["id"] not in used), None)
        if match:
            final = match["id"]
            for extra in ("tags", "note", "tracks"):  # curated details on an unchanged fact
                if extra in match:
                    item[extra] = match[extra]
        elif gen not in blocked and gen not in used:
            final = gen
        else:
            final = _fresh(gen, blocked | used)
        used.add(final)
        rename[gen] = final
        item["id"] = final

    # Keep what didn't come from the resume.
    for container, item in _items(old):
        if item["id"] in used:
            continue
        curated = container == "headlines" or item.get("source", "resume") != "resume" or \
            item.get("in_base_resume") is False
        if not curated:
            continue  # a resume fact that changed or disappeared: retired
        target = _container_list(new, container)
        if target is None:
            raise ValueError(f"{item['id']} ({item.get('source', 'resume')} evidence) can't be kept: its place "
                             f"({container}) no longer exists in the re-ingested resume")
        target.append(item)
        used.add(item["id"])

    groups = {g["category"]: g for g in new.setdefault("skills", [])}
    for g in old.get("skills") or []:
        if g["category"] in groups:
            groups[g["category"]]["items"] += [i for i in g["items"] if i not in groups[g["category"]]["items"]]
        else:
            new["skills"].append(dict(g))
    new["synonyms"] = [s for s in old.get("synonyms") or []] + \
        [s for s in new.get("synonyms") or [] if s not in (old.get("synonyms") or [])]
    new["vocabulary"] = list(dict.fromkeys([*(old.get("vocabulary") or []), *(new.get("vocabulary") or [])]))
    new["retired_ids"] = list(old.get("retired_ids") or [])
    return new, _remap_base(base, rename)


def _remap_base(base: dict, rename: dict[str, str]) -> dict:
    ids = lambda xs: [rename.get(x, x) for x in xs]  # noqa: E731

    def claim(c):
        if c:
            c["sources"] = ids(c.get("sources") or [])
        return c
    if base.get("headline"):
        base["headline"] = rename.get(base["headline"], base["headline"])
    claim(base.get("summary"))
    for c in base.get("highlights") or []:
        claim(c)
    for r in base.get("experience") or []:
        claim(r.get("scope"))
        for c in r.get("bullets") or []:
            claim(c)
        for s in r.get("sub_roles") or []:
            s["id"] = rename.get(s["id"], s["id"])
    for p in base.get("projects") or []:
        p["id"] = rename.get(p["id"], p["id"])
    for key in ("education", "extras"):
        base[key] = ids(base.get(key) or [])
    return base
