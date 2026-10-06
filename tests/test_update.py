"""Update checks (PyPI, at most daily, never when off) and the one-click upgrade that restarts TailorbirdCV."""

import asyncio
import json
import shutil
import time
from pathlib import Path

import httpx
import pytest

from tailorbirdcv import cli, oscompat, update
from tailorbirdcv.api import create_app
from tailorbirdcv.engine import FakeEngine
from tailorbirdcv.store import Store
from tailorbirdcv.update import fetch_latest as real_fetch_latest  # conftest replaces it with an offline stub
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent


def test_the_version_file_is_the_package_version():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert update.VERSION_RE.match(version)
    assert update.current() == version


@pytest.mark.parametrize("latest,installed,expected", [
    ("1.0.3", "1.0.2", True), ("1.10.0", "1.9.9", True), ("2.0.0", "1.99.99", True),
    ("1.0.2", "1.0.2", False), ("1.0.1", "1.0.2", False),
    ("1.0.3", "dev", False), (None, "1.0.2", False), ("1.0", "0.9.0", False), ("1.0.3rc1", "1.0.2", False),
])
def test_newer(latest, installed, expected):
    assert update.newer(latest, installed) is expected


def receipt(tmp_path, requirement: str) -> Path:
    (tmp_path / "uv-receipt.toml").write_text(f"[tool]\nrequirements = [{requirement}]\npython = \"3.13\"\n",
                                              encoding="utf-8")
    return tmp_path


def test_install_kind(tmp_path, monkeypatch):
    for d in "abc":
        (tmp_path / d).mkdir()
    assert update.install_kind(receipt(tmp_path / "a", '{ name = "tailorbirdcv" }')) == "uv-tool"
    assert update.install_kind(receipt(tmp_path / "b", '{ name = "tailorbirdcv", path = "/x/tailorbirdcv.whl" }')) == "uv-tool-local"
    from tailorbirdcv import paths
    monkeypatch.setattr(paths, "is_checkout", lambda: False)
    assert update.install_kind(tmp_path / "c") == "other"
    monkeypatch.setattr(paths, "is_checkout", lambda: True)
    assert update.install_kind(tmp_path / "c") == "checkout"


def pypi(version, status=200):
    def handler(request):
        assert request.url == httpx.URL(update.PYPI_URL) and request.method == "GET"
        assert request.headers["user-agent"].startswith("TailorbirdCV/")
        return httpx.Response(status, json={"info": {"version": version}})
    return httpx.MockTransport(handler)


def test_fetch_latest_reads_pypi_and_rejects_odd_answers():
    assert asyncio.run(real_fetch_latest(pypi("1.4.2"))) == "1.4.2"
    for bad in ("1.4", "1.4.2rc1", "<b>1.4.2</b>", ""):
        with pytest.raises(ValueError):
            asyncio.run(real_fetch_latest(pypi(bad)))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(real_fetch_latest(pypi("1.4.2", status=503)))


def test_checks_at_most_daily_never_when_off_and_quietly_offline(tmp_path, monkeypatch):
    refresh = lambda **kw: asyncio.run(update.refresh(tmp_path, **kw))  # noqa: E731
    calls = []

    async def fetch(transport=None):
        calls.append(1)
        return "1.4.2"
    monkeypatch.setattr(update, "fetch_latest", fetch)
    assert refresh(enabled=False) == {} and calls == []  # off: never asks
    assert refresh(enabled=True)["latest"] == "1.4.2" and len(calls) == 1
    refresh(enabled=True)
    assert len(calls) == 1  # cached for a day
    refresh(enabled=True, force=True)
    assert len(calls) == 2  # "Check now"
    cache = update.load(tmp_path)
    cache["checked_at"] = "2020-01-01T00:00:00+00:00"
    update.save(tmp_path, cache)

    async def offline(transport=None):
        raise httpx.ConnectError("no network")
    monkeypatch.setattr(update, "fetch_latest", offline)
    cache = refresh(enabled=True)
    assert cache["latest"] == "1.4.2" and "Couldn't reach PyPI" in cache["error"]  # the last answer is kept


