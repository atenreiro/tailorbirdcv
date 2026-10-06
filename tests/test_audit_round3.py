"""Fixes from the third audit: id reuse after a profile is re-created, Word's lock file, typed settings,
the API client reuse, and the CLI's PDF errors."""

import json
import shutil
from pathlib import Path

from tailorbirdcv import cli, importer
from tailorbirdcv.engine import AnthropicAPIEngine
from tailorbirdcv.store import Store
from test_importer import TRANSCRIPTION

FIX = Path(__file__).parent / "fixtures"


def test_a_recreated_profile_never_reuses_an_old_id(tmp_path):
    store = Store(tmp_path / "p")
    store.save_profile(importer.build_profile(TRANSCRIPTION), cause="first")
    data = store.profile().model_dump(exclude_none=True)
    data["headlines"][0]["text"] = "Lead Designer"
    store.save_profile(data, cause="edit")  # history now holds the old version
    store.profile_path.unlink()
    used = store.used_ids("profile")
    assert {"northwind-bank", "northwind-bank.a1", "h.main"} <= used
    fresh = importer.build_profile(TRANSCRIPTION, used)
    assert not set(fresh_ids(fresh)) & used  # the re-import gets new ids
    store.save_profile(fresh, cause="re-import")
    assert "northwind-bank.a1" in store.profile().retired_ids


def fresh_ids(profile: dict) -> list[str]:
    from tailorbirdcv.schema import MasterProfile
    return MasterProfile.model_validate(profile).all_ids()


def test_rebuilding_leaves_words_lock_file_alone(tmp_path):
    private = tmp_path / "p"
    shutil.copytree(FIX, private, ignore=shutil.ignore_patterns("*.xml"))
    store = Store(private)
    app_id = store.create_app("Acme", "Lead", "jd " * 50)
    folder = store.app_path(app_id)
    for name in ("Jane_Resume.docx", "Jane_Resume.pdf", "~$ne_Resume.docx", ".hidden.pdf"):
        (folder / name).write_bytes(b"x")
    store.clear_outputs(app_id)
    assert sorted(p.name for p in folder.iterdir() if p.suffix in (".docx", ".pdf")) == [".hidden.pdf", "~$ne_Resume.docx"]


def test_hand_edited_settings_of_the_wrong_type_fall_back(tmp_path):
    store = Store(tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({"targets": {"pages": "2", "field": 5, "region": "Oslo"},
                                                        "theme": 3, "pdf_engine": "word"}), encoding="utf-8")
    s = store.settings()
    assert s["targets"]["pages"] == 2 and s["targets"]["field"] == "" and s["targets"]["region"] == "Oslo"
    assert s["theme"] == "classic" and s["pdf_engine"] == "word"
    (tmp_path / "settings.json").write_text(json.dumps({"targets": {"pages": 9}}), encoding="utf-8")
    assert store.settings()["targets"]["pages"] == 2


def test_the_api_engine_reuses_one_client_per_key():
    engine = AnthropicAPIEngine(key=lambda: "sk-ant-" + "x" * 30)
    a, b = engine._client("sk-ant-" + "x" * 30), engine._client("sk-ant-" + "x" * 30)
    assert a is b and engine._client("sk-ant-" + "y" * 30) is not a


def test_cli_build_reports_a_pdf_failure_without_a_traceback(tmp_path, monkeypatch, capsys):
    from tailorbirdcv import pdf
    private = tmp_path / "p"
    shutil.copytree(FIX, private, ignore=shutil.ignore_patterns("*.xml"))
    store = Store(private)
    app_id = store.create_app("Acme", "Lead", "jd " * 50)
    shutil.copy(FIX / "tailored.yaml", store.app_path(app_id) / "tailored.yaml")
    monkeypatch.setattr(cli, "STORE", store)
    monkeypatch.setattr(cli, "PRIVATE", private)
    monkeypatch.setattr(cli, "PROFILE", store.profile_path)
    monkeypatch.setattr(cli, "APPS", store.apps_dir)

    def no_engine(*a, **k):
        raise RuntimeError("No PDF engine found: install Microsoft Word or LibreOffice")
    monkeypatch.setattr(pdf, "to_pdf", no_engine)
    assert cli.cmd_build(type("A", (), {"app": app_id, "no_pdf": False, "max_pages": None})()) == cli.PDF_FAILED
    err = capsys.readouterr().err
    assert "pdf failed (the .docx was built): No PDF engine found" in err and "Traceback" not in err
    assert any(f.endswith(".docx") for f in store.files(app_id))
