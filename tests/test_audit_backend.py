"""Regression tests for the backend audit findings (A–M). Each test reproduces the original
failure on the fictional fixture profile; Word is never opened (to_pdf is stubbed)."""

import argparse
import asyncio
import copy
import datetime as dt
import json
import os
import shutil
from pathlib import Path

import httpx
import pytest
import yaml

from autocv import ai, cli, factcheck, jobfetch
from autocv import pdf as pdfmod
from autocv.api import create_app
from autocv.engine import FakeEngine
from autocv.ingest import merge_reingest
from autocv.store import APP_SEP, LEGACY_IDS, RetiredIdReused, Store, _write_json_atomic
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
TODAY = f"{dt.date.today():%Y-%m-%d}"
JD = "# Detection Lead — Example Capital\n\n" + "We need a hands-on detection engineering lead. " * 10
TAILORED = yaml.safe_load((FIX / "tailored.yaml").read_text())
ANALYSIS = {"company": "Example Capital", "role": "Lead", "industry": "quant", "track": "ic", "seniority": "S",
            "location": "SG", "summary": "x", "requirements": [], "keywords": [], "known_gaps": [],
            "questions": [{"id": "q1", "requirement": "Kubernetes", "question": "Any Kubernetes?", "prefill_from": ""}]}
REVIEW = {"verdict": {"decision": "borderline", "reason": "ok"},
          "scores": {k: {"score": 7, "why": "ok"} for k in ("fit", "impact", "clarity", "seniority")},
          "skim": {"takeaway": "x", "lands": [], "misses": []}, "strengths": [],
          "issues": [{"where": "summary", "kind": "unclear", "severity": "low", "problem": "p", "action": "advice",
                      "rewrite": None, "question": None, "note_for": None}]}


def long_tailored():
    t = copy.deepcopy(TAILORED)
    t["experience"][0]["bullets"] = t["experience"][0]["bullets"] * 25
    return t


@pytest.fixture
def env(tmp_path, monkeypatch):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    shutil.copy(FIX / "tailored.yaml", private / "source" / "base_tailored.yaml")

    def fake_to_pdf(docx, pdf=None, timeout=0):  # stands in for Word
        out = pdf or docx.with_suffix(".pdf")
        out.write_bytes(b"%PDF-1.4 stand-in")
        return out
    monkeypatch.setattr(pdfmod, "to_pdf", fake_to_pdf)
    monkeypatch.setattr(pdfmod, "page_count", lambda p: 2)
    engine = FakeEngine({"analyze": ANALYSIS, "compose": TAILORED, "repair": TAILORED, "trim": TAILORED,
                         "critique": REVIEW})
    store = Store(private)
    return client_for(create_app(store, engine)), store, engine


def new_app(client, **body):
    return client.post("/api/applications", json={"jd": JD, "company": "Example Capital", "role": "Lead", **body}).json()["id"]


def composed_app(client):
    app_id = new_app(client)
    client.post(f"/api/applications/{app_id}/analyze")
    client.post(f"/api/applications/{app_id}/compose", json={})
    return app_id


def edit_profile(client, change):
    loaded = client.get("/api/profile").json()
    change(loaded["profile"])
    return client.put("/api/profile", json=loaded["profile"], headers={"If-Match": loaded["version"]})


# ---- A: freeze gate ---------------------------------------------------------------------------

def test_freeze_refused_after_the_profile_changed(env):
    from autocv.store import render_fingerprint
    client, store, _ = env
    app_id = composed_app(client)
    client.post(f"/api/applications/{app_id}/build")
    assert store.meta(app_id)["built_profile"] == render_fingerprint(store.profile(), store.tailored(app_id))
    # profile edits the resume doesn't print leave the build current…
    edit_profile(client, lambda p: p["vocabulary"].append("Singapore"))
    assert not client.get(f"/api/applications/{app_id}").json()["outputs_stale"]
    # …but a change to something it prints (a role's locked title) makes it outdated
    edit_profile(client, lambda p: p["roles"][0].update(title=p["roles"][0]["title"] + " (Acting)"))
    assert client.get(f"/api/applications/{app_id}").json()["outputs_stale"]
    res = client.post(f"/api/applications/{app_id}/freeze")
    assert res.status_code == 409 and "profile changed" in res.json()["detail"]["message"]
    assert store.sent_copies(app_id) == []
    assert client.post(f"/api/applications/{app_id}/freeze?build=true").status_code == 200  # rebuild fixes it


