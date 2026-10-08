"""What end-to-end runs with other people's CVs (a nurse, a new graduate, an engineer, a TPM: none of them the
developer) turned up: each test is one of those findings, with fictional people only."""

import asyncio
import copy

import pytest

from tailorbirdcv import critique, importer, privacy, themes
from tailorbirdcv.api import create_app
from tailorbirdcv.engine import FakeEngine, PrivateEngine
from tailorbirdcv.render import docx_text, render, use_design
from tailorbirdcv.schema import MasterProfile, TailoredResume
from tailorbirdcv.store import Store
from conftest import client_for
from test_audit_fixes import TAILORED
from test_importer import TRANSCRIPTION

MAI = "Nguyễn Thị Mai"
MAI_CV = f"""{MAI}
Registered Nurse (Adult)
Leeds, UK · 07700 900123 · mai@example.org
EXPERIENCE
Staff Nurse, Westgate Hospital, Leeds, 2019 – Present
- Cared for up to 8 patients per shift on a 30-bed ward.
EDUCATION
BSc Adult Nursing — University of Northfield (2019)
"""
MAI_READ = {"contact": {"name": "", "location": "Leeds, UK", "phone": "[PHONE]", "email": "[EMAIL]", "links": []},
            "headline": "Registered Nurse (Adult)", "summary": "", "highlights": [], "skills": [],
            "roles": [{"employer": "Westgate Hospital", "location": "Leeds", "title": "Staff Nurse",
                       "dates": "2019 – Present", "scope": "",
                       "achievements": ["Cared for up to 8 patients per shift on a 30-bed ward."], "sub_roles": []}],
            "projects": [], "education": [{"label": "BSc Adult Nursing", "text": "University of Northfield (2019)"}],
            "extras": []}


class Recorder:
    name = "recorder"

    def __init__(self, answer):
        self.answer, self.systems, self.prompts = answer, [], []

    async def complete(self, system, prompt, schema):
        self.systems.append(system)
        self.prompts.append(prompt)
        return copy.deepcopy(self.answer)


def test_a_dropped_name_placeholder_falls_back_to_the_name_typed(tmp_path):
    """The AI sometimes answers the CV import without the [NAME] placeholder: the profile used to be "Your Name"."""
    store = Store(tmp_path / "private")
    client = client_for(create_app(store, FakeEngine({"import": MAI_READ})))
    r = client.post("/api/profile/import", json={"text": MAI_CV, "name": MAI})
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["contact"]["name"] == MAI and r.json()["unverified"] == []


def test_the_ai_is_told_to_keep_placeholders_only_when_something_was_hidden(tmp_path):
    store = Store(tmp_path / "private")
    rec = Recorder({"ok": True})
    engine = PrivateEngine(rec, store)
    token = privacy.use(MAI)
    try:
        asyncio.run(engine.complete("You transcribe CVs.", MAI_CV, {}))
        asyncio.run(engine.complete("You transcribe CVs.", "Nothing personal here.", {}))
    finally:
        privacy.EXTRA.reset(token)
    assert MAI not in rec.prompts[0] and privacy.PLACEHOLDER_NOTE in rec.systems[0]
    assert rec.systems[1] == "You transcribe CVs."


@pytest.mark.parametrize("phone", ["07700 900123", "06 12 34 56 78", "0151 23456789", "020 7946 0958", "07700900123",
                                   "9123 4567", "98765 43210"])
def test_national_phone_formats_are_hidden(phone):
    assert "[PHONE]" in privacy.Vault().redact(f"Leeds, UK · {phone} · mai@example.org")


@pytest.mark.parametrize("text", ["01.03.2019 – 03.2022", "2016-2019", "2014 2015", "4,500 employees", "10 000 users",
                                  "from 900 ms to 180 ms", "€40M a month to 12,000 merchants", "05/2019 – 08/2021",
                                  "ISO 27001:2022", "1 200 000 records", "Band 6"])
def test_resume_numbers_and_dates_are_not_phones(text):
    assert "[PHONE" not in privacy.Vault().redact(text)


