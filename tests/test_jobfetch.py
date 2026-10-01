"""Job-description fetching: ATS routing, formatting, JSON-LD, SSRF checks (offline)."""

import asyncio
import json

import httpx
import pytest

from autocv import jobfetch
from autocv.jobfetch import (FetchError, ashby_ref, fetch_job, format_lever, from_json_ld, greenhouse_ref,
                             html_to_text, lever_ref)

JOB_ID = "01e7966a-9873-461c-ad17-771fd7c0be9a"

LEVER = {
    "text": "Platform Engineer",
    "categories": {"location": "Asia", "commitment": "Full-time", "department": "Security", "team": "AppSec"},
    "description": "<div>Example Co protects millions of users.</div>",
    "lists": [
        {"text": "Responsibilities", "content": "<li>Own detection engineering</li><li><p>Lead a team of 5</p></li>"},
        {"text": "Requirements", "content": "<li>10+ years in security</li>"},
    ],
    "additional": "<div>Equal opportunity employer.</div>",
    "hostedUrl": f"https://jobs.lever.co/example/{JOB_ID}",
}


def test_lever_routing():
    assert lever_ref(f"https://www.binance.com/en/careers/job?id={JOB_ID}&name=X") == ("binance", JOB_ID)
    assert lever_ref(f"https://jobs.lever.co/example/{JOB_ID}/apply") == ("example", JOB_ID)
    assert lever_ref("https://www.binance.com/en/careers/job?id=not-a-uuid") is None
    assert lever_ref(f"https://evilbinance.com/careers/job?id={JOB_ID}") is None
    assert lever_ref("https://example.com/careers") is None


def test_greenhouse_and_ashby_routing():
    assert greenhouse_ref("https://boards.greenhouse.io/acme/jobs/12345") == ("acme", "12345")
    assert greenhouse_ref("https://job-boards.greenhouse.io/acme/jobs/678?gh_src=x") == ("acme", "678")
    assert ashby_ref(f"https://jobs.ashbyhq.com/acme/{JOB_ID}") == ("acme", JOB_ID)
    assert greenhouse_ref("https://acme.com/jobs/1") is None


def test_format_lever():
    job = format_lever(LEVER, "example")
    assert (job.company, job.role, job.source) == ("Example", "Platform Engineer", "lever")
    assert "## Responsibilities\n- Own detection engineering\n- Lead a team of 5" in job.text
    assert "Location: Asia" in job.text and "Team: Security / AppSec" in job.text


def test_format_lever_skips_lists_already_in_description():
    data = {**LEVER, "description": LEVER["description"] + "<div><b>Responsibilities</b></div><ul><li>Own detection engineering</li></ul>"}
    job = format_lever(data, "example")
    assert job.text.count("Own detection engineering") == 1
    assert "## Requirements" in job.text  # not in the description → still added


def test_html_to_text_bullets_and_spacing():
    assert html_to_text("<p>Intro</p><ul><li>One <b>bold</b></li><li><p>Two</p></li></ul>") == "Intro\n\n- One bold\n- Two"


def test_json_ld_jobposting():
    body = "We need a detection lead. " * 20
    page = f"""<html><head><script type="application/ld+json">{json.dumps({
        "@context": "https://schema.org", "@graph": [{"@type": "Organization", "name": "x"}, {
            "@type": "JobPosting", "title": "Detection Lead", "description": f"<p>{body}</p>",
            "hiringOrganization": {"@type": "Organization", "name": "Acme"},
            "jobLocation": {"@type": "Place", "address": {"addressLocality": "Singapore"}}}]})}</script></head>
            <body><div id="root"></div></body></html>"""
    job = from_json_ld(page)
    assert job and (job.company, job.role, job.source) == ("Acme", "Detection Lead", "json-ld")
    assert "Location: Singapore" in job.text


def _client(routes: dict[str, httpx.Response]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def public_dns(monkeypatch):
    async def ok(url):  # skip real DNS in tests; SSRF rejection is tested separately
        if not url.startswith(("http://", "https://")):
            raise FetchError("The URL must start with http:// or https://")
    monkeypatch.setattr(jobfetch, "check_public_url", ok)


def test_fetch_binance_url_uses_lever_api(public_dns):
    api = f"https://api.lever.co/v0/postings/binance/{JOB_ID}"
    client = _client({api: httpx.Response(200, json=LEVER)})
    job = asyncio.run(fetch_job(f"https://www.binance.com/en/careers/job?id={JOB_ID}", client))
    assert job.source == "lever" and job.company == "Binance"


def test_fetch_follows_redirects_and_rechecks_each_hop(monkeypatch):
    checked = []

    async def check(url):
        checked.append(url)
        if "169.254" in url:
            raise FetchError("That URL points to a private or local network address, so AutoCV won't fetch it.")
    monkeypatch.setattr(jobfetch, "check_public_url", check)
    client = _client({"https://jobs.example.com/1": httpx.Response(302, headers={"location": "http://169.254.169.254/"})})
    with pytest.raises(FetchError, match="private or local"):
        asyncio.run(fetch_job("https://jobs.example.com/1", client))
    assert checked == ["https://jobs.example.com/1", "http://169.254.169.254/"]


def test_fetch_js_only_page_explains(public_dns):
    client = _client({"https://jobs.example.com/2": httpx.Response(200, text="<html><body><div id=root></div></body></html>")})
    with pytest.raises(FetchError, match="JavaScript"):
        asyncio.run(fetch_job("https://jobs.example.com/2", client))


def test_check_public_url_blocks_private_addresses():
    for url in ("http://127.0.0.1/", "http://10.1.2.3/", "http://[::1]/", "http://169.254.169.254/", "file:///etc/passwd"):
        with pytest.raises(FetchError):
            asyncio.run(jobfetch.check_public_url(url))