def test_freeze_refused_when_the_draft_no_longer_passes_the_fact_check(env):
    client, store, _ = env
    app_id = composed_app(client)
    client.post(f"/api/applications/{app_id}/build")
    edit_profile(client, lambda p: p["roles"][0].update(
        achievements=[a for a in p["roles"][0]["achievements"] if a["id"] != "acme-bank.a2"]))
    # nothing the resume prints from the profile changed, so only the fact-check can catch this
    res = client.patch(f"/api/applications/{app_id}", json={"status": "applied"})
    assert res.status_code == 409 and "fact-check" in res.json()["detail"]["message"]
    assert store.sent_copies(app_id) == [] and store.meta(app_id)["status"] != "applied"


def test_build_hash_is_of_the_bytes_rendered(env, monkeypatch):
    client, store, _ = env
    app_id = composed_app(client)
    original = (store.app_path(app_id) / "tailored.yaml").read_bytes()
    real_check, edited = factcheck.check, {"done": False}

    def check_while_user_saves(profile, tailored):  # a save lands between reading and hashing
        if not edited["done"]:
            edited["done"] = True
            t = copy.deepcopy(TAILORED)
            t["highlights"][0]["text"] = "Cut false positives by over 65%."
            from autocv.schema import TailoredResume
            store.save_tailored(app_id, TailoredResume.model_validate(t))
        return real_check(profile, tailored)
    monkeypatch.setattr(factcheck, "check", check_while_user_saves)
    client.post(f"/api/applications/{app_id}/build")
    monkeypatch.setattr(factcheck, "check", real_check)
    assert store.meta(app_id)["built_hash"] == file_version_of(original)   # labelled with what was rendered
    assert store.outputs_stale(app_id)                                      # …so the new draft shows as unbuilt
    assert client.post(f"/api/applications/{app_id}/freeze").status_code == 409


def file_version_of(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]


def test_cli_build_records_the_profile_version(env, monkeypatch):
    client, store, _ = env
    app_id = composed_app(client)
    monkeypatch.setattr(cli, "STORE", store)
    monkeypatch.setattr(cli, "PROFILE", store.profile_path)
    monkeypatch.setattr(cli, "APPS", store.apps_dir)
    assert cli.cmd_build(argparse.Namespace(app=app_id, no_pdf=False, max_pages=2)) == 0
    meta = store.meta(app_id)
    from autocv.store import render_fingerprint
    assert meta["built_profile"] == render_fingerprint(store.profile(), store.tailored(app_id))
    assert meta["built_hash"] == store.tailored_hash(app_id)
    assert store.freeze_problem(app_id) is None


# ---- B: AI trim proposes, never saves ---------------------------------------------------------

def test_trim_returns_a_fact_checked_proposal_without_saving(env):
    client, store, _ = env
    app_id = composed_app(client)
    t = client.get(f"/api/applications/{app_id}").json()["tailored"]
    client.put(f"/api/applications/{app_id}/tailored", json={**t, "experience": long_tailored()["experience"]})
    before = (store.app_path(app_id) / "tailored.yaml").read_bytes()
    data = client.post(f"/api/applications/{app_id}/trim").json()
    assert (store.app_path(app_id) / "tailored.yaml").read_bytes() == before
    proposal = data["trim_proposal"]
    assert set(proposal) >= {"tailored", "lines", "budget", "trim_rounds"}
    from autocv.schema import TailoredResume
    assert factcheck.check(store.profile(), TailoredResume.model_validate(proposal["tailored"])).ok


def test_trim_that_breaks_the_fact_check_proposes_nothing(env):
    client, store, engine = env
    app_id = composed_app(client)
    t = client.get(f"/api/applications/{app_id}").json()["tailored"]
    client.put(f"/api/applications/{app_id}/tailored", json={**t, "experience": long_tailored()["experience"]})
    bad = copy.deepcopy(TAILORED)
    bad["highlights"][0]["text"] = "Cut false positives by 99%."
    engine.responses.update(trim=bad, repair=bad)
    before = (store.app_path(app_id) / "tailored.yaml").read_bytes()
    data = client.post(f"/api/applications/{app_id}/trim").json()
    assert data["trim_proposal"] is None and (store.app_path(app_id) / "tailored.yaml").read_bytes() == before