def test_two_roles_at_one_employer_are_each_verified_in_their_own_part():
    """A promotion: "Technical Program Manager" is also inside "Senior Technical Program Manager", so both roles
    used to claim the first heading and every line of the newer role was flagged as not in the CV."""
    cv = """Kai Example
Senior Technical Program Manager, Compute
Northwind Cloud, Seattle | 2019–present
- Ran the migration of 2,300 services to containers across 41 teams.
- Set up quarterly planning for 6 teams.
Technical Program Manager, Storage
Northwind Cloud, Seattle | Apr. 2017 – Dec. 2018
- Coordinated the launch of tiered storage with 5 teams.
"""
    read = {"contact": {"name": "Kai Example", "location": "", "phone": "", "email": "", "links": []},
            "headline": "", "summary": "", "highlights": [], "skills": [], "projects": [], "education": [], "extras": [],
            "roles": [{"employer": "Northwind Cloud", "location": "Seattle", "title": "Senior Technical Program Manager, Compute",
                       "dates": "2019–present", "scope": "", "sub_roles": [],
                       "achievements": ["Ran the migration of 2,300 services to containers across 41 teams.",
                                        "Set up quarterly planning for 6 teams."]},
                      {"employer": "Northwind Cloud", "location": "Seattle", "title": "Technical Program Manager, Storage",
                       "dates": "Apr. 2017 – Dec. 2018", "scope": "", "sub_roles": [],
                       "achievements": ["Coordinated the launch of tiered storage with 5 teams."]}]}
    profile = importer.build_profile(read)
    assert importer.unverified(profile, cv) == []
    moved = copy.deepcopy(profile)  # …and a line still can't move to the other role at the same employer
    moved["roles"][1]["achievements"][0]["text"] = "Set up quarterly planning for 6 teams."
    assert f"{moved['roles'][1]['id']}.a1" in importer.unverified(moved, cv)


def test_the_review_sees_education_certificates_and_projects():
    """The review was given only the draft's claims, so it reported a degree or a certificate that is on the page
    as missing."""
    profile = MasterProfile.model_validate(importer.build_profile(TRANSCRIPTION))
    t = TailoredResume.model_validate({**TAILORED, "experience": [], "highlights": [],
                                       "education": [e.id for e in profile.education]})
    prompt = critique._prompt(profile, t, {"requirements": []}, None)
    assert "BA Design University of Porto (2014)" in prompt.split("ALSO ON THE PAGE")[1]


def test_a_new_profile_gets_neutral_headings_and_older_ones_keep_theirs(tmp_path):
    store = Store(tmp_path / "private")
    client = client_for(create_app(store, FakeEngine({"import": MAI_READ})))
    assert client.post("/api/profile/import", json={"text": MAI_CV, "name": MAI}).status_code == 200
    profile = store.setup_draft()["profile"]
    assert client.post("/api/profile/create", json={"profile": profile, "confirmed": []}).status_code == 200
    assert store.settings()["section_titles"]["extras"] == "ADDITIONAL INFORMATION"
    assert client.get("/api/settings").json()["section_defaults"]["extras"] == themes.TITLES["extras"]
    # headings print as set, and a blank one is the design's own
    assert client.put("/api/settings", json={"section_titles": {"education": "Registration & education"}}).status_code == 200
    assert client.put("/api/settings", json={"section_titles": {"nope": "x"}}).status_code == 422
    titles = store.settings()["section_titles"]
    use_design("classic", "a4", None, titles)
    try:
        text = docx_text(render(store.profile(), TailoredResume.model_validate(
            {"headline": store.profile().headlines[0].id, "experience": [], "education": ["edu.bsc-adult-nursing"]}),
            tmp_path / "r.docx"))
    finally:
        use_design(None, None)
    assert "Registration & education" in text and "EDUCATION & CERTIFICATIONS" not in text
    assert not any(Store(tmp_path / "older").settings()["section_titles"].values())  # no setting: TITLES, as before


def test_headings_in_shipped_defaults_read_like_nobodys_resume():
    assert "COMMUNITY" not in " ".join(themes.NEW_PROFILE_TITLES.values())
    assert set(themes.NEW_PROFILE_TITLES) <= set(themes.TITLES)
