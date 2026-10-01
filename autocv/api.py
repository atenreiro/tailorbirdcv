"""FastAPI backend for the AutoCV web UI (localhost only).

    uv run autocv serve            → http://127.0.0.1:8000 (serves web/dist if built)
    cd web && npm run dev          → http://localhost:5173 (proxies /api to :8000)
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ValidationError

from . import ai, ats, factcheck
from .engine import Engine, EngineError, default_engine
from .render import docx_text, render
from .schema import TailoredResume
from .store import ROOT, STATUSES, Store

MAX_PAGES = 2


# --------------------------------------------------------------------------- request models


class NewApplication(BaseModel):
    jd: str = ""
    url: str | None = None
    company: str = ""
    role: str = ""


class MetaPatch(BaseModel):
    status: Literal[tuple(STATUSES)] | None = None  # type: ignore[valid-type]
    notes: str | None = None
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


class ProfileYaml(BaseModel):
    yaml: str


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


MAX_REDIRECTS = 5
MAX_PAGE_BYTES = 3_000_000


async def _check_public_url(url: str) -> None:
    """SSRF guard: only http(s) to hosts that resolve exclusively to public addresses."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(422, "The URL must start with http:// or https://")
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or None)
    except socket.gaierror:
        raise HTTPException(422, f"Could not resolve {parsed.hostname}. Paste the job description instead.")
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise HTTPException(422, "That URL points to a private or local network address, so AutoCV won't fetch it.")


async def _fetch_url(url: str) -> str:
    import httpx
    from bs4 import BeautifulSoup

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=20,
                                     headers={"User-Agent": "Mozilla/5.0 AutoCV"}) as client:
            for _ in range(MAX_REDIRECTS + 1):  # follow redirects by hand, re-checking every hop
                await _check_public_url(url)
                async with client.stream("GET", url) as resp:
                    if resp.is_redirect:
                        url = str(resp.url.join(resp.headers.get("location", "")))
                        continue
                    resp.raise_for_status()
                    body = b""
                    async for chunk in resp.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_PAGE_BYTES:
                            raise HTTPException(422, "That page is too large. Paste the job description instead.")
                    html = body.decode(resp.encoding or "utf-8", errors="replace")
                    break
            else:
                raise HTTPException(422, "Too many redirects. Paste the job description instead.")
    except httpx.HTTPError as e:
        raise HTTPException(422, f"Could not fetch the URL ({e}). Paste the job description instead.")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg"]):
        tag.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    if len(text) < 300:
        raise HTTPException(422, "The page returned too little text (it may need a login or JavaScript). "
                                 "Paste the job description instead.")
    return text


def _engine_call(exc: EngineError) -> HTTPException:
    return HTTPException(503, f"AI engine error: {exc}")


# --------------------------------------------------------------------------- app


