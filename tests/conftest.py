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
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return ring


def client_for(app) -> TestClient:
    """A client that behaves like the AutoCV UI: allowed host + the X-AutoCV header."""
    return TestClient(app, base_url="http://127.0.0.1", headers={"X-AutoCV": "1"})
