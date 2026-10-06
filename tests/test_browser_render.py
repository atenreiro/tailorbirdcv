"""Real headless-Chromium test against a local server: JavaScript content renders,
while internal requests (fetch, navigation redirects) are blocked by the SSRF guard.
Skipped if Playwright's Chromium isn't installed."""

import asyncio
import http.server
import os
import threading
from pathlib import Path

import pytest

from tailorbirdcv import jobfetch
from tailorbirdcv.jobfetch import BlockedURL, FetchError, render_page

pytest.importorskip("playwright")
_CACHES = [Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])] if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") else [
    Path.home() / "Library/Caches/ms-playwright", Path.home() / ".cache/ms-playwright",
    Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"]
if not any(list(c.glob("chromium*")) for c in _CACHES):
    pytest.skip("Playwright Chromium not installed", allow_module_level=True)

LAN_PORT = {"port": 0}

PAGE = b"""<!doctype html><html><body><div id="root"></div><script>
  document.getElementById('root').innerText = 'Head of Detection. ' + 'Own detection engineering. '.repeat(20);
  fetch('/internal/secret').then(r => r.text()).then(t => document.body.append(t)).catch(() => {});
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/job":
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(PAGE)
        elif self.path == "/rebind":
            # the page's JS reads a hostname that passed the URL check but resolves to another LAN service
            html = ("<html><body><div id=out>Waiting</div><script>document.getElementById('out').innerText = "
                    "'Own detection engineering. '.repeat(20);"
                    f"fetch('http://rebind.test:{LAN_PORT['port']}/').then(r => r.text())"
                    ".then(t => document.body.append(t)).catch(() => {});</script></body></html>").encode()
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(html)
        elif self.path == "/hop-ok":
            self.send_response(301); self.send_header("Location", "/job"); self.end_headers()
        elif self.path == "/hop":
            self.send_response(302); self.send_header("Location", "/internal/landing"); self.end_headers()
        elif self.path.startswith("/internal"):
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(b"<html><body>TOP-SECRET-INTERNAL " + b"x" * 400 + b"</body></html>")
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def server(monkeypatch):
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    async def guard(url):  # URL-level: treat this test server as "public", except /internal
        if "/internal" in url:
            raise BlockedURL("private")
        if not url.startswith((f"http://127.0.0.1:{httpd.server_port}/", "http://rebind.test:")):
            raise BlockedURL("not the test server")

    def addr(ip, port=None):  # connection-level: only the test server's port counts as "public"
        if port != httpd.server_port:
            raise BlockedURL("private")

    monkeypatch.setattr(jobfetch, "check_public_url", guard)
    monkeypatch.setattr(jobfetch, "check_addr", addr)
    monkeypatch.setattr(jobfetch, "_resolve", lambda host, port: ["127.0.0.1"])
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_renders_javascript_and_blocks_internal_fetch(server):
    r = asyncio.run(render_page(f"{server}/job"))
    assert "Own detection engineering." in r.text
    assert "TOP-SECRET" not in r.text
    assert any("/internal/secret" in u for u in r.blocked)


def test_navigation_redirect_to_internal_is_blocked(server):
    try:
        r = asyncio.run(render_page(f"{server}/hop"))
    except FetchError:
        return  # navigation aborted outright — also fine
    assert "TOP-SECRET" not in r.text
    assert any("/internal/landing" in u for u in r.blocked)


def test_public_redirect_is_followed(server):
    r = asyncio.run(render_page(f"{server}/hop-ok"))
    assert "Own detection engineering." in r.text


class LanService(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
        self.wfile.write(b"ROUTER-ADMIN-SECRET")

    def log_message(self, *args):
        pass


def test_page_javascript_cannot_reach_a_rebound_lan_service(server):
    lan = http.server.HTTPServer(("127.0.0.1", 0), LanService)
    threading.Thread(target=lan.serve_forever, daemon=True).start()
    LAN_PORT["port"] = lan.server_port
    try:
        r = asyncio.run(render_page(f"{server}/rebind"))
    finally:
        lan.shutdown()
    assert "Own detection engineering." in r.text
    assert "ROUTER-ADMIN-SECRET" not in r.text
    assert any("rebind.test" in u for u in r.blocked)
