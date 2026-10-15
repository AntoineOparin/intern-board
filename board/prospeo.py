"""Prospeo API client (https://prospeo.io/api-docs): people search and verified-email reveal.

Credits: a search costs 1 per page that returns anyone (repeating it within 30 days is free);
revealing an email costs 1 only when a verified email is found. Account info is free.
"""

import json
import threading
import time
import urllib.error
import urllib.request

from . import settings

API = "https://api.prospeo.io"
KEY_NAME = "PROSPEO_API_KEY"

MESSAGES = {
    "INVALID_API_KEY": "Prospeo rejected the API key. Check it under My profile → Integrations.",
    "INSUFFICIENT_CREDITS": "You're out of Prospeo credits for this month.",
    "RATE_LIMIT": "Prospeo is rate-limiting requests. Wait a minute and try again.",
    "PLAN_REQUIRED": "That search needs a paid Prospeo plan.",
    "SERVICE_TEMPORARILY_UNAVAILABLE": "Prospeo is temporarily unavailable. Try again shortly.",
}


# Search allows about 1 request per second; space them out and retry once when rate-limited.
SEARCH_GAP = 1.2
_search_lock = threading.Lock()
_last_search = 0.0


class ProspeoError(Exception):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or MESSAGES.get(code) or f"Prospeo error: {code}")


class NoKey(ProspeoError):
    def __init__(self):
        super().__init__("NO_KEY", "Add your Prospeo API key under My profile → Integrations.")


def key() -> str | None:
    return settings.get(KEY_NAME)


def _call(path: str, body: dict | None = None, api_key: str | None = None) -> dict:
    api_key = api_key or key()
    if not api_key:
        raise NoKey()
    req = urllib.request.Request(f"{API}{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-KEY": api_key, "Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise ProspeoError("RATE_LIMIT") from exc
        try:
            data = json.loads(exc.read() or b"{}")
        except json.JSONDecodeError:
            raise ProspeoError("HTTP_ERROR", f"Prospeo returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProspeoError("NETWORK", f"Couldn't reach Prospeo: {exc}") from exc
    if data.get("error"):
        raise ProspeoError(data.get("error_code") or "UNKNOWN")
    return data


def account(api_key: str | None = None) -> dict:
    """Free. {current_plan, remaining_credits, used_credits, next_quota_renewal_date, ...}"""
    return _call("/account-information", api_key=api_key)["response"]


def search_people(*, website: str, titles: list[str], countries: list[str] | None = None,
                  exclude_seniority: list[str] | None = None, page: int = 1) -> dict | None:
    """One page (25) of people at the company with matching titles. None when nobody matches (free)."""
    filters = {
        "company": {"websites": {"include": [website]}},
        "person_job_title": {"include": titles, "match_mode": "CONTAINS"},
    }
    if countries:
        filters["person_location_search"] = {"include": countries}
    if exclude_seniority:
        filters["person_seniority"] = {"exclude": exclude_seniority}
    global _last_search
    for attempt in range(2):
        with _search_lock:
            wait = _last_search + SEARCH_GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last_search = time.monotonic()
        try:
            return _call("/search-person", {"page": page, "filters": filters})
        except ProspeoError as exc:
            if exc.code == "NO_RESULTS":
                return None
            if exc.code == "RATE_LIMIT" and attempt == 0:
                time.sleep(2.5)
                continue
            raise


def enrich_person(person_id: str) -> dict | None:
    """{"person", "company", "free_enrichment"} with a verified email, or None when there isn't one.

    Costs 1 credit when a verified email is found, except within 90 days of enriching the same
    person (free_enrichment is then true). Not finding one is free.
    """
    try:
        return _call("/enrich-person", {"only_verified_email": True, "data": {"person_id": person_id}})
    except ProspeoError as exc:
        if exc.code == "NO_MATCH":
            return None
        raise


def reveal_email(person_id: str) -> dict | None:
    """The person's verified email object, or None when there isn't one (not charged)."""
    data = enrich_person(person_id)
    email = ((data or {}).get("person") or {}).get("email") or {}
    return email if email.get("revealed") and email.get("email") else None
