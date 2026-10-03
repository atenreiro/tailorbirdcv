"""Applications live in applications/<company>/<yyyy-mm-dd>_<role>/ (id: <company>~<yyyy-mm-dd>_<role>);
folders from the old flat layout move there, and their old ids and stored references keep working."""

import datetime as dt
import json
import os
import shutil
import stat
from pathlib import Path

import pytest
import yaml

from autocv.store import Store

FIX = Path(__file__).parent / "fixtures"
TODAY = f"{dt.date.today():%Y-%m-%d}"
JD = "# Lead — Example Capital\n\n" + "We need a hands-on detection engineering lead. " * 10


@pytest.fixture
def store(tmp_path):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    return Store(private)


def test_new_applications_are_grouped_by_company(store):
    a = store.create_app("Example Capital", "Detection Lead", JD)
    b = store.create_app("Example Capital", "Detection Lead", JD)
    assert a == f"example-capital~{TODAY}_detection-lead" and b == f"{a}-2"
    assert store.app_path(a) == (store.apps_dir / "example-capital" / f"{TODAY}_detection-lead").resolve()
    assert [x["id"] for x in store.list_apps()] == [b, a]


@pytest.mark.parametrize("bad", ["", "no-separator", "../x~y", "a~../../profile", "a~b/c", "..~..", "a~", "~b",
                                 "example-capital~../../../etc"])
def test_ids_never_escape_the_applications_folder(store, bad):
    store.create_app("Example Capital", "Detection Lead", JD)
    with pytest.raises(KeyError):
        store.app_path(bad)


def test_rename_after_analysis_moves_the_folder_and_prunes_the_placeholder(store):
    app_id = store.create_app("company", "role", JD)
    new_id = store.rename_app(app_id, "Example Capital", "Detection Lead")
    assert new_id == f"example-capital~{TODAY}_detection-lead"
    assert not (store.apps_dir / "company").exists()
    assert store.rename_app(new_id, "Example Capital", "Detection Lead") == new_id  # already in place


def _old_style(store, name, company, role, status="applied"):
    folder = store.apps_dir / name
    (folder / "sent" / "2026-10-01_120000").mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"company": company, "role": role, "status": status,
                                                  "created": "2026-10-01T10:00:00"}))
    (folder / "jd.md").write_text(JD)
    (folder / "Jane_Example_Resume.pdf").write_bytes(b"%PDF-1.4")
    sent = folder / "sent" / "2026-10-01_120000" / "Jane_Example_Resume.pdf"
    sent.write_bytes(b"%PDF-1.4 sent")
    os.chmod(sent, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # sent copies are read-only
    return name


def test_old_flat_folders_move_and_old_ids_keep_working(store):
    old = _old_style(store, "2026-10-01_northwind_platform-engineer", "Northwind", "Platform Engineer")
    old2 = _old_style(store, "2026-10-01_contoso-bank_risk-analyst", "Contoso Bank", "Risk Analyst")
    (store.private / "knowledge.yaml").write_text(yaml.safe_dump({
        "answers": [{"id": "k1", "topic": "K8s", "question": "Any K8s?", "answer": "", "kind": "no_experience",
                     "app_id": old, "company": "Northwind", "date": "2026-10-01"}],
        "preferences": [{"id": "p1", "text": "Plain verbs.", "rationale": "x", "status": "proposed",
                         "source_app": old2, "date": "2026-10-01"}]}))

    moved = store.migrate_layout()
    new = "northwind~2026-10-01_platform-engineer"
    assert moved == {old: new, old2: "contoso-bank~2026-10-01_risk-analyst"}
    assert not (store.apps_dir / old).exists()
    path = store.apps_dir / "northwind" / "2026-10-01_platform-engineer"
    assert (path / "Jane_Example_Resume.pdf").exists()
    assert (path / "sent" / "2026-10-01_120000" / "Jane_Example_Resume.pdf").read_bytes() == b"%PDF-1.4 sent"
    # stored references point at the new ids; old ids (bookmarks, history snapshots) still resolve
    k = store.knowledge()
    assert k.answers[0].app_id == new and k.preferences[0].source_app == "contoso-bank~2026-10-01_risk-analyst"
    assert store.app_path(old) == path.resolve()
    assert store.meta(old)["company"] == "Northwind" and store.sent_copies(old) == store.sent_copies(new)
    assert {a["id"] for a in store.list_apps()} == set(moved.values())
    assert store.migrate_layout() == {}                     # idempotent
    assert any(h["cause"] == "application folders reorganized" for h in store.history("knowledge"))


def test_migration_runs_when_the_server_starts(store):
    from autocv.api import create_app
    from autocv.engine import FakeEngine
    from conftest import client_for
    old = _old_style(store, "2026-10-03_globex_data-analyst", "Google", "Data Analyst", "built")
    client = client_for(create_app(store, FakeEngine({})))
    (row,) = client.get("/api/applications").json()
    assert row["id"] == "google~2026-10-03_data-analyst"
    assert client.get(f"/api/applications/{old}").status_code == 200   # old link still opens it
    assert client.delete(f"/api/applications/{row['id']}").status_code == 204
    assert not (store.apps_dir / "google").exists()


def test_old_company_named_resumes_lose_the_company(store):
    old = _old_style(store, "2026-10-01_example-capital_lead", "Example Capital", "Lead")
    folder = store.apps_dir / old
    (folder / "Jane_Example_Resume.pdf").unlink()
    for ext in (".docx", ".pdf"):
        (folder / f"Jane_Example_Resume_Example_Capital{ext}").write_bytes(b"built")
    (folder / "Jane_Example_Resume_v2.docx").write_bytes(b"mine")      # not the old pattern: left alone
    store.migrate_layout()
    (app,) = store.list_apps()
    assert store.files(app["id"]) == ["Jane_Example_Resume.docx", "Jane_Example_Resume.pdf", "Jane_Example_Resume_v2.docx"]
    sent = store.app_path(app["id"]) / "sent" / "2026-10-01_120000"
    assert [p.name for p in sent.iterdir()] == ["Jane_Example_Resume.pdf"]  # sent copies untouched
