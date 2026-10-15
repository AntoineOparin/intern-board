"""Find people at a company and draft outreach messages.

"Find people" only builds LinkedIn and Google search links that you open yourself. The app never
fetches LinkedIn, never automates requests to it and never stores anyone's details, apart from a
recipient name you type for a draft. Claude then drafts short, honest messages from your profile.
Drafts are kept in the shared `documents` table with kind 'outreach'.
"""

import json
import re
import time
import uuid
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import ai, db, jobs, outreach as writer, postings, profile
from .locations import CA_NAMES, CA_PROVINCES, US_ALIASES, US_NAMES, US_STATES

router = APIRouter()

KIND = "outreach"
APPLIED_STATUSES = ("applied", "interviewing", "offer")
RECIPIENT_TYPES = ("recruiter", "engineer", "alum", "hiring_manager")
CHANNELS = ("linkedin_note", "email", "follow_up")


# ---------- search links ----------

LINKEDIN_PEOPLE = "https://www.linkedin.com/search/results/people/?keywords="
GOOGLE = "https://www.google.com/search?q="

# Legal suffixes that only add noise to a people search. "Co." and "Company" stay: they are often
# part of the name people use ("Brain Co.", "S&C Electric Company").
_LEGAL = r"(?:inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|plc|gmbh|ag|s\.a|sa|lp|llp|ulc|pbc)\.?"
_LEGAL_RE = re.compile(rf"(?:,?\s+{_LEGAL})+\s*$", re.I)

_SEASON = r"(?:spring|summer|fall|autumn|winter|january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
# Words that describe the internship rather than the team or role.
_NOISE_RE = re.compile(
    rf"\b(?:{_SEASON}|(?:19|20)\d\d|interns?|internships?|co-?ops?|coop|students?|placement|"
    r"work[- ]term|term|months?|\d+[- ]?months?|phd|ph\.d\.?|masters?|master's|mba|bachelors?|bachelor's|"
    r"undergrad(?:uate)?|graduate|grad|new|university|campus|early[- ]career|program(?:me)?|"
    r"full[- ]time|part[- ]time|remote|hybrid|onsite|on-site|paid|unpaid|summer|fall|"
    r"\d+)\b", re.I)
_SPLIT_RE = re.compile(r"\s+[-–—|]\s+|\s*[:,;(\)\[\]]\s*|\s*/\s*(?=(?:intern|co-?op))", re.I)
_PLACES = {c.lower() for c in (*US_STATES, *CA_PROVINCES)} | US_NAMES | CA_NAMES | US_ALIASES | {"remote", "hybrid"}
# Lower-case connector words that are fine inside a phrase but not at its edges.
_EDGE_WORDS = {"and", "&", "or", "of", "the", "for", "in", "at", "with", "to", "a", "an", "-", "/"}


