"""Community-maintained internship lists on GitHub, besides SimplifyJobs.

Each fetcher returns listings in the same shape as sources.simplify_listings(). Listings are
de-duplicated against higher-priority sources in sources.refresh().
"""

import hashlib
import json
import re
import time
import urllib.request
from datetime import datetime

from . import ats
from .locations import classify, US_STATES, US_NAMES, CA_PROVINCES

# Order matters: an earlier source wins when the same internship appears in several.
SOURCES = {
    "negarprh": {
        "label": "Canadian Tech Internships",
        "repo": "https://github.com/negarprh/Canadian-Tech-Internships-2027",
        "url": "https://raw.githubusercontent.com/negarprh/Canadian-Tech-Internships-2027/main/README.md",
    },
    "michelleokolie": {
        "label": "Canada Tech Internships Summer 2027",
        "repo": "https://github.com/michelleokolie/canada-tech-internships-summer-2027",
        "url": "https://raw.githubusercontent.com/michelleokolie/canada-tech-internships-summer-2027/main/.github/scripts/listings.json",
    },
    "frogg": {
        # Canada only, refreshed every 30 minutes, about 40 Montreal internships at a time. No license
        # file: we link to each posting and credit the repository, as for the lists above.
        "label": "Frogg Canadian Internships",
        "repo": "https://github.com/seun-ipaye/frogg-canadian-internships",
        "url": "https://raw.githubusercontent.com/seun-ipaye/frogg-canadian-internships/main/listings.json",
    },
    "zapply": {
        # Reuse terms: credit Zapply and link back to the repository (see its README, "Data & Reuse").
        "label": "Zapply",
        "repo": "https://github.com/zapplyjobs/Internships-2027",
        "url": "https://raw.githubusercontent.com/zapplyjobs/Internships-2027/main/README.md",
    },
}

ZAPPLY_SECTIONS = {"Software Engineering", "Data Science & AI", "Hardware & Engineering",
                   "Product, Design & Research"}
_SEASON = ats.SEASON
# "Summer 2027", "Été 2027", and "Summer/Fall 2027" -> both terms.
TERM_IN_TITLE = re.compile(rf"\b({_SEASON}(?:\s*[/&,]\s*{_SEASON}|\s+(?:and|or)\s+{_SEASON})*)\s*(20\d\d)", re.I)


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": ats.USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _joined(values) -> str:
    return "," + ",".join(v for v in values if v and v != "N/A") + ","


def _id(source: str, *parts: str) -> str:
    return f"{source}:" + hashlib.sha1("|".join(parts).lower().encode()).hexdigest()[:16]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _link(cell: str) -> str | None:
    m = re.search(r"\]\((https?://[^)\s]+)\)\s*$", cell) or re.search(r"\((https?://[^)\s]+)\)", cell)
    return m.group(1) if m else None


def _plain(cell: str) -> str:
    cell = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    cell = re.sub(r"<[^>]+>", "", cell)
    return re.sub(r"\*\*|__", "", cell).strip()


def _terms(title: str) -> list[str]:
    seen = []
    for seasons, year in TERM_IN_TITLE.findall(title):
        for season in re.findall(_SEASON, seasons, re.I):
            term = f"{ats.season_name(season)} {year}"
            if term not in seen:
                seen.append(term)
    return seen


def regions_of(locations: list[str]) -> tuple[list[str], set[str]]:
    """Keep the US/Canada locations; return (kept, regions)."""
    kept, regions = [], set()
    for loc in locations:
        r = classify(loc)
        if r:
            kept.append(loc)
            regions |= r
    return kept, regions


def _listing(source, *, id, company, title, url, locations, date_posted, category=None, terms=None,
             sponsorship=None) -> dict | None:
    kept, regions = regions_of(locations)
    if not kept or not company or not title or not url:
        return None
    return {
        "id": id, "source": source, "company": company.strip(), "title": title.strip(), "url": url,
        "locations": " / ".join(kept), "regions": _joined(sorted(regions)),
        "category": category or ats.tech_category(title), "terms": _joined(terms or _terms(title)),
        "degrees": ",", "sponsorship": sponsorship, "date_posted": date_posted,
        "posting_key": ats.posting_key(url), "board": None,
    }


# ---------- negarprh: README table ----------

def parse_negarprh(md: str) -> list[dict]:
    listings, company = [], None
    for line in md.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) < 5 or cells[0] in ("Company", "") and cells[1] == "Role" or set(cells[0]) <= set("-: "):
            continue
        name, role, location, apply, posted = cells[:5]
        name = _plain(name)
        company = company if name in ("↳", "") else name
        url = _link(apply)
        if not url or "closed" in apply.lower() or "🔒" in apply:
            continue
        try:
            date = int(datetime.strptime(_plain(posted), "%b %d, %Y").timestamp())
        except ValueError:
            date = None
        locs = [p.strip() for p in re.split(r"\s*/\s*|\s*;\s*|<br\s*/?>", _plain(location)) if p.strip()]
        listing = _listing("negarprh", id=_id("negarprh", company, role, url), company=company, title=_plain(role),
                           url=url, locations=locs, date_posted=date)
        if listing:
            listings.append(listing)
    return listings


