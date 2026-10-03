"""First-run import: any resume (.docx, .pdf, text) → a draft master profile.

The AI only *transcribes*: it sorts the resume's own sentences into the profile's sections, copying
the wording verbatim. AutoCV then assigns the evidence ids itself (the same scheme as `autocv ingest`)
and checks every extracted text against the original; anything not found word-for-word is flagged
for the user to check. Nothing is saved here: the user reviews the draft and saves it explicitly.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile

from .engine import Engine
from .ingest import _slug, _split_sentences

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 60_000
TEXT_SUFFIXES = (".txt", ".md", ".text", "")


class ImportError_(ValueError):
    """The file can't be read as a resume."""


# --------------------------------------------------------------------------- text extraction
def extract_text(filename: str, data: bytes) -> str:
    if len(data) > MAX_FILE_BYTES:
        raise ImportError_("That file is larger than 10 MB. Save it as a smaller .docx or PDF, or paste the text.")
    name = filename.lower()
    if name.endswith(".docx"):
        text = _docx_text(data)
    elif name.endswith(".pdf"):
        text = _pdf_text(data)
    elif name.endswith(".doc"):
        raise ImportError_("Old .doc files can't be read. Save it as .docx (or PDF) in your word processor first.")
    elif any(name.endswith(s) for s in TEXT_SUFFIXES if s) or "." not in name:
        text = data.decode("utf-8", errors="replace")
    else:
        raise ImportError_("Use a .docx, .pdf or .txt file, or paste the text.")
    text = text.strip()
    if len(text) < 80:
        raise ImportError_("Couldn't find much text in that file (a scanned PDF has none). Paste the text instead.")
    return text[:MAX_TEXT_CHARS]


def _docx_text(data: bytes) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    try:
        doc = Document(io.BytesIO(data))
    except (zipfile.BadZipFile, KeyError, ValueError) as e:
        raise ImportError_("That .docx file couldn't be opened.") from e
    lines: list[str] = []

    def walk(container):
        for child in container.iter_inner_content():
            if isinstance(child, Paragraph):
                lines.append(child.text)
            elif isinstance(child, Table):
                for row in child.rows:
                    for cell in row.cells:
                        walk(cell)
    walk(doc)
    for section in doc.sections:  # contact details often live in the header
        lines[:0] = [p.text for p in section.header.paragraphs if p.text.strip()]
    return "\n".join(lines)


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    except (PdfReadError, ValueError) as e:
        raise ImportError_("That PDF couldn't be read.") from e


# --------------------------------------------------------------------------- AI transcription
def _lead_items() -> dict:
    return {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                        "required": ["label", "text"],
                                        "properties": {"label": {"type": "string"}, "text": {"type": "string"}}}}


def import_schema() -> dict:
    s = {"type": "string"}
    strs = {"type": "array", "items": s}
    return {
        "type": "object", "additionalProperties": False,
        "required": ["contact", "headline", "summary", "highlights", "skills", "roles", "projects", "education",
                     "extras"],
        "properties": {
            "contact": {"type": "object", "additionalProperties": False,
                        "required": ["name", "location", "phone", "email", "links"],
                        "properties": {"name": s, "location": s, "phone": s, "email": s, "links": {
                            "type": "array", "items": {"type": "object", "additionalProperties": False,
                                                       "required": ["text", "url"],
                                                       "properties": {"text": s, "url": s}}}}},
            "headline": s, "summary": s, "highlights": strs,
            "skills": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                  "required": ["category", "items"],
                                                  "properties": {"category": s, "items": strs}}},
            "roles": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["employer", "location", "title", "dates", "scope", "achievements", "sub_roles"],
                "properties": {"employer": s, "location": s, "title": s, "dates": s, "scope": s,
                               "achievements": strs, "sub_roles": _lead_items()}}},
            "projects": _lead_items(), "education": _lead_items(), "extras": _lead_items(),
        },
    }


SYSTEM = """You transcribe resumes into a structured form for AutoCV. You never write, rephrase, summarise, \
translate, correct or add anything: every value is copied verbatim from the resume. Answer only with JSON \
matching the schema."""


def _prompt(text: str) -> str:
    return f"""TASK: import
Transcribe this resume into the schema. Copy text EXACTLY as written (same words, numbers and punctuation; \
only drop bullet symbols and line-wrapping). Leave out anything the resume doesn't contain (empty string or list).

- contact: name, location (city/country as written), phone, email, links (text as shown; url with https:// \
when the resume shows a bare domain).
- headline: the title line under the name, if any.
- summary: the summary/profile paragraph, if any.
- highlights: bullets of a "highlights"/"key achievements" section, if any.
- skills: each skills group as category + items (split lists on commas, "·", "|" or ";"). A list without a \
category gets category "Skills".
- roles: every job in resume order: employer, location, title, dates (as written), scope = a non-bullet \
description line under the title (else ""), achievements = its bullets, one per bullet. A bullet that starts \
with a bold-style label ("Label: text" or "Label — text") inside a role goes in sub_roles.
- projects / education / extras (awards, languages, certifications, publications, volunteering): \
label = the item's name or degree, text = the rest of the line (dates, institution, details).

RESUME:
{text}
"""


async def import_profile(engine: Engine, text: str) -> dict:
    """Ask the AI to transcribe, then assign ids and verify against the original text."""
    raw = await engine.complete(SYSTEM, _prompt(text), import_schema())
    profile = build_profile(raw)
    return {"profile": profile, "unverified": unverified(profile, text)}


# --------------------------------------------------------------------------- ids + verification
def _unique(stem: str, taken: set[str]) -> str:
    stem = stem or "item"
    out, n = stem, 2
    while out in taken:
        out, n = f"{stem}-{n}", n + 1
    taken.add(out)
    return out


