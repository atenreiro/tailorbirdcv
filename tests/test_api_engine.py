"""The Anthropic API engine (your own key, in the OS keychain) and the engine switch in Settings.
A fake client stands in for the Anthropic API; the keychain is in memory (conftest)."""

import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from autocv import apikey
from autocv.api import create_app
from autocv.engine import AnthropicAPIEngine, ClaudeCLIEngine, EngineError, SwitchingEngine
from autocv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
KEY = "sk-ant-api03-" + "x" * 40


class FakeClient:
    """Stands in for anthropic.AsyncAnthropic: `replies` are returned in order (an Exception is raised)."""

    def __init__(self, *replies):
        self.calls, self.replies = [], list(replies)
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        self.calls.append(kw)
        reply = self.replies.pop(0) if self.replies else json_reply({})
        if isinstance(reply, Exception):
            raise reply
        return reply


def json_reply(data, stop="end_turn"):
    import json
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=json.dumps(data))])


def tool_reply(data, stop="tool_use"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text="ok"),
                                                      SimpleNamespace(type="tool_use", input=data)])


def engine_with(client, key=KEY, model=None):
    return AnthropicAPIEngine(model=model, key=lambda: key, client_factory=lambda k: client)


SCHEMA = {"type": "object", "properties": {"status": {"type": "string"},
                                           "items": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
                                           "score": {"type": "integer", "minimum": 1, "maximum": 10}}}


def bad_request(message):
    import anthropic
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    return anthropic.BadRequestError(message, response=response, body={"error": {"message": message}})


def test_answers_come_back_as_structured_output_never_forced_tool_use():
    client = FakeClient(json_reply({"status": "OK"}))
    out = asyncio.run(engine_with(client).complete("SYSTEM", "TASK: x\nsecret profile", SCHEMA))
    assert out == {"status": "OK"}
    call = client.calls[0]
    assert call["system"] == "SYSTEM" and call["messages"] == [{"role": "user", "content": "TASK: x\nsecret profile"}]
    assert call["model"] == "claude-sonnet-5-5" and "tool_choice" not in call and "tools" not in call
    sent = call["output_config"]["format"]
    assert sent["type"] == "json_schema" and sent["schema"]["additionalProperties"] is False
    props = sent["schema"]["properties"]
    assert "maxItems" not in props["items"] and "minimum" not in props["score"]  # unsupported → dropped


def test_a_schema_the_api_cant_compile_falls_back_to_a_tool_call_once():
    client = FakeClient(bad_request("output_config.format.schema: too complex"), tool_reply({"status": "OK"}),
                        tool_reply({"status": "again"}))
    engine = engine_with(client)
    assert asyncio.run(engine.complete("S", "TASK: x", SCHEMA)) == {"status": "OK"}
    assert client.calls[1]["tool_choice"] == {"type": "auto"} and "answer" in client.calls[1]["system"]
    assert asyncio.run(engine.complete("S", "TASK: x", SCHEMA)) == {"status": "again"}
    assert "output_config" not in client.calls[2]  # remembered: no second failing request


def test_errors_and_refusals_are_explained():
    import anthropic
    conn = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    with pytest.raises(EngineError, match="internet connection"):
        asyncio.run(engine_with(FakeClient(conn)).complete("S", "TASK: x", SCHEMA))
    with pytest.raises(EngineError, match="declined"):
        asyncio.run(engine_with(FakeClient(json_reply({}, stop="refusal"))).complete("S", "TASK: x", SCHEMA))
    with pytest.raises(EngineError, match="cut off"):
        asyncio.run(engine_with(FakeClient(json_reply({}, stop="max_tokens"))).complete("S", "TASK: x", SCHEMA))
    with pytest.raises(EngineError, match="No Anthropic API key"):
        asyncio.run(engine_with(FakeClient(), key=None).complete("S", "TASK: x", SCHEMA))
    with pytest.raises(EngineError, match="error \\(400\\)"):  # a 400 that isn't about the schema: no fallback
        asyncio.run(engine_with(FakeClient(bad_request("messages: invalid"))).complete("S", "TASK: x", SCHEMA))


def test_status_makes_one_tiny_real_request_and_caches_success():
    client = FakeClient()
    engine = engine_with(client, model="claude-opus-5-5")
    assert asyncio.run(engine.status())["ready"] is True
    assert asyncio.run(engine.status())["ready"] is True
    assert len(client.calls) == 1 and client.calls[0]["max_tokens"] == 1 and client.calls[0]["model"] == "claude-opus-5-5"
    assert asyncio.run(engine_with(FakeClient(), key=None).status())["ready"] is False


def test_the_subscription_engine_never_passes_an_api_key_on(monkeypatch):
    from autocv.engine import cli_env
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token")
    env = cli_env()
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env and "PATH" in env


def test_the_key_lives_in_the_keychain(memory_keyring, monkeypatch):
    assert apikey.get() == (None, None)
    apikey.save(f"  {KEY}  ")
    assert apikey.get() == (KEY, "keychain") and memory_keyring.store[("AutoCV", "anthropic-api-key")] == KEY
    assert apikey.masked(KEY) == "sk-ant-…xxxx"
    apikey.delete()
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    assert apikey.get() == (KEY, "environment")
    with pytest.raises(ValueError):
        apikey.save("short")


@pytest.fixture
def client(tmp_path):
    private = tmp_path / "private"
    (private / "source").mkdir(parents=True)
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    store = Store(private)
    c = client_for(create_app(store))  # the real default engine: the switch
    c.store = store
    return c


def test_settings_switch_the_engine_without_a_restart(client):
    engine = SwitchingEngine(client.store)
    assert isinstance(engine.current(), ClaudeCLIEngine)
    client.put("/api/settings", json={"ai_engine": "anthropic-api", "api_model": " claude-opus-5-5 "})
    current = engine.current()
    assert isinstance(current, AnthropicAPIEngine) and current.model == "claude-opus-5-5"
    client.put("/api/settings", json={"api_model": ""})
    assert engine.current().model == "claude-sonnet-5-5"
    assert client.put("/api/settings", json={"ai_engine": "gpt"}).status_code == 422
    assert client.put("/api/settings", json={"api_model": "bad model; rm -rf"}).status_code == 422


def test_the_api_never_returns_the_key(client):
    r = client.put("/api/settings/api-key", json={"key": KEY})
    assert r.status_code == 200 and KEY not in r.text
    assert r.json()["api_key"] == {"configured": True, "source": "keychain", "masked": "sk-ant-…xxxx"}
    assert KEY not in client.get("/api/settings").text
    assert not any(KEY in p.read_text(encoding="utf-8", errors="ignore") for p in client.store.private.rglob("*") if p.is_file())
    assert client.put("/api/settings/api-key", json={"key": "nope"}).status_code == 422
    assert client.delete("/api/settings/api-key").json()["api_key"]["configured"] is False