# ---- C: retired ids stay retired ----------------------------------------------------------------

def _delete_a2(p):
    p["roles"][0]["achievements"] = [a for a in p["roles"][0]["achievements"] if a["id"] != "acme-bank.a2"]


def test_profile_put_cannot_unretire_an_id(env):
    client, store, _ = env
    edit_profile(client, _delete_a2)
    assert "acme-bank.a2" in store.profile().retired_ids

    def bring_back(p):
        p["roles"][0]["achievements"].append({"id": "acme-bank.a2", "text": "A different fact."})
        p["retired_ids"] = []                                    # a client dropping the list changes nothing
    res = edit_profile(client, bring_back)
    assert res.status_code == 422 and "acme-bank.a2" in res.json()["detail"]
    y = client.get("/api/profile/yaml").json()
    text = y["yaml"].replace("achievements:\n", "achievements:\n  - id: acme-bank.a2\n    text: Other.\n", 1)
    assert client.put("/api/profile/yaml", json={"yaml": text}, headers={"If-Match": y["version"]}).status_code == 422
    assert "acme-bank.a2" not in store.profile().all_ids() and "acme-bank.a2" in store.profile().retired_ids


def test_restore_cannot_unretire_an_id(env):
    client, store, _ = env
    edit_profile(client, lambda p: p["vocabulary"].append("Singapore"))  # snapshot with a2 still live
    edit_profile(client, _delete_a2)
    snap = client.get("/api/history/profile").json()[-1]["id"]
    before = store.profile_path.read_bytes()
    res = client.post(f"/api/history/profile/{snap}/restore")
    assert res.status_code == 422 and "acme-bank.a2" in res.json()["detail"]
    assert store.profile_path.read_bytes() == before


def test_save_knowledge_cannot_unretire_an_id(env):
    _, store, _ = env
    from autocv.schema import Knowledge
    k = Knowledge.model_validate({"answers": [{"id": "k1", "topic": "t", "question": "q", "kind": "no_experience",
                                               "date": "2026-10-01"}]})
    store.save_knowledge(k)
    store.save_knowledge(Knowledge())                       # k1 forgotten → retired
    with pytest.raises(RetiredIdReused):
        store.save_knowledge(k)


def _ingested():
    """What `ingest` would produce for a resume where a1 is unchanged, a2 was reworded, a new
    bullet was added, and the telco role is unchanged."""
    p = yaml.safe_load((FIX / "profile.yaml").read_text())
    acme = p["roles"][0]
    acme["achievements"] = [
        {"id": "acme-bank.a1", "text": "Shipped a new detection pipeline."},                 # new bullet first
        {"id": "acme-bank.a2", "text": acme["achievements"][0]["text"]},                      # old a1, moved
        {"id": "acme-bank.a3", "text": "Own vendor spend across six platforms (Fastly, AWS WAF, Imperva)."}]  # reworded a2
    p["synonyms"], p["vocabulary"] = [], []
    p["headlines"] = [p["headlines"][0]]
    base = copy.deepcopy(TAILORED)
    base["experience"][0]["bullets"] = [{"text": a["text"], "sources": [a["id"]]} for a in acme["achievements"]]
    return p, base


def test_reingest_keeps_meaning_of_every_id():
    old = yaml.safe_load((FIX / "profile.yaml").read_text())
    old["roles"][0]["achievements"].append({"id": "acme-bank.a4", "text": "Hardened Kubernetes clusters.",
                                             "source": "interview", "in_base_resume": False})
    old["retired_ids"] = ["acme-bank.a3"]
    new, base = merge_reingest(copy.deepcopy(old), *_ingested())
    ach = {a["id"]: a["text"] for a in new["roles"][0]["achievements"]}
    old_text = {a["id"]: a["text"] for a in old["roles"][0]["achievements"]}
    assert ach["acme-bank.a1"] == old_text["acme-bank.a1"]                  # unchanged fact keeps its id
    assert "acme-bank.a2" not in ach                                         # reworded: old id not reused…
    assert "acme-bank.a3" not in ach                                         # …and a retired id never is
    assert ach["acme-bank.a4"] == "Hardened Kubernetes clusters."           # interview evidence kept
    fresh = {i: t for i, t in ach.items() if i not in old_text}
    assert sorted(fresh.values()) == ["Own vendor spend across six platforms (Fastly, AWS WAF, Imperva).",
                                      "Shipped a new detection pipeline."]
    assert new["retired_ids"] == ["acme-bank.a3"] and new["synonyms"] == old["synonyms"]
    assert {h["id"] for h in new["headlines"]} == {"h.leader", "h.engineer"}  # approved headlines kept
    cited = [s for b in base["experience"][0]["bullets"] for s in b["sources"]]
    assert [ach[s] for s in cited] == [b["text"] for b in base["experience"][0]["bullets"]]  # base remapped


