"""FastAPI backend for the TailorbirdCV web UI (localhost only).

    uv run tailorbirdcv serve            → http://127.0.0.1:8000 (serves web/dist if built)
    cd web && npm run dev          → http://localhost:5173 (proxies /api to :8000)
"""

from __future__ import annotations

import asyncio
import datetime as dt
import difflib
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Annotated, Literal

import yaml
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import ai, ats, backup, critique as hm, factcheck, favicon, fit, oscompat, paths, pdf as pdfmod, themes, update
from .jobfetch import FetchError, fetch_job
from .apikey import PROVIDERS
from .engine import DEFAULT_API_MODEL, ENGINES, Engine, EngineError, PrivateEngine, default_engine
from .render import docx_text, render, render_letter, use_design
from .schema import AppAnswer, CoverLetter, Knowledge, MasterProfile, Preference, TailoredResume
from .store import (OUTCOMES, STATUSES, AppNotFound, Conflict, CorruptApp, IncompleteRole, NeedsBuild, OutputInUse,
                    RetiredIdReused, Store, next_id)

log = logging.getLogger("tailorbirdcv")



# --------------------------------------------------------------------------- request models


MAX_JD = 60_000  # characters: ~15 pages of job description; longer is almost certainly not one job


class NewApplication(BaseModel):
    jd: str = Field("", max_length=MAX_JD * 2)  # trimmed below; refuse absurd bodies outright
    url: str | None = Field(None, max_length=2000)
    company: str = Field("", max_length=500)
    role: str = Field("", max_length=500)


class ProfileImport(BaseModel):
    filename: str = Field("", max_length=255)
    data: str = Field("", max_length=15_000_000)   # base64 file contents
    text: str = Field("", max_length=200_000)      # or pasted text
    name: str = Field("", max_length=200)          # hidden from the AI (Settings → Privacy) from the first call
    address: str = Field("", max_length=300)       # optional street address, hidden too


class PdfUpload(BaseModel):
    filename: str = Field("", max_length=255)
    data: str = Field(..., max_length=15_000_000)  # base64 file contents


class SetupStep(BaseModel):
    step: Literal[tuple(Store.SETUP_STEPS)]  # type: ignore[valid-type]


