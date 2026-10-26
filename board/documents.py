"""Tailored resumes and cover letters for a listing, written by Claude from your profile.

For a resume Claude only chooses and orders: it picks points and phrasings from the profile by
number and the server copies the text verbatim (at most one phrasing per point). Names, employers,
roles, dates, schools and links are copied from the profile too, skills are limited to the ones
the profile lists, and every number in generated text is checked against the profile.

Content JSON stored in `documents.content`:

  resume:       {header: {name, contact[], links[{label, url}]},
                 education[{school, degree, location, dates, details[]}],
                 experience[{source_id, organization, role, location, dates, bullets[],
                             refs[{point_id, phrasing} | null]}],   -- refs[i] says where bullets[i] came from
                 projects[{source_id, name, tech, link, dates, bullets[], refs[]}],
                 skills[{label, items[]}],
                 awards[],
                 notes: {emphasized[], gaps[], description_used, checks[]}}

  cover_letter: {tone, header: {...as above}, date, recipient, greeting, paragraphs[], closing,
                 signature, notes: {drew_on[], gaps[], description_used, word_count, checks[]}}

Edits on the document page may add formatting (never generated, only saved):
  - any line of text (a field, or an item of bullets, details, paragraphs, contact) can be a list of
    runs instead of a string: [{t, b?, i?, u?, c?: "#rrggbb"}], with "\n" in t for a line break.
  - format: {page: {margins: {top, right, bottom, left} (inches), size: "auto" | pt, lineHeight, font},
             styles: {<path, e.g. "experience.0.bullets.2">: {align?, size? (x base size), before?, after? (lines)}}}
  - headings: {education?, experience?, projects?, skills?}, renamed section titles.
"""

import json
import re
import time
import unicodedata
import uuid
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import ai, db, docx_export, honesty, jobs, postings, profile

router = APIRouter()

KINDS = ("resume", "cover_letter")
TONES = ("formal", "conversational", "enthusiastic")
MAX_BULLETS = 4
MAX_PROJECTS = 3
MAX_CONTENT_CHARS = 60_000

_str = {"type": "string"}
_strs = {"type": "array", "items": _str}


