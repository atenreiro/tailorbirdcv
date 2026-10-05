"""The hiring company's site icon (favicon) for an application, fetched once and kept with it.

Which site: the job link's own site, unless that's a job board (Greenhouse, Lever, Workday, LinkedIn…), whose icon
would be the board's, not the company's. Then the company's website named in the posting's JobPosting data
(hiringOrganization url/sameAs) is used, or no icon at all. Every request goes through jobfetch's SSRF-guarded
client; only raster images (ICO, PNG, GIF, JPEG, WEBP) up to 200 KB are kept, never SVG. The browser only ever
loads the icon from AutoCV (GET /api/applications/{id}/favicon), never from the company's site.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .jobfetch import FetchError, org_sites, pinned_client, safe_fetch, safe_get

log = logging.getLogger("autocv")

MAX_ICON = 200_000
TIMEOUT = 10.0
FILE_RE = re.compile(r"^favicon\.(ico|png|gif|jpg|webp)$")

BOARDS = (  # job boards and applicant-tracking systems: their favicon is their own logo
    "greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "workday.com", "smartrecruiters.com",
    "linkedin.com", "indeed.com", "glassdoor.com", "jobvite.com", "icims.com", "taleo.net", "oraclecloud.com",
    "successfactors.com", "successfactors.eu", "sapsf.com", "workable.com", "bamboohr.com", "recruitee.com",
    "personio.com", "personio.de", "teamtailor.com", "breezy.hr", "wellfound.com", "ziprecruiter.com",
    "monster.com", "dice.com", "builtin.com", "welcometothejungle.com", "mycareersfuture.gov.sg", "jobstreet.com",
    "efinancialcareers.com", "avature.net", "csod.com", "eightfold.ai",
)
SOCIAL = (  # profiles a posting may list in sameAs: never the company's own site
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com", "tiktok.com", "github.com",
    "crunchbase.com", "wikipedia.org", "medium.com",
)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def _under(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def is_board(url: str) -> bool:
    return _under(_host(url), BOARDS)


def _origin(url: str) -> str | None:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}" if p.scheme in ("http", "https") and p.hostname else None


def company_site(job_url: str, sites: list[str]) -> str | None:
    """Where to take the icon from: the link's own site, or (for a job board) the company's site, or None."""
    if not is_board(job_url):
        return _origin(job_url)
    for site in sites:
        host = _host(site)
        if host and not _under(host, BOARDS + SOCIAL):
            return _origin(site)
    return None


def _size(sizes: str | None) -> int:
    m = re.search(r"(\d+)\s*x\s*\d+", sizes or "")
    return int(m.group(1)) if m else 0


def icon_links(page: str, base: str) -> list[str]:
    """Candidate icon URLs, best first: declared raster icons nearest 32–64 px, apple-touch icons, then
    /favicon.ico. SVG icons are skipped (only raster images are kept)."""
    found: list[tuple[int, str]] = []
    if page:
        for link in BeautifulSoup(page, "html.parser").find_all("link", href=True):
            rel = " ".join(link.get("rel") or []).lower()
            if "icon" not in rel or "mask-icon" in rel:
                continue
            href = link["href"].strip()
            if link.get("type", "").lower() == "image/svg+xml" or urlparse(href).path.lower().endswith(".svg"):
                continue
            size = _size(link.get("sizes"))
            rank = 3 if "apple-touch" in rel else 0 if 32 <= size <= 64 else 1 if size else 2
            found.append((rank, urljoin(base, href)))
    urls = [u for _, u in sorted(found, key=lambda x: x[0])]
    urls.append(urljoin(base, "/favicon.ico"))
    return [u for i, u in enumerate(urls) if u.startswith(("http://", "https://")) and u not in urls[:i]]


def sniff(data: bytes) -> str | None:
    """The image type from its first bytes (never trusting the server's content type), or None."""
    if data[:4] == b"\x00\x00\x01\x00":
        return "ico"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"GIF8":
        return "gif"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


async def find_icon(job_url: str, sites: list[str], client: httpx.AsyncClient) -> tuple[bytes, str] | None:
    site = company_site(job_url, sites)
    if site is None and is_board(job_url) and not sites:
        try:  # read through a board API: the posting page may still name the company's website
            site = company_site(job_url, org_sites(await safe_get(client, job_url)))
        except (FetchError, httpx.HTTPError, ValueError):
            return None
    if not site:
        return None
    try:
        home = await safe_get(client, site + "/")
    except (FetchError, httpx.HTTPError, ValueError):
        home = ""  # still try /favicon.ico
    for url in icon_links(home, site + "/"):
        try:
            data, _, _ = await safe_fetch(client, url, MAX_ICON)
        except (FetchError, httpx.HTTPError, ValueError):
            continue
        if ext := sniff(data):
            return data, ext
    return None


async def fetch(job_url: str, sites: list[str] | None = None, client: httpx.AsyncClient | None = None
                ) -> tuple[bytes, str] | None:
    """The company's icon for this job link, or None (never raises; at most TIMEOUT seconds)."""
    own = client is None
    client = client or pinned_client(timeout=TIMEOUT)
    try:
        return await asyncio.wait_for(find_icon(job_url, list(sites or []), client), TIMEOUT)
    except Exception as e:  # noqa: BLE001 — no icon is fine; it never matters enough to show an error
        log.debug("AutoCV: no site icon for %s (%s)", job_url, e)
        return None
    finally:
        if own:
            await client.aclose()
