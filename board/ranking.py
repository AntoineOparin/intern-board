"""Rank listings against your profile.

Two kinds of score live in the `matches` table, keyed on the profile version they were made for:
- 'quick': a deterministic keyword score for every active listing, computed in about a second.
- 'claude': Claude's judgement for the top listings, made on request by the `rank_listings` job.
A quick score never replaces a Claude score made for the same profile version.
"""

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from . import ai, db, jobs, profile

log = logging.getLogger(__name__)
router = APIRouter()

NO_PROFILE = "Add your resume on the Profile tab first."
BATCH_SIZE = 20
MAX_LIMIT = 100
_quick_lock = threading.Lock()

# ---------- quick scores ----------

CATEGORIES = ("Software", "AI/ML/Data", "Hardware", "Product", "Quant")
# Words in a profile that suggest interest in a category, used only when no categories are chosen.
CATEGORY_HINTS = {
    "Software": ["software", "developer", "backend", "frontend", "full stack", "full-stack", "web", "api",
                 "python", "java", "javascript", "typescript", "react", "node", "fastapi", "django", "go",
                 "rust", "postgres", "docker", "computer science", "computer engineering", "software engineering"],
    "AI/ML/Data": ["machine learning", "ml", "ai", "data", "pytorch", "tensorflow", "pandas", "nlp",
                   "computer vision", "llm", "statistics", "analytics", "deep learning", "data science"],
    "Hardware": ["hardware", "verilog", "systemverilog", "vhdl", "fpga", "asic", "rtl", "firmware", "embedded",
                 "cpu", "circuit", "pcb", "electrical", "computer engineering", "risc-v"],
    "Product": ["product manager", "product management", "product", "ux", "design"],
    "Quant": ["quant", "quantitative", "trading", "finance", "probability", "stochastic"],
}
REGION_LABELS = {"US": "US", "CA": "Canada", "REMOTE": "Remote"}
SEASON_START = {"Winter": 1, "Spring": 5, "Summer": 5, "Fall": 9}
DEGREE_RANK = {"Associate's": 1, "Bachelor's": 2, "Master's": 3, "MBA": 3, "PhD": 4}
# Title words that are too generic to count as a role match on their own.
TITLE_DEGREE = re.compile(r"\b(ph\.?d|doctoral|mba|master'?s|graduate)\b", re.IGNORECASE)
GENERIC_WORDS = {"intern", "internship", "co-op", "coop", "student", "engineer", "engineering", "and", "the",
                 "of", "for", "in", "with", "a", "an", "to", "summer", "fall", "winter", "spring", "volunteer",
                 "assistant", "teaching", "research", "junior", "new", "grad"}


def _norm_skill(s: str) -> str:
    """'AWS (EC2, S3)' -> 'AWS'; 'Node.js' stays."""
    return re.sub(r"\s*\(.*?\)", "", s or "").strip()


def _term_regex(word: str) -> re.Pattern:
    # Word boundaries that also work for C++, C#, .NET, Node.js; short words like "Go" must match case.
    flags = 0 if len(word) <= 2 else re.IGNORECASE
    return re.compile(rf"(?<![\w+#.]){re.escape(word)}(?![\w+#])", flags)


def degree_level(p: dict) -> str:
    level = (p["preferences"].get("degree_level") or "").strip()
    if level:
        return level
    for edu in p["data"].get("education") or []:
        d = (edu.get("degree") or "").lower()
        if re.search(r"ph\.?d|doctor", d):
            return "PhD"
        if re.search(r"\bmba\b", d):
            return "MBA"
        if re.search(r"master|\bm\.?s\.?c?\b|\bm\.?eng|\bmasc\b", d):
            return "Master's"
        if re.search(r"bachelor|\bb\.?s\.?c?\b|\bb\.?a\.?s\.?c\b|\bbasc\b|\bb\.?eng|\bb\.?a\.?\b|\bbsc\b", d):
            return "Bachelor's"
        if "associate" in d:
            return "Associate's"
    return ""


