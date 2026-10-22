"""What US internship postings say about visa sponsorship.

After each refresh, the descriptions of new US listings are read from their job board's free API
(never Claude) and checked for plain statements: "we are unable to sponsor", "must be a U.S.
citizen", "visa sponsorship is available". The verdict and the sentence it came from are stored
on the listing. Postings that say nothing, or whose board has no API, stay unknown.
"""

import html
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import db, postings

log = logging.getLogger(__name__)

OFFERS = "Offers Sponsorship"
NO = "Does Not Offer Sponsorship"
CITIZEN = "U.S. Citizenship is Required"
RULED_OUT = (NO, CITIZEN)
# Zapply's own estimate (its terms: not to be shown as the employer's statement). A posting that
# says something replaces it.
MAYBE = "May Offer Sponsorship"

US = r"(?:u\.\s?s\.?|us|united states|american)"
# Checked in this order over the whole posting: a refusal anywhere outweighs a general offer.
RULES = [
    (CITIZEN, [
        rf"\b{US} citizens?(hip)?\b.{{0,60}}\b(is |are )?(required|requirement|necessary|mandatory|only)\b",
        rf"\b(must|required to|need to|requires?|requiring)\b.{{0,40}}\b(be |is |are )?(an? )?{US} (citizen|person)s?\b",
        rf"\b{US} citizens? only\b|\b(only|exclusively) (open|available) to {US} citizens\b",
        r"\b(active|current|existing|interim)?\s*(secret|top secret|ts/sci|ts\s*/\s*sci|dod|government|security)"
        r" clearance\b.{0,40}\b(is |are )?(required|must)\b",
        r"\b(must|required to|requires?|ability to|able to|eligible to|eligibility to)\s+(obtain|hold|maintain|possess"
        r"|acquire|receive)\b.{0,60}\bclearance\b",
    ]),
    (NO, [
        r"\b(not|unable to|cannot|can ?not|can't|won't|will not|do not|does not|don't|doesn't|are not able to"
        r"|is not able to|no longer)\s+(currently\s+)?(be able to\s+)?(provide|offer|sponsor|support|consider|accept)\w*\b"
        r".{0,60}\b(visas?|immigration|work (authorization|permit)s?|sponsorship|h-?1b|cpt|f-?1)\b",
        r"\bnot (eligible|available) for (visa |immigration |employment |employer )?sponsorship\b",
        r"\bwithout\s+(the\s+)?(need\s+(for|of)\s+|requiring\s+|requirement\s+(for|of)\s+)?(any\s+)?(current\s+or\s+future\s+"
        r"|future\s+|present\s+or\s+future\s+)?(employer\s+|visa\s+|immigration\s+|company\s+|employment\s+)?sponsorship\b",
        r"\bsponsorship\b.{0,40}\b(is not|will not be|isn't|are not|not)\s+(available|provided|offered|possible|supported)\b",
        r"\bno\s+(visa\s+|immigration\s+|h-?1b\s+|employer\s+)?sponsorship\b",
        r"\b(must|should|will) not\s+(now\s+or\s+in\s+the\s+future\s+)?(require|need)\b.{0,40}\bsponsorship\b",
    ]),
    (OFFERS, [
        r"\b(visa|immigration|h-?1b|work permit|work visa)\s+sponsorship\s+(is\s+|may be\s+|will be\s+|can be\s+)?"
        r"(available|offered|provided|possible|supported)\b",
        r"\b(we|company|employer|role|position|team)\b.{0,30}\b(offers?|provides?|will provide|can provide|supports?"
        r"|sponsors?|will sponsor|can sponsor|(is|are) open to sponsoring|(is|are) willing to sponsor)\s+"
        r"(visas?|immigration|h-?1b|work visas?|employment visas?|visa sponsorship|immigration sponsorship)\b",
        r"\b(open|willing) to sponsor(ing)?\b",
        r"\b(eligible|eligibility) for (visa |immigration )?sponsorship\b",
    ]),
]
RULES = [(verdict, [re.compile(p, re.I) for p in patterns]) for verdict, patterns in RULES]
# Equal-opportunity boilerplate mentions citizenship without setting a requirement.
BOILERPLATE = re.compile(r"discriminat|without regard|regard to|protected (veteran|characteristic|class|status)"
                         r"|equal (employment )?opportunit|e-verify", re.I)
