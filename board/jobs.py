"""Background AI jobs. Claude calls take 10-60s, so the browser starts a job and polls for it.

Features register a handler per job kind:

    @jobs.handler("cover_letter")
    def cover_letter(payload: dict) -> dict: ...

A handler gets the JSON payload the browser sent and returns a JSON-serialisable result.
Raise ai.AIError (or ValueError) with a message the user should see.
"""

import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from . import ai, db

log = logging.getLogger(__name__)

HANDLERS: dict[str, Callable[[dict], dict]] = {}
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-job")


def handler(kind: str):
    def register(fn):
        HANDLERS[kind] = fn
        return fn
    return register


def submit(kind: str, payload: dict) -> str:
    if kind not in HANDLERS:
        raise KeyError(kind)
    job_id = uuid.uuid4().hex[:12]
    with db.connect() as conn:
        conn.execute("INSERT INTO ai_jobs (id, kind, listing_id, payload, status, created_at) "
                     "VALUES (?, ?, ?, ?, 'queued', ?)",
                     (job_id, kind, payload.get("listing_id"), json.dumps(payload), int(time.time())))
    _pool.submit(_run, job_id, kind, payload)
    return job_id


def _run(job_id: str, kind: str, payload: dict) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE ai_jobs SET status = 'running', started_at = ? WHERE id = ?", (int(time.time()), job_id))
    try:
        result, error, status = HANDLERS[kind](payload), None, "done"
    except (ai.AIError, ValueError) as exc:
        result, error, status = None, str(exc), "error"
    except Exception as exc:  # a bug: log it, but still tell the browser
        log.exception("job %s (%s) failed", job_id, kind)
        result, error, status = None, f"Unexpected error: {type(exc).__name__}: {exc}", "error"
    with db.connect() as conn:
        conn.execute("UPDATE ai_jobs SET status = ?, result = ?, error = ?, finished_at = ? WHERE id = ?",
                     (status, json.dumps(result) if result is not None else None, error, int(time.time()), job_id))


def get(job_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM ai_jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    job = dict(row)
    job["payload"] = json.loads(job["payload"] or "{}")
    job["result"] = json.loads(job["result"]) if job["result"] else None
    return job


def recover() -> None:
    """Mark jobs failed that a stopped server left unfinished.

    Several servers can share the database (e.g. dev servers), so only jobs older than any call
    could take are touched; a younger one may still be running in another process.
    """
    stale = int(time.time()) - (ai.DEFAULT_TIMEOUT * 2 + 120)
    with db.connect() as conn:
        conn.execute("UPDATE ai_jobs SET status = 'error', error = 'The app restarted before this finished.' "
                     "WHERE status IN ('queued', 'running') AND created_at < ?", (stale,))
