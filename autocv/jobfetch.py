"""Fetch a job description from a URL.

Many career sites render the job with JavaScript, so their HTML has no text. Before
falling back to visible text, try (in order):
  1. Known applicant-tracking systems with public posting APIs: Lever (incl. Binance
     careers, which is backed by Lever), Greenhouse, Ashby
  2. schema.org JobPosting JSON-LD embedded in the page (used for Google Jobs)
  3. The page's visible text

Every request goes through `safe_get`, which only allows http(s) to public addresses
and re-checks each redirect hop (SSRF guard).
"""

from __future__ import annotations

import asyncio
import html as htmllib
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

MAX_REDIRECTS = 5
MAX_BYTES = 3_000_000
MIN_TEXT = 300
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class FetchError(Exception):
    """A user-facing reason the URL could not be turned into a job description."""


@dataclass
class Job:
    text: str
    company: str = ""
    role: str = ""
    source: str = "page"  # lever | greenhouse | ashby | json-ld | page


# --------------------------------------------------------------------------- safe http


async def check_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FetchError("The URL must start with http:// or https://")
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or None)
    except socket.gaierror:
        raise FetchError(f"Could not resolve {parsed.hostname}.")
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise FetchError("That URL points to a private or local network address, so AutoCV won't fetch it.")


async def safe_get(client: httpx.AsyncClient, url: str) -> str:
    """GET with per-hop SSRF checks and a size cap."""
    for _ in range(MAX_REDIRECTS + 1):
        await check_public_url(url)
        async with client.stream("GET", url) as resp:
            if resp.is_redirect:
                url = str(resp.url.join(resp.headers.get("location", "")))
                continue
            if resp.status_code == 404:
                raise FetchError("The job posting was not found (404). It may have been closed.")
            resp.raise_for_status()
            body = b""
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise FetchError("That page is too large.")
            return body.decode(resp.encoding or "utf-8", errors="replace")
    raise FetchError("Too many redirects.")


# --------------------------------------------------------------------------- formatting


