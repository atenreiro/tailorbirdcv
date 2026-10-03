"""Fetch a job description from a URL.

Many career sites render the job with JavaScript, so their HTML has no text. Before
falling back to visible text, try (in order):
  1. Known applicant-tracking systems with public posting APIs: Lever (incl. Binance
     careers, which is backed by Lever), Greenhouse, Ashby
  2. schema.org JobPosting JSON-LD embedded in the page (used for Google Jobs)
  3. The page's visible text
  4. Fallback: render the page in headless Chromium (Playwright) and read the result
     — for JavaScript-only career sites (Workday, SuccessFactors, custom apps…)

SSRF guard: every request — including each redirect hop, and every request the
headless browser makes (scripts, XHR/fetch, redirects) — must target a public
address. WebSockets and service workers are disabled in the browser.
Set AUTOCV_BROWSER_FALLBACK=0 to disable step 4.
"""

from __future__ import annotations

import asyncio
import html as htmllib
import ipaddress
import json
import os
import re
import socket
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse

import httpcore
import httpx
from bs4 import BeautifulSoup

MAX_REDIRECTS = 5
MAX_BYTES = 3_000_000
MIN_TEXT = 300
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class FetchError(Exception):
    """A user-facing reason the URL could not be turned into a job description."""


class BlockedURL(FetchError):
    """The URL targets a non-public address or scheme — never retried another way."""


class NotFound(FetchError):
    """The posting does not exist (404) — rendering it won't help."""


@dataclass
class Job:
    text: str
    company: str = ""
    role: str = ""
    source: str = "page"  # lever | greenhouse | ashby | json-ld | page


# --------------------------------------------------------------------------- safe http