# ---------- michelleokolie: SimplifyJobs-style JSON ----------

def parse_michelleokolie(raw: str) -> list[dict]:
    listings = []
    for item in json.loads(raw):
        if not item.get("active") or not item.get("is_visible", True):
            continue
        title = item.get("title", "")
        season = item.get("season")
        terms = _terms(title) or ([f"{season} 2027"] if season else [])
        listing = _listing("michelleokolie", id=f"michelleokolie:{item['id']}", company=item.get("company_name", ""),
                           title=title, url=item.get("url", ""), locations=item.get("locations") or [],
                           date_posted=item.get("date_posted"), terms=terms)
        if listing:
            listings.append(listing)
    return listings


# ---------- frogg: JSON array ----------

def parse_frogg(raw: str) -> list[dict]:
    listings = []
    for item in json.loads(raw):
        if item.get("status") != "open":
            continue
        title, url = item.get("role") or "", item.get("link") or ""
        term = item.get("term") or ""
        try:
            date = int(datetime.strptime(item.get("date_posted") or "", "%Y-%m-%d").timestamp())
        except ValueError:
            date = None
        locs = [p.strip() for p in re.split(r"\s*[;|]\s*", item.get("location") or "") if p.strip()]
        listing = _listing("frogg", id=_id("frogg", url.split("?")[0]), company=item.get("company") or "",
                           title=title, url=url, locations=locs, date_posted=date,
                           terms=_terms(title) or _terms(term))
        if listing:
            listings.append(listing)
    return listings


# ---------- zapply: README tables, one per category ----------

_AGE = {"m": 60, "h": 3600, "d": 86400, "w": 7 * 86400, "mo": 30 * 86400}


def _zapply_age(text: str, now: int) -> int | None:
    m = re.fullmatch(r"(\d+)\s*(mo|m|h|d|w)", text.strip())
    if not m:
        return None
    # Round to the hour so the date doesn't drift on every refresh.
    return (now - int(m.group(1)) * _AGE[m.group(2)]) // 3600 * 3600


def zapply_location(text: str) -> list[str]:
    """Zapply cuts long locations ("Santa Clara, California -...") and uses "IA-CEDAR RAPIDS"."""
    text = re.sub(r"\s*,?\s*More\.\.\.$|\s*[-,]?\s*\.\.\.$|\s+-$", "", text.strip()).strip(" ,-")
    if m := re.fullmatch(r"([A-Z]{2})-(.+)", text):
        code, city = m.groups()
        if code in US_STATES:
            return [f"{city.title()}, {code}"]
    if classify(text):
        return [text]
    # Fall back to any US state name/code, "USA" or Canada word inside the text.
    words = re.split(r"[\s,/-]+", text)
    if re.search(r"\b(USA|United States|US)\b", text) or any(w in US_STATES for w in words) or \
            any(n in text.lower() for n in US_NAMES):
        return ["United States"] if not classify(text) else [text]
    if any(w in CA_PROVINCES for w in words) or "canada" in text.lower():
        return ["Canada"]
    return []


def parse_zapply(md: str, now: int | None = None) -> list[dict]:
    now = now or int(time.time())
    listings, section = [], None
    for line in md.splitlines():
        if h := re.search(r"<h3>.*?<strong>(.+?)</strong>", line):
            section = h.group(1).replace("&amp;", "&").strip()
            continue
        if not line.startswith("| ") or section not in ZAPPLY_SECTIONS:
            continue
        cells = _cells(line)
        if len(cells) < 6 or cells[0] == "Company":
            continue
        company, role, location, posted, visa, apply = (_plain(c) if i != 5 else c for i, c in enumerate(cells[:6]))
        url = _link(apply)
        # Their "Hardware & Engineering" and "Product, Design & Research" include non-tech roles.
        category = ats.tech_category(role)
        if not url or not category:
            continue
        listing = _listing("zapply", id=_id("zapply", url.split("?")[0]), company=company, title=role, url=url,
                           locations=zapply_location(location), date_posted=_zapply_age(posted, now),
                           # Zapply's visa column is its estimate, not what the employer says.
                           category=category, sponsorship="May Offer Sponsorship" if "Sponsor" in visa else None)
        if listing:
            listings.append(listing)
    return listings


PARSERS = {"negarprh": parse_negarprh, "michelleokolie": parse_michelleokolie, "frogg": parse_frogg,
           "zapply": parse_zapply}


def fetch(source: str) -> list[dict]:
    return PARSERS[source](_get(SOURCES[source]["url"]))


def name_key(company: str, title: str) -> str:
    """Loose identity for the same internship listed with different links."""
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", re.sub(r"\(.*?\)|\b(inc|llc|ltd|corp|corporation)\b\.?", "",
                                                       s.lower())).strip()
    return f"{norm(company)}|{norm(title)}"
