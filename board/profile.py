"""Your resume and profile: the source of truth every AI feature writes from.

The stored profile `data` follows PROFILE_SCHEMA, except that each experience and project entry has
`id`, `missing_from_resume` and `points` instead of `bullets`:

    {"id": "e-3f9a2c1b", "organization": ..., "role": ..., "missing_from_resume": False,
     "points": [{"id": "p-8c1d2e3f", "phrasings": ["Cut report time from 14 s to 2 s.", ...]}]}

A point is one fact; its phrasings say it in different ways, and the first one is the primary.
Tailored resumes pick points and phrasings verbatim. PROFILE_SCHEMA is only the extraction
contract (Claude returns flat `bullets`); normalize() converts either shape, so the raw JSON editor
may still use `bullets`. Only facts bump `version` (rankings and documents key on it): adding a
phrasing doesn't.
"""

import copy
import hashlib
import io
import json
import re
import time
import uuid
import zipfile
from xml.etree import ElementTree

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from . import ai, db, honesty, jobs
from .locations import fold

router = APIRouter()

MAX_RESUME_BYTES = 5 * 1024 * 1024
MAX_DATA_CHARS = 200_000
MAX_PHRASINGS = 6   # per point; the editor stops there and the tailoring index lists no more
SUGGEST_COUNT = 3   # phrasings Claude suggests per click

_str = {"type": "string"}
_strs = {"type": "array", "items": _str}
PROFILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "email", "phone", "location", "links", "education", "experience", "projects",
                 "skills", "awards", "summary"],
    "properties": {
        "name": _str, "email": _str, "phone": _str, "location": _str,
        "links": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": ["label", "url"],
                                             "properties": {"label": _str, "url": _str}}},
        "education": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["school", "degree", "field", "location", "start", "end", "gpa", "details"],
            "properties": {"school": _str, "degree": _str, "field": _str, "location": _str, "start": _str,
                           "end": _str, "gpa": _str, "details": _strs}}},
        "experience": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["organization", "role", "location", "start", "end", "bullets"],
            "properties": {"organization": _str, "role": _str, "location": _str, "start": _str, "end": _str,
                           "bullets": _strs}}},
        "projects": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "tech", "link", "date", "bullets"],
            "properties": {"name": _str, "tech": _strs, "link": _str, "date": _str, "bullets": _strs}}},
        "skills": {"type": "object", "additionalProperties": False,
                   "required": ["languages", "frameworks", "tools", "other"],
                   "properties": {"languages": _strs, "frameworks": _strs, "tools": _strs, "other": _strs}},
        "awards": _strs,
        "summary": {"type": "string", "description": "One factual sentence: who they are and what they've worked on."},
    },
}

SUGGEST_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["phrasings"],
                  "properties": {"phrasings": {**_strs, "description": "Alternative phrasings, no numbering."}}}

DEFAULT_PREFERENCES = {
    "target_roles": [],         # free text, e.g. ["backend", "ML infrastructure"]
    "categories": [],           # e.g. ["Software", "AI/ML/Data"]
    "regions": [],              # "US", "CA", "REMOTE"
    "terms": [],                # e.g. ["Summer 2027"]
    "degree_level": "",         # e.g. "Bachelor's"
    "graduation": "",           # e.g. "May 2028"
    "work_authorization": "",   # free text, e.g. "Canadian citizen; needs US sponsorship"
    "school": "",               # used for alumni searches
    "notes": "",                # anything else Claude should know
    "linkedin_premium": False,  # Premium allows 300-character connection notes; free accounts get 200
}

# Sections that hold points, and the id prefix of their entries.
SECTIONS = {"experience": "e", "projects": "j"}


# ---------- points ----------

def _text_key(s) -> str:
    """Letters and digits only, lower case, no accents: for matching phrasings and entries."""
    return re.sub(r"[^a-z0-9]", "", fold(str(s or "")))


def _hash_id(prefix: str, *parts: str) -> str:
    """A stable id from content, so the same legacy data converts to the same ids on every read."""
    return f"{prefix}-{hashlib.sha1('\x1f'.join(parts).encode()).hexdigest()[:8]}"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def entry_key(section: str, e: dict) -> tuple:
    if section == "experience":
        return (_text_key(e.get("organization")), _text_key(e.get("role")))
    return (_text_key(e.get("name")),)