# ---- API -----------------------------------------------------------------------------------------------
@pytest.fixture
def env(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    app = create_app(Store(private), FakeEngine({}))

    async def latest(transport=None):
        return "9.9.9"
    monkeypatch.setattr(update, "fetch_latest", latest)
    monkeypatch.setattr(update, "find_uv", lambda: "/home/me/.local/bin/uv")
    return client_for(app), app, private


def test_status_and_upgrade_refusals(env, monkeypatch):
    client, app, private = env
    s = client.get("/api/update").json()
    assert s["enabled"] and s["latest"] == "9.9.9" and s["newer"] and s["current"] == update.current()
    assert s["kind"] == "checkout" and "git pull" in s["command"] and s["upgrading"] is None
    r = client.post("/api/update/upgrade")
    assert r.status_code == 409 and "one-line installer" in r.json()["detail"]  # a checkout upgrades by hand

    monkeypatch.setattr(update, "install_kind", lambda prefix=None: "uv-tool")
    r = client.post("/api/update/upgrade")
    assert r.status_code == 409 and "tailorbirdcv serve" in r.json()["detail"]  # not started by `tailorbirdcv serve`

    exits = []
    app.state.request_exit = lambda: exits.append(1)
    app.state.busy = 1  # another request still running
    r = client.post("/api/update/upgrade")
    assert r.status_code == 409 and "busy" in r.json()["detail"]
    app.state.busy = 0
    monkeypatch.setattr(update, "find_uv", lambda: None)
    assert "uv" in client.post("/api/update/upgrade").json()["detail"]
    assert exits == [] and app.state.upgrade is None and "pending" not in update.load(private)


def test_nothing_newer_and_checks_off(env, monkeypatch):
    client, app, private = env
    monkeypatch.setattr(update, "install_kind", lambda prefix=None: "uv-tool")
    app.state.request_exit = lambda: None

    async def same(transport=None):
        return update.current()
    monkeypatch.setattr(update, "fetch_latest", same)
    r = client.post("/api/update/upgrade")
    assert r.status_code == 409 and "latest version" in r.json()["detail"]
    client.put("/api/settings", json={"update_check": False})
    s = client.get("/api/update").json()
    assert s["enabled"] is False and s["latest"] is None and s["newer"] is False
    assert client.post("/api/update/check").status_code == 409


def test_an_accepted_upgrade_records_it_and_stops_the_server(env, monkeypatch):
    client, app, private = env
    monkeypatch.setattr(update, "install_kind", lambda prefix=None: "uv-tool")
    exits = []
    app.state.request_exit = lambda: exits.append(1)
    with client:  # keeps the event loop running between requests, like a real server
        r = client.post("/api/update/upgrade")
        assert r.status_code == 202 and r.json()["upgrading"] == "9.9.9"
        assert app.state.upgrade == {"target": "9.9.9", "uv": "/home/me/.local/bin/uv"}
        assert update.load(private)["pending"]["target"] == "9.9.9"
        deadline = time.monotonic() + 3
        while not exits and time.monotonic() < deadline:
            time.sleep(0.05)
    assert exits == [1]  # once the answer has gone out


def test_the_next_start_says_whether_the_upgrade_took(tmp_path):
    update.mark_pending(tmp_path, update.current())
    update.settle(tmp_path)
    assert update.load(tmp_path)["last_upgrade"]["ok"] is True and "pending" not in update.load(tmp_path)
    update.mark_pending(tmp_path, "99.0.0")
    update.settle(tmp_path)
    last = update.load(tmp_path)["last_upgrade"]
    assert last["ok"] is False and last["target"] == "99.0.0" and "still running" in last["error"]


# ---- restart -------------------------------------------------------------------------------------------
class FakeProc:
    def __init__(self, code, out="Updated tailorbirdcv v0.2.0 -> v9.9.9\n"):
        self.stdout, self.code = iter([out]), code

    def wait(self):
        return self.code


@pytest.mark.parametrize("code", [0, 2])
def test_posix_restart_upgrades_then_execs_on_the_same_port(tmp_path, monkeypatch, capsys, code):
    seen = {}
    monkeypatch.setattr(cli, "PRIVATE", tmp_path)
    monkeypatch.setattr(cli, "IS_WINDOWS", False)
    monkeypatch.setattr(cli.sys, "argv", ["/home/me/.local/bin/tailorbirdcv", "serve", "--port", "8010"])

    def popen(cmd, env, **kw):
        seen["cmd"], seen["env"] = cmd, env
        return FakeProc(code)
    monkeypatch.setattr("subprocess.Popen", popen)
    monkeypatch.setattr(cli.os, "execv", lambda path, argv: seen.update(exec=(path, argv)))
    cli.restart_after_upgrade({"target": "9.9.9", "uv": "/home/me/.local/bin/uv"}, 8010)
    assert seen["cmd"] == ["/home/me/.local/bin/uv", "tool", "upgrade", "tailorbirdcv"]
    assert seen["env"]["UV_MANAGED_PYTHON"] == "1" and seen["env"]["UV_SYSTEM_CERTS"]
    # the old version starts again too if the upgrade failed: the next start reports it
    assert seen["exec"] == ("/home/me/.local/bin/tailorbirdcv",
                            ["/home/me/.local/bin/tailorbirdcv", "serve", "--port", "8010", "--no-browser"])
    assert "v9.9.9" in update.log_path(tmp_path).read_text(encoding="utf-8")
    assert ("Upgraded" if code == 0 else "failed") in capsys.readouterr().out


def test_nothing_to_install_is_said_plainly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "PRIVATE", tmp_path)
    monkeypatch.setattr(cli, "IS_WINDOWS", False)
    monkeypatch.setattr(cli.sys, "argv", ["/home/me/.local/bin/tailorbirdcv"])
    monkeypatch.setattr("subprocess.Popen", lambda cmd, env, **kw: FakeProc(0, "Nothing to upgrade\n"))
    monkeypatch.setattr(cli.os, "execv", lambda *a: None)
    cli.restart_after_upgrade({"target": "9.9.9", "uv": "uv"}, 8000)
    out = capsys.readouterr().out
    assert "nothing newer" in out and "Upgraded" not in out


