"""Full job descriptions, fetched on demand and cached.

Greenhouse, Lever and Ashby postings come from their public APIs. Anything else (Workday,
iCIMS, company sites) is read by Claude with its WebFetch tool, which can fail on pages that
need JavaScript or a login; callers should then ask the user to paste the description.
"""

import gzip
import html
import json
import re
import time
import urllib.error
import urllib.request

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
    req = urllib.request.Request(url, headers={"User-Agent": ats.USER_AGENT, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    return json.loads(body)


def _from_api(listing: dict) -> str | None:
    key, url = listing.get("posting_key") or "", listing["url"]
    board = ats.parse_board_url(url)
    try:
        if key.startswith("gh:") and board:
            data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{board[1]}/jobs/{key[3:]}")
            return _plain(data.get("content", ""))
        if key.startswith("lever:") and board:
            data = _get_json(f"https://api.lever.co/v0/postings/{board[1]}/{key[6:]}")
            parts = [data.get("descriptionPlain") or ""]
            parts += [f"{l.get('text', '')}:\n{_plain(l.get('content', ''))}" for l in data.get("lists", [])]
            parts.append(data.get("additionalPlain") or "")
            return "\n\n".join(p for p in parts if p).strip()[:MAX_CHARS]
        if key.startswith("ashby:") and board:
            data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board[1]}")
            job = next((j for j in data.get("jobs", []) if j.get("id") == key[6:]), None)
            return (job.get("descriptionPlain") or _plain(job.get("descriptionHtml", "")))[:MAX_CHARS] if job else None
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None
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
