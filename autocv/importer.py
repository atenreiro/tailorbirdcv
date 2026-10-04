"""First-run import: any resume (.docx, .pdf, text) → a draft master profile.

The AI only *transcribes*: it sorts the resume's own sentences into the profile's sections, copying
the wording verbatim. AutoCV then assigns the evidence ids itself (the same scheme as `autocv ingest`)
and checks every extracted text against the original; anything not found word-for-word is flagged
for the user to check. Nothing is saved here: the user reviews the draft and saves it explicitly.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
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
    elif name.endswith(".pages"):
        raise ImportError_("Pages files can't be read directly. In Pages, choose File → Export To → Word (or PDF), "
                           "then upload that file.")
    elif name.endswith((".doc", ".rtf", ".rtfd", ".odt")):
        text = _converted_text(name, data)
    elif any(name.endswith(s) for s in TEXT_SUFFIXES if s) or "." not in name:
        text = _decode_text(data)
    else:
        raise ImportError_("Use a .docx, .pdf or .txt file, or paste the text.")
    text = text.strip()
    if len(text) < 80:
        raise ImportError_("Couldn't find much text in that file (a scanned PDF has none). Paste the text instead.")
    return text[:MAX_TEXT_CHARS]


def _decode_text(data: bytes) -> str:
    """A plain-text CV in whatever encoding its editor used: UTF-8 (with or without BOM), UTF-16 (Notepad's
    "Unicode"), or Windows-1252 ("ANSI"). Binary data is refused rather than sent to the AI as gibberish."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if b"\x00" in data[:4096]:
        raise ImportError_("That file isn't plain text. Upload a .docx, .pdf or .txt file, or paste the text.")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _converted_text(name: str, data: bytes) -> str:
    """.doc, .rtf and .odt through macOS's built-in `textutil` (other systems: ask for .docx or PDF)."""
    import shutil
    import subprocess
    import tempfile
    tool = shutil.which("textutil")
    if not tool:
        raise ImportError_(f"{Path(name).suffix} files can't be read here. Save your CV as .docx (or PDF) in your word "
                           "processor first.")
    with tempfile.TemporaryDirectory(prefix="autocv-cv-") as tmp:
        src = Path(tmp) / f"cv{Path(name).suffix}"
        src.write_bytes(data)
        try:
            out = subprocess.run([tool, "-convert", "txt", "-encoding", "UTF-8", "-stdout", str(src)],
                                 capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            out = None
    if not out or out.returncode != 0:
        raise ImportError_("That file couldn't be read. Save your CV as .docx (or PDF) first, then upload it.")
    return out.stdout.decode("utf-8", errors="replace")


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
    from pypdf.errors import PyPdfError
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    except (PyPdfError, ValueError, KeyError) as e:  # damaged, password-protected or AES-encrypted
        raise ImportError_("That PDF couldn't be read (is it password-protected?). Paste the text instead.") from e


def pdf_pages(filename: str, data: bytes) -> int | None:
    """Page count of an uploaded PDF (suggests the page limit); None for other files or on error."""
    if not filename.lower().endswith(".pdf"):
        return None
    from pypdf import PdfReader
    try:
        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:  # noqa: BLE001
        return None


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
                     "extras", "suggested_targets"],
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
            "suggested_targets": {"type": "object", "additionalProperties": False,
                                  "required": ["field", "seniority", "roles", "region", "spelling"],
                                  "properties": {"field": s, "seniority": s, "roles": s, "region": s,
                                                 "spelling": {"type": "string", "enum": ["US", "UK", ""]}}},
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

- suggested_targets (not part of the profile; a starting point the candidate will edit): field = their \
profession in a few words (e.g. "cybersecurity", "product design"), seniority (e.g. "senior", "mid-level", \
"executive"), roles = the kind of next roles this CV points to in one short phrase, region = where they're \
based or looking (city/country/region as the CV shows), spelling = "US" or "UK" from the CV's own spelling \
(e.g. "organization" vs "organisation"). Infer only from the CV; leave a value empty if unsure.

