"""How full the built PDF really is, and learning from it.

`ai.estimate_lines` counts wrapped lines with a fixed characters-per-line and lines-per-page for each
theme; Word (or LibreOffice) is the truth. After every PDF build we measure how far down each page the
text reaches, and keep a correction factor per design (theme + paper) in `<data folder>/calibration.json`,
so length budgets converge on what the PDF engine really fits. The same measurement tells the UI how much
room the last page has left ("Fill the page").
"""

from __future__ import annotations

import json
from pathlib import Path

from .themes import Theme

FILL_GOAL = 0.92     # "Fill the page" aims the last page at this share of its usable height
ROOM_MIN_LINES = 5   # offer "Fill the page" only with at least this many free lines
_FACTOR_RANGE = (0.8, 1.3)
_WEIGHT = 0.4        # how much each new build moves the factor (moving average)


def page_fill(pdf: Path, theme: Theme) -> list[float]:
    """For each page, how far down the usable height (inside the top/bottom margins) the text reaches: 0-1."""
    from pypdf import PdfReader

    top, _, bottom, _ = (m / 20 for m in theme.margins)  # twips → points
    fills = []
    for page in PdfReader(str(pdf)).pages:
        lowest: list[float] = []

        def visit(text, cm, tm, _font, _size, lowest=lowest):
            if text.strip():
                lowest.append(tm[4] * cm[1] + tm[5] * cm[3] + cm[5])  # baseline y on the page
        page.extract_text(visitor_text=visit)
        height = float(page.mediabox.height)
        usable = height - top - bottom
        fills.append(0.0 if not lowest else round(min(1.0, max(0.0, (height - top - min(lowest)) / usable)), 3))
    return fills


def _path(private: Path) -> Path:
    return private / "calibration.json"


def _load(private: Path | None) -> dict | None:
    """The calibration data; {} when there is none yet, None when the file exists but can't be read
    (then nothing is learned, rather than overwriting what other designs learned)."""
    if not private or not _path(private).exists():
        return {}
    from .oscompat import read_text
    try:
        data = json.loads(read_text(_path(private)))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def lines_factor(private: Path | None, theme: Theme, paper: str | None) -> float:
    """Measured lines-per-page ÷ the theme's nominal figure for this design (1.0 until a PDF was measured)."""
    entry = (_load(private) or {}).get(f"{theme.id}/{paper or theme.paper}", {})
    factor = entry.get("factor") if isinstance(entry, dict) else None
    return float(factor) if isinstance(factor, (int, float)) else 1.0


def record(private: Path, theme: Theme, paper: str | None, est_lines: int, fills: list[float]) -> None:
    """Learn from a real build: `est_lines` estimated lines took `sum(fills)` pages in the PDF."""
    used = sum(fills)
    if used < 0.5 or est_lines <= 0:  # too little text to learn anything
        return
    nominal = theme.lines_per_page(paper)
    sample = min(max(est_lines / used / nominal, _FACTOR_RANGE[0]), _FACTOR_RANGE[1])
    data = _load(private)
    if data is None:
        return
    key = f"{theme.id}/{paper or theme.paper}"
    old = data.get(key) if isinstance(data.get(key), dict) else {}
    factor = sample if "factor" not in old else (1 - _WEIGHT) * float(old["factor"]) + _WEIGHT * sample
    data[key] = {"factor": round(factor, 4), "builds": int(old.get("builds", 0)) + 1}
    from .store import _write_json_atomic  # callers hold store.lock
    _write_json_atomic(_path(private), data)


def room_lines(fills: list[float], lines_per_page: float) -> int:
    """Lines that fit on the last page before it reaches FILL_GOAL (0 when it's already full enough)."""
    if not fills:
        return 0
    return max(0, int((FILL_GOAL - fills[-1]) * lines_per_page))
