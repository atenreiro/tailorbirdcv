"""Hide the user's contact details from the AI: redact every prompt, restore every answer.

Nothing the AI does needs them: the resume prints contact details from the profile (render.py), never from
an AI answer. So before any prompt leaves this computer (`PrivateEngine`, engine.py), the user's name, email,
phone, street address and personal links are replaced by placeholders like `[NAME]` and `[EMAIL]`, and so is
any other email address, phone number or personal-profile link in the text (a CV being imported, a gap
answer, a job description). The AI's answer gets the real values back (`Vault.restore`) before anything else
reads it, so the fact-check, the import's word-for-word check and the resume are unchanged.

City and country are not hidden (job descriptions and role locations need them), and neither is the career
history itself, which can still identify someone; Settings → Privacy says so.
"""

from __future__ import annotations

import re
import unicodedata
from contextvars import ContextVar
from dataclasses import dataclass, field

# Values typed before there's a profile (the setup wizard's name and address, for the CV import).
EXTRA: ContextVar[dict] = ContextVar("tailorbirdcv_privacy_extra", default={})

EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![\w-])")
# Phone numbers, strictly: international (+…) or grouped like a phone number (3+ groups, 8+ digits), so resume
# metrics ("US$1.7M", "20M+", "4,500", "2019 – 2022") are never mistaken for one.
PHONE = re.compile(r"(?<![\w+$£€.,])(?:\+\d{1,3}[\s.\-]?(?:\(\d{1,4}\)[\s.\-]?)?\d{2,4}(?:[\s.\-]?\d{2,4}){1,4}"
                   r"|\(\d{2,4}\)[\s.\-]?\d{3,4}[\s.\-]\d{3,4}"
                   r"|\d{3,4}[\s.\-]\d{3,4}[\s.\-]\d{3,4})(?![\w%])")
PROFILE_LINK = re.compile(r"(?<![\w/.-])(?:https?://)?(?:www\.)?(?:linkedin\.com/in|github\.com|gitlab\.com|"
                          r"x\.com|twitter\.com|medium\.com/@?)/?[A-Za-z0-9_.\-]+/?(?![\w/-])", re.I)

DOMAIN = re.compile(r"(?<![\w@/.-])(?:https?://)?(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?:/[^\s,;)]*)?", re.I)


def use(name: str = "", address: str = ""):
    """Hide these too during this request (e.g. the CV import, before the profile exists)."""
    return EXTRA.set({"name": name.strip(), "address": address.strip()})


def _fold(c: str) -> str:
    """One character, lower-cased and without accents (é → e), keeping one character for one."""
    base = "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x)).lower()
    if len(base) == 1:
        return base
    low = c.lower()
    return low if len(low) == 1 else c  # "İ".lower() is two characters: keep positions aligned


def _folded(text: str) -> str:
    return "".join(_fold(c) for c in text)


def _words_pattern(text: str) -> str:
    """A whole-word, accent/case-insensitive pattern (applied to folded text) for a phrase."""
    words = [re.escape(_folded(w)) for w in text.split()]
    return r"(?<![\w])" + r"[\s ]+".join(words) + r"(?![\w])"


def _digits_pattern(phone: str) -> str | None:
    """A known phone number in any spacing or punctuation: +65 9123 4567, 91234567, (65) 9123-4567…"""
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 6:
        return None
    sep = r"[\s().\- ]*"
    full = sep.join(digits)
    local = sep.join(digits[-8:]) if len(digits) > 8 else None  # without the country code
    body = f"(?:\\+?{full}" + (f"|{local}" if local else "") + ")"
    return r"(?<![\w+])" + body + r"(?!\d)"


def _link_pattern(value: str) -> str | None:
    core = re.sub(r"^(?:https?://)?(?:www\.)?", "", value.strip(), flags=re.I).rstrip("/")
    if len(core) < 4 or "." not in core:
        return None
    return r"(?<![\w/.-])(?:https?://)?(?:www\.)?" + re.escape(_folded(core)) + r"/?(?![\w/-])"