def _normalize_entry(section: str, entry: dict, taken_ids: set[str]) -> dict:
    e = dict(entry)
    points, keys, ids = [], set(), set()

    def add(point_id, phrasings):
        phrasings = [s for s in honesty.clean(phrasings) if _text_key(s)]
        fresh = []
        for s in phrasings:
            k = _text_key(s)
            if k not in keys:  # the same sentence twice in one entry is a mistake, keep the first
                keys.add(k)
                fresh.append(s)
        if not fresh:
            return
        if not isinstance(point_id, str) or not point_id or point_id in ids:
            point_id = _hash_id("p", _text_key(fresh[0]))
            while point_id in ids:
                point_id = new_id("p")
        ids.add(point_id)
        points.append({"id": point_id, "phrasings": fresh})

    for pt in e.get("points") if isinstance(e.get("points"), list) else []:
        if isinstance(pt, dict):
            add(pt.get("id"), pt.get("phrasings") if isinstance(pt.get("phrasings"), list) else [])
        elif isinstance(pt, str):
            add(None, [pt])
    for b in e.get("bullets") if isinstance(e.get("bullets"), list) else []:
        add(None, [b])  # a bullet that repeats an existing phrasing is skipped
    e.pop("bullets", None)

    if not isinstance(e.get("id"), str) or not e["id"] or e["id"] in taken_ids:
        e["id"] = _hash_id(SECTIONS[section], *entry_key(section, e))
        while e["id"] in taken_ids:
            e["id"] = new_id(SECTIONS[section])
    taken_ids.add(e["id"])
    e["points"] = points
    e["missing_from_resume"] = bool(e.get("missing_from_resume"))
    return e


def normalize(data) -> dict:
    """The stored shape (ids, points) from either stored or extracted data. Idempotent."""
    if not isinstance(data, dict):
        return {}
    data = copy.deepcopy(data)
    for section in SECTIONS:
        if section not in data:
            continue
        entries = data.get(section) if isinstance(data.get(section), list) else []
        taken: set[str] = set()
        data[section] = [_normalize_entry(section, e, taken) for e in entries if isinstance(e, dict)]
    return data


def flat_data(data: dict, *, bullets: bool = True) -> dict:
    """The profile as PROFILE_SCHEMA shapes it: ids and flags dropped, points as their primary phrasing.

    Every prompt except resume tailoring sees this, so prompts stay as short as before.
    `bullets=False` leaves bullets out entirely (tailoring lists every phrasing separately).
    """
    data = normalize(data)
    for section in SECTIONS:
        for e in data.get(section) or []:
            points = e.pop("points")
            e.pop("id", None)
            e.pop("missing_from_resume", None)
            if bullets:
                e["bullets"] = [pt["phrasings"][0] for pt in points]
    return data


def _facts(data: dict) -> str:
    return json.dumps(flat_data(data), sort_keys=True, ensure_ascii=False)


def find_point(data: dict, point_id: str) -> tuple[str, dict, dict]:
    """(section, entry, point) for a point id, or a ValueError the user sees."""
    for section in SECTIONS:
        for e in data.get(section) or []:
            for pt in e.get("points") or []:
                if pt["id"] == point_id:
                    return section, e, pt
    raise ValueError("That point no longer exists. Reload the page.")


def _merge_entry(old: dict, new: dict) -> dict:
    """An old entry updated from its re-extracted twin: facts from the file, points kept and extended."""
    e = dict(old)
    for k, v in new.items():
        if k in ("id", "points", "missing_from_resume"):
            continue
        if k == "tech":
            have = {_text_key(t) for t in old.get("tech") or []}
            e["tech"] = list(old.get("tech") or []) + [t for t in v or [] if _text_key(t) not in have]
        elif v not in ("", [], None):
            e[k] = v
    keys = {_text_key(s) for pt in old["points"] for s in pt["phrasings"]}
    e["points"] = list(old["points"]) + [pt for pt in new["points"] if _text_key(pt["phrasings"][0]) not in keys]
    e["missing_from_resume"] = False
    return e


def merge_profile(old: dict, new: dict) -> dict:
    """A re-extracted profile merged over the stored one.

    Everything outside experience and projects comes from the file. Entries are matched by
    organisation and role (experience) or name (projects); matched entries keep their ids, points
    and phrasings and gain the file's new bullets as new points. Entries the file no longer has are
    kept after the others and flagged `missing_from_resume`.
    """
    old, new = normalize(old), normalize(new)
    if not old:
        return new
    merged = dict(new)
    for section in SECTIONS:
        old_entries = old.get(section) or []
        used, out = set(), []
        for e in new.get(section) or []:
            key = entry_key(section, e)
            match = next((o for o in old_entries if o["id"] not in used and entry_key(section, o) == key), None)
            if match:
                used.add(match["id"])
                out.append(_merge_entry(match, e))
            else:
                out.append(e)
        out += [{**o, "missing_from_resume": True} for o in old_entries if o["id"] not in used]
        merged[section] = out
    return normalize(merged)  # a new entry's id could clash with a kept one


