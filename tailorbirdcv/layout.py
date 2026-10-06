"""Where a rendered resume's text falls on the page, computed from the .docx itself (no Word needed).

Every paragraph the renderer writes is measured the way Word lays it out: its runs are wrapped word by word
with the real character widths of the fonts (Calibri and Georgia through their metric-compatible stand-ins
Carlito and Gelasio, bundled in data/fonts), at their own size, inside the paragraph's indent; then its
spacing before/after, line height (single spacing: the font's ascent + descent) and bottom rule are added.
Paragraphs never split across pages (the renderer sets keepLines) and headings stay with what follows them
(keepNext), so pages are filled the same way Word fills them.

The result predicts the PDF's page count and how full each page is, to within a few percent; `fit.py`
learns what is left per design from real builds. Lengths are expressed in body lines (the body text's line
height), the unit of the AI's length budget.
"""

from __future__ import annotations

import re
import struct
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lxml import etree

from . import paths
from .themes import PAPER, Theme

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
STAND_INS = {"Calibri": "Carlito", "Georgia": "Gelasio"}  # metric-compatible, bundled
# Single line height (em) of the real fonts (their Windows ascent + descent). The stand-ins match the
# character widths, not always the line height: Gelasio's is 1.66 em against Georgia's 1.136.
LINE = {"Calibri": 2500 / 2048, "Georgia": 2327 / 2048}
_SAMPLE = ("Led a team of eight engineers running payment services for 20M customers, cutting p95 latency "
           "from 900 ms to 180 ms and saving US$1.2M a year across three regions.")


@dataclass(frozen=True)
class _Font:
    upm: int
    advances: tuple[int, ...]   # per glyph id
    cmap: dict[int, int]        # code point → glyph id
    line: float                 # single line height, in em (Windows ascent + descent)

    def width(self, text: str, size: float) -> float:
        """Width of `text` in points at `size` points."""
        last = len(self.advances) - 1
        units = sum(self.advances[min(self.cmap.get(ord(c), 0), last)] for c in text)
        return units * size / self.upm


def _tables(data: bytes) -> dict[str, bytes]:
    count = struct.unpack(">H", data[4:6])[0]
    out = {}
    for i in range(count):
        tag, _, offset, length = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        out[tag.decode("latin-1")] = data[offset:offset + length]
    return out


def _cmap(table: bytes) -> dict[int, int]:
    """Unicode code points → glyph ids, from a format 12 or format 4 subtable."""
    records = struct.unpack(">H", table[2:4])[0]
    subtables = {}
    for i in range(records):
        platform, encoding, offset = struct.unpack(">HHI", table[4 + 8 * i:12 + 8 * i])
        subtables[(platform, encoding)] = offset
    for key in ((3, 10), (0, 4), (3, 1), (0, 3)):
        if key not in subtables:
            continue
        sub = table[subtables[key]:]
        fmt = struct.unpack(">H", sub[:2])[0]
        mapping: dict[int, int] = {}
        if fmt == 12:
            groups = struct.unpack(">I", sub[12:16])[0]
            for g in range(groups):
                start, end, glyph = struct.unpack(">III", sub[16 + 12 * g:28 + 12 * g])
                for code in range(start, min(end, 0x2FFFF) + 1):
                    mapping[code] = glyph + code - start
            return mapping
        if fmt == 4:
            seg2 = struct.unpack(">H", sub[6:8])[0]
            n = seg2 // 2
            ends = struct.unpack(f">{n}H", sub[14:14 + seg2])
            starts = struct.unpack(f">{n}H", sub[16 + seg2:16 + 2 * seg2])
            deltas = struct.unpack(f">{n}h", sub[16 + 2 * seg2:16 + 3 * seg2])
            ro_at = 16 + 3 * seg2
            ranges = struct.unpack(f">{n}H", sub[ro_at:ro_at + seg2])
            for i in range(n):
                for code in range(starts[i], ends[i] + 1):
                    if code == 0xFFFF:
                        continue
                    if ranges[i] == 0:
                        glyph = (code + deltas[i]) & 0xFFFF
                    else:
                        at = ro_at + 2 * i + ranges[i] + 2 * (code - starts[i])
                        glyph = struct.unpack(">H", sub[at:at + 2])[0]
                        glyph = (glyph + deltas[i]) & 0xFFFF if glyph else 0
                    mapping[code] = glyph
            return mapping
    return {}