@dataclass
class Vault:
    """Real value ↔ placeholder, for one AI call."""
    known: list[tuple[str, str]] = field(default_factory=list)   # (pattern on folded text, kind)
    tokens: dict[str, str] = field(default_factory=dict)          # placeholder → real value
    name_parts: set[str] = field(default_factory=set)             # a web address with one of these is personal
    _by_value: dict[str, str] = field(default_factory=dict)
    _counts: dict[str, int] = field(default_factory=dict)

    def _token(self, kind: str, value: str) -> str:
        key = _folded(value)
        if key in self._by_value:
            return self._by_value[key]
        n = self._counts.get(kind, 0) + 1
        self._counts[kind] = n
        token = f"[{kind}]" if n == 1 else f"[{kind} {n}]"
        self._by_value[key] = token
        self.tokens[token] = value
        return token

    def redact(self, text: str) -> str:
        if not text:
            return text
        spans: list[tuple[int, int, str]] = []
        folded = _folded(text)
        for pattern, kind in self.known:
            spans += [(m.start(), m.end(), kind) for m in re.finditer(pattern, folded)]
        for regex, kind in ((EMAIL, "EMAIL"), (PROFILE_LINK, "LINK"), (PHONE, "PHONE")):
            spans += [(m.start(), m.end(), kind) for m in regex.finditer(text)]
        if self.name_parts:  # a personal website (janedoe.design, jane-doe.dev/blog)
            spans += [(m.start(), m.end(), "LINK") for m in DOMAIN.finditer(text)
                      if any(part in re.sub(r"[^a-z]", "", _folded(m.group(0))) for part in self.name_parts)]
        out, at = [], 0
        for start, end, kind in sorted(spans, key=lambda s: (s[0], -(s[1] - s[0]))):
            if start < at:
                continue  # inside a longer match already replaced
            value = text[start:end]
            if kind == "PHONE" and sum(c.isdigit() for c in value) < 8:
                continue
            out += [text[at:start], self._token(kind, value)]
            at = end
        return "".join(out) + text[at:]

    def restore(self, value):
        """Put the real values back in an AI answer (strings, lists, dicts)."""
        if isinstance(value, str):
            if "[" not in value:
                return value
            for token in sorted(self.tokens, key=len, reverse=True):  # "[LINK 12]" before "[LINK 1]"
                value = value.replace(token, self.tokens[token])
            return value
        if isinstance(value, list):
            return [self.restore(v) for v in value]
        if isinstance(value, dict):
            return {k: self.restore(v) for k, v in value.items()}
        return value


def vault_for(contact: dict | None, address: str = "", extra: dict | None = None) -> Vault:
    """The values to hide: the profile's contact details, the saved street address, and `extra` (EXTRA)."""
    from .factcheck import is_common_word
    contact, extra = contact or {}, extra or {}
    v = Vault()
    names = [n for n in (contact.get("name"), extra.get("name")) if n]
    for name in names:  # the full name first, then the distinctive parts on their own
        v.known.append((_words_pattern(name), "NAME"))
    for name in names:
        for part in name.replace("-", " ").split():
            if len(part) >= 3 and not is_common_word(part):
                v.known.append((_words_pattern(part), "NAME"))
            if len(part) >= 4:
                v.name_parts.add(re.sub(r"[^a-z]", "", _folded(part)))
    for addr in {a.strip() for a in (address, extra.get("address", "")) if a and a.strip()}:
        v.known.append((_words_pattern(addr), "ADDRESS"))
    if contact.get("email"):
        v.known.append((re.escape(_folded(contact["email"])), "EMAIL"))
    if contact.get("phone") and (p := _digits_pattern(contact["phone"])):
        v.known.append((p, "PHONE"))
    for link in contact.get("links") or []:
        for value in (link.get("url"), link.get("text")):
            if value and (p := _link_pattern(value)):
                v.known.append((p, "LINK"))
    return v
