"""Data models.

MasterProfile is the single source of truth: every sentence in it is something the
candidate has confirmed. TailoredResume is a per-job *layout* that may rephrase and
reorder, but every free-text item must cite the profile evidence it is derived from.

Locked fields (contact, employer, location, title, dates, education, certifications,
awards, languages) are never copied into a TailoredResume — the renderer pulls them
from the profile by id, so they cannot drift.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .oscompat import replace as _replace

Track = Literal["manager", "ic", "hybrid"]
Source = Literal["resume", "prep_guide", "interview"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- profile


class Link(_Model):
    text: str
    url: str


class Contact(_Model):
    name: str
    location: str
    phone: str | None = None
    email: str | None = None
    links: list[Link] = Field(default_factory=list)


class Headline(_Model):
    id: str
    text: str
    tracks: list[Track]


class Evidence(_Model):
    """One verified, citable statement."""

    id: str
    text: str
    source: Source = "resume"
    in_base_resume: bool = True
    tags: list[str] = Field(default_factory=list)
    note: str | None = None  # provenance detail, e.g. quoted prep-guide passage


class LeadItem(_Model):
    """A bullet rendered as **label** + text, e.g. sub-roles, projects, education."""

    id: str
    label: str
    text: str
    source: Source = "resume"
    in_base_resume: bool = True


class Scope(Evidence):
    italic: bool = True


class Role(_Model):
    id: str
    employer: str
    location: str
    title: str
    dates: str
    scope: Scope | None = None
    achievements: list[Evidence] = Field(default_factory=list)
    sub_roles: list[LeadItem] = Field(default_factory=list)


class SkillGroup(_Model):
    category: str
    items: list[str]


class MasterProfile(_Model):
    contact: Contact
    headlines: list[Headline]
    summary_facts: list[Evidence] = Field(default_factory=list)
    highlights: list[Evidence] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    roles: list[Role] = Field(default_factory=list)
    projects: list[LeadItem] = Field(default_factory=list)
    education: list[LeadItem] = Field(default_factory=list)
    extras: list[LeadItem] = Field(default_factory=list)  # awards, languages
    # Groups of interchangeable terms, e.g. ["WAF", "Web Application Firewall"].
    synonyms: list[list[str]] = Field(default_factory=list)
    # Extra proper nouns the candidate approved for use anywhere (e.g. "Singapore").
    vocabulary: list[str] = Field(default_factory=list)
    # Ids of deleted evidence. Never reused, so old resumes can't silently re-attach
    # their claims to a different fact.
    retired_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> MasterProfile:
        seen: set[str] = set()
        for id_ in self.all_ids():
            if id_ in seen:
                raise ValueError(f"duplicate id in profile: {id_}")
            seen.add(id_)
        return self

    def all_ids(self) -> list[str]:
        ids = [h.id for h in self.headlines]
        ids += [e.id for e in self.summary_facts + self.highlights]
        for r in self.roles:
            ids.append(r.id)
            if r.scope:
                ids.append(r.scope.id)
            ids += [a.id for a in r.achievements]
            ids += [s.id for s in r.sub_roles]
        ids += [i.id for i in self.projects + self.education + self.extras]
        return ids

    def role(self, role_id: str) -> Role:
        for r in self.roles:
            if r.id == role_id:
                return r
        raise KeyError(role_id)

    def lead_item(self, item_id: str) -> LeadItem:
        for i in self.projects + self.education + self.extras:
            if i.id == item_id:
                return i
        for r in self.roles:
            for s in r.sub_roles:
                if s.id == item_id:
                    return s
        raise KeyError(item_id)

    def headline(self, headline_id: str) -> Headline:
        for h in self.headlines:
            if h.id == headline_id:
                return h
        raise KeyError(headline_id)


# --------------------------------------------------------------------------- tailored


class Claim(_Model):
    text: str
    sources: list[str] = Field(default_factory=list)


class TailoredSubRole(_Model):
    id: str
    text: Claim | None = None  # None → profile text verbatim


class TailoredRole(_Model):
    role: str  # profile role id; employer/title/dates come from the profile
    scope: Claim | None = None
    bullets: list[Claim] = Field(default_factory=list)
    sub_roles: list[TailoredSubRole] = Field(default_factory=list)


class TailoredProject(_Model):
    id: str
    text: Claim | None = None


class Competency(_Model):
    label: str
    items: list[str]


class TailoredResume(_Model):
    headline: str  # profile headline id
    summary: Claim | None = None
    highlights: list[Claim] = Field(default_factory=list)
    competencies: list[Competency] = Field(default_factory=list)
    experience: list[TailoredRole] = Field(default_factory=list)
    projects: list[TailoredProject] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)  # ids, verbatim
    extras: list[str] = Field(default_factory=list)  # ids, verbatim


# --------------------------------------------------------------------------- memory
#
# What AutoCV remembers across applications. None of this is citable evidence: a
# resume claim can only cite the MasterProfile. Knowledge steers *questions* (don't
# re-ask, pre-fill) and active preferences steer *style*.


class AppAnswer(_Model):
    """One gap question on one application, as the user left it."""

    question_id: str
    requirement: str = ""
    question: str
    answer: str = ""
    status: Literal["draft", "no_experience", "approved", "rejected"] = "draft"
    evidence_id: str | None = None  # set when the drafted evidence was approved
    prefill_from: str | None = None  # knowledge id the answer was pre-filled from


class KnowledgeAnswer(_Model):
    """A finalized answer, remembered for future roles."""

    id: str
    topic: str  # the requirement it answered, e.g. "Kubernetes / container security"
    question: str
    answer: str = ""
    kind: Literal["experience", "no_experience"]
    evidence_id: str | None = None
    app_id: str | None = None
    company: str | None = None
    date: str


class Preference(_Model):
    """A writing-style rule learned from guidance and Review edits. Only `active`
    preferences (approved by the user) are used."""

    id: str
    text: str
    rationale: str = ""
    status: Literal["proposed", "active", "dismissed"] = "proposed"
    source_app: str | None = None
    date: str


class Knowledge(_Model):
    answers: list[KnowledgeAnswer] = Field(default_factory=list)
    preferences: list[Preference] = Field(default_factory=list)
    retired_ids: list[str] = Field(default_factory=list)  # deleted k/p ids, never reused

    def active_preferences(self) -> list[Preference]:
        return [p for p in self.preferences if p.status == "active"]


# --------------------------------------------------------------------------- io


def _str_presenter(dumper: yaml.Dumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(str, _str_presenter)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def dump_yaml(data: dict, path: Path) -> None:
    """Atomic write: a crash or a concurrent writer can never leave a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:  # same bytes on every OS
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        _replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load_profile(path: Path) -> MasterProfile:
    return MasterProfile.model_validate(load_yaml(path))


def load_tailored(path: Path) -> TailoredResume:
    return TailoredResume.model_validate(load_yaml(path))
