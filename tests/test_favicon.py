"""Company site icons: the right site (never a job board's logo), raster images only, fetched once in the
background, served only by TailorbirdCV, and nothing shown or fetched when Settings turns icons off. Fictional sites."""

import asyncio
import shutil
import time
from pathlib import Path

import httpx
import pytest

from tailorbirdcv import favicon, jobfetch
from tailorbirdcv.api import create_app
from tailorbirdcv.engine import FakeEngine
from tailorbirdcv.favicon import fetch as real_fetch  # conftest replaces favicon.fetch with an offline stub
from tailorbirdcv.jobfetch import FetchError
from tailorbirdcv.store import Store
from conftest import client_for

FIX = Path(__file__).parent / "fixtures"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
ICO = b"\x00\x00\x01\x00" + b"\x00" * 40
JD = "# Platform Engineer\n\n" + "We need a hands-on platform engineer to run our payment services. " * 8


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch):
    """The headless-browser retry never launches Chromium here; tests that need it pass a fake render."""
    async def unavailable(url):
        raise FetchError("no headless browser in tests")
    monkeypatch.setattr(jobfetch, "render_page", unavailable)


@pytest.fixture
def public_dns(monkeypatch):
    async def ok(url):  # no real DNS; SSRF rejection is tested in test_jobfetch/test_pinning
        if not url.startswith(("http://", "https://")):
            raise FetchError("The URL must start with http:// or https://")
    monkeypatch.setattr(jobfetch, "check_public_url", ok)


def sites(routes: dict):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        r = routes.get(str(request.url))
        return r() if callable(r) else r or httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


def get(url, routes):
    client, seen = sites(routes)
    return asyncio.run(real_fetch(url, [], client)), seen


def page(head: str) -> httpx.Response:
    return httpx.Response(200, text=f"<html><head>{head}</head><body>Example Co</body></html>",
                          headers={"content-type": "text/html"})


def test_a_declared_icon_beats_favicon_ico(public_dns):
    found, seen = get("https://careers.example.com/jobs/42", {
        "https://careers.example.com/": page('<link rel="icon" href="/static/icon-32.png" sizes="32x32">'),
        "https://careers.example.com/static/icon-32.png": httpx.Response(200, content=PNG),
        "https://careers.example.com/favicon.ico": httpx.Response(200, content=ICO)})
    assert found == (PNG, "png") and "https://careers.example.com/favicon.ico" not in seen


def test_favicon_ico_when_nothing_is_declared(public_dns):
    found, _ = get("https://example.com/careers/42", {
        "https://example.com/": page(""), "https://example.com/favicon.ico": httpx.Response(200, content=ICO)})
    assert found == (ICO, "ico")


SVG = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect width="16" height="16"/></svg>'


def test_an_svg_only_site_gets_its_svg_icon(public_dns):
    found, _ = get("https://example.com/job", {
        "https://example.com/": page('<link rel="shortcut icon" href="/assets/logo.svg" type="image/svg+xml">'),
        "https://example.com/assets/logo.svg": httpx.Response(200, content=SVG)})
    assert found == (SVG, "svg")


def test_a_raster_icon_beats_an_svg_one(public_dns):
    found, _ = get("https://example.com/job", {
        "https://example.com/": page('<link rel="icon" href="/i.svg" type="image/svg+xml"><link rel="icon" href="/i.png">'),
        "https://example.com/i.svg": httpx.Response(200, content=SVG), "https://example.com/i.png": httpx.Response(200, content=PNG)})
    assert found == (PNG, "png")


def test_non_images_are_never_kept(public_dns):
    found, _ = get("https://example.com/job", {
        "https://example.com/": page('<link rel="icon" href="https://example.com/" type="image/png">'),  # a broken tag
        "https://example.com/favicon.ico": httpx.Response(200, content=b"<html><svg></svg></html>")})
    assert found is None