def create_app(store: Store | None = None, engine: Engine | None = None) -> FastAPI:
    store = store or Store.default()
    engine = engine or default_engine()
    app = FastAPI(title="AutoCV", docs_url="/api/docs", openapi_url="/api/openapi.json")
    # DNS-rebinding guard: a malicious site can't reach this local API through a hostname it controls.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
    api = APIRouter(prefix="/api")

    def need_app(app_id: str) -> str:
        try:
            store.app_path(app_id)
        except KeyError:
            raise HTTPException(404, "application not found")
        return app_id

    def need_profile():
        if not store.profile_path.exists():
            raise HTTPException(409, "No master profile yet — run `uv run autocv ingest` first.")
        return store.profile()

    # -- engine / profile ------------------------------------------------------------
    @api.get("/engine")
    async def engine_status():
        return await engine.status()

    @api.get("/profile")
    def get_profile():
        profile = need_profile()
        return {"profile": profile.model_dump(exclude_none=True),
                "evidence": factcheck.evidence_index(profile)}

    @api.put("/profile")
    def put_profile(data: dict):
        need_profile()
        try:
            profile = store.save_profile(data)
        except ValidationError as e:
            raise HTTPException(422, str(e))
        return {"profile": profile.model_dump(exclude_none=True),
                "evidence": factcheck.evidence_index(profile)}

    @api.get("/profile/yaml")
    def get_profile_yaml():
        need_profile()
        return {"yaml": store.profile_path.read_text(encoding="utf-8")}

    @api.put("/profile/yaml")
    def put_profile_yaml(body: ProfileYaml):
        need_profile()
        try:
            data = yaml.safe_load(body.yaml)
            store.save_profile(data)
        except (yaml.YAMLError, ValidationError, TypeError) as e:
            raise HTTPException(422, str(e))
        return get_profile_yaml()

    @api.post("/profile/evidence")
    def post_evidence(body: EvidenceIn):
        profile = need_profile()
        try:
            profile, new_id = ai.add_evidence(profile, body.target, body.text, body.skills, body.note)
        except KeyError:
            raise HTTPException(422, f"unknown role '{body.target}'")
        store.save_profile(profile.model_dump(exclude_none=True))
        return {"id": new_id, "evidence": factcheck.evidence_index(profile)}

    # -- applications ------------------------------------------------------------------
    @api.get("/applications")
    def list_applications():
        return store.list_apps()

    @api.post("/applications", status_code=201)
    async def create_application(body: NewApplication):
        need_profile()
        jd = body.jd.strip()
        if not jd and body.url:
            jd = await _fetch_url(body.url)
        if len(jd) < 100:
            raise HTTPException(422, "The job description looks too short — paste the full text.")
        app_id = store.create_app(body.company or "company", body.role or "role", jd, body.url)
        return {"id": app_id}

    @api.get("/applications/{app_id}")
    def get_application(app_id: str):
        need_app(app_id)
        tailored = store.tailored(app_id)
        out = {"id": app_id, "meta": store.meta(app_id), "jd": store.jd(app_id),
               "analysis": store.analysis(app_id), "files": store.files(app_id),
               "tailored": tailored.model_dump(exclude_none=True) if tailored else None,
               "report": None, "ats": None}
        if tailored and store.profile_path.exists():
            out["report"] = _report_json(factcheck.check(store.profile(), tailored))
            out["ats"] = _ats_json(store, app_id, tailored)
        return out

    @api.patch("/applications/{app_id}")
    def patch_application(app_id: str, body: MetaPatch):
        need_app(app_id)
        return store.update_meta(app_id, **body.model_dump(exclude_none=True))

    @api.delete("/applications/{app_id}", status_code=204)
    def delete_application(app_id: str):
        import shutil
        shutil.rmtree(store.app_path(need_app(app_id)))

    @api.post("/applications/{app_id}/analyze")
    async def analyze(app_id: str):
        need_app(app_id)
        try:
            analysis = await ai.analyze(engine, need_profile(), store.jd(app_id))
        except EngineError as e:
            raise _engine_call(e)
        store.save_analysis(app_id, analysis)
        meta = store.meta(app_id)
        changes = {"status": "analyzed"}
        placeholder = meta.get("company") in (None, "", "company")
        if placeholder:
            changes["company"] = analysis.get("company")
        if meta.get("role") in (None, "", "role"):
            changes["role"] = analysis.get("role")
        store.update_meta(app_id, **changes)
        if placeholder:
            app_id = store.rename_app(app_id, changes["company"] or "", changes.get("role") or meta.get("role", ""))
        return get_application(app_id)

    @api.post("/applications/{app_id}/proposals")
    async def proposals(app_id: str, answers: list[Answer]):
        need_app(app_id)
        try:
            return await ai.propose_evidence(engine, need_profile(), [a.model_dump() for a in answers])
        except EngineError as e:
            raise _engine_call(e)

    @api.post("/applications/{app_id}/compose")
    async def compose(app_id: str, body: ComposeIn):
        need_app(app_id)
        analysis = store.analysis(app_id)
        if not analysis:
            raise HTTPException(409, "Analyze the job description first.")
        try:
            result = await ai.compose(engine, need_profile(), analysis, store.base_tailored(), body.guidance)
        except EngineError as e:
            raise _engine_call(e)
        except ValidationError as e:
            raise HTTPException(502, f"The model returned an invalid resume structure: {e}")
        store.save_tailored(app_id, result["tailored"])
        store.update_meta(app_id, status="composed", repair_rounds=result["repair_rounds"])
        return get_application(app_id)

    @api.put("/applications/{app_id}/tailored")
    def put_tailored(app_id: str, data: dict):
        need_app(app_id)
        try:
            tailored = TailoredResume.model_validate(data)
        except ValidationError as e:
            raise HTTPException(422, str(e))
        store.save_tailored(app_id, tailored)
        return get_application(app_id)

    @api.post("/applications/{app_id}/build")
    async def build(app_id: str, pdf: bool = True):
        need_app(app_id)
        tailored = store.tailored(app_id)
        if not tailored:
            raise HTTPException(409, "Nothing to build yet.")
        profile = need_profile()
        report = factcheck.check(profile, tailored)
        if not report.ok:
            raise HTTPException(409, "Fact-check failed — fix the errors before building.")
        path = store.app_path(app_id)
        for old in path.glob("*.pdf"):
            old.unlink()
        docx = render(profile, tailored, path / f"{store.output_stem(app_id)}.docx")
        pages = None
        if pdf:
            from .pdf import page_count, to_pdf
            try:
                pages = page_count(await asyncio.to_thread(to_pdf, docx))
            except Exception as e:  # Word missing / automation permission denied
                raise HTTPException(500, f"DOCX built, but PDF conversion via Word failed: {e}")
        store.update_meta(app_id, status="built", pages=pages)
        out = get_application(app_id)
        out["build"] = {"pages": pages, "too_long": bool(pages and pages > MAX_PAGES)}
        return out

    @api.get("/applications/{app_id}/files/{name}")
    def get_file(app_id: str, name: str, download: bool = False):
        path = store.app_path(need_app(app_id))
        if name not in store.files(app_id):
            raise HTTPException(404, "file not found")
        media = "application/pdf" if name.endswith(".pdf") else \
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return FileResponse(path / name, media_type=media,
                            content_disposition_type="attachment" if download else "inline", filename=name)

    app.include_router(api)

    dist = ROOT / "web" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "not found")
            file = (dist / path).resolve()
            if path and file.is_file() and file.is_relative_to(dist):
                return FileResponse(file)
            return FileResponse(dist / "index.html")

    return app
