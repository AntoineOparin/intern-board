"""Your resume and profile: the source of truth every AI feature writes from."""

import io
import json
import re
import time
import zipfile
from xml.etree import ElementTree

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from . import ai, db, jobs

router = APIRouter()

MAX_RESUME_BYTES = 5 * 1024 * 1024

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


# ---------- reading ----------

def load(conn) -> dict:
    """The current profile row as a dict, with JSON fields decoded. Safe to call from any feature."""
    row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    if not row:
        return {"resume_filename": None, "resume_text": "", "data": {}, "preferences": dict(DEFAULT_PREFERENCES),
                "version": 0, "updated_at": None}
    p = dict(row)
    p["data"] = json.loads(p["data"] or "{}")
    p["preferences"] = {**DEFAULT_PREFERENCES, **json.loads(p["preferences"] or "{}")}
    return p


def require(conn) -> dict:
    """The profile, or a ValueError the user sees if there's no resume yet."""
    p = load(conn)
    if not p["data"]:
        raise ValueError("Add your resume on the Profile tab first.")
    return p


def as_prompt_text(p: dict) -> str:
    """The profile and preferences, formatted for a prompt."""
    return (f"CANDIDATE PROFILE (JSON):\n{json.dumps(p['data'], indent=1)}\n\n"
            f"CANDIDATE PREFERENCES (JSON):\n{json.dumps(p['preferences'], indent=1)}")


def _save(conn, **fields) -> None:
    now = int(time.time())
    conn.execute("INSERT INTO profile (id, updated_at) VALUES (1, ?) ON CONFLICT (id) DO NOTHING", (now,))
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE profile SET {sets}, version = version + 1, updated_at = ? WHERE id = 1",
                 [*fields.values(), now])


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
        prefs = load(conn)["preferences"]
        if not prefs["school"] and data.get("education"):
            prefs["school"] = data["education"][0].get("school", "")
        _save(conn, data=json.dumps(data), preferences=json.dumps(prefs))
    return {"ok": True}


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
    if body.data is not None:
        fields["data"] = json.dumps(body.data)
    if body.preferences is not None:
        unknown = set(body.preferences) - set(DEFAULT_PREFERENCES)
        if unknown:
            raise HTTPException(422, f"Unknown preference: {', '.join(sorted(unknown))}")
        fields["preferences"] = json.dumps({**DEFAULT_PREFERENCES, **body.preferences})
    if not fields:
        raise HTTPException(422, "Nothing to update.")
    with db.connect() as conn:
        _save(conn, **fields)
        return _public(load(conn))
