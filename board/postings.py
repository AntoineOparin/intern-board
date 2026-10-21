"""Full job descriptions, fetched on demand and cached.

Postings on Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, BambooHR, Rippling and
Recruiterbox come from their public APIs. Anything else (iCIMS, Oracle, company sites) is read by
Claude with its WebFetch tool, which can fail on pages that need JavaScript or a login; callers
should then ask the user to paste the description.
"""

import gzip
import html
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import ai, ats, db

MAX_CHARS = 12_000
CACHE_DAYS = 14

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["found", "description"],
    "properties": {
        "found": {"type": "boolean", "description": "False if the page had no readable job description."},
        "description": {"type": "string", "description": "The posting's text: responsibilities, "
                        "qualifications, team, location, pay. Plain text, no commentary."},
    },
}


def _plain(text: str) -> str:
    text = html.unescape(re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", text or "", flags=re.I))
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()[:MAX_CHARS]


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": ats.USER_AGENT, "Accept-Encoding": "gzip",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    return json.loads(body)


def _board(listing: dict) -> tuple[str, str] | None:
    if listing.get("board"):
        platform, _, token = listing["board"].partition(":")
        return platform, token
    return ats.parse_board_url(listing["url"])


# Lists whose apply links go through their own site first (zapply.jobs/l/d/… -> the employer's posting).
REDIRECTORS = {"zapply.jobs"}


def _resolve(url: str) -> str:
    """Where a redirecting link ends up."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": ats.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.geturl()
    except urllib.error.HTTPError as exc:  # the employer's page refused a HEAD; its address is enough
        if urlparse(exc.geturl() or "").netloc not in REDIRECTORS | {""}:
            return exc.geturl()
        raise


def _cached(cache: dict | None, url: str):
    """Whole-board downloads, shared by the postings of one board within a batch."""
    if cache is None:
        return _get_json(url)
    if url not in cache:
        cache[url] = _get_json(url)
    return cache[url]


def api_text(listing: dict, cache: dict | None = None) -> str | None:
    """The posting's description from its job board's free API.

    None if the board has no API or the posting is gone. Network and parsing errors are raised,
    so callers can tell "nothing to read" from "try again later".
    """
    url = listing["url"]
    if urlparse(url).netloc in REDIRECTORS:
        url = _resolve(url)
        listing = {**listing, "url": url, "board": None, "posting_key": None}
    key = ats.posting_key(url) or listing.get("posting_key") or ""
    board = _board(listing)
    kind, _, ident = key.partition(":")
    try:
        if kind == "gh" and board and board[0] == "greenhouse":
            return _plain(_get_json(f"https://boards-api.greenhouse.io/v1/boards/{board[1]}/jobs/{ident}")
                          .get("content", ""))
        if kind == "lever" and board:
            data = _get_json(f"https://api.lever.co/v0/postings/{board[1]}/{ident}")
            parts = [data.get("descriptionPlain") or ""]
            parts += [f"{l.get('text', '')}:\n{_plain(l.get('content', ''))}" for l in data.get("lists", [])]
            parts.append(data.get("additionalPlain") or "")
            return "\n\n".join(p for p in parts if p).strip()[:MAX_CHARS]
        if kind == "ashby" and board:
            data = _cached(cache, f"https://api.ashbyhq.com/posting-api/job-board/{board[1]}")
            job = next((j for j in data.get("jobs", []) if j.get("id") == ident), None)
            return (job.get("descriptionPlain") or _plain(job.get("descriptionHtml", "")))[:MAX_CHARS] if job else None
        if kind == "wd" and board and board[0] == "workday":
            base, tenant, site = ats.workday_site(board[1])
            path = urlparse(url).path
            at = max(path.find("/job/"), path.find("/details/"))
            if at < 0:
                return None
            rest = re.sub(r"/apply.*$", "", path[at:]).replace("/details/", "/job/", 1)
            info = _get_json(f"{base}/wday/cxs/{tenant}/{site}{rest}").get("jobPostingInfo") or {}
            return _plain(info.get("jobDescription", "")) or None
        if kind == "sr" and board:
            data = _get_json(f"https://api.smartrecruiters.com/v1/companies/{board[1]}/postings/{ident}")
            sections = ((data.get("jobAd") or {}).get("sections") or {}).values()
            return _plain("\n\n".join(s.get("text", "") for s in sections if isinstance(s, dict))) or None
        if kind == "workable" and board:
            data = _cached(cache, f"https://apply.workable.com/api/v1/widget/accounts/{board[1]}?details=true")
            job = next((j for j in data.get("jobs", []) if (j.get("shortcode") or "").upper() == ident), None)
            return _plain(job.get("description", "")) or None if job else None
        if kind == "bamboo":
            sub, _, job_id = ident.partition(":")
            data = _get_json(f"https://{sub}.bamboohr.com/careers/{job_id}/detail")
            return _plain(((data.get("result") or {}).get("jobOpening") or {}).get("description", "")) or None
        if kind == "rippling" and board:
            data = _get_json(f"https://ats.rippling.com/api/v2/board/{board[1]}/jobs/{ident}")
            desc = data.get("description") or {}
            return _plain("\n\n".join(v for v in desc.values() if isinstance(v, str))
                          if isinstance(desc, dict) else str(desc)) or None
        if kind == "rbox" and board:
            data = _get_json(f"https://jsapi.recruiterbox.com/v1/openings/{ident}?client_name={board[1]}")
            return _plain(data.get("description", "")) or None
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404, 410):  # the posting was taken down (Workday answers 403)
            return None
        raise
    return None


def _from_api(listing: dict) -> str | None:
    try:
        return api_text(listing)
    except (OSError, ValueError):
        return None


def _from_claude(listing: dict) -> str | None:
    result = ai.ask(
        f"Use WebFetch to open this job posting and return its description text.\nURL: {listing['url']}\n"
        f"Expected role: {listing['title']} at {listing['company']}.\nIf the page is a login wall, an error, "
        "or a different job, set found to false.",
        system="You retrieve job postings. Return the posting text faithfully; never summarise or invent.",
        schema=SCHEMA, tools=["WebFetch"], timeout=180)
    return result["description"][:MAX_CHARS] if result.get("found") and result.get("description") else None


def description(listing_id: str, *, refresh: bool = False) -> dict:
    """{"text": str | None, "source": "api" | "claude" | "pasted" | None, "fetched_at": int | None}.

    Blocking (up to a few minutes when Claude has to fetch the page); call it from an AI job.
    """
    with db.connect() as conn:
        listing = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
        if not listing:
            raise ValueError("That listing no longer exists.")
        cached = conn.execute("SELECT * FROM posting_details WHERE listing_id = ?", (listing_id,)).fetchone()
    if cached and (cached["source"] == "pasted" or
                   (not refresh and cached["fetched_at"] > time.time() - CACHE_DAYS * 86400)):
        return {"text": cached["text"], "source": cached["source"], "fetched_at": cached["fetched_at"]}

    listing = dict(listing)
    text, source = _from_api(listing), "api"
    if not text:
        text, source = _from_claude(listing), "claude"
    if not text:
        return {"text": None, "source": None, "fetched_at": None}
    save(listing_id, text, source)
    return {"text": text, "source": source, "fetched_at": int(time.time())}


def save(listing_id: str, text: str, source: str = "pasted") -> None:
    """Store a description; "pasted" ones (typed by the user) are never overwritten by fetches."""
    with db.connect() as conn:
        conn.execute("INSERT INTO posting_details (listing_id, text, source, fetched_at) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT (listing_id) DO UPDATE SET text = excluded.text, source = excluded.source, "
                     "fetched_at = excluded.fetched_at", (listing_id, text[:MAX_CHARS], source, int(time.time())))