RESUME:
{text}
"""


async def import_profile(engine: Engine, text: str, used_ids: set[str] | None = None) -> dict:
    """Ask the AI to transcribe, then assign ids (never one an earlier profile used) and verify
    against the original text."""
    raw = await engine.complete(SYSTEM, _prompt(text), import_schema())
    profile = build_profile(raw, used_ids)
    return {"profile": profile, "unverified": unverified(profile, text),
            "suggested_targets": suggested_targets(raw.get("suggested_targets"))}


def suggested_targets(raw) -> dict:
    """The AI's guesses for Settings → Your targets, cleaned (steer emphasis only, never facts)."""
    raw = raw if isinstance(raw, dict) else {}
    out = {k: _clean(raw.get(k))[:limit] for k, limit in (("field", 80), ("seniority", 80), ("roles", 240),
                                                          ("region", 80))}
    out["spelling"] = raw.get("spelling") if raw.get("spelling") in ("US", "UK") else "US"
    if "cyber" in out["field"].lower() or "security" in out["field"].lower():
        out["pack"] = "cybersecurity"
    return out


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


def build_profile(raw: dict, used_ids: set[str] | None = None) -> dict:
    """The AI's transcription → a MasterProfile dict with AutoCV's own ids (avoiding `used_ids`)."""
    taken: set[str] = set(used_ids or ())
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


_DASHES = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"} |
                        {c: "'" for c in "\u2018\u2019\u201b\u2032"} | {c: '"' for c in "\u201c\u201d\u201f\u2033"})


def _tokens(text: str) -> list[str]:
    """Words, whole numbers ("1.2", "3,000") and the symbols that change a fact (% + # $ € £ ¥): "US$1.2M" never
    matches "US$12M", "C#" never matches "C++", "40%" never matches "40"."""
    return re.findall(r"\d+(?:[.,]\d+)*|[^\W\d_]+|\d+|[%+#$€£¥]",
                      unicodedata.normalize("NFKC", text or "").translate(_DASHES).lower())


class _Source:
    """The original resume text, for whole-word matching."""

    def __init__(self, text: str):
        tokens = _tokens(text)
        self.spaced = " " + " ".join(tokens) + " "
        self.joined = "".join(tokens)
        self.starts, self.ends, at = set(), set(), 0
        for t in tokens:  # where each word begins and ends in `joined`
            self.starts.add(at)
            at += len(t)
            self.ends.add(at)

    def has(self, text: str) -> bool:
        tokens = _tokens(text)
        if not tokens:
            return True
        if " " + " ".join(tokens) + " " in self.spaced:  # the same words, in order, as whole words
            return True
        joined = "".join(tokens)
        # PDFs split words at line ends ("detec- tion"): long items may also match without word breaks, but only
        # where the match starts and ends on word boundaries ("Head of Security" is not in "ahead of security").
        if len(joined) < 12:
            return False
        at = self.joined.find(joined)
        while at != -1:
            if at in self.starts and at + len(joined) in self.ends:
                return True
            at = self.joined.find(joined, at + 1)
        return False


def import_shape(profile: dict) -> dict:
    """A reviewed import as the server accepts it: no approved vocabulary, synonyms or retired ids (they widen
    what the fact-check accepts and only come from the profile editor later), and every evidence item marked
    as coming from the resume."""
    out = {k: v for k, v in profile.items() if k not in ("vocabulary", "synonyms", "retired_ids")}

    def clean(items):
        return [{k: v for k, v in i.items() if k not in ("source", "in_base_resume", "tags")}
                for i in items or [] if isinstance(i, dict)]
    for key in ("summary_facts", "highlights", "projects", "education", "extras"):
        if key in out:
            out[key] = clean(out[key])
    for r in out.get("roles") or []:
        if isinstance(r, dict):
            r["achievements"] = clean(r.get("achievements"))
            r["sub_roles"] = clean(r.get("sub_roles"))
            if isinstance(r.get("scope"), dict):
                r["scope"] = clean([r["scope"]])[0]
    return out


def _url_text(url: str) -> str:
    return re.sub(r"^(?:https?://)?(?:www\.)?|/+$", "", url.strip(), flags=re.I)