def clean_company(name: str) -> str:
    """A company name as people write it on LinkedIn: no legal suffixes, no parentheticals."""
    s = (name or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"\s*[(\[][^)\]]*[)\]]", " ", s)          # "Meta (Facebook)" -> "Meta"
    s = re.sub(r"[\"]", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ,;-–—|")
    for _ in range(2):  # "Acme Holdings, Inc., LLC"
        stripped = _LEGAL_RE.sub("", s).strip(" ,;")
        if not stripped:
            break
        s = stripped
    return s or (name or "").strip()


def _tidy_phrase(text: str) -> str:
    text = _NOISE_RE.sub(" ", text)
    text = re.sub(r"[^\w&+#./' -]", " ", text)
    words = [w for w in text.split() if w.strip("-./")]
    while words and words[0].lower() in _EDGE_WORDS:
        words.pop(0)
    while words and words[-1].lower() in _EDGE_WORDS:
        words.pop()
    return " ".join(words).lower()


def _is_place(part: str, locations: str) -> bool:
    part = part.strip().lower()
    return part in _PLACES or (len(part) > 2 and part in (locations or "").lower())


def role_keywords(title: str, category: str | None = None, locations: str = "") -> list[str]:
    """One or two short phrases describing the role and team, for a people search.

    "Machine Learning Engineer Intern - Ads" -> ["machine learning engineer", "ads"].
    """
    parts = [p for p in _SPLIT_RE.split(title or "") if p and p.strip()]
    phrases: list[str] = []
    for part in parts:
        if _is_place(part, locations):
            continue
        phrase = _tidy_phrase(part)
        # Single letters ("Product Management Intern - S") and very long fragments aren't useful.
        if len(phrase) < 2 or len(phrase.replace(" ", "")) < 2 or len(phrase.split()) > 5:
            continue
        if any(phrase in p or p in phrase for p in phrases):
            continue
        phrases.append(phrase)
        if len(phrases) == 2:
            break
    if not phrases:
        phrases = [{"Software": "software engineer", "AI/ML/Data": "machine learning",
                    "Hardware": "hardware engineer", "Quant": "quantitative"}.get(category or "", "engineering")]
    return phrases


def _linkedin(keywords: str) -> str:
    # LinkedIn treats upper-case AND/OR/NOT as search operators; a company name shouldn't.
    keywords = re.sub(r"\b(AND|OR|NOT)\b", lambda m: m.group(1).lower(), keywords)
    return LINKEDIN_PEOPLE + quote_plus(keywords)


def _google(q: str) -> str:
    return GOOGLE + quote_plus(q)


def search_links(company: str, title: str, school: str = "", category: str | None = None,
                 locations: str = "") -> dict:
    """LinkedIn and Google search links for people to contact about one listing. Pure function."""
    co = clean_company(company)
    school = re.sub(r"\s+", " ", school or "").strip()
    roles = role_keywords(title, category, locations)
    groups = [
        {"id": "recruiters", "title": "Recruiters",
         "hint": "Recruiters who hire students. Look for “university”, “campus” or “early careers” in the headline.",
         "items": [
             {"label": "University recruiter", "url": _linkedin(f"{co} university recruiter"),
              "hint": "Owns intern hiring; the best first contact."},
             {"label": "Technical recruiter", "url": _linkedin(f"{co} technical recruiter"),
              "hint": "Check the headline mentions interns or new grads."},
             {"label": "Campus recruiting", "url": _linkedin(f"{co} campus recruiting"),
              "hint": "Runs career fairs and info sessions."},
         ]},
        {"id": "team", "title": "People on the team",
         "hint": "Engineers doing similar work. Prefer people a year or two out of school.",
         "items": [{"label": r[0].upper() + r[1:], "url": _linkedin(f"{co} {r}"),
                    "hint": "Look for the same team or product in their experience."} for r in roles]},
        {"id": "alumni", "title": "Alumni from your school",
         "hint": "People who went to your school. Shared background makes a reply more likely.",
         "items": [{"label": f"{school} alumni", "url": _linkedin(f"{co} {school}"),
                    "hint": f"Use the “School” filter on LinkedIn for {school}."}] if school else [],
         "note": "" if school else "Add your school on the Profile tab to search for alumni."},
        {"id": "google", "title": "Google searches",
         "hint": "Public pages, for when LinkedIn search is limited.",
         "items": [
             {"label": "Recruiter profiles", "url": _google(f'site:linkedin.com/in "{co}" "university recruiter"'),
              "hint": "Public LinkedIn profiles that mention the company and role."},
             {"label": f"{roles[0][0].upper() + roles[0][1:]} profiles",
              "url": _google(f'site:linkedin.com/in "{co}" "{roles[0]}"'),
              "hint": "Public profiles of people with this kind of role."},
             {"label": "Engineering blog", "url": _google(f'"{co}" engineering blog'),
              "hint": "Recent posts make a good, specific opener."},
             {"label": "Careers and students page", "url": _google(f'"{co}" careers students internships'),
              "hint": "Recruiting contacts, events and timelines."},
         ]},
    ]
    return {"company": co, "keywords": roles, "school": school, "groups": groups}


@router.get("/api/people/links")
def links(listing_id: str):
    with db.connect() as conn:
        row = conn.execute("SELECT company, title, category, locations FROM listings WHERE id = ?", (listing_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown listing")
        school = profile.load(conn)["preferences"].get("school") or ""
    return search_links(row["company"], row["title"], school, row["category"], row["locations"])


# ---------- outreach drafts ----------

CHANNEL_LABELS = {"linkedin_note": "LinkedIn note", "email": "Email", "follow_up": "Follow-up"}
RECIPIENT_LABELS = {"recruiter": "recruiter", "engineer": "engineer", "alum": "alum",
                    "hiring_manager": "hiring manager"}


def _description(listing: dict) -> str | None:
    """A cached description, or one from the job board's API. Never blocks on a slow page fetch:
    a short note doesn't need the full posting."""
    with db.connect() as conn:
        cached = conn.execute("SELECT text FROM posting_details WHERE listing_id = ?", (listing["id"],)).fetchone()
    if cached:
        return cached["text"]
    if not str(listing.get("posting_key") or "").startswith(("gh:", "lever:", "ashby:")):
        return None
    try:
        return postings.description(listing["id"]).get("text")
    except (ai.AIError, ValueError, OSError):
        return None


def _text(payload: dict, key: str, limit: int) -> str:
    value = payload.get(key) or ""
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text.")
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > limit:
        raise ValueError(f"Keep the {key.replace('_', ' ')} under {limit} characters.")
    return value


@jobs.handler("outreach")
def outreach(payload: dict) -> dict:
    """Write a LinkedIn note, email or follow-up (see board/outreach.py for how)."""
    recipient_type, channel = payload.get("recipient_type"), payload.get("channel")
    if recipient_type not in RECIPIENT_TYPES:
        raise ValueError("Choose who the message is for.")
    if channel not in CHANNELS:
        raise ValueError("Choose a message type.")
    recipient = {"type": recipient_type, "name": _text(payload, "recipient_name", 80), "title": "", "location": ""}
    context = _text(payload, "context", 500)
    person_id, previous = None, None
    with db.connect() as conn:
        p = profile.require(conn)
        if payload.get("person_id"):  # a contact from Find People
            contact = conn.execute("SELECT full_name, title, city, state, country FROM contacts "
                                   "WHERE listing_id = ? AND person_id = ?",
                                   (payload.get("listing_id"), payload["person_id"])).fetchone()
            if not contact:
                raise ValueError("That contact is no longer saved. Search again.")
            person_id = payload["person_id"]
            recipient.update(name=contact["full_name"], title=contact["title"] or "",
                             location=", ".join(x for x in (contact["city"], contact["state"] or contact["country"]) if x))
        if payload.get("previous_id"):  # "Rewrite": take a different angle from this draft
            row = conn.execute("SELECT content FROM documents WHERE id = ? AND kind = ?",
                               (payload["previous_id"], KIND)).fetchone()
            previous = json.loads(row["content"]) if row else None
        row = conn.execute("SELECT l.*, t.status FROM listings l LEFT JOIN tracker t ON t.listing_id = l.id "
                           "WHERE l.id = ?", (payload.get("listing_id"),)).fetchone()
    if not row:
        raise ValueError("That listing no longer exists.")
    listing = dict(row)
    applied = listing.get("status") in APPLIED_STATUSES
    if channel == "follow_up" and not applied:
        raise ValueError("A follow-up is for after you apply. Move this card to Applied first, "
                         "or draft a LinkedIn note or email instead.")
    if recipient_type == "alum" and not p["preferences"].get("school"):
        raise ValueError("Add your school on the Profile tab to write to alumni.")

    draft = writer.compose(p, listing, recipient, channel=channel, applied=applied, context=context,
                           description=_description(listing), previous=previous)

    content = {"recipient_type": recipient_type, "channel": channel, "recipient_name": recipient["name"],
               "recipient_title": recipient["title"], "person_id": person_id, "context": context,
               "subject": draft["subject"], "body": draft["body"], "angle": draft["angle"], "checks": draft["checks"]}
    title = f"{CHANNEL_LABELS[channel]} · {RECIPIENT_LABELS[recipient_type]}"
    if recipient["name"]:
        title += f" · {recipient['name']}"
    doc_id, now = uuid.uuid4().hex[:12], int(time.time())
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id, listing_id, kind, title, content, profile_version, created_at, "
                     "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (doc_id, listing["id"], KIND, title, json.dumps(content), p["version"], now, now))
    return {"document_id": doc_id, "id": doc_id, "title": title, **{k: content[k] for k in (
        "subject", "body", "angle", "checks", "channel", "person_id")}, "chars": len(draft["body"]),
        "limit": draft["limit"]}


# ---------- draft endpoints (kind 'outreach' only) ----------

def _public(row) -> dict:
    content = json.loads(row["content"] or "{}")
    return {"id": row["id"], "listing_id": row["listing_id"], "title": row["title"],
            "created_at": row["created_at"], "updated_at": row["updated_at"], **content,
            "chars": len(content.get("body") or "")}


@router.get("/api/people/drafts")
def list_drafts(listing_id: str):
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM documents WHERE kind = ? AND listing_id = ? ORDER BY created_at DESC",
                            (KIND, listing_id)).fetchall()
    return {"items": [_public(r) for r in rows]}


class DraftUpdate(BaseModel):
    subject: str | None = Field(None, max_length=300)
    body: str | None = Field(None, max_length=10_000)


@router.put("/api/people/drafts/{doc_id}")
def update_draft(doc_id: str, body: DraftUpdate):
    if body.subject is None and body.body is None:
        raise HTTPException(422, "Nothing to update.")
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ? AND kind = ?", (doc_id, KIND)).fetchone()
        if not row:
            raise HTTPException(404, "That draft no longer exists.")
        content = json.loads(row["content"] or "{}")
        if body.subject is not None:
            content["subject"] = body.subject.strip()
        if body.body is not None:
            if not body.body.strip():
                raise HTTPException(422, "The message is empty.")
            content["body"] = body.body.replace("\r\n", "\n").strip()
        conn.execute("UPDATE documents SET content = ?, updated_at = ? WHERE id = ? AND kind = ?",
                     (json.dumps(content), int(time.time()), doc_id, KIND))
        return _public(conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone())


@router.delete("/api/people/drafts/{doc_id}")
def delete_draft(doc_id: str):
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM documents WHERE id = ? AND kind = ?", (doc_id, KIND))
    if not cur.rowcount:
        raise HTTPException(404, "That draft no longer exists.")
    return {"ok": True}
