"""Real headless-Chromium test against a local server: JavaScript content renders,
while internal requests (fetch, navigation redirects) are blocked by the SSRF guard.
Skipped if Playwright's Chromium isn't installed."""

import asyncio
import http.server
import threading
from pathlib import Path

import pytest

from autocv import jobfetch
from autocv.jobfetch import BlockedURL, FetchError, render_page

pytest.importorskip("playwright")
if not list((Path.home() / "Library/Caches/ms-playwright").glob("chromium*")) and \
        not list((Path.home() / ".cache/ms-playwright").glob("chromium*")):
    pytest.skip("Playwright Chromium not installed", allow_module_level=True)

PAGE = b"""<!doctype html><html><body><div id="root"></div><script>
  document.getElementById('root').innerText = 'Head of Detection. ' + 'Own detection engineering. '.repeat(20);
  fetch('/internal/secret').then(r => r.text()).then(t => document.body.append(t)).catch(() => {});
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/job":
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(PAGE)
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

    async def guard(url):  # treat this test server as "public", except /internal
        if "/internal" in url:
            raise BlockedURL("private")
        if not url.startswith(f"http://127.0.0.1:{httpd.server_port}/"):
            raise BlockedURL("not the test server")
    monkeypatch.setattr(jobfetch, "check_public_url", guard)
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
