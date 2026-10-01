"""Freeze-on-applied (exact sent copies) and profile/knowledge history with restore."""

import shutil
import stat
from pathlib import Path

import pytest
import yaml

from autocv import pdf as pdfmod
from autocv.api import create_app
from autocv.engine import FakeEngine
from autocv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
JD = "# Detection Lead — Example Capital\n\n" + "We need a hands-on detection engineering lead. " * 10
TAILORED = yaml.safe_load((FIX / "tailored.yaml").read_text())
ANALYSIS = {"company": "Example Capital", "role": "Lead", "industry": "quant", "track": "ic", "seniority": "S",
            "location": "SG", "summary": "x", "requirements": [], "keywords": [], "known_gaps": [], "questions": []}


@pytest.fixture
def env(tmp_path, monkeypatch):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    shutil.copy(FIX / "tailored.yaml", private / "source" / "base_tailored.yaml")
    pages = {"n": 2}

    def fake_to_pdf(docx, pdf=None, timeout=0):  # stands in for Word
        out = pdf or docx.with_suffix(".pdf")
        out.write_bytes(b"%PDF-1.4 stand-in")
        return out
    monkeypatch.setattr(pdfmod, "to_pdf", fake_to_pdf)
    monkeypatch.setattr(pdfmod, "page_count", lambda p: pages["n"])
    engine = FakeEngine({"analyze": ANALYSIS, "compose": TAILORED, "repair": TAILORED,
                         "learn_preferences": {"preferences": [{"text": "Prefer plain verbs.", "rationale": "x"}]}})
    store = Store(private)
    client = client_for(create_app(store, engine))
    app_id = client.post("/api/applications", json={"jd": JD, "company": "Example Capital", "role": "Lead"}).json()["id"]
    client.post(f"/api/applications/{app_id}/analyze")
    client.post(f"/api/applications/{app_id}/compose", json={})
    return client, store, app_id, pages


# ---- freeze on applied ---------------------------------------------------------------------

def test_applying_without_a_pdf_asks_to_build(env):
    client, store, app_id, _ = env
    res = client.patch(f"/api/applications/{app_id}", json={"status": "applied"})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "needs_build"
    assert store.meta(app_id)["status"] != "applied" and store.sent_copies(app_id) == []


def test_build_and_freeze_records_exactly_what_was_sent(env):
    client, store, app_id, _ = env
    data = client.post(f"/api/applications/{app_id}/freeze?build=true&mark_applied=true").json()
    assert data["meta"]["status"] == "applied"
    (sent,) = data["sent"]
    assert sent["reason"] == "applied" and sent["company"] == "Example Capital"
    assert set(sent["files"]) == {"Jane_Example_Resume.docx", "Jane_Example_Resume.pdf", "jd.md", "tailored.yaml", "analysis.yaml"}
    folder = store.sent_dir(app_id) / sent["id"]
    for f in folder.iterdir():
        assert not f.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH), f  # read-only
    # the frozen tailored resume matches what was built
    assert (folder / "tailored.yaml").read_bytes() == (store.app_path(app_id) / "tailored.yaml").read_bytes()


def test_a_stale_pdf_is_never_frozen(env):
    client, store, app_id, _ = env
    client.post(f"/api/applications/{app_id}/build")
    t = client.get(f"/api/applications/{app_id}").json()["tailored"]
    t["highlights"][0]["text"] = "Cut false positives by over 65%."
    client.put(f"/api/applications/{app_id}/tailored", json=t)
    res = client.post(f"/api/applications/{app_id}/freeze")
    assert res.status_code == 409 and "out of date" in res.json()["detail"]["message"]


def test_too_long_pdf_is_not_frozen(env):
    client, store, app_id, pages = env
    pages["n"] = 3
    res = client.post(f"/api/applications/{app_id}/freeze?build=true&mark_applied=true")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "too_long"
    assert store.sent_copies(app_id) == [] and store.meta(app_id)["status"] != "applied"


def test_later_rebuilds_never_touch_sent_copies(env):
    client, store, app_id, _ = env
    first = client.post(f"/api/applications/{app_id}/freeze?build=true&mark_applied=true").json()["sent"][0]
    sent_pdf = store.sent_dir(app_id) / first["id"] / "Jane_Example_Resume.pdf"
    before = sent_pdf.read_bytes()
    t = client.get(f"/api/applications/{app_id}").json()["tailored"]
    t["highlights"][0]["text"] = "Cut false positives by over 65%."
    client.put(f"/api/applications/{app_id}/tailored", json=t)
    client.post(f"/api/applications/{app_id}/build")
    client.post(f"/api/applications/{app_id}/freeze")          # a second, manual copy
    sent = client.get(f"/api/applications/{app_id}").json()["sent"]
    assert [c["reason"] for c in sent] == ["manual copy", "applied"]  # newest first
    assert sent_pdf.read_bytes() == before