def _clean(x) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip().lstrip("•·-*–— ").strip()


def build_profile(raw: dict) -> dict:
    """The AI's transcription → a MasterProfile dict with AutoCV's own ids."""
    taken: set[str] = set()
    c = raw.get("contact") or {}
    links = [{"text": _clean(lk.get("text")), "url": _clean(lk.get("url"))}
             for lk in c.get("links") or [] if _clean(lk.get("text")) and _clean(lk.get("url"))]
    contact = {"name": _clean(c.get("name")) or "Your Name", "location": _clean(c.get("location")), "links": links}
    if _clean(c.get("phone")):
        contact["phone"] = _clean(c["phone"])
    if _clean(c.get("email")):
        contact["email"] = _clean(c["email"])
    profile: dict = {"contact": contact, "headlines": [], "summary_facts": [], "highlights": [], "skills": [],
                     "roles": [], "projects": [], "education": [], "extras": []}
    # The headline line under the name; without one, the most recent job title (still the resume's own words).
    first_title = next((_clean(r.get("title")) for r in raw.get("roles") or [] if _clean(r.get("title"))), "")
    if headline := _clean(raw.get("headline")) or first_title:
        profile["headlines"].append({"id": _unique("h.main", taken), "text": headline,
                                     "tracks": ["manager", "ic", "hybrid"]})
    for sentence in _split_sentences(_clean(raw.get("summary"))):
        profile["summary_facts"].append({"id": _unique(f"summary.s{len(profile['summary_facts']) + 1}", taken),
                                         "text": sentence})
    for text in map(_clean, raw.get("highlights") or []):
        if text:
            profile["highlights"].append({"id": _unique(f"highlight.h{len(profile['highlights']) + 1}", taken),
                                          "text": text})
    for group in raw.get("skills") or []:
        items = [i for i in map(_clean, group.get("items") or []) if i]
        if items:
            profile["skills"].append({"category": _clean(group.get("category")) or "Skills", "items": items})
    for r in raw.get("roles") or []:
        employer = _clean(r.get("employer"))
        if not employer:
            continue
        rid = _unique(_slug(employer, 2) or "role", taken)
        role = {"id": rid, "employer": employer, "location": _clean(r.get("location")),
                "title": _clean(r.get("title")) or "—", "dates": _clean(r.get("dates")),
                "achievements": [], "sub_roles": []}
        if scope := _clean(r.get("scope")):
            role["scope"] = {"id": _unique(f"{rid}.scope", taken), "text": scope, "italic": True}
        for text in map(_clean, r.get("achievements") or []):
            if text:
                role["achievements"].append({"id": _unique(f"{rid}.a{len(role['achievements']) + 1}", taken),
                                             "text": text})
        for sub in r.get("sub_roles") or []:
            if _clean(sub.get("label")) or _clean(sub.get("text")):
                role["sub_roles"].append({"id": _unique(f"{rid}.sub{len(role['sub_roles']) + 1}", taken),
                                          "label": _clean(sub.get("label")), "text": _clean(sub.get("text"))})
        profile["roles"].append(role)
    for section, prefix in (("projects", "project"), ("education", "edu"), ("extras", "extra")):
        for item in raw.get(section) or []:
            label, text = _clean(item.get("label")), _clean(item.get("text"))
            if label or text:
                profile[section].append({"id": _unique(f"{prefix}.{_slug(label or text) or 'item'}", taken),
                                         "label": label, "text": text})
    return profile


_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−"} |
                        {c: "'" for c in "‘’‛′"} | {c: '"' for c in "“”‟″"})


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_DASHES).lower()
    return re.sub(r"[\s•·▪●◦*|]+", " ", text).strip()


def unverified(profile: dict, source: str) -> list[str]:
    """Paths of extracted texts that don't appear word-for-word in the original (for the user to check)."""
    hay = _norm(source)
    hay_nospace = hay.replace(" ", "")
    out = []

    def check(path: str, text: str) -> None:
        t = _norm(text)
        # PDFs often lose or add spaces at line wraps: also compare without any spaces.
        if t and t not in hay and t.replace(" ", "") not in hay_nospace:
            out.append(path)

    check("contact.name", profile["contact"]["name"])
    for i, h in enumerate(profile["headlines"]):
        check(f"headlines[{i}]", h["text"])
    for key in ("summary_facts", "highlights"):
        for i, e in enumerate(profile[key]):
            check(f"{key}[{i}]", e["text"])
    for g in profile["skills"]:
        for j, item in enumerate(g["items"]):
            check(f"skills.{g['category']}[{j}]", item)
    for r in profile["roles"]:
        for field in ("employer", "title", "dates"):
            if r[field] != "—":
                check(f"{r['id']}.{field}", r[field])
        if r.get("scope"):
            check(r["scope"]["id"], r["scope"]["text"])
        for a in r["achievements"]:
            check(a["id"], a["text"])
        for sub in r["sub_roles"]:
            for part in (sub["label"], sub["text"]):
                check(sub["id"], part)
    for key in ("projects", "education", "extras"):
        for item in profile[key]:
            for part in (item["label"], item["text"]):
                check(item["id"], part)
    return sorted(set(out), key=out.index)


def blank_profile(name: str, location: str, headline: str = "") -> dict:
    profile = {"contact": {"name": name.strip(), "location": location.strip(), "links": []}, "headlines": []}
    if headline.strip():
        profile["headlines"].append({"id": "h.main", "text": headline.strip(), "tracks": ["manager", "ic", "hybrid"]})
    return profile
