"""Which application a PDF came from. Nothing is ever added to the PDF: a file is matched against the
copies AutoCV froze when you applied (and the current builds) by

1. its SHA-256: the exact file, byte for byte;
2. the PDF's own document ids: Word's XMP `xmpMM:DocumentID` and the trailer `/ID`, new on every export
   and kept by many tools that re-save a PDF;
3. its text, for copies whose file changed completely: the closest match, never proof.
"""

from __future__ import annotations

import difflib
import hashlib
import io
import logging
import re

log = logging.getLogger(__name__)

TEXT_MIN = 0.7     # below this, two resumes aren't "the same text" (different tailorings of one profile score ~0.6)
TEXT_SHOWN = 3     # closest text matches listed when nothing matches exactly


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reader(data: bytes):
    from pypdf import PdfReader
    return PdfReader(io.BytesIO(data))


def pdf_ids(data: bytes) -> dict:
    """The ids a PDF carries itself (None when it has none or can't be read)."""
    document_id = pdf_id = None
    try:
        reader = _reader(data)
        try:
            xmp = reader.xmp_metadata
            raw = xmp.xmpmm_document_id if xmp else None
            if raw:
                document_id = str(raw).strip().lower().removeprefix("uuid:") or None
        except Exception:  # noqa: BLE001 — malformed XMP: no document id
            pass
        ids = reader.trailer.get("/ID")
        if ids:
            first = ids[0].get_object()
            raw = getattr(first, "original_bytes", None) or bytes(str(first), "latin-1")
            pdf_id = raw.hex() or None
    except Exception as e:  # noqa: BLE001 — not a readable PDF
        log.debug("AutoCV: no PDF ids (%s)", e)
    return {"document_id": document_id, "pdf_id": pdf_id}


def fingerprint(data: bytes) -> dict:
    return {"sha256": sha256(data), **pdf_ids(data)}


def words(data: bytes) -> list[str]:
    try:
        text = " ".join(page.extract_text() or "" for page in _reader(data).pages[:10])
    except Exception:  # noqa: BLE001
        return []
    return re.findall(r"\w+", text.lower())


def similarity(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if m.real_quick_ratio() < TEXT_MIN or m.quick_ratio() < TEXT_MIN:
        return 0.0
    return m.ratio()


def match(data: bytes, candidates: list[dict]) -> dict:
    """`candidates`: {"read": () -> bytes, "fingerprint": dict | None, ...anything to return}.
    Exact and same-document matches when there are any; otherwise the closest texts."""
    mine = fingerprint(data)
    found, unread = [], []
    for c in candidates:
        try:
            theirs = c.get("fingerprint") or fingerprint(c["read"]())
        except OSError as e:
            log.warning("AutoCV: can't read %s (%s)", c.get("file"), e)
            continue
        info = {k: v for k, v in c.items() if k not in ("read", "fingerprint")}
        if theirs.get("sha256") == mine["sha256"]:
            found.append({**info, "match": "exact", "score": 1.0})
        elif any(mine[k] and theirs.get(k) == mine[k] for k in ("document_id", "pdf_id")):
            found.append({**info, "match": "document", "score": 1.0})
        else:
            unread.append((c, info))
    if not found:
        text = words(data)
        scored = []
        for c, info in unread:
            try:
                score = similarity(text, words(c["read"]()))
            except OSError:
                continue
            if score >= TEXT_MIN:
                scored.append({**info, "match": "text", "score": round(score, 3)})
        found = sorted(scored, key=lambda m: -m["score"])[:TEXT_SHOWN]
    order = {"exact": 0, "document": 1, "text": 2}
    found.sort(key=lambda m: (order[m["match"]], -m["score"], m.get("kind") != "sent", m.get("created") or ""))
    return {**mine, "matches": found}