def test_icons_over_200_kb_are_refused(public_dns):
    found, _ = get("https://example.com/job", {
        "https://example.com/": page(""),
        "https://example.com/favicon.ico": httpx.Response(200, content=ICO + b"\x00" * 210_000)})
    assert found is None


def test_a_job_board_uses_the_company_site_named_in_the_posting(public_dns):
    posting = page('<script type="application/ld+json">{"@type": "JobPosting", "title": "Engineer", '
                   '"hiringOrganization": {"name": "Northwind", "sameAs": ["https://www.linkedin.com/company/nw", '
                   '"https://jobs.lever.co/nw", "https://northwind.example"]}}</script>')
    found, seen = get("https://boards.greenhouse.io/northwind/jobs/123", {
        "https://boards.greenhouse.io/northwind/jobs/123": posting,
        "https://northwind.example/": page(""),
        "https://northwind.example/favicon.ico": httpx.Response(200, content=ICO)})
    assert found == (ICO, "ico")
    assert not any("greenhouse.io/favicon" in u or "linkedin" in u or "lever.co" in u for u in seen)


def test_a_job_board_without_the_company_site_gets_no_icon(public_dns):
    found, seen = get("https://jobs.lever.co/northwind/abc", {
        "https://jobs.lever.co/northwind/abc": page(""),
        "https://jobs.lever.co/favicon.ico": httpx.Response(200, content=ICO)})
    assert found is None and "https://jobs.lever.co/favicon.ico" not in seen


def test_network_trouble_means_no_icon(public_dns):
    def boom():
        raise httpx.ConnectError("down")
    found, _ = get("https://example.com/job", {"https://example.com/": boom, "https://example.com/favicon.ico": boom})
    assert found is None


def test_a_site_that_blocks_plain_requests_is_read_through_the_headless_browser(public_dns, monkeypatch):
    rendered = []

    async def render(url):
        rendered.append(url)
        return jobfetch.Rendered('<html><head><link rel="icon" href="https://static.example-cdn.net/img/favicon.ico">'
                                 '</head></html>', "", url, [])
    monkeypatch.setattr(jobfetch, "render_page", render)
    found, seen = get("https://www.example.com/careers/job/9", {
        "https://www.example.com/": httpx.Response(200, content=b""),  # bot protection: an empty page
        "https://www.example.com/favicon.ico": httpx.Response(200, content=b""),
        "https://static.example-cdn.net/img/favicon.ico": httpx.Response(200, content=ICO)})
    assert found == (ICO, "ico") and rendered == ["https://www.example.com/"]
    assert "https://static.example-cdn.net/img/favicon.ico" in seen  # fetched by TailorbirdCV's own guarded client


def test_private_addresses_are_refused():
    client, seen = sites({})
    assert asyncio.run(real_fetch("http://127.0.0.1:8000/job", [], client)) is None and seen == []


def test_json_ld_names_the_company_sites():
    html = ('<script type="application/ld+json">{"@type": "JobPosting", "title": "Engineer", "description": "'
            + "Build things. " * 40 + '", "hiringOrganization": {"name": "Northwind", "url": "https://northwind.example", '
            '"sameAs": "https://twitter.com/northwind"}}</script>')
    job = jobfetch.from_json_ld(html)
    assert job.sites == ["https://northwind.example", "https://twitter.com/northwind"]
    assert favicon.company_site("https://boards.greenhouse.io/nw/jobs/1", job.sites) == "https://northwind.example"


# ---- API: stored once, served by TailorbirdCV, and Settings can turn it all off -----------------------------------
@pytest.fixture
def env(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    shutil.copy(FIX / "profile.yaml", private / "profile.yaml")
    store = Store(private)
    calls = []

    async def fake(job_url, sites=None, client=None):
        calls.append((job_url, list(sites or [])))
        return (PNG, "png")
    monkeypatch.setattr(favicon, "fetch", fake)
    client = client_for(create_app(store, FakeEngine({})))
    return client, store, calls


def wait_for(cond, seconds=3.0):
    deadline = time.monotonic() + seconds
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.05)
    return cond()


