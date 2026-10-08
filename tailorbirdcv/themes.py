"""Resume designs. `classic` is the original design, byte-for-byte; the others vary fonts, colours,
sizes and spacing on the same structure (so every theme works with the fact-check and ATS checks).

Sizes are Word half-points (19 = 9.5 pt); spacing and margins are twips (1/1440 inch).
Fonts are ones LibreOffice can match without Microsoft's fonts installed (Calibri → Carlito,
Georgia → Gelasio, both shipped in data/fonts), so page breaks stay the same on every OS.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

MIN_SIZE = 19  # half-points: no text smaller than 9.5 pt, except Classic as originally drawn (Standard size)

# Paper sizes (twips): width, height.
PAPER = {"letter": (12240, 15840), "a4": (11906, 16838)}

TITLES = {
    "summary": "SUMMARY",
    "highlights": "CAREER HIGHLIGHTS",
    "competencies": "CORE COMPETENCIES",
    "experience": "PROFESSIONAL EXPERIENCE",
    "projects": "PROJECTS & COMMUNITY LEADERSHIP",
    "education": "EDUCATION & CERTIFICATIONS",
    "extras": "AWARDS & LANGUAGES",
}

# What a new profile starts with (Settings → Resume design → Section headings): the two TITLES above that read
# like one person's resume ("community leadership", "awards & languages") become neutral. Profiles made before
# headings were a setting keep TITLES exactly, and so does the Classic golden render.
NEW_PROFILE_TITLES = {"projects": "PROJECTS", "extras": "ADDITIONAL INFORMATION"}


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    description: str
    name_font: str = "Georgia"
    body_font: str = "Calibri"
    # colours (hex, no #)
    accent: str = "7C2D12"
    ink: str = "171717"
    body: str = "2B2B2B"
    muted: str = "555555"
    scope: str = "4A4A4A"
    date: str = "666666"
    rule: str = "D9D2C9"
    # sizes (half-points)
    name_size: int = 46
    headline_size: int = 21
    contact_size: int = 17
    section_size: int = 18
    body_size: int = 19
    company_size: int = 20
    date_size: int = 17
    # spacing (twips)
    after: int = 30
    name_after: int = 40
    contact_after: int = 120
    section_before: int = 140
    section_after: int = 60
    company_before: int = 90
    company_after: int = 20
    scope_after: int = 40
    hang: int = 280
    # page
    margins: tuple[int, int, int, int] = (850, 1080, 850, 1080)  # top, right, bottom, left
    paper: str = "letter"
    bullet: str = "•  "
    separator: str = " · "
    text_size: str = "standard"  # see TEXT_SIZES / sized()
    titles: dict[str, str] = field(default_factory=lambda: dict(TITLES))

    def page(self, paper: str | None = None) -> tuple[int, int]:
        return PAPER[paper or self.paper]

    def text_width(self, paper: str | None = None) -> int:
        top, right, bottom, left = self.margins
        return self.page(paper)[0] - left - right

    def line_chars(self, paper: str | None = None) -> int:
        """Characters of typical body text per line (measured with the fonts' real widths, see layout.py)."""
        from .layout import line_chars
        return line_chars(self, paper)

    def lines_per_page(self, paper: str | None = None) -> float:
        """Body lines that fit inside the margins (the unit of the length budget, see layout.py)."""
        from .layout import lines_per_page
        return lines_per_page(self, paper)

    def fonts(self) -> list[str]:
        return sorted({self.name_font, self.body_font})


CLASSIC = Theme("classic", "Classic", "Serif name, warm rust accent, rules under each heading. The original design.")

MODERN = Theme(
    "modern", "Modern", "One clean sans-serif throughout, navy accent, slightly larger name.",
    name_font="Calibri", accent="1F3A68", ink="111827", body="273142", muted="5B6475", scope="3E4757",
    date="5B6475", rule="C9D3E3", name_size=50, headline_size=22,
    contact_size=MIN_SIZE, section_size=MIN_SIZE, date_size=MIN_SIZE,
)

COMPACT = Theme(
    "compact", "Compact", "The Classic look with tighter spacing and margins, for 1-page resumes.",
    name_size=40, headline_size=20, contact_size=MIN_SIZE, section_size=MIN_SIZE, body_size=MIN_SIZE,
    company_size=MIN_SIZE, date_size=MIN_SIZE,
    after=20, name_after=30, contact_after=80, section_before=110, section_after=40, company_before=70,
    company_after=10, scope_after=30, hang=260, margins=(720, 900, 720, 900),
)

THEMES = {t.id: t for t in (CLASSIC, MODERN, COMPACT)}


# Text size (Settings → Resume design), applied on top of any theme. "standard" is each theme as designed
# (Classic byte-for-byte); "comfortable" makes the body 1 pt larger (9.5 → 10.5 pt) and dates, section titles
# and company names 1 pt larger too — easier to read, a little less per page. Nothing is smaller than 9.5 pt
# (MIN_SIZE) except in Classic at the Standard size, which keeps the original design's 8.5 pt contact line
# and dates.
TEXT_SIZES = ("standard", "comfortable")
DEFAULT_TEXT_SIZE = "comfortable"


def sized(theme: Theme, text_size: str | None) -> Theme:
    if text_size != "comfortable" or theme.text_size == "comfortable":
        return theme
    # The contact line stays as small as the minimum allows: it's one line of links that would otherwise wrap.
    return replace(theme, text_size="comfortable", body_size=theme.body_size + 2, company_size=theme.company_size + 2,
                   section_size=theme.section_size + 2, date_size=theme.date_size + 2,
                   headline_size=theme.headline_size + 1, contact_size=max(theme.contact_size, MIN_SIZE))


def get(theme_id: str | None, text_size: str | None = None) -> Theme:
    return sized(THEMES.get(theme_id or "classic", CLASSIC), text_size)
