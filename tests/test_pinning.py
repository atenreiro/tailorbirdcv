"""DNS-rebinding protection: the address that is validated is the address that is used."""

import asyncio
import http.server
import threading

import pytest

from tailorbirdcv import jobfetch
from tailorbirdcv.jobfetch import BlockedURL, check_public_url, pinned_client, safe_get


class Recorder(http.server.BaseHTTPRequestHandler):
    hits: list = []

    def do_GET(self):
        Recorder.hits.append((self.path, self.headers.get("Host")))
        body = b"<html><body>" + b"SECRET-LAN-PAGE " * 40 + b"</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    Recorder.hits = []
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Recorder)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_port
    httpd.shutdown()


def test_rebinding_between_check_and_connect_is_blocked(server, monkeypatch):
    answers = iter([["93.184.216.34"], ["127.0.0.1"], ["127.0.0.1"]])  # public for the check, then rebinds
    monkeypatch.setattr(jobfetch, "_resolve", lambda host, port: next(answers))

    async def go():
        async with pinned_client() as client:
            return await safe_get(client, f"http://rebind.test:{server}/secret")

    with pytest.raises(BlockedURL):
        asyncio.run(go())
    assert Recorder.hits == []  # the LAN server was never contacted


def test_connects_to_the_validated_address_with_the_original_host(server, monkeypatch):
    monkeypatch.setattr(jobfetch, "_resolve", lambda host, port: ["127.0.0.1"])
    monkeypatch.setattr(jobfetch, "check_addr", lambda ip, port=None: None)  # treat it as public

    async def go():
        async with pinned_client() as client:
            return await safe_get(client, f"http://pinned.test:{server}/job")

    assert "SECRET-LAN-PAGE" in asyncio.run(go())
    assert Recorder.hits == [("/job", f"pinned.test:{server}")]  # Host header kept, IP pinned


def test_any_private_answer_blocks_even_if_one_is_public(server, monkeypatch):
    monkeypatch.setattr(jobfetch, "_resolve", lambda host, port: ["93.184.216.34", "127.0.0.1"])
    with pytest.raises(BlockedURL):
        asyncio.run(check_public_url(f"http://mixed.test:{server}/"))


@pytest.mark.parametrize("url", ["http://127.0.0.1:99999/x", "http://example.com:abc/"])
def test_malformed_port_is_a_clean_refusal(url):
    with pytest.raises(BlockedURL):
        asyncio.run(check_public_url(url))


def test_ipv4_mapped_ipv6_loopback_is_blocked():
    with pytest.raises(BlockedURL):
        jobfetch.check_addr("::ffff:127.0.0.1")