@lru_cache(maxsize=None)
def font(family: str, bold: bool = False, italic: bool = False) -> _Font:
    """Metrics of a theme font (any other family is measured as Calibri)."""
    style = {(False, False): "Regular", (True, False): "Bold", (False, True): "Italic", (True, True): "BoldItalic"}
    name = STAND_INS.get(family, "Carlito")
    data = (paths.DATA / "fonts" / f"{name}-{style[(bold, italic)]}.ttf").read_bytes()
    t = _tables(data)
    upm = struct.unpack(">H", t["head"][18:20])[0]
    metrics = struct.unpack(">H", t["hhea"][34:36])[0]
    advances = list(struct.unpack(f">{2 * metrics}H", t["hmtx"][:4 * metrics])[::2])
    glyphs = struct.unpack(">H", t["maxp"][4:6])[0]
    advances += [advances[-1]] * (glyphs - metrics)
    ascent, descent = struct.unpack(">HH", t["OS/2"][74:78])
    return _Font(upm, tuple(advances), _cmap(t["cmap"]), LINE.get(family, (ascent + descent) / upm))


# ---- the page --------------------------------------------------------------------------------------------
def usable(theme: Theme, paper: str | None) -> tuple[float, float]:
    """Text width and height inside the margins, in points."""
    width, height = PAPER[paper or theme.paper]
    top, right, bottom, left = theme.margins
    return (width - left - right) / 20, (height - top - bottom) / 20


def body_line(theme: Theme) -> float:
    """Height of one line of body text, in points: the unit of the length budget."""
    return theme.body_size / 2 * font(theme.body_font).line


def lines_per_page(theme: Theme, paper: str | None) -> float:
    return usable(theme, paper)[1] / body_line(theme)


def line_chars(theme: Theme, paper: str | None) -> int:
    """Characters of typical body text that fit on one line."""
    per_char = font(theme.body_font).width(_SAMPLE, theme.body_size / 2) / len(_SAMPLE)
    return round(usable(theme, paper)[0] / per_char)


# ---- paragraphs --------------------------------------------------------------------------------------------
@dataclass
class _Para:
    before: float      # space above (pt)
    body: float        # its lines, plus a bottom rule (pt)
    after: float       # space below (pt)
    keep_next: bool    # stays on the same page as the next paragraph


def _twips(el, attr: str) -> float:
    value = el.get(W + attr) if el is not None else None
    return int(value) / 20 if value and value.lstrip("-").isdigit() else 0.0


def _runs(p) -> list[tuple[str, _Font, float]]:
    """(text, font, size in points) for each run, in order; a tab is the text "\t"."""
    out = []
    for r in p.iter(W + "r"):
        rpr = r.find(W + "rPr")
        family, size, bold, italic = "Calibri", 12.0, False, False
        if rpr is not None:
            fonts = rpr.find(W + "rFonts")
            family = fonts.get(W + "ascii", family) if fonts is not None else family
            sz = rpr.find(W + "sz")
            size = int(sz.get(W + "val")) / 2 if sz is not None else size
            bold, italic = rpr.find(W + "b") is not None, rpr.find(W + "i") is not None
        f = font(family, bold, italic)
        for child in r:
            if child.tag == W + "t" and child.text:
                out.append((child.text, f, size))
            elif child.tag == W + "tab":
                out.append(("\t", f, size))
    return out