def test_windows_restart_hands_over_to_a_helper_in_a_new_window(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "PRIVATE", tmp_path)
    monkeypatch.setattr(cli, "IS_WINDOWS", True)
    monkeypatch.setattr(cli.sys, "argv", [r"C:\Users\Me Too\.local\bin\tailorbirdcv.exe", "serve"])
    monkeypatch.setattr(cli.os.path, "isabs", lambda p: True)
    monkeypatch.setattr(oscompat, "spawn_new_console", lambda cmd, env: seen.update(cmd=cmd, env=env))
    monkeypatch.setattr(cli.os, "execv", lambda *a: pytest.fail("Windows must not exec"))
    assert cli.restart_after_upgrade({"target": "9.9.9", "uv": r"C:\Users\Me Too\.local\bin\uv.exe"}, 8010) == 0
    script = tmp_path / "update" / "upgrade.ps1"
    text = script.read_bytes()
    text.decode("ascii")  # Windows PowerShell 5.1 reads it however it's saved
    assert b"9.9.9" not in text and b"8010" not in text and b"Me Too" not in text  # values only via env vars
    assert seen["cmd"][:2] == ["powershell", "-NoProfile"] and seen["cmd"][-1] == str(script)
    env = seen["env"]
    assert env["TAILORBIRDCV_UPGRADE_TARGET"] == "9.9.9" and env["TAILORBIRDCV_UPGRADE_PORT"] == "8010"
    assert env["TAILORBIRDCV_UPGRADE_UV"].endswith("uv.exe") and env["TAILORBIRDCV_UPGRADE_EXE"].endswith("tailorbirdcv.exe")
    assert env["TAILORBIRDCV_UPGRADE_PID"].isdigit() and env["UV_MANAGED_PYTHON"] == "1"


def test_update_json_is_private_data(tmp_path):
    update.save(tmp_path, {"latest": "1.0.0"})
    assert json.loads((tmp_path / "update.json").read_text(encoding="utf-8")) == {"latest": "1.0.0"}