def test_ingest_force_goes_through_save_profile(env, monkeypatch):
    _, store, _ = env
    monkeypatch.setattr(cli, "STORE", store)
    monkeypatch.setattr(cli, "PROFILE", store.profile_path)
    monkeypatch.setattr(cli, "BASE_TAILORED", store.base_tailored_path)
    monkeypatch.setattr(cli, "ingest", lambda path: _ingested())
    assert cli.cmd_ingest(argparse.Namespace(force=True)) == 0
    p = store.profile()
    assert "acme-bank.a2" in p.retired_ids and "acme-bank.a2" not in p.all_ids()
    assert any(h["cause"] == "ingest force" for h in store.history("profile"))
    assert factcheck.check(p, store.base_tailored()).ok   # the base layout cites the merged ids


# ---- D: migration never breaks startup ----------------------------------------------------------

def _flat(store, name, company="Northwind", role="Engineer", meta=True):
    folder = store.apps_dir / name
    folder.mkdir(parents=True)
    (folder / "jd.md").write_text(JD)
    if meta:
        (folder / "meta.json").write_text(json.dumps({"company": company, "role": role, "status": "draft",
                                                      "created": "2026-10-01T10:00:00"}))
    return name


def test_migration_records_each_move_as_it_happens(env, monkeypatch):
    _, store, _ = env
    a = _flat(store, "2026-10-01_northwind_engineer")
    b = _flat(store, "2026-10-02_contoso_analyst", "Contoso", "Analyst")
    (store.private / "knowledge.yaml").write_text(yaml.safe_dump({"answers": [
        {"id": "k1", "topic": "t", "question": "q", "kind": "no_experience", "app_id": a, "date": "2026-10-01"}]}))
    real_rename = Path.rename

    def crash_on_second(self, target):
        if self.name == b:
            raise OSError("disk went away")
        return real_rename(self, target)
    monkeypatch.setattr(Path, "rename", crash_on_second)
    moved = store.migrate_layout()                           # no exception
    assert moved == {a: "northwind~2026-10-01_engineer"}
    assert json.loads((store.apps_dir / LEGACY_IDS).read_text())[a] == "northwind~2026-10-01_engineer"
    assert store.knowledge().answers[0].app_id == "northwind~2026-10-01_engineer"
    assert (store.apps_dir / b / "meta.json").exists()       # interrupted: left in place, retried next start
    monkeypatch.setattr(Path, "rename", real_rename)
    assert store.migrate_layout() == {b: "contoso~2026-10-02_analyst"}
    assert store.meta(a)["company"] == "Northwind" and store.meta(b)["company"] == "Contoso"


def test_unreadable_meta_is_skipped_and_flat_folders_without_meta_migrate(env):
    _, store, _ = env
    bad = _flat(store, "2026-10-01_broken_thing")
    (store.apps_dir / bad / "meta.json").write_text("{not json")
    nometa = _flat(store, "2026-10-02_acme-corp_security-lead", meta=False)
    moved = store.migrate_layout()
    assert moved == {nometa: "acme-corp~2026-10-02_security-lead"}
    meta = store.meta(nometa)
    assert meta["company"] == "Acme Corp" and meta["role"] == "Security Lead"
    assert (store.apps_dir / bad).exists()                     # left alone…
    assert all(not a["id"].startswith(bad) for a in store.list_apps())  # …and never taken for a company folder


def test_server_starts_with_corrupt_files(env):
    _, store, engine = env
    good = new_app(env[0])
    broken = store.create_app("Broken Co", "Role", JD)
    (store.app_path(broken) / "meta.json").write_text("{oops")
    (store.apps_dir / LEGACY_IDS).write_text("[not, json")
    store.profile_path.write_text(store.profile_path.read_text().replace("headlines:", "headlinez:"))
    client = client_for(create_app(store, engine))           # must not raise
    rows = {r["id"]: r for r in client.get("/api/applications").json()}
    assert set(rows) == {good, broken} and rows[broken]["broken"] and not rows[good].get("broken")
    assert client.get(f"/api/applications/{good}").status_code == 200
    assert client.get(f"/api/applications/{broken}").status_code == 409
    assert client.delete(f"/api/applications/{broken}").status_code == 204


