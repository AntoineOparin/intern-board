"""Fetch internship listings and store the US/Canada ones.

Two sources:
- the community-maintained SimplifyJobs list (one JSON file), and
- company job boards on Greenhouse, Lever and Ashby (the watchlist), read directly.

A posting found in both is kept once, from the SimplifyJobs list.
"""

import collections
import json
import logging
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import ats, community, db
from .locations import classify

log = logging.getLogger(__name__)

SIMPLIFY_URL = ("https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/"
                "dev/.github/scripts/listings.json")
# Boards whose last community-listed internship is older than this are not auto-added.
AUTO_BOARD_MAX_AGE = 540 * 86400
BOARD_WORKERS = 6
# Boards with matching internships are checked every refresh (hourly); the rest less often.
QUIET_BOARD_INTERVAL = 6 * 3600

CATEGORY_ALIASES = {
    "Software Engineering": "Software",
    "Data Science, AI & Machine Learning": "AI/ML/Data",
    "Hardware Engineering": "Hardware",
    "Quantitative Finance": "Quant",
    "Product Management": "Product",
}

_refresh_lock = threading.Lock()

# A listing counts as new only if it was posted shortly before we first saw it.
FRESH_WINDOW = 2 * 86400


def first_seen_for(date_posted: int | None, now: int) -> int:
    """When to say we first saw a listing.

    Postings found long after they went up (a board switched back on, a filter change, a job
    dropping off one source but not the other) are dated by their posting date, so they never
    show up as "new".
    """
    if date_posted and date_posted < now - FRESH_WINDOW:
        return date_posted
    return now

UPSERT = """
    INSERT INTO listings (id, source, company, title, url, locations, regions, category, terms, degrees,
                          sponsorship, date_posted, first_seen, active, posting_key, board)
    VALUES (:id, :source, :company, :title, :url, :locations, :regions, :category, :terms, :degrees,
            :sponsorship, :date_posted, :first_seen, 1, :posting_key, :board)
    ON CONFLICT (id) DO UPDATE SET
        company = excluded.company, title = excluded.title, url = excluded.url,
        locations = excluded.locations, regions = excluded.regions, category = excluded.category,
        terms = excluded.terms, degrees = excluded.degrees, sponsorship = excluded.sponsorship,
        date_posted = excluded.date_posted, posting_key = excluded.posting_key, board = excluded.board,
        active = 1
"""


def _joined(values) -> str:
    return "," + ",".join(v for v in values if v and v != "N/A") + ","


# ---------- SimplifyJobs ----------

