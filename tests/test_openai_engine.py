"""OpenAI-style engines: strict schemas (openai_schema / strip_nulls), the OpenAI API engine and the
OpenRouter engine. Fake clients stand in for the APIs; the keychain is in memory (conftest)."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

from autocv import ai, apikey, critique, importer
from autocv.api import create_app
from autocv.engine import (DEFAULT_OPENROUTER_MODEL, EngineError, OpenAIAPIEngine, OpenRouterEngine, SwitchingEngine,
                           openai_schema, strip_nulls)
from autocv.schema import TailoredResume, load_profile, load_tailored
from autocv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
PROFILE = load_profile(FIX / "profile.yaml")
TAILORED = load_tailored(FIX / "tailored.yaml")
OPENAI_KEY = "sk-proj-" + "x" * 40
OR_KEY = "sk-or-v1-" + "y" * 40


def all_schemas() -> dict:
    ids = [*ai.factcheck.evidence_index(PROFILE)]
    return {
        "analysis": ai.analysis_schema(ids, ["k1"]),
        "proposals": ai.proposals_schema([r.id for r in PROFILE.roles], ["achievement", "skill"]),
        "tailored": ai.tailored_schema(PROFILE, "hybrid"),
        "preferences": ai.preferences_schema(),
        "critique": critique.critique_schema(list(critique.claim_paths(TAILORED)), ids),
        "import": importer.import_schema(),
    }


def walk(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


@pytest.mark.parametrize("name", sorted(all_schemas()))
def test_every_schema_converts_to_openai_strict_form(name):
    strict = openai_schema(all_schemas()[name])
    assert strict["type"] == "object" and "anyOf" not in strict
    for path, node in walk(strict):
        if path.endswith(".properties"):
            continue  # a map of field names (a role's "title" is a field, not the keyword)
        assert not {"title", "default", "maxItems", "minimum", "maximum", "minItems"} & set(node), path
        if "$ref" in node:  # shared definitions stay shared, and must exist
            assert set(node) == {"$ref"} and node["$ref"].removeprefix("#/$defs/") in strict["$defs"], path
        if "properties" in node:
            assert node["additionalProperties"] is False, path
            assert set(node["required"]) == set(node["properties"]), path
    json.dumps(strict)  # serialisable
    if name == "tailored":  # the evidence-id enum is defined once, not copied into every claim
        ids = set(ai.factcheck.evidence_index(PROFILE))
        copies = [n for _, n in walk(strict) if isinstance(n.get("enum"), list) and ids <= set(n["enum"])]
        assert len(copies) == 1
    if name == "import":  # field names survive the keyword cleanup
        assert "title" in strict["properties"]["roles"]["items"]["properties"]


def test_optional_fields_become_nullable_and_their_nulls_are_dropped_again():
    schema = ai.tailored_schema(PROFILE, "hybrid")
    strict = openai_schema(schema)
    assert "summary" in strict["required"]  # optional in AutoCV, required-but-nullable for OpenAI
    answer = TAILORED.model_dump(exclude_none=True)
    answer["summary"] = None  # what a strict model sends for "no summary"
    for role in answer["experience"]:
        role.setdefault("scope", None)
    cleaned = strip_nulls(answer, schema)
    assert "summary" not in cleaned and all("scope" not in r or r["scope"] for r in cleaned["experience"])
    TailoredResume.model_validate(cleaned)
    # nulls the original schema allows (required + nullable) are kept
    crit = critique.critique_schema(["summary"], ["summary.s1"])
    issue = {"where": "summary", "kind": "unclear", "severity": "low", "problem": "p", "action": "advice",
             "rewrite": None, "question": None, "note_for": None}
    assert strip_nulls({"issues": [issue]}, crit)["issues"][0]["rewrite"] is None


# ---- the OpenAI API engine ----------------------------------------------------------------------

class FakeOpenAI:
    """Stands in for openai.AsyncOpenAI (responses, chat.completions, models, get)."""

    def __init__(self, *replies):
        self.calls, self.replies = [], list(replies)
        self.responses = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(retrieve=self._retrieve)

    async def _create(self, **kw):
        self.calls.append(kw)
        reply = self.replies.pop(0) if self.replies else None
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def _retrieve(self, model):
        self.calls.append({"retrieve": model})
        reply = self.replies.pop(0) if self.replies else None
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(id=model)

    async def get(self, path, cast_to=None):
        self.calls.append({"get": path})
        reply = self.replies.pop(0) if self.replies else {"data": {"limit_remaining": 4.5}}
        if isinstance(reply, Exception):
            raise reply
        return reply


def response(data=None, status="completed", refusal=False, reason=None):
    content = [SimpleNamespace(type="refusal", refusal="no")] if refusal else \
        [SimpleNamespace(type="output_text", text=json.dumps(data))]
    return SimpleNamespace(status=status, output=[SimpleNamespace(type="message", content=content)],
                           output_text="" if refusal else json.dumps(data),
                           incomplete_details=SimpleNamespace(reason=reason) if reason else None)


def status_error(cls_name, code, message="nope", url="https://api.openai.com/v1/responses"):
    import openai
    resp = httpx.Response(code, request=httpx.Request("POST", url))
    return getattr(openai, cls_name)(message, response=resp, body={"error": {"message": message}})


SCHEMA = {"type": "object", "properties": {"status": {"type": "string"}, "note": {"type": "string"}},
          "required": ["status"]}


def test_openai_request_is_strict_and_stores_nothing():
    client = FakeOpenAI(response({"status": "ok", "note": None}))
    eng = OpenAIAPIEngine(key=lambda: OPENAI_KEY, client_factory=lambda k: client)
    assert asyncio.run(eng.complete("SYS", "TASK: x", SCHEMA)) == {"status": "ok"}  # the null optional is dropped
    call = client.calls[0]
    assert call["store"] is False and call["instructions"] == "SYS" and call["input"] == "TASK: x"
    fmt = call["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["schema"]["required"] == ["status", "note"]
    assert "tool_choice" not in call and "tools" not in call


@pytest.mark.parametrize("reply,needle", [
    (response(refusal=True), "declined"),
    (response(status="incomplete", reason="max_output_tokens"), "cut off"),
    (status_error("AuthenticationError", 401), "rejected"),
    (status_error("RateLimitError", 429), "rate limit"),
])
def test_openai_failures_read_plainly(reply, needle):
    eng = OpenAIAPIEngine(key=lambda: OPENAI_KEY, client_factory=lambda k: FakeOpenAI(reply))
    with pytest.raises(EngineError, match=needle):
        asyncio.run(eng.complete("S", "TASK: x", SCHEMA))


def test_openai_status_checks_the_key_without_spending():
    client = FakeOpenAI()
    eng = OpenAIAPIEngine(key=lambda: OPENAI_KEY, client_factory=lambda k: client)
    st = asyncio.run(eng.status())
    assert st["ready"] and client.calls == [{"retrieve": "gpt-6.1-sol"}]
    assert not asyncio.run(OpenAIAPIEngine(key=lambda: None).status())["ready"]


# ---- OpenRouter -----------------------------------------------------------------------------------

def chat(data=None, finish="stop", refusal=None):
    msg = SimpleNamespace(content=None if data is None else json.dumps(data), refusal=refusal, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)])


def test_openrouter_defaults_to_the_same_claude_with_zero_retention():
    client = FakeOpenAI(chat({"status": "ok", "note": "n"}))
    eng = OpenRouterEngine(key=lambda: OR_KEY, client_factory=lambda k: client)
    assert eng.model == DEFAULT_OPENROUTER_MODEL == "anthropic/claude-sonnet-5.5"
    assert asyncio.run(eng.complete("SYS", "TASK: x", SCHEMA)) == {"status": "ok", "note": "n"}
    call = client.calls[0]
    assert call["messages"][0] == {"role": "system", "content": "SYS"}
    assert call["response_format"]["json_schema"]["strict"] is True
    assert call["extra_body"]["provider"] == {"require_parameters": True, "data_collection": "deny", "zdr": True,
                                              "allow_fallbacks": True}
    assert "temperature" not in call and "max_completion_tokens" not in call


def test_openrouter_can_route_to_anthropic_itself():
    client = FakeOpenAI(chat({"status": "ok"}))
    eng = OpenRouterEngine(key=lambda: OR_KEY, client_factory=lambda k: client, zdr=False)
    asyncio.run(eng.complete("S", "TASK: x", SCHEMA))
    assert client.calls[0]["extra_body"]["provider"] == {"require_parameters": True, "data_collection": "deny",
                                                         "only": ["anthropic"], "allow_fallbacks": False}


@pytest.mark.parametrize("reply,needle", [
    (status_error("APIStatusError", 402, url="https://openrouter.ai/api/v1/chat/completions"), "credit"),
    (status_error("InternalServerError", 503, url="https://openrouter.ai/api/v1/chat/completions"), "privacy settings"),
    (status_error("PermissionDeniedError", 403, "flagged", url="https://openrouter.ai/api/v1/chat/completions"), "moderation"),
    (chat(None, finish="length"), "cut off"),
    (chat(None, refusal="no"), "declined"),
])
def test_openrouter_failures_read_plainly(reply, needle):
    eng = OpenRouterEngine(key=lambda: OR_KEY, client_factory=lambda k: FakeOpenAI(reply))
    with pytest.raises(EngineError, match=needle):
        asyncio.run(eng.complete("S", "TASK: x", SCHEMA))


def test_openrouter_status_shows_the_credit_left():
    eng = OpenRouterEngine(key=lambda: OR_KEY, client_factory=lambda k: FakeOpenAI())
    st = asyncio.run(eng.status())
    assert st["ready"] and "$4.50 credit left" in st["detail"]


# ---- keys and the engine switch -------------------------------------------------------------------

def test_each_provider_has_its_own_key(memory_keyring, monkeypatch):
    apikey.save(OPENAI_KEY, "openai")
    apikey.save(OR_KEY, "openrouter")
    assert apikey.get("openai") == (OPENAI_KEY, "keychain") and apikey.get("openrouter") == (OR_KEY, "keychain")
    assert apikey.get() == (None, None)  # the Anthropic key is separate
    assert memory_keyring.store[("AutoCV", "openai-api-key")] == OPENAI_KEY
    apikey.delete("openai")
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)
    assert apikey.get("openai") == (OPENAI_KEY, "environment")


@pytest.fixture
def client(tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    (private / "profile.yaml").write_text((FIX / "profile.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    store = Store(private)
    c = client_for(create_app(store, SwitchingEngine(store)))
    c.store = store
    return c


def test_settings_choose_any_of_the_five_engines(client):
    engine = SwitchingEngine(client.store)
    client.put("/api/settings", json={"ai_engine": "openai-api", "openai_model": " gpt-6-luna "})
    assert isinstance(engine.current(), OpenAIAPIEngine) and engine.current().model == "gpt-6-luna"
    client.put("/api/settings", json={"ai_engine": "openrouter-api"})
    cur = engine.current()
    assert isinstance(cur, OpenRouterEngine) and cur.model == DEFAULT_OPENROUTER_MODEL and cur.zdr is True
    client.put("/api/settings", json={"openrouter_zdr": False, "openrouter_model": "anthropic/claude-opus-5.5"})
    assert engine.current().zdr is False and engine.current().model == "anthropic/claude-opus-5.5"
    client.put("/api/settings", json={"ai_engine": "codex-cli"})
    assert engine.current().name == "codex-cli"
    assert client.put("/api/settings", json={"ai_engine": "gpt"}).status_code == 422
    settings = yaml.safe_load((client.store.private / "settings.json").read_text(encoding="utf-8"))
    settings["ai_engine"] = "something-newer"  # a hand-edited or newer value falls back
    (client.store.private / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    assert client.store.settings()["ai_engine"] == "claude-cli"


def test_provider_keys_are_stored_per_provider_and_never_returned(client):
    r = client.put("/api/settings/api-key?provider=openrouter", json={"key": OR_KEY})
    assert r.status_code == 200 and OR_KEY not in r.text
    keys = r.json()["api_keys"]
    assert keys["openrouter"]["configured"] and not keys["openai"]["configured"] and not keys["anthropic"]["configured"]
    assert keys["openrouter"]["masked"] == "sk-or-v…yyyy" and keys["openrouter"]["env"] == "OPENROUTER_API_KEY"
    assert client.put("/api/settings/api-key?provider=nope", json={"key": OR_KEY}).status_code == 422
    assert not any(OR_KEY in p.read_text(encoding="utf-8", errors="ignore")
                   for p in client.store.private.rglob("*") if p.is_file())
    engines = {e["id"]: e for e in client.get("/api/settings").json()["engines"]}
    assert set(engines) == {"claude-cli", "codex-cli", "anthropic-api", "openai-api", "openrouter-api"}
    assert engines["openrouter-api"]["default_model"] == "anthropic/claude-sonnet-5.5"
    assert client.delete("/api/settings/api-key?provider=openrouter").json()["api_keys"]["openrouter"]["configured"] is False


def test_openrouter_without_zero_retention_only_pins_anthropic_for_claude():
    eng = OpenRouterEngine(model="openai/gpt-6.1-sol", key=lambda: OR_KEY, zdr=False)
    assert eng.routing()["provider"] == {"require_parameters": True, "data_collection": "deny"}


def test_saved_roles_keep_their_company_and_title(client):
    data = client.get("/api/profile").json()
    data["profile"]["roles"][0]["employer"] = "  "
    r = client.put("/api/profile", json=data["profile"], headers={"If-Match": data["version"]})
    assert r.status_code == 422 and "company name and a title" in r.json()["detail"]
