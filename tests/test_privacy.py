"""Privacy mode (privacy.py, engine.PrivateEngine): the user's contact details never reach the AI, every
answer gets them back, and the resume still prints them. Fictional people only."""

import re
import shutil
import unicodedata
from pathlib import Path

import pytest
import yaml

from tailorbirdcv import ai, critique, importer, privacy
from tailorbirdcv.api import create_app
from tailorbirdcv.engine import EngineError, FakeEngine, PrivateEngine
from tailorbirdcv.render import docx_text, render
from tailorbirdcv.schema import load_profile, load_tailored
from tailorbirdcv.store import Store
from conftest import client_for
from test_api import ANALYSIS, JD, TAILORED
from test_importer import NAME, RESUME, TRANSCRIPTION

FIX = Path(__file__).parent / "fixtures"
ADDRESS = "12 Example Street, #05-01"
# Jane Example's contact details (tests/fixtures/profile.yaml), in the forms they could take in a prompt.
LEAKS = ["jane example", "jane@example.com", "+65 0000 0000", "65 0000 0000", "github.com/jane-example", ADDRESS.lower()]


def plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def leaked(prompts: list[str]) -> list[str]:
    return [leak for prompt in prompts for leak in LEAKS if leak in plain(prompt)]


@pytest.fixture
def env(tmp_path):
    """Jane's data folder, with her contact details also written into places a prompt carries: a project, a
    gap answer, the guidance, and her saved street address."""
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    profile = yaml.safe_load((FIX / "profile.yaml").read_text(encoding="utf-8"))
    profile["projects"][0]["text"] = "— Open-source threat-intel tool by Jane Example (github.com/jane-example/toolx)."
    (private / "profile.yaml").write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    shutil.copy(FIX / "tailored.yaml", private / "source" / "base_tailored.yaml")
    store = Store(private)
    store.save_settings({"private_address": ADDRESS})
    engine = FakeEngine({"analyze": ANALYSIS, "compose": TAILORED, "repair": TAILORED,
                         "propose_evidence": {"proposals": []}})
    return client_for(create_app(store, engine)), store, engine


def test_no_contact_detail_reaches_the_ai_in_any_flow(env):
    client, store, engine = env
    assert client.post("/api/engine/test").status_code in (200, 503)
    app_id = client.post("/api/applications", json={"jd": JD + "\nApply to jobs@example-capital.com."}).json()["id"]
    app_id = client.post(f"/api/applications/{app_id}/analyze").json()["id"]
    proposals = client.post(f"/api/applications/{app_id}/proposals", json=[
        {"question_id": "q1", "question": "Any Kubernetes work?",
         "answer": "Yes — ask Jane Example at jane@example.com or +65 0000 0000, 12 Example Street, #05-01."}])
    assert proposals.status_code == 200, proposals.text
    composed = client.post(f"/api/applications/{app_id}/compose", json={"guidance": "Jane Example prefers short bullets."})
    assert composed.status_code == 200
    prompts = [p for _, p in engine.calls]
    assert {"test", "analyze", "propose_evidence", "compose"} <= {task for task, _ in engine.calls}
    assert leaked(prompts) == []
    assert "[NAME]" in "".join(prompts) and "[EMAIL]" in "".join(prompts) and "[ADDRESS]" in "".join(prompts)
    assert "Example Capital" in prompts[-1]  # the job's own company and details still go


class Recorder:
    """Records the prompt, then fails: enough to see what each AI task would send."""
    name = "recorder"

    def __init__(self):
        self.prompts: list[str] = []

    async def complete(self, system, prompt, schema):
        self.prompts += [system, prompt]
        raise EngineError("recorded")


@pytest.mark.parametrize("task", ["critique", "fill", "trim", "preferences", "propose"])
def test_every_other_ai_task_is_covered_too(env, task):
    _, store, _ = env
    rec = Recorder()
    engine = PrivateEngine(rec, store)
    profile, tailored = store.profile(), load_tailored(FIX / "tailored.yaml")
    tailored.summary.text += " Contact Jane Example."
    calls = {
        "critique": lambda: critique.critique(engine, profile, tailored, ANALYSIS, None),
        "fill": lambda: ai.fill(engine, profile, tailored, ANALYSIS, 10, []),
        "trim": lambda: ai.fit_to_length(engine, profile, tailored, ANALYSIS, budget=1),
        "preferences": lambda: ai.learn_preferences(engine, [{"before": "x", "after": "Jane Example, jane@example.com"}],
                                                    ["Write like Jane Example"], [], []),
        "propose": lambda: ai.propose_evidence(engine, profile, [{"question_id": "q1", "text": "Call +65 0000 0000"}]),
    }
    import asyncio
    try:
        asyncio.run(calls[task]())
    except Exception:  # noqa: BLE001 — the recorder always fails; only the prompt matters
        pass
    assert rec.prompts and leaked(rec.prompts) == []