def _obj(props: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


_picks = {"type": "array",
          "description": "Bullets in order: the point, and the phrasing of it that fits this job best. "
                         "At most one pick per point.",
          "items": _obj({"point": {"type": "integer"}, "phrasing": {"type": "integer"}})}

RESUME_SCHEMA = _obj({
    "experience": {"type": "array", "description": "Roles to include, most relevant first or reverse-chronological.",
                   "items": _obj({"source_index": {"type": "integer", "description": "Index into profile.experience."},
                                  "picks": _picks})},
    "projects": {"type": "array", "description": "The 2-3 most relevant projects.",
                 "items": _obj({"source_index": {"type": "integer", "description": "Index into profile.projects."},
                                "picks": _picks})},
    "skills": {"type": "array", "description": "Skill groups, most relevant first.",
               "items": _obj({"label": _str, "items": _strs})},
    "notes": _obj({
        "emphasized": {**_strs, "description": "What you prioritised and why, one short sentence each."},
        "gaps": {**_strs, "description": "Requirements in the posting the profile doesn't show. Be honest."},
        "description_used": {"type": "boolean"},
    }),
})

LETTER_SCHEMA = _obj({
    "greeting": _str,
    "paragraphs": {**_strs, "description": "3-4 paragraphs, 250-350 words in total."},
    "closing": {"type": "string", "description": "e.g. 'Sincerely,' or 'Best regards,'"},
    "notes": _obj({
        "drew_on": {**_strs, "description": "The profile experiences or projects the letter draws on."},
        "gaps": {**_strs, "description": "Requirements in the posting the profile doesn't show."},
        "description_used": {"type": "boolean"},
    }),
})

TONE_GUIDE = {
    "formal": "Formal and precise: complete sentences, no contractions, restrained.",
    "conversational": "Conversational and direct: plain words, contractions are fine, like a thoughtful email.",
    "enthusiastic": "Warm and energetic, but specific: show real interest through concrete details, "
                    "not adjectives or exclamation marks.",
}

BANNED = honesty.BANNED
# Relative dates go wrong easily ("last summer" for a job two summers ago); dates should be as written.
RELATIVE = ("last summer", "this summer", "last fall", "this fall", "last winter", "this winter", "last spring",
            "this spring", "last year", "this year", "recently", "currently")


# ---------- helpers ----------

def _listing(conn, listing_id: str) -> dict:
    row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if not row:
        raise ValueError("That listing no longer exists.")
    return dict(row)


def _posting_text(listing_id: str, pasted: str | None) -> str | None:
    if pasted and pasted.strip():
        if len(pasted.strip()) < 50:
            raise ValueError("That job description is too short. Paste the full posting.")
        postings.save(listing_id, pasted.strip())
    try:
        return postings.description(listing_id)["text"]
    except ai.AIError:
        return None  # write from the title alone rather than fail


def _listing_prompt(listing: dict, text: str | None) -> str:
    terms = ", ".join(t for t in (listing.get("terms") or "").split(",") if t)
    head = (f"JOB: {listing['title']} at {listing['company']}\nLocation: {listing.get('locations') or 'not given'}"
            + (f"\nTerm: {terms}" if terms else ""))
    if text:
        return f"{head}\n\nJOB DESCRIPTION:\n{text}"
    return (f"{head}\n\nJOB DESCRIPTION: not available. Work from the title and company only, keep claims "
            "about the role general, and set description_used to false.")


def _dates(start: str, end: str) -> str:
    start, end = (start or "").strip(), (end or "").strip()
    return f"{start} – {end}" if start and end else start or end


def _header(data: dict) -> dict:
    contact = [v for v in (data.get("location"), data.get("phone"), data.get("email")) if v]
    links = [{"label": l.get("label", ""), "url": l.get("url", "")} for l in data.get("links") or [] if l.get("url")]
    return {"name": data.get("name", ""), "contact": contact, "links": links}


_numbers = honesty.numbers
_unverified_numbers = honesty.unverified_numbers
_clean = honesty.clean


def _checks(texts: list[str], source: str) -> list[str]:
    checks = []
    missing = _unverified_numbers(texts, source)
    if missing:
        checks.append(f"Numbers not found in your profile: {', '.join(missing)}. Check them before sending.")
    joined = " ".join(texts).lower()
    hits = [p for p in BANNED if p in joined]
    if hits:
        checks.append(f"Contains filler phrases: {', '.join(hits)}.")
    relative = [p for p in RELATIVE if re.search(rf"\b{p}\b", joined)]
    if relative:
        checks.append(f"Uses relative dates ({', '.join(relative)}); check they're still true.")
    return checks


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+#]", "", s.lower())


def _resolve(entry: dict, picks) -> tuple[list[str], list[dict]]:
    """Verbatim bullets for Claude's picks: (texts, refs), at most one phrasing per point.

    Bad or missing picks fall back to the entry's first points, each in its primary phrasing.
    """
    points = entry.get("points") or []
    used, texts, refs = set(), [], []
    for pk in picks if isinstance(picks, list) else []:
        if not isinstance(pk, dict):
            continue
        i, j = pk.get("point"), pk.get("phrasing")
        if not isinstance(i, int) or not 0 <= i < len(points) or i in used:
            continue
        phrasings = points[i]["phrasings"]
        if not isinstance(j, int) or not 0 <= j < len(phrasings):
            j = 0
        used.add(i)
        texts.append(phrasings[j])
        refs.append({"point_id": points[i]["id"], "phrasing": j})
        if len(texts) == MAX_BULLETS:
            break
    if not texts:
        for pt in points[:MAX_BULLETS]:
            texts.append(pt["phrasings"][0])
            refs.append({"point_id": pt["id"], "phrasing": 0})
    return texts, refs


def build_resume(data: dict, answer: dict, description_used: bool) -> dict:
    """Combine Claude's selections with text and facts copied from the profile."""
    data = profile.normalize(data)
    exp_src, proj_src = data.get("experience") or [], data.get("projects") or []

    def pick(items, src, limit):
        seen, out = set(), []
        for it in items or []:
            i = it.get("source_index")
            if not isinstance(i, int) or not 0 <= i < len(src) or i in seen:
                continue
            seen.add(i)
            out.append((src[i], *_resolve(src[i], it.get("picks"))))
        return out[:limit] if limit else out

    experience = [{"source_id": e["id"], "organization": e.get("organization", ""), "role": e.get("role", ""),
                   "location": e.get("location", ""), "dates": _dates(e.get("start"), e.get("end")),
                   "bullets": b, "refs": r} for e, b, r in pick(answer.get("experience"), exp_src, None)
                  or pick([{"source_index": i} for i in range(len(exp_src))], exp_src, None)]
    projects = [{"source_id": p["id"], "name": p.get("name", ""), "tech": ", ".join(p.get("tech") or []),
                 "link": p.get("link", ""), "dates": p.get("date", ""), "bullets": b, "refs": r}
                for p, b, r in pick(answer.get("projects"), proj_src, MAX_PROJECTS)]

    # Skills: only ones the profile lists, in Claude's order; anything Claude skipped goes at the end.
    have = {}
    for group in (data.get("skills") or {}).values():
        for s in group or []:
            have.setdefault(_norm(s), s)
    used, skills = set(), []
    for g in answer.get("skills") or []:
        items = []
        for s in g.get("items") or []:
            key = _norm(s)
            if key in have and key not in used:
                used.add(key)
                items.append(have[key])
        if items:
            skills.append({"label": str(g.get("label") or "Skills").strip(), "items": items})
    if not skills:  # fall back to the profile's own grouping
        labels = {"languages": "Languages", "frameworks": "Frameworks", "tools": "Tools", "other": "Other"}
        skills = [{"label": labels.get(k, k.title()), "items": list(v)}
                  for k, v in (data.get("skills") or {}).items() if v]

    education = []
    for e in data.get("education") or []:
        degree = ", ".join(v for v in (e.get("degree"), e.get("field")) if v)
        details = ([f"GPA: {e['gpa']}" if not re.search(r"gpa|average|%", e["gpa"], re.I) else e["gpa"]]
                   if e.get("gpa") else []) + _clean(e.get("details"))
        education.append({"school": e.get("school", ""), "degree": degree, "location": e.get("location", ""),
                          "dates": _dates(e.get("start"), e.get("end")), "details": details})

    notes = answer.get("notes") or {}
    texts = [b for x in experience + projects for b in x["bullets"]]
    return {
        "header": _header(data),
        "education": education,
        "experience": experience,
        "projects": projects,
        "skills": skills,
        "awards": _clean(data.get("awards")),
        "notes": {"emphasized": _clean(notes.get("emphasized")), "gaps": _clean(notes.get("gaps")),
                  "description_used": description_used,
                  "checks": _checks(texts, json.dumps(data, ensure_ascii=False))},
    }


def build_letter(data: dict, answer: dict, tone: str, listing: dict, description: str | None) -> dict:
    paragraphs = _clean(answer.get("paragraphs"))
    if not paragraphs:
        raise ai.AIError("Claude returned an empty letter. Try again.")
    notes = answer.get("notes") or {}
    words = sum(len(p.split()) for p in paragraphs)
    source = json.dumps(data, ensure_ascii=False) + listing["title"] + listing["company"] + (description or "")
    checks = _checks(paragraphs, source)
    if not 200 <= words <= 400:
        checks.append(f"The letter is {words} words; aim for 250–350.")
    return {
        "tone": tone,
        "header": _header(data),
        "date": date.today().strftime("%B %-d, %Y"),
        "recipient": f"{listing['company']} hiring team",
        "greeting": (answer.get("greeting") or f"Dear {listing['company']} hiring team,").strip(),
        "paragraphs": paragraphs,
        "closing": (answer.get("closing") or "Sincerely,").strip(),
        "signature": data.get("name", ""),
        "notes": {"drew_on": _clean(notes.get("drew_on")), "gaps": _clean(notes.get("gaps")),
                  "description_used": description is not None, "word_count": words, "checks": checks},
    }


def _indexed(data: dict) -> str:
    """Every entry, point and phrasing with the numbers Claude picks by."""
    lines = ["INDEX OF PROFILE POINTS. Use these source_index, point and phrasing numbers; the server inserts "
             "the exact text of each pick."]

    def points(entry):
        for i, pt in enumerate(entry.get("points") or []):
            for j, s in enumerate(pt["phrasings"][:profile.MAX_PHRASINGS]):
                lines.append(f"  point {i}, phrasing {j}: {s}")

    def flag(entry):
        return " — not on the latest resume" if entry.get("missing_from_resume") else ""

    for i, e in enumerate(data.get("experience") or []):
        dates = _dates(e.get("start"), e.get("end"))
        lines.append(f"experience[{i}]: {e.get('role')} at {e.get('organization')}" + (f" ({dates})" if dates else "")
                     + flag(e))
        points(e)
    for i, p in enumerate(data.get("projects") or []):
        tech = ", ".join(p.get("tech") or [])
        lines.append(f"projects[{i}]: {p.get('name')}" + (f" — {tech}" if tech else "") + flag(p))
        points(p)
    return "\n".join(lines)


def _save(kind: str, listing: dict, content: dict, version: int) -> str:
    doc_id = uuid.uuid4().hex[:12]
    now = int(time.time())
    title = f"{'Resume' if kind == 'resume' else 'Cover letter'} · {listing['company']}"
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id, listing_id, kind, title, content, profile_version, created_at, "
                     "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (doc_id, listing["id"], kind, title, json.dumps(content), version, now, now))
    return doc_id


# ---------- jobs ----------

@jobs.handler("tailor_resume")
def tailor_resume(payload: dict) -> dict:
    listing_id = payload.get("listing_id") or ""
    with db.connect() as conn:
        listing = _listing(conn, listing_id)
        p = profile.require(conn)
    text = _posting_text(listing_id, payload.get("description"))
    answer = ai.ask(
        "Tailor this candidate's resume to the job below. Return selections only: the server copies the "
        "chosen bullet text, names, employers, dates, schools and links from the profile.\n\n"
        "Rules:\n"
        "- It must fit on ONE page. Include every experience entry unless it is clearly irrelevant and "
        "the page is full. Pick the 2-3 most relevant projects.\n"
        "- Bullets: choose from the INDEX below by point and phrasing number. Never write bullet text. "
        "Each point is one fact, so pick at most one phrasing per point. 3-4 picks per role, never more "
        "than the role has points. Choose the phrasing whose emphasis best matches this job, and order "
        "the picks most relevant first.\n"
        "- Skills: use only skills listed in the profile, grouped (e.g. Languages, Frameworks, Tools), "
        "with the ones the job asks for first.\n"
        "- notes.emphasized: 2-4 short sentences on what you prioritised and why.\n"
        "- notes.gaps: specific requirements in the posting the profile doesn't show. Be honest; an empty "
        "list only if there truly are none.\n\n"
        f"{ai.HONESTY_RULES}\n\n{profile.as_prompt_text(p, bullets=False)}\n\n{_indexed(p['data'])}\n\n"
        f"{_listing_prompt(listing, text)}",
        system="You are a careful resume editor for software internship applications. You never invent facts.",
        schema=RESUME_SCHEMA)
    content = build_resume(p["data"], answer, text is not None)
    return {"document_id": _save("resume", listing, content, p["version"])}


@jobs.handler("cover_letter")
def cover_letter(payload: dict) -> dict:
    listing_id = payload.get("listing_id") or ""
    tone = payload.get("tone") or "formal"
    if tone not in TONES:
        raise ValueError(f"Unknown tone: {tone}. Choose formal, conversational or enthusiastic.")
    with db.connect() as conn:
        listing = _listing(conn, listing_id)
        p = profile.require(conn)
    text = _posting_text(listing_id, payload.get("description"))
    answer = ai.ask(
        f"Write a cover letter from this candidate for the job below.\n\nTone: {TONE_GUIDE[tone]}\n\n"
        "Rules:\n"
        "- 3-4 short paragraphs, 250-350 words in total, no headings or bullet points.\n"
        "- Open with something specific about this company or role (from the description) and why it fits "
        "the candidate. Do not open with 'I am writing to express my interest' or any variant.\n"
        "- Draw on 1-2 real experiences or projects from the profile, with their real details and numbers "
        "exactly as written. Connect them to what the job asks for.\n"
        "- Mention nothing about the company that isn't in the description or the listing. Don't invent "
        f"names: greet the hiring team (e.g. 'Dear {listing['company']} hiring team,') unless the description names "
        "the hiring contact.\n"
        f"- Today is {date.today():%B %-d, %Y}. Refer to past work by the dates in the profile (e.g. 'in "
        "summer 2025'), never with relative words like 'last summer', 'recently' or 'currently'.\n"
        "- Don't claim feelings, preferences or plans the profile doesn't support; plain interest in this "
        "role is fine.\n"
        "- End with a brief, plain closing paragraph about availability or next steps, using only the "
        "candidate's preferences for terms or dates. No sign-off name: the server adds it.\n"
        "- notes.drew_on: which experiences/projects you used. notes.gaps: requirements the profile "
        "doesn't show.\n\n"
        f"{ai.HONESTY_RULES}\n\n{profile.as_prompt_text(p)}\n\n{_listing_prompt(listing, text)}",
        system="You write concise, specific cover letters for software internship applications. "
               "You never invent facts.",
        schema=LETTER_SCHEMA)
    content = build_letter(p["data"], answer, tone, listing, text)
    return {"document_id": _save("cover_letter", listing, content, p["version"])}


# ---------- API ----------

def _row(row, current_version: int | None = None, with_content=True) -> dict:
    d = dict(row)
    d["content"] = json.loads(d["content"] or "{}")
    if not with_content:
        notes = d.pop("content").get("notes") or {}
        d["notes"] = notes
    if current_version is not None:
        d["stale"] = d["profile_version"] is not None and d["profile_version"] != current_version
    return d


def _current_version(conn) -> int:
    row = conn.execute("SELECT version FROM profile WHERE id = 1").fetchone()
    return row["version"] if row else 0


@router.get("/api/documents")
def list_documents(listing_id: str = ""):
    sql = "SELECT * FROM documents WHERE kind IN (?, ?)"
    args: list = list(KINDS)
    if listing_id:
        sql += " AND listing_id = ?"
        args.append(listing_id)
    with db.connect() as conn:
        version = _current_version(conn)
        rows = conn.execute(sql + " ORDER BY created_at DESC, rowid DESC", args).fetchall()
    return {"items": [_row(r, version, with_content=False) for r in rows]}


@router.get("/api/documents/posting/{listing_id:path}")
def posting_status(listing_id: str):
    """What job description is cached for a listing, without fetching anything."""
    with db.connect() as conn:
        row = conn.execute("SELECT source, fetched_at, length(text) AS chars FROM posting_details "
                           "WHERE listing_id = ?", (listing_id,)).fetchone()
    return dict(row) | {"available": True} if row else {"available": False, "source": None,
                                                         "fetched_at": None, "chars": 0}


def _get(conn, doc_id: str):
    row = conn.execute(f"SELECT * FROM documents WHERE id = ? AND kind IN ({','.join('?' * len(KINDS))})",
                       (doc_id, *KINDS)).fetchone()
    if not row:
        raise HTTPException(404, "That document doesn't exist.")
    return row


@router.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    with db.connect() as conn:
        doc = _row(_get(conn, doc_id), _current_version(conn))
        listing = conn.execute("SELECT company, title, url FROM listings WHERE id = ?",
                               (doc["listing_id"],)).fetchone()
    return doc | {"listing": dict(listing) if listing else None}


class DocumentUpdate(BaseModel):
    content: dict
    title: str | None = Field(None, max_length=200)


REQUIRED = {"resume": ("header", "education", "experience", "projects", "skills"),
            "cover_letter": ("greeting", "paragraphs", "closing", "signature")}
FONTS = ("Source Serif 4", "Georgia", "Times New Roman", "Arial", "Helvetica")
ALIGNS = ("left", "center", "right", "justify")
MAX_STYLES = 1000
_style_key = re.compile(r"^[a-z_]+(\.[a-z0-9_]+)*$")
_colour = re.compile(r"^#[0-9a-f]{6}$")


def _is_runs(value) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(r, dict) and "t" in r for r in value)


