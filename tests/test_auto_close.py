"""Settings → Applications → close applications with no response after N days (off by default)."""

import datetime as dt
import shutil
from pathlib import Path

import pytest

from tailorbirdcv.api import create_app
from tailorbirdcv.engine import FakeEngine
from tailorbirdcv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
JD = "# Platform Engineer\n\n" + "We need a hands-on platform engineer to run our payment services. " * 8
NOW = dt.datetime(2026, 12, 10, 9, 0)


@pytest.fixture
def env(tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    store = Store(private)
    return client_for(create_app(store, FakeEngine({}))), store


def app(client, store, company, status, applied_days_ago=None, now=NOW):
    app_id = client.post("/api/applications", json={"jd": JD, "company": company, "role": "Engineer"}).json()["id"]
    milestones = {"applied": (now - dt.timedelta(days=applied_days_ago)).isoformat(timespec="seconds")} \
        if applied_days_ago is not None else {}
    store.update_meta(app_id, status=status, milestones=milestones)
    return app_id


def test_it_is_off_by_default(env):
    client, store = env
    assert store.settings()["auto_close"] == {"enabled": False, "days": 60}
    old = app(client, store, "Northwind", "applied", 400)
    client.get("/api/applications")
    assert store.meta(old)["status"] == "applied"


def test_only_applied_ones_past_the_wait_are_closed_as_no_response(env):
    client, store = env
    old = app(client, store, "Northwind", "applied", 61)
    recent = app(client, store, "Contoso", "applied", 59)
    interview = app(client, store, "Fabrikam", "interview", 90)
    draft = app(client, store, "Litware", "built")
    assert store.auto_close(60, NOW) == [old]
    meta = store.meta(old)
    assert (meta["status"], meta["outcome"], meta["auto_close_days"]) == ("closed", "no_response", 60)
    assert meta["auto_closed"].startswith("2026-12-10")
    assert store.reached(old)[0] == "applied"  # the stage it reached stays: Results still counts it as applied
    assert [store.meta(i)["status"] for i in (recent, interview, draft)] == ["applied", "interview", "built"]


def test_a_reopened_one_is_never_closed_again(env):
    client, store = env
    old = app(client, store, "Northwind", "applied", 90)
    store.auto_close(60, NOW)
    store.set_status(old, "applied")  # the user reopened it: they heard back, or want to keep it open
    assert store.auto_close(60, NOW + dt.timedelta(days=30)) == []
    assert store.meta(old)["status"] == "applied"


def test_the_setting_is_validated_and_the_list_runs_the_sweep(env):
    client, store = env
    assert client.put("/api/settings", json={"auto_close": {"days": 3}}).status_code == 422
    assert client.put("/api/settings", json={"auto_close": {"days": 400}}).status_code == 422
    r = client.put("/api/settings", json={"auto_close": {"enabled": True, "days": 30}})
    assert r.status_code == 200 and r.json()["auto_close"] == {"enabled": True, "days": 30}
    assert client.put("/api/settings", json={"auto_close": {"days": 45}}).json()["auto_close"] == {"enabled": True, "days": 45}
    old = app(client, store, "Northwind", "applied", 46, now=dt.datetime.now())  # the API sweeps at the real time
    row = next(a for a in client.get("/api/applications").json() if a["id"] == old)
    assert row["status"] == "closed" and row["outcome"] == "no_response" and row["auto_closed"]
