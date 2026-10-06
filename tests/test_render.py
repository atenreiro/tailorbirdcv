"""Render ↔ ingest round trip on the synthetic fixture: what render writes, ingest
must read back identically (this is what makes `tailorbirdcv baseline` meaningful)."""

from pathlib import Path

from tailorbirdcv.ingest import ingest
from tailorbirdcv.render import docx_text, render
from tailorbirdcv.schema import MasterProfile, TailoredResume, load_profile, load_tailored

FIX = Path(__file__).parent / "fixtures"


def test_render_ingest_round_trip(tmp_path):
    profile = load_profile(FIX / "profile.yaml")
    tailored = load_tailored(FIX / "tailored.yaml")
    out = render(profile, tailored, tmp_path / "r.docx")

    p2, base = ingest(out)
    again = render(MasterProfile.model_validate(p2), TailoredResume.model_validate(base), tmp_path / "r2.docx")
    assert docx_text(out) == docx_text(again)


def test_locked_fields_come_from_profile(tmp_path):
    profile = load_profile(FIX / "profile.yaml")
    tailored = load_tailored(FIX / "tailored.yaml")
    lines = docx_text(render(profile, tailored, tmp_path / "r.docx"))
    assert "Acme Bank, Singapore\tJan 2022 – Present" in lines
    assert "Vice President | Detection Lead" in lines
    assert "Detection & Response Engineering Lead" in lines  # tailored headline id resolved
    assert "•  Analyst (2020 – 2021) — Triaged alerts." in lines
    assert "•  Security: Detection engineering · WAF · Perimeter & edge security" in lines


def test_empty_sections_are_omitted(tmp_path):
    profile = load_profile(FIX / "profile.yaml")
    tailored = load_tailored(FIX / "tailored.yaml")
    tailored.highlights = []
    tailored.projects = []
    lines = docx_text(render(profile, tailored, tmp_path / "r.docx"))
    assert "CAREER HIGHLIGHTS" not in lines
    assert "PROJECTS & COMMUNITY LEADERSHIP" not in lines
