"""FastAPI backend for the AutoCV web UI (localhost only).

    uv run autocv serve            → http://127.0.0.1:8000 (serves web/dist if built)
    cd web && npm run dev          → http://localhost:5173 (proxies /api to :8000)
"""

from __future__ import annotations

import asyncio
import datetime as dt
import difflib
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ValidationError

from . import ai, ats, critique as hm, factcheck
from .jobfetch import FetchError, fetch_job
from .engine import Engine, EngineError, default_engine
from .render import docx_text, render
from .schema import AppAnswer, Knowledge, Preference, TailoredResume
from .store import ROOT, STATUSES, Conflict, NeedsBuild, Store, next_id

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


def create_app(store: Store | None = None, engine: Engine | None = None,
               allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "[::1]")) -> FastAPI:
    store = store or Store.default()
    engine = engine or default_engine()
    app = FastAPI(title="AutoCV", docs_url="/api/docs", openapi_url="/api/openapi.json")
    # DNS-rebinding guard: a malicious site can't reach this local API through a hostname it controls.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Cross-site guard: a page on another site can send "simple" POSTs to localhost without
        # a preflight. Requiring a custom header forces a CORS preflight, which this API never
        # grants, so only the AutoCV UI itself can change data or start AI runs.
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS") \
                and request.headers.get("x-autocv") != "1":
            return JSONResponse({"detail": "Missing X-AutoCV header (cross-site request refused)."}, status_code=403)
        response = await call_next(request)
        # Anti-clickjacking: other sites can't frame AutoCV; AutoCV may frame itself
        # (the Export step previews the PDF in an iframe).
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
        return response

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

    def profile_payload(profile=None):
        profile = profile or store.profile()
        return {"profile": profile.model_dump(exclude_none=True), "evidence": factcheck.evidence_index(profile),
                "version": store.profile_version()}

    def knowledge_payload(knowledge=None):
        return {**(knowledge or store.knowledge()).model_dump(exclude_none=True), "version": store.knowledge_version()}

    # -- engine / profile ------------------------------------------------------------
    @api.get("/engine")
    async def engine_status():
        return await engine.status()

    @api.get("/profile")
    def get_profile():
        return profile_payload(need_profile())

    @api.put("/profile")
    def put_profile(data: dict, if_match: str | None = Header(default=None)):
        need_profile()
        try:
            profile = store.save_profile(data, base_version=if_match, cause="profile editor")
        except Conflict as e:
            raise HTTPException(409, str(e))
        except ValidationError as e:
            raise HTTPException(422, str(e))
        return profile_payload(profile)

    @api.get("/profile/yaml")
    def get_profile_yaml():
        need_profile()
        return {"yaml": store.profile_path.read_text(encoding="utf-8"), "version": store.profile_version()}

    @api.put("/profile/yaml")
    def put_profile_yaml(body: ProfileYaml, if_match: str | None = Header(default=None)):
        need_profile()
        try:
            data = yaml.safe_load(body.yaml)
            store.save_profile(data, base_version=if_match, cause="yaml edit")
        except Conflict as e:
            raise HTTPException(409, str(e))
        except (yaml.YAMLError, ValidationError, TypeError) as e:
            raise HTTPException(422, str(e))
        return get_profile_yaml()

    @api.post("/profile/evidence")
    def post_evidence(body: EvidenceIn):
        need_profile()
        with store.lock:
            try:
                profile, new_id = ai.add_evidence(store.profile(), body.target, body.text, body.skills, body.note)
            except KeyError:
                raise HTTPException(422, f"unknown role '{body.target}'")
            store.save_profile(profile.model_dump(exclude_none=True), cause="evidence approved")
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

    @api.get("/applications")
    def list_applications():
        apps = store.list_apps()
        profile = store.profile() if store.profile_path.exists() else None
        for a in apps:
            try:
                a["outputs_stale"] = store.outputs_stale(a["id"])
                sent = store.sent_copies(a["id"])
                a["sent"] = sent[0] if sent else None
                a["progress"] = progress(a["id"], profile)
            except KeyError:
                a["outputs_stale"], a["sent"], a["progress"] = False, None, None
        return apps

    @api.post("/applications", status_code=201)
    async def create_application(body: NewApplication):
        need_profile()
        jd, company, role = body.jd.strip(), body.company, body.role
        if not jd and body.url:
            try:
                job = await fetch_job(body.url.strip())
            except FetchError as e:
                raise HTTPException(422, f"{e} Paste the job description instead.")
            except ValueError:
                raise HTTPException(422, "That URL isn't valid. Paste the job description instead.")
            jd, company, role = job.text, company or job.company, role or job.role
        if len(jd) < 100:
            raise HTTPException(422, "The job description looks too short — paste the full text.")
        app_id = store.create_app(company or "company", role or "role", jd, body.url)
        return {"id": app_id}

    @api.get("/applications/{app_id}")
    def get_application(app_id: str):
        need_app(app_id)
        tailored = store.tailored(app_id)
        out = {"id": app_id, "meta": store.meta(app_id), "jd": store.jd(app_id),
               "analysis": store.analysis(app_id), "files": store.files(app_id),
               "outputs_stale": store.outputs_stale(app_id),
               "tailored": tailored.model_dump(exclude_none=True) if tailored else None,
               "answers": [a.model_dump(exclude_none=True) for a in store.answers(app_id)],
               "edits": 0, "report": None, "ats": None, "length": None, "critique": critique_payload(app_id),
               "sent": store.sent_copies(app_id)}
        ai_draft = store.ai_tailored(app_id)
        if ai_draft and tailored:
            out["edits"] = len(ai.edited_claims(ai_draft, tailored))
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
        need_app(app_id)
        tailored = store.tailored(app_id)
        if not tailored:
            raise HTTPException(409, "Compose a resume first.")
        profile = need_profile()
        if not factcheck.check(profile, tailored).ok:
            raise HTTPException(409, "Fix the fact-check errors first — the review assumes a valid draft.")
        run_no = len(store.critique(app_id)["runs"]) + 1
        try:
            result = await hm.critique(engine, profile, tailored, store.analysis(app_id) or {}, store.knowledge(), run_no)
        except EngineError as e:
            raise _engine_call(e)
        except ValidationError as e:
            raise HTTPException(502, f"The model returned an invalid review: {e}")
        store.add_critique_run(app_id, result)
        return get_application(app_id)

    @api.put("/applications/{app_id}/critique/decisions")
    def put_critique_decisions(app_id: str, body: Decisions):
        need_app(app_id)
        store.set_critique_decisions(app_id, body.decisions)
        return critique_payload(app_id)

    @api.patch("/applications/{app_id}")
    def patch_application(app_id: str, body: MetaPatch):
        need_app(app_id)
        if body.status == "applied" and store.meta(app_id).get("status") != "applied":
            # Applying freezes the exact files sent. If they're missing or stale, the UI
            # offers "Build & freeze" instead of recording a version that doesn't match.
            try:
                store.freeze(app_id, "applied")
            except NeedsBuild as e:
                raise HTTPException(409, {"code": "needs_build", "message": str(e)})
        return store.update_meta(app_id, **body.model_dump(exclude_none=True))

    @api.delete("/applications/{app_id}", status_code=204)
    def delete_application(app_id: str):
        import shutil
        shutil.rmtree(store.app_path(need_app(app_id)))

    @api.post("/applications/{app_id}/analyze")
    async def analyze(app_id: str):
        need_app(app_id)
        try:
            analysis = await ai.analyze(engine, need_profile(), store.jd(app_id), store.knowledge())
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
        store.update_meta(app_id, guidance=body.guidance.strip())  # kept even if the AI call fails
        try:
            result = await ai.compose(engine, need_profile(), analysis, store.base_tailored(), body.guidance,
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

    @api.post("/applications/{app_id}/trim")
    async def trim(app_id: str):
        """Shorten the current resume with the AI (after a build came out over 2 pages)."""
        need_app(app_id)
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
        try:
            result = await ai.fit_to_length(engine, profile, tailored, analysis, target, max_rounds=1)
        except EngineError as e:
            raise _engine_call(e)
        if result["trim_rounds"] and result["tailored"] is not tailored:
            store.save_tailored(app_id, result["tailored"])
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

    async def do_build(app_id: str, pdf: bool = True) -> int | None:
        tailored = store.tailored(app_id)
        if not tailored:
            raise HTTPException(409, "Nothing to build yet.")
        profile = need_profile()
        report = factcheck.check(profile, tailored)
        if not report.ok:
            raise HTTPException(409, "Fact-check failed — fix the errors before building.")
        store.clear_outputs(app_id)  # never leave an older .docx/.pdf around to be sent by mistake
        built_hash = store.tailored_hash(app_id)
        docx = render(profile, tailored, store.app_path(app_id) / f"{store.output_stem(app_id)}.docx")
        pages = None
        if pdf:
            from .pdf import page_count, to_pdf
            try:
                pages = page_count(await asyncio.to_thread(to_pdf, docx))
            except Exception as e:  # Word missing / automation permission denied / timeout
                store.update_meta(app_id, built_hash=built_hash, pages=None)
                raise HTTPException(500, f"DOCX built, but PDF conversion via Word failed: {e}")
        store.update_meta(app_id, built_hash=built_hash, pages=pages)
        store.advance_status(app_id, "built")
        return pages

    @api.post("/applications/{app_id}/build")
    async def build(app_id: str, pdf: bool = True):
        need_app(app_id)
        pages = await do_build(app_id, pdf)
        out = get_application(app_id)
        out["build"] = {"pages": pages, "too_long": bool(pages and pages > MAX_PAGES)}
        return out

    @api.post("/applications/{app_id}/freeze")
    async def freeze(app_id: str, build: bool = False, mark_applied: bool = False):
        """Freeze a read-only copy of what's being sent. `build=true` rebuilds first
        ("Build & freeze"); `mark_applied=true` then records the application as applied."""
        need_app(app_id)
        if build:
            pages = await do_build(app_id, pdf=True)
            if pages and pages > MAX_PAGES:
                raise HTTPException(409, {"code": "too_long", "message":
                                          f"The PDF is {pages} pages — trim it before sending. Nothing was frozen."})
        try:
            store.freeze(app_id, "applied" if mark_applied else "manual copy")
        except NeedsBuild as e:
            raise HTTPException(409, {"code": "needs_build", "message": str(e)})
        if mark_applied:
            store.update_meta(app_id, status="applied")
        return get_application(app_id)

    @api.get("/applications/{app_id}/sent/{snapshot}/{name}")
    def get_sent_file(app_id: str, snapshot: str, name: str, download: bool = False):
        need_app(app_id)
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
        current_text = path.read_text(encoding="utf-8") if path.exists() else ""
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
        except ValidationError as e:
            raise HTTPException(422, f"That version can't be restored (it no longer validates): {e}")
        return profile_payload() if kind == "profile" else knowledge_payload()

    # -- gap answers + memory -------------------------------------------------------------
    @api.put("/applications/{app_id}/answers")
    def put_answers(app_id: str, answers: list[AppAnswer]):
        need_app(app_id)
        store.save_answers(app_id, answers)
        return [a.model_dump(exclude_none=True) for a in store.answers(app_id)]

    @api.get("/knowledge")
    def get_knowledge():
        return knowledge_payload()

    @api.put("/knowledge")
    def put_knowledge(data: dict, if_match: str | None = Header(default=None)):
        data = {k: v for k, v in data.items() if k != "version"}
        try:
            return knowledge_payload(store.save_knowledge(Knowledge.model_validate(data), base_version=if_match,
                                                          cause="answers & preferences editor"))
        except Conflict as e:
            raise HTTPException(409, str(e))
        except ValidationError as e:
            raise HTTPException(422, str(e))

    @api.post("/applications/{app_id}/preferences")
    async def suggest_preferences(app_id: str):
        """Propose style preferences from this application's guidance and Review edits."""
        need_app(app_id)
        ai_draft, current = store.ai_tailored(app_id), store.tailored(app_id)
        edits = ai.edited_claims(ai_draft, current) if ai_draft and current else []
        guidance = [store.meta(app_id).get("guidance") or ""]
        existing = [p for p in store.knowledge().preferences if p.status != "dismissed"]
        review = store.critique(app_id)
        rejected = [{"line": i.get("original", {}).get("text", i.get("where")), "suggested": i["rewrite"]["text"],
                     "problem": i.get("problem", "")}
                    for run in review["runs"] for i in run["result"].get("issues", [])
                    if review["decisions"].get(i["id"]) == "rejected" and i.get("rewrite")]
        try:
            proposals = await ai.learn_preferences(engine, edits, guidance, existing, rejected)
        except EngineError as e:
            raise _engine_call(e)
        today = f"{dt.date.today():%Y-%m-%d}"
        with store.editing_knowledge(cause="preferences suggested") as knowledge:  # fresh copy after the AI call
            for prop in proposals:
                taken = {x.id for x in knowledge.preferences} | set(knowledge.retired_ids)
                knowledge.preferences.append(Preference(
                    id=next_id("p", taken), text=prop["text"].strip(), rationale=prop.get("rationale", ""),
                    status="proposed", source_app=app_id, date=today))
        return {"edits": len(edits), "proposed": len(proposals), "knowledge": knowledge_payload()}

    @api.post("/applications/{app_id}/reveal", status_code=204)
    def reveal(app_id: str, snapshot: str | None = None):
        """Open the application folder (or a sent copy) in Finder with the PDF selected, so
        the exact file can be uploaded from there — no "(1)" duplicates from Downloads."""
        import subprocess
        import sys
        path = store.app_path(need_app(app_id))
        if snapshot:
            sent = next((c for c in store.sent_copies(app_id) if c["id"] == snapshot), None)
            if not sent:
                raise HTTPException(404, "sent copy not found")
            path = store.sent_dir(app_id) / snapshot
            files = sent["files"]
        else:
            files = store.files(app_id)
        pdf = next((path / f for f in files if f.endswith(".pdf")), None)
        target = pdf or next((path / f for f in files if f.endswith(".docx")), None)
        if sys.platform == "darwin":
            cmd = ["open", "-R", str(target)] if target else ["open", str(path)]
        elif sys.platform.startswith("win"):
            cmd = ["explorer", f"/select,{target}"] if target else ["explorer", str(path)]
        else:
            cmd = ["xdg-open", str(path)]
        try:
            subprocess.run(cmd, check=False, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise HTTPException(500, f"Couldn't open the folder: {e}")

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

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def unknown_api(path: str):
        # Otherwise these fall through to the page route and surface as a cryptic
        # "405 Method Not Allowed" — typically a server started before an update.
        raise HTTPException(404, "Unknown AutoCV endpoint. If you just updated AutoCV, restart the server "
                                 "(Ctrl+C, then `uv run autocv serve`).")

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
            # always revalidate the page so a rebuilt UI shows up after a restart (assets are hashed)
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app