NEGATION = re.compile(r"\b(not|unable|cannot|can't|won't|don't|doesn't|no longer|without)\b", re.I)
# "Citizenship is not required", "a clearance is a plus": no requirement.
NOT_REQUIRED = re.compile(r"\bnot (required|necessary|mandatory)\b|\b(plus|preferred|desired|desirable|nice to have"
                          r"|bonus|advantage)\b", re.I)


def _sentences(text: str) -> list[str]:
    # A single letter and a full stop ("U.S.", "e.g.") doesn't end a sentence.
    return [s.strip() for s in re.split(r"(?<=[.!?])(?<!\b[A-Za-z]\.)\s+|\n+|•", text) if len(s.strip()) > 10]


def detect(text: str | None) -> tuple[str, str] | None:
    """(verdict, the sentence that says so), or None if the posting doesn't say."""
    # Some boards escape their descriptions twice ("&amp;#xa;"); undo what's left.
    sentences = [s for s in _sentences(html.unescape(text or "")) if not BOILERPLATE.search(s)]
    for verdict, patterns in RULES:
        for s in sentences:
            if verdict == OFFERS and NEGATION.search(s) or verdict == CITIZEN and NOT_REQUIRED.search(s):
                continue
            if any(p.search(s) for p in patterns):
                return verdict, (s if len(s) <= 240 else s[:237].rstrip() + "…")
    return None


# ---------- checking listings ----------

BATCH = 300
WORKERS = 6
_lock = threading.Lock()


def pending(conn, limit: int = BATCH) -> list[dict]:
    """Visible US (or plain "Remote") listings whose posting hasn't been read yet, newest first."""
    return [dict(r) for r in conn.execute(
        f"SELECT id, url, posting_key, board FROM listings WHERE {db.visible()} AND visa_checked IS NULL "
        "AND (regions LIKE '%,US,%' OR regions = ',REMOTE,') ORDER BY date_posted DESC LIMIT ?", (limit,))]


def check(listings: list[dict]) -> dict:
    """Read each listing's description and store what it says about sponsorship."""
    cache: dict = {}  # whole-board downloads (Ashby, Workable), shared across the batch

    def one(listing):
        try:
            return listing["id"], postings.api_text(listing, cache=cache), None
        except Exception as exc:  # network trouble: try again after the next refresh
            return listing["id"], None, exc

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(one, listings))
    now, stats = int(time.time()), {"read": 0, "found": 0, "failed": 0}
    with db.connect() as conn:
        for listing_id, text, error in results:
            if error:
                stats["failed"] += 1
                continue
            found = detect(text)
            stats["read"] += text is not None
            stats["found"] += found is not None
            conn.execute("UPDATE listings SET visa = ?, visa_quote = ?, visa_checked = ? WHERE id = ?",
                         (found and found[0], found and found[1], now, listing_id))
    return stats


def check_pending(limit: int = BATCH) -> dict:
    """Check one batch of unread listings. Safe to call from several threads; extra calls return at once."""
    if not _lock.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        with db.connect() as conn:
            batch = pending(conn, limit)
        stats = check(batch) if batch else {}
        if batch:
            log.info("sponsorship check: %s", stats)
        return {"status": "ok", "checked": len(batch), **stats}
    finally:
        _lock.release()


def check_in_background() -> None:
    """Start reading new postings after a refresh, without making the refresh wait."""
    def run():
        try:
            # A full batch means there may be more; stop if most of it failed (offline, say).
            while (r := check_pending()).get("checked") == BATCH and r.get("failed", 0) < BATCH // 2:
                pass
        except Exception:
            log.exception("sponsorship check failed")
    threading.Thread(target=run, name="visa-check", daemon=True).start()


def effective(visa: str | None, sponsorship: str | None) -> str | None:
    """What the board shows: the posting's own words first, then the source list's field."""
    return visa or (sponsorship if sponsorship and sponsorship != "Other" else None)


def sql(alias: str = "l") -> str:
    """SQL for effective(), for filters and counts."""
    return f"COALESCE({alias}.visa, NULLIF({alias}.sponsorship, 'Other'))"