def _num(value, lo: float, hi: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and lo <= value <= hi


def _check_runs(runs: list) -> None:
    for r in runs:
        if set(r) - {"t", "b", "i", "u", "c"} or not isinstance(r["t"], str):
            raise HTTPException(422, "Formatted text has an unknown part.")
        if any(k in r and not isinstance(r[k], bool) for k in ("b", "i", "u")):
            raise HTTPException(422, "Bold, italic and underline must be true or false.")
        if "c" in r and not (isinstance(r["c"], str) and _colour.match(r["c"])):
            raise HTTPException(422, "Text colours must look like #1f3a5f.")


def _check_text(value) -> None:
    """Every list of runs anywhere in the content must be well formed."""
    if _is_runs(value):
        _check_runs(value)
    elif isinstance(value, list):
        for v in value:
            _check_text(v)
    elif isinstance(value, dict):
        for k, v in value.items():
            if k != "format":
                _check_text(v)


def _check_format(fmt) -> None:
    if fmt is None:
        return
    if not isinstance(fmt, dict) or set(fmt) - {"page", "styles"}:
        raise HTTPException(422, "The page format isn't valid.")
    page = fmt.get("page") or {}
    if not isinstance(page, dict) or set(page) - {"margins", "size", "lineHeight", "font"}:
        raise HTTPException(422, "The page format isn't valid.")
    margins = page.get("margins") or {}
    if (not isinstance(margins, dict) or set(margins) - {"top", "right", "bottom", "left"}
            or not all(_num(v, 0.25, 1.5) for v in margins.values())):
        raise HTTPException(422, "Margins must be between 0.25 and 1.5 inches.")
    if "size" in page and page["size"] != "auto" and not _num(page["size"], 8, 14):
        raise HTTPException(422, "The text size must be Auto or between 8 and 14pt.")
    if "lineHeight" in page and not _num(page["lineHeight"], 1, 2):
        raise HTTPException(422, "Line spacing must be between 1 and 2.")
    if "font" in page and page["font"] not in FONTS:
        raise HTTPException(422, f"The font must be one of: {', '.join(FONTS)}.")
    styles = fmt.get("styles") or {}
    if not isinstance(styles, dict) or len(styles) > MAX_STYLES:
        raise HTTPException(422, "There is too much formatting to save.")
    for key, st in styles.items():
        if not _style_key.match(key) or not isinstance(st, dict) or set(st) - {"align", "size", "before", "after"}:
            raise HTTPException(422, f"The formatting for {key[:60]} isn't valid.")
        if ("align" in st and st["align"] not in ALIGNS) or ("size" in st and not _num(st["size"], 0.5, 4)) \
                or any(k in st and not _num(st[k], 0, 4) for k in ("before", "after")):
            raise HTTPException(422, f"The formatting for {key[:60]} isn't valid.")


def _check_headings(headings) -> None:
    if headings is None:
        return
    if not isinstance(headings, dict) or set(headings) - set(docx_export.HEADINGS) \
            or not all(isinstance(v, str) or _is_runs(v) for v in headings.values()):
        raise HTTPException(422, "Section titles must be text.")


@router.put("/api/documents/{doc_id}")
def update_document(doc_id: str, body: DocumentUpdate):
    encoded = json.dumps(body.content)
    if len(encoded) > MAX_CONTENT_CHARS:
        raise HTTPException(413, "That document is too large to save.")
    with db.connect() as conn:
        row = _get(conn, doc_id)
        missing = [k for k in REQUIRED[row["kind"]] if k not in body.content]
        if missing:
            raise HTTPException(422, f"The document is missing: {', '.join(missing)}.")
        if row["kind"] == "cover_letter" and not all(isinstance(p, str) or _is_runs(p)
                                                     for p in body.content["paragraphs"]):
            raise HTTPException(422, "Paragraphs must be text.")
        _check_text(body.content)
        _check_format(body.content.get("format"))
        _check_headings(body.content.get("headings"))
        conn.execute("UPDATE documents SET content = ?, title = COALESCE(?, title), updated_at = ? WHERE id = ?",
                     (encoded, body.title, int(time.time()), doc_id))
        return _row(_get(conn, doc_id), _current_version(conn))


def _filename(name: str, kind: str, company: str) -> tuple[str, str]:
    """(ASCII fallback, UTF-8 name) for Content-Disposition."""
    full = " – ".join(v for v in (name, "Resume" if kind == "resume" else "Cover letter", company) if v)
    full = re.sub(r'[\\/:*?"<>|\r\n]+', " ", full).strip()[:120] or "Document"
    ascii_name = unicodedata.normalize("NFKD", full.replace("–", "-")).encode("ascii", "ignore").decode()
    return f"{ascii_name or 'Document'}.docx", f"{full}.docx"


@router.get("/api/documents/{doc_id}/docx")
def download_docx(doc_id: str, fs: float = 11, sp: float = 1):
    """The document as a Word file, at the base size and spacing the page fitted to."""
    with db.connect() as conn:
        doc = _row(_get(conn, doc_id))
        listing = conn.execute("SELECT company FROM listings WHERE id = ?", (doc["listing_id"],)).fetchone()
    content = doc["content"]
    company = listing["company"] if listing else ""
    ascii_name, full = _filename(docx_export.plain((content.get("header") or {}).get("name")), doc["kind"], company)
    data = docx_export.build(doc["kind"], content, fs=min(max(fs, 6), 16), sp=min(max(sp, 0.5), 1.5),
                             title=full.removesuffix(".docx"))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; "
                                                    f"filename*=UTF-8''{quote(full)}"})


@router.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    with db.connect() as conn:
        _get(conn, doc_id)
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return {"ok": True}
