"""Filesystem store for the private data: profile + one folder per application.

    private/
      profile.yaml          the only citable facts
      knowledge.yaml        remembered answers + learned style preferences (not citable)
      source/base_resume.docx, base_tailored.yaml
      applications/<company>/<YYYY-MM-DD>_<role>/     id: <company>~<YYYY-MM-DD>_<role>
        meta.json  jd.md  analysis.yaml  answers.yaml
        tailored.ai.yaml    the AI's composed draft (to learn from the user's edits)
        tailored.yaml       the current, user-edited version
        <Name>_Resume.docx/.pdf   (company-neutral: the folder says which company)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .schema import (AppAnswer, Knowledge, KnowledgeAnswer, MasterProfile, TailoredResume, dump_yaml,
                     load_profile, load_tailored, load_yaml)

ROOT = Path(__file__).resolve().parent.parent
STATUSES = ["draft", "analyzed", "composed", "built", "applied", "interview", "offer", "rejected", "withdrawn"]
PIPELINE = ["draft", "analyzed", "composed", "built"]  # set by the tool; the rest are set by the user
# Funnel stages, in order. An application "reached" a stage once its status got there,
# even if it later moved on to rejected/withdrawn.
MILESTONES = ["built", "applied", "interview", "offer"]

# One lock for every read-modify-write of private data. FastAPI runs sync endpoints in
# a thread pool, so concurrent requests are real. Never hold it across an AI call.
_LOCK = threading.RLock()


class Conflict(Exception):
    """The file changed since the client loaded it (another tab, or a background save)."""


class NeedsBuild(Exception):
    """The PDF is missing or out of date, so there's nothing trustworthy to freeze."""


