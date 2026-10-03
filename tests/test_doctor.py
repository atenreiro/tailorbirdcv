"""`autocv doctor` / GET /api/doctor: reports what this machine needs, changes nothing."""

import shutil
from pathlib import Path

from autocv import doctor, pdf
from autocv.api import create_app
from autocv.engine import FakeEngine
from autocv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"


def engines(word=True, libreoffice=True):
    return [{"id": "word", "name": "Microsoft Word", "available": word, "path": None, "version": None},
            {"id": "libreoffice", "name": "LibreOffice", "available": libreoffice, "path": None, "version": "26.8"}]


def test_doctor_reports_each_check(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "detect", lambda: engines())
    private = tmp_path / "private"
    shutil.copytree(FIX, private, ignore=shutil.ignore_patterns("tailored.yaml"))
    checks = client_for(create_app(Store(private), FakeEngine())).get("/api/doctor").json()
    by_id = {c["id"]: c for c in checks}
    assert set(by_id) == {"data", "profile", "ai", "pdf", "fonts", "browser", "web"}
    assert by_id["data"]["status"] == "ok" and by_id["profile"]["status"] == "ok"
    assert by_id["ai"]["status"] == "ok" and "Microsoft Word" in by_id["pdf"]["detail"]


def test_doctor_explains_what_is_missing(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.setattr(pdf, "detect", lambda: engines(False, False))

    class Offline(FakeEngine):
        async def status(self):
            return {"engine": "claude-cli", "ready": False, "detail": "Claude Code CLI not found"}
    checks = {c["id"]: c for c in asyncio.run(doctor.run_checks(Offline(), tmp_path / "new", None))}
    assert checks["profile"]["status"] == "warn" and "import your resume" in checks["profile"]["fix"]
    assert checks["ai"]["status"] == "error" and "API key" in checks["ai"]["fix"]
    assert checks["pdf"]["status"] == "error" and "LibreOffice" in checks["pdf"]["fix"]
    assert "✗ PDF engine" in doctor.render(list(checks.values()))


def test_libreoffice_without_microsoft_fonts_reports_the_stand_ins(monkeypatch):
    monkeypatch.setattr(pdf, "detect", lambda: engines(word=False))
    monkeypatch.setattr(pdf, "installed", lambda family: family != "Georgia")
    check = doctor._fonts(None)
    assert check["status"] == "ok" and "Georgia → Gelasio" in check["detail"]