def _term_started(term: str, now: datetime) -> bool:
    m = re.match(r"(Winter|Spring|Summer|Fall)\s+(\d{4})", term)
    if not m:
        return False
    return (int(m.group(2)), SEASON_START[m.group(1)]) <= (now.year, now.month)


class Scorer:
    """Precomputes everything that depends only on the profile, then scores listings quickly."""

    def __init__(self, p: dict, now: float | None = None):
        data, prefs = p["data"], p["preferences"]
        self.now = now or time.time()
        self.today = datetime.fromtimestamp(self.now, timezone.utc)
        skills = data.get("skills") or {}
        names, seen = [], set()
        for group in ("languages", "frameworks", "tools", "other"):
            for s in skills.get(group) or []:
                s = _norm_skill(s)
                if s and s.lower() not in seen and len(s) <= 30:
                    seen.add(s.lower())
                    names.append(s)
        for proj in data.get("projects") or []:
            for s in proj.get("tech") or []:
                s = _norm_skill(s)
                if s and s.lower() not in seen and len(s) <= 30:
                    seen.add(s.lower())
                    names.append(s)
        self.skills = [(s, _term_regex(s)) for s in names]

        # Target roles: each phrase as a whole, plus its distinctive words.
        self.roles = []
        for role in prefs.get("target_roles") or []:
            role = role.strip()
            if role:
                words = [w for w in re.findall(r"[\w+#/-]+", role.lower()) if w not in GENERIC_WORDS and len(w) > 1]
                self.roles.append((role, _term_regex(role), [_term_regex(w) for w in words]))
        # Without target roles, the roles you've held hint at what fits (e.g. "Software Developer").
        self.past_role_words = []
        if not self.roles:
            words = set()
            for exp in data.get("experience") or []:
                words |= {w for w in re.findall(r"[a-z][\w+#-]*", (exp.get("role") or "").lower())
                          if w not in GENERIC_WORDS and len(w) > 2}
            self.past_role_words = [(w, _term_regex(w)) for w in sorted(words)]

        self.pref_categories = [c for c in prefs.get("categories") or [] if c in CATEGORIES]
        self.inferred_categories = []
        if not self.pref_categories:
            text = " ".join([*names, *(e.get("role", "") for e in data.get("experience") or []),
                             *(e.get("field", "") for e in data.get("education") or []),
                             data.get("summary", "")]).lower()
            hits = {c: sum(1 for w in ws if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text))
                    for c, ws in CATEGORY_HINTS.items()}
            self.inferred_categories = [c for c, n in hits.items() if n >= 2]
        self.regions = [r for r in prefs.get("regions") or [] if r in REGION_LABELS]
        self.terms = list(prefs.get("terms") or [])
        self.degree = degree_level(p)

    def score(self, row) -> tuple[int, str]:
        title = row["title"] or ""
        regions = [r for r in (row["regions"] or "").split(",") if r]
        terms = [t for t in (row["terms"] or "").split(",") if t]
        degrees = [d for d in (row["degrees"] or "").split(",") if d]
        category = row["category"]
        score, good, bad = 40, [], []

        # Title: skills and roles.
        skill_hits = [s for s, rx in self.skills if rx.search(title)]
        if skill_hits:
            score += min(24, 12 * len(skill_hits))
        role_hit = None
        for role, rx, word_rxs in self.roles:
            if rx.search(title):
                role_hit, score = role, score + 18
                break
            if word_rxs and any(w.search(title) for w in word_rxs):
                role_hit, score = role, score + 10
                break
        past = [w for w, rx in self.past_role_words if rx.search(title)] if not self.roles else []
        if past:
            score += 6
        if skill_hits:
            good.append("Matches " + ", ".join(skill_hits[:3]))
        if role_hit:
            good.append(f"{role_hit} role")
        elif past and not skill_hits:
            good.append(f"{past[0].capitalize()} title like your past roles")

        # Category.
        if self.pref_categories:
            if category in self.pref_categories:
                score += 12
                if not skill_hits and not role_hit:
                    good.append(category)
            elif category:
                score -= 15
                bad.append(f"{category} isn't a chosen category")
        elif self.inferred_categories and category:
            if category in self.inferred_categories:
                score += 8
                if not good:
                    good.append(f"{category}, close to your background")
            else:
                score -= 6

        # Region.
        if self.regions and regions:
            overlap = [r for r in regions if r in self.regions]
            if overlap:
                score += 8
                good.append(" or ".join(REGION_LABELS[r] for r in overlap))
            else:
                score -= 15
                bad.append("Outside your regions")

        # Term.
        if terms:
            wanted = [t for t in terms if t in self.terms]
            upcoming = [t for t in terms if not _term_started(t, self.today)]
            if self.terms and wanted:
                score += 10
                good.append(", ".join(wanted[:2]))
            elif self.terms:
                score -= 10
                bad.append(f"{terms[0]} isn't a chosen term")
            elif not upcoming:
                score -= 15
                bad.append(f"{terms[-1]} has already started")
            else:
                score += 3
                good.append(", ".join(upcoming[:2]))

        # Degree.
        if self.degree and degrees:
            if self.degree in degrees:
                score += 4
            else:
                mine = DEGREE_RANK.get(self.degree, 0)
                if mine and all(DEGREE_RANK.get(d, 0) > mine for d in degrees):
                    score -= 25
                    bad.append(" or ".join(sorted(set(degrees), key=lambda d: DEGREE_RANK.get(d, 0))) + " only")
                elif mine and all(DEGREE_RANK.get(d, 0) < mine for d in degrees):
                    score -= 8

        # Degree named in the title, e.g. "PhD Research Intern" or "MBA Product Intern".
        mine = DEGREE_RANK.get(self.degree, 0)
        m = TITLE_DEGREE.search(title)
        if mine and m and self.degree not in degrees:
            asked = "PhD" if m.group(0).lower().startswith(("ph", "doct")) else (
                "MBA" if m.group(0).upper() == "MBA" else "Master's")
            if DEGREE_RANK[asked] > mine and not any(asked in b for b in bad):
                score -= 15
                bad.append(f"Title asks for {asked} students")

        # Recency.
        posted = row["date_posted"]
        if posted:
            age = (self.now - posted) / 86400
            if age <= 7:
                score += 5
            elif age <= 30:
                score += 3
            elif age > 120:
                score -= 5

        reason = "; ".join([*good, *bad][:4]) or "No keyword overlap with your profile"
        return max(0, min(100, score)), reason