def new_app(client, url):
    return client.post("/api/applications", json={"jd": JD, "url": url, "company": "Northwind", "role": "Engineer"}).json()["id"]


def test_created_from_a_link_the_icon_is_fetched_once_stored_and_served(env):
    client, store, calls = env
    with client:  # keeps the event loop running for the background fetch
        app_id = new_app(client, "https://northwind.example/careers/1")
        assert wait_for(lambda: store.meta(app_id).get("favicon") == "favicon.png")
        r = client.get(f"/api/applications/{app_id}/favicon")
        assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
        assert r.headers["x-content-type-options"] == "nosniff" and "default-src 'none'" in r.headers["content-security-policy"]
        client.get("/api/applications")
        time.sleep(0.2)
    assert calls == [("https://northwind.example/careers/1", [])]  # the list doesn't fetch it again
    assert "favicon.png" not in store.files(app_id)  # never a downloadable, built or sent file


def test_an_svg_icon_is_served_with_scripts_blocked(env, monkeypatch):
    client, store, calls = env

    async def svg(job_url, sites=None, client=None):
        return (SVG, "svg")
    monkeypatch.setattr(favicon, "fetch", svg)
    with client:
        app_id = new_app(client, "https://northwind.example/careers/7")
        assert wait_for(lambda: store.meta(app_id).get("favicon") == "favicon.svg")
        r = client.get(f"/api/applications/{app_id}/favicon")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert "default-src 'none'" in r.headers["content-security-policy"] and "sandbox" in r.headers["content-security-policy"]


def test_saving_an_icon_never_changes_the_boards_order(tmp_path):
    store = Store(tmp_path)
    app_id = store.create_app("Northwind", "Engineer", JD, "https://northwind.example/careers/8")
    before = store.meta(app_id)["updated"]
    time.sleep(1.1)  # "updated" has one-second resolution
    store.save_favicon(app_id, (PNG, "png"))
    meta = store.meta(app_id)
    assert meta["favicon"] == "favicon.png" and meta["updated"] == before


def test_no_icon_found_is_recorded_so_it_isnt_fetched_again(env, monkeypatch):
    client, store, calls = env

    async def none(job_url, sites=None, client=None):
        calls.append(job_url)
        return None
    monkeypatch.setattr(favicon, "fetch", none)
    with client:
        app_id = new_app(client, "https://northwind.example/careers/2")
        assert wait_for(lambda: store.meta(app_id).get("favicon") == "")
        client.get("/api/applications")
        time.sleep(0.2)
    assert len(calls) == 1 and client.get(f"/api/applications/{app_id}/favicon").status_code == 404


def test_older_applications_get_their_icon_from_the_list(env):
    client, store, calls = env
    app_id = store.create_app("Northwind", "Engineer", JD, "https://northwind.example/careers/3")  # no favicon key
    with client:
        rows = client.get("/api/applications").json()
        assert "favicon" not in rows[0]
        assert wait_for(lambda: store.meta(app_id).get("favicon") == "favicon.png")
        assert client.get("/api/applications").json()[0]["favicon"] == "favicon.png"
    assert len(calls) == 1


def test_pasted_jobs_never_fetch(env):
    client, store, calls = env
    with client:
        client.post("/api/applications", json={"jd": JD, "company": "Northwind", "role": "Engineer"})
        client.get("/api/applications")
        time.sleep(0.2)
    assert calls == []


def test_icons_off_in_settings_means_nothing_is_fetched(env):
    client, store, calls = env
    assert client.get("/api/settings").json()["company_icons"] is True  # on by default
    client.put("/api/settings", json={"company_icons": False})
    with client:
        new_app(client, "https://northwind.example/careers/4")
        store.create_app("Contoso", "Analyst", JD, "https://contoso.example/jobs/5")
        client.get("/api/applications")
        time.sleep(0.3)
    assert calls == []