def test_cli_main_survives_a_failing_migration(env, monkeypatch, capsys):
    _, store, _ = env
    monkeypatch.setattr(cli, "STORE", store)
    monkeypatch.setattr(store.__class__, "migrate_layout", lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(cli, "cmd_evidence", lambda args: 0)
    assert cli.main(["evidence"]) == 0
    assert "migration failed" in capsys.readouterr().err


# ---- E: status/outcome consistency ---------------------------------------------------------------

def test_rejected_patch_never_freezes(env):
    client, store, _ = env
    app_id = composed_app(client)
    client.post(f"/api/applications/{app_id}/build")
    res = client.patch(f"/api/applications/{app_id}", json={"status": "applied", "outcome": "rejected"})
    assert res.status_code == 422 and store.sent_copies(app_id) == []


def test_mark_applied_from_closed_clears_the_outcome(env):
    client, store, _ = env
    app_id = composed_app(client)
    client.patch(f"/api/applications/{app_id}", json={"status": "closed", "outcome": "did_not_apply"})
    meta = client.post(f"/api/applications/{app_id}/freeze?build=true&mark_applied=true").json()["meta"]
    assert meta["status"] == "applied" and "outcome" not in meta and "closed_at" not in meta


def test_reentering_applied_freezes_only_once(env):
    client, store, _ = env
    app_id = composed_app(client)
    client.post(f"/api/applications/{app_id}/freeze?build=true&mark_applied=true")
    client.patch(f"/api/applications/{app_id}", json={"status": "interview"})
    assert client.patch(f"/api/applications/{app_id}", json={"status": "applied"}).status_code == 200
    client.post(f"/api/applications/{app_id}/freeze?mark_applied=true")
    assert [c["reason"] for c in store.sent_copies(app_id)] == ["applied"]
    assert store.meta(app_id)["status"] == "applied"


# ---- F: funnel ---------------------------------------------------------------------------------

def test_manual_copy_is_not_evidence_of_applying(env):
    client, store, _ = env
    app_id = composed_app(client)
    client.post(f"/api/applications/{app_id}/freeze?build=true")         # "Freeze a copy", not applied
    meta = store.meta(app_id)
    meta.pop("milestones")
    _write_json_atomic(store.app_path(app_id) / "meta.json", meta)       # as before milestones existed
    assert store.reached(app_id)[0] == "built"


def test_legacy_closed_falls_back_to_the_outcome_and_migration_records_it(env):
    client, store, _ = env
    app_id = new_app(client)
    meta = store.meta(app_id)
    meta.pop("milestones", None)
    meta.update(status="closed", outcome="rejected", closed_at="2026-09-01T10:00:00")
    _write_json_atomic(store.app_path(app_id) / "meta.json", meta)
    assert store.reached(app_id) == ("applied", "2026-09-01T10:00:00")
    meta.update(status="rejected", updated="2026-09-02T10:00:00")
    meta.pop("outcome"), meta.pop("closed_at")
    _write_json_atomic(store.app_path(app_id) / "meta.json", meta)
    assert store.reached(app_id)[0] == "applied"
    store.migrate_layout()
    assert store.meta(app_id)["milestones"] == {"applied": "2026-09-02T10:00:00"}


# ---- G: review run ids ----------------------------------------------------------------------

def test_review_issue_ids_are_never_reused(env):
    client, store, _ = env
    app_id = composed_app(client)
    seen = []
    for _ in range(7):
        seen.append(client.post(f"/api/applications/{app_id}/critique").json()["critique"]["latest"]["issues"][0]["id"])
    assert len(set(seen)) == 7 and seen[-1] == "r7-i1"
    assert len(store.critique(app_id)["runs"]) == 5


# ---- H: legacy ids and renames ------------------------------------------------------------------

def test_legacy_id_requests_use_the_current_id(env):
    client, store, _ = env
    _flat(store, "2026-10-01_northwind_engineer")
    store.migrate_layout()
    client.put("/api/applications/2026-10-01_northwind_engineer/answers", json=[
        {"question_id": "q1", "requirement": "K8s", "question": "Any K8s?", "status": "no_experience"}])
    assert [k.app_id for k in store.knowledge().answers] == ["northwind~2026-10-01_engineer"]
    assert client.get("/api/applications/2026-10-01_northwind_engineer").json()["id"] == "northwind~2026-10-01_engineer"


def test_rename_keeps_old_ids_working_and_never_reuses_them(env):
    _, store, _ = env
    placeholder = store.create_app("company", "role", JD)
    renamed = store.rename_app(placeholder, "Example Capital", "Lead")
    assert store.canonical_id(placeholder) == renamed                      # old links still work
    other = store.create_app("company", "role", JD)
    assert other != placeholder and store.canonical_id(other) == other     # the freed id isn't handed out
    final = store.rename_app(renamed, "Example Capital", "Detection Lead")
    assert store.canonical_id(placeholder) == final == store.canonical_id(renamed)  # chains are updated


def test_rename_to_a_prefix_of_the_role_still_moves(env):
    _, store, _ = env
    app_id = store.create_app("Example Capital", "Lead Manager", JD)
    new = store.rename_app(app_id, "Example Capital", "Lead")
    assert new == f"example-capital~{TODAY}_lead" and store.canonical_id(app_id) == new


def test_request_finishing_after_delete_is_a_clean_404(env):
    client, store, engine = env
    app_id = new_app(client)
    client.post(f"/api/applications/{app_id}/analyze")

    def compose(_prompt):
        store.delete_app(app_id)
        return TAILORED
    engine.responses["compose"] = compose
    assert client.post(f"/api/applications/{app_id}/compose", json={}).status_code == 404


# ---- I: model-supplied question ids ----------------------------------------------------------------

def test_analyze_renumbers_forged_question_ids():
    from autocv.schema import load_profile
    profile = load_profile(FIX / "profile.yaml")
    questions = [{"id": "kg-k1", "requirement": "a", "question": "A?", "prefill_from": ""},
                 {"id": "q1", "requirement": "b", "question": "B?", "prefill_from": ""},
                 {"id": "hm-r1-i1", "requirement": "c", "question": "C?", "prefill_from": ""},
                 {"id": "q1", "requirement": "d", "question": "D?", "prefill_from": ""}]
    engine = FakeEngine({"analyze": {**ANALYSIS, "questions": questions}})
    result = asyncio.run(ai.analyze(engine, profile, JD))
    ids = [q["id"] for q in result["questions"]]
    assert ids == ["q2", "q1", "q3", "q4"]


# ---- J: approving evidence twice ------------------------------------------------------------------

def test_evidence_approval_is_idempotent(env):
    client, store, _ = env
    body = {"target": "acme-bank", "text": "Approved fact."}
    first = client.post("/api/profile/evidence", json=body).json()["id"]
    second = client.post("/api/profile/evidence", json={**body, "text": " Approved  fact. "}).json()["id"]
    assert first == second
    assert [a.text for a in store.profile().roles[0].achievements].count("Approved fact.") == 1


# ---- K: security hardening -------------------------------------------------------------------------

@pytest.mark.parametrize("ip", ["64:ff9b::7f00:1", "64:ff9b::a00:1", "64:ff9b::c0a8:101", "64:ff9b:1::808:808",
                                "::127.0.0.1", "::10.0.0.1", "::a9fe:a9fe", "2002:7f00:1::1", "2002:c0a8:101::1",
                                "2001:0:808:808::f5ff:fffe", "::ffff:10.0.0.1"])
def test_ipv4_embedded_in_ipv6_is_checked(ip):
    with pytest.raises(jobfetch.BlockedURL):
        jobfetch.check_addr(ip)


@pytest.mark.parametrize("ip", ["8.8.8.8", "64:ff9b::808:808", "2606:4700:4700::1111", "2002:808:808::1"])
def test_public_addresses_still_pass(ip):
    jobfetch.check_addr(ip)


@pytest.mark.parametrize("declared", [True, False])
def test_browser_responses_are_capped(monkeypatch, declared):
    monkeypatch.setattr(jobfetch, "MAX_BYTES", 1000)

    async def body():
        for _ in range(10):
            yield b"x" * 200

    def handler(request):
        if declared:
            return httpx.Response(200, content=b"x" * 2000)
        return httpx.Response(200, content=body())

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await jobfetch._capped_request(client, "GET", "http://example.com/", {}, None)
    with pytest.raises(jobfetch.TooLarge):
        asyncio.run(go())


def test_small_browser_responses_pass(monkeypatch):
    async def go():
        transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"hello"))
        async with httpx.AsyncClient(transport=transport) as client:
            return await jobfetch._capped_request(client, "GET", "http://example.com/", {}, None)
    resp, content = asyncio.run(go())
    assert content == b"hello" and resp.status_code == 200