_UPSERT = (
    "INSERT INTO matches (listing_id, score, reason, method, profile_version, scored_at) VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT (listing_id) DO UPDATE SET score = excluded.score, reason = excluded.reason, "
    "method = excluded.method, profile_version = excluded.profile_version, scored_at = excluded.scored_at "
    # Never go back to an older profile version, and never replace Claude's score with a quick one.
    "WHERE excluded.profile_version >= matches.profile_version AND NOT ("
    "  excluded.method = 'quick' AND matches.method = 'claude' "
    "  AND matches.profile_version = excluded.profile_version)")


def compute_quick(conn, p: dict | None = None, only_missing: bool = False) -> int:
    """Score active listings by keywords and store them. Returns how many rows were written."""
    p = p or profile.load(conn)
    if not p["data"]:
        return 0
    with _quick_lock:
        scorer = Scorer(p)
        sql = "SELECT l.id, l.title, l.category, l.terms, l.regions, l.degrees, l.date_posted FROM listings l"
        args = []
        if only_missing:
            sql += " LEFT JOIN matches m ON m.listing_id = l.id AND m.profile_version = ? WHERE m.listing_id IS NULL AND"
            args.append(p["version"])
        else:
            sql += " WHERE"
        rows = conn.execute(sql + " l.active = 1", args).fetchall()
        if not rows:
            return 0
        now = int(time.time())
        params = []
        for r in rows:
            score, reason = scorer.score(r)
            params.append((r["id"], score, reason, "quick", p["version"], now))
        with conn:
            conn.executemany(_UPSERT, params)
        return len(params)


