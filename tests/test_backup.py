"""Backup and restore (backup.py): the user's data as one .zip, restored on another computer or after a
mistake, safely. Fictional data only."""

import io
import json
import os
import shutil
import stat
import zipfile
from pathlib import Path

import pytest

from tailorbirdcv import apikey, backup, cli
from tailorbirdcv.api import create_app
from tailorbirdcv.engine import FakeEngine
from tailorbirdcv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
JD = "# Platform Engineer\n\n" + "We need a hands-on platform engineer to run our payment services. " * 8
KEY = "sk-ant-" + "x" * 40


def data_store(root: Path) -> tuple[Store, str]:
    """A data folder with a profile, its history, settings, an application with a sent (read-only) copy, and
    this computer's own files, which must never travel."""
    private = root / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    shutil.copy(FIX / "tailored.yaml", private / "source" / "base_tailored.yaml")
    store = Store(private)
    store.save_settings({**store.settings(), "theme": "modern"})
    app_id = store.create_app("Northwind", "Engineer", JD, "https://northwind.example/jobs/1")
    sent = store.app_path(app_id) / "sent" / "20261001-120000"
    sent.mkdir(parents=True)
    (sent / "Jane_Example_Resume.pdf").write_bytes(b"%PDF-1.4 sent\n")
    (sent / "Jane_Example_Resume.pdf").chmod(0o444)
    (private / "history" / "profile").mkdir(parents=True)
    (private / "history" / "profile" / "20260101-000000-000000__edit.yaml").write_text("old: profile\n")
    store.access_key()
    for machine in ("word/x.docx", "libreoffice/user/registrymodifications.xcu", "update.json", "calibration.json"):
        (private / machine).parent.mkdir(parents=True, exist_ok=True)
        (private / machine).write_text("this computer only")
    (private / "applications" / ".profile.yaml.abc.tmp").write_text("half-written")
    return store, app_id


def test_a_backup_restores_everything_on_another_computer(tmp_path):
    old, app_id = data_store(tmp_path / "old")
    zip_path = tmp_path / "TailorbirdCV-backup.zip"
    info = backup.create(old, zip_path)
    assert info["keys"] == [] and info["files"] >= 6
    names = zipfile.ZipFile(zip_path).namelist()
    assert "data/profile.yaml" in names and backup.MANIFEST in names and backup.KEYS not in names
    assert not any(n.startswith(("data/word", "data/libreoffice", "data/update", "data/calibration", "data/.access"))
                   or n.endswith(".tmp") for n in names)  # this computer's files stay here

    new = Store(tmp_path / "new" / "private")  # a fresh install: no profile yet
    new.private.mkdir(parents=True)
    new_key = new.access_key()
    result = backup.restore(new, zip_path)
    assert result["applications"] == 1 and result["kept"] is None
    for rel in ("profile.yaml", "settings.json", "source/base_tailored.yaml",
                "history/profile/20260101-000000-000000__edit.yaml"):
        assert (new.private / rel).read_bytes() == (old.private / rel).read_bytes(), rel
    assert new.settings()["theme"] == "modern" and new.meta(app_id)["company"] == "Northwind"
    sent = new.app_path(app_id) / "sent" / "20261001-120000" / "Jane_Example_Resume.pdf"
    assert sent.read_bytes() == b"%PDF-1.4 sent\n"
    if os.name != "nt":
        assert not sent.stat().st_mode & stat.S_IWUSR  # what was sent stays read-only
    assert new.access_key() == new_key  # the new computer keeps its own access key
    assert not any(p.name.startswith(".restore") for p in new.private.iterdir())


def test_restoring_over_existing_data_keeps_it_aside(tmp_path):
    old, _ = data_store(tmp_path / "old")
    zip_path = tmp_path / "b.zip"
    backup.create(old, zip_path)
    current = Store(tmp_path / "current" / "private")
    (current.private).mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", current.private / "profile.yaml")
    (current.private / "knowledge.yaml").write_text("mine: true\n")
    result = backup.restore(current, zip_path)
    kept = current.private / result["kept"]
    assert result["kept"].startswith(f"{backup.KEPT}/") and (kept / "knowledge.yaml").read_text() == "mine: true\n"
    assert not (current.private / "knowledge.yaml").exists()  # the backup had none: the current one moved aside
    backup.create(current, tmp_path / "again.zip")  # what was kept aside is never part of the next backup
    assert not any(n.startswith(f"data/{backup.KEPT}") for n in zipfile.ZipFile(tmp_path / "again.zip").namelist())


def test_api_keys_travel_only_when_asked(tmp_path, memory_keyring):
    store, _ = data_store(tmp_path / "old")
    apikey.save(KEY, "anthropic")
    backup.create(store, tmp_path / "plain.zip")
    assert backup.KEYS not in zipfile.ZipFile(tmp_path / "plain.zip").namelist()
    assert backup.create(store, tmp_path / "keys.zip", include_keys=True)["keys"] == ["anthropic"]
    apikey.delete("anthropic")
    result = backup.restore(Store(tmp_path / "new"), tmp_path / "keys.zip")
    assert result["keys_restored"] == ["anthropic"] and apikey.get("anthropic") == (KEY, "keychain")
    assert "API keys" in backup.warning(True) and "API keys" not in backup.warning(False)