def fetch_simplify_raw() -> list[dict]:
    req = urllib.request.Request(SIMPLIFY_URL, headers={"User-Agent": ats.USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def simplify_listings(raw: list[dict]) -> list[dict]:
    listings = []
    for item in raw:
        if not item.get("active") or not item.get("is_visible", True):
            continue
        kept = [loc for loc in item.get("locations") or [] if classify(loc)]
        if not kept:
            continue
        regions = set().union(*(classify(loc) for loc in kept))
        category = item.get("category")
        url = item.get("url", "")
        listings.append({
            "id": f"simplify:{item['id']}",
            "source": "simplify",
            "company": item.get("company_name", "").strip(),
            "title": item.get("title", "").strip(),
            "url": url,
            "locations": " / ".join(kept),
            "regions": _joined(sorted(regions)),
            "category": CATEGORY_ALIASES.get(category, category),
            "terms": _joined(item.get("terms") or []),
            "degrees": _joined(item.get("degrees") or []),
            "sponsorship": item.get("sponsorship"),
            "date_posted": item.get("date_posted"),
            "posting_key": ats.posting_key(url),
            "board": None,
        })
    return listings


def seed_companies(conn, raw: list[dict], now: int) -> int:
    """Add every Greenhouse/Lever/Ashby board the community list has linked to recently."""
    names: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    for item in raw:
        if (item.get("date_posted") or 0) < now - AUTO_BOARD_MAX_AGE:
            continue
        board = ats.parse_board_url(item.get("url", ""))
        if board:
            names[board][item.get("company_name", "").strip() or board[1]] += 1
    before = conn.total_changes
    conn.executemany(
        "INSERT INTO companies (platform, token, name, origin, added_at) VALUES (?, ?, ?, 'auto', ?) "
        "ON CONFLICT (platform, token) DO NOTHING",
        [(p, t, c.most_common(1)[0][0], now) for (p, t), c in names.items()])
    return conn.total_changes - before


# ---------- company boards ----------

def board_listings(company: dict, jobs: list[dict]) -> list[dict]:
    listings = []
    for j in ats.internships(jobs):
        shown = [loc for loc in j["locations"] if ats.regions_for([loc])] or j["locations"]
        listings.append({
            "id": j["key"],
            "source": "board",
            "company": company["name"],
            "title": j["title"].strip(),
            "url": j["url"],
            "locations": " / ".join(shown) or "Location not listed",
            "regions": _joined(sorted(j["regions"])),
            "category": j["category"],
            "terms": _joined(j["terms"]),
            "degrees": ",",
            "sponsorship": None,
            "date_posted": j["posted"],
            "posting_key": j["key"],
            "board": f"{company['platform']}:{company['token']}",
        })
    return listings


def _fetch_one(company: dict) -> dict:
    try:
        jobs, size = ats.fetch_board(company["platform"], company["token"])
        return {"company": company, "status": "ok", "jobs": jobs, "bytes": size}
    except ats.BoardNotFound:
        return {"company": company, "status": "not_found"}
    except Exception as exc:  # network errors, bad JSON: keep the old listings
        return {"company": company, "status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}


def sync_boards(conn, companies: list[dict], skip_keys: set[str], now: int) -> dict:
    """Fetch the given boards and store their internships, skipping postings in `skip_keys`."""
    stats = collections.Counter()
    with ThreadPoolExecutor(BOARD_WORKERS) as pool:
        results = list(pool.map(_fetch_one, companies))

    for r in results:
        c, board = r["company"], f"{r['company']['platform']}:{r['company']['token']}"
        stats[r["status"]] += 1
        stats["bytes"] += r.get("bytes", 0)
        if r["status"] != "ok":
            # A board that no longer exists was likely renamed; stop checking auto-added ones.
            disable = r["status"] == "not_found" and c["origin"] == "auto"
            conn.execute("UPDATE companies SET last_checked = ?, last_status = ?, last_error = ?, "
                         "enabled = CASE WHEN ? THEN 0 ELSE enabled END WHERE platform = ? AND token = ?",
                         (now, r["status"], r.get("error"), disable, c["platform"], c["token"]))
            if r["status"] == "not_found":
                conn.execute("UPDATE listings SET active = 0 WHERE board = ?", (board,))
            continue

        listings = [l for l in board_listings(c, r["jobs"]) if l["posting_key"] not in skip_keys]
        existing = {row[0] for row in conn.execute("SELECT id FROM listings WHERE board = ?", (board,))}
        conn.executemany(UPSERT, [{**l, "first_seen": first_seen_for(l["date_posted"], now)} for l in listings])
        current = {l["id"] for l in listings}
        conn.executemany("UPDATE listings SET active = 0 WHERE id = ?", [(i,) for i in existing - current])
        conn.execute("UPDATE companies SET last_checked = ?, last_status = 'ok', last_error = NULL, "
                     "jobs_total = ?, interns = ? WHERE platform = ? AND token = ?",
                     (now, len(r["jobs"]), len(listings), c["platform"], c["token"]))
        stats["kept"] += len(listings)
        stats["new"] += sum(1 for l in listings if l["id"] not in existing
                            and first_seen_for(l["date_posted"], now) == now)
    return dict(stats)


def _move_tracked_duplicates(conn) -> None:
    """If a tracked board listing now also appears in the community list, track that copy instead."""
    conn.execute("""
        UPDATE tracker SET listing_id = (
            SELECT s.id FROM listings b JOIN listings s
              ON s.posting_key = b.posting_key AND s.source = 'simplify' AND s.active = 1
            WHERE b.id = tracker.listing_id AND b.source = 'board')
        WHERE listing_id IN (
            SELECT b.id FROM listings b JOIN listings s
              ON s.posting_key = b.posting_key AND s.source = 'simplify' AND s.active = 1
            WHERE b.source = 'board' AND b.active = 0
              AND s.id NOT IN (SELECT listing_id FROM tracker))
    """)


def due_companies(conn, now: int, everything: bool = False) -> list[dict]:
    """Enabled boards to check now: active ones every time, quiet ones every QUIET_BOARD_INTERVAL."""
    if everything:
        return [dict(r) for r in conn.execute("SELECT * FROM companies WHERE enabled = 1")]
    return [dict(r) for r in conn.execute(
        "SELECT * FROM companies WHERE enabled = 1 AND (last_checked IS NULL OR interns > 0 "
        "OR last_status <> 'ok' OR last_checked <= ?)", (now - QUIET_BOARD_INTERVAL + 300,))]


def active_simplify_keys(conn) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT posting_key FROM listings WHERE source = 'simplify' AND active = 1 AND posting_key IS NOT NULL")}


# ---------- other community lists ----------

def sync_community(conn, now: int) -> dict:
    """Fetch the other GitHub lists; skip internships a higher-priority source already has."""
    active = conn.execute("SELECT source, company, title, posting_key FROM listings WHERE active = 1").fetchall()
    stats = {}
    for source in community.SOURCES:
        try:
            listings = community.fetch(source)
        except Exception as exc:  # one broken list shouldn't stop the others
            log.warning("community source %s failed: %s", source, exc)
            stats[source] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
            continue
        higher = [r for r in active if r["source"] != source]
        keys = {r["posting_key"] for r in higher if r["posting_key"]}
        names = {community.name_key(r["company"], r["title"]) for r in higher}
        unique = [l for l in listings if not (l["posting_key"] and l["posting_key"] in keys)
                  and community.name_key(l["company"], l["title"]) not in names]
        # Several rows can share an id (same link listed twice); keep one.
        unique = list({l["id"]: l for l in unique}.values())
        was_active = {r[0] for r in conn.execute("SELECT id FROM listings WHERE source = ? AND active = 1", (source,))}
        conn.executemany(UPSERT, [{**l, "first_seen": first_seen_for(l["date_posted"], now)} for l in unique])
        current = {l["id"] for l in unique}
        conn.executemany("UPDATE listings SET active = 0 WHERE id = ?", [(i,) for i in was_active - current])
        # Later sources de-duplicate against this one too.
        active = [r for r in active if r["source"] != source] + [
            {"source": source, "company": l["company"], "title": l["title"], "posting_key": l["posting_key"]}
            for l in unique]
        stats[source] = {"listed": len(listings), "kept": len(unique),
                         "new": sum(1 for l in unique if l["id"] not in was_active
                                    and first_seen_for(l["date_posted"], now) == now),
                         "closed": len(was_active - current)}
    db.set_meta(conn, "community_status", json.dumps({**stats, "checked_at": now}))
    return stats


# ---------- refresh ----------

def refresh(all_boards: bool = False) -> dict:
    """Pull the latest listings. Safe to call from several threads.

    Checks the boards that are due unless `all_boards` is set.
    """
    if not _refresh_lock.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        started = time.time()
        now = int(started)
        raw = fetch_simplify_raw()
        listings = simplify_listings(raw)
        with db.connect() as conn:
            was_active = {r["id"] for r in conn.execute(
                "SELECT id FROM listings WHERE source = 'simplify' AND active = 1")}
            conn.executemany(UPSERT, [{**l, "first_seen": first_seen_for(l["date_posted"], now)}
                                      for l in listings])
            current = {l["id"] for l in listings}
            closed = was_active - current
            conn.executemany("UPDATE listings SET active = 0 WHERE id = ?", [(i,) for i in closed])
            added_boards = seed_companies(conn, raw, now)
            companies = due_companies(conn, now, all_boards)
            skip = active_simplify_keys(conn)

        # Board fetches take a while; don't hold a write transaction open during them.
        with db.connect() as conn:
            boards = sync_boards(conn, companies, skip, now)
            others = sync_community(conn, now)
            _move_tracked_duplicates(conn)
            db.set_meta(conn, "last_refresh", str(now))
            db.set_meta(conn, "last_error", "")

        fresh = sum(1 for l in listings if l["id"] not in was_active and first_seen_for(l["date_posted"], now) == now)
        result = {"status": "ok", "simplify_active": len(listings), "new": fresh,
                  "closed": len(closed), "boards_checked": len(companies), "boards_added": added_boards,
                  "board_listings": boards.get("kept", 0), "board_new": boards.get("new", 0),
                  "board_errors": boards.get("error", 0), "boards_not_found": boards.get("not_found", 0),
                  "megabytes": round(boards.get("bytes", 0) / 1e6, 1), "community": others,
                  "seconds": round(time.time() - started, 1)}
        result["new"] += result["board_new"] + sum(o.get("new", 0) for o in others.values())
        log.info("refresh: %s", result)
        return result
    except Exception as exc:
        log.exception("refresh failed")
        with db.connect() as conn:
            db.set_meta(conn, "last_error", f"{type(exc).__name__}: {exc}")
        return {"status": "error", "error": str(exc)}
    finally:
        _refresh_lock.release()


def add_board(conn, platform: str, token: str, name: str | None) -> dict:
    """Validate and add a board by hand, then sync it right away."""
    jobs, _ = ats.fetch_board(platform, token)  # raises BoardNotFound
    now = int(time.time())
    name = (name or "").strip() or token.replace("-", " ").title()
    conn.execute("INSERT INTO companies (platform, token, name, origin, added_at) VALUES (?, ?, ?, 'manual', ?) "
                 "ON CONFLICT (platform, token) DO UPDATE SET enabled = 1, name = excluded.name",
                 (platform, token, name, now))
    company = dict(conn.execute("SELECT * FROM companies WHERE platform = ? AND token = ?",
                                (platform, token)).fetchone())
    stats = sync_boards(conn, [company], active_simplify_keys(conn), now)
    return {**company, "kept": stats.get("kept", 0), "jobs_total": len(jobs)}
