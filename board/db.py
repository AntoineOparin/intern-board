import sqlite3
from pathlib import Path

from .locations import fold

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "board.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id           TEXT PRIMARY KEY,   -- "<source>:<source id>"
    source       TEXT NOT NULL,
    company      TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    locations    TEXT NOT NULL,      -- " / "-joined, US/Canada/remote entries only
    regions      TEXT NOT NULL,      -- e.g. ",US,CA,REMOTE,"
    category     TEXT,
    terms        TEXT NOT NULL,      -- e.g. ",Summer 2027,Fall 2026,"
    degrees      TEXT NOT NULL,      -- e.g. ",Bachelor's,Master's,"
    sponsorship  TEXT,
    date_posted  INTEGER,
    first_seen   INTEGER NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS listings_posted ON listings (active, date_posted DESC);

CREATE TABLE IF NOT EXISTS tracker (
    listing_id   TEXT PRIMARY KEY REFERENCES listings (id),
    status       TEXT NOT NULL,
    notes        TEXT NOT NULL DEFAULT '',
    deadline     TEXT,               -- YYYY-MM-DD
    position     REAL NOT NULL DEFAULT 0,
    updated_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Company job boards read directly (board/ats.py lists the platforms).
CREATE TABLE IF NOT EXISTS companies (
    platform      TEXT NOT NULL,
    token         TEXT NOT NULL,
    name          TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    origin        TEXT NOT NULL,     -- 'auto' (found in a community list or board/montreal.py) or 'manual'
    added_at      INTEGER NOT NULL,
    last_checked  INTEGER,
    last_status   TEXT,              -- 'ok', 'not_found', 'error'
    last_error    TEXT,
    jobs_total    INTEGER,           -- every posting on the board
    PRIMARY KEY (platform, token)
);

-- Your resume and the profile Claude extracts from it (one row, id = 1).
CREATE TABLE IF NOT EXISTS profile (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    resume_filename  TEXT,
    resume_text      TEXT,
    data             TEXT NOT NULL DEFAULT '{}',  -- JSON, see board/profile.py PROFILE_SCHEMA
    preferences      TEXT NOT NULL DEFAULT '{}',  -- JSON, set by you on the Profile tab
    version          INTEGER NOT NULL DEFAULT 0,  -- bumped on every change; caches key on it
    updated_at       INTEGER
);

-- Background Claude calls (board/jobs.py).
CREATE TABLE IF NOT EXISTS ai_jobs (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    listing_id   TEXT,
    payload      TEXT,
    status       TEXT NOT NULL,      -- queued, running, done, error
    result       TEXT,               -- JSON
    error        TEXT,
    created_at   INTEGER NOT NULL,
    started_at   INTEGER,
    finished_at  INTEGER
);

-- How well each listing fits your profile (filled by board/ranking.py).
CREATE TABLE IF NOT EXISTS matches (
    listing_id       TEXT PRIMARY KEY REFERENCES listings (id),
    score            INTEGER NOT NULL,   -- 0-100
    reason           TEXT,
    method           TEXT NOT NULL,      -- 'quick' (keyword scoring) or 'claude'
    profile_version  INTEGER NOT NULL,
    scored_at        INTEGER NOT NULL
);

-- Generated documents: tailored resumes, cover letters, outreach drafts.
CREATE TABLE IF NOT EXISTS documents (
    id               TEXT PRIMARY KEY,
    listing_id       TEXT REFERENCES listings (id),
    kind             TEXT NOT NULL,      -- 'resume', 'cover_letter', 'outreach'
    title            TEXT,
    content          TEXT NOT NULL,      -- JSON; shape depends on kind
    profile_version  INTEGER,
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS documents_listing ON documents (listing_id, kind);

-- Find People (board/people.py): each company's website (Prospeo searches by domain) ...
CREATE TABLE IF NOT EXISTS company_sites (
    company       TEXT PRIMARY KEY,     -- people.company_key(listing company)
    domain        TEXT NOT NULL,        -- root domain, e.g. "ea.com"
    source        TEXT NOT NULL,        -- 'url' (careers site), 'claude', or 'user'
    prospeo_name  TEXT,                 -- the company's name in Prospeo, once a search found it
    logo_url      TEXT,
    updated_at    INTEGER NOT NULL
);

-- ... the people found for a listing, and when each search ran.
CREATE TABLE IF NOT EXISTS contacts (
    listing_id    TEXT NOT NULL REFERENCES listings (id),
    kind          TEXT NOT NULL,        -- 'recruiters' or 'team'
    person_id     TEXT NOT NULL,        -- Prospeo person_id
    rank          INTEGER NOT NULL,
    full_name     TEXT NOT NULL,
    title         TEXT,
    city          TEXT,
    state         TEXT,
    country       TEXT,
    linkedin_url  TEXT,
    email         TEXT,                 -- only after you reveal it (1 credit)
    email_status  TEXT,                 -- Prospeo's status, e.g. VERIFIED / UNAVAILABLE
    found_at      INTEGER NOT NULL,
    PRIMARY KEY (listing_id, kind, person_id)
);
CREATE TABLE IF NOT EXISTS people_searches (
    listing_id    TEXT NOT NULL,
    kind          TEXT NOT NULL,
    domain        TEXT NOT NULL,
    total         INTEGER NOT NULL,     -- matches Prospeo reported (we keep the best page)
    country_filtered INTEGER NOT NULL,  -- 1 if limited to the job's country
    searched_at   INTEGER NOT NULL,
    PRIMARY KEY (listing_id, kind)
);

-- Full job descriptions (board/postings.py).
CREATE TABLE IF NOT EXISTS posting_details (
    listing_id  TEXT PRIMARY KEY REFERENCES listings (id),
    text        TEXT NOT NULL,
    source      TEXT NOT NULL,       -- 'api', 'claude' (WebFetch) or 'pasted' (by you)
    fetched_at  INTEGER NOT NULL
);
"""

# Columns added after the first release; added in place on existing databases.
MIGRATIONS = {
    "listings": {
        "posting_key": "TEXT",  # e.g. "gh:12345": the same job from two sources shares it
        "board": "TEXT",        # "<platform>:<token>" for listings read from a company board
        # What the posting itself says about US visa sponsorship (board/visa.py), in the same words
        # as `sponsorship`; NULL if it says nothing. `sponsorship` is the source list's own field.
        "visa": "TEXT",
        "visa_quote": "TEXT",   # the sentence it came from
        "visa_checked": "INTEGER",  # when the posting was read; NULL = not yet
    },
    "companies": {
        "interns": "INTEGER",   # matching internships found on the last successful check
    },
    "contacts": {
        "source": "TEXT NOT NULL DEFAULT 'prospeo'",  # or 'manual' (added by you)
        "email_found_at": "INTEGER",   # when the email was revealed or last re-checked
        "job_change_at": "INTEGER",    # Prospeo's last detected job change, at search time
        "moved_to": "TEXT",            # set by a re-check that finds them at another company
    },
}


# Listings older than this are hidden from the board (tracked ones stay in the tracker).
MAX_AGE_DAYS = 30


def visible(alias: str = "") -> str:
    """SQL condition for listings shown on the board: open, and posted within MAX_AGE_DAYS."""
    a = f"{alias}." if alias else ""
    return (f"{a}active = 1 AND ({a}date_posted IS NULL OR "
            f"{a}date_posted >= CAST(strftime('%s', 'now') AS INTEGER) - {MAX_AGE_DAYS * 86400})")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # fold(text): lower case without accents, so a search for "montreal" finds "Montréal".
    conn.create_function("fold", 1, lambda t: fold(t) if t else t, deterministic=True)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        for table, columns in MIGRATIONS.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns.items():
                if name not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        conn.execute("CREATE INDEX IF NOT EXISTS listings_board ON listings (board)")
        conn.execute("CREATE INDEX IF NOT EXISTS listings_posting_key ON listings (posting_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS listings_visa_pending ON listings (visa_checked, active)")
        conn.execute("UPDATE contacts SET email_found_at = found_at WHERE email IS NOT NULL AND email_found_at IS NULL")
        # Older versions dated late-discovered postings by discovery time; date them by posting.
        if not get_meta(conn, "fix_first_seen_v1"):
            conn.execute("UPDATE listings SET first_seen = date_posted "
                         "WHERE date_posted IS NOT NULL AND first_seen - date_posted > 2 * 86400 "
                         "AND first_seen > (SELECT MIN(first_seen) FROM listings WHERE source = 'simplify')")
            set_meta(conn, "fix_first_seen_v1", "1")
        if not get_meta(conn, "fix_first_seen_v2"):
            # The very first import dated everything by import time; apply the same rule to it.
            conn.execute("UPDATE listings SET first_seen = date_posted "
                         "WHERE date_posted IS NOT NULL AND first_seen - date_posted > 2 * 86400")
            set_meta(conn, "fix_first_seen_v2", "1")


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))