def validate_phrasings(candidates, point: dict) -> list[str]:
    """Suggestions that state the same fact: same numbers, no filler, not already in the point."""
    primary = point["phrasings"][0]
    want = honesty.numbers(primary)
    seen = {_text_key(s) for s in point["phrasings"]}
    kept = []
    for c in honesty.clean(candidates):
        key = _text_key(c)
        if (not key or key in seen or len(c) > 220 or len(c.split()) > 30
                or honesty.numbers(c) != want or honesty.banned_hits(c)):
            continue
        seen.add(key)
        kept.append(c)
    return kept[:SUGGEST_COUNT]


# ---------- reading ----------

def load(conn) -> dict:
    """The current profile row as a dict, with JSON fields decoded. Safe to call from any feature."""
    row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    if not row:
        return {"resume_filename": None, "resume_text": "", "data": {}, "preferences": dict(DEFAULT_PREFERENCES),
                "version": 0, "updated_at": None}
    p = dict(row)
    p["data"] = normalize(json.loads(p["data"] or "{}"))
    p["preferences"] = {**DEFAULT_PREFERENCES, **json.loads(p["preferences"] or "{}")}
    return p


def require(conn) -> dict:
    """The profile, or a ValueError the user sees if there's no resume yet."""
    p = load(conn)
    if not p["data"]:
        raise ValueError("Add your resume on the Profile tab first.")
    return p


def as_prompt_text(p: dict, *, bullets: bool = True) -> str:
    """The profile and preferences, formatted for a prompt (one bullet per point; see flat_data)."""
    return (f"CANDIDATE PROFILE (JSON):\n{json.dumps(flat_data(p['data'], bullets=bullets), indent=1)}\n\n"
            f"CANDIDATE PREFERENCES (JSON):\n{json.dumps(p['preferences'], indent=1)}")


def _save(conn, bump: bool = True, **fields) -> None:
    """Write fields; `bump=False` keeps `version` (phrasing-only edits must not stale rankings or documents)."""
    now = int(time.time())
    conn.execute("INSERT INTO profile (id, updated_at) VALUES (1, ?) ON CONFLICT (id) DO NOTHING", (now,))
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE profile SET {sets}, version = version + ?, updated_at = ? WHERE id = 1",
                 [*fields.values(), 1 if bump else 0, now])


# ---------- resume text ----------

def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        try:
            text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
        except Exception as exc:
            raise ValueError(f"Couldn't read that PDF: {exc}") from exc
    elif name.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                root = ElementTree.fromstring(z.read("word/document.xml"))
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise ValueError("Couldn't read that Word file.") from exc
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        text = "\n".join("".join(t.text or "" for t in p.iter(f"{ns}t")) for p in root.iter(f"{ns}p"))
    elif name.endswith((".txt", ".md")):
        text = data.decode("utf-8", errors="replace")
    else:
        raise ValueError("Upload a PDF, Word (.docx), or text file.")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 200:
        raise ValueError("Found almost no text in that file. If it's a scanned PDF, upload a text-based "
                         "PDF or paste your resume as a .txt file.")
    return text


# ---------- jobs ----------

@jobs.handler("extract_profile")
def extract_profile(payload: dict) -> dict:
    with db.connect() as conn:
        p = load(conn)
    if not p["resume_text"]:
        raise ValueError("Upload your resume first.")
    data = ai.ask(
        "Extract this resume into the JSON schema. Copy facts exactly; don't add, infer or embellish. "
        "Use empty strings or empty lists for anything missing. Keep each bullet's wording, fixing only "
        "obvious typos. Dates as written (e.g. 'May 2025', 'Present').\n\nRESUME:\n" + p["resume_text"],
        system="You extract resumes into structured data with perfect fidelity.",
        schema=PROFILE_SCHEMA)
    with db.connect() as conn:
        current = load(conn)
        prefs = current["preferences"]
        if not prefs["school"] and data.get("education"):
            prefs["school"] = data["education"][0].get("school", "")
        merged = merge_profile(current["data"], data)
        _save(conn, data=json.dumps(merged), preferences=json.dumps(prefs))
    return {"ok": True}