def status(conn, ensure: bool = True) -> dict:
    p = profile.load(conn)
    has_profile = bool(p["data"])
    computed = 0
    if has_profile and ensure:
        computed = compute_quick(conn, p, only_missing=True)
    counts = {r["method"]: dict(r) for r in conn.execute(
        "SELECT m.method, COUNT(*) AS n, MAX(m.scored_at) AS at FROM matches m "
        "JOIN listings l ON l.id = m.listing_id AND l.active = 1 "
        "WHERE m.profile_version = ? GROUP BY m.method", (p["version"],))}
    active = conn.execute("SELECT COUNT(*) FROM listings WHERE active = 1").fetchone()[0]
    quick, claude = counts.get("quick", {}), counts.get("claude", {})
    return {
        "has_profile": has_profile,
        "profile_version": p["version"],
        "active": active,
        "quick": quick.get("n", 0), "quick_at": quick.get("at"),
        "claude": claude.get("n", 0), "claude_at": claude.get("at"),
        "unscored": active - quick.get("n", 0) - claude.get("n", 0),
        "computed": computed,
        "running_job": _running_job(conn),
    }


def _running_job(conn) -> str | None:
    row = conn.execute("SELECT id FROM ai_jobs WHERE kind = 'rank_listings' AND status IN ('queued', 'running') "
                       "ORDER BY created_at DESC LIMIT 1").fetchone()
    return row["id"] if row else None


# ---------- Claude ranking ----------

RANK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["results"],
    "properties": {"results": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "score", "reason"],
        "properties": {
            "id": {"type": "integer", "description": "The listing's id from the list you were given."},
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "reason": {"type": "string", "description": "One specific sentence, under 25 words."},
        }}}},
}

RANK_SYSTEM = """\
You judge how well internship listings fit one candidate, for a personal job board.
You see only each listing's title and metadata (company, locations, category, terms, degrees,
sponsorship), never the full description. Judge only from what you can see: don't assume the
tech stack, responsibilities, seniority or requirements beyond what the title and metadata say.
If the title is vague, say the fit is unclear rather than guessing. Don't guess at employer policies
(security clearance, citizenship), the candidate's school schedule, or where past jobs were.

Scoring: 85-100 the title clearly lines up with the candidate's experience, skills or stated
targets and nothing visible rules them out; 60-84 a reasonable fit; 35-59 a stretch or unclear;
0-34 a poor fit or something visible rules them out (degree level, term already started or not
wanted, region, a field far from their background). Use the whole range.

Each reason is one specific sentence under 25 words that names a concrete fact from the candidate
(a past role, project, skill, degree or preference) and a concrete fact from the listing, or the
visible mismatch. Never write generic praise like "great fit" or "exciting opportunity".
Example: "Backend role using Python like your Northwind co-op; Summer 2027 matches your timing."
Score every listing you are given, using its id exactly."""


def _candidates(conn, p: dict, limit: int, region: str = "", category: str = "") -> list:
    where, args = ["l.active = 1", "m.method <> 'claude'"], [p["version"]]
    if region:
        where.append("l.regions LIKE ?")
        args.append(f"%,{region},%")
    if category:
        where.append("l.category = ?")
        args.append(category)
    return conn.execute(
        "SELECT l.id, l.company, l.title, l.locations, l.category, l.terms, l.degrees, l.sponsorship, m.score "
        "FROM listings l JOIN matches m ON m.listing_id = l.id AND m.profile_version = ? "
        f"WHERE {' AND '.join(where)} ORDER BY m.score DESC, l.date_posted DESC LIMIT ?",
        [*args, limit]).fetchall()