@pytest.mark.parametrize("site,ok", [("cross-site", False), ("same-site", False), ("same-origin", True),
                                     ("none", True), (None, True)])
def test_cross_site_reads_are_refused(env, site, ok):
    client, _, _ = env
    headers = {"Sec-Fetch-Site": site} if site else {}
    res = client.get("/api/profile", headers=headers)
    assert (res.status_code == 200) == ok and (ok or res.status_code == 403)


# ---- L/M: id hygiene ------------------------------------------------------------------------------------

def test_case_aliases_and_non_applications_are_not_ids(env):
    client, store, _ = env
    app_id = new_app(client)
    company, _, rest = app_id.partition(APP_SEP)
    with pytest.raises(KeyError):
        store.app_path(f"{company.upper()}{APP_SEP}{rest}")
    with pytest.raises(KeyError):
        store.delete_app(f"{company}{APP_SEP}{rest.upper()}")
    (store.apps_dir / company / "notes").mkdir()                 # not an application (no meta.json)
    assert client.delete(f"/api/applications/{company}{APP_SEP}notes").status_code == 404
    assert (store.apps_dir / company / "notes").exists()
    os.symlink(store.app_path(app_id), store.apps_dir / company / "alias")
    with pytest.raises(KeyError):
        store.app_path(f"{company}{APP_SEP}alias")
    assert store.app_path(app_id).exists()


