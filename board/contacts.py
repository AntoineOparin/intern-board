"""Find People: recruiters and team members at a tracked internship's company, via Prospeo.

Prospeo searches by company website, so each company's root domain is resolved once (careers-site
link, then a quick Claude lookup) and can be corrected by you. Results are stored locally; emails
are only revealed when you ask, at 1 credit each.
"""

import re
import time
import uuid
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import ai, db, jobs, people, profile, prospeo, settings

router = APIRouter()

KINDS = ("recruiters", "team")
SHOWN = 10  # people kept per search: the best of Prospeo's page of 25

RECRUITER_TITLES = ["recruit", "talent acquisition", "university relations", "early career",
                    "emerging talent", "talent partner", "campus"]
# Recruiters most likely to own intern hiring come first.
_STUDENT_RECRUITING = re.compile(r"universit|campus|early.?career|emerging|intern|new.?grad|graduate|student", re.I)
_TECH_RECRUITING = re.compile(r"technical|engineering|tech\b|software", re.I)
_SENIOR_ONLY = ["C-Suite", "Founder/Owner", "Vice President", "Partner"]

COUNTRIES = {"US": "United States", "CA": "Canada"}

STALE_AFTER = 30 * 86400          # searches and emails older than this may be out of date
FREE_RECHECK_WITHIN = 85 * 86400  # Prospeo re-enriches a person for free within 90 days
LOW_CREDITS = 10

# Job sites, not the employer's own website.
_NOT_EMPLOYER = re.compile(
    r"greenhouse\.io|lever\.co|ashbyhq\.com|myworkday(jobs|site)\.com|icims\.com|smartrecruiters\.com|"
    r"oraclecloud\.com|workable\.com|jobvite\.com|taleo\.net|successfactors\.|eightfold\.ai|applytojob\.com|"
    r"bamboohr\.com|zapply\.jobs|linkedin\.com|indeed\.com|simplify\.jobs|github\.com|recruitee\.com|"
    r"breezy\.hr|jazzhr\.com|ultipro\.com|paylocity\.com|adp\.com|dayforcehcm\.com|rippling\.com|"
    r"wellfound\.com|ycombinator\.com|notion\.site|gem\.com|teamtailor\.com|personio\.|pinpointhq\.com|"
    r"dover\.com|careers-page\.com|hire\.|trinethire\.com|catsone\.com|avature\.net|brassring\.com|"
    r"careerpuck\.com|workatastartup\.com|builtin\.com|handshake\.com|joinhandshake\.com|ziprecruiter\.com")
_TWO_PART_TLDS = {"co.uk", "com.au", "co.jp", "com.br", "co.in", "com.mx", "co.nz", "com.sg"}


def company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", people.clean_company(name).lower()).strip()


def root_domain(host_or_url: str) -> str | None:
    host = urlparse(host_or_url if "//" in host_or_url else f"//{host_or_url}").hostname or ""
    parts = [p for p in host.lower().split(".") if p]
    if len(parts) < 2:
        return None
    n = 3 if ".".join(parts[-2:]) in _TWO_PART_TLDS else 2
    return ".".join(parts[-n:])


def domain_matches_company(domain: str, company: str) -> bool:
    """Whether a domain plausibly belongs to the company: "lyft.com" for Lyft, "ea.com" for Electronic Arts."""
    label = re.sub(r"[^a-z0-9]", "", domain.split(".")[0].lower())
    words = [w for w in company_key(company).split() if w not in {"the", "and", "of", "group", "technologies",
                                                                 "technology", "labs", "inc", "co"}]
    if not label or not words:
        return False
    compact = "".join(words)
    initials = "".join(w[0] for w in words)
    return (label in compact and len(label) >= 3) or compact in label or label == initials or \
        (len(words[0]) >= 4 and label.startswith(words[0]))