def test_the_cv_import_hides_the_name_typed_first_and_restores_the_answer(tmp_path):
    seen = []

    def transcribe(prompt):
        seen.append(prompt)
        out = yaml.safe_load(yaml.safe_dump(TRANSCRIPTION))  # what the AI reads: placeholders
        out["contact"] = {"name": "[NAME]", "location": "Lisbon, Portugal", "phone": "[PHONE]", "email": "[EMAIL]",
                          "links": [{"text": "[LINK]", "url": "https://[LINK]"}]}
        out["roles"][0]["achievements"] = out["roles"][0]["achievements"][:1] + [
            "Built the design system used by 5 product teams."]
        return out
    store = Store(tmp_path / "private")
    client = client_for(create_app(store, FakeEngine({"import": transcribe})))
    r = client.post("/api/profile/import", json={"text": RESUME, "name": NAME})
    assert r.status_code == 200, r.text
    for value in ("Jordan Rivera", "jordan@example.com", "+351 900 000 000", "jordanrivera.design"):
        assert value not in seen[0]
    contact = r.json()["profile"]["contact"]
    assert (contact["name"], contact["email"], contact["phone"]) == ("Jordan Rivera", "jordan@example.com", "+351 900 000 000")
    assert contact["links"][0]["text"] == "jordanrivera.design" and r.json()["unverified"] == []
    no_name = client.post("/api/profile/import", json={"text": RESUME})
    assert no_name.status_code == 422 and "full name" in no_name.json()["detail"]


def test_with_privacy_mode_off_only_the_contact_block_stays_out(env):
    client, store, engine = env
    client.put("/api/settings", json={"hide_personal": False})
    app_id = client.post("/api/applications", json={"jd": JD}).json()["id"]
    client.post(f"/api/applications/{app_id}/analyze")
    prompt = engine.calls[-1][1]
    assert "Jane Example" in prompt  # in the project text: sent as written
    assert "jane@example.com" not in prompt and "+65 0000 0000" not in prompt  # the contact block never is


def test_the_resume_still_prints_every_contact_detail(env, tmp_path):
    _, store, _ = env
    text = "\n".join(docx_text(render(store.profile(), load_tailored(FIX / "tailored.yaml"), tmp_path / "r.docx")))
    for value in ("Jane Example", "jane@example.com", "+65 0000 0000", "github.com/jane-example"):
        assert value in text


def test_resume_facts_are_never_hidden():
    profile = load_profile(FIX / "profile.yaml")
    vault = privacy.vault_for(profile.contact.model_dump(), ADDRESS)
    text = ai.profile_text(profile) + JD + ("Cut costs by US$1.7M, 20M+ users, 4,500 staff, 2019 – 2022, 65% fewer alerts, "
                                            "Grant Will and Rose Mark reviewed it; see acme.com/careers and 10.0.0.1.")
    assert vault.redact(text) == text  # nothing personal in there: nothing changes
    assert "contact" not in yaml.safe_load(ai.profile_text(profile))


@pytest.mark.parametrize("variant", ["JANE EXAMPLE", "Jane  Example", "jane@EXAMPLE.com", "+65-0000-0000",
                                     "(65) 0000 0000", "https://www.github.com/jane-example/"])
def test_variants_of_the_same_detail_are_hidden(variant):
    vault = privacy.vault_for(load_profile(FIX / "profile.yaml").contact.model_dump())
    redacted = vault.redact(f"Reach {variant} today.")
    assert re.fullmatch(r"Reach \[[A-Z]+(?: \d+)?\] today\.", redacted), redacted
    assert vault.restore(redacted) == f"Reach {variant} today."


def test_the_settings_preview_shows_what_the_ai_receives(env):
    client, _, _ = env
    preview = client.get("/api/privacy/preview").json()
    assert preview["on"] and "[NAME]" in preview["text"] and "Jane Example" not in preview["text"]
    assert preview["hidden"]["[NAME]"] == "Jane Example"