def _lines(runs: list[tuple[str, _Font, float]], first: float, rest: float) -> int:
    """Lines needed, wrapping word by word: `first` points wide for the first line, `rest` after."""
    lines, used, room = 1, 0.0, first
    for text, f, size in runs:
        if text == "\t":
            used += 12  # a right-aligned tab (company line): at least a small gap before the dates
            continue
        for word in re.findall(r"[^ ]+ *| +", text):  # lines break at spaces only (not at no-break spaces)
            ink = f.width(word.rstrip(), size)
            if used and used + ink > room:
                lines, used, room = lines + 1, 0.0, rest
                if not word.strip():
                    continue
            used += f.width(word, size)
            while used > room:  # one word longer than the line (a long URL)
                lines, used, room = lines + 1, used - room, rest
    return lines


def paragraphs(docx: Path, theme: Theme, paper: str | None) -> list[_Para]:
    body = etree.fromstring(zipfile.ZipFile(docx).read("word/document.xml")).find(W + "body")
    width = usable(theme, paper)[0]
    items = [p for p in body if p.tag == W + "p"]
    borders = [etree.tostring(p.find(f"{W}pPr/{W}pBdr")) if p.find(f"{W}pPr/{W}pBdr") is not None else None
               for p in items]
    out = []
    for i, p in enumerate(items):
        ppr = p.find(W + "pPr")
        spacing = ppr.find(W + "spacing") if ppr is not None else None
        ind = ppr.find(W + "ind") if ppr is not None else None
        runs = _runs(p)
        left, hanging = _twips(ind, "left"), _twips(ind, "hanging")
        lines = _lines(runs, width - left + hanging, width - left) if runs else 1
        # A line is as tall as its tallest text (a bare tab run has no size of its own and doesn't count).
        tallest = max((size * f.line for text, f, size in runs if text != "\t"), default=body_line(theme))
        height = lines * tallest
        # A bottom rule adds its gap and its width, drawn once under a run of paragraphs that share it
        # (the section title and the summary below it).
        if borders[i] is not None and (i + 1 == len(items) or borders[i + 1] != borders[i]):
            bottom = p.find(f"{W}pPr/{W}pBdr/{W}bottom")
            if bottom is not None:
                height += int(bottom.get(W + "space", "0")) + int(bottom.get(W + "sz", "4")) / 8  # pt, ⅛ pt
        keep = ppr is not None and ppr.find(W + "keepNext") is not None
        out.append(_Para(_twips(spacing, "before"), height, _twips(spacing, "after"), keep))
    return out


@dataclass(frozen=True)
class Layout:
    fills: list[float]   # per page, how much of the usable height is used (0-1)
    lines: float         # body lines used, counting the room each page break leaves empty
    per_page: float      # body lines per page

    @property
    def pages(self) -> int:
        return len(self.fills)


def paginate(paras: list[_Para], height: float) -> list[float]:
    """Points used on each page. Between two paragraphs the larger of the first one's space after and the next
    one's space before applies (as in Word); paragraphs never split, and a heading (keep with next) moves to
    the next page together with what follows it."""
    groups: list[list[_Para]] = [[]]
    for p in paras:
        groups[-1].append(p)
        if not p.keep_next:
            groups.append([])

    def cost(paras: list[_Para], after: float | None) -> float:  # after None: at the top of a page
        total = 0.0
        for p in paras:
            total += (p.before if after is None else max(after, p.before)) + p.body
            after = p.after
        return total

    pages: list[float] = []
    used, after = 0.0, None
    for group in (g for g in groups if g):
        if after is not None and used + cost(group, after) > height and cost(group, None) <= height:
            pages.append(used)
            used, after = 0.0, None
        for p in group:  # a group taller than a page breaks where it must
            if after is not None and used + cost([p], after) > height:
                pages.append(used)
                used, after = 0.0, None
            used += cost([p], after)
            after = p.after
    pages.append(used)
    return pages


def measure(docx: Path, theme: Theme, paper: str | None) -> Layout:
    """Lay the document out on pages, the way Word does (see paginate)."""
    height = usable(theme, paper)[1]
    pages = paginate(paragraphs(docx, theme, paper), height)
    line = body_line(theme)
    return Layout([round(min(u / height, 1.0), 3) for u in pages],
                  ((len(pages) - 1) * height + pages[-1]) / line, height / line)
