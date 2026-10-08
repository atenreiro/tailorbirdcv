"""The hiring company's site icon (favicon) for an application, fetched once and kept with it.

Which site: the job link's own site, unless that's a job board (Greenhouse, Lever, Workday, LinkedIn…), whose icon
would be the board's, not the company's. Then, in order: the company's website named in the posting's JobPosting
data (hiringOrganization url/sameAs), a domain the board's link names (Eightfold's ?domain=), and the company's
official website as the job analysis names it (the AI, only when it's certain; also for pasted job descriptions).
Each of those must pass `matches_company`: the site's homepage title or name, or its address, has to name the
company from the posting, so a recruitment agency's or a recruiting system's own site never gives the icon. Nothing
found or nothing that passes: no icon. No search engine or logo service is ever asked (they'd learn every company
the user applies to). Every request goes through jobfetch's SSRF-guarded
client; only images up to 200 KB are kept (ICO, PNG, GIF, JPEG, WEBP, or SVG, which is only ever shown as an image
and served with a policy that blocks scripts). Sites that answer plain requests with an empty page (bot protection)
get one more try through the headless browser, when it's installed: it renders the homepage to find where the icon
really lives. The browser only ever loads the icon from TailorbirdCV (GET /api/applications/{id}/favicon), never from
the company's site.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .jobfetch import FetchError, org_sites, pinned_client, safe_fetch, safe_get

log = logging.getLogger("tailorbirdcv")

MAX_ICON = 200_000
TIMEOUT = 10.0
BROWSER_TIMEOUT = 45.0  # rendering a protected homepage in the headless browser takes a few seconds
FILE_RE = re.compile(r"^favicon\.(ico|png|gif|jpg|webp|svg)$")

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


def clean_site(value: str | None) -> str | None:
    """A website as the analysis or a board names it ("ocbc.com", "https://www.ocbc.com/group") → its origin, or
    None when it isn't a plain public web address, or is a board or social profile."""
    value = (value or "").strip()
    if not value:
        return None
    if "://" not in value:
        value = "https://" + value
    p = urlparse(value)
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}", host) \
            or _under(host, BOARDS + SOCIAL):
        return None
    return f"https://{host}"


def board_domain(job_url: str) -> str | None:
    """A domain the board's own link names for the employer (Eightfold: …eightfold.ai/careers?domain=paypal.com)."""
    if not is_board(job_url):
        return None
    values = parse_qs(urlparse(job_url).query).get("domain") or []
    return clean_site(values[0]) if values else None


# Words that don't identify a company on their own (or describe an undisclosed one).
_GENERIC = set("""
the and of for via by on behalf client company companies group holdings holding corp corporation co inc incorporated
ltd limited llc llp plc pte pvt gmbh ag sa sas nv bv spa kk bhd sdn international global worldwide multinational
undisclosed confidential stealth leading top major large tier one regional local services service solutions
technologies technology tech systems partners partner consulting recruitment recruiting staffing talent bank banking
financial finance capital asia apac emea europe americas
""".split())


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def _name_words(company: str) -> list[str]:
    """The company's name words, without what a recruiter adds ("… via Agency", "(on behalf of …)")."""
    name = re.split(r"\bvia\b|\bon behalf of\b|\bthrough\b|[(\[|]", _fold(company))[0]
    return re.findall(r"[a-z0-9]+", name)


def matches_company(company: str, site: str, home: str) -> bool:
    """Whether the site at `site` (homepage HTML `home`) is this company's: its main name word is in the page's
    title or site name, or in the address (4+ letters), or the name's initials are the address
    ("Oversea-Chinese Banking Corporation" → ocbc.com). An undisclosed or generic name never matches."""
    words = _name_words(company)
    distinctive = [w for w in words if w not in _GENERIC and len(w) >= 2]
    if not distinctive:
        return False
    main = distinctive[0]
    host = _host(site).removeprefix("www.")
    label = host.split(".")[0]
    initials = "".join(w[0] for w in words if w not in ("the", "and", "of", "via", "by", "for"))
    if (len(main) >= 4 and main in host.replace("-", "")) or (len(initials) >= 3 and label == initials):
        return True
    soup = BeautifulSoup(home or "", "html.parser")
    names = [soup.title.get_text(" ") if soup.title else ""]
    for meta in soup.find_all("meta"):
        if (meta.get("property") or meta.get("name") or "").lower() in ("og:site_name", "application-name", "og:title"):
            names.append(meta.get("content") or "")
    text = _fold(" ".join(names))
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(main)}(?![a-z0-9])", text))


def _size(sizes: str | None) -> int:
    m = re.search(r"(\d+)\s*x\s*\d+", sizes or "")
    return int(m.group(1)) if m else 0


