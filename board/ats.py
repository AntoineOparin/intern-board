"""Read internships straight from company job boards on Greenhouse, Lever and Ashby.

All three publish a free, read-only JSON feed of each company's open postings.
"""

import gzip
import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from .locations import classify

USER_AGENT = "intern-board (personal use)"

FEEDS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
}
BOARD_PAGES = {
    "greenhouse": "https://job-boards.greenhouse.io/{token}",
    "lever": "https://jobs.lever.co/{token}",
    "ashby": "https://jobs.ashbyhq.com/{token}",
}


class BoardNotFound(Exception):
    pass


# ---------- URLs ----------

def parse_board_url(url: str) -> tuple[str, str] | None:
    """Return (platform, board token) for a company's job board or posting URL."""
    u = urlparse(url if "://" in url else "https://" + url)
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        token = parse_qs(u.query).get("for", [None])[0]
        if not token and parts and parts[0] != "embed":
            token = parts[0]
        return ("greenhouse", token.lower()) if token else None
    if host == "boards-api.greenhouse.io" and len(parts) >= 3:
        return "greenhouse", parts[2].lower()
    if host in {"jobs.lever.co", "api.lever.co"} and parts:
        return "lever", (parts[2] if parts[0] == "v0" and len(parts) > 2 else parts[0]).lower()
    if host in {"jobs.ashbyhq.com", "api.ashbyhq.com"} and parts:
        token = parts[2] if parts[0] == "posting-api" and len(parts) > 2 else parts[0]
        return "ashby", token.lower()
    return None


def posting_key(url: str) -> str | None:
    """A platform-wide ID for one posting, used to spot the same job from two sources."""
    if m := re.search(r"greenhouse\.io/.*?(?:/jobs/|[?&]gh_jid=|[?&]token=)(\d+)", url):
        return f"gh:{m.group(1)}"
    if m := re.search(r"lever\.co/[^/]+/([0-9a-f-]{36})", url):
        return f"lever:{m.group(1)}"
    if m := re.search(r"ashbyhq\.com/[^/]+/([0-9a-f-]{36})", url):
        return f"ashby:{m.group(1)}"
    return None


# ---------- classification ----------

INTERN = re.compile(r"\b(interns?|internships?|co-?ops?|coop|apprentice(ship)?s?|student\s+(researcher|engineer|developer))\b", re.I)
# Full-time roles that run internship programs rather than being internships.
NOT_INTERN = re.compile(r"\b(internships?|interns?|co-?op)\s+(program\s+)?(manager|coordinator|recruiter|lead|director)"
                        r"|\b(university|campus|early careers?)\s+recruiter\b", re.I)

# First match wins, so the most specific categories come first.
CATEGORIES = [
    ("Quant", r"\bquant|\btrad(er|ing)\b"),
    ("AI/ML/Data", r"machine learning|\bml\b|\bai\b|artificial intelligence|\bdata\b|deep learning|computer vision"
                   r"|\bnlp\b|\bllm|research scien|applied scien|analytics|perception|geospatial|\bgis\b"
                   r"|image processing|\bslam\b|state estimation|business intelligence|product analyst|algorithm"
                   r"|researcher|research intern|computational"),
    ("Hardware", r"hardware|electrical|firmware|embedded|\basic\b|fpga|silicon|semiconductor|\bchip|\brf\b"
                 r"|robotic|mechatronic|avionics|\bic\b|analog|mixed.signal|circuit|vlsi|\brtl\b|\bdft\b"
                 r"|physical design|design verification|photonic|optic|sensor|power electronics|pcb|electronics"
                 r"|validation"),
    ("Product", r"product manag|technical program|\bapm\b|^product intern|product owner"),
    # No bare "engineer": on company boards it mostly means mechanical, civil, test or quality roles.
    ("Software", r"software|developer|(software|web|app|application|game) development|\bswe\b|back.?end"
                 r"|front.?end|full.?stack|mobile|\bios\b|android|\bweb\b|devops|\bsre\b|site reliability"
                 r"|security|cyber|cloud|infrastructure|platform eng|computer science|\bit\b|\bqa\b"
                 r"|test automation|programm|technical staff|information technology|technology intern|network(ing)?\b"
                 r"|(research|forward deployed|solutions|systems"
                 r"|production|tools|build|release|graphics|compiler|kernel|network) engineer"),
]
CATEGORIES = [(name, re.compile(rx, re.I)) for name, rx in CATEGORIES]
NOT_TECH = re.compile(r"\b(sales|marketing|recruit\w*|talent|human resources|\bhr\b|account(ing|ant)|legal"
                      r"|communications|people ops|finance intern|business development|customer success"
                      r"|fundrais\w*|market research|competitive intelligence|supply chain|procurement"
                      r"|propulsion|quality|mining|geolog\w*|facilities|substation|power generation|nuclear"
                      r"|aerospace|structures|thermal|fluids|water|hvac|(civil|chemical|structural|environmental|process"
                      r"|manufacturing|industrial|mechanical|construction|biomedical) (systems )?engineer\w*)\b", re.I)