def domain_from_listing_url(url: str, company: str) -> str | None:
    """The employer's domain when the apply link is on its own careers site (jobs.ea.com -> ea.com).

    Hosted job boards (careerpuck.com/job-board/lyft/...) aren't the employer, so the domain must
    match the company's name; otherwise the caller asks Claude.
    """
    if not url or _NOT_EMPLOYER.search(url):
        return None
    domain = root_domain(url)
    return domain if domain and domain_matches_company(domain, company) else None


DOMAIN_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["domain", "confident"],
    "properties": {
        "domain": {"type": "string", "description": "Root domain only, e.g. 'stripe.com'. Empty if unknown."},
        "confident": {"type": "boolean"},
    },
}


def _claude_domain(listing: dict) -> str | None:
    result = ai.ask(
        f"What is the main corporate website domain of this employer?\nEmployer: {listing['company']}\n"
        f"It is hiring: {listing['title']} in {listing.get('locations') or 'the US or Canada'}.\n"
        "Answer with the root domain only (e.g. 'stripe.com', not 'www.stripe.com' or a careers subdomain). "
        "If several companies share this name, pick the one that fits the role and location. If you don't "
        "know, return an empty domain and confident=false.",
        system="You identify companies' official website domains. Never guess a domain you don't know.",
        schema=DOMAIN_SCHEMA, model="sonnet", timeout=90)
    domain = root_domain(result.get("domain") or "") if result.get("confident") else None
    return domain


def company_site(conn, listing: dict, *, resolve: bool) -> dict | None:
    """The cached website for the listing's company; with resolve=True, find one if missing."""
    key = company_key(listing["company"])
    row = conn.execute("SELECT * FROM company_sites WHERE company = ?", (key,)).fetchone()
    if row or not resolve:
        return dict(row) if row else None
    domain, source = domain_from_listing_url(listing["url"], listing["company"]), "url"
    if not domain:
        domain, source = _claude_domain(listing), "claude"
    if not domain:
        return None
    save_site(conn, listing["company"], domain, source)
    return dict(conn.execute("SELECT * FROM company_sites WHERE company = ?", (key,)).fetchone())


def save_site(conn, company: str, domain: str, source: str, **extra) -> None:
    conn.execute(
        "INSERT INTO company_sites (company, domain, source, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (company) DO UPDATE SET domain = excluded.domain, source = excluded.source, "
        "updated_at = excluded.updated_at, prospeo_name = NULL, logo_url = NULL",
        (company_key(company), domain, source, int(time.time())))
    if extra:
        sets = ", ".join(f"{k} = ?" for k in extra)
        conn.execute(f"UPDATE company_sites SET {sets} WHERE company = ?", [*extra.values(), company_key(company)])


# ---------- searching ----------

def search_spec(kind: str, listing: dict) -> dict:
    if kind == "recruiters":
        return {"titles": RECRUITER_TITLES, "exclude_seniority": None}
    roles = people.role_keywords(listing["title"], listing.get("category"), listing.get("locations") or "")
    return {"titles": roles[:2], "exclude_seniority": _SENIOR_ONLY}


_PERSON_NOUNS = {"engineer", "developer", "scientist", "analyst", "designer", "manager", "researcher", "architect",
                 "specialist", "consultant", "technician", "administrator", "programmer", "strategist", "associate",
                 "trader", "quant", "partner", "coordinator", "lead", "director", "officer", "writer", "tester"}


def team_label(listing: dict) -> str:
    """Who to have coffee chats with: 'Software engineers', or 'People in research' when the role isn't a job noun."""
    role = people.role_keywords(listing["title"], listing.get("category"), listing.get("locations") or "")[0]
    if role.split()[-1] in _PERSON_NOUNS:
        plural = role[:-1] + "ies" if role.endswith("y") and role[-2:] != "ey" else role + "s"
        return plural[0].upper() + plural[1:]
    return f"People in {role}"


def _listing_places(listing: dict) -> tuple[set[str], set[str]]:
    locs = (listing.get("locations") or "").lower()
    words = {w.strip() for w in re.split(r"[,/·]| - ", locs) if w.strip()}
    return words, {COUNTRIES[r] for r in (listing.get("regions") or "").split(",") if r in COUNTRIES}


