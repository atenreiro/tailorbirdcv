"""Render a TailoredResume to .docx, reproducing the base resume's design exactly.

The base resume uses direct formatting (no Word styles), so each paragraph type is
encoded here as the same pPr/rPr XML measured from the original. The template
(data/templates/base.docx) carries the theme, fonts, settings and page setup with an
empty body and no personal data.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import parse_xml

from .schema import MasterProfile, TailoredResume

TEMPLATE = Path(__file__).resolve().parent / "data" / "templates" / "base.docx"

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

ACCENT, INK, BODY, MUTED, SCOPE, DATE, RULE = (
    "7C2D12", "171717", "2B2B2B", "555555", "4A4A4A", "666666", "D9D2C9",
)
BULLET = "•  "
SEP = " · "

SECTION_TITLES = {
    "summary": "SUMMARY",
    "highlights": "CAREER HIGHLIGHTS",
    "competencies": "CORE COMPETENCIES",
    "experience": "PROFESSIONAL EXPERIENCE",
    "projects": "PROJECTS & COMMUNITY LEADERSHIP",
    "education": "EDUCATION & CERTIFICATIONS",
    "extras": "AWARDS & LANGUAGES",
}

_SPACING = '<w:spacing w:before="{before}" w:after="{after}" w:line="240" w:lineRule="auto"/>'
_RULE = f'<w:pBdr><w:bottom w:val="single" w:sz="4" w:space="2" w:color="{RULE}"/></w:pBdr>'
_HANG = '<w:ind w:left="280" w:hanging="280"/>'
_TAB = '<w:tabs><w:tab w:val="right" w:pos="10080"/></w:tabs>'


def _rpr(color: str, size: int, *, bold=False, italic=False, font="Calibri") -> str:
    return (
        f'<w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}"/>'
        + ("<w:b/>" if bold else "")
        + ("<w:i/>" if italic else "")
        + f'<w:color w:val="{color}"/><w:sz w:val="{size}"/></w:rPr>'
    )


_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")  # e.g. form feeds from PDFs


def clean_text(text: str) -> str:
    return _XML_INVALID.sub(" ", text or "")


def _run(text: str, color: str, size: int, **kw) -> str:
    return f'<w:r>{_rpr(color, size, **kw)}<w:t xml:space="preserve">{escape(clean_text(text))}</w:t></w:r>'


def _para(runs: str, *, before=0, after=30, rule=False, hang=False, tab=False) -> str:
    spacing = _SPACING.format(before=before, after=after).replace(' w:before="0"', "")
    ppr = "<w:keepLines/>" + (_TAB if tab else "") + (_RULE if rule else "") + spacing
    ppr += _HANG if hang else ""
    return f"<w:p {W_NS} {R_NS}><w:pPr>{ppr}</w:pPr>{runs}</w:p>"


class _Builder:
    def __init__(self, template: Path):
        self.doc = Document(str(template))
        self.body = self.doc.element.body
        self.sect = self.body[-1]  # sectPr stays last

    def add(self, xml: str) -> None:
        self.sect.addprevious(parse_xml(xml))

    def hyperlink(self, text: str, url: str) -> str:
        rid = self.doc.part.relate_to(url, RT.HYPERLINK, is_external=True)
        inner = _run(text, ACCENT, 17)
        return f'<w:hyperlink r:id="{rid}">{inner}</w:hyperlink>'

    # paragraph types ------------------------------------------------------------
    def name(self, text):
        self.add(_para(_run(text, INK, 46, bold=True, font="Georgia"), after=40))

    def headline(self, text):
        self.add(_para(_run(text, ACCENT, 21, bold=True), after=40))

    def contact(self, parts: list[tuple[str, str | None]]):
        runs = []
        for i, (text, url) in enumerate(parts):
            if i:
                runs.append(_run(SEP, MUTED, 17))
            runs.append(self.hyperlink(text, url) if url else _run(text, MUTED, 17))
        self.add(_para("".join(runs), after=120))

    def section(self, title):
        self.add(_para(_run(title, ACCENT, 18, bold=True), before=140, after=60, rule=True))

    def summary(self, text):
        # The original summary shares the heading's bottom rule (Word draws one rule
        # under the grouped pair), so the paragraph properties are the same.
        self.add(_para(_run(text, BODY, 19), before=140, after=60, rule=True))

    def bullet(self, text):
        self.add(_para(_run(BULLET + text, BODY, 19), hang=True))

    def lead_bullet(self, label, text):
        runs = _run(BULLET, BODY, 19) + _run(label, INK, 19, bold=True) + _run(text, BODY, 19)
        self.add(_para(runs, hang=True))

    def company(self, left, dates):
        runs = _run(left, INK, 20, bold=True) + "<w:r><w:tab/></w:r>" + _run(dates, DATE, 17)
        self.add(_para(runs, before=90, after=20, tab=True))

    def title(self, text):
        self.add(_para(_run(text, ACCENT, 19, bold=True)))

    def scope(self, text, italic=True):
        color = SCOPE if italic else BODY
        self.add(_para(_run(text, color, 19, italic=italic), after=40))


def _lead_text(text: str) -> str:
    return " " + text if text and not text.startswith((" ", ",", ":")) else text


def render(profile: MasterProfile, tailored: TailoredResume, out: Path,
           template: Path = TEMPLATE) -> Path:
    b = _Builder(template)
    c = profile.contact

    b.name(c.name)
    b.headline(profile.headline(tailored.headline).text)
    parts: list[tuple[str, str | None]] = [(c.location, None)]
    if c.phone:
        parts.append((c.phone, None))
    if c.email:
        parts.append((c.email, f"mailto:{c.email}"))
    parts += [(link.text, link.url) for link in c.links]
    b.contact(parts)

    if tailored.summary:
        b.section(SECTION_TITLES["summary"])
        b.summary(tailored.summary.text)

    if tailored.highlights:
        b.section(SECTION_TITLES["highlights"])
        for h in tailored.highlights:
            b.bullet(h.text)

    if any(c.items for c in tailored.competencies):
        b.section(SECTION_TITLES["competencies"])
        for comp in tailored.competencies:
            if comp.items:  # an emptied group is simply left out
                b.lead_bullet(f"{comp.label}: ", SEP.join(comp.items))

    if tailored.experience:
        b.section(SECTION_TITLES["experience"])
        for tr in tailored.experience:
            role = profile.role(tr.role)
            b.company(f"{role.employer}, {role.location}", role.dates)
            b.title(role.title)
            if tr.scope:
                b.scope(tr.scope.text, italic=role.scope.italic if role.scope else True)
            for bl in tr.bullets:
                b.bullet(bl.text)
            for sr in tr.sub_roles:
                item = profile.lead_item(sr.id)
                b.lead_bullet(item.label, _lead_text(sr.text.text if sr.text else item.text))

    if tailored.projects:
        b.section(SECTION_TITLES["projects"])
        for tp in tailored.projects:
            item = profile.lead_item(tp.id)
            b.lead_bullet(item.label, _lead_text(tp.text.text if tp.text else item.text))

    for key in ("education", "extras"):
        ids = getattr(tailored, key)
        if ids:
            b.section(SECTION_TITLES[key])
            for item_id in ids:
                item = profile.lead_item(item_id)
                b.lead_bullet(item.label, _lead_text(item.text))

    props = b.doc.core_properties
    props.author = props.last_modified_by = c.name
    props.title = f"{c.name} — Resume"
    props.created = props.modified = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    out.parent.mkdir(parents=True, exist_ok=True)
    b.doc.save(str(out))
    return out


def docx_text(path: Path) -> list[str]:
    """Paragraph texts of a .docx (tabs kept), for fidelity comparisons."""
    doc = Document(str(path))
    lines = []
    for p in doc.paragraphs:
        text = "".join(
            (node.text or "") if node.tag.endswith("}t") else "\t"
            for node in p._p.iter()
            if node.tag.endswith("}t") or node.tag.endswith("}tab") and node.getparent().tag.endswith("}r")
        )
        lines.append(text)
    return [line for line in lines if line.strip()]
