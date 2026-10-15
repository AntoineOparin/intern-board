"""Writing outreach messages: LinkedIn connection notes, cold emails and follow-ups.

A short chain instead of one big prompt (see the lemlist and Regie guides on sales prompting):
  1. brief:  what this person cares about, a true reason to write to *them*, the single best proof
             from the profile for this posting, one small ask, and what to avoid (fast model);
  2. write:  the message, from the brief, with per-channel rules, banned phrases and short
             examples of the shape we want;
  3. check:  deterministic checks (length, banned phrases, invented numbers, placeholders,
             claiming to have applied when you haven't, ...);
  4. repair: one targeted fix if a check fails, then check again.
"""

import json
import re
import time

from . import ai, profile

CHANNELS = ("linkedin_note", "email", "follow_up")
FREE_NOTE_LIMIT, PREMIUM_NOTE_LIMIT = 200, 300   # LinkedIn's limits for invitation notes

RECIPIENTS = {
    "recruiter": ("a university or technical recruiter at the company",
                  "Recruiters want qualified, eligible candidates for open roles and care about timelines and "
                  "requirements. Good asks: whether the candidate fits a requirement (term, graduation date, "
                  "location), the timeline, or which role suits their background."),
    "engineer": ("someone who works in a role like the one the candidate is applying for",
                 "Engineers are busy and owe the candidate nothing. Curiosity about their kind of work lands better "
                 "than flattery. Good asks: one specific question, or 15 minutes to hear what the work is like. "
                 "Never ask for a referral in a first message."),
    "alum": ("a graduate of the candidate's school who works at the company",
             "The shared school is the hook; lead with it. Good asks: 15 minutes for advice on the company or role."),
    "hiring_manager": ("a manager who may hire for this role",
                       "Managers care whether a candidate can do the work. Good asks: what the team looks for in "
                       "interns, or whether a specific skill matters."),
}

# Phrases that make a message read as a template or as AI-written.
BANNED = [
    r"hope (this|you('re| are)|your|all is)", r"i am writing to", r"my name is", r"i came across your",
    r"reach(ing)? out", r"touch(ing)? base", r"circl(e|ing) back", r"just following up", r"following up on my",
    r"bump(ing)? this", r"checking in", r"pick your brain", r"quick question", r"passionate", r"leverag(e|ing)",
    r"synerg", r"thrilled", r"excited to", r"delve", r"esteemed", r"\bhuge fan\b", r"truly inspir",
    r"i('d| would) love to connect", r"looking forward to hearing", r"at your earliest convenience",
    r"cutting[- ]edge", r"dynamic team", r"fast[- ]paced", r"take (my|the) (skills|career) to the next level",
    r"\bkindly\b", r"don't hesitate", r"in today's",
]
_BANNED_RE = re.compile("|".join(f"(?:{b})" for b in BANNED), re.I)
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_APPLIED_CLAIM = re.compile(r"\bI(?:'ve| have)? (?:just |recently )?applied\b|\bmy application\b|\bI submitted\b", re.I)


def note_limit(prefs: dict) -> int:
    return PREMIUM_NOTE_LIMIT if prefs.get("linkedin_premium") else FREE_NOTE_LIMIT


# ---------- 1. brief ----------

BRIEF_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["recipient_cares_about", "hook", "proof", "ask", "avoid"],
    "properties": {
        "recipient_cares_about": {"type": "string", "description": "One sentence, inferred only from their role and the posting."},
        "hook": {"type": "object", "additionalProperties": False, "required": ["text", "basis"],
                 "properties": {"text": {"type": "string", "description": "Why write to THIS person, in under 15 words."},
                                "basis": {"type": "string", "enum": ["their_title", "their_location", "shared_school",
                                                                      "the_posting", "candidate_context", "the_company"]}}},
        "proof": {"type": "object", "additionalProperties": False, "required": ["fact", "label", "requirement"],
                  "properties": {"fact": {"type": "string", "description": "One true achievement from the profile, numbers verbatim."},
                                 "label": {"type": "string", "description": "That achievement in under 8 words, e.g. 'SSE feature at TS Imagine'."},
                                 "requirement": {"type": "string", "description": "The posting requirement or duty it matches."}}},
        "ask": {"type": "string", "description": "One small, specific ask they can answer in a line."},
        "avoid": {"type": "array", "items": {"type": "string"}, "description": "Things this message must not say or imply."},
    },
}


