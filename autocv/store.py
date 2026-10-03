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
import logging
import os
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import oscompat, paths
from .schema import (AppAnswer, Knowledge, KnowledgeAnswer, MasterProfile, TailoredResume, dump_yaml,
                     load_profile, load_tailored, load_yaml)

log = logging.getLogger("autocv")

ROOT = Path(__file__).resolve().parent.parent
STATUSES = ["draft", "analyzed", "composed", "built", "applied", "interview", "offer", "closed"]
PIPELINE = ["draft", "analyzed", "composed", "built"]  # set by the tool; the rest are set by the user
# Funnel stages, in order. An application "reached" a stage once its status got there,
# even if it was later closed.
MILESTONES = ["built", "applied", "interview", "offer"]
# How a closed application ended. Who ended it matters more than the label; the stage it
# reached is already known from its milestones (so "rejected" + reached "interview" means
# rejected after interviewing).
OUTCOMES = ["rejected", "no_response", "role_closed",              # ended by them
            "withdrew", "declined_offer", "did_not_apply",          # ended by you
            "accepted_offer"]                                       # success
# Closing this way implies the application got at least this far.
OUTCOME_REACHED = {"rejected": "applied", "no_response": "applied",
                   "declined_offer": "offer", "accepted_offer": "offer"}
LEGACY_CLOSED = {"rejected": "rejected", "withdrawn": "withdrew"}  # old statuses → outcome

# One lock for every read-modify-write of private data. FastAPI runs sync endpoints in
# a thread pool, so concurrent requests are real. Never hold it across an AI call.
_LOCK = threading.RLock()


class Conflict(Exception):
    """The file changed since the client loaded it (another tab, or a background save)."""


class NeedsBuild(Exception):
    """The PDF is missing or out of date, so there's nothing trustworthy to freeze."""


class AppNotFound(KeyError):
    """No application with this id (or the id isn't a valid one)."""


class OutputInUse(RuntimeError):
    """A built file can't be replaced because another app has it open (Windows)."""


class CorruptApp(Exception):
    """An application folder whose meta.json can't be read."""


class RetiredIdReused(ValueError):
    """A save would bring back an id that was deleted earlier (ids are never reused)."""


def render_fingerprint(profile: MasterProfile, tailored: TailoredResume) -> str:
    """Hash of everything the renderer takes from the profile for this draft (contact, the
    chosen headline, each role's header, and the sub-roles/projects/education/extras it
    includes). Claim text comes from the draft itself. Unrelated profile edits (new evidence
    elsewhere, skills, synonyms) therefore don't make built files 'outdated'."""
    def dump(get, key, exclude=None):
        try:
            return get(key).model_dump(exclude=exclude)
        except Exception:  # noqa: BLE001 — a dangling reference simply contributes nothing
            return None
    parts = {
        "contact": profile.contact.model_dump(),
        "headline": dump(profile.headline, tailored.headline),
        "roles": [dump(profile.role, r.role, {"achievements", "scope", "sub_roles"}) for r in tailored.experience],
        "items": [dump(profile.lead_item, i) for i in
                  [s.id for r in tailored.experience for s in r.sub_roles] + [p.id for p in tailored.projects]
                  + list(tailored.education) + list(tailored.extras)],
    }
    return _digest(json.dumps(parts, sort_keys=True, default=str).encode("utf-8"))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def file_version(path: Path) -> str:
    return _digest(path.read_bytes()) if path.exists() else "none"


