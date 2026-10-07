"""AI steps run as tasks: leaving the page never loses them, they can be stopped, and the page finds them again
(running, finished, or with a suggestion still waiting). Fictional data only."""

import asyncio
import shutil
import threading
import time
from pathlib import Path

import pytest
import yaml
from conftest import client_for

from tailorbirdcv.api import create_app
from tailorbirdcv.engine import FakeEngine
from tailorbirdcv.store import Store

FIX = Path(__file__).parent / "fixtures"
JD = "# Detection Lead — Example Capital\n\n" + "We need a hands-on detection engineering lead. " * 10
TAILORED = yaml.safe_load((FIX / "tailored.yaml").read_text(encoding="utf-8"))
ANALYSIS = {"company": "Example Capital", "role": "Detection Lead", "industry": "quant", "track": "ic",
            "seniority": "Senior", "location": "SG", "summary": "x", "requirements": [], "keywords": [],
            "questions": [{"id": "q1", "requirement": "Kubernetes", "question": "Any K8s?", "prefill_from": ""}],
            "known_gaps": []}


class Gate(FakeEngine):
    """Answers like FakeEngine, but each call waits until the test opens the gate (or the call is stopped)."""

    def __init__(self, responses):
        super().__init__(responses)
        self.open = threading.Event()
        self.waiting = threading.Event()

    async def complete(self, system, prompt, schema):
        self.waiting.set()
        while not self.open.is_set():
            await asyncio.sleep(0.01)
        return await super().complete(system, prompt, schema)


def wait_for(cond, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.02)
    return cond()


@pytest.fixture
def env(tmp_path):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    engine = Gate({"analyze": ANALYSIS, "compose": TAILORED, "repair": TAILORED,
                   "propose_evidence": {"proposals": [{"question_id": "q1", "target": "acme-bank", "text": "Ran EKS clusters.",
                                                       "skills": []}]}})
    store = Store(private)
    client = client_for(create_app(store, engine))
    with client:  # one event loop for the whole test: tasks outlive the request that started them
        engine.open.set()
        app_id = client.post("/api/applications", json={"jd": JD, "company": "Example Capital", "role": "Lead"}).json()["id"]
        client.post(f"/api/applications/{app_id}/analyze")
        client.delete(f"/api/applications/{app_id}/task")  # the page has shown the analysis
        engine.open.clear()
        engine.waiting.clear()
        try:
            yield client, store, engine, app_id
        finally:
            engine.open.set()  # never leave a step waiting: the client's event loop must be able to close


def in_background(fn):
    """Start a request the way a page does, then 'leave' it: the test keeps going without its answer."""
    out = {}
    thread = threading.Thread(target=lambda: out.setdefault("response", fn()), daemon=True)
    thread.start()
    return thread, out


def task(client, app_id):
    return client.get(f"/api/applications/{app_id}").json()["task"]


def test_a_running_step_is_found_again_and_not_started_twice(env):
    client, store, engine, app_id = env
    thread, out = in_background(lambda: client.post(f"/api/applications/{app_id}/compose", json={}))
    assert engine.waiting.wait(5)
    t = task(client, app_id)
    assert (t["kind"], t["status"], t["label"]) == ("compose", "running", "Composing your tailored resume")
    assert client.get("/api/applications").json()[0]["task"]["status"] == "running"  # the board shows it
    assert [x["kind"] for x in client.get("/api/tasks").json()] == ["compose"]

    again = client.post(f"/api/applications/{app_id}/compose", json={})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "running"
    assert client.post(f"/api/applications/{app_id}/critique").status_code == 409  # one AI step per application

    engine.open.set()
    thread.join(5)
    assert out["response"].status_code == 200 and store.tailored(app_id) is not None
    assert task(client, app_id)["status"] == "done"  # kept until the page has shown it…
    assert client.delete(f"/api/applications/{app_id}/task").status_code == 204
    assert task(client, app_id) is None  # …then forgotten


def test_stop_ends_the_step_and_saves_nothing(env):
    client, store, engine, app_id = env
    thread, out = in_background(lambda: client.post(f"/api/applications/{app_id}/compose", json={}))
    assert engine.waiting.wait(5)
    stopped = client.post(f"/api/applications/{app_id}/task/stop").json()["task"]
    assert stopped["status"] == "stopped"
    thread.join(5)
    assert out["response"].status_code == 409 and out["response"].json()["detail"]["code"] == "stopped"
    assert store.tailored(app_id) is None  # nothing was saved
    client.delete(f"/api/applications/{app_id}/task")
    engine.open.set()
    assert client.post(f"/api/applications/{app_id}/compose", json={}).status_code == 200  # free to start again


def test_a_suggestion_waits_for_the_page_that_left(env):
    """Evidence drafted from gap answers is never saved by itself: it waits in the task until it's seen."""
    client, store, engine, app_id = env
    answers = [{"question_id": "q1", "question": "Any K8s?", "answer": "Ran EKS at Acme."}]
    thread, _ = in_background(lambda: client.post(f"/api/applications/{app_id}/proposals", json=answers))
    assert engine.waiting.wait(5)
    engine.open.set()
    thread.join(5)  # the page that asked is gone; its answer was never read
    t = task(client, app_id)
    assert t["status"] == "done" and t["result"][0]["text"] == "Ran EKS clusters."
    assert "result" not in client.get("/api/tasks").json()[0]  # only the application's own page gets it


def test_a_failed_step_says_why_when_you_come_back(env):
    client, store, engine, app_id = env
    engine.responses["compose"] = {"not": "a resume"}
    engine.open.set()
    assert client.post(f"/api/applications/{app_id}/compose", json={}).status_code == 502
    t = task(client, app_id)
    assert t["status"] == "failed" and "invalid resume" in t["error"]


def test_an_analysis_that_names_the_application_is_found_under_its_new_name(env):
    client, store, engine, _ = env
    engine.open.set()
    placeholder = client.post("/api/applications", json={"jd": JD}).json()["id"]  # company not known yet
    engine.open.clear()
    engine.waiting.clear()
    thread, out = in_background(lambda: client.post(f"/api/applications/{placeholder}/analyze"))
    assert engine.waiting.wait(5)
    engine.open.set()
    thread.join(5)
    new_id = out["response"].json()["id"]
    assert new_id != placeholder and task(client, new_id)["status"] == "done"
    assert task(client, placeholder)["kind"] == "analyze"  # the old link leads to the same application


def test_restore_waits_while_an_ai_step_runs(env):
    client, store, engine, app_id = env
    thread, _ = in_background(lambda: client.post(f"/api/applications/{app_id}/compose", json={}))
    assert engine.waiting.wait(5)
    r = client.post("/api/restore", content=b"PK\x05\x06" + b"\0" * 18)
    assert r.status_code == 409 and "busy" in r.json()["detail"]
    engine.open.set()
    thread.join(5)