class BlankProfile(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    location: str = Field("", max_length=120)
    headline: str = Field(min_length=1, max_length=240)


class TargetsPatch(BaseModel):
    field: str | None = Field(None, max_length=80)
    seniority: str | None = Field(None, max_length=80)
    roles: str | None = Field(None, max_length=240)
    region: str | None = Field(None, max_length=80)
    spelling: Literal["US", "UK"] | None = None
    pages: Literal[1, 2, 3] | None = None
    pack: Literal[tuple(ai.PACKS)] | None = None  # type: ignore[valid-type]


MODEL_ID = r"^(?:[A-Za-z0-9][A-Za-z0-9._:/\-]*)?$"  # e.g. claude-sonnet-5-5, gpt-6.1-sol, anthropic/claude-sonnet-5.5


class SettingsPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    pdf_engine: Literal[tuple(pdfmod.ENGINES)] | None = None  # type: ignore[valid-type]  # None = automatic
    targets: TargetsPatch | None = None
    theme: Literal[tuple(themes.THEMES)] | None = None  # type: ignore[valid-type]
    paper: Literal["letter", "a4"] | None = None  # None = the theme's default
    text_size: Literal[tuple(themes.TEXT_SIZES)] | None = None  # type: ignore[valid-type]
    ai_engine: Literal[tuple(ENGINES)] | None = None  # type: ignore[valid-type]
    api_model: str | None = Field(None, max_length=100, pattern=MODEL_ID)  # "" / None = default
    openai_model: str | None = Field(None, max_length=100, pattern=MODEL_ID)
    codex_model: str | None = Field(None, max_length=100, pattern=MODEL_ID)
    openrouter_model: str | None = Field(None, max_length=100, pattern=MODEL_ID)
    openrouter_zdr: bool | None = None
    update_check: bool | None = None
    company_icons: bool | None = None
    learn_style: bool | None = None
    hide_personal: bool | None = None
    private_address: str | None = Field(None, max_length=300)
    section_titles: dict[Literal[tuple(themes.TITLES)], Annotated[str, Field(max_length=60)]] | None = None  # type: ignore[valid-type]


class ApiKey(BaseModel):
    key: str = Field(min_length=1, max_length=400)


class MetaPatch(BaseModel):
    status: Literal[tuple(STATUSES)] | None = None  # type: ignore[valid-type]
    outcome: Literal[tuple(OUTCOMES)] | None = None  # type: ignore[valid-type]  # with status "closed"
    notes: str | None = None
    guidance: str | None = None
    company: str | None = None
    role: str | None = None


class Answer(BaseModel):
    question_id: str
    question: str
    answer: str


class EvidenceIn(BaseModel):
    target: str
    text: str
    skills: list[dict] = []
    note: str | None = None


class ComposeIn(BaseModel):
    guidance: str = ""


class LetterIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    tone: Literal["formal", "warm", "direct"] = "formal"
    recipient: str = Field("", max_length=120)   # the hiring manager's name, if known
    notes: list[str] = Field(default_factory=list, max_length=20)  # review issue ids marked "for the cover letter"


class ProfileYaml(BaseModel):
    yaml: str


class Decisions(BaseModel):
    decisions: dict[str, Literal["accepted", "rejected"]]


# --------------------------------------------------------------------------- helpers


def _report_json(report: factcheck.Report) -> dict:
    return {
        "ok": report.ok,
        "errors": [{"where": i.where, "message": i.message} for i in report.errors],
        "warnings": [{"where": i.where, "message": i.message} for i in report.warnings],
    }


def _ats_json(store: Store, app_id: str, tailored: TailoredResume) -> dict | None:
    analysis = store.analysis(app_id) or {}
    if not analysis.get("keywords"):
        return None
    profile = store.profile()
    with tempfile.TemporaryDirectory() as tmp:
        lines = docx_text(render(profile, tailored, Path(tmp) / "r.docx"))
    report = ats.analyze(analysis["keywords"], lines, profile)
    coverage = {p: dict(zip(("hit", "total"), report.coverage(p))) for p in ("must", "nice")}
    return {"words": report.words, "coverage": coverage,
            "keywords": [r.__dict__ for r in report.results]}


def _safe_ats(store: Store, app_id: str, tailored: TailoredResume) -> dict | None:
    try:
        return _ats_json(store, app_id, tailored)
    except Exception:  # the ATS view is informational; never let it break loading an application
        return None


def history_summary(kind: str, old_text: str, new_text: str) -> list[str]:
    """Human summary of what changed from a saved version to the current one."""
    old, new = yaml.safe_load(old_text) or {}, yaml.safe_load(new_text) or {}
    lines: list[str] = []
    if kind == "profile":
        from .schema import MasterProfile
        try:
            a, b = factcheck.evidence_index(MasterProfile.model_validate(old)), \
                factcheck.evidence_index(MasterProfile.model_validate(new))
        except ValidationError:
            return ["(can't summarise: one version doesn't validate)"]
        added, removed = sorted(set(b) - set(a)), sorted(set(a) - set(b))
        changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        skills_a = {i for g in old.get("skills", []) for i in g.get("items", [])}
        skills_b = {i for g in new.get("skills", []) for i in g.get("items", [])}
        heads_a = {h["text"] for h in old.get("headlines", [])}
        heads_b = {h["text"] for h in new.get("headlines", [])}
        for label, items in (("evidence added since", added), ("evidence removed since", removed),
                             ("evidence edited since", changed)):
            if items:
                lines.append(f"{len(items)} {label}: {', '.join(items[:6])}{'…' if len(items) > 6 else ''}")
        if skills_b - skills_a:
            lines.append(f"skills added since: {', '.join(sorted(skills_b - skills_a))}")
        if skills_a - skills_b:
            lines.append(f"skills removed since: {', '.join(sorted(skills_a - skills_b))}")
        if heads_a != heads_b:
            lines.append("headlines changed")
    else:
        for key, label in (("answers", "answer"), ("preferences", "preference")):
            a = {x["id"]: x for x in old.get(key, [])}
            b = {x["id"]: x for x in new.get(key, [])}
            for verb, ids in (("added since", set(b) - set(a)), ("removed since", set(a) - set(b)),
                              ("changed since", {k for k in set(a) & set(b) if a[k] != b[k]})):
                if ids:
                    lines.append(f"{len(ids)} {label}{'s' if len(ids) > 1 else ''} {verb}")
    return lines or ["no content changes (formatting only)"]


def _engine_call(exc: EngineError) -> HTTPException:
    return HTTPException(503, f"AI engine error: {exc}")


# --------------------------------------------------------------------------- app


ACCESS_COOKIE = "tailorbirdcv_key"


def create_app(store: Store | None = None, engine: Engine | None = None,
               allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "[::1]")) -> FastAPI:
    store = store or Store.default()
    try:  # older flat application folders → applications/<company>/<date>_<role>/
        moved = store.migrate_layout()
        if moved:
            print(f"TailorbirdCV: moved {len(moved)} application folder(s) to applications/<company>/<date>_<role>/")
    except Exception as e:  # noqa: BLE001 — the app must always start; the UI shows what's readable
        log.warning("TailorbirdCV: application folder migration failed (%s); starting anyway", e)
    try:  # did the upgrade that restarted us take? (the UI says so either way)
        update.settle(store.private)
    except Exception as e:  # noqa: BLE001
        log.warning("TailorbirdCV: couldn't read the last upgrade's outcome (%s)", e)
    try:
        if store.profile_path.exists():
            store.profile()
    except Exception as e:  # noqa: BLE001
        log.warning("TailorbirdCV: private/profile.yaml doesn't validate (%s). Fix it in Master profile → YAML.", e)
    try:  # answers remembered more than once (before merging existed): keep the newest per topic
        store.compact_knowledge()
    except Exception as e:  # noqa: BLE001 — memory housekeeping never stops the app
        log.warning("TailorbirdCV: couldn't merge repeated answers (%s)", e)
    engine = PrivateEngine(engine or default_engine(store), store)  # every AI call: contact details hidden
    app = FastAPI(title="TailorbirdCV", docs_url="/api/docs", openapi_url="/api/openapi.json")
    import hmac
    app.state.access_key = access_key = store.access_key()
    app.state.busy = 0         # non-GET API requests still running: an upgrade waits until there are none
    app.state.upgrade = None   # set by POST /api/update/upgrade; `tailorbirdcv serve` upgrades once the server stops
    # app.state.request_exit is set by `tailorbirdcv serve`: it stops the server (for an upgrade)
    # One cookie per data folder: a second TailorbirdCV (another folder, another port) doesn't lock this one out.
    import hashlib
    cookie = app.state.cookie_name = ACCESS_COOKIE + "_" + hashlib.sha256(str(store.private.resolve()).encode()).hexdigest()[:10]
    oscompat.make_private(store.private)  # resumes, profile and the key: not readable by other accounts

    @app.exception_handler(AppNotFound)
    async def app_not_found(request: Request, exc: AppNotFound):
        # Also covers a request that finishes after its application was deleted.
        return JSONResponse({"detail": "application not found"}, status_code=404)

    @app.exception_handler(CorruptApp)
    async def corrupt_app(request: Request, exc: CorruptApp):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Opening TailorbirdCV's link (…/?key=…) turns the key into a cookie and drops it from the address bar.
        if request.method == "GET" and "key" in request.query_params:
            from fastapi.responses import RedirectResponse
            from urllib.parse import urlencode
            given = request.query_params["key"]
            rest = [(k, v) for k, v in request.query_params.multi_items() if k != "key"]
            path = "/" + request.url.path.lstrip("/\\")  # never "//other.site" or "/\\other.site": stays here
            if path.startswith("/api/"):
                path, rest = "/", []
            target = path + ("?" + urlencode(rest) if rest else "")
            response = RedirectResponse(target, status_code=303)
            if hmac.compare_digest(given.encode(), access_key.encode()):
                response.set_cookie(cookie, access_key, max_age=400 * 24 * 3600, httponly=True,
                                    samesite="strict", path="/")
            return response
        if request.url.path.startswith("/api/"):
            # Browsers label every request with where it came from. Only TailorbirdCV's own pages
            # (same-origin) and typed URLs/bookmarks ("none") may read or change data: another
            # site can't even GET a resume or the profile through a link, image or iframe.
            site = request.headers.get("sec-fetch-site")
            if site is not None and site not in ("same-origin", "none"):
                return JSONResponse({"detail": "Cross-site request refused."}, status_code=403)
            # Cross-site guard: a page on another site can send "simple" POSTs to localhost without
            # a preflight. Requiring a custom header forces a CORS preflight, which this API never
            # grants, so only the TailorbirdCV UI itself can change data or start AI runs.
            if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-tailorbirdcv") != "1":
                return JSONResponse({"detail": "Missing X-TailorbirdCV header (cross-site request refused)."},
                                    status_code=403)
            # Only this user's browser: other programs and other accounts on this computer don't have the key.
            if not hmac.compare_digest(request.cookies.get(cookie, "").encode(), access_key.encode()):
                return JSONResponse({"detail": {"code": "locked", "message": "Open TailorbirdCV from the link `tailorbirdcv serve` "
                                                "printed in your terminal (it unlocks this browser)."}},
                                    status_code=401)
            # The candidate's targets (Settings) steer every AI prompt made while handling this request.
            settings = store.settings()
            ai.use_context(ai.Context.from_settings(settings["targets"], store.private))
            use_design(settings["theme"], settings["paper"], settings["text_size"],  # every render uses the chosen design
                       settings["section_titles"])
        counted = request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS")
        app.state.busy += counted
        try:
            response = await call_next(request)
        finally:
            app.state.busy -= counted
        # Anti-clickjacking: other sites can't frame TailorbirdCV; TailorbirdCV may frame itself
        # (the Export step previews the PDF in an iframe).
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
        return response

    # DNS-rebinding guard, added last so it runs first (before the key and cross-site checks): a malicious
    # site can't reach this local API through a hostname it controls.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))

    api = APIRouter(prefix="/api")

    def need_version(if_match: str | None) -> None:
        """Edits must say which version they started from, so a stale page can never overwrite a newer save."""
        if not if_match:
            raise HTTPException(428, "Reload the page: this edit didn't say which version it started from.")

    def page_limit() -> int:
        return int(store.settings()["targets"]["pages"])

    def need_app(app_id: str) -> str:
        """The application's current id (an old id from before a move/rename maps to it, so
        answers and knowledge never get a second key for the same application)."""
        try:
            return store.canonical_id(app_id)
        except KeyError:
            raise HTTPException(404, "application not found")

    def need_profile():
        if not store.profile_path.exists():
            raise HTTPException(409, "No master profile yet — open TailorbirdCV's Welcome page to import your resume.")
        return store.profile()

    def profile_payload(profile=None):
        if profile is None:
            profile, version, _ = store.profile_snapshot()
        else:
            version = store.profile_version()
        return {"profile": profile.model_dump(exclude_none=True), "evidence": factcheck.evidence_index(profile),
                "version": version}

    def knowledge_payload(knowledge=None):
        return {**(knowledge or store.knowledge()).model_dump(exclude_none=True), "version": store.knowledge_version()}

    # -- engine / profile ------------------------------------------------------------
    @api.get("/engine")
    async def engine_status():
        return await engine.status()

    @api.get("/engine/installed")
    def engines_installed():
        """Which subscription CLIs are on this computer (the setup wizard picks Codex when Claude Code isn't)."""
        from .engine import find_cli
        return {"claude-cli": bool(os.environ.get("TAILORBIRDCV_CLAUDE_BIN") or find_cli("claude")),
                "codex-cli": bool(os.environ.get("TAILORBIRDCV_CODEX_BIN") or find_cli("codex"))}

    def settings_payload():
        settings, engines = store.settings(), pdfmod.detect()
        try:
            effective = pdfmod.resolve(settings["pdf_engine"], engines)
        except RuntimeError:
            effective = None
        return {**settings, "pdf_engines": engines, "pdf_effective": effective, "platform": oscompat.PLATFORM,
                "packs": ai.PACKS, "section_defaults": themes.TITLES,
                "themes": [{"id": t.id, "name": t.name, "description": t.description, "fonts": t.fonts(),
                            "accent": t.accent, "ink": t.ink, "rule": t.rule, "name_font": t.name_font,
                            "paper": t.paper} for t in themes.THEMES.values()],
                "api_key": api_key_info(), "api_default_model": DEFAULT_API_MODEL,
                "api_keys": {p: api_key_info(p) for p in PROVIDERS}, "keychain": keychain_status(),
                "engines": [{"id": i, "label": e.label, "kind": e.kind, "model_setting": e.model_setting,
                             "default_model": e.default_model, "provider": e.provider} for i, e in ENGINES.items()]}

    @api.get("/doctor")
    async def get_doctor(phase: Literal["all", "setup"] = "all"):
        from . import doctor
        return await doctor.run_checks(engine, store.private, store.settings()["pdf_engine"], phase=phase)

    @api.post("/engine/test")
    async def engine_test():
        """One tiny real call to the chosen AI engine (a few tokens), so "connected" means "works"."""
        import time
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
        start = time.monotonic()
        try:
            out = await asyncio.wait_for(engine.complete("Answer in JSON.", "TASK: test\nReply with ok set to true.",
                                                         schema), 120)
            ok = isinstance(out, dict) and out.get("ok") is True
            detail = "The AI answered." if ok else "The AI answered, but not as expected. Try again."
        except asyncio.TimeoutError:
            ok, detail = False, "No answer within 2 minutes. Check your connection, or try another engine."
        except EngineError as e:
            ok, detail = False, str(e)
        return {"ok": ok, "detail": detail, "seconds": round(time.monotonic() - start, 1),
                "engine": getattr(engine, "name", "")}

    @api.post("/pdf/test")
    async def pdf_test():
        """Convert a one-page sample with the chosen PDF engine (surfaces Word permission prompts now)."""
        return await asyncio.to_thread(pdfmod.test_conversion, store.settings()["pdf_engine"])

    def keychain_status() -> dict:
        from . import apikey
        return apikey.backend_status()

    def api_key_info(provider: str = "anthropic") -> dict:
        from . import apikey
        key, source = apikey.get(provider)
        return {"configured": bool(key), "source": source, "masked": apikey.masked(key),
                "env": PROVIDERS[provider].env, "prefix": PROVIDERS[provider].prefix}

    @api.put("/settings/api-key")
    async def put_api_key(body: ApiKey, provider: Literal[tuple(PROVIDERS)] = "anthropic"):  # type: ignore[valid-type]
        """Store an API key in the OS keychain (never in the data folder, never sent back)."""
        from . import apikey
        try:
            await asyncio.to_thread(apikey.save, body.key, provider)
        except ValueError as e:
            raise HTTPException(422, str(e))
        except apikey.KeychainUnavailable as e:
            raise HTTPException(409, str(e))
        return await asyncio.to_thread(settings_payload)

    @api.delete("/settings/api-key")
    async def delete_api_key(provider: Literal[tuple(PROVIDERS)] = "anthropic"):  # type: ignore[valid-type]
        from . import apikey
        await asyncio.to_thread(apikey.delete, provider)
        return await asyncio.to_thread(settings_payload)

    @api.get("/settings")
    async def get_settings():
        return await asyncio.to_thread(settings_payload)

    @api.put("/settings")
    async def put_settings(patch: SettingsPatch):
        if patch.pdf_engine and not any(e["id"] == patch.pdf_engine and e["available"]
                                        for e in await asyncio.to_thread(pdfmod.detect)):
            raise HTTPException(400, f"{pdfmod.NAMES[patch.pdf_engine]} isn't installed on this computer.")
        data = patch.model_dump(include=patch.model_fields_set - {"targets"})
        for key in ("api_model", "openai_model", "codex_model", "openrouter_model"):
            if key in data:
                data[key] = (data[key] or "").strip() or None
        if patch.targets is not None:
            data["targets"] = {k: v.strip() if isinstance(v, str) else v
                               for k, v in patch.targets.model_dump(exclude_unset=True).items() if v is not None}
        store.save_settings(data)
        return await asyncio.to_thread(settings_payload)

    @api.get("/profile")
    def get_profile():
        need_profile()  # 409 when there's none yet
        return profile_payload()  # content and version from one read

    # -- first run: the setup wizard ----------------------------------------------------
    def setup_payload() -> dict:
        draft = store.setup_draft() or {}
        has_profile = store.profile_path.exists()
        out = {"has_profile": has_profile, **store.setup_state(),
               "suggested_targets": draft.get("suggested_targets"), "pages": draft.get("pages")}
        if draft and not has_profile:  # the imported profile awaiting review (survives a refresh)
            out["draft"] = {"profile": draft["profile"], "unverified": draft["unverified"]}
        return out

    @api.get("/setup")
    def get_setup():
        return setup_payload()

    @api.put("/setup")
    def put_setup(body: SetupStep):
        store.save_setup_state(step=body.step)
        return setup_payload()

    @api.post("/setup/finish")
    def finish_setup():
        need_profile()
        store.save_setup_state(completed=True, step="checks")
        store.clear_setup_draft()
        return setup_payload()

    @api.delete("/setup/draft")
    def delete_setup_draft():
        """Start over: forget the imported draft (nothing was saved from it)."""
        store.clear_setup_draft()
        return setup_payload()

    browser_install: dict = {"state": "idle", "detail": ""}

    # -- privacy -----------------------------------------------------------------------------------------
    @api.get("/privacy/preview")
    def privacy_preview():
        """Your profile exactly as AI prompts carry it, and the values hidden from it (Settings → Privacy)."""
        profile = need_profile()
        vault = engine.vault()
        text = ai.profile_text(profile)
        shown = vault.redact(text) if vault else text
        return {"on": vault is not None, "text": shown, "hidden": vault.tokens if vault else {}}

    # -- backup and restore --------------------------------------------------------------------------------
    MAX_UPLOAD = 600_000_000  # a backup .zip (a real one is a few MB)

    @api.get("/backup")
    async def download_backup(keys: bool = False):
        """The data folder as one .zip (backup.py). API keys only when asked (`keys=true`). The X-Backup-Keys
        header lists the providers whose keys are inside, for the warning the UI shows afterwards."""
        fd, tmp = tempfile.mkstemp(dir=store.private, prefix=".backup-", suffix=".zip")
        os.close(fd)
        try:
            info = await asyncio.to_thread(backup.create, store, Path(tmp), keys)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return FileResponse(tmp, media_type="application/zip", filename=backup.file_name(),
                            content_disposition_type="attachment",
                            headers={"X-Backup-Keys": ",".join(info["keys"]), "Cache-Control": "no-store"},
                            background=BackgroundTask(lambda: Path(tmp).unlink(missing_ok=True)))

    @api.post("/restore")
    async def restore_backup(request: Request):
        """Replace the data with a backup (the request body is the .zip). Refused while anything else runs; the
        data it replaces is kept in before-restore/<time>/."""
        if app.state.upgrade or app.state.busy > 1 or tasks_running() or browser_install["state"] == "running":
            raise HTTPException(409, "TailorbirdCV is busy (an AI run, build or download is still going). Try again "
                                     "when it has finished.")
        fd, tmp = tempfile.mkstemp(dir=store.private, prefix=".restore-upload-", suffix=".zip")
        size = 0
        try:
            with os.fdopen(fd, "wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "That file is too large to be a TailorbirdCV backup.")
                    f.write(chunk)
            if not size:
                raise HTTPException(422, "Choose a backup file (.zip).")
            try:
                return await asyncio.to_thread(backup.restore, store, Path(tmp))
            except backup.BackupError as e:
                raise HTTPException(422, str(e)) from e
        finally:
            Path(tmp).unlink(missing_ok=True)

    # -- updates ---------------------------------------------------------------------------------------
    def update_view(cache: dict | None = None) -> dict:
        enabled = store.settings()["update_check"]
        return {**update.view(store.private, enabled, cache), "upgrading": (app.state.upgrade or {}).get("target"),
                "windows": oscompat.IS_WINDOWS, "log": update.log_path(store.private).is_file()}

    @api.get("/update")
    async def update_status():
        """The running and latest versions (PyPI, checked at most daily, never when checks are off)."""
        enabled = store.settings()["update_check"]
        return update_view(await update.refresh(store.private, enabled))

    @api.post("/update/check")
    async def update_check():
        if not store.settings()["update_check"]:
            raise HTTPException(409, "Update checks are off. Turn them on in Settings → About TailorbirdCV.")
        return update_view(await update.refresh(store.private, True, force=True))

    @api.post("/update/upgrade", status_code=202)
    async def upgrade():
        """Upgrade to the latest version: the server stops, `tailorbirdcv serve` runs `uv tool upgrade` and starts
        again on the same port. Only for one-line-installer copies, and only when nothing else is running."""
        if app.state.upgrade:
            return update_view()
        view = update_view(await update.refresh(store.private, store.settings()["update_check"]))
        if view["kind"] != "uv-tool":
            raise HTTPException(409, "This copy of TailorbirdCV wasn't installed with the one-line installer, so it can't "
                                     f"upgrade itself. To upgrade: {view['command']}")
        if not view["newer"]:
            raise HTTPException(409, "You already have the latest version.")
        uv = update.find_uv()
        if not uv:
            raise HTTPException(409, "uv, which installed TailorbirdCV, can't be found. Upgrade by running the install "
                                     "command again.")
        request_exit = getattr(app.state, "request_exit", None)
        if request_exit is None:
            raise HTTPException(409, "TailorbirdCV can only upgrade itself when it was started with `tailorbirdcv serve`.")
        if app.state.busy > 1 or tasks_running() or browser_install["state"] == "running":
            raise HTTPException(409, "TailorbirdCV is busy (an AI run, build or download is still going). Try again when "
                                     "it has finished.")
        app.state.upgrade = {"target": view["latest"], "uv": uv}
        update.mark_pending(store.private, view["latest"])
        asyncio.get_running_loop().call_later(0.5, request_exit)  # after this answer has gone out
        return update_view()

    @api.post("/update/log")
    def reveal_upgrade_log():
        log_file = update.log_path(store.private)
        if not log_file.is_file():
            raise HTTPException(404, "There's no upgrade log yet.")
        try:
            oscompat.reveal(log_file, log_file.parent)
        except OSError as e:
            raise HTTPException(500, f"Couldn't open the folder: {e}")
        return {"ok": True}

    @api.get("/setup/browser")
    def browser_status():
        from .doctor import browser_installed
        if browser_install["state"] == "idle" and browser_installed():
            return {"state": "done", "detail": "Installed."}
        return browser_install

    @api.post("/setup/browser", status_code=202)
    async def install_browser():
        """Install the optional headless browser (same as `tailorbirdcv install-browser`), in the background."""
        import sys
        if browser_install["state"] == "running":
            return browser_install

        async def run():
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "playwright", "install", "--only-shell", "chromium",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **oscompat.group_kwargs())
                try:
                    out, _ = await asyncio.wait_for(proc.communicate(), 900)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    oscompat.kill_tree(proc.pid)  # never leave a download running behind a "failed" message
                    raise
                lines = [ln for ln in out.decode(errors="replace").splitlines() if ln.strip()]
                ok = proc.returncode == 0
                browser_install.update(state="done" if ok else "failed",
                                       detail="Installed." if ok else (lines[-1] if lines else "Install failed."))
            except asyncio.TimeoutError:
                browser_install.update(state="failed", detail="The download took more than 15 minutes and was stopped. "
                                                              "Check your connection, then try again.")
            except Exception as e:  # noqa: BLE001
                browser_install.update(state="failed", detail=str(e) or "Install failed.")

        browser_install.update(state="running", detail="Downloading (about 200 MB)…")
        asyncio.get_running_loop().create_task(run())
        return browser_install

    def no_profile_yet():
        if store.profile_path.exists():
            raise HTTPException(409, "You already have a master profile. Edit it under Master profile.")

    @api.post("/profile/import")
    async def import_resume(body: ProfileImport):
        """Read a resume with the AI into a DRAFT profile, kept in the data folder until the user
        reviews and saves it (or starts over). Nothing becomes part of the profile here."""
        import base64
        import binascii

        from . import importer, privacy
        no_profile_yet()
        if store.settings()["hide_personal"] and not body.name.strip():
            raise HTTPException(422, "Enter your full name first, so it can be hidden from the AI.")
        if body.address.strip():
            store.save_settings({"private_address": body.address.strip()})
        privacy.use(body.name, body.address)
        try:
            if body.text.strip():
                filename, raw = "pasted.txt", body.text.encode("utf-8")
            else:
                try:
                    filename, raw = body.filename, base64.b64decode(body.data, validate=True)
                except (binascii.Error, ValueError):
                    raise HTTPException(422, "The file couldn't be read.")
            text = await asyncio.to_thread(importer.extract_text, filename, raw)
            pages = await asyncio.to_thread(importer.pdf_pages, filename, raw)
        except importer.ImportError_ as e:
            raise HTTPException(422, str(e))
        try:
            result = await importer.import_profile(engine, text, store.used_ids("profile"), body.name)
        except EngineError as e:
            raise HTTPException(503, f"AI engine unavailable: {e}")
        try:
            MasterProfile.model_validate(result["profile"])
        except ValidationError as e:
            raise HTTPException(502, f"The AI's reading of the resume wasn't usable ({e.error_count()} problems). Try again.")
        store.save_setup_draft({**result, "source": text, "pages": pages})
        store.save_setup_state(step="review")
        return {**result, "pages": pages}

    @api.post("/profile/create")
    def create_profile(body: dict):
        """Save the first profile: the reviewed import ({"profile", "confirmed": [paths]}) or a blank
        one ({"blank": {...}}). Lines that don't match the original file word-for-word are refused
        unless the user confirmed them — checked here against the stored source, not trusted from the UI."""
        from . import importer
        with store.lock:  # check-then-create as one step
            return _create_profile(body, importer)

    def _create_profile(body: dict, importer):
        no_profile_yet()
        if "blank" in body:
            try:
                blank = BlankProfile.model_validate(body["blank"])
            except ValidationError as e:
                raise HTTPException(422, str(e))
            data, cause = importer.blank_profile(blank.name, blank.location, blank.headline), "blank profile"
        else:
            draft = store.setup_draft()
            if not draft or not draft.get("source"):
                raise HTTPException(409, "Import your CV first (Setup → Upload your CV).")
            data = body.get("profile") if isinstance(body.get("profile"), dict) else {}
            data = importer.import_shape(data)  # only what an import produces: nothing that widens the fact-check
            confirmed = {p for p in body.get("confirmed") or [] if isinstance(p, str)}
            try:
                pending = [p for p in importer.unverified(data, draft["source"]) if p not in confirmed]
            except (KeyError, TypeError, AttributeError):
                raise HTTPException(422, "The profile is missing required fields (e.g. a link without text).")
            if pending:
                raise HTTPException(422, {"code": "unconfirmed", "paths": pending,
                                          "message": f"{len(pending)} line(s) don't match your file word-for-word. "
                                                     "Fix, remove or confirm each one before saving."})
            data, cause = importer.mark_confirmed(data, confirmed), "resume import"
        try:
            profile = store.save_profile(data, cause=cause)
        except (ValidationError, RetiredIdReused, IncompleteRole) as e:
            raise HTTPException(422, str(e))
        if not any(store.settings()["section_titles"].values()):  # a new profile: neutral headings (Settings)
            store.save_settings({"section_titles": themes.NEW_PROFILE_TITLES})
        store.save_setup_state(step="targets")
        return profile_payload(profile)

    @api.put("/profile")
    def put_profile(data: dict, if_match: str | None = Header(default=None)):
        need_version(if_match)
        need_profile()
        try:
            profile = store.save_profile(data, base_version=if_match, cause="profile editor")
        except Conflict as e:
            raise HTTPException(409, str(e))
        except (ValidationError, RetiredIdReused, IncompleteRole) as e:
            raise HTTPException(422, str(e))
        return profile_payload(profile)

    @api.get("/profile/yaml")
    def get_profile_yaml():
        need_profile()
        _, version, text = store.profile_snapshot()
        return {"yaml": text, "version": version}

    @api.put("/profile/yaml")
    def put_profile_yaml(body: ProfileYaml, if_match: str | None = Header(default=None)):
        need_version(if_match)
        need_profile()
        try:
            data = yaml.safe_load(body.yaml)
            if not isinstance(data, dict):
                raise TypeError("The profile must be a YAML mapping.")
            store.save_profile(data, base_version=if_match, cause="yaml edit")
        except Conflict as e:
            raise HTTPException(409, str(e))
        except (yaml.YAMLError, ValidationError, RetiredIdReused, IncompleteRole, TypeError) as e:
            raise HTTPException(422, str(e))
        return get_profile_yaml()

    @api.post("/profile/evidence")
    def post_evidence(body: EvidenceIn):
        need_profile()
        with store.lock:
            current = store.profile()
            existing = ai.find_evidence(current, body.target, body.text)
            if existing:  # the same approval twice (double-click, retry): don't add a duplicate
                return {"id": existing, "evidence": factcheck.evidence_index(current)}
            try:
                profile, new_id = ai.add_evidence(current, body.target, body.text, body.skills, body.note)
            except KeyError:
                raise HTTPException(422, f"unknown role '{body.target}'")
            try:
                store.save_profile(profile.model_dump(exclude_none=True), cause="evidence approved")
            except (ValidationError, RetiredIdReused, IncompleteRole) as e:
                raise HTTPException(422, str(e))
        return {"id": new_id, "evidence": factcheck.evidence_index(profile)}

    # -- applications ------------------------------------------------------------------
    def progress(app_id: str, profile) -> dict:
        """What the tracker needs to say where an application stands and what's next."""
        analysis = store.analysis(app_id) or {}
        answers = {a.question_id: a for a in store.answers(app_id)}
        settled = {"no_experience", "approved", "rejected"}
        gaps_open = sum(1 for q in analysis.get("questions", [])
                        if (a := answers.get(q["id"])) is None or (a.status not in settled and not a.answer.strip()))
        tailored = store.tailored(app_id)
        verified = None
        if tailored and profile:
            try:
                verified = factcheck.check(profile, tailored).ok
            except Exception:
                verified = False
        review = critique_payload(app_id)
        hm_summary = None
        if review:
            latest = review["latest"]
            hm_summary = {"verdict": latest["verdict"]["decision"], "stale": review["stale"],
                          "open": sum(1 for i in latest["issues"] if i["id"] not in review["decisions"])}
        return {"seniority": analysis.get("seniority"), "requirements": len(analysis.get("requirements", [])),
                "gaps_open": gaps_open, "drafted": tailored is not None, "verified": verified, "critique": hm_summary}

    # -- AI steps run as tasks: they keep going when the page is left, can be stopped, and are found again ------
    # One per application at a time, held in memory (a restart ends them). A finished task stays until the page
    # that shows its outcome acknowledges it (DELETE …/task), so a result is never lost by looking away; the
    # three steps that only suggest (trim, fill, evidence proposals) keep their suggestion here until then.
    tasks: dict[str, dict] = {}
    RESULT_KINDS = {"trim", "fill", "proposals"}

    def task_view(app_id: str, result: bool = True) -> dict | None:
        t = tasks.get(app_id)
        if not t:
            return None
        view = {k: t[k] for k in ("kind", "label", "status", "started", "finished", "error")}
        if result and t["status"] == "done" and t["kind"] in RESULT_KINDS:
            view["result"] = t["result"]
        return view

    def tasks_running() -> bool:
        return any(t["status"] == "running" for t in tasks.values())

    def _detail(e: Exception) -> str:
        if isinstance(e, HTTPException):
            return e.detail if isinstance(e.detail, str) else str((e.detail or {}).get("message", e.detail))
        return str(e) or type(e).__name__

    def refuse_if_running(app_id: str) -> None:
        if (t := tasks.get(app_id)) and t["status"] == "running":
            raise HTTPException(409, {"code": "running", "task": task_view(app_id, result=False),
                                      "message": f"“{t['label']}” is still running for this application. "
                                                 "Its result appears here when it's done."})

    async def run_task(app_id: str, kind: str, label: str, work):
        """Run `work()` (an AI step of this application) as a task the user can leave, stop and come back to.
        The request still waits for it and answers as before; a second start while it runs is refused."""
        refuse_if_running(app_id)
        record = {"app_id": app_id, "kind": kind, "label": label, "status": "running", "error": None, "result": None,
                  "started": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "finished": None}

        async def body():
            try:
                record["result"] = await work()
                record["status"] = "done"
                return record["result"]
            except asyncio.CancelledError:
                record["status"] = "stopped"
                raise
            except Exception as e:
                record["status"], record["error"] = "failed", _detail(e)
                raise
            finally:
                record["finished"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                final = record["result"].get("id") if isinstance(record["result"], dict) else None
                if final and final != record["app_id"] and tasks.get(record["app_id"]) is record:  # renamed meanwhile
                    del tasks[record["app_id"]]
                    record["app_id"] = final
                    tasks[final] = record

        handle = asyncio.get_running_loop().create_task(body())  # keeps this request's context (targets, design)
        record["handle"] = handle
        tasks[app_id] = record
        try:
            return await asyncio.shield(handle)  # leaving the page never cancels it; only Stop does
        except asyncio.CancelledError:
            if handle.cancelled():
                raise HTTPException(409, {"code": "stopped", "message": "Stopped. Nothing was changed."})
            raise

    @api.get("/tasks")
    def list_tasks():
        """Every running or not-yet-seen AI step, newest first (for the tab title and the board)."""
        out = []
        for app_id, t in tasks.items():
            try:
                meta = store.meta(app_id)
            except Exception:  # noqa: BLE001 — deleted or unreadable meanwhile
                meta = {}
            out.append({"app_id": app_id, "company": meta.get("company") or "", "role": meta.get("role") or "",
                        **task_view(app_id, result=False)})
        return sorted(out, key=lambda t: t["started"], reverse=True)

    @api.post("/applications/{app_id}/task/stop")
    async def stop_task(app_id: str):
        """Stop this application's running AI step. Nothing it was going to save is saved."""
        app_id = need_app(app_id)
        t = tasks.get(app_id)
        if t and t["status"] == "running":
            t["handle"].cancel()
            await asyncio.wait([t["handle"]], timeout=15)  # the AI process is ended before answering
        return {"task": task_view(app_id, result=False)}

    @api.delete("/applications/{app_id}/task", status_code=204)
    def clear_task(app_id: str):
        """The page has shown this finished step's outcome: forget it."""
        app_id = need_app(app_id)
        if (t := tasks.get(app_id)) and t["status"] != "running":
            del tasks[app_id]

    # -- the company's site icon: fetched in the background, once per application (favicon.py) ----------
    favicon_pending: set[str] = set()
    favicon_tasks: set = set()  # keeps the running tasks referenced
    favicon_next: dict[str, tuple] = {}  # a job waiting for the one in progress for the same application

    # A job: (app id, job link or "", sites the posting names, company name, website the analysis names or "").
    async def fetch_favicons(jobs: list[tuple[str, str, list[str], str, str]]) -> None:
        for app_id, url, sites, company, website in jobs:  # one at a time: never a burst of requests to company sites
            found = None
            try:
                found = await favicon.fetch(url, sites, company=company, website=website)
                await asyncio.to_thread(store.save_favicon, app_id, found, website)
            except Exception as e:  # noqa: BLE001 — an icon is never worth an error
                log.debug("TailorbirdCV: site icon for %s failed (%s)", app_id, e)
            finally:
                favicon_pending.discard(app_id)
                if (waiting := favicon_next.pop(app_id, None)) and not found:
                    queue_favicons([waiting])

    def queue_favicons(jobs: list[tuple[str, str, list[str], str, str]]) -> None:
        """Fetch these applications' icons in the background, unless icons are off in Settings."""
        jobs = [j for j in jobs if j[0] not in favicon_pending]
        if not jobs or not store.settings()["company_icons"]:
            return
        favicon_pending.update(j[0] for j in jobs)
        task = asyncio.get_running_loop().create_task(fetch_favicons(jobs))
        favicon_tasks.add(task)
        task.add_done_callback(favicon_tasks.discard)

    @api.get("/applications")
    async def list_applications():
        apps = await asyncio.to_thread(list_rows)
        # Applications from before icons existed (or made while they were off) get theirs now.
        queue_favicons([(a["id"], a["url"], [], a.get("company") or "", "") for a in apps
                        if a.get("url") and "favicon" not in a and not a.get("broken")])
        return apps

    def list_rows():
        apps = store.list_apps()
        try:
            profile = store.profile() if store.profile_path.exists() else None
        except Exception:  # noqa: BLE001 — an invalid profile: list without verification
            profile = None
        for a in apps:
            try:
                if a.get("broken"):
                    raise CorruptApp(a["broken"])
                a["outputs_stale"] = store.outputs_stale(a["id"])
                sent = store.sent_copies(a["id"])
                a["sent"] = sent[0] if sent else None
                a["progress"] = progress(a["id"], profile)
                a["reached"], a["reached_at"] = store.reached(a["id"])
                a["task"] = task_view(a["id"], result=False)
            except Exception:  # noqa: BLE001 — one unreadable application never breaks the list
                a["outputs_stale"], a["sent"], a["progress"] = False, None, None
                a["reached"], a["reached_at"], a["task"] = None, None, None
        return apps

    @api.post("/applications", status_code=201)
    async def create_application(body: NewApplication):
        need_profile()
        jd, company, role = body.jd.strip(), body.company, body.role
        sites: list[str] = []  # the company's own website, when the job page names it (for its icon)
        if not jd and body.url:
            try:
                job = await asyncio.wait_for(fetch_job(body.url.strip()), 90)
            except asyncio.TimeoutError:
                raise HTTPException(422, "The job page took too long to load. Paste the job description instead.")
            except FetchError as e:
                raise HTTPException(422, f"{e} Paste the job description instead.")
            except ValueError:
                raise HTTPException(422, "That URL isn't valid. Paste the job description instead.")
            jd, company, role, sites = job.text, company or job.company, role or job.role, job.sites
        if len(jd) < 100:
            raise HTTPException(422, "The job description looks too short — paste the full text.")
        if len(jd) > MAX_JD:
            raise HTTPException(422, f"The job description is very long ({len(jd):,} characters; the limit is "
                                     f"{MAX_JD:,}). Paste just the posting itself.")
        app_id = store.create_app(company or "company", role or "role", jd, body.url)
        if body.url:
            queue_favicons([(app_id, body.url.strip(), sites, company or "", "")])
        return {"id": app_id}

    @api.get("/applications/{app_id}")
    def get_application(app_id: str):
        app_id = need_app(app_id)
        tailored = store.tailored(app_id)
        out = {"id": app_id, "task": task_view(app_id), "meta": store.meta(app_id), "jd": store.jd(app_id),
               "analysis": store.analysis(app_id), "files": store.files(app_id),
               "outputs_stale": store.outputs_stale(app_id),
               "tailored": tailored.model_dump(exclude_none=True) if tailored else None,
               "answers": [a.model_dump(exclude_none=True) for a in store.answers(app_id)],
               "edits": 0, "report": None, "ats": None, "length": None, "critique": critique_payload(app_id),
               "sent": store.sent_copies(app_id, fingerprints=True),
               "letter": None, "letter_report": None, "letter_stale": store.letter_stale(app_id),
               "learning_style": app_id in style_pending,
               "letter_notes": letter_notes(app_id)}
        letter = store.letter(app_id)
        if letter:
            out["letter"] = letter.model_dump()
            if store.profile_path.exists():
                out["letter_report"] = _report_json(factcheck.check_letter(
                    store.profile(), letter, out["jd"] or "", ai.letter_names(out["analysis"])))
        fill = out["meta"].get("fill")
        if fill and fill.get("design") != ai.design_key():  # measured in another design: no longer meaningful
            out["meta"] = {**out["meta"], "fill": None}
        ai_draft = store.ai_tailored(app_id)
        if ai_draft and tailored:
            out["edits"] = len(ai.edited_claims(ai_draft, tailored))
        ai_letter = store.ai_letter(app_id)
        if ai_letter and letter:
            out["edits"] += len(ai.edited_letter(ai_letter, letter))
        if tailored and store.profile_path.exists():
            profile = store.profile()
            report = factcheck.check(profile, tailored)
            out["report"] = _report_json(report)
            if report.ok:  # rendering assumes valid references; never let it break loading
                out["ats"] = _safe_ats(store, app_id, tailored)
                try:
                    out["length"] = {"lines": ai.estimate_lines(profile, tailored),
                                     "budget": ai.length_budget(profile, store.base_tailored())["lines"]}
                except Exception:
                    pass
        return out

    def letter_notes(app_id: str) -> list[dict]:
        """The latest hiring-manager review's issues marked "note for the cover letter"."""
        runs = store.critique(app_id)["runs"]
        issues = runs[-1]["result"].get("issues", []) if runs else []
        return [{"id": i["id"], "text": i.get("problem", "")} for i in issues
                if i.get("note_for") == "cover_letter" and i.get("id")]

    def critique_payload(app_id: str) -> dict | None:
        data = store.critique(app_id)
        if not data["runs"]:
            return None
        latest = data["runs"][-1]
        return {"latest": latest["result"], "created": latest["created"],
                "previous_scores": data["runs"][-2]["result"].get("scores") if len(data["runs"]) > 1 else None,
                "decisions": data["decisions"], "stale": latest["tailored_hash"] != store.tailored_hash(app_id)}

    @api.post("/applications/{app_id}/critique")
    async def run_critique(app_id: str):
        """Hiring-manager + recruiter review of the current draft (on demand)."""
        app_id = need_app(app_id)
        tailored = store.tailored(app_id)
        if not tailored:
            raise HTTPException(409, "Compose a resume first.")
        profile = need_profile()
        if not factcheck.check(profile, tailored).ok:
            raise HTTPException(409, "Fix the fact-check errors first — the review assumes a valid draft.")

        async def work():
            run_no = store.next_critique_run(app_id)  # unique forever, even though only 5 runs are kept
            try:
                result = await hm.critique(engine, profile, tailored, store.analysis(app_id) or {}, store.knowledge(), run_no)
            except EngineError as e:
                raise _engine_call(e)
            except ValidationError as e:
                raise HTTPException(502, f"The model returned an invalid review: {e}")
            store.add_critique_run(app_id, result)
            return get_application(app_id)
        return await run_task(app_id, "critique", "Reviewing as the hiring manager", work)

    @api.put("/applications/{app_id}/critique/decisions")
    def put_critique_decisions(app_id: str, body: Decisions):
        app_id = need_app(app_id)
        store.set_critique_decisions(app_id, body.decisions)
        return critique_payload(app_id)

    @api.patch("/applications/{app_id}")
    async def patch_application(app_id: str, body: MetaPatch):
        app_id = need_app(app_id)
        meta = await asyncio.to_thread(change_application, app_id, body)  # waits on locks: off the event loop
        if body.status == "applied":
            queue_style_learning(app_id)
        return meta

    def change_application(app_id: str, body: MetaPatch) -> dict:
        # The application's lock comes before the store's (as in builds and freezes): taking them the other way
        # round could deadlock against a build of this application.
        with store.app_lock(app_id), store.lock:
            meta = store.meta(app_id)
            # Validate everything before changing anything (a rejected request never freezes).
            if body.outcome and body.status not in (None, "closed"):
                raise HTTPException(422, "An outcome only applies when closing an application.")
            status = body.status or (meta.get("status") if body.outcome else None)
            if body.outcome and status != "closed":
                raise HTTPException(422, "Close the application to record how it ended.")
            if status == "closed" and not body.outcome and not (meta.get("status") == "closed" and meta.get("outcome")):
                raise HTTPException(422, "Say how it ended: pick an outcome to close the application.")
            if status == "applied" and meta.get("status") == "applied":
                pass  # already applied: nothing to freeze or change
            elif status == "applied":
                # Applying freezes the exact files sent (once). If they're missing or stale, the UI
                # offers "Build & freeze" instead of recording a version that doesn't match.
                try:
                    store.mark_applied(app_id, locked=True)
                except NeedsBuild as e:
                    raise HTTPException(409, {"code": "needs_build", "message": str(e)})
            elif status:
                try:
                    store.set_status(app_id, status, body.outcome)
                except ValueError as e:
                    raise HTTPException(422, str(e))
            rest = body.model_dump(exclude_none=True, exclude={"status", "outcome"})
            return store.update_meta(app_id, **rest) if rest else store.meta(app_id)

    @api.delete("/applications/{app_id}", status_code=204)
    def delete_application(app_id: str):
        store.delete_app(need_app(app_id))

    @api.post("/applications/{app_id}/analyze")
    async def analyze(app_id: str):
        app_id = need_app(app_id)
        profile = need_profile()
        return await run_task(app_id, "analyze", "Reading the job description", lambda: analyze_work(app_id, profile))

    async def analyze_work(app_id: str, profile):
        try:
            analysis = await ai.analyze(engine, profile, store.jd(app_id), store.knowledge())
        except EngineError as e:
            raise _engine_call(e)
        store.save_analysis(app_id, analysis)
        store.remap_answers(app_id, analysis.get("questions", []))  # question ids are renumbered
        meta = store.meta(app_id)
        changes = {}
        placeholder = meta.get("company") in (None, "", "company")
        if placeholder:
            changes["company"] = analysis.get("company")
        if meta.get("role") in (None, "", "role"):
            changes["role"] = analysis.get("role")
        if changes:
            store.update_meta(app_id, **changes)
        store.advance_status(app_id, "analyzed")
        if placeholder:
            app_id = store.rename_app(app_id, changes["company"] or "", changes.get("role") or meta.get("role", ""))
        queue_analysis_favicon(app_id, analysis)
        return get_application(app_id)

    def queue_analysis_favicon(app_id: str, analysis: dict) -> None:
        """No icon yet: try the company website the analysis names (once per website), for job boards that don't
        name it and for pasted job descriptions. It still has to pass favicon.matches_company."""
        site = favicon.clean_site(analysis.get("company_website"))
        meta = store.meta(app_id)
        if site and not store.favicon_path(app_id) and meta.get("favicon_website") != site:
            job = (app_id, "", [], analysis.get("company") or meta.get("company") or "", site)
            if app_id in favicon_pending:
                favicon_next[app_id] = job  # after the attempt in progress, if that finds nothing
            else:
                queue_favicons([job])

    @api.post("/applications/{app_id}/proposals")
    async def proposals(app_id: str, answers: list[Answer]):
        app_id = need_app(app_id)
        profile = need_profile()

        async def work():
            try:
                return await ai.propose_evidence(engine, profile, [a.model_dump() for a in answers])
            except EngineError as e:
                raise _engine_call(e)
        label = f"Drafting evidence from {len(answers)} answers" if len(answers) > 1 else "Drafting evidence from your answer"
        return await run_task(app_id, "proposals", label, work)

    @api.post("/applications/{app_id}/compose")
    async def compose(app_id: str, body: ComposeIn):
        app_id = need_app(app_id)
        analysis = store.analysis(app_id)
        if not analysis:
            raise HTTPException(409, "Analyze the job description first.")
        profile = need_profile()
        refuse_if_running(app_id)  # before saving the guidance
        store.update_meta(app_id, guidance=body.guidance.strip())  # kept even if the AI call fails

        async def work():
            try:
                result = await ai.compose(engine, profile, analysis, store.base_tailored(), body.guidance,
                                          store.knowledge().active_preferences())
            except EngineError as e:
                raise _engine_call(e)
            except ValidationError as e:
                raise HTTPException(502, f"The model returned an invalid resume structure: {e}")
            store.save_tailored(app_id, result["tailored"])
            store.save_ai_tailored(app_id, result["tailored"])
            store.update_meta(app_id, repair_rounds=result["repair_rounds"], trim_rounds=result["trim_rounds"])
            store.advance_status(app_id, "composed")
            return get_application(app_id)
        return await run_task(app_id, "compose", "Composing your tailored resume", work)

    @api.post("/applications/{app_id}/trim")
    async def trim(app_id: str):
        """Shorten the current resume with the AI (after a build came out over the page limit)."""
        app_id = need_app(app_id)
        tailored, analysis = store.tailored(app_id), store.analysis(app_id) or {}
        if not tailored:
            raise HTTPException(409, "Nothing to trim yet.")
        profile = need_profile()
        if not factcheck.check(profile, tailored).ok:
            raise HTTPException(409, "Fix the fact-check errors before trimming.")
        budget = ai.length_budget(profile, store.base_tailored())["lines"]
        current = ai.estimate_lines(profile, tailored)
        # The build overflowed, so aim clearly below both the budget and the current length.
        target = min(budget, current) - 6

        async def work():
            try:
                result = await ai.fit_to_length(engine, profile, tailored, analysis, target, max_rounds=1)
            except EngineError as e:
                raise _engine_call(e)
            # Never saved here: the user reviews the shorter version and saves it (PUT /tailored).
            proposal = None
            trimmed = result["tailored"]
            if result["trim_rounds"] and trimmed is not tailored and \
                    trimmed.model_dump(exclude_none=True) != tailored.model_dump(exclude_none=True) and \
                    factcheck.check(profile, trimmed).ok:
                proposal = {"tailored": trimmed.model_dump(exclude_none=True), "lines": ai.estimate_lines(profile, trimmed),
                            "budget": budget, "trim_rounds": result["trim_rounds"]}
            return {**get_application(app_id), "trim_proposal": proposal}
        return await run_task(app_id, "trim", f"Trimming to {ai.pages_text()}", work)

    @api.post("/applications/{app_id}/fill")
    async def fill_page(app_id: str):
        """Use the room left on the last page of the built PDF with relevant evidence the resume doesn't use
        yet. Never saved here: the UI loads the proposal into Review as unsaved edits (like /trim)."""
        app_id = need_app(app_id)
        tailored, analysis, meta = store.tailored(app_id), store.analysis(app_id) or {}, store.meta(app_id)
        if not tailored:
            raise HTTPException(409, "Nothing to fill yet.")
        fill = meta.get("fill") or {}
        room = fill.get("room", 0)
        if store.outputs_stale(app_id) or not meta.get("pages") or fill.get("design") != ai.design_key():
            raise HTTPException(409, "Build the PDF first, so TailorbirdCV can measure the room left on the last page.")
        if meta["pages"] > page_limit():
            raise HTTPException(409, f"The PDF is over the {page_limit()}-page limit: trim it instead.")
        if room < fit.ROOM_MIN_LINES:
            raise HTTPException(409, "The last page is already full enough.")
        profile = need_profile()
        if not factcheck.check(profile, tailored).ok:
            raise HTTPException(409, "Fix the fact-check errors first.")

        async def work():
            try:
                filled = await ai.fill(engine, profile, tailored, analysis, room, store.ai_tailored(app_id))
            except EngineError as e:
                raise _engine_call(e)
            proposal = None
            if filled is not None and filled.model_dump(exclude_none=True) != tailored.model_dump(exclude_none=True):
                proposal = {"tailored": filled.model_dump(exclude_none=True), "room": room,
                            "added_lines": ai.estimate_lines(profile, filled) - ai.estimate_lines(profile, tailored)}
            return {**get_application(app_id), "fill_proposal": proposal}
        return await run_task(app_id, "fill", "Filling the last page", work)

    @api.put("/applications/{app_id}/tailored")
    def put_tailored(app_id: str, data: dict):
        app_id = need_app(app_id)
        try:
            tailored = TailoredResume.model_validate(data)
        except ValidationError as e:
            raise HTTPException(422, str(e))
        store.save_tailored(app_id, tailored)
        return get_application(app_id)

    async def do_build(app_id: str, pdf: bool = True) -> int | None:
        need_profile()
        lock = store.app_lock(app_id)  # one build/freeze/delete per application at a time
        await asyncio.to_thread(lock.acquire)
        try:
            return await _build_locked(app_id, pdf)
        finally:
            lock.release()

    async def _build_locked(app_id: str, pdf: bool) -> int | None:
        try:  # the hashes recorded are of exactly the bytes rendered
            tailored, built_hash, profile, profile_version = store.build_inputs(app_id)
        except FileNotFoundError:
            raise HTTPException(409, "Nothing to build yet.")
        except (ValidationError, ValueError, yaml.YAMLError) as e:
            raise HTTPException(409, f"The resume or profile can't be read: {e}")
        report = factcheck.check(profile, tailored)
        if not report.ok:
            raise HTTPException(409, "Fact-check failed — fix the errors before building.")
        try:
            store.clear_outputs(app_id)  # never leave an older .docx/.pdf around to be sent by mistake
        except OutputInUse as e:
            raise HTTPException(409, str(e))
        docx = render(profile, tailored, store.app_path(app_id) / f"{store.output_stem(app_id)}.docx")
        pages, fill = None, None
        if pdf:
            preferred = store.settings()["pdf_engine"]
            try:
                name = pdfmod.NAMES[await asyncio.to_thread(pdfmod.resolve, preferred)]
            except RuntimeError as e:  # neither Word nor LibreOffice
                store.record_build(app_id, built_hash, profile_version, None)
                raise HTTPException(500, f"DOCX built, but no PDF: {e}")
            pdf_file = None
            try:
                pdf_file = await asyncio.to_thread(pdfmod.to_pdf, docx, engine=preferred)
                pages = pdfmod.page_count(pdf_file)
            except Exception as e:  # no engine / automation permission denied / timeout / unreadable PDF
                if pdf_file is not None:
                    pdf_file.unlink(missing_ok=True)  # a PDF we couldn't check must not be sent or frozen
                store.record_build(app_id, built_hash, profile_version, None)
                raise HTTPException(500, f"DOCX built, but PDF conversion via {name} failed: {e}")
            try:
                fill = await asyncio.to_thread(ai.measure_pdf, profile, tailored, pdf_file, store.lock)
            except Exception:  # measuring is a nicety: never fail a build over it
                fill = None
        store.record_build(app_id, built_hash, profile_version, pages, fill)
        store.advance_status(app_id, "built")
        return pages

    @api.post("/applications/{app_id}/build")
    async def build(app_id: str, pdf: bool = True):
        app_id = need_app(app_id)
        pages = await do_build(app_id, pdf)
        out = get_application(app_id)
        out["build"] = {"pages": pages, "too_long": bool(pages and pages > page_limit())}
        return out

    # -- cover letter ---------------------------------------------------------------------------------------
    @api.post("/applications/{app_id}/letter")
    async def write_letter(app_id: str, body: LetterIn):
        """Draft the cover letter with the AI (fact-checked sentence by sentence, repaired up to 3 times)."""
        app_id = need_app(app_id)
        analysis, tailored, profile = store.analysis(app_id), store.tailored(app_id), need_profile()
        if not analysis or not tailored:
            raise HTTPException(409, "Write the tailored resume first: the letter tells the same story.")
        if not factcheck.check(profile, tailored).ok:
            raise HTTPException(409, "The resume doesn't pass the fact-check yet. Fix it first.")
        wanted = {n["id"]: n["text"] for n in letter_notes(app_id)}
        notes = [wanted[i] for i in body.notes if i in wanted]

        async def work():
            try:
                result = await ai.compose_letter(engine, profile, tailored, analysis, store.jd(app_id) or "", body.tone,
                                                 body.recipient, notes, store.knowledge().active_preferences())
            except EngineError as e:
                raise _engine_call(e)
            except ValidationError as e:
                raise HTTPException(502, f"The model returned an invalid letter: {e}")
            store.save_letter(app_id, result["letter"])
            store.save_ai_letter(app_id, result["letter"])
            store.update_meta(app_id, letter_repair_rounds=result["repair_rounds"])
            return get_application(app_id)
        return await run_task(app_id, "letter", "Writing your cover letter", work)

    @api.put("/applications/{app_id}/letter")
    def save_letter(app_id: str, letter: CoverLetter):
        """Save edits (the response's letter_report is the fact-check of what was saved)."""
        app_id = need_app(app_id)
        store.save_letter(app_id, letter)
        return get_application(app_id)

    @api.delete("/applications/{app_id}/letter")
    def delete_letter(app_id: str):
        """Remove the cover letter (draft and built files): this application is sent without one."""
        app_id = need_app(app_id)
        try:
            store.delete_letter(app_id)
        except OutputInUse as e:
            raise HTTPException(409, str(e))
        return get_application(app_id)

    async def do_build_letter(app_id: str) -> int | None:
        lock = store.app_lock(app_id)
        await asyncio.to_thread(lock.acquire)
        try:
            return await _build_letter_locked(app_id)
        finally:
            lock.release()

    async def _build_letter_locked(app_id: str) -> int | None:
        path = store.app_path(app_id) / "letter.yaml"
        if not path.exists():
            raise HTTPException(409, "Write the cover letter first.")
        from .store import file_version
        need_profile()
        with store.lock:  # the hashes recorded are of what is rendered
            built_hash, profile_version = store.letter_hash(app_id), file_version(store.profile_path)
            letter, profile, tailored = store.letter(app_id), store.profile(), store.tailored(app_id)
        analysis = store.analysis(app_id) or {}
        if tailored is None:
            raise HTTPException(409, "Write the tailored resume first.")
        if not factcheck.check_letter(profile, letter, store.jd(app_id) or "", ai.letter_names(analysis)).ok:
            raise HTTPException(409, "Fact-check failed — fix the letter's errors before building.")
        try:
            store.clear_outputs(app_id, letter=True)
        except OutputInUse as e:
            raise HTTPException(409, str(e))
        docx = render_letter(profile, letter, store.app_path(app_id) / f"{store.letter_stem(app_id)}.docx",
                             headline_id=tailored.headline, company=analysis.get("company") or "",
                             role=analysis.get("role") or "", location=analysis.get("location") or "",
                             spelling=store.settings()["targets"].get("spelling", "US"))
        preferred = store.settings()["pdf_engine"]
        pdf_file = None
        try:
            pdf_file = await asyncio.to_thread(pdfmod.to_pdf, docx, engine=preferred)
            pages = pdfmod.page_count(pdf_file)
        except Exception as e:  # noqa: BLE001
            if pdf_file is not None:
                pdf_file.unlink(missing_ok=True)
            store.record_letter_build(app_id, built_hash, profile_version, None)
            raise HTTPException(500, f"DOCX built, but the PDF conversion failed: {e}")
        if pages > 1:
            store.clear_outputs(app_id, letter=True)  # a cover letter is one page: never send a longer one
            raise HTTPException(409, f"The letter came out at {pages} pages. Shorten it to one page, then build again.")
        store.record_letter_build(app_id, built_hash, profile_version, pages)
        return pages

    @api.post("/applications/{app_id}/letter/build")
    async def build_letter(app_id: str):
        app_id = need_app(app_id)
        await do_build_letter(app_id)
        return get_application(app_id)

    @api.post("/applications/{app_id}/freeze")
    async def freeze(app_id: str, build: bool = False, mark_applied: bool = False):
        """Freeze a read-only copy of what's being sent. `build=true` rebuilds first
        ("Build & freeze"); `mark_applied=true` then records the application as applied."""
        app_id = need_app(app_id)
        if build:
            if store.letter_files(app_id):  # a built cover letter goes with the resume: rebuild it too
                await do_build_letter(app_id)
            pages = await do_build(app_id, pdf=True)
            if pages and pages > page_limit():
                raise HTTPException(409, {"code": "too_long", "message":
                                          f"The PDF is {pages} pages — trim it before sending. Nothing was frozen."})
        try:  # in a worker thread: waiting for a build of this application must never stall the server
            if mark_applied:
                await asyncio.to_thread(store.mark_applied, app_id)  # freezes once; clears any closed outcome
                queue_style_learning(app_id)
            else:
                await asyncio.to_thread(store.freeze, app_id, "manual copy")
        except NeedsBuild as e:
            raise HTTPException(409, {"code": "needs_build", "message": str(e)})
        return await asyncio.to_thread(get_application, app_id)

    @api.post("/identify")
    async def identify_pdf(body: PdfUpload):
        """Which application a PDF came from (Applications → Identify a PDF). Read-only: the PDF
        is compared with the sent copies and current builds, never stored."""
        import base64
        import binascii
        try:
            raw = base64.b64decode(body.data, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "The file couldn't be read.")
        if not raw.lstrip()[:5].startswith(b"%PDF"):
            raise HTTPException(422, "That isn't a PDF.")
        return await asyncio.to_thread(store.identify, raw)

    @api.get("/applications/{app_id}/sent/{snapshot}/{name}")
    def get_sent_file(app_id: str, snapshot: str, name: str, download: bool = False):
        app_id = need_app(app_id)
        try:
            path = store.sent_file(app_id, snapshot, name)
        except KeyError:
            raise HTTPException(404, "file not found")
        media = {".pdf": "application/pdf", ".md": "text/markdown"}.get(
            path.suffix, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        return FileResponse(path, media_type=media, filename=name,
                            content_disposition_type="attachment" if download else "inline")

    # -- profile / knowledge history ----------------------------------------------------------
    def need_kind(kind: str) -> str:
        if kind not in store.HISTORY_KINDS:
            raise HTTPException(404, "unknown history")
        return kind

    @api.get("/history/{kind}")
    def list_history(kind: str):
        return store.history(need_kind(kind))

    @api.get("/history/{kind}/{snapshot_id}")
    def history_diff(kind: str, snapshot_id: str):
        need_kind(kind)
        try:
            old_text = store.history_text(kind, snapshot_id)
        except KeyError:
            raise HTTPException(404, "snapshot not found")
        path = store.profile_path if kind == "profile" else store.knowledge_path
        current_text = oscompat.read_text(path) if path.exists() else ""
        return {"id": snapshot_id, "yaml": old_text,
                "summary": history_summary(kind, old_text, current_text),
                "diff": "".join(difflib.unified_diff(old_text.splitlines(keepends=True),
                                                     current_text.splitlines(keepends=True),
                                                     "this version", "current", n=2))}

    @api.post("/history/{kind}/{snapshot_id}/restore")
    def restore_history(kind: str, snapshot_id: str):
        need_kind(kind)
        try:
            store.restore(kind, snapshot_id)
        except KeyError:
            raise HTTPException(404, "snapshot not found")
        except RetiredIdReused as e:
            raise HTTPException(422, str(e))
        except (ValidationError, ValueError) as e:
            raise HTTPException(422, f"That version can't be restored (it no longer validates): {e}")
        return profile_payload() if kind == "profile" else knowledge_payload()

    # -- gap answers + memory -------------------------------------------------------------
    @api.put("/applications/{app_id}/answers")
    def put_answers(app_id: str, answers: list[AppAnswer]):
        app_id = need_app(app_id)
        store.save_answers(app_id, answers)
        return [a.model_dump(exclude_none=True) for a in store.answers(app_id)]

    @api.get("/knowledge")
    def get_knowledge():
        return knowledge_payload()

    @api.put("/knowledge")
    def put_knowledge(data: dict, if_match: str | None = Header(default=None)):
        need_version(if_match)
        data = {k: v for k, v in data.items() if k != "version"}
        try:
            return knowledge_payload(store.save_knowledge(Knowledge.model_validate(data), base_version=if_match,
                                                          cause="answers & preferences editor"))
        except Conflict as e:
            raise HTTPException(409, str(e))
        except (ValidationError, RetiredIdReused, IncompleteRole) as e:
            raise HTTPException(422, str(e))

    def style_material(app_id: str) -> tuple[list[dict], list[str], list[dict]]:
        """What the user changed from the AI's drafts (resume and cover letter), the guidance they
        gave, and the review suggestions they rejected: what style preferences are learned from."""
        ai_draft, current = store.ai_tailored(app_id), store.tailored(app_id)
        edits = ai.edited_claims(ai_draft, current) if ai_draft and current else []
        ai_letter, letter = store.ai_letter(app_id), store.letter(app_id)
        if ai_letter and letter:
            edits += ai.edited_letter(ai_letter, letter)
        guidance = [store.meta(app_id).get("guidance") or ""]
        review = store.critique(app_id)
        rejected = [{"line": i.get("original", {}).get("text", i.get("where")), "suggested": i["rewrite"]["text"],
                     "problem": i.get("problem", "")}
                    for run in review["runs"] for i in run["result"].get("issues", [])
                    if review["decisions"].get(i["id"]) == "rejected" and i.get("rewrite")]
        return edits, guidance, rejected

    def style_fingerprint(material) -> str:
        return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]

    async def learn_style(app_id: str) -> tuple[int, int]:
        """Propose style preferences from this application (never active until the user approves
        them). Returns (edits seen, preferences proposed)."""
        material = await asyncio.to_thread(style_material, app_id)
        edits, guidance, rejected = material
        existing = [p for p in store.knowledge().preferences if p.status != "dismissed"]
        proposals = await ai.learn_preferences(engine, edits, guidance, existing, rejected)
        today = f"{dt.date.today():%Y-%m-%d}"
        with store.editing_knowledge(cause="preferences suggested") as knowledge:  # fresh copy after the AI call
            for prop in proposals:
                taken = {x.id for x in knowledge.preferences} | set(knowledge.retired_ids)
                knowledge.preferences.append(Preference(
                    id=next_id("p", taken), text=prop["text"].strip(), rationale=prop.get("rationale", ""),
                    status="proposed", source_app=app_id, date=today))
        await asyncio.to_thread(store.update_meta, app_id, style_learned=style_fingerprint(material))
        return len(edits), len(proposals)

    # Marking an application applied studies what the user changed before sending it, in the
    # background (Settings → Applications → learn_style). Each version of the edits is studied once.
    style_pending: set[str] = set()
    style_tasks: set = set()  # keeps the running tasks referenced

    async def learn_style_quietly(app_id: str) -> None:
        try:
            material = await asyncio.to_thread(style_material, app_id)
            edits, guidance, rejected = material
            if (edits or rejected or any(g.strip() for g in guidance)) and \
                    store.meta(app_id).get("style_learned") != style_fingerprint(material):
                await learn_style(app_id)
        except Exception as e:  # noqa: BLE001 — a suggestion is never worth an error; the button still works
            log.info("TailorbirdCV: learning style from %s failed (%s)", app_id, e)
        finally:
            style_pending.discard(app_id)

    def queue_style_learning(app_id: str) -> None:
        if app_id in style_pending or not store.settings()["learn_style"]:
            return
        style_pending.add(app_id)
        task = asyncio.get_running_loop().create_task(learn_style_quietly(app_id))  # keeps this request's context
        style_tasks.add(task)
        task.add_done_callback(style_tasks.discard)

    @api.post("/applications/{app_id}/preferences")
    async def suggest_preferences(app_id: str):
        """Propose style preferences from this application's guidance and Review edits."""
        app_id = need_app(app_id)
        try:
            edits, proposed = await learn_style(app_id)
        except EngineError as e:
            raise _engine_call(e)
        return {"edits": edits, "proposed": proposed, "knowledge": knowledge_payload()}

    @api.post("/applications/{app_id}/reveal", status_code=204)
    def reveal(app_id: str, snapshot: str | None = None):
        """Show the application folder (or a sent copy) in Finder / Explorer / the file manager with
        the PDF selected, so the exact file can be uploaded from there — no "(1)" duplicates."""
        app_id = need_app(app_id)
        path = store.app_path(app_id)
        if snapshot:
            sent = next((c for c in store.sent_copies(app_id) if c["id"] == snapshot), None)
            if not sent:
                raise HTTPException(404, "sent copy not found")
            path = store.sent_dir(app_id) / snapshot
            files = sent["files"]
        else:
            files = store.files(app_id)
        files = sorted(files, key=store.is_letter_file)  # the resume first, then the cover letter
        pdf = next((path / f for f in files if f.endswith(".pdf")), None)
        target = pdf or next((path / f for f in files if f.endswith(".docx")), None)
        try:
            oscompat.reveal(target, path)
        except OSError as e:
            raise HTTPException(500, f"Couldn't open the folder: {e}")

    @api.get("/applications/{app_id}/favicon")
    def get_favicon(app_id: str):
        """The company's site icon, from the application's folder (the browser never loads it from the site)."""
        path = store.favicon_path(need_app(app_id))
        if not path:
            raise HTTPException(404, "no icon")
        media = {".ico": "image/x-icon", ".png": "image/png", ".gif": "image/gif", ".jpg": "image/jpeg",
                 ".webp": "image/webp", ".svg": "image/svg+xml"}[path.suffix]
        # Scripts are blocked even if an SVG icon is opened directly (an <img> never runs them anyway).
        return FileResponse(path, media_type=media, headers={
            "Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"})

    @api.get("/applications/{app_id}/files/{name}")
    def get_file(app_id: str, name: str, download: bool = False):
        app_id = need_app(app_id)
        path = store.app_path(app_id)
        if name not in store.files(app_id):
            raise HTTPException(404, "file not found")
        media = "application/pdf" if name.endswith(".pdf") else \
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return FileResponse(path / name, media_type=media,
                            content_disposition_type="attachment" if download else "inline", filename=name)

    app.include_router(api)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def unknown_api(path: str):
        # Otherwise these fall through to the page route and surface as a cryptic
        # "405 Method Not Allowed" — typically a server started before an update.
        raise HTTPException(404, "Unknown TailorbirdCV endpoint. If you just updated TailorbirdCV, restart the server "
                                 "(Ctrl+C, then `tailorbirdcv serve`, or `uv run tailorbirdcv serve` in a source checkout).")

    dist = paths.web_dir()
    if dist:
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "not found")
            file = (dist / path).resolve()
            if path and file.is_file() and file.is_relative_to(dist):
                return FileResponse(file)
            # always revalidate the page so a rebuilt UI shows up after a restart (assets are hashed)
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app