def _compact(i: int, r) -> str:
    parts = [f"id={i}", f"{r['company']} | {r['title']}", f"locations: {r['locations'] or 'unknown'}"]
    if r["category"]:
        parts.append(f"category: {r['category']}")
    terms = r["terms"].strip(",").replace(",", ", ")
    degrees = r["degrees"].strip(",").replace(",", ", ")
    parts.append(f"terms: {terms or 'not listed'}")
    if degrees:
        parts.append(f"degrees: {degrees}")
    if r["sponsorship"] and r["sponsorship"] != "Other":
        parts.append(f"sponsorship: {r['sponsorship']}")
    return " | ".join(parts)


def _rank_batch(p: dict, batch: list, today: str) -> list[tuple]:
    """One Claude call for a batch. Returns [(listing_id, score, reason)] for valid answers only."""
    by_id = {i: r for i, r in enumerate(batch, 1)}
    prompt = (f"Today is {today}.\n\n{profile.as_prompt_text(p)}\n\n"
              f"LISTINGS ({len(batch)}):\n" + "\n".join(_compact(i, r) for i, r in by_id.items()))
    out = ai.ask(prompt, system=RANK_SYSTEM, schema=RANK_SCHEMA, model="sonnet")
    results, seen = [], set()
    for item in (out or {}).get("results") or []:
        if not isinstance(item, dict):
            continue
        try:
            i, score = int(item.get("id")), int(item.get("score"))
        except (TypeError, ValueError):
            continue
        reason = " ".join(str(item.get("reason") or "").split())[:300]
        if i not in by_id or i in seen or not reason:
            continue
        seen.add(i)
        results.append((by_id[i]["id"], max(0, min(100, score)), reason))
    return results


@jobs.handler("rank_listings")
def rank_listings(payload: dict) -> dict:
    try:
        limit = max(1, min(MAX_LIMIT, int(payload.get("limit") or 40)))
    except (TypeError, ValueError):
        raise ValueError("The limit must be a number.")
    region = payload.get("region") or ""
    category = payload.get("category") or ""
    if region and region not in REGION_LABELS:
        raise ValueError(f"Unknown region: {region}")
    started = time.time()
    with db.connect() as conn:
        p = profile.require(conn)
        compute_quick(conn, p, only_missing=True)
        rows = _candidates(conn, p, limit, region, category)
    if not rows:
        return {"ranked": 0, "requested": 0, "skipped": 0, "batches": 0, "seconds": 0,
                "message": "Every listing in this selection already has a Claude score."}

    batches = [rows[i:i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]
    today = datetime.now().strftime("%B %-d, %Y")
    ranked, errors = 0, []

    def run(batch):
        return _rank_batch(p, batch, today)

    with ThreadPoolExecutor(max_workers=2) as pool:
        for batch, fut in [(b, pool.submit(run, b)) for b in batches]:
            try:
                results = fut.result()
            except ai.AIError as exc:
                errors.append(str(exc))
                continue
            now = int(time.time())
            with db.connect() as conn:
                conn.executemany(_UPSERT, [(lid, s, why, "claude", p["version"], now) for lid, s, why in results])
            ranked += len(results)
    if errors and not ranked:
        raise ai.AIError(errors[0])
    return {"ranked": ranked, "requested": len(rows), "skipped": len(rows) - ranked, "batches": len(batches),
            "failed_batches": len(errors), "error": errors[0] if errors else None,
            "seconds": round(time.time() - started, 1)}


# ---------- API ----------

@router.get("/api/ranking/status")
def get_status():
    """Counts for the current profile version. Fills in quick scores for any unscored listings first."""
    with db.connect() as conn:
        return status(conn)


@router.post("/api/ranking/quick")
def recompute_quick():
    """Recompute every quick score (Claude scores for this profile version are kept)."""
    started = time.time()
    with db.connect() as conn:
        if not profile.load(conn)["data"]:
            raise HTTPException(409, NO_PROFILE)
        n = compute_quick(conn)
        return {"computed": n, "seconds": round(time.time() - started, 2), **{"status": status(conn, ensure=False)}}