def rank(kind: str, listing: dict, results: list[dict]) -> list[dict]:
    """Best contacts first: student recruiters, then those near the job, then the rest."""
    places, countries = _listing_places(listing)
    scored = []
    for r in results:
        p = r.get("person") or {}
        loc = p.get("location") or {}
        title = p.get("current_job_title") or ""
        score = 0
        if (loc.get("country") or "") in countries:
            score += 3
        if (loc.get("city") or "").lower() in places or (loc.get("state") or "").lower() in places:
            score += 4
        if kind == "recruiters":
            score += 6 if _STUDENT_RECRUITING.search(title) else 2 if _TECH_RECRUITING.search(title) else 0
        if (p.get("email") or {}).get("status") == "VERIFIED":
            score += 1
        scored.append((score, r))
    scored.sort(key=lambda s: -s[0])
    return [r for _, r in scored]


def _listing(conn, listing_id: str) -> dict:
    row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if not row:
        raise ValueError("That listing no longer exists.")
    return dict(row)


@jobs.handler("people_search")
def people_search(payload: dict) -> dict:
    kind = payload.get("kind")
    if kind not in KINDS:
        raise ValueError("Choose recruiters or coffee chats.")
    if not prospeo.key():
        raise prospeo.NoKey()
    with db.connect() as conn:
        listing = _listing(conn, payload.get("listing_id"))
        site = company_site(conn, listing, resolve=True)
    if not site:
        raise ValueError(f"Couldn't work out {listing['company']}'s website. Enter it with “Change website”.")

    spec = search_spec(kind, listing)
    _, countries = _listing_places(listing)
    try:
        data, country_filtered = None, bool(countries)
        if countries:  # Nobody found costs nothing, so try the job's country first.
            data = prospeo.search_people(website=site["domain"], countries=sorted(countries), **spec)
        if not data:
            country_filtered = False
            data = prospeo.search_people(website=site["domain"], **spec)
    except prospeo.ProspeoError as exc:
        raise ValueError(friendly(exc)) from exc

    results = rank(kind, listing, (data or {}).get("results") or [])[:SHOWN]
    now = int(time.time())
    with db.connect() as conn:
        # Keep what you paid for (revealed emails) and people you added yourself.
        old = {r["person_id"]: r for r in conn.execute(
            "SELECT * FROM contacts WHERE listing_id = ? AND kind = ?", (listing["id"], kind))}
        conn.execute("DELETE FROM contacts WHERE listing_id = ? AND kind = ? AND source = 'prospeo'",
                     (listing["id"], kind))
        for i, r in enumerate(results):
            p, loc, email = r["person"], r["person"].get("location") or {}, r["person"].get("email") or {}
            prev = old.get(p["person_id"])
            conn.execute(
                "INSERT OR REPLACE INTO contacts (listing_id, kind, person_id, rank, full_name, title, city, state, "
                "country, linkedin_url, email, email_status, email_found_at, job_change_at, found_at, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prospeo')",
                (listing["id"], kind, p["person_id"], i, p.get("full_name") or "", p.get("current_job_title"),
                 loc.get("city"), loc.get("state"), loc.get("country"), p.get("linkedin_url"),
                 prev["email"] if prev else None,
                 prev["email_status"] if prev and prev["email"] else email.get("status"),
                 prev["email_found_at"] if prev else None, _timestamp(p.get("last_job_change_detected_at")),
                 prev["found_at"] if prev else now))
        # Revealed emails for people this search no longer returns: keep them at the end of the list.
        kept = {r["person"]["person_id"] for r in results}
        for pid, prev in old.items():
            if prev["source"] == "prospeo" and prev["email"] and pid not in kept:
                conn.execute(
                    "INSERT INTO contacts (listing_id, kind, person_id, rank, full_name, title, city, state, country, "
                    "linkedin_url, email, email_status, email_found_at, job_change_at, moved_to, found_at, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prospeo')",
                    (listing["id"], kind, pid, 500, prev["full_name"], prev["title"], prev["city"], prev["state"],
                     prev["country"], prev["linkedin_url"], prev["email"], prev["email_status"],
                     prev["email_found_at"], prev["job_change_at"], prev["moved_to"], prev["found_at"]))
        company = next((r.get("company") for r in results if r.get("company")), None)
        if company:
            conn.execute("UPDATE company_sites SET prospeo_name = ?, logo_url = ? WHERE company = ?",
                         (company.get("name"), company.get("logo_url"), company_key(listing["company"])))
        conn.execute(
            "INSERT INTO people_searches (listing_id, kind, domain, total, country_filtered, searched_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (listing_id, kind) DO UPDATE SET domain = excluded.domain, "
            "total = excluded.total, country_filtered = excluded.country_filtered, searched_at = excluded.searched_at",
            (listing["id"], kind, site["domain"], ((data or {}).get("pagination") or {}).get("total_count", 0),
             int(country_filtered), now))
    return {"count": len(results), "free": bool((data or {}).get("free")), "charged": bool(data) and not data.get("free")}