def html_to_text(fragment: str) -> str:
    soup = BeautifulSoup(fragment or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    # One line per bullet ("<li><p>text</p></li>" would otherwise split across lines).
    for li in soup.find_all("li"):
        if li.parent is not None:  # skip items already folded into an outer <li>
            li.replace_with(soup.new_string("\n- " + " ".join(li.get_text(" ").split()) + "\n"))
    out: list[str] = []
    for raw in soup.get_text("\n").splitlines():
        line = " ".join(raw.split())
        if line:
            if line.startswith("- ") and len(out) >= 2 and out[-1] == "" and out[-2].startswith("- "):
                out.pop()  # keep a bullet list tight
            out.append(line)
        elif out and out[-1]:
            out.append("")
    return "\n".join(out).strip()


def _doc(title: str, company: str, facts: list[tuple[str, str]], sections: list[tuple[str, str]]) -> str:
    parts = [f"# {title}" + (f" — {company}" if company else "")]
    meta = [f"{k}: {v}" for k, v in facts if v]
    if meta:
        parts.append("\n".join(meta))
    for heading, body in sections:
        body = body.strip()
        if body:
            parts.append(f"## {heading}\n{body}" if heading else body)
    return "\n\n".join(parts) + "\n"


def _company_from_slug(slug: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_]", slug) if w)


# --------------------------------------------------------------------------- lever


def lever_ref(url: str) -> tuple[str, str] | None:
    """(company slug, posting id) for Lever-backed URLs."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host in ("jobs.lever.co", "jobs.eu.lever.co"):
        m = re.match(rf"^/([^/]+)/({UUID})", p.path, re.I)
        return (m.group(1), m.group(2)) if m else None
    if (host == "binance.com" or host.endswith(".binance.com")) and "/careers/job" in p.path:
        job_id = parse_qs(p.query).get("id", [""])[0]
        return ("binance", job_id) if re.fullmatch(UUID, job_id, re.I) else None
    return None


def format_lever(data: dict, slug: str) -> Job:
    cats = data.get("categories") or {}
    company = _company_from_slug(slug)
    description = html_to_text(data.get("description") or "") or data.get("descriptionPlain", "")
    sections = [("", description)]
    for item in data.get("lists") or []:
        heading = item.get("text", "")
        # Some companies paste the whole posting into `description` as well; don't repeat it.
        if heading and re.search(rf"^{re.escape(heading)}\s*:?\s*$", description, re.M | re.I):
            continue
        sections.append((heading, html_to_text(item.get("content", ""))))
    sections.append(("", html_to_text(data.get("additional") or "") or data.get("additionalPlain", "")))
    locations = ", ".join(cats.get("allLocations") or []) or cats.get("location", "")
    facts = [("Location", locations), ("Commitment", cats.get("commitment", "")),
             ("Team", " / ".join(x for x in (cats.get("department"), cats.get("team")) if x)),
             ("Workplace", data.get("workplaceType", "")), ("URL", data.get("hostedUrl", ""))]
    title = data.get("text", "")
    return Job(_doc(title, company, facts, sections), company, title, "lever")


# --------------------------------------------------------------------------- greenhouse


def greenhouse_ref(url: str) -> tuple[str, str] | None:
    """(board, job id) for boards.greenhouse.io / job-boards.greenhouse.io URLs."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host == "greenhouse.io" or host.endswith(".greenhouse.io"):
        m = re.match(r"^/([^/]+)/jobs/(\d+)", p.path)
        if m:
            return m.group(1), m.group(2)
        q = parse_qs(p.query)
        if q.get("for") and q.get("token"):
            return q["for"][0], q["token"][0]
    return None


def format_greenhouse(data: dict, board: str) -> Job:
    company = data.get("company_name") or _company_from_slug(board)
    content = html_to_text(htmllib.unescape(data.get("content", "")))
    facts = [("Location", (data.get("location") or {}).get("name", "")), ("URL", data.get("absolute_url", ""))]
    title = data.get("title", "")
    return Job(_doc(title, company, facts, [("", content)]), company, title, "greenhouse")


# --------------------------------------------------------------------------- ashby


def ashby_ref(url: str) -> tuple[str, str] | None:
    p = urlparse(url)
    if (p.hostname or "").lower() == "jobs.ashbyhq.com":
        m = re.match(rf"^/([^/]+)/({UUID})", p.path, re.I)
        return (m.group(1), m.group(2)) if m else None
    return None


def format_ashby(board: dict, org: str, job_id: str) -> Job | None:
    job = next((j for j in board.get("jobs", []) if j.get("id") == job_id), None)
    if not job:
        return None
    company = _company_from_slug(org)
    body = html_to_text(job.get("descriptionHtml") or "") or job.get("descriptionPlain", "")
    facts = [("Location", job.get("location", "")), ("Employment", job.get("employmentType", "")),
             ("Team", job.get("department") or job.get("team", "")), ("URL", job.get("jobUrl", ""))]
    title = job.get("title", "")
    return Job(_doc(title, company, facts, [("", body)]), company, title, "ashby")


# --------------------------------------------------------------------------- json-ld + page


def _jobposting_nodes(data) -> list[dict]:
    found = []
    if isinstance(data, list):
        for item in data:
            found += _jobposting_nodes(item)
    elif isinstance(data, dict):
        kind = data.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "JobPosting" in kinds:
            found.append(data)
        for key in ("@graph", "mainEntity"):
            if key in data:
                found += _jobposting_nodes(data[key])
    return found


def from_json_ld(page: str) -> Job | None:
    soup = BeautifulSoup(page, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _jobposting_nodes(data):
            org = node.get("hiringOrganization") or {}
            company = org.get("name", "") if isinstance(org, dict) else str(org)
            locs = node.get("jobLocation") or []
            locs = locs if isinstance(locs, list) else [locs]
            where = ", ".join(filter(None, (
                (loc.get("address") or {}).get("addressLocality", "") for loc in locs if isinstance(loc, dict))))
            body = html_to_text(htmllib.unescape(node.get("description", "")))
            if len(body) >= MIN_TEXT:
                title = node.get("title", "")
                facts = [("Location", where), ("Employment", str(node.get("employmentType", "") or ""))]
                return Job(_doc(title, company, facts, [("", body)]), company, title, "json-ld")
    return None


def from_page(page: str) -> Job | None:
    soup = BeautifulSoup(page, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg"]):
        tag.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    return Job(text) if len(text) >= MIN_TEXT else None


# --------------------------------------------------------------------------- entry point


async def fetch_job(url: str, client: httpx.AsyncClient | None = None) -> Job:
    own = client is None
    client = client or httpx.AsyncClient(follow_redirects=False, timeout=20,
                                         headers={"User-Agent": "Mozilla/5.0 AutoCV"})
    try:
        if ref := lever_ref(url):
            slug, job_id = ref
            return format_lever(json.loads(await safe_get(client, f"https://api.lever.co/v0/postings/{slug}/{job_id}")), slug)
        if ref := greenhouse_ref(url):
            board, job_id = ref
            api = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
            return format_greenhouse(json.loads(await safe_get(client, api)), board)
        if ref := ashby_ref(url):
            org, job_id = ref
            board = json.loads(await safe_get(client, f"https://api.ashbyhq.com/posting-api/job-board/{org}"))
            if job := format_ashby(board, org, job_id):
                return job
        page = await safe_get(client, url)
        job = from_json_ld(page) or from_page(page)
        if not job:
            raise FetchError("The page returned too little text (it likely needs JavaScript or a login).")
        return job
    except httpx.HTTPError as e:
        raise FetchError(f"Could not fetch the URL ({e}).") from e
    except json.JSONDecodeError as e:
        raise FetchError("The job board returned an unexpected response.") from e
    finally:
        if own:
            await client.aclose()
