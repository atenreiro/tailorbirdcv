"""Resume designs. `classic` is the original design, byte-for-byte; the others vary fonts, colours,
sizes and spacing on the same structure (so every theme works with the fact-check and ATS checks).

Sizes are Word half-points (19 = 9.5 pt); spacing and margins are twips (1/1440 inch).
Fonts are ones LibreOffice can match without Microsoft's fonts installed (Calibri → Carlito,
Georgia → Gelasio, Cambria → Caladea), so page breaks stay the same on every OS.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    titles: dict[str, str] = field(default_factory=lambda: dict(TITLES))

    def page(self, paper: str | None = None) -> tuple[int, int]:
        return PAPER[paper or self.paper]

    def text_width(self, paper: str | None = None) -> int:
        top, right, bottom, left = self.margins
        return self.page(paper)[0] - left - right

    def line_chars(self, paper: str | None = None) -> int:
        """Rough characters per line, scaled from the Classic design (100 at 9.5 pt on Letter)."""
        return round(100 * self.text_width(paper) / 10080 * 19 / self.body_size)

    def lines_per_page(self, paper: str | None = None) -> int:
        top, right, bottom, left = self.margins
        height = self.page(paper)[1] - top - bottom
        return round(55 * height / (15840 - 1700) * 19 / self.body_size)

    def fonts(self) -> list[str]:
        return sorted({self.name_font, self.body_font})


CLASSIC = Theme("classic", "Classic", "Serif name, warm rust accent, rules under each heading. The original design.")

MODERN = Theme(
    "modern", "Modern", "One clean sans-serif throughout, navy accent, slightly larger name.",
    name_font="Calibri", accent="1F3A68", ink="111827", body="273142", muted="5B6475", scope="3E4757",
    date="5B6475", rule="C9D3E3", name_size=50, headline_size=22,
)

COMPACT = Theme(
    "compact", "Compact", "The Classic look with smaller type and tighter spacing, for 1-page resumes.",
    name_size=40, headline_size=20, contact_size=16, section_size=17, body_size=18, company_size=19, date_size=16,
    after=20, name_after=30, contact_after=80, section_before=110, section_after=40, company_before=70,
    company_after=10, scope_after=30, hang=260, margins=(720, 900, 720, 900),
)

THEMES = {t.id: t for t in (CLASSIC, MODERN, COMPACT)}


def get(theme_id: str | None) -> Theme:
    return THEMES.get(theme_id or "classic", CLASSIC)