def _timestamp(value) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def friendly(exc: prospeo.ProspeoError) -> str:
    """Prospeo errors as the page shows them; running out of credits names the renewal date."""
    if exc.code != "INSUFFICIENT_CREDITS":
        return str(exc)
    try:
        renews = (prospeo.account().get("next_quota_renewal_date") or "")[:10]
    except prospeo.ProspeoError:
        renews = ""
    when = f" until {datetime.fromisoformat(renews).strftime('%B %-d')}" if renews else ""
    return (f"You're out of Prospeo credits{when}. Saved people still work, and you can use the free "
            "search links or add someone yourself.")


# ---------- API ----------

def _contact(row) -> dict:
    d = dict(row)
    d["location"] = ", ".join(x for x in (d.get("city"), d.get("state") or d.get("country")) if x)
    now = time.time()
    found = d.get("email_found_at")
    # Re-checking an email is free within Prospeo's 90-day window; after that it costs a credit.
    d["email_stale"] = bool(d.get("email") and d.get("source") == "prospeo" and found and now - found > STALE_AFTER)
    d["recheck_free"] = bool(found and now - found < FREE_RECHECK_WITHIN)
    d["new_in_role"] = bool(d.get("job_change_at") and d["found_at"] - d["job_change_at"] < 90 * 86400)
    return d


@router.get("/api/people/session")
def session(listing_id: str):
    """Everything the Find People page needs for one listing; no paid calls."""
    with db.connect() as conn:
        try:
            listing = _listing(conn, listing_id)
        except ValueError:
            raise HTTPException(404, "Unknown listing")
        site = company_site(conn, listing, resolve=False)
        searches = {r["kind"]: {**dict(r), "stale": time.time() - r["searched_at"] > STALE_AFTER}
                    for r in conn.execute("SELECT * FROM people_searches WHERE listing_id = ?", (listing_id,))}
        contacts = {k: [_contact(r) for r in conn.execute(
            "SELECT * FROM contacts WHERE listing_id = ? AND kind = ? ORDER BY rank", (listing_id, k))] for k in KINDS}
        school = profile.load(conn)["preferences"].get("school") or ""
    return {
        "listing": {k: listing[k] for k in ("id", "company", "title", "locations", "url", "category")},
        "company": people.clean_company(listing["company"]),
        "site": site, "searches": searches, "contacts": contacts, "team_label": team_label(listing),
        "links": people.search_links(listing["company"], listing["title"], school, listing.get("category"),
                                     listing.get("locations") or ""),
        "configured": bool(prospeo.key()),
    }


@router.get("/api/people/logos")
def logos():
    """{listing_id: logo_url} for tracked listings whose company an earlier search found."""
    with db.connect() as conn:
        sites = {r["company"]: r["logo_url"] for r in conn.execute(
            "SELECT company, logo_url FROM company_sites WHERE logo_url IS NOT NULL")}
        tracked = conn.execute("SELECT l.id, l.company FROM tracker t JOIN listings l ON l.id = t.listing_id")
        return {r["id"]: sites[k] for r in tracked if (k := company_key(r["company"])) in sites}