@pytest.mark.parametrize("bad", ["a~b%00c", "a~" + "x" * 400, "x" * 300 + "~" + "y" * 300])
def test_odd_ids_are_404_not_500(env, bad):
    client, _, _ = env
    assert client.get(f"/api/applications/{bad}").status_code == 404
    assert client.delete(f"/api/applications/{bad}").status_code == 404


def test_long_names_are_capped_and_failures_leave_no_folder(env, monkeypatch):
    client, store, _ = env
    app_id = new_app(client, company="C" * 300, role="R" * 300)
    company, _, rest = app_id.partition(APP_SEP)
    assert len(company) <= 60 and len(rest) <= 72 and store.app_path(app_id).exists()

    def boom(self, folder, meta):
        raise OSError("disk full")
    monkeypatch.setattr(Store, "_write_meta", boom)
    with pytest.raises(OSError):
        store.create_app("Fresh Co", "Role", JD)
    assert not (store.apps_dir / "fresh-co").exists()


def test_list_is_newest_first_by_creation_time(env):
    client, store, _ = env
    older = store.create_app("Zeta Co", "Role", JD)
    newer = store.create_app("Alpha Co", "Role", JD)
    store.update_meta(older, created="2026-01-01T09:00:00")
    store.update_meta(newer, created="2026-01-02T09:00:00")
    assert [a["id"] for a in store.list_apps()] == [newer, older]


def test_delete_by_old_id_clears_every_reference(env):
    client, store, _ = env
    old = _flat(store, "2026-10-01_northwind_engineer")
    (store.private / "knowledge.yaml").write_text(yaml.safe_dump({"answers": [
        {"id": "k1", "topic": "t", "question": "q", "kind": "no_experience", "app_id": old, "date": "2026-10-01"}]}))
    store.migrate_layout()
    assert client.delete(f"/api/applications/{old}").status_code == 204
    assert store.knowledge().answers[0].app_id is None
    assert old not in json.loads((store.apps_dir / LEGACY_IDS).read_text())


def test_builds_from_before_fingerprints_count_as_current(env):
    client, store, _ = env
    app_id = composed_app(client)
    client.post(f"/api/applications/{app_id}/build")
    meta = store.meta(app_id)
    meta.pop("built_profile")
    from autocv.store import _write_json_atomic
    _write_json_atomic(store.app_path(app_id) / "meta.json", meta)   # as an older build wrote it
    assert not client.get(f"/api/applications/{app_id}").json()["outputs_stale"]
    assert store.freeze_problem(app_id) is None                       # the fact-check still ran and passed
