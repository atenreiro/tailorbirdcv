import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend


class MemoryKeyring(KeyringBackend):
    """Tests never touch the real OS keychain."""
    priority = 1

    def __init__(self):
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch):
    ring = MemoryKeyring()
    keyring.set_keyring(ring)
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    return ring


@pytest.fixture(autouse=True)
def no_update_checks(monkeypatch):
    """Tests never ask PyPI for the latest version; test_update.py swaps in its own answers."""
    async def offline(transport=None):
        raise OSError("tests are offline")
    from autocv import update
    monkeypatch.setattr(update, "fetch_latest", offline)


@pytest.fixture(autouse=True)
def no_favicon_fetches(monkeypatch):
    """Tests never contact company sites for icons; test_favicon.py drives the fetcher with fake sites."""
    async def none(job_url, sites=None, client=None):
        return None
    from autocv import favicon
    monkeypatch.setattr(favicon, "fetch", none)


def client_for(app) -> TestClient:
    """A client that behaves like the AutoCV UI: allowed host + the X-AutoCV header."""
    client = TestClient(app, base_url="http://127.0.0.1", headers={"X-AutoCV": "1"})
    client.cookies.set(app.state.cookie_name, app.state.access_key)  # like a browser opened from `autocv serve`'s link
    return client
