from fastapi.testclient import TestClient


def client_for(app) -> TestClient:
    """A client that behaves like the AutoCV UI: allowed host + the X-AutoCV header."""
    return TestClient(app, base_url="http://127.0.0.1", headers={"X-AutoCV": "1"})