@jobs.handler("suggest_phrasings")
def suggest_phrasings(payload: dict) -> dict:
    """Alternative phrasings of one point, checked against it. Returned for review, never saved."""
    with db.connect() as conn:
        p = require(conn)
    section, entry, point = find_point(p["data"], str(payload.get("point_id") or ""))
    if len(point["phrasings"]) >= MAX_PHRASINGS:
        raise ValueError(f"This point already has {MAX_PHRASINGS} phrasings. Remove one first.")
    if section == "experience":
        context = f"{entry.get('role')} at {entry.get('organization')}, {entry.get('start')} – {entry.get('end')}"
        current = (entry.get("end") or "").strip().lower() in ("present", "now", "current", "ongoing", "today")
    else:
        tech = ", ".join(entry.get("tech") or [])
        context = f"PROJECT {entry.get('name')}" + (f"; tech: {tech}" if tech else "")
        current = False
    others = "\n".join(f"- {s}" for s in point["phrasings"][1:])
    answer = ai.ask(
        f"Write {SUGGEST_COUNT} alternative phrasings of ONE resume bullet. Every phrasing must state exactly "
        "the same fact: the same action, tools, numbers, units and outcome. Change only the emphasis and "
        "structure, for example lead with the result, with the tool, or with the scale; make one under 15 "
        "words, one about 20 and one up to 25. Start each with a "
        f"{'present-tense verb, since the role is current' if current else 'past-tense verb'}. Do not add "
        "a tool, metric, purpose, outcome, adjective or scale the bullet doesn't state, and do not drop a "
        "number. Return the phrasings only.\n\n"
        f"CONTEXT: {context}\n\nBULLET: {point['phrasings'][0]}\n"
        + (f"\nPHRASINGS ALREADY IN USE (don't repeat them):\n{others}\n" if others else "")
        + f"\n{ai.HONESTY_RULES}",
        system="You rephrase resume bullets without changing a single fact.",
        schema=SUGGEST_SCHEMA)
    raw = answer.get("phrasings") if isinstance(answer, dict) and isinstance(answer.get("phrasings"), list) else []
    kept = validate_phrasings(raw, point)
    return {"point_id": point["id"], "suggestions": kept, "dropped": len(raw) - len(kept)}


# ---------- API ----------

def _public(p: dict) -> dict:
    return {k: p[k] for k in ("resume_filename", "data", "preferences", "version", "updated_at")} | \
        {"has_resume": bool(p["resume_text"]), "resume_chars": len(p["resume_text"] or "")}


@router.get("/api/profile")
def get_profile():
    with db.connect() as conn:
        p = load(conn)
        pending = conn.execute("SELECT id FROM ai_jobs WHERE kind = 'extract_profile' AND status IN "
                               "('queued', 'running') ORDER BY created_at DESC LIMIT 1").fetchone()
    return {**_public(p), "extract_job": pending["id"] if pending else None}


@router.post("/api/profile/resume")
async def upload_resume(file: UploadFile):
    data = await file.read(MAX_RESUME_BYTES + 1)
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(413, "That file is over 5 MB.")
    try:
        text = extract_text(file.filename or "", data)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    with db.connect() as conn:
        _save(conn, resume_filename=file.filename, resume_text=text)
    return {"job_id": jobs.submit("extract_profile", {}), "chars": len(text)}


class ProfileUpdate(BaseModel):
    data: dict | None = None
    preferences: dict | None = None


@router.put("/api/profile")
def update_profile(body: ProfileUpdate):
    fields = {}
    data = None
    if body.data is not None:
        data = normalize(body.data)
        fields["data"] = json.dumps(data)
        if len(fields["data"]) > MAX_DATA_CHARS:
            raise HTTPException(413, "That profile is too large to save.")
    if body.preferences is not None:
        unknown = set(body.preferences) - set(DEFAULT_PREFERENCES)
        if unknown:
            raise HTTPException(422, f"Unknown preference: {', '.join(sorted(unknown))}")
        fields["preferences"] = json.dumps({**DEFAULT_PREFERENCES, **body.preferences})
    if not fields:
        raise HTTPException(422, "Nothing to update.")
    with db.connect() as conn:
        # Preferences and facts bump the version; extra phrasings alone don't (see _save).
        bump = body.preferences is not None or (data is not None and _facts(load(conn)["data"]) != _facts(data))
        _save(conn, bump=bump, **fields)
        return _public(load(conn))
