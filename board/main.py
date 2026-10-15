import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ats, db, jobs, sources
from . import ai, contacts, documents, people, postings, profile, ranking  # noqa: F401  (registers AI job handlers)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

REFRESH_EVERY = 60 * 60
STATUSES = ("saved", "applied", "interviewing", "offer", "rejected")


async def refresh_loop():
    while True:
        with db.connect() as conn:
            last = int(db.get_meta(conn, "last_refresh") or 0)
        wait = last + REFRESH_EVERY - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
            continue
        await run_in_threadpool(sources.refresh)
        await asyncio.sleep(60)  # Back off after a failed refresh instead of spinning.


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    jobs.recover()
    # INTERN_BOARD_NO_REFRESH=1 skips the hourly fetch (for extra dev servers sharing the database).
    task = None if os.environ.get("INTERN_BOARD_NO_REFRESH") else asyncio.create_task(refresh_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="Intern Board", lifespan=lifespan)
for feature in (profile, ranking, documents, people, contacts):
    app.include_router(feature.router)


@app.middleware("http")
async def revalidate_static(request, call_next):
    """Make the browser check for updated HTML/JS/CSS on every load instead of using a stale copy."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _listing_filters(q, region, category, term, degree, since, hide_tracked, source=""):
    where, args = [db.visible("l")], []
    if source:
        where.append("l.source = ?")
        args.append(source)
    for word in q.split():
        where.append("(l.title LIKE ? OR l.company LIKE ? OR l.locations LIKE ?)")
        args += [f"%{word}%"] * 3
    if region:
        where.append("l.regions LIKE ?")
        args.append(f"%,{region},%")
    if category:
        where.append("l.category = ?")
        args.append(category)
    if term:
        where.append("l.terms LIKE ?")
        args.append(f"%,{term},%")
    if degree:
        where.append("l.degrees LIKE ?")
        args.append(f"%,{degree},%")
    if since:
        where.append("l.first_seen > ?")
        args.append(since)
    if hide_tracked:
        where.append("t.listing_id IS NULL")
    return " AND ".join(where), args


@app.get("/api/listings")
def listings(
    q: str = "",
    region: Literal["", "US", "CA", "REMOTE"] = "",
    category: str = "",
    term: str = "",
    degree: str = "",
    since: int = 0,
    hide_tracked: bool = False,
    source: Literal["", "simplify", "board", "negarprh", "michelleokolie", "zapply"] = "",
    sort: Literal["posted", "added", "company", "match"] = "posted",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    where, args = _listing_filters(q, region, category, term, degree, since, hide_tracked, source)
    order = {"posted": "l.date_posted DESC", "added": "l.first_seen DESC, l.date_posted DESC",
             "company": "l.company COLLATE NOCASE, l.date_posted DESC",
             "match": "m.score IS NULL, m.score DESC, l.date_posted DESC"}[sort]
    # Only scores made against the current profile count.
    base = ("FROM listings l LEFT JOIN tracker t ON t.listing_id = l.id "
            "LEFT JOIN matches m ON m.listing_id = l.id "
            "AND m.profile_version = (SELECT version FROM profile WHERE id = 1) "
            f"WHERE {where}")
    with db.connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
        rows = conn.execute(f"SELECT l.*, t.status AS tracked_status, m.score AS match_score, "
                            f"m.reason AS match_reason, m.method AS match_method {base} ORDER BY {order} "
                            "LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    return {"total": total, "items": [_listing(r) for r in rows]}


def _listing(row) -> dict:
    d = dict(row)
    for key in ("regions", "terms", "degrees"):
        d[key] = [v for v in d[key].split(",") if v]
    return d


@app.get("/api/meta")
def meta():
    with db.connect() as conn:
        def counts(sql):
            return [{"value": r[0], "count": r[1]} for r in conn.execute(sql)]
        return {
            "last_refresh": int(db.get_meta(conn, "last_refresh") or 0),
            "last_error": db.get_meta(conn, "last_error") or "",
            "active": conn.execute(f"SELECT COUNT(*) FROM listings WHERE {db.visible()}").fetchone()[0],
            "regions": counts("SELECT r, COUNT(*) FROM (SELECT 'US' r UNION ALL SELECT 'CA' UNION ALL "
                              f"SELECT 'REMOTE') JOIN listings ON {db.visible()} AND regions LIKE '%,' || r || ',%' "
                              "GROUP BY r"),
            "categories": counts(f"SELECT category, COUNT(*) FROM listings WHERE {db.visible()} "
                                 "GROUP BY category ORDER BY 2 DESC"),
            "terms": counts(_split_counts("terms")),
            "degrees": counts(_split_counts("degrees")),
            "sources": counts(f"SELECT source, COUNT(*) FROM listings WHERE {db.visible()} GROUP BY source"),
            "boards": dict(conn.execute(
                "SELECT COUNT(*) AS total, SUM(enabled) AS enabled, "
                "SUM(enabled AND interns > 0) AS hiring FROM companies").fetchone()),
        }


def _split_counts(column: str) -> str:
    # Unnest the ",a,b," columns with a recursive CTE.
    return f"""
        WITH RECURSIVE split(value, rest) AS (
            SELECT '', substr({column}, 2) FROM listings WHERE {db.visible()}
            UNION ALL
            SELECT substr(rest, 1, instr(rest, ',') - 1), substr(rest, instr(rest, ',') + 1)
            FROM split WHERE rest <> ''
        )
        SELECT value, COUNT(*) FROM split WHERE value <> '' GROUP BY value ORDER BY 2 DESC
    """


@app.post("/api/refresh")
async def refresh():
    return await run_in_threadpool(sources.refresh)


class TrackerUpdate(BaseModel):
    status: Literal[STATUSES] | None = None
    notes: str | None = Field(None, max_length=20_000)
    deadline: str | None = Field(None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    position: float | None = None


@app.get("/api/tracker")
def tracker():
    with db.connect() as conn:
        rows = conn.execute("""
            SELECT t.*, l.company, l.title, l.url, l.locations, l.active, l.date_posted, l.terms,
                   l.regions, l.degrees, l.category, l.sponsorship, l.first_seen, l.id
            FROM tracker t JOIN listings l ON l.id = t.listing_id
            ORDER BY t.status, t.position, t.updated_at DESC
        """).fetchall()
    return {"statuses": STATUSES, "items": [_listing(r) for r in rows]}


@app.put("/api/tracker/{listing_id:path}")
def track(listing_id: str, update: TrackerUpdate):
    now = int(time.time())
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM listings WHERE id = ?", (listing_id,)).fetchone():
            raise HTTPException(404, "Unknown listing")
        conn.execute("INSERT INTO tracker (listing_id, status, updated_at) VALUES (?, ?, ?) "
                     "ON CONFLICT (listing_id) DO NOTHING", (listing_id, update.status or "saved", now))
        fields = update.model_dump(exclude_none=True)
        if "deadline" in fields and fields["deadline"] == "":
            fields["deadline"] = None
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE tracker SET {sets + ', ' if sets else ''}updated_at = ? WHERE listing_id = ?",
                     [*fields.values(), now, listing_id])
    return {"ok": True}


@app.delete("/api/tracker/{listing_id:path}")
def untrack(listing_id: str):
    with db.connect() as conn:
        conn.execute("DELETE FROM tracker WHERE listing_id = ?", (listing_id,))
    return {"ok": True}


@app.get("/api/companies")
def companies():
    with db.connect() as conn:
        rows = conn.execute(f"""
            SELECT c.*, COUNT(l.id) AS listings
            FROM companies c
            LEFT JOIN listings l ON l.board = c.platform || ':' || c.token AND {db.visible("l")}
            GROUP BY c.platform, c.token
            ORDER BY c.enabled DESC, listings DESC, c.name COLLATE NOCASE
        """).fetchall()
    return {"items": [{**dict(r), "board_url": ats.BOARD_PAGES[r["platform"]].format(token=r["token"])}
                      for r in rows]}


class NewCompany(BaseModel):
    url: str = Field(min_length=3, max_length=500)
    name: str | None = Field(None, max_length=120)


@app.post("/api/companies")
def add_company(body: NewCompany):
    board = ats.parse_board_url(body.url.strip())
    if not board:
        raise HTTPException(422, "Paste a Greenhouse, Lever or Ashby link, like jobs.lever.co/company.")
    try:
        with db.connect() as conn:
            return sources.add_board(conn, *board, body.name)
    except ats.BoardNotFound:
        raise HTTPException(404, f"No {board[0].title()} job board called “{board[1]}” exists.")
    except OSError as exc:
        raise HTTPException(502, f"Couldn't reach {board[0].title()}: {exc}")


class CompanyUpdate(BaseModel):
    enabled: bool


@app.patch("/api/companies/{platform}/{token}")
def update_company(platform: str, token: str, body: CompanyUpdate):
    with db.connect() as conn:
        # Re-enabled boards are checked on the next refresh, without flooding "new".
        cur = conn.execute("UPDATE companies SET enabled = ?, "
                           "last_checked = CASE WHEN ? THEN NULL ELSE last_checked END "
                           "WHERE platform = ? AND token = ?", (body.enabled, body.enabled, platform, token))
        if not cur.rowcount:
            raise HTTPException(404, "Unknown company")
        if not body.enabled:
            conn.execute("UPDATE listings SET active = 0 WHERE board = ?", (f"{platform}:{token}",))
    return {"ok": True}


# ---------- AI jobs ----------

class JobRequest(BaseModel):
    kind: str
    payload: dict = {}


@app.post("/api/ai/jobs")
def start_job(body: JobRequest):
    try:
        return {"job_id": jobs.submit(body.kind, body.payload)}
    except KeyError:
        raise HTTPException(404, f"Unknown job kind: {body.kind}")


@app.get("/api/ai/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return job


class PastedDescription(BaseModel):
    text: str = Field(min_length=50, max_length=50_000)


@app.put("/api/listings/{listing_id:path}/description")
def paste_description(listing_id: str, body: PastedDescription):
    """Save a job description you pasted, for postings Claude can't open."""
    postings.save(listing_id, body.text)
    return {"ok": True}


@jobs.handler("fetch_description")
def fetch_description(payload: dict) -> dict:
    return postings.description(payload["listing_id"], refresh=bool(payload.get("refresh")))


@app.get("/api/ai/status")
def ai_status():
    return {"claude": bool(ai.claude_path()), "kinds": sorted(jobs.HANDLERS)}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
