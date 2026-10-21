"""Checks that keep generated text honest: numbers must come from the profile, no filler phrases.

Shared by documents.py (tailored resumes, cover letters) and profile.py (suggested phrasings).
The prompt-side rules live in ai.HONESTY_RULES.
"""

import re

BANNED = ("i am writing to express", "passionate", "leverage", "synergy", "dynamic", "cutting-edge")


def numbers(text: str) -> set[str]:
    """Every number in the text, without trailing punctuation: "14s to 2s." -> {"14", "2"}."""
    return {m.rstrip(".,") for m in re.findall(r"\d[\d,.]*", text)}


def unverified_numbers(texts: list[str], source: str) -> list[str]:
    """Numbers in `texts` that don't appear anywhere in `source`."""
    known = numbers(source)
    found = set()
    for t in texts:
        found |= numbers(t)
    return sorted(n for n in found if n not in known)


def banned_hits(text: str) -> list[str]:
    lowered = text.lower()
    return [p for p in BANNED if p in lowered]


def clean(items, limit: int | None = None) -> list[str]:
    """Strings with whitespace collapsed and blanks dropped, optionally capped."""
    out = [re.sub(r"\s+", " ", str(s)).strip() for s in items or []]
    out = [s for s in out if s]
    return out[:limit] if limit else out
