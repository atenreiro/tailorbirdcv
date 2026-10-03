"""Who the resume is for (Settings → Your targets) steers the prompts and the page limit —
nothing about one particular candidate is hard-coded."""

import shutil
from pathlib import Path

import pytest
import yaml

from autocv import ai
from autocv.api import create_app
from autocv.engine import FakeEngine
from autocv.store import Store, file_safe_name
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
TAILORED = yaml.safe_load((FIX / "tailored.yaml").read_text(encoding="utf-8"))
ANALYSIS = {"company": "Example Capital", "role": "Lead", "industry": "tech", "track": "hybrid", "seniority": "Senior",
            "location": "", "summary": "x", "requirements": [], "keywords": [], "questions": [], "known_gaps": []}


@pytest.fixture
def env(tmp_path):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    engine = FakeEngine({"analyze": ANALYSIS, "compose": TAILORED, "repair": TAILORED, "trim": TAILORED})
    return client_for(create_app(Store(private), engine)), Store(private), engine


def new_app(client):
    return client.post("/api/applications", json={"jd": "Lead — Example Capital\n" + "x " * 80,
                                                   "company": "Example Capital", "role": "Lead"}).json()["id"]


def test_a_new_user_gets_neutral_prompts(env):
    client, _, engine = env
    client.post(f"/api/applications/{new_app(client)}/analyze")
    assert "healthcare" in engine.calls[0][1]  # the general industry lenses
    ai.use_context(ai.Context())  # no targets set
    assert ai.system_prompt().startswith("You are AutoCV, a meticulous resume strategist for a job seeker.")
    for word in ("cyber", "Singapore", "APAC", "banking"):
        assert word not in ai.system_prompt()


def test_targets_shape_the_system_prompt_and_spelling(env, monkeypatch):
    client, _, _ = env
    seen = []
    import autocv.engine as eng
    monkeypatch.setattr(eng.FakeEngine, "complete", lambda self, system, prompt, schema: _record(seen, self, system, prompt))
    r = client.put("/api/settings", json={"targets": {"field": "nursing", "seniority": "senior", "region": "  London ",
                                                      "roles": "ward manager roles", "spelling": "UK", "pages": 1}})
    assert r.status_code == 200 and r.json()["targets"]["region"] == "London"
    client.post(f"/api/applications/{new_app(client)}/analyze")
    system = seen[0]
    assert system.startswith("You are AutoCV, a meticulous resume strategist for a senior nursing professional "
                             "(targets: ward manager roles; London).")
    assert "UK English spelling" in system


async def _record(seen, engine, system, prompt):
    seen.append(system)
    return ANALYSIS


def test_invalid_targets_are_refused(env):
    client, _, _ = env
    assert client.put("/api/settings", json={"targets": {"pages": 4}}).status_code == 422
    assert client.put("/api/settings", json={"targets": {"spelling": "FR"}}).status_code == 422
    assert client.put("/api/settings", json={"targets": {"pack": "nope"}}).status_code == 422
    assert client.put("/api/settings", json={"targets": {"field": "x" * 81}}).status_code == 422


def test_config_comes_from_the_override_then_the_pack_then_the_default(tmp_path):
    ai.use_context(ai.Context())
    assert "healthcare" in ai.industries()
    ai.use_context(ai.Context(pack="cybersecurity"))
    assert ai.industries() == ["banking", "tech", "quant", "fintech", "telco", "consulting"]
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "industries.yaml").write_text("biotech:\n  signals: [lab]\n", encoding="utf-8")
    ai.use_context(ai.Context(pack="cybersecurity", private=tmp_path))
    assert ai.industries() == ["biotech"]
    assert "manager" in ai._config("tracks.yaml")  # no override for tracks → the pack's
    ai.use_context(ai.Context())


def test_shipped_config_has_no_personal_data():
    shipped = "\n".join(p.read_text(encoding="utf-8") for p in (ai.paths.DATA / "config").rglob("*.yaml"))
    for personal in ("ToolX", "mobile money", "Telco Co", "national CERT", "account-takeover", "Globex"):
        assert personal not in shipped


def test_the_page_limit_sets_the_budget_and_too_long(env):
    client, store, _ = env
    ai.use_context(ai.Context(pages=1))
    assert ai.default_budget() == {"lines": 55, "words": 500, "measured": False}
    ai.use_context(ai.Context(pages=3))
    assert ai.pages_text() == "3 pages" and ai.default_budget()["lines"] == 165
    ai.use_context(ai.Context())
    client.put("/api/settings", json={"targets": {"pages": 1}})
    assert store.settings()["targets"]["pages"] == 1


@pytest.mark.parametrize("name, stem", [("José Núñez", "Jose_Nunez"), ("Zoë O'Brien", "Zoe_O_Brien"),
                                        ("王小明", "王小明"), ("   ", "Resume")])
def test_output_file_names_keep_the_letters_of_any_name(name, stem):
    assert file_safe_name(name) == stem