def _write_json_atomic(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:  # same bytes on every OS
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        oscompat.replace(tmp, path)
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


# Names Windows reserves for devices: a folder called "con" or "com1" can't be created there.
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return f"{s}-co" if s in _WINDOWS_RESERVED else s


SLUG_MAX = 60  # per folder-name part, so long company/role names can't exceed file-name limits


def _short_slug(text: str, fallback: str) -> str:
    return slug(text or "")[:SLUG_MAX].strip("-") or fallback


def _app_like(folder: Path) -> bool:
    """Looks like an application folder (old flat layout or new), never a company folder."""
    return any((folder / f).exists() for f in ("meta.json", "jd.md", "tailored.yaml"))


def _reused(live: set[str], *retired: list[str]) -> list[str]:
    return sorted(live & set().union(*map(set, retired)))


# Applications live in applications/<company>/<yyyy-mm-dd>_<role>/. Their id (used in URLs and
# the API) is "<company>~<yyyy-mm-dd>_<role>": one URL segment, and "~" never occurs in a slug.
APP_SEP = "~"
LEGACY_IDS = ".moved.json"  # old flat-layout ids → new ids, so old links keep working


@dataclass
class Store:
    private: Path

    @classmethod
    def default(cls) -> Store:
        return cls(paths.private_dir())

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

    # -- settings ------------------------------------------------------------------
    SETTINGS = {"pdf_engine": None}  # None = automatic (Word when installed, else LibreOffice)

    @property
    def settings_path(self) -> Path:
        return self.private / "settings.json"

    def settings(self) -> dict:
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        return {k: saved.get(k, v) for k, v in self.SETTINGS.items()} if isinstance(saved, dict) else dict(self.SETTINGS)

    def save_settings(self, patch: dict) -> dict:
        with self.lock:
            data = {**self.settings(), **{k: v for k, v in patch.items() if k in self.SETTINGS}}
            self.private.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(self.settings_path, data)
            return data

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
            live = set(profile.all_ids())
            old_ids, old_retired = self._previous_ids("profile", self.profile_path)
            reused = _reused(live, old_retired, profile.retired_ids)
            if reused:
                raise RetiredIdReused(
                    f"These ids belonged to evidence that was deleted earlier, and ids are never reused: "
                    f"{', '.join(reused)}. Give the items new ids (or add them through evidence approval).")
            profile.retired_ids = sorted(set(old_retired) | set(profile.retired_ids) | (old_ids - live))
            self._write_with_history("profile", self.profile_path, profile.model_dump(exclude_none=True), cause)
            return profile

    def _previous_ids(self, kind: str, path: Path) -> tuple[set[str], list[str]]:
        """(live ids, retired ids) of the file being replaced. A file that no longer validates
        still contributes the ids it lists, so a broken file can be fixed without losing them."""
        if not path.exists():
            return set(), []
        try:
            if kind == "profile":
                old = self.profile()
                return set(old.all_ids()), list(old.retired_ids)
            k = self.knowledge()
            return {x.id for x in [*k.answers, *k.preferences]}, list(k.retired_ids)
        except Exception:  # noqa: BLE001 — invalid or unparsable: salvage what we can
            raw = _parse(path.read_bytes())
            raw = raw if isinstance(raw, dict) else {}
            retired = [str(i) for i in raw.get("retired_ids") or [] if isinstance(i, (str, int))]
            ids: set[str] = set()

            def walk(node):
                if isinstance(node, dict):
                    if isinstance(node.get("id"), str):
                        ids.add(node["id"])
                    for v in node.values():
                        walk(v)
                elif isinstance(node, list):
                    for v in node:
                        walk(v)
            walk({k: v for k, v in raw.items() if k != "retired_ids"})
            return ids, retired

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
        if not isinstance(data, dict):
            raise ValueError("That version isn't a valid YAML mapping.")
        with _LOCK:
            path = self.profile_path if kind == "profile" else self.knowledge_path
            _, retired = self._previous_ids(kind, path)
            data["retired_ids"] = sorted(set(data.get("retired_ids") or []) | set(retired))
            try:
                if kind == "profile":
                    return self.save_profile(data, cause=f"restore {snapshot_id[:15]}")
                return self.save_knowledge(Knowledge.model_validate(data), cause=f"restore {snapshot_id[:15]}")
            except RetiredIdReused as e:
                raise RetiredIdReused(f"That version can't be restored: it contains items deleted since. {e}") from e

    def base_tailored(self) -> TailoredResume | None:
        p = self.base_tailored_path
        return load_tailored(p) if p.exists() else None

    # -- applications ----------------------------------------------------------------
    MAX_ID = 300

    def _resolve_id(self, app_id: str) -> Path:
        """applications/<company>/<folder>/ for a current-layout id. Names must match the
        directory entries exactly (no case aliases on case-insensitive disks), neither level may
        be a symlink, and the folder must be an application (has meta.json)."""
        company, sep, rest = app_id.partition(APP_SEP)
        if not sep or not company or not rest:
            raise AppNotFound(app_id)
        for part in (company, rest):
            if part in (".", "..") or part.startswith(".") or "/" in part or "\\" in part or len(part) > 200:
                raise AppNotFound(app_id)
        try:
            if company not in os.listdir(self.apps_dir):
                raise AppNotFound(app_id)
            cdir = self.apps_dir / company
            if cdir.is_symlink() or not cdir.is_dir() or _app_like(cdir) or rest not in os.listdir(cdir):
                raise AppNotFound(app_id)
            path = cdir / rest
            if path.is_symlink() or not path.is_dir() or not (path / "meta.json").is_file():
                raise AppNotFound(app_id)
        except OSError:
            raise AppNotFound(app_id) from None
        return path.resolve()

    def app_path(self, app_id: str) -> Path:
        if not isinstance(app_id, str) or not app_id or "\x00" in app_id or len(app_id) > self.MAX_ID:
            raise AppNotFound(str(app_id)[:80])
        mapped = self._legacy_ids().get(app_id)
        if mapped and mapped != app_id:
            try:
                return self._resolve_id(mapped)
            except AppNotFound:
                pass  # an interrupted move: the folder is still at its own id
        return self._resolve_id(app_id)

    def app_id_for(self, path: Path) -> str:
        """The id of an application folder (raises KeyError if it isn't one)."""
        rel = path.resolve().relative_to(self.apps_dir.resolve()).parts
        if len(rel) != 2:
            raise AppNotFound(str(path))
        app_id = f"{rel[0]}{APP_SEP}{rel[1]}"
        self._resolve_id(app_id)
        return app_id

    def canonical_id(self, app_id: str) -> str:
        """The current id for `app_id` (which may be an old id from before a move or rename)."""
        return self.app_id_for(self.app_path(app_id))

    def _new_folder(self, company: str, date: str, role: str) -> tuple[str, Path]:
        """A free applications/<company>/<date>_<role>[-n]/ folder (not created). Ids that once
        belonged to another application (moved or renamed away) are never handed out again."""
        c = _short_slug(company, "company")
        base = f"{date}_{_short_slug(role, 'role')}"
        legacy = self._legacy_ids()
        rest, n = base, 2
        while (self.apps_dir / c / rest).exists() or f"{c}{APP_SEP}{rest}" in legacy:
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
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("AutoCV: ignoring unreadable %s (%s); old application links may not resolve", p, e)
            return {}
        if not isinstance(data, dict):
            log.warning("AutoCV: ignoring %s (not a JSON object)", p)
            return {}
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}

    def _save_legacy_ids(self, mapping: dict[str, str]) -> None:
        self.apps_dir.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(self.apps_dir / LEGACY_IDS, mapping)

    _FLAT = re.compile(r"^(\d{4}-\d{2}-\d{2})_([a-z0-9-]+)_(.+)$")

    def migrate_layout(self) -> dict[str, str]:
        """Move applications from the old flat layout (applications/<date>_<company>_<role>/) to
        applications/<company>/<date>_<role>/, and point stored references at the new ids.
        Idempotent and incremental (each move is recorded as it happens, so an interrupted run
        never orphans an id); a folder that can't be read is skipped with a warning.
        Returns {old id: new id} for what it moved."""
        if not self.apps_dir.exists():
            return {}
        moved: dict[str, str] = {}
        with _LOCK:
            for old in sorted(self.apps_dir.iterdir()):
                try:
                    new_id = self._migrate_one(old)
                except Exception as e:  # noqa: BLE001 — one bad folder must never block the rest
                    log.warning("AutoCV: couldn't move application folder %s (%s); left as is", old.name, e)
                    continue
                if new_id:
                    moved[old.name] = new_id
            for step in (self.drop_company_from_filenames, self._close_legacy_statuses):
                try:
                    step()
                except Exception as e:  # noqa: BLE001
                    log.warning("AutoCV: %s skipped (%s)", step.__name__.strip("_").replace("_", " "), e)
        return moved

    def _migrate_one(self, old: Path) -> str | None:
        if old.name.startswith(".") or old.is_symlink() or not old.is_dir():
            return None
        meta_path = old / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if not isinstance(meta, dict):
                    raise ValueError("not a JSON object")
            except (OSError, ValueError) as e:
                log.warning("AutoCV: skipping %s: unreadable meta.json (%s)", old.name, e)
                return None
        else:
            m = self._FLAT.match(old.name)
            if not (m and _app_like(old)):
                return None  # a company folder (or something else): left alone
            # An old application without meta.json: rebuild it from the folder name.
            meta = {"company": m.group(2).replace("-", " ").title(), "role": m.group(3).replace("-", " ").title(),
                    "status": "composed" if (old / "tailored.yaml").exists()
                    else "analyzed" if (old / "analysis.yaml").exists() else "draft",
                    "created": f"{m.group(1)}T00:00:00"}
            _write_json_atomic(meta_path, meta)
        m = re.match(r"\d{4}-\d{2}-\d{2}", old.name)
        date = m.group(0) if m else str(meta.get("created") or f"{dt.date.today():%Y-%m-%d}")[:10]
        legacy = self._legacy_ids()
        planned = legacy.get(old.name)  # an earlier, interrupted run already chose its new id
        new_id = target = None
        if planned and APP_SEP in planned:
            c, _, rest = planned.partition(APP_SEP)
            if not (self.apps_dir / c / rest).exists():
                new_id, target = planned, self.apps_dir / c / rest
        if target is None:
            new_id, target = self._new_folder(str(meta.get("company") or ""), date, str(meta.get("role") or ""))
        self._save_legacy_ids({**legacy, old.name: new_id})  # recorded before the move
        target.parent.mkdir(parents=True, exist_ok=True)
        old.rename(target)
        try:
            self._repoint_knowledge({old.name: new_id})
        except Exception as e:  # noqa: BLE001 — the old id still resolves through the map
            log.warning("AutoCV: couldn't update knowledge links for %s (%s)", old.name, e)
        return new_id

    def _close_legacy_statuses(self) -> None:
        """rejected/withdrawn statuses (before outcomes existed) → closed + outcome, recording
        the stage the outcome implies. Keeps the original 'updated' time, which is when the
        application was closed."""
        for app in self.list_apps():
            if app.get("status") in LEGACY_CLOSED and not app.get("broken"):
                path = self.app_path(app["id"]) / "meta.json"
                meta = json.loads(path.read_text(encoding="utf-8"))
                outcome = LEGACY_CLOSED[meta["status"]]
                closed_at = meta.get("closed_at") or meta.get("updated")
                meta.update(status="closed", outcome=outcome, closed_at=closed_at)
                stage = OUTCOME_REACHED.get(outcome)
                if stage and stage not in meta.get("milestones", {}):
                    meta["milestones"] = {**meta.get("milestones", {}), stage: closed_at}
                _write_json_atomic(path, meta)

    def drop_company_from_filenames(self) -> list[Path]:
        """Rename resumes built before file names became company-neutral
        (<Name>_Resume_<Company>.docx/.pdf → <Name>_Resume.docx/.pdf). Only that exact pattern,
        only the working files (never sent/ copies), and never over an existing file."""
        if not self.apps_dir.exists() or not self.profile_path.exists():
            return []
        renamed = []
        with _LOCK:
            for app in self.list_apps():
                company = re.sub(r"[^A-Za-z0-9]+", "_", app.get("company") or "").strip("_")
                if not company or app.get("broken"):
                    continue
                folder, stem = self.app_path(app["id"]), self.output_stem(app["id"])
                for ext in (".docx", ".pdf"):
                    old, new = folder / f"{stem}_{company}{ext}", folder / f"{stem}{ext}"
                    if old.is_file() and not new.exists():
                        old.rename(new)
                        renamed.append(new)
        return renamed

    def _repoint_knowledge(self, renamed: dict[str, str | None]) -> None:
        """Answers and style preferences remember which application they came from
        (None: the application was deleted; the answer itself is kept)."""
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
        """Delete an application folder (job description, drafts, built files, sent copies).
        Remembered answers and style preferences are kept; they just stop linking to it."""
        with _LOCK:
            path = self.app_path(app_id)
            canonical = self.app_id_for(path)
            oscompat.rmtree(path)  # sent copies are read-only on purpose
            self._prune(path.parent)
            legacy = self._legacy_ids()
            gone = [old for old, new in legacy.items() if new == canonical]
            if gone:
                self._save_legacy_ids({k: v for k, v in legacy.items() if k not in gone})
            try:
                self._repoint_knowledge({i: None for i in [canonical, *gone]})
            except Exception as e:  # noqa: BLE001 — the folder is gone either way
                log.warning("AutoCV: couldn't unlink knowledge from %s (%s)", canonical, e)

    def create_app(self, company: str, role: str, jd: str, url: str | None = None) -> str:
        with _LOCK:
            app_id, path = self._new_folder(company, f"{dt.date.today():%Y-%m-%d}", role)
            path.mkdir(parents=True)
            try:
                (path / "jd.md").write_text(jd, encoding="utf-8", newline="\n")
                now = dt.datetime.now().isoformat(timespec="seconds")
                self._write_meta(path, {"company": company, "role": role, "url": url, "status": "draft",
                                        "created": now, "updated": now})
            except BaseException:
                oscompat.rmtree(path, ignore_errors=True)  # never leave a half-created folder behind
                self._prune(path.parent)
                raise
            return app_id

    def rename_app(self, app_id: str, company: str, role: str) -> str:
        """Move a folder created before the company/role were known to its readable place.
        The old id keeps resolving (and is never handed to another application)."""
        with _LOCK:
            old = self.app_path(app_id)
            app_id = self.app_id_for(old)
            date = old.name[:10]
            want = f"{_short_slug(company, 'company')}{APP_SEP}{date}_{_short_slug(role, 'role')}"
            if re.fullmatch(re.escape(want) + r"(-\d+)?", app_id):
                return app_id
            new_id, target = self._new_folder(company, date, role)
            if target.resolve() == old:
                return app_id
            legacy = self._legacy_ids()
            self._save_legacy_ids({**{k: (new_id if v == app_id else v) for k, v in legacy.items()}, app_id: new_id})
            target.parent.mkdir(parents=True, exist_ok=True)
            old.rename(target)
            self._prune(old.parent)
            try:
                self._repoint_knowledge({app_id: new_id})
            except Exception as e:  # noqa: BLE001 — the old id still resolves through the map
                log.warning("AutoCV: couldn't update knowledge links for %s (%s)", app_id, e)
            return new_id

    def meta(self, app_id: str) -> dict:
        path = self.app_path(app_id) / "meta.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise CorruptApp(f"This application's meta.json can't be read ({e}). Fix or delete the application.") from e
        if not isinstance(data, dict):
            raise CorruptApp("This application's meta.json isn't a JSON object. Fix or delete the application.")
        return data

    @staticmethod
    def _stamp_meta(meta: dict) -> dict:
        now = dt.datetime.now().isoformat(timespec="seconds")
        meta = {**meta, "updated": now}
        stage = meta.get("status") if meta.get("status") in MILESTONES else \
            OUTCOME_REACHED.get(meta.get("outcome")) if meta.get("status") == "closed" else None
        if stage and stage not in meta.get("milestones", {}):
            meta["milestones"] = {**meta.get("milestones", {}), stage: now}
        return meta

    def _write_meta(self, folder: Path, meta: dict) -> dict:
        meta = self._stamp_meta(meta)
        _write_json_atomic(folder / "meta.json", meta)
        return meta

    def save_meta(self, app_id: str, meta: dict) -> dict:
        with _LOCK:
            return self._write_meta(self.app_path(app_id), meta)

    def update_meta(self, app_id: str, **changes) -> dict:
        with _LOCK:
            return self.save_meta(app_id, {**self.meta(app_id), **changes})

    def set_status(self, app_id: str, status: str, outcome: str | None = None) -> dict:
        """A user status change. Closing needs an outcome (or keeps the one it has); any other
        status clears it, so a reopened application doesn't carry a stale reason."""
        with _LOCK:
            meta = self.meta(app_id)
            if status != "closed":
                meta.pop("outcome", None)
                meta.pop("closed_at", None)
                return self.save_meta(app_id, {**meta, "status": status})
            outcome = outcome or (meta.get("outcome") if meta.get("status") == "closed" else None)
            if outcome not in OUTCOMES:
                raise ValueError("Say how it ended: pick an outcome to close the application.")
            if meta.get("status") != "closed":
                meta["closed_at"] = dt.datetime.now().isoformat(timespec="seconds")
            return self.save_meta(app_id, {**meta, "status": "closed", "outcome": outcome})

    def applied_copy(self, app_id: str) -> dict | None:
        """The sent copy frozen when the application was marked applied (oldest, if several)."""
        applied = [c for c in self.sent_copies(app_id) if c.get("reason") == "applied"]
        return applied[-1] if applied else None

    def mark_applied(self, app_id: str) -> dict:
        """Record the application as applied. The first time, freeze exactly what is being sent
        (raises NeedsBuild if that isn't trustworthy); re-entering 'applied' later (after an
        interview, a reopen…) never freezes another copy."""
        with _LOCK:
            if self.applied_copy(app_id) is None:
                self.freeze(app_id, "applied")
            return self.set_status(app_id, "applied")

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
        recorded: the current status, how it was closed, the copy frozen when applying
        (a manual "freeze a copy" isn't evidence of applying), or built files."""
        meta = self.meta(app_id)
        seen = dict(meta.get("milestones", {}))
        status = meta.get("status")
        if status in MILESTONES:
            seen.setdefault(status, meta.get("updated"))
        applied = self.applied_copy(app_id)
        if applied:
            seen.setdefault("applied", applied.get("created"))
        outcome = meta.get("outcome") if status == "closed" else LEGACY_CLOSED.get(status)
        if outcome in OUTCOME_REACHED:
            seen.setdefault(OUTCOME_REACHED[outcome], meta.get("closed_at") or meta.get("updated"))
        pdf = next((f for f in self.app_path(app_id).glob("*.pdf")), None)
        if pdf or meta.get("built_hash"):
            when = dt.datetime.fromtimestamp(pdf.stat().st_mtime).isoformat(timespec="seconds") if pdf else meta.get("updated")
            seen.setdefault("built", when)
        top = max((MILESTONES.index(k) for k in seen if k in MILESTONES), default=None)
        return (None, None) if top is None else (MILESTONES[top], seen[MILESTONES[top]])

    # -- outputs ---------------------------------------------------------------------------
    def tailored_hash(self, app_id: str) -> str:
        return file_version(self.app_path(app_id) / "tailored.yaml")

    def build_inputs(self, app_id: str) -> tuple[TailoredResume, str, MasterProfile, str]:
        """What a build renders from: (draft, its hash, profile, its version), each parsed from
        exactly the bytes that were hashed, so a save racing the build can't be mislabelled."""
        import yaml
        with _LOCK:
            draft = self.app_path(app_id) / "tailored.yaml"
            if not draft.exists():
                raise FileNotFoundError("Nothing to build yet.")
            t_bytes, p_bytes = draft.read_bytes(), self.profile_path.read_bytes()
        tailored = TailoredResume.model_validate(yaml.safe_load(t_bytes.decode("utf-8")) or {})
        profile = MasterProfile.model_validate(yaml.safe_load(p_bytes.decode("utf-8")) or {})
        return tailored, _digest(t_bytes), profile, render_fingerprint(profile, tailored)

    def record_build(self, app_id: str, built_hash: str, profile_version: str, pages: int | None) -> dict:
        return self.update_meta(app_id, built_hash=built_hash, built_profile=profile_version, pages=pages)

    def clear_outputs(self, app_id: str) -> None:
        for f in self.app_path(app_id).iterdir():
            if f.suffix in (".docx", ".pdf"):
                try:
                    f.unlink()
                except PermissionError as e:  # Windows locks files that are open in another app
                    raise OutputInUse(f"{f.name} is open in another app. Close it, then build again.") from e

    def outputs_stale(self, app_id: str) -> bool:
        """Built files exist but the tailored resume or the profile changed after they were built."""
        if not self.files(app_id):
            return False
        meta = self.meta(app_id)
        return meta.get("built_hash") != self.tailored_hash(app_id) or self._profile_moved_on(app_id, meta)

    def _profile_moved_on(self, app_id: str, meta: dict) -> bool:
        """True when something this application's resume prints from the profile changed since
        the build. Builds from before fingerprints were recorded count as current (the freeze
        gate still re-runs the fact-check against the current profile)."""
        if not meta.get("built_profile"):
            return False
        try:
            tailored = self.tailored(app_id)
            return tailored is None or meta["built_profile"] != render_fingerprint(self.profile(), tailored)
        except Exception:  # noqa: BLE001 — unreadable draft/profile: treat as outdated
            return True

    def list_apps(self) -> list[dict]:
        """Every application, newest first. One whose files can't be read is still listed
        (flagged `broken`) so it can be deleted, and never breaks the list."""
        if not self.apps_dir.exists():
            return []
        apps = []
        for c in self.apps_dir.iterdir():
            if c.name.startswith(".") or c.is_symlink() or not c.is_dir() or _app_like(c):
                continue
            for p in c.iterdir():
                if p.is_symlink() or not p.is_dir() or not (p / "meta.json").is_file():
                    continue
                app_id = f"{c.name}{APP_SEP}{p.name}"
                try:
                    meta = self.meta(app_id)
                    analysis = self.analysis(app_id) or {}
                    row = {"id": app_id, **meta, "industry": analysis.get("industry"), "track": analysis.get("track"),
                           "files": self.files(app_id)}
                except Exception as e:  # noqa: BLE001
                    log.warning("AutoCV: application %s can't be read (%s)", app_id, e)
                    row = {"id": app_id, "company": c.name, "role": p.name, "status": "draft",
                           "created": p.name[:10], "files": [], "broken": str(e)}
                apps.append(row)
        apps.sort(key=lambda a: (str(a.get("created") or a["id"].partition(APP_SEP)[2][:10]),
                                 a["id"].partition(APP_SEP)[2], a["id"]), reverse=True)  # newest first
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
        with _LOCK:  # so a freeze (which holds the lock) copies exactly the draft it verified
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
        return {"runs": data.get("runs", []), "decisions": data.get("decisions", {}),
                "run_counter": int(data.get("run_counter") or 0)}

    def next_critique_run(self, app_id: str) -> int:
        """Reserve a review run number. Unique forever (issue ids rN-iM key the decisions, and
        only the last few runs are kept), so it's a stored counter, never len(runs)."""
        with _LOCK:
            data = self.critique(app_id)
            ids = [i.get("id", "") for run in data["runs"] for i in (run.get("result") or {}).get("issues", [])]
            used = [int(m.group(1)) for x in [*ids, *data["decisions"]] if (m := re.match(r"r(\d+)-i", str(x)))]
            data["run_counter"] = max([data["run_counter"], len(data["runs"]), *used]) + 1
            dump_yaml(data, self.app_path(app_id) / "review.yaml")
            return data["run_counter"]

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
            live = {x.id for x in [*knowledge.answers, *knowledge.preferences]}
            old_ids, old_retired = self._previous_ids("knowledge", self.knowledge_path)
            reused = _reused(live, old_retired, knowledge.retired_ids)
            if reused:
                raise RetiredIdReused(
                    f"These answer/preference ids were deleted earlier, and ids are never reused: "
                    f"{', '.join(reused)}.")
            knowledge.retired_ids = sorted(set(old_retired) | set(knowledge.retired_ids) | (old_ids - live))
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
        """Why the built files can't be frozen as what was sent (None: they can). They must be
        built from the current draft and the current profile, and that draft must pass the
        fact-check against the current profile."""
        from . import factcheck
        if not any(f.endswith(".pdf") for f in self.files(app_id)):
            return "There's no PDF for this application yet."
        meta = self.meta(app_id)
        if meta.get("built_hash") != self.tailored_hash(app_id):
            return "The PDF is out of date: the resume changed after it was built."
        if self._profile_moved_on(app_id, meta):
            return "The PDF is out of date: your master profile changed after it was built. Rebuild it."
        try:
            tailored, profile = self.tailored(app_id), self.profile()
            ok = tailored is not None and factcheck.check(profile, tailored).ok
        except Exception:  # noqa: BLE001 — unreadable draft/profile: certainly not verified
            ok = False
        if not ok:
            return "The resume doesn't pass the fact-check against your current profile. Fix it, then rebuild."
        return None

    def freeze(self, app_id: str, reason: str) -> dict:
        """Copy exactly what is being sent (PDF, DOCX, job description, resume data) into a
        dated, read-only snapshot. Never overwrites an earlier snapshot."""
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
                      "tailored_hash": self.tailored_hash(app_id), "profile_version": meta.get("built_profile"),
                      "files": copied}
            (dest / "sent.json").write_text(json.dumps(record, indent=2), encoding="utf-8", newline="\n")
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
                try:
                    record = json.loads((d / "sent.json").read_text(encoding="utf-8"))
                except (OSError, ValueError) as e:
                    log.warning("AutoCV: unreadable sent copy %s (%s)", d, e)
                    continue
                if isinstance(record, dict):
                    out.append(record)
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