def _job_text(listing: dict, description: str | None) -> str:
    text = f"Company: {listing['company']}\nRole: {listing['title']}\nLocations: {listing.get('locations') or ''}"
    if description:
        text += f"\nPosting (excerpt):\n{description[:3500]}"
    return text


def _recipient_text(recipient: dict) -> str:
    who, what_they_care_about = RECIPIENTS[recipient["type"]]
    lines = [f"Type: {who}.", f"About this kind of recipient: {what_they_care_about}"]
    if recipient.get("name"):
        lines.append(f"Name: {recipient['name']}")
    if recipient.get("title"):
        lines.append(f"Current title (from their public profile): {recipient['title']}")
    if recipient.get("location"):
        lines.append(f"Location: {recipient['location']}")
    return "\n".join(lines)


def make_brief(p: dict, listing: dict, recipient: dict, *, channel: str, applied: bool, context: str,
               description: str | None, avoid_angle: str = "") -> dict:
    prompt = f"""Plan an outreach message from a university student to one person. Don't write the message.

JOB
{_job_text(listing, description)}

RECIPIENT
{_recipient_text(recipient)}

CANDIDATE STATUS: {"has applied to this role (tracker status: " + str(listing.get("status")) + ")" if applied else "has NOT applied yet"}.
{f"CONTEXT FROM THE CANDIDATE (true): {context}" if context else ""}
MESSAGE TYPE: {channel.replace("_", " ")}
{f"A previous draft used this angle; choose a clearly different hook or proof: {avoid_angle}" if avoid_angle else ""}

Decide:
- recipient_cares_about: what someone in their role likely cares about here. Infer only from their title, the
  role and the posting. Don't invent their team, projects, posts, or history.
- hook: a true, specific reason to write to this person rather than anyone else, e.g. their title matches the
  role's team, they're in the job's city, a shared school (only if the profile shows it and the recipient is an
  alum), or something in the posting. Never claim a connection, meeting or shared interest that isn't given.
- proof: the ONE profile achievement that best matches one requirement or duty in the posting. Copy numbers
  exactly. Prefer concrete results over lists of technologies.
- ask: one small ask that fits the recipient and message type, answerable in a line.
- avoid: claims to steer clear of, e.g. saying they applied when they haven't, a requirement they don't meet
  presented as met, relative dates (today is {time.strftime('%B %-d, %Y')}).

{profile.as_prompt_text(p)}"""
    return ai.ask(prompt, system="You plan honest, specific outreach for students. You never invent facts.",
                  schema=BRIEF_SCHEMA, model="sonnet", timeout=120)


# ---------- 2. write ----------

def _rules(channel: str, limit: int, applied: bool) -> str:
    if channel == "linkedin_note":
        return f"""LINKEDIN CONNECTION NOTE
- HARD LIMIT: {limit} characters including spaces and line breaks. Aim for {limit - 45}-{limit - 10}.
- Shape: "Hi <first name>," then who the candidate is and the exact role in one short clause, the hook in one
  short clause, then the ask as a question. Two or three sentences total.
- No pitch, no list of skills, no links, no signature (LinkedIn shows their name). Subject must be "".

Example of the shape (fictional people; don't reuse its facts):
Hi Dana, I'm a McGill CS student applying to Shopify's Winter 2027 backend internship. Since you recruit for Core Engineering, could I ask one question about the timeline?"""
    if channel == "email":
        return """COLD EMAIL
- Write it as if it's the third cold email they've read today: the first line must earn the second.
- Subject: 3-8 words, specific: the role or team plus one concrete detail. No "Quick question", no
  clickbait, no exclamation marks, no ALL CAPS.
- Body: 60-110 words in 2-3 short paragraphs. Sentences under 20 words. Plain words (8th-grade reading level).
- First sentence: about them or the role (the hook), not about the candidate's feelings.
- Then the proof: one achievement with its real numbers, tied to one thing the posting asks for.
- Then exactly one ask, phrased as a question they can answer in one line.
- Sign-off: "Thanks," then the candidate's full name, then school and program on one line. Add one link
  (LinkedIn, GitHub or portfolio) only if it's in the profile.

Example of the shape (fictional people; don't reuse its facts):
Subject: Backend intern, Winter 2027 (McGill CS)
Hi Dana,

I'm applying to Shopify's Backend Developer Intern role for Winter 2027, and saw you recruit for Core Engineering.

At Lightspeed (May to August 2025) I added Redis caching to a checkout API and cut p95 latency from 900 ms to 300 ms. The posting asks for exactly this kind of performance work.

Is the Winter 2027 cohort open to students graduating in 2028?

Thanks,
Alex Chen
McGill University, B.Sc. Computer Science"""
    return f"""FOLLOW-UP EMAIL (after applying)
- Never write "just following up", "bumping this", "circling back" or "checking in". Give them a reason to reply:
  ONE new, useful thing: a relevant result they may not have seen, or a specific question about the process.
- Subject: specific, naming the role. Body: 40-80 words, 2 short paragraphs.
- {"Mention once that they applied, with the role name." if applied else "They have NOT applied; don't write a follow-up that implies they did."}
- One ask, as a question. Sign-off as in a cold email: "Thanks," then full name, then school."""