def rewrite(src: Path, dst: Path, change) -> Path:
    """A copy of a backup with its entries changed by `change(entries: dict[name, bytes])`."""
    with zipfile.ZipFile(src) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    change(entries)
    with zipfile.ZipFile(dst, "w") as z:
        for n, data in entries.items():
            z.writestr(n, data)
    return dst


@pytest.mark.parametrize("change, message", [
    (lambda e: e.pop(backup.MANIFEST), "isn't a TailorbirdCV backup"),
    (lambda e: e.__setitem__("data/../evil.txt", b"x"), "unsafe"),
    (lambda e: e.__setitem__("data/word/x.docx", b"x"), "unsafe"),
    (lambda e: e.__setitem__(backup.MANIFEST, json.dumps({**json.loads(e[backup.MANIFEST]), "files": {
        **json.loads(e[backup.MANIFEST])["files"], "applications/./x.txt": {"size": 1, "sha256": "0"}}}).encode()),
     "unsafe"),
    (lambda e: e.__setitem__("data/profile.yaml", e["data/profile.yaml"] + b"\n# changed"), "checksum"),
    (lambda e: e.pop("data/settings.json"), "incomplete"),
    (lambda e: e.__setitem__(backup.MANIFEST, json.dumps({**json.loads(e[backup.MANIFEST]), "format": 99}).encode()),
     "newer TailorbirdCV"),
])
def test_damaged_or_unsafe_backups_change_nothing(tmp_path, change, message):
    store, _ = data_store(tmp_path / "old")
    good = tmp_path / "good.zip"
    backup.create(store, good)
    bad = rewrite(good, tmp_path / "bad.zip", change)
    before = sorted(p.relative_to(store.private).as_posix() for p in store.private.rglob("*"))
    with pytest.raises(backup.BackupError, match=message):
        backup.restore(store, bad)
    assert sorted(p.relative_to(store.private).as_posix() for p in store.private.rglob("*")) == before
    assert not (tmp_path / "evil.txt").exists()


def test_a_profile_that_wont_load_is_never_restored(tmp_path):
    store, _ = data_store(tmp_path / "old")
    good = tmp_path / "good.zip"
    backup.create(store, good)

    def broken(entries):
        entries["data/profile.yaml"] = b"contact: [not, a, profile]\n"
        manifest = json.loads(entries[backup.MANIFEST])
        manifest["files"]["profile.yaml"]["sha256"] = backup._sha(entries["data/profile.yaml"])
        entries[backup.MANIFEST] = json.dumps(manifest).encode()
    with pytest.raises(backup.BackupError, match="profile in that backup"):
        backup.restore(store, rewrite(good, tmp_path / "bad.zip", broken))
    assert (store.private / "profile.yaml").read_bytes() == (FIX / "profile.yaml").read_bytes()


def test_not_a_zip(tmp_path):
    junk = tmp_path / "x.zip"
    junk.write_bytes(b"not a zip")
    with pytest.raises(backup.BackupError, match="isn't a .zip"):
        backup.inspect(junk)


# ---- the API and the CLI -----------------------------------------------------------------------------------
def test_download_and_restore_through_the_api(tmp_path):
    store, app_id = data_store(tmp_path / "old")
    client = client_for(create_app(store, FakeEngine({})))
    r = client.get("/api/backup")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "TailorbirdCV-backup-" in r.headers["content-disposition"] and r.headers["x-backup-keys"] == ""
    assert not any(p.name.startswith(".backup-") for p in store.private.iterdir())  # the temporary copy is gone

    fresh = Store(tmp_path / "new" / "private")
    fresh.private.mkdir(parents=True)
    other = client_for(create_app(fresh, FakeEngine({})))
    assert other.get("/api/setup").json()["has_profile"] is False
    restored = other.post("/api/restore", content=r.content, headers={"Content-Type": "application/zip"})
    assert restored.status_code == 200 and restored.json()["applications"] == 1
    assert other.get("/api/setup").json()["has_profile"] is True
    assert other.get(f"/api/applications/{app_id}").status_code == 200
    bad = other.post("/api/restore", content=b"junk", headers={"Content-Type": "application/zip"})
    assert bad.status_code == 422 and "isn't a TailorbirdCV backup" in bad.json()["detail"]


def test_restore_waits_until_nothing_else_runs(tmp_path):
    store, _ = data_store(tmp_path / "old")
    app = create_app(store, FakeEngine({}))
    client = client_for(app)
    content = client.get("/api/backup").content
    app.state.upgrade = {"target": "9.9.9"}
    assert client.post("/api/restore", content=content).status_code == 409


def test_the_cli_backs_up_and_restores(tmp_path, monkeypatch, capsys):
    store, _ = data_store(tmp_path / "old")
    monkeypatch.setattr(cli, "STORE", store)
    monkeypatch.setattr(cli, "PRIVATE", store.private)
    out = tmp_path / "cli.zip"
    assert cli.main(["backup", str(out)]) == 0
    printed = capsys.readouterr().out
    assert out.is_file() and "WARNING: Keep this backup safe" in printed and "API keys" not in printed
    fresh = Store(tmp_path / "new" / "private")
    monkeypatch.setattr(cli, "STORE", fresh)
    monkeypatch.setattr(cli, "PRIVATE", fresh.private)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert cli.main(["restore", str(out)]) == 1 and not (fresh.private / "profile.yaml").exists()
    assert cli.main(["restore", str(out), "--yes"]) == 0 and (fresh.private / "profile.yaml").exists()