TERM = re.compile(r"\b(summer|fall|autumn|winter|spring)\b[\s,/-]*(?:\w+\s+)?(20\d\d)\b", re.I)


def tech_category(title: str) -> str | None:
    # Judge the role by its main title; " - Customer Success" style suffixes name the team.
    main = re.split(r"\s+[-–—|]\s+|\s*\(", title, maxsplit=1)[0]
    if NOT_TECH.search(main):
        return None
    if category := next((name for name, rx in CATEGORIES if rx.search(main)), None):
        return category
    # A generic main title ("Intern - Sales Analytics"): the rest of the title decides.
    if NOT_TECH.search(title):
        return None
    return next((name for name, rx in CATEGORIES if rx.search(title)), None)


def terms_from(title: str) -> list[str]:
    terms = []
    for season, year in TERM.findall(title):
        season = "Fall" if season.lower() == "autumn" else season.title()
        terms.append(f"{season} {year}")
    return list(dict.fromkeys(terms))


COUNTRY_HINTS = {"us": "US", "usa": "US", "united states": "US", "united states of america": "US",
                 "ca": "CA", "can": "CA", "canada": "CA"}


def regions_for(locations: list[str], country: str | None = None, remote: bool = False) -> set[str]:
    regions: set[str] = set()
    for loc in locations:
        # Ashby-style "US-WA-Bellevue" / "CA-ON-Toronto": the prefix is an ISO country code.
        m = re.match(r"^(US|CA)-", loc)
        regions |= {m.group(1)} if m else classify(loc)
    hint = COUNTRY_HINTS.get((country or "").strip().lower())
    if hint:
        regions.add(hint)
    if remote and regions & {"US", "CA"}:
        regions.add("REMOTE")
    return regions


def split_locations(text: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"\s*[;|]\s*|\s+or\s+", text or "") if p.strip()]


def _ts(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value / 1000) if value > 1e11 else int(value)
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


# ---------- per-platform parsing ----------

def _greenhouse(data: dict) -> list[dict]:
    jobs = []
    for j in data.get("jobs", []):
        locs = split_locations((j.get("location") or {}).get("name"))
        jobs.append({"key": f"gh:{j['id']}", "title": j.get("title", ""), "url": j.get("absolute_url", ""),
                     "locations": locs, "regions": regions_for(locs),
                     "posted": _ts(j.get("first_published") or j.get("updated_at")), "intern_flag": False})
    return jobs


def _lever(data: list) -> list[dict]:
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or split_locations(cats.get("location"))
        jobs.append({"key": f"lever:{j['id']}", "title": j.get("text", ""), "url": j.get("hostedUrl", ""),
                     "locations": locs,
                     "regions": regions_for(locs, j.get("country"), j.get("workplaceType") == "remote"),
                     "posted": _ts(j.get("createdAt")),
                     "intern_flag": (cats.get("commitment") or "").lower().startswith("intern")})
    return jobs


def _ashby(data: dict) -> list[dict]:
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        places = [j] + (j.get("secondaryLocations") or [])
        locs = [p.get("location") for p in places if p.get("location")]
        regions: set[str] = set()
        for p in places:
            country = ((p.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
            regions |= regions_for([p["location"]] if p.get("location") else [], country)
        if j.get("isRemote") and regions:
            regions.add("REMOTE")
        jobs.append({"key": f"ashby:{j['id']}", "title": j.get("title", ""), "url": j.get("jobUrl", ""),
                     "locations": locs, "regions": regions, "posted": _ts(j.get("publishedAt")),
                     "intern_flag": j.get("employmentType") == "Intern"})
    return jobs


PARSERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


# ---------- fetching ----------

def fetch_board(platform: str, token: str, timeout: int = 30) -> tuple[list[dict], int]:
    """Return (all postings on the board, bytes downloaded). Raises BoardNotFound on 404."""
    req = urllib.request.Request(FEEDS[platform].format(token=token),
                                 headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            size = len(body)
            if resp.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise BoardNotFound(f"{platform}/{token}") from exc
        raise
    return PARSERS[platform](json.loads(body)), size


def internships(jobs: list[dict]) -> list[dict]:
    """Keep tech internships located in the US or Canada."""
    kept = []
    for j in jobs:
        title = j["title"]
        if not (INTERN.search(title) or j["intern_flag"]) or NOT_INTERN.search(title):
            continue
        category = tech_category(title)
        regions = j["regions"]
        if not category or not regions & {"US", "CA"} and regions != {"REMOTE"}:
            continue
        kept.append({**j, "category": category, "terms": terms_from(title)})
    return kept
