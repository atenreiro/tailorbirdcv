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
    def __init__(self, reply=None, error=None):
        self.calls, self.retrieved, self.reply, self.error = [], [], reply, error
        self.messages = SimpleNamespace(create=self._create)
        self.models = SimpleNamespace(retrieve=self._retrieve)

    async def _create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return self.reply

    async def _retrieve(self, model):
        self.retrieved.append(model)
        if self.error:
            raise self.error
        return {"id": model}


def tool_reply(data, stop="tool_use"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text="ok"),
                                                      SimpleNamespace(type="tool_use", input=data)])


def engine_with(client, key=KEY, model=None):
    return AnthropicAPIEngine(model=model, key=lambda: key, client_factory=lambda k: client)


def test_structured_output_comes_from_a_forced_tool_call():
    client = FakeClient(tool_reply({"status": "OK"}))
    schema = {"type": "object", "properties": {"status": {"type": "string"}}}
    out = asyncio.run(engine_with(client).complete("SYSTEM", "TASK: x\nsecret profile", schema))
    assert out == {"status": "OK"}
    call = client.calls[0]
    assert call["system"] == "SYSTEM" and call["messages"] == [{"role": "user", "content": "TASK: x\nsecret profile"}]
    assert call["tools"][0]["input_schema"] == schema and call["tool_choice"] == {"type": "tool", "name": "answer"}
    assert call["model"] == "claude-sonnet-5-5"


def test_errors_are_explained():
    import anthropic
    conn = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    with pytest.raises(EngineError, match="internet connection"):
        asyncio.run(engine_with(FakeClient(error=conn)).complete("S", "TASK: x", {"type": "object"}))
    with pytest.raises(EngineError, match="cut off"):
        asyncio.run(engine_with(FakeClient(tool_reply({}, stop="max_tokens"))).complete("S", "TASK: x", {"type": "object"}))
    with pytest.raises(EngineError, match="No Anthropic API key"):
        asyncio.run(engine_with(FakeClient(), key=None).complete("S", "TASK: x", {"type": "object"}))


def test_status_checks_the_key_once_and_caches_it():
    client = FakeClient()
    engine = engine_with(client, model="claude-opus-5-5")
    assert asyncio.run(engine.status())["ready"] is True
    assert asyncio.run(engine.status())["ready"] is True
    assert client.retrieved == ["claude-opus-5-5"]  # cached: one cheap call, no tokens
    assert asyncio.run(engine_with(FakeClient(), key=None).status())["ready"] is False


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