STYLE = """STYLE
- Sound like a sharp, friendly student writing to a peer: direct, specific, human. Contractions are fine.
- Use the recipient's first name. Never use placeholders like [Name] or {Company}.
- No flattery ("impressed by", "huge fan", "amazing work"), no rhetorical questions, no exclamation marks,
  no emoji, no em dashes or en dashes (use commas or periods), no markdown.
- Never use these: "I hope this finds you well", "My name is", "I am writing to", "I came across your profile",
  "reach out", "touch base", "pick your brain", "quick question", "passionate", "leverage", "excited to",
  "thrilled", "I'd love to connect", "looking forward to hearing from you", "don't hesitate".
- Don't claim to know anything about the recipient beyond their name, title and location."""

DRAFT_SCHEMA_TEMPLATE = {
    "type": "object", "additionalProperties": False, "required": ["subject", "body"],
    "properties": {
        "subject": {"type": "string", "maxLength": 90, "description": "Email subject; empty string for a LinkedIn note."},
        "body": {"type": "string", "description": "The full message, plain text."},
    },
}


def _draft_schema(channel: str, limit: int) -> dict:
    schema = json.loads(json.dumps(DRAFT_SCHEMA_TEMPLATE))
    schema["properties"]["body"]["maxLength"] = limit if channel == "linkedin_note" else 1500
    return schema


def write(p: dict, listing: dict, recipient: dict, brief: dict, *, channel: str, applied: bool, context: str,
          limit: int) -> dict:
    prompt = f"""Write one outreach message from a university student, following the plan below.

PLAN
- What they care about: {brief["recipient_cares_about"]}
- Hook (why this person): {brief["hook"]["text"]}
- Proof: {brief["proof"]["fact"]} (matches: {brief["proof"]["requirement"]})
- Ask: {brief["ask"]}
- Avoid: {"; ".join(brief["avoid"]) or "nothing specific"}

JOB
{_job_text(listing, None)}

RECIPIENT
{_recipient_text(recipient)}
{f"CONTEXT FROM THE CANDIDATE (true; use it if it helps): {context}" if context else ""}
CANDIDATE STATUS: {"has applied" if applied else "has NOT applied yet; don't say or imply they applied"}.

{_rules(channel, limit, applied)}

{STYLE}

{ai.HONESTY_RULES}
Today is {time.strftime('%B %-d, %Y')}. Give dates as in the profile, never relative ("last summer").

Before answering, check your draft against every rule above and fix it. Output only the final message.

{profile.as_prompt_text(p)}"""
    result = ai.ask(prompt, system="You write short, specific, honest outreach that busy people answer.",
                    schema=_draft_schema(channel, limit))
    return {"subject": _clean(result.get("subject", "")).replace("\n", " ") if channel != "linkedin_note" else "",
            "body": _clean(result.get("body", ""))}


# ---------- 3. check ----------

def _known_numbers(*texts: str) -> set[str]:
    return {n.replace(",", "") for t in texts for n in re.findall(r"\d[\d,]*(?:\.\d+)?", t or "")}


