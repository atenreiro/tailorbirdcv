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
    assert set(by_id) == {"data", "profile", "ai", "pdf", "fonts", "keychain", "browser", "web"}
    assert {c["level"] for c in checks} <= {"required", "recommended", "optional", "info"}
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


def test_setup_phase_lists_what_you_have_and_what_you_need(tmp_path, monkeypatch):
    """The wizard's first step: every AI option, keychain, PDF, browser and Node — each with its level."""
    import asyncio
    from autocv import engine as eng
    monkeypatch.setattr(pdf, "detect", lambda: engines(word=False, libreoffice=False))

    async def logged_in(self):
        return {"engine": self.name, "ready": True, "detail": "logged in"}

    async def missing(self):
        return {"engine": self.name, "ready": False, "detail": "Codex CLI not found"}
    monkeypatch.setattr(eng.ClaudeCLIEngine, "status", logged_in)
    monkeypatch.setattr(eng.CodexCLIEngine, "status", missing)
    checks = {c["id"]: c for c in asyncio.run(doctor.run_checks(FakeEngine(), tmp_path / "new", None, phase="setup"))}
    assert list(checks) == ["data", "ai_options", "pdf", "keychain", "browser", "node"]
    ai = checks["ai_options"]
    assert ai["status"] == "ok" and ai["level"] == "required"
    states = {i["id"]: i["state"] for i in ai["items"]}
    assert states == {"claude-cli": "ready", "codex-cli": "missing", "anthropic-api": "no-key",
                      "openai-api": "no-key", "openrouter-api": "no-key"}
    assert checks["pdf"]["status"] == "error" and checks["pdf"]["level"] == "recommended"
    assert checks["browser"]["level"] == "optional"
    assert checks["keychain"]["status"] == "ok"  # the in-memory test keyring


def test_browser_check_needs_the_exact_complete_chromium(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.setattr(doctor, "_chromium_revision", lambda: "1243")
    (tmp_path / "chromium_headless_shell-1217").mkdir()  # another version
    (tmp_path / "chromium_headless_shell-1217" / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")
    (tmp_path / "chromium-1243").mkdir()  # the full browser: headless pages never use it
    (tmp_path / "chromium-1243" / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")
    (tmp_path / "chromium_headless_shell-1243").mkdir()  # partial download: no marker
    assert not doctor.browser_installed()
    (tmp_path / "chromium_headless_shell-1243" / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")
    assert doctor.browser_installed()


def test_test_endpoints_make_one_real_call_each(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    eng = FakeEngine({"test": {"ok": True}})
    client = client_for(create_app(Store(private), eng))
    r = client.post("/api/engine/test").json()
    assert r["ok"] and [t for t, _ in eng.calls] == ["test"]
    broken = client_for(create_app(Store(private), FakeEngine({})))
    r = broken.post("/api/engine/test").json()
    assert not r["ok"] and "no response" in r["detail"]

    monkeypatch.setattr(pdf, "detect", lambda: engines(word=False))
    seen = {}

    def fake_to_pdf(docx, pdf_path=None, timeout=0, engine=None):
        seen["engine"], seen["exists"] = engine, docx.exists()
        out = docx.with_suffix(".pdf")
        out.write_bytes(b"%PDF-1.4 test")
        return out
    monkeypatch.setattr(pdf, "to_pdf", fake_to_pdf)
    r = client.post("/api/pdf/test").json()
    assert r["ok"] and r["engine"] == "LibreOffice" and seen == {"engine": "libreoffice", "exists": True}
    monkeypatch.setattr(pdf, "detect", lambda: engines(False, False))
    r = client.post("/api/pdf/test").json()
    assert not r["ok"] and "No PDF engine" in r["detail"]
    assert client.put("/api/setup", json={"step": "computer"}).json()["step"] == "computer"
    assert client.get("/api/doctor?phase=setup").status_code == 200