def _resolve(host: str, port: int | None) -> list[str]:
    """All addresses `host` resolves to (patched in tests)."""
    return [info[4][0].split("%")[0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


_NAT64 = ipaddress.ip_network("64:ff9b::/96")         # well-known NAT64 prefix: IPv4 in the last 32 bits
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")  # local-use NAT64 (RFC 8215): never a public target
_COMPAT = ipaddress.ip_network("::/96")                # deprecated IPv4-compatible ::a.b.c.d


def _embedded_ipv4(addr: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """IPv4 addresses an IPv6 address can carry to the network (translation/tunnel formats)."""
    out = []
    if addr.ipv4_mapped:
        out.append(addr.ipv4_mapped)
    if addr in _NAT64 or addr in _COMPAT:
        out.append(ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF))
    if addr.sixtofour:
        out.append(addr.sixtofour)
    if addr.teredo:
        out.extend(addr.teredo)  # (server, client)
    return out


def check_addr(ip: str, port: int | None = None) -> None:
    """Raise BlockedURL unless `ip` is a public unicast address, including any IPv4 address
    embedded in an IPv6 one (mapped, NAT64, IPv4-compatible, 6to4, Teredo). (`port` is for tests.)"""
    blocked = BlockedURL("That URL points to a private or local network address, so AutoCV won't fetch it.")
    addr = ipaddress.ip_address(ip)
    candidates: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = [addr]
    if isinstance(addr, ipaddress.IPv6Address):
        if addr in _NAT64_LOCAL:
            raise blocked
        embedded = _embedded_ipv4(addr)
        # A translated/tunnelled address is judged by the IPv4 address it reaches.
        candidates = embedded or [addr]
    for a in candidates:
        if not a.is_global or a.is_multicast or a.is_unspecified or a.is_loopback or a.is_link_local \
                or a.is_reserved or a.is_private:
            raise blocked


async def check_public_url(url: str) -> None:
    """Fast pre-check of scheme and address. The binding guarantee is PinnedBackend,
    which re-validates the exact address every connection uses."""
    parsed = urlparse(url)
    try:
        host, port = parsed.hostname, parsed.port
    except ValueError:
        raise BlockedURL("That URL isn't valid (bad port).")
    if parsed.scheme not in ("http", "https") or not host:
        raise BlockedURL("The URL must start with http:// or https://")
    try:
        addrs = await asyncio.to_thread(_resolve, host, port)
    except socket.gaierror:
        raise FetchError(f"Could not resolve {host}.")
    for ip in addrs:
        check_addr(ip, port)


class PinnedBackend(httpcore.AsyncNetworkBackend):
    """Resolve once, validate every address, connect to the validated one.

    Closes the DNS-rebinding race where a hostname resolves to a public address for the
    check and to 127.0.0.1 / a LAN address for the actual connection. TLS still verifies
    the certificate against the real hostname, and the Host header is unchanged."""

    def __init__(self, inner: httpcore.AsyncNetworkBackend | None = None):
        self.inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            addrs = await asyncio.to_thread(_resolve, host, port)
        except socket.gaierror as e:
            raise httpcore.ConnectError(f"Could not resolve {host}") from e
        if not addrs:
            raise httpcore.ConnectError(f"Could not resolve {host}")
        for ip in addrs:
            check_addr(ip, port)  # every answer must be public, not just the one we use
        return await self.inner.connect_tcp(addrs[0], port, timeout=timeout, local_address=local_address,
                                            socket_options=socket_options)

    async def connect_unix_socket(self, *args, **kwargs):
        raise BlockedURL("Unix sockets are not allowed.")

    async def sleep(self, seconds: float) -> None:
        await self.inner.sleep(seconds)


def pinned_client(timeout: float = 20) -> httpx.AsyncClient:
    """An httpx client whose every connection goes through PinnedBackend. No proxies
    (a proxy would resolve names itself), no automatic redirects."""
    transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0)
    pool = transport._pool  # httpx has no public hook for the network backend
    assert hasattr(pool, "_network_backend"), "httpx internals changed: PinnedBackend can't be installed"
    pool._network_backend = PinnedBackend()
    return httpx.AsyncClient(transport=transport, follow_redirects=False, timeout=timeout, trust_env=False,
                             headers={"User-Agent": "Mozilla/5.0 AutoCV"})


async def safe_get(client: httpx.AsyncClient, url: str) -> str:
    """GET with per-hop SSRF checks and a size cap."""
    for _ in range(MAX_REDIRECTS + 1):
        await check_public_url(url)
        async with client.stream("GET", url) as resp:  # connection re-validated by PinnedBackend
            if resp.is_redirect:
                url = str(resp.url.join(resp.headers.get("location", "")))
                continue
            if resp.status_code == 404:
                raise NotFound("The job posting was not found (404). It may have been closed.")
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
    if len(text) < MIN_TEXT or (len(text) < 1500 and re.search(r"enable javascript|javascript (is )?required", text, re.I)):
        return None
    return Job(text)


# --------------------------------------------------------------------------- headless browser


BROWSER_FALLBACK = os.environ.get("AUTOCV_BROWSER_FALLBACK", "1") != "0"
RENDER_TIMEOUT_MS = 30_000
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
_VISIBLE_TEXT_JS = """() => {
  document.querySelectorAll('nav, header, footer, script, style, noscript, svg, [aria-hidden="true"], '
    + '[id*="cookie" i], [class*="cookie" i]').forEach(e => e.remove());
  return document.body ? document.body.innerText : '';
}"""


class TooLarge(FetchError):
    """A response over MAX_BYTES."""


async def _capped_request(client: httpx.AsyncClient, method: str, url: str, headers: dict,
                          body: bytes | None) -> tuple[httpx.Response, bytes]:
    """Perform a request for the headless browser, streaming the body and giving up past
    MAX_BYTES (a redirect's body is never read)."""
    request = client.build_request(method, url, headers=headers, content=body)
    resp = await client.send(request, stream=True)
    try:
        if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
            return resp, b""
        declared = resp.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BYTES:
            raise TooLarge("That page is too large.")
        chunks, size = [], 0
        async for chunk in resp.aiter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise TooLarge("That page is too large.")
            chunks.append(chunk)
        return resp, b"".join(chunks)
    finally:
        await resp.aclose()


@dataclass
class Rendered:
    html: str
    text: str
    url: str
    blocked: list[str]


async def render_page(url: str) -> Rendered:
    """Load `url` in headless Chromium with every request SSRF-checked."""
    try:
        from playwright.async_api import Error as PWError
        from playwright.async_api import async_playwright
    except ImportError:
        raise FetchError("The headless-browser fallback isn't installed (run `uv sync`).")

    await check_public_url(url)
    blocked: list[str] = []
    client = pinned_client(timeout=15)
    hop_by_hop = {"host", "content-length", "accept-encoding", "connection", "transfer-encoding", "keep-alive"}
    drop_response = {"content-encoding", "content-length", "transfer-encoding", "connection"}

    async def guard(route):
        """Every browser request is performed by the pinned client (never by Chromium's own
        network stack), so neither redirects nor DNS rebinding can reach a private address."""
        request = route.request
        scheme = urlparse(request.url).scheme
        if scheme in ("data", "blob"):
            return await route.continue_()
        if request.resource_type in ("image", "media", "font"):
            return await route.abort()
        headers = {k: v for k, v in (await request.all_headers()).items()
                   if k.lower() not in hop_by_hop and not k.startswith(":")}
        target, method, body = request.url, request.method, request.post_data_buffer
        for _ in range(MAX_REDIRECTS + 1):
            try:
                await check_public_url(target)
                resp, content = await _capped_request(client, method, target, headers, body)
            except TooLarge:
                return await route.abort()
            except FetchError:
                blocked.append(target)
                return await route.abort("blockedbyclient")
            except httpx.HTTPError:
                return await route.abort()
            location = resp.headers.get("location")
            if resp.status_code in (301, 302, 303, 307, 308) and location:
                target = urljoin(target, location)
                if resp.status_code == 303 or (resp.status_code in (301, 302) and method == "POST"):
                    method, body = "GET", None
                continue
            out_headers: dict[str, str] = {}
            for k, v in resp.headers.multi_items():
                if k.lower() in drop_response:
                    continue
                out_headers[k] = f"{out_headers[k]}\n{v}" if k in out_headers and k.lower() == "set-cookie" else v
            return await route.fulfill(status=resp.status_code, headers=out_headers, body=content)
        blocked.append(target)
        return await route.abort("blockedbyclient")

    async def no_websockets(ws):
        await ws.close()

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except PWError:
            raise FetchError("The headless browser isn't installed — run `uv run playwright install chromium`.")
        try:
            context = await browser.new_context(user_agent=BROWSER_UA, service_workers="block", locale="en-US")
            await context.route("**/*", guard)
            await context.route_web_socket("**/*", no_websockets)
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=RENDER_TIMEOUT_MS)
            except PWError as e:
                raise FetchError(f"The headless browser could not load the page ({str(e).splitlines()[0][:120]}).")
            for wait in (page.wait_for_load_state("networkidle", timeout=8_000),
                         page.wait_for_function(f"document.body && document.body.innerText.length > {MIN_TEXT}",
                                                timeout=5_000)):
                try:
                    await wait
                except PWError:
                    pass  # best effort: some pages never go idle
            html = await page.content()
            text = await page.evaluate(_VISIBLE_TEXT_JS)
            return Rendered(html, text, page.url, blocked)
        finally:
            await browser.close()
            await client.aclose()


def from_rendered(r: Rendered) -> Job | None:
    if job := from_json_ld(r.html):
        job.source = "browser+json-ld"
        return job
    lines = [" ".join(line.split()) for line in r.text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return Job(text, source="browser") if len(text) >= MIN_TEXT else None


# --------------------------------------------------------------------------- entry point


async def fetch_job(url: str, client: httpx.AsyncClient | None = None) -> Job:
    own = client is None
    client = client or pinned_client()
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
        try:
            page = await safe_get(client, url)
            if job := from_json_ld(page) or from_page(page):
                return job
        except (BlockedURL, NotFound):
            raise
        except (httpx.HTTPError, FetchError):
            pass  # bot protection (403/429), TLS quirks… — a real browser may still get through
        if BROWSER_FALLBACK:
            if job := from_rendered(await render_page(url)):
                return job
        raise FetchError("The page returned too little text, even when rendered in a headless browser "
                         "(it probably needs a login).")
    except httpx.HTTPError as e:
        raise FetchError(f"Could not fetch the URL ({e}).") from e
    except json.JSONDecodeError as e:
        raise FetchError("The job board returned an unexpected response.") from e
    finally:
        if own:
            await client.aclose()
