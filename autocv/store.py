"""Filesystem store for the private data: profile + one folder per application.

    private/
      profile.yaml          the only citable facts
      knowledge.yaml        remembered answers + learned style preferences (not citable)
      source/base_resume.docx, base_tailored.yaml
      applications/<YYYY-MM-DD>_<company>_<role>/
        meta.json  jd.md  analysis.yaml  answers.yaml
        tailored.ai.yaml    the AI's composed draft (to learn from the user's edits)
        tailored.yaml       the current, user-edited version
        <Name>_Resume_<Company>.docx/.pdf
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .schema import (AppAnswer, Knowledge, KnowledgeAnswer, MasterProfile, TailoredResume, dump_yaml,
                     load_profile, load_tailored, load_yaml)

ROOT = Path(__file__).resolve().parent.parent
STATUSES = ["draft", "analyzed", "composed", "built", "applied", "interview", "offer", "rejected", "withdrawn"]


def next_id(prefix: str, taken: set[str]) -> str:
    n = 1
    while f"{prefix}{n}" in taken:
        n += 1
    return f"{prefix}{n}"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


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

    def save_profile(self, data: dict) -> MasterProfile:
        profile = MasterProfile.model_validate(data)  # raises on invalid
        dump_yaml(profile.model_dump(exclude_none=True), self.profile_path)
        return profile

    def base_tailored(self) -> TailoredResume | None:
        p = self.base_tailored_path
        return load_tailored(p) if p.exists() else None

    # -- applications ----------------------------------------------------------------
    def app_path(self, app_id: str) -> Path:
        path = (self.apps_dir / app_id).resolve()
        if path.parent != self.apps_dir.resolve() or not path.is_dir():
            raise KeyError(app_id)
        return path

    def create_app(self, company: str, role: str, jd: str, url: str | None = None) -> str:
        base = f"{dt.date.today():%Y-%m-%d}_{slug(company) or 'company'}_{slug(role) or 'role'}"
        app_id, n = base, 2
        while (self.apps_dir / app_id).exists():
            app_id, n = f"{base}-{n}", n + 1
        path = self.apps_dir / app_id
        path.mkdir(parents=True)
        (path / "jd.md").write_text(jd, encoding="utf-8")
        now = dt.datetime.now().isoformat(timespec="seconds")
        self.save_meta(app_id, {"company": company, "role": role, "url": url, "status": "draft",
                                "created": now, "updated": now})
        return app_id

    def rename_app(self, app_id: str, company: str, role: str) -> str:
        """Give a folder created before the company/role were known a readable name."""
        old = self.app_path(app_id)
        base = f"{app_id[:10]}_{slug(company) or 'company'}_{slug(role) or 'role'}"
        new_id, n = base, 2
        while (self.apps_dir / new_id).exists() and new_id != app_id:
            new_id, n = f"{base}-{n}", n + 1
        if new_id != app_id:
            old.rename(self.apps_dir / new_id)
        return new_id

    def meta(self, app_id: str) -> dict:
        path = self.app_path(app_id) / "meta.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def save_meta(self, app_id: str, meta: dict) -> dict:
        meta = {**meta, "updated": dt.datetime.now().isoformat(timespec="seconds")}
        (self.apps_dir / app_id / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    def update_meta(self, app_id: str, **changes) -> dict:
        return self.save_meta(app_id, {**self.meta(app_id), **changes})

    def list_apps(self) -> list[dict]:
        if not self.apps_dir.exists():
            return []
        apps = []
        for path in sorted(self.apps_dir.iterdir(), reverse=True):
            if path.is_dir() and (path / "meta.json").exists():
                meta = self.meta(path.name)
                analysis = self.analysis(path.name) or {}
                apps.append({"id": path.name, **meta,
                             "industry": analysis.get("industry"), "track": analysis.get("track"),
                             "files": self.files(path.name)})
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

    # -- gap answers (per application) ---------------------------------------------------
    def answers(self, app_id: str) -> list[AppAnswer]:
        p = self.app_path(app_id) / "answers.yaml"
        data = load_yaml(p) if p.exists() else {}
        return [AppAnswer.model_validate(a) for a in data.get("answers", [])]

    def save_answers(self, app_id: str, answers: list[AppAnswer]) -> None:
        dump_yaml({"answers": [a.model_dump(exclude_none=True) for a in answers]},
                  self.app_path(app_id) / "answers.yaml")
        self._remember(app_id, answers)

    # -- knowledge (across applications) -------------------------------------------------
    @property
    def knowledge_path(self) -> Path:
        return self.private / "knowledge.yaml"

    def knowledge(self) -> Knowledge:
        p = self.knowledge_path
        return Knowledge.model_validate(load_yaml(p)) if p.exists() else Knowledge()

    def save_knowledge(self, knowledge: Knowledge) -> Knowledge:
        knowledge = Knowledge.model_validate(knowledge.model_dump())
        dump_yaml(knowledge.model_dump(exclude_none=True), self.knowledge_path)
        return knowledge

    def _remember(self, app_id: str, answers: list[AppAnswer]) -> None:
        """Upsert finalized answers into the knowledge base; drafts are forgotten.

        no_experience → a known gap. approved → experience (backed by profile evidence).
        rejected → the answer is kept for pre-filling, but is never evidence.
        """
        knowledge = self.knowledge()
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
                knowledge.answers.append(KnowledgeAnswer(id=next_id("k", {k.id for k in knowledge.answers}),
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
            self.save_knowledge(knowledge)

    def files(self, app_id: str) -> list[str]:
        path = self.app_path(app_id)
        return sorted(p.name for p in path.iterdir() if p.suffix in (".docx", ".pdf"))

    def output_stem(self, app_id: str) -> str:
        meta = self.meta(app_id)
        company = meta.get("company") or app_id.split("_")[1]
        name = self.profile().contact.name.replace(" ", "_")
        return f"{name}_Resume_{re.sub(r'[^A-Za-z0-9]+', '_', company).strip('_')}"
