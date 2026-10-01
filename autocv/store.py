"""Filesystem store for the private data: profile + one folder per application.

    private/
      profile.yaml
      source/base_resume.docx, base_tailored.yaml
      applications/<YYYY-MM-DD>_<company>_<role>/
        meta.json  jd.md  analysis.yaml  tailored.yaml  <Name>_Resume_<Company>.docx/.pdf
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .schema import MasterProfile, TailoredResume, dump_yaml, load_profile, load_tailored, load_yaml

ROOT = Path(__file__).resolve().parent.parent
STATUSES = ["draft", "analyzed", "composed", "built", "applied", "interview", "offer", "rejected", "withdrawn"]


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

    def files(self, app_id: str) -> list[str]:
        path = self.app_path(app_id)
        return sorted(p.name for p in path.iterdir() if p.suffix in (".docx", ".pdf"))

    def output_stem(self, app_id: str) -> str:
        meta = self.meta(app_id)
        company = meta.get("company") or app_id.split("_")[1]
        name = self.profile().contact.name.replace(" ", "_")
        return f"{name}_Resume_{re.sub(r'[^A-Za-z0-9]+', '_', company).strip('_')}"