def checkable(profile: dict) -> list[tuple[str, str]]:
    """Every (path, text) the import produced, in resume order. Paths are what the review UI shows
    and what `confirmed` lists; evidence items use their id."""
    out: list[tuple[str, str]] = []
    c = profile.get("contact", {})
    for key in ("name", "location", "phone", "email"):
        if c.get(key):
            out.append((f"contact.{key}", c[key]))
    for i, link in enumerate(c.get("links") or []):
        out += [(f"contact.links[{i}].text", link["text"]), (f"contact.links[{i}].url", _url_text(link["url"]))]
    out += [(f"headlines[{i}]", h["text"]) for i, h in enumerate(profile.get("headlines") or [])]
    for key in ("summary_facts", "highlights"):
        out += [(e["id"], e["text"]) for e in profile.get(key) or []]
    for g, group in enumerate(profile.get("skills") or []):
        if group.get("category") != "Skills":  # the default for an unlabelled list
            out.append((f"skills[{g}].category", group["category"]))
        out += [(f"skills[{g}].items[{j}]", item) for j, item in enumerate(group.get("items") or [])]
    for r in profile.get("roles") or []:
        out += [(f"{r['id']}.{f}", r[f]) for f in ("employer", "location", "title", "dates") if r.get(f) and r[f] != "—"]
        if r.get("scope"):
            out.append((r["scope"]["id"], r["scope"]["text"]))
        out += [(a["id"], a["text"]) for a in r.get("achievements") or []]
        for sub in r.get("sub_roles") or []:
            out += [(sub["id"], part) for part in (sub["label"], sub["text"]) if part]
    for key in ("projects", "education", "extras"):
        for item in profile.get(key) or []:
            out += [(item["id"], part) for part in (item["label"], item["text"]) if part]
    return out


def _role_sections(profile: dict, source: str) -> dict[str, str]:
    """Each role's own part of the CV: from where its employer (next to its title) appears to where the next
    role's begins. A role whose heading can't be found isn't sectioned (it's checked against the whole file)."""
    words = _tokens(source)
    starts: list[tuple[int, str]] = []
    for r in profile.get("roles") or []:
        emp, title = _tokens(r.get("employer", "")), _tokens(r.get("title", ""))[:3]
        hits = [i for i in range(len(words)) if emp and words[i:i + len(emp)] == emp]
        near = [i for i in hits if title and any(words[j:j + len(title)] == title
                                                 for j in range(max(0, i - 40), min(len(words), i + 40)))]
        if near:
            pos = near[0]
            title_at = [j for j in range(max(0, pos - 40), pos) if words[j:j + len(title)] == title]
            starts.append((min([pos, *title_at]), r["id"]))  # some CVs put the title first
    starts.sort()
    sections: dict[str, str] = {}
    for k, (pos, rid) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(words)
        sections[rid] = " ".join(words[pos:end])
    return sections


def unverified(profile: dict, source: str) -> list[str]:
    """Paths whose text isn't in the original resume word-for-word (whole words, in order). A role's fields and
    bullets must be in that role's own part of the CV, so facts can't move between employers."""
    src = _Source(source)
    sections = {rid: _Source(text) for rid, text in _role_sections(profile, source).items()}
    owner: dict[str, str] = {}
    for r in profile.get("roles") or []:
        for f in ("employer", "location", "title", "dates"):
            owner[f"{r['id']}.{f}"] = r["id"]
        for item in [*([r["scope"]] if r.get("scope") else []), *(r.get("achievements") or []), *(r.get("sub_roles") or [])]:
            owner[item["id"]] = r["id"]
    out: list[str] = []
    for path, text in checkable(profile):
        where = sections.get(owner.get(path, ""), src)
        if not where.has(text) and path not in out:
            out.append(path)
    return out


CONFIRMED_NOTE = "confirmed by you at import (not word-for-word in the original file)"


def mark_confirmed(profile: dict, paths: set[str]) -> dict:
    """Record provenance on evidence the user confirmed although it didn't match the file."""
    def visit(items):
        for item in items or []:
            if item.get("id") in paths:
                item["note"] = CONFIRMED_NOTE
    visit(profile.get("summary_facts"))
    visit(profile.get("highlights"))
    for r in profile.get("roles") or []:
        visit([r["scope"]] if r.get("scope") else [])
        visit(r.get("achievements"))
        visit(r.get("sub_roles"))
    for key in ("projects", "education", "extras"):
        visit(profile.get(key))
    return profile


def blank_profile(name: str, location: str, headline: str = "") -> dict:
    profile = {"contact": {"name": name.strip(), "location": location.strip(), "links": []}, "headlines": []}
    if headline.strip():
        profile["headlines"].append({"id": "h.main", "text": headline.strip(), "tracks": ["manager", "ic", "hybrid"]})
    return profile
