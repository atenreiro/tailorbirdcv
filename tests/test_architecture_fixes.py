"""Fixes from the architecture review: no server hang around builds, no 500 on a failing compose, Claude Code
never used on a pay-per-use login, the key link never leaves AutoCV, and the key never reaches the request log."""

import asyncio
import logging
import shutil
import threading
import time
from pathlib import Path

import pytest
import yaml

from autocv import cli
from autocv.api import create_app
from autocv.engine import ClaudeCLIEngine, EngineError, FakeEngine
from autocv.store import Store
from conftest import client_for
from test_freeze_history import ANALYSIS, JD, TAILORED, env  # noqa: F401 — application fixture with a fake PDF engine

FIX = Path(__file__).parent / "fixtures"


def in_thread(fn):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", fn()), daemon=True)
    t.start()
    return t, out


def answers_quickly(client, seconds=3.0) -> bool:
    t, out = in_thread(lambda: client.get("/api/applications"))
    t.join(seconds)
    return "r" in out and out["r"].status_code == 200


# ---- 1. the server never stalls waiting for a build -------------------------------------------------------
def test_freeze_waits_for_a_build_without_stalling_the_server(env):  # noqa: F811
    client, store, app_id, _ = env
    lock = store.app_lock(app_id)
    with client:  # one event loop for every request, as in the real server
        lock.acquire()  # a build of this application is running
        try:
            t, out = in_thread(lambda: client.post(f"/api/applications/{app_id}/freeze"))
            time.sleep(0.3)
            assert answers_quickly(client), "the server stalled while freeze waited for the build"
        finally:
            lock.release()
        t.join(10)
    assert out["r"].status_code in (200, 409)  # 409: nothing built yet; what matters is that it answered


def test_marking_applied_takes_the_application_lock_before_the_store_lock(env):  # noqa: F811
    client, store, app_id, _ = env
    lock = store.app_lock(app_id)
    with client:
        lock.acquire()
        try:
            t, out = in_thread(lambda: client.patch(f"/api/applications/{app_id}", json={"status": "applied"}))
            time.sleep(0.3)
            # It waits for the build without holding the store lock (the build needs that lock to finish).
            assert store.lock.acquire(timeout=2), "the status change held the store lock while waiting"
            store.lock.release()
            assert answers_quickly(client)
        finally:
            lock.release()
        t.join(10)
    assert out["r"].status_code in (200, 409)


# ---- 2. a draft that fails the fact-check never turns compose into a 500 ------------------------------------
def test_compose_with_unknown_ids_reports_instead_of_crashing(tmp_path):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    bad = yaml.safe_load((FIX / "tailored.yaml").read_text(encoding="utf-8"))
    bad["experience"][0]["role"] = "no-such-role"  # a fallback engine path can return an id outside the schema enum
    client = client_for(create_app(Store(private), FakeEngine({"analyze": ANALYSIS, "compose": bad, "repair": bad})))
    app_id = client.post("/api/applications", json={"jd": JD, "company": "Example Capital", "role": "Lead"}).json()["id"]
    client.post(f"/api/applications/{app_id}/analyze")
    r = client.post(f"/api/applications/{app_id}/compose", json={})
    assert r.status_code == 200, r.text
    assert r.json()["report"]["ok"] is False and r.json()["length"] is None
    assert client.get(f"/api/applications/{app_id}").status_code == 200


# ---- 3. Claude Code is never used on a login that bills per use ---------------------------------------------
class FakeClaude(ClaudeCLIEngine):
    def __init__(self, login):
        super().__init__(binary="claude")
        self.login, self.calls = login, []

    async def _run(self, args, stdin=None, timeout=None, files=None):
        self.calls.append(args[:2])
        if args[:2] == ["auth", "status"]:
            if isinstance(self.login, Exception):
                raise self.login
            return self.login
        return '{"structured_output": {"ok": true}}'


@pytest.mark.parametrize("login,refused", [
    ('{"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "firstParty"}', None),
    ('{"loggedIn": true, "authMethod": "console", "apiProvider": "firstParty"}', "Console"),
    ('{"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "bedrock"}', "bedrock"),
    ('{"loggedIn": false}', "Not logged in"),
    (EngineError("auth status isn't supported by this version"), None),  # unreadable: let the call go ahead
])
def test_claude_code_refuses_pay_per_use_logins(login, refused):
    engine = FakeClaude(login)
    if refused:
        with pytest.raises(EngineError, match=refused):
            asyncio.run(engine.complete("system", "prompt", {}))
        assert ["-p", "--output-format"] not in engine.calls  # never ran the prompt
    else:
        assert asyncio.run(engine.complete("system", "prompt", {})) == {"ok": True}
        asyncio.run(engine.complete("system", "prompt", {}))
        assert engine.calls.count(["auth", "status"]) == 1  # checked once a minute, not per call


# ---- 4. the private link only ever redirects within AutoCV ---------------------------------------------------
@pytest.mark.parametrize("path,expected", [
    ("//evil.example/?key=wrong", "/evil.example/"),
    ("/%5Cevil.example/?key=wrong", "/evil.example/"),
    ("/settings?key=wrong&next=a b&x=<y>", "/settings?next=a+b&x=%3Cy%3E"),
    ("/api/profile?key=wrong&x=1", "/"),
])
def test_the_key_link_never_redirects_to_another_site(tmp_path, path, expected):
    private = tmp_path / "private"
    private.mkdir()
    client = client_for(create_app(Store(private), FakeEngine({})))
    r = client.get("http://127.0.0.1" + path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == expected


# ---- 5. the request log never shows the key -----------------------------------------------------------------
def test_the_request_log_masks_the_key():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:5000", "GET", "/?key=S3cr3t-k3y_x&tab=board", "1.1", 303), None)
    assert cli._HideKey().filter(record) is True
    assert "S3cr3t" not in record.getMessage() and "key=•••&tab=board" in record.getMessage()