class SiteUpdate(BaseModel):
    listing_id: str
    website: str = Field(min_length=3, max_length=200)


@router.put("/api/people/site")
def set_site(body: SiteUpdate):
    domain = root_domain(body.website.strip())
    if not domain or "." not in domain:
        raise HTTPException(422, "Enter a website like stripe.com.")
    with db.connect() as conn:
        listing = conn.execute("SELECT company FROM listings WHERE id = ?", (body.listing_id,)).fetchone()
        if not listing:
            raise HTTPException(404, "Unknown listing")
        save_site(conn, listing["company"], domain, "user")
    return {"domain": domain}


class EmailRequest(BaseModel):
    listing_id: str
    kind: str
    person_id: str


@router.post("/api/people/email")
def reveal(body: EmailRequest):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE listing_id = ? AND kind = ? AND person_id = ?",
                           (body.listing_id, body.kind, body.person_id)).fetchone()
    if not row:
        raise HTTPException(404, "Unknown contact")
    if row["email"]:
        return _contact(row)
    try:
        email = prospeo.reveal_email(body.person_id)
    except prospeo.ProspeoError as exc:
        raise HTTPException(402 if exc.code == "INSUFFICIENT_CREDITS" else 502, friendly(exc))
    with db.connect() as conn:
        # The same person may have been found for other listings; fill them all in.
        conn.execute("UPDATE contacts SET email = ?, email_status = ?, email_found_at = ? WHERE person_id = ?",
                     (email["email"], email.get("status") or "VERIFIED", int(time.time()), body.person_id) if email
                     else (None, "NOT_FOUND", None, body.person_id))
        row = conn.execute("SELECT * FROM contacts WHERE listing_id = ? AND kind = ? AND person_id = ?",
                           (body.listing_id, body.kind, body.person_id)).fetchone()
    return _contact(row)


@router.post("/api/people/recheck")
def recheck(body: EmailRequest):
    """Look the person up again: are they still at the company, and is the email still verified?

    Free within Prospeo's 90-day window after the email was revealed; after that 1 credit.
    """
    with db.connect() as conn:
        row = conn.execute("SELECT c.*, l.company AS listing_company FROM contacts c JOIN listings l "
                           "ON l.id = c.listing_id WHERE c.listing_id = ? AND c.kind = ? AND c.person_id = ?",
                           (body.listing_id, body.kind, body.person_id)).fetchone()
        site = conn.execute("SELECT * FROM company_sites WHERE company = ?",
                            (company_key(row["listing_company"]),)).fetchone() if row else None
    if not row or row["source"] != "prospeo":
        raise HTTPException(404, "Only people found through Prospeo can be re-checked.")
    try:
        data = prospeo.enrich_person(body.person_id)
    except prospeo.ProspeoError as exc:
        raise HTTPException(402 if exc.code == "INSUFFICIENT_CREDITS" else 502, friendly(exc))
    now = int(time.time())
    with db.connect() as conn:
        if not data:
            conn.execute("UPDATE contacts SET email_status = 'NO_LONGER_VERIFIED', email_found_at = ? "
                         "WHERE person_id = ?", (now, body.person_id))
        else:
            p, company = data.get("person") or {}, data.get("company") or {}
            email = (p.get("email") or {}).get("email") or row["email"]
            domain = root_domain(company.get("website") or company.get("domain") or "")
            moved = company.get("name") if site and domain and domain != site["domain"] else None
            conn.execute("UPDATE contacts SET email = ?, email_status = ?, email_found_at = ?, title = ?, moved_to = ? "
                         "WHERE person_id = ?", (email, (p.get("email") or {}).get("status") or "VERIFIED", now,
                                                 p.get("current_job_title") or row["title"], moved, body.person_id))
        row = conn.execute("SELECT * FROM contacts WHERE listing_id = ? AND kind = ? AND person_id = ?",
                           (body.listing_id, body.kind, body.person_id)).fetchone()
    return {**_contact(row), "charged": bool(data) and not data.get("free_enrichment")}