def icon_links(page: str, base: str) -> list[str]:
    """Candidate icon URLs, best first: declared raster icons nearest 32–64 px, other raster icons, SVG icons,
    apple-touch icons, then /favicon.ico."""
    found: list[tuple[float, str]] = []
    if page:
        for link in BeautifulSoup(page, "html.parser").find_all("link", href=True):
            rel = " ".join(link.get("rel") or []).lower()
            if "icon" not in rel or "mask-icon" in rel:
                continue
            href = link["href"].strip()
            svg = "svg" in link.get("type", "").lower() or urlparse(href).path.lower().endswith(".svg")
            size = _size(link.get("sizes"))
            rank = 3 if "apple-touch" in rel else 2.5 if svg else 0 if 32 <= size <= 64 else 1 if size else 2
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
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if (head.startswith(b"<svg") or head.startswith(b"<?xml") or head.startswith(b"<!--")) \
            and b"<svg" in head and b"<html" not in head:
        return "svg"  # shown only as an image, served with scripts blocked (api.get_favicon)
    return None


async def candidates(job_url: str, sites: list[str], website: str, client: httpx.AsyncClient
                     ) -> list[tuple[str, bool]]:
    """(site, must it match the company?) in order of trust. The job link's own site needs no check (it's the
    company's careers site); everything named by a board, the posting or the AI does."""
    out: list[tuple[str, bool]] = []
    if job_url and not is_board(job_url):
        if origin := _origin(job_url):
            out.append((origin, False))
    elif job_url:
        if not sites:
            try:  # read through a board API: the posting page may still name the company's website
                sites = org_sites(await safe_get(client, job_url))
            except (FetchError, httpx.HTTPError, ValueError):
                sites = []
        out += [(site, True) for site in map(clean_site, sites) if site]
        if site := board_domain(job_url):
            out.append((site, True))
    if site := clean_site(website):
        out.append((site, True))
    unique: dict[str, tuple[str, bool]] = {}
    for site, check in out:  # one try per site ("www." or not)
        unique.setdefault(_host(site).removeprefix("www."), (site, check))
    return list(unique.values())


async def find_icon(site: str, check: bool, company: str, client: httpx.AsyncClient) -> tuple[bytes, str] | None | bool:
    """The icon from this site's homepage, None when it has none, or False when it isn't the company's site (or its
    homepage was empty, so that couldn't be checked: then the headless browser gets a try)."""
    try:
        home = await safe_get(client, site + "/")
    except (FetchError, httpx.HTTPError, ValueError):
        home = ""
    if check and not (home.strip() and matches_company(company, site, home)):
        return False if home.strip() else None
    return await _first_icon(icon_links(home, site + "/"), client)  # an empty page still has /favicon.ico


async def _first_icon(urls: list[str], client: httpx.AsyncClient) -> tuple[bytes, str] | None:
    for url in urls:
        try:
            data, _, _ = await safe_fetch(client, url, MAX_ICON)
        except (FetchError, httpx.HTTPError, ValueError):
            continue
        if ext := sniff(data):
            return data, ext
    return None


async def find_icon_rendered(site: str, check: bool, company: str, client: httpx.AsyncClient
                             ) -> tuple[bytes, str] | None:
    """For sites that give plain requests an empty page: render the homepage in the headless browser (every
    request still SSRF-checked) to find the icon's real address, often on a separate image server."""
    from . import jobfetch
    if not jobfetch.BROWSER_FALLBACK:
        return None
    rendered = await jobfetch.render_page(site + "/")
    if check and not matches_company(company, site, rendered.html):
        return None
    return await _first_icon(icon_links(rendered.html, rendered.url or site + "/"), client)


async def fetch(job_url: str, sites: list[str] | None = None, client: httpx.AsyncClient | None = None,
                company: str = "", website: str = "") -> tuple[bytes, str] | None:
    """The company's icon, or None (never raises). Each candidate site in turn (`candidates`): plain requests
    first (at most TIMEOUT seconds), then the headless browser when they found nothing (at most BROWSER_TIMEOUT
    seconds); a site that isn't the company's is skipped without the browser."""
    own = client is None
    client = client or pinned_client(timeout=TIMEOUT)
    try:
        try:
            found_sites = await asyncio.wait_for(candidates(job_url, list(sites or []), website, client), TIMEOUT)
        except Exception as e:  # noqa: BLE001 — no icon is fine
            log.debug("TailorbirdCV: no site candidates for %s (%s)", job_url, e)
            return None
        for site, check in found_sites:
            try:
                found = await asyncio.wait_for(find_icon(site, check, company, client), TIMEOUT)
            except Exception as e:  # noqa: BLE001 — no icon is fine; it never matters enough to show an error
                log.debug("TailorbirdCV: no site icon from %s (%s)", site, e)
                found = None
            if found is False:
                continue  # not the company's site
            if found:
                return found
            try:
                if found := await asyncio.wait_for(find_icon_rendered(site, check, company, client), BROWSER_TIMEOUT):
                    return found
            except Exception as e:  # noqa: BLE001
                log.debug("TailorbirdCV: no rendered site icon from %s (%s)", site, e)
        return None
    finally:
        if own:
            await client.aclose()