def test_sent_files_download_and_paths_are_confined(env):
    client, store, app_id, _ = env
    snap = client.post(f"/api/applications/{app_id}/freeze?build=true").json()["sent"][0]["id"]
    assert client.get(f"/api/applications/{app_id}/sent/{snap}/Jane_Example_Resume.pdf").status_code == 200
    assert client.get(f"/api/applications/{app_id}/sent/{snap}/tailored.yaml").status_code == 404
    assert client.get(f"/api/applications/{app_id}/sent/{snap}/..%2F..%2Fjd.md").status_code == 404
    assert client.get(f"/api/applications/{app_id}/sent/../meta.json").status_code == 404


def test_tracker_shows_latest_sent_copy_and_delete_still_works(env):
    client, store, app_id, _ = env
    client.post(f"/api/applications/{app_id}/freeze?build=true&mark_applied=true")
    (row,) = client.get("/api/applications").json()
    assert row["sent"]["reason"] == "applied"
    assert client.delete(f"/api/applications/{app_id}").status_code == 204   # read-only files included
    assert not (store.apps_dir / app_id).exists()


def test_reveal_a_sent_copy(env, monkeypatch):
    import subprocess
    client, store, app_id, _ = env
    snap = client.post(f"/api/applications/{app_id}/freeze?build=true").json()["sent"][0]["id"]
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    assert client.post(f"/api/applications/{app_id}/reveal?snapshot={snap}").status_code == 204
    assert f"/sent/{snap}/" in calls[0][-1]
    assert client.post(f"/api/applications/{app_id}/reveal?snapshot=nope").status_code == 404


# ---- profile & knowledge history -------------------------------------------------------------

def causes(client, kind):
    return [h["cause"] for h in client.get(f"/api/history/{kind}").json()]


def test_every_save_path_keeps_the_previous_version(env):
    client, store, app_id, _ = env
    loaded = client.get("/api/profile").json()
    client.put("/api/profile", json=loaded["profile"], headers={"If-Match": loaded["version"]})  # identical
    assert causes(client, "profile") == []                                                      # → no snapshot
    client.post("/api/profile/evidence", json={"target": "acme-bank", "text": "Approved fact."})
    loaded = client.get("/api/profile").json()
    loaded["profile"]["vocabulary"].append("Singapore")
    client.put("/api/profile", json=loaded["profile"], headers={"If-Match": loaded["version"]})
    y = client.get("/api/profile/yaml").json()
    client.put("/api/profile/yaml", json={"yaml": y["yaml"].replace("Singapore", "Hong Kong")},
               headers={"If-Match": y["version"]})
    assert causes(client, "profile") == ["yaml edit", "profile editor", "evidence approved"]

    put = lambda status: client.put(f"/api/applications/{app_id}/answers", json=[  # noqa: E731
        {"question_id": "q1", "requirement": "K8s", "question": "Any K8s?", "status": status}])
    put("no_experience")
    put("draft")
    assert causes(client, "knowledge") == ["gap answer"]  # first save created the file; the retraction kept it


def test_restore_round_trip_is_undoable_and_never_reuses_ids(env):
    client, store, app_id, _ = env
    new_id = client.post("/api/profile/evidence", json={"target": "acme-bank", "text": "Approved fact."}).json()["id"]
    (before_add,) = client.get("/api/history/profile").json()
    diff = client.get(f"/api/history/profile/{before_add['id']}").json()
    assert any(new_id in line and "added since" in line for line in diff["summary"])
    assert "+  - id: acme-bank.a3" in diff["diff"] or "acme-bank.a3" in diff["diff"]

    restored = client.post(f"/api/history/profile/{before_add['id']}/restore").json()
    assert new_id not in restored["evidence"]                           # back to the earlier version
    assert new_id in restored["profile"]["retired_ids"]                 # …and its id stays retired
    assert causes(client, "profile")[0].startswith("restore")           # restore itself is undoable
    again = client.post("/api/profile/evidence", json={"target": "acme-bank", "text": "Another fact."}).json()["id"]
    assert again != new_id


def test_history_ids_are_confined(env):
    client, _, _, _ = env
    assert client.get("/api/history/profile/..%2F..%2Fprofile").status_code == 404
    assert client.get("/api/history/secrets").status_code == 404
    assert client.post("/api/history/profile/nope/restore").status_code == 404