def check(draft: dict, *, channel: str, limit: int, applied: bool, known_text: str) -> list[str]:
    """Problems a reader would notice. Empty means the draft passes."""
    body, subject = draft["body"], draft.get("subject", "")
    text = f"{subject}\n{body}"
    issues = []
    if channel == "linkedin_note" and len(body) > limit:
        issues.append(f"The note is {len(body)} characters; LinkedIn allows {limit}. Cut it to under {limit - 15}.")
    if channel != "linkedin_note":
        words = len(body.split())
        top = 130 if channel == "email" else 100
        if words > top:
            issues.append(f"The email is {words} words; keep it under {top - 20}.")
        if not subject:
            issues.append("Add a short, specific subject line.")
    if m := _BANNED_RE.search(text):
        issues.append(f'Remove the stock phrase "{m.group(0)}".')
    if "!" in text:
        issues.append("Remove exclamation marks.")
    if "—" in text or "–" in text:
        issues.append("Replace em/en dashes with commas or periods.")
    if _EMOJI_RE.search(text):
        issues.append("Remove emoji.")
    if re.search(r"\[[^\]]*\]|\{[^}]*\}|<[^>]+>", text):
        issues.append("Replace the placeholder with real text or remove it.")
    if not applied and _APPLIED_CLAIM.search(text):
        issues.append("They haven't applied yet; don't say or imply they did.")
    # Numbers that are claims must come from the profile or posting. Durations in an ask ("15 minutes")
    # and years are fine.
    claims = re.sub(r"\b\d{1,2}[- ]?(?:minutes?|mins?)\b|\b20\d\d\b", " ", text, flags=re.I)
    known = _known_numbers(known_text)
    invented = sorted(n for n in _known_numbers(claims) - known if len(n) > 1 or n not in "123456789")
    if invented:
        issues.append(f"These numbers aren't in the profile or the posting: {', '.join(invented)}. Remove or correct them.")
    return issues


# ---------- 4. repair ----------

def repair(draft: dict, issues: list[str], *, channel: str, limit: int, known_text: str) -> dict:
    prompt = f"""Fix this outreach message. Change only what the issues require; keep the facts, ask and tone.

ISSUES
- """ + "\n- ".join(issues) + f"""

MESSAGE
{("Subject: " + draft["subject"] + chr(10)) if draft.get("subject") else ""}{draft["body"]}

{"Keep the note under " + str(limit - 15) + " characters." if channel == "linkedin_note" else ""}
Facts you may use (anything else must not appear):
{known_text[:6000]}"""
    result = ai.ask(prompt, system="You edit outreach messages precisely and never add facts.",
                    schema=_draft_schema(channel, limit), model="sonnet", timeout=120)
    return {"subject": _clean(result.get("subject", "")).replace("\n", " ") if channel != "linkedin_note" else "",
            "body": _clean(result.get("body", ""))}


def _clean(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("—", ", ").replace("–", "-")
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+\n", "\n", s)).strip()


# ---------- the whole chain ----------

def compose(p: dict, listing: dict, recipient: dict, *, channel: str, applied: bool, context: str = "",
            description: str | None = None, previous: dict | None = None) -> dict:
    """Brief -> write -> check -> (repair -> check). Returns {subject, body, angle, checks}."""
    limit = note_limit(p["preferences"])
    avoid_angle = ""
    if previous and previous.get("angle"):
        avoid_angle = previous["angle"]
    brief = make_brief(p, listing, recipient, channel=channel, applied=applied, context=context,
                       description=description, avoid_angle=avoid_angle)
    known_text = "\n".join([json.dumps(p["data"]), json.dumps(p["preferences"]), listing["title"],
                            listing.get("locations") or "", description or "", context or ""])
    draft = write(p, listing, recipient, brief, channel=channel, applied=applied, context=context, limit=limit)
    issues = check(draft, channel=channel, limit=limit, applied=applied, known_text=known_text)
    if issues:
        draft = repair(draft, issues, channel=channel, limit=limit, known_text=known_text)
        issues = check(draft, channel=channel, limit=limit, applied=applied, known_text=known_text)
    if not draft["body"]:
        raise ai.AIError("Claude returned an empty draft. Try again.")
    if channel == "linkedin_note" and len(draft["body"]) > limit:
        raise ValueError(f"The note came out at {len(draft['body'])} characters, over LinkedIn's {limit}. "
                         "Try again, or write an email instead.")
    angle = f"{brief['hook']['text'].rstrip('.')} · {brief['proof'].get('label') or brief['proof']['fact']}"
    return {**draft, "angle": angle[:200], "checks": issues, "limit": limit}