def file_version(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "none"


def _write_json_atomic(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _parse(raw: bytes):
    import yaml
    try:
        return yaml.safe_load(raw.decode("utf-8", errors="replace"))
    except yaml.YAMLError:
        return None


def _same_content(kind: str, old, new: dict) -> bool:
    """Equal after validation (defaults filled in), so layout or default-only differences
    don't create history entries."""
    model = MasterProfile if kind == "profile" else Knowledge
    try:
        return model.model_validate(old).model_dump(exclude_none=True) == model.model_validate(new).model_dump(exclude_none=True)
    except Exception:  # noqa: BLE001 — an unparsable old version is definitely worth keeping
        return False


def next_id(prefix: str, taken: set[str]) -> str:
    n = 1
    while f"{prefix}{n}" in taken:
        n += 1
    return f"{prefix}{n}"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# Applications live in applications/<company>/<yyyy-mm-dd>_<role>/. Their id (used in URLs and
# the API) is "<company>~<yyyy-mm-dd>_<role>": one URL segment, and "~" never occurs in a slug.
APP_SEP = "~"
LEGACY_IDS = ".moved.json"  # old flat-layout ids → new ids, so old links keep working


@dataclass
class Store:
    private: Path

    @classmethod
    def default(cls) -> Store:
        return cls(Path(os.environ.get("AUTOCV_PRIVATE", ROOT / "private")))

    # -- paths -------------------------------------------------------------------
    @property
    def profile_path(self) -> Path:
        return self.private / "profile.yaml"

    @property
    def source_docx(self) -> Path:
        return self.private / "source" / "base_resume.docx"

    @property
    def base_tailored_path(self) -> Path:
        return self.private / "source" / "base_tailored.yaml"

    @property
    def apps_dir(self) -> Path:
        return self.private / "applications"

    # -- profile -------------------------------------------------------------------
    def profile(self) -> MasterProfile:
        return load_profile(self.profile_path)

    @property
    def lock(self) -> threading.RLock:
        return _LOCK

    def profile_version(self) -> str:
        return file_version(self.profile_path)

    def save_profile(self, data: dict, base_version: str | None = None, cause: str = "edit") -> MasterProfile:
        """Validate and save. Ids that disappear are retired so they're never reused. The
        previous version is kept in history (labelled with `cause`). With `base_version`,
        refuse to overwrite a profile that changed since it was read."""
        with _LOCK:
            if base_version is not None and base_version != self.profile_version():
                raise Conflict("Your profile changed since this page loaded (another tab or an approval). "
                               "Reload, then re-apply your edits.")
            profile = MasterProfile.model_validate(data)  # raises on invalid
            if self.profile_path.exists():
                old = self.profile()
                live = set(profile.all_ids())
                retired = set(old.retired_ids) | set(profile.retired_ids) | (set(old.all_ids()) - live)
                profile.retired_ids = sorted(retired - live)
            self._write_with_history("profile", self.profile_path, profile.model_dump(exclude_none=True), cause)
            return profile

    @contextmanager
    def editing_profile(self, cause: str = "edit"):
        """Read-modify-write the profile under the lock: `with store.editing_profile() as data: ...`"""
        with _LOCK:
            data = self.profile().model_dump(exclude_none=True)
            yield data
            self.save_profile(data, cause=cause)

    # -- history (profile + knowledge) ------------------------------------------------------
    HISTORY_KINDS = ("profile", "knowledge")

    def history_dir(self, kind: str) -> Path:
        if kind not in self.HISTORY_KINDS:
            raise KeyError(kind)
        return self.private / "history" / kind

    def _write_with_history(self, kind: str, path: Path, data: dict, cause: str) -> None:
        """Write `data` atomically; if that changes the file, keep the previous version."""
        old = path.read_bytes() if path.exists() else None
        dump_yaml(data, path)
        if old is not None and old != path.read_bytes() and not _same_content(kind, _parse(old), data):
            folder = self.history_dir(kind)
            folder.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            (folder / f"{stamp}__{slug(cause) or 'edit'}.yaml").write_bytes(old)

    def history(self, kind: str) -> list[dict]:
        """Saved previous versions, newest first. Each is the state *before* `cause`."""
        folder = self.history_dir(kind)
        if not folder.exists():
            return []
        out = []
        for f in sorted(folder.glob("*.yaml"), reverse=True):
            stamp, _, cause = f.stem.partition("__")
            when = dt.datetime.strptime(stamp, "%Y%m%d-%H%M%S-%f")
            out.append({"id": f.stem, "time": when.isoformat(timespec="seconds"),
                        "cause": cause.replace("-", " "), "size": f.stat().st_size})
        return out

    def history_text(self, kind: str, snapshot_id: str) -> str:
        folder = self.history_dir(kind)
        path = (folder / f"{snapshot_id}.yaml").resolve()
        if path.parent != folder.resolve() or not path.exists():
            raise KeyError(snapshot_id)
        return path.read_text(encoding="utf-8")

    def restore(self, kind: str, snapshot_id: str):
        """Restore a previous version. The current one goes to history first (undoable);
        retired ids are merged so a deleted id can never come back and collide."""
        import yaml as _yaml
        data = _yaml.safe_load(self.history_text(kind, snapshot_id)) or {}
        with _LOCK:
            if kind == "profile":
                current = self.profile()
                data["retired_ids"] = sorted(set(data.get("retired_ids", [])) | set(current.retired_ids))
                return self.save_profile(data, cause=f"restore {snapshot_id[:15]}")
            current = self.knowledge()
            data["retired_ids"] = sorted(set(data.get("retired_ids", [])) | set(current.retired_ids))
            return self.save_knowledge(Knowledge.model_validate(data), cause=f"restore {snapshot_id[:15]}")

    def base_tailored(self) -> TailoredResume | None:
        p = self.base_tailored_path
        return load_tailored(p) if p.exists() else None

    # -- applications ----------------------------------------------------------------
    def app_path(self, app_id: str) -> Path:
        app_id = self._legacy_ids().get(app_id, app_id)
        company, sep, rest = app_id.partition(APP_SEP)
        if not sep or not company or not rest:
            raise KeyError(app_id)
        root = self.apps_dir.resolve()
        path = (self.apps_dir / company / rest).resolve()
        # confined to exactly applications/<company>/<folder>/
        if path.parent.parent != root or path.parent.name != company or path.name != rest or not path.is_dir():
            raise KeyError(app_id)
        return path

    def app_id_for(self, path: Path) -> str:
        """The id of an application folder (raises KeyError if it isn't one)."""
        rel = path.resolve().relative_to(self.apps_dir.resolve()).parts
        if len(rel) != 2:
            raise KeyError(str(path))
        app_id = f"{rel[0]}{APP_SEP}{rel[1]}"
        self.app_path(app_id)
        return app_id

    def _new_folder(self, company: str, date: str, role: str) -> tuple[str, Path]:
        """A free applications/<company>/<date>_<role>[-n]/ folder (not created)."""
        c = slug(company) or "company"
        base = f"{date}_{slug(role) or 'role'}"
        rest, n = base, 2
        while (self.apps_dir / c / rest).exists():
            rest, n = f"{base}-{n}", n + 1
        return f"{c}{APP_SEP}{rest}", self.apps_dir / c / rest

    def _prune(self, company_dir: Path) -> None:
        """Remove a company folder once its last application is gone."""
        try:
            company_dir.rmdir()
        except OSError:
            pass

    def _legacy_ids(self) -> dict[str, str]:
        p = self.apps_dir / LEGACY_IDS
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def migrate_layout(self) -> dict[str, str]:
        """Move applications from the old flat layout (applications/<date>_<company>_<role>/) to
        applications/<company>/<date>_<role>/, and point stored references at the new ids.
        Idempotent; returns {old id: new id} for what it moved."""
        if not self.apps_dir.exists():
            return {}
        moved: dict[str, str] = {}
        with _LOCK:
            for old in sorted(self.apps_dir.iterdir()):
                if not (old.is_dir() and (old / "meta.json").exists()):
                    continue  # company folders (and anything else) are left alone
                meta = json.loads((old / "meta.json").read_text(encoding="utf-8"))
                m = re.match(r"\d{4}-\d{2}-\d{2}", old.name)
                date = m.group(0) if m else (meta.get("created") or f"{dt.date.today():%Y-%m-%d}")[:10]
                new_id, target = self._new_folder(meta.get("company") or "", date, meta.get("role") or "")
                target.parent.mkdir(parents=True, exist_ok=True)
                old.rename(target)
                moved[old.name] = new_id
            if moved:
                _write_json_atomic(self.apps_dir / LEGACY_IDS, {**self._legacy_ids(), **moved})
                self._repoint_knowledge(moved)
        return moved

    def _repoint_knowledge(self, renamed: dict[str, str]) -> None:
        """Answers and style preferences remember which application they came from."""
        if not self.knowledge_path.exists() or not renamed:
            return
        knowledge = self.knowledge()
        changed = False
        for a in knowledge.answers:
            if a.app_id in renamed:
                a.app_id, changed = renamed[a.app_id], True
        for p in knowledge.preferences:
            if p.source_app in renamed:
                p.source_app, changed = renamed[p.source_app], True
        if changed:
            self.save_knowledge(knowledge, cause="application folders reorganized")

    def delete_app(self, app_id: str) -> None:
        import shutil
        with _LOCK:
            path = self.app_path(app_id)
            shutil.rmtree(path)
            self._prune(path.parent)

    def create_app(self, company: str, role: str, jd: str, url: str | None = None) -> str:
        app_id, path = self._new_folder(company, f"{dt.date.today():%Y-%m-%d}", role)
        path.mkdir(parents=True)
        (path / "jd.md").write_text(jd, encoding="utf-8")
        now = dt.datetime.now().isoformat(timespec="seconds")
        self.save_meta(app_id, {"company": company, "role": role, "url": url, "status": "draft",
                                "created": now, "updated": now})
        return app_id

    def rename_app(self, app_id: str, company: str, role: str) -> str:
        """Move a folder created before the company/role were known to its readable place."""
        with _LOCK:
            old = self.app_path(app_id)
            want = f"{slug(company) or 'company'}{APP_SEP}{old.name[:10]}_{slug(role) or 'role'}"
            if app_id == want or app_id.startswith(want + "-"):
                return app_id
            new_id, target = self._new_folder(company, old.name[:10], role)
            target.parent.mkdir(parents=True, exist_ok=True)
            old.rename(target)
            self._prune(old.parent)
            self._repoint_knowledge({app_id: new_id})
            return new_id

    def meta(self, app_id: str) -> dict:
        path = self.app_path(app_id) / "meta.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def save_meta(self, app_id: str, meta: dict) -> dict:
        now = dt.datetime.now().isoformat(timespec="seconds")
        meta = {**meta, "updated": now}
        if meta.get("status") in MILESTONES and meta.get("status") not in meta.get("milestones", {}):
            meta["milestones"] = {**meta.get("milestones", {}), meta["status"]: now}
        _write_json_atomic(self.app_path(app_id) / "meta.json", meta)
        return meta

    def update_meta(self, app_id: str, **changes) -> dict:
        with _LOCK:
            return self.save_meta(app_id, {**self.meta(app_id), **changes})

    def advance_status(self, app_id: str, status: str) -> dict:
        """Pipeline steps only move the status forward, and never override a status
        the user set (applied, interview, offer…)."""
        with _LOCK:
            current = self.meta(app_id).get("status", "draft")
            if current in PIPELINE and PIPELINE.index(status) > PIPELINE.index(current):
                return self.update_meta(app_id, status=status)
            return self.meta(app_id)

    def reached(self, app_id: str) -> tuple[str | None, str | None]:
        """The furthest funnel stage this application reached, and when. Uses recorded
        milestones, falling back to evidence for applications from before they were
        recorded: the current status, a frozen sent copy, or built files."""
        meta = self.meta(app_id)
        seen = dict(meta.get("milestones", {}))
        status = meta.get("status")
        if status in MILESTONES:
            seen.setdefault(status, meta.get("updated"))
        sent = self.sent_copies(app_id)
        if sent:
            seen.setdefault("applied", sent[-1].get("created"))
        pdf = next((f for f in self.app_path(app_id).glob("*.pdf")), None)
        if pdf or meta.get("built_hash"):
            when = dt.datetime.fromtimestamp(pdf.stat().st_mtime).isoformat(timespec="seconds") if pdf else meta.get("updated")
            seen.setdefault("built", when)
        top = max((MILESTONES.index(k) for k in seen if k in MILESTONES), default=None)
        return (None, None) if top is None else (MILESTONES[top], seen[MILESTONES[top]])

    # -- outputs ---------------------------------------------------------------------------
    def tailored_hash(self, app_id: str) -> str:
        return file_version(self.app_path(app_id) / "tailored.yaml")

    def clear_outputs(self, app_id: str) -> None:
        for f in self.app_path(app_id).iterdir():
            if f.suffix in (".docx", ".pdf"):
                f.unlink()

    def outputs_stale(self, app_id: str) -> bool:
        """Built files exist but the tailored resume changed after they were built."""
        built = self.meta(app_id).get("built_hash")
        return bool(self.files(app_id)) and built != self.tailored_hash(app_id)

    def list_apps(self) -> list[dict]:
        if not self.apps_dir.exists():
            return []
        folders = [p for c in self.apps_dir.iterdir() if c.is_dir() for p in c.iterdir()
                   if p.is_dir() and (p / "meta.json").exists()]
        apps = []
        for path in sorted(folders, key=lambda p: (p.name, p.parent.name), reverse=True):  # newest first
            app_id = f"{path.parent.name}{APP_SEP}{path.name}"
            meta = self.meta(app_id)
            analysis = self.analysis(app_id) or {}
            apps.append({"id": app_id, **meta,
                         "industry": analysis.get("industry"), "track": analysis.get("track"),
                         "files": self.files(app_id)})
        return apps

    def jd(self, app_id: str) -> str:
        return (self.app_path(app_id) / "jd.md").read_text(encoding="utf-8")

    def analysis(self, app_id: str) -> dict | None:
        p = self.app_path(app_id) / "analysis.yaml"
        return load_yaml(p) if p.exists() else None

    def save_analysis(self, app_id: str, analysis: dict) -> None:
        dump_yaml(analysis, self.app_path(app_id) / "analysis.yaml")

    def tailored(self, app_id: str) -> TailoredResume | None:
        p = self.app_path(app_id) / "tailored.yaml"
        return load_tailored(p) if p.exists() else None

    def save_tailored(self, app_id: str, tailored: TailoredResume) -> None:
        dump_yaml(tailored.model_dump(exclude_none=True), self.app_path(app_id) / "tailored.yaml")

    def ai_tailored(self, app_id: str) -> TailoredResume | None:
        p = self.app_path(app_id) / "tailored.ai.yaml"
        return load_tailored(p) if p.exists() else None

    def save_ai_tailored(self, app_id: str, tailored: TailoredResume) -> None:
        dump_yaml(tailored.model_dump(exclude_none=True), self.app_path(app_id) / "tailored.ai.yaml")

    # -- hiring-manager review (per application) ---------------------------------------
    def critique(self, app_id: str) -> dict:
        p = self.app_path(app_id) / "review.yaml"
        data = load_yaml(p) if p.exists() else {}
        return {"runs": data.get("runs", []), "decisions": data.get("decisions", {})}

    def add_critique_run(self, app_id: str, result: dict) -> dict:
        with _LOCK:
            data = self.critique(app_id)
            data["runs"].append({"created": dt.datetime.now().isoformat(timespec="seconds"),
                                 "tailored_hash": self.tailored_hash(app_id), "result": result})
            data["runs"] = data["runs"][-5:]  # keep the last few for score deltas
            dump_yaml(data, self.app_path(app_id) / "review.yaml")
            return data

    def set_critique_decisions(self, app_id: str, decisions: dict[str, str]) -> dict:
        with _LOCK:
            data = self.critique(app_id)
            data["decisions"].update({k: v for k, v in decisions.items() if v in ("accepted", "rejected")})
            dump_yaml(data, self.app_path(app_id) / "review.yaml")
            return data

    # -- gap answers (per application) ---------------------------------------------------
    def answers(self, app_id: str) -> list[AppAnswer]:
        p = self.app_path(app_id) / "answers.yaml"
        data = load_yaml(p) if p.exists() else {}
        return [AppAnswer.model_validate(a) for a in data.get("answers", [])]

    def save_answers(self, app_id: str, answers: list[AppAnswer]) -> None:
        with _LOCK:
            dump_yaml({"answers": [a.model_dump(exclude_none=True) for a in answers]},
                      self.app_path(app_id) / "answers.yaml")
            self._remember(app_id, answers)

    def remap_answers(self, app_id: str, questions: list[dict]) -> None:
        """After (re-)analysis, keep only answers that still match a question — by its
        text, since question ids (q1, q2…) are renumbered — plus reopened known gaps.
        Finalized answers are already in the knowledge base, so nothing is lost."""
        with _LOCK:
            by_text = {" ".join(q["question"].split()).lower(): q for q in questions}
            kept = []
            for a in self.answers(app_id):
                q = by_text.get(" ".join(a.question.split()).lower())
                if q:
                    kept.append(a.model_copy(update={"question_id": q["id"], "requirement": q.get("requirement", a.requirement)}))
                elif a.question_id.startswith(("kg-", "hm-")):  # reopened gaps, review questions
                    kept.append(a)
            dump_yaml({"answers": [a.model_dump(exclude_none=True) for a in kept]},
                      self.app_path(app_id) / "answers.yaml")

    # -- knowledge (across applications) -------------------------------------------------
    @property
    def knowledge_path(self) -> Path:
        return self.private / "knowledge.yaml"

    def knowledge(self) -> Knowledge:
        p = self.knowledge_path
        return Knowledge.model_validate(load_yaml(p)) if p.exists() else Knowledge()

    def knowledge_version(self) -> str:
        return file_version(self.knowledge_path)

    def save_knowledge(self, knowledge: Knowledge, base_version: str | None = None, cause: str = "edit") -> Knowledge:
        with _LOCK:
            if base_version is not None and base_version != self.knowledge_version():
                raise Conflict("Your answers/preferences changed since this page loaded. Reload, then retry.")
            knowledge = Knowledge.model_validate(knowledge.model_dump())
            if self.knowledge_path.exists():
                old = self.knowledge()
                old_ids = {x.id for x in [*old.answers, *old.preferences]}
                live = {x.id for x in [*knowledge.answers, *knowledge.preferences]}
                knowledge.retired_ids = sorted((set(old.retired_ids) | set(knowledge.retired_ids) | (old_ids - live)) - live)
            self._write_with_history("knowledge", self.knowledge_path, knowledge.model_dump(exclude_none=True), cause)
            return knowledge

    @contextmanager
    def editing_knowledge(self, cause: str = "edit"):
        with _LOCK:
            knowledge = self.knowledge()
            yield knowledge
            self.save_knowledge(knowledge, cause=cause)

    def _remember(self, app_id: str, answers: list[AppAnswer]) -> None:
        """Upsert finalized answers into the knowledge base; drafts are forgotten.

        no_experience → a known gap. approved → experience (backed by profile evidence).
        rejected → the answer is kept for pre-filling, but is never evidence.
        """
        knowledge = self.knowledge()  # caller holds _LOCK
        company = self.meta(app_id).get("company")
        today = f"{dt.date.today():%Y-%m-%d}"
        by_key = {(k.app_id, k.question): k for k in knowledge.answers}
        changed = False
        for a in answers:
            key = (app_id, a.question)
            existing = by_key.get(key)
            if a.status == "draft" or (a.status == "rejected" and not a.answer.strip()):
                if existing:
                    knowledge.answers.remove(existing)
                    changed = True
                continue
            kind = "no_experience" if a.status == "no_experience" else "experience"
            fields = {"topic": a.requirement or a.question, "question": a.question,
                      "answer": "" if kind == "no_experience" else a.answer.strip(), "kind": kind,
                      "evidence_id": a.evidence_id if a.status == "approved" else None,
                      "app_id": app_id, "company": company}
            if existing:
                if any(getattr(existing, k) != v for k, v in fields.items()):
                    for k, v in fields.items():
                        setattr(existing, k, v)
                    existing.date = today
                    changed = True
            else:
                taken = {k.id for k in knowledge.answers} | set(knowledge.retired_ids)
                knowledge.answers.append(KnowledgeAnswer(id=next_id("k", taken),
                                                         date=today, **fields))
                changed = True
        # A finalized answer to a reopened known gap ("kg-<id>") replaces the old entry.
        for a in answers:
            if a.question_id.startswith("kg-") and a.status != "draft":
                old_id = a.question_id[3:]
                kept = [k for k in knowledge.answers if k.id != old_id]
                if len(kept) != len(knowledge.answers):
                    knowledge.answers = kept
                    changed = True
        if changed:
            self.save_knowledge(knowledge, cause="gap answer")

    # -- sent copies (frozen when applying) ------------------------------------------------
    def sent_dir(self, app_id: str) -> Path:
        return self.app_path(app_id) / "sent"

    def freeze_problem(self, app_id: str) -> str | None:
        if not any(f.endswith(".pdf") for f in self.files(app_id)):
            return "There's no PDF for this application yet."
        if self.outputs_stale(app_id):
            return "The PDF is out of date: the resume changed after it was built."
        return None

    def freeze(self, app_id: str, reason: str) -> dict:
        """Copy exactly what is being sent (PDF, DOCX, job description, resume data) into a
        dated, read-only snapshot. Never overwrites an earlier snapshot."""
        import shutil
        with _LOCK:
            problem = self.freeze_problem(app_id)
            if problem:
                raise NeedsBuild(problem)
            src = self.app_path(app_id)
            stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
            dest, n = self.sent_dir(app_id) / stamp, 2
            while dest.exists():
                dest, n = self.sent_dir(app_id) / f"{stamp}-{n}", n + 1
            dest.mkdir(parents=True)
            copied = []
            for name in [*self.files(app_id), "jd.md", "tailored.yaml", "analysis.yaml"]:
                if (src / name).exists():
                    shutil.copy2(src / name, dest / name)
                    copied.append(name)
            meta = self.meta(app_id)
            record = {"id": dest.name, "created": dt.datetime.now().isoformat(timespec="seconds"), "reason": reason,
                      "company": meta.get("company"), "role": meta.get("role"), "pages": meta.get("pages"),
                      "tailored_hash": self.tailored_hash(app_id), "files": copied}
            (dest / "sent.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            for f in dest.iterdir():
                f.chmod(0o444)  # read-only: this is the record of what was sent
            return record

    def sent_copies(self, app_id: str) -> list[dict]:
        folder = self.sent_dir(app_id)
        if not folder.exists():
            return []
        out = []
        for d in sorted(folder.iterdir(), reverse=True):
            if (d / "sent.json").exists():
                out.append(json.loads((d / "sent.json").read_text(encoding="utf-8")))
        return out

    def sent_file(self, app_id: str, snapshot: str, name: str) -> Path:
        folder = self.sent_dir(app_id).resolve()
        path = (folder / snapshot / name).resolve()
        if path.parent.parent != folder or not path.is_file() or path.suffix not in (".pdf", ".docx", ".md"):
            raise KeyError(name)
        return path

    def files(self, app_id: str) -> list[str]:
        path = self.app_path(app_id)
        return sorted(p.name for p in path.iterdir() if p.suffix in (".docx", ".pdf"))

    def output_stem(self, app_id: str) -> str:
        """The file name recruiters see: the candidate's name only. Never the company —
        CVs get forwarded and resubmitted, and a wrong-company filename is a visible
        mistake. The application folder already says which company it's for."""
        name = re.sub(r"[^A-Za-z0-9]+", "_", self.profile().contact.name).strip("_") or "Resume"
        return f"{name}_Resume"