class NewContact(BaseModel):
    listing_id: str
    kind: str
    full_name: str = Field(min_length=2, max_length=100)
    title: str = Field("", max_length=150)
    linkedin_url: str = Field("", max_length=300)
    email: str = Field("", max_length=200)


@router.post("/api/people/contacts")
def add_contact(body: NewContact):
    """Someone you found yourself (e.g. from the free search links). Costs nothing."""
    if body.kind not in KINDS:
        raise HTTPException(422, "Choose recruiters or coffee chats.")
    linkedin = body.linkedin_url.strip()
    if linkedin and not re.match(r"^(https?://)?([a-z]{2,3}\.)?linkedin\.com/in/[^\s/]+/?", linkedin, re.I):
        raise HTTPException(422, "Paste a LinkedIn profile link like linkedin.com/in/their-name.")
    if linkedin and not linkedin.startswith("http"):
        linkedin = "https://" + linkedin
    email = body.email.strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email, re.I):
        raise HTTPException(422, "That email address doesn't look right.")
    now = int(time.time())
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM listings WHERE id = ?", (body.listing_id,)).fetchone():
            raise HTTPException(404, "Unknown listing")
        rank = conn.execute("SELECT COALESCE(MAX(rank), -1) + 1 FROM contacts WHERE listing_id = ? AND kind = ?",
                            (body.listing_id, body.kind)).fetchone()[0]
        person_id = "manual:" + uuid.uuid4().hex[:12]
        conn.execute("INSERT INTO contacts (listing_id, kind, person_id, rank, full_name, title, linkedin_url, email, "
                     "email_status, found_at, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual')",
                     (body.listing_id, body.kind, person_id, rank, body.full_name.strip(), body.title.strip() or None,
                      linkedin or None, email or None, "ADDED" if email else None, now))
        row = conn.execute("SELECT * FROM contacts WHERE person_id = ?", (person_id,)).fetchone()
    return _contact(row)


@router.delete("/api/people/contacts/one")
def remove_contact(listing_id: str, kind: str, person_id: str):
    with db.connect() as conn:
        n = conn.execute("DELETE FROM contacts WHERE listing_id = ? AND kind = ? AND person_id = ?",
                         (listing_id, kind, person_id)).rowcount
    if not n:
        raise HTTPException(404, "Unknown contact")
    return {"ok": True}


@router.delete("/api/people/contacts")
def forget_contacts():
    """Delete every saved contact and search (Profile → Integrations)."""
    with db.connect() as conn:
        n = conn.execute("DELETE FROM contacts").rowcount
        conn.execute("DELETE FROM people_searches")
    return {"deleted": n}


# ---------- Prospeo key and credits (Profile → Integrations) ----------

@router.get("/api/integrations/prospeo")
def prospeo_status():
    if not prospeo.key():
        return {"configured": False}
    try:
        a = prospeo.account()
    except prospeo.ProspeoError as exc:
        return {"configured": True, "error": str(exc)}
    k = prospeo.key()
    remaining = a.get("remaining_credits") or 0
    return {"configured": True, "masked": f"{k[:5]}…{k[-4:]}", "plan": a.get("current_plan"),
            "remaining": remaining, "used": a.get("used_credits"), "renews": a.get("next_quota_renewal_date"),
            "low": remaining < LOW_CREDITS, "empty": remaining <= 0}


class KeyUpdate(BaseModel):
    key: str = Field(min_length=10, max_length=200, pattern=r"^[A-Za-z0-9_\-]+$")


@router.put("/api/integrations/prospeo")
def set_prospeo_key(body: KeyUpdate):
    try:
        prospeo.account(api_key=body.key)  # free; fails on a bad key
    except prospeo.ProspeoError as exc:
        raise HTTPException(422, str(exc))
    settings.set(prospeo.KEY_NAME, body.key)
    return prospeo_status()


@router.delete("/api/integrations/prospeo")
def remove_prospeo_key():
    settings.set(prospeo.KEY_NAME, None)
    return {"configured": bool(prospeo.key())}
