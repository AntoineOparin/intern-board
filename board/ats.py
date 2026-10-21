"""Read internships straight from company job boards.

Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, BambooHR, Rippling, Breezy and
Recruiterbox (now Trakstar Hire) all publish a free, read-only JSON feed of each company's open
postings. Most return the whole board in one request; Workday and SmartRecruiters are searched
for internships in the US and Canada instead, since their boards can hold thousands of jobs.
"""

import collections
import gzip
import html
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from .locations import classify

USER_AGENT = "intern-board (personal use)"
# Some careers pages turn away anything that doesn't look like a browser.
BROWSER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"

PLATFORMS = {
    "greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workday": "Workday",
    "smartrecruiters": "SmartRecruiters", "workable": "Workable", "bamboohr": "BambooHR",
    "rippling": "Rippling", "breezy": "Breezy", "recruiterbox": "Recruiterbox",
}
FEEDS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{token}",
    "breezy": "https://{token}.breezy.hr/json",
}
BOARD_PAGES = {
    "greenhouse": "https://job-boards.greenhouse.io/{token}",
    "lever": "https://jobs.lever.co/{token}",
    "ashby": "https://jobs.ashbyhq.com/{token}",
    "smartrecruiters": "https://careers.smartrecruiters.com/{token}",
    "workable": "https://apply.workable.com/{token}/",
    "bamboohr": "https://{token}.bamboohr.com/careers",
    "rippling": "https://ats.rippling.com/{token}/jobs",
    "breezy": "https://{token}.breezy.hr/",
    "recruiterbox": "https://{token}.hire.trakstar.com/",
}


class BoardNotFound(Exception):
    pass


def board_page(platform: str, token: str) -> str:
    """The company's job board as a person sees it."""
    if platform == "workday":
        base, _, site = workday_site(token)
        return f"{base}/{site}"
    return BOARD_PAGES[platform].format(token=token)


def workday_site(token: str) -> tuple[str, str, str]:
    """"cae.wd3/career" -> ("https://cae.wd3.myworkdayjobs.com", "cae", "career")."""
    host, site = token.split("/", 1)
    return f"https://{host}.myworkdayjobs.com", host.split(".")[0], site


# ---------- URLs ----------

def parse_board_url(url: str) -> tuple[str, str] | None:
    """Return (platform, board token) for a company's job board or posting URL."""
    u = urlparse(url if "://" in url else "https://" + url)
    host, parts = u.netloc.lower().split(":")[0], [p for p in u.path.split("/") if p]
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
    # Workday: TENANT.wdN.myworkdayjobs.com/[en-US/]SITE/... or wdN.myworkdaysite.com/recruiting/TENANT/SITE/...
    if m := re.fullmatch(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com", host):
        if parts and re.fullmatch(r"[a-z]{2}-[A-Za-z]{2}", parts[0]):
            parts = parts[1:]
        if parts and parts[0] == "wday" and len(parts) >= 4:  # the API: /wday/cxs/TENANT/SITE/...
            parts = parts[3:]
        if parts and parts[0] not in {"job", "details"}:
            return "workday", f"{m.group(1)}.{m.group(2)}/{parts[0].lower()}"
        return None
    if m := re.fullmatch(r"(wd\d+)\.myworkdaysite\.com", host):
        if len(parts) >= 3 and parts[0] == "recruiting":
            return "workday", f"{parts[1].lower()}.{m.group(1)}/{parts[2].lower()}"
        return None
    if host in {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"} and parts:
        return "smartrecruiters", parts[0].lower()
    if host == "api.smartrecruiters.com" and len(parts) >= 3 and parts[1] == "companies":
        return "smartrecruiters", parts[2].lower()
    if host == "apply.workable.com" and parts:
        if parts[0] == "api" and len(parts) >= 5 and parts[3] == "accounts":
            return "workable", parts[4].lower()
        return ("workable", parts[0].lower()) if parts[0] not in {"j", "api"} else None
    if m := re.fullmatch(r"([a-z0-9-]+)\.(workable\.com|bamboohr\.com|breezy\.hr)", host):
        sub, domain = m.groups()
        if sub not in {"www", "apply", "api", "app", "jobs"}:
            return {"workable.com": "workable", "bamboohr.com": "bamboohr", "breezy.hr": "breezy"}[domain], sub
        return None
    if host == "ats.rippling.com" and parts:
        if re.fullmatch(r"[a-z]{2}-[A-Za-z]{2}", parts[0]):
            parts = parts[1:]
        if parts and parts[0] == "api" and len(parts) >= 4:  # /api/v2/board/SLUG/jobs
            return "rippling", parts[3].lower()
        return ("rippling", parts[0].lower()) if parts else None
    if host == "jsapi.recruiterbox.com":
        name = parse_qs(u.query).get("client_name", [None])[0]
        return ("recruiterbox", name.lower()) if name else None
    if m := re.fullmatch(r"([a-z0-9-]+)\.(recruiterbox\.com|hire\.trakstar\.com)", host):
        return ("recruiterbox", m.group(1)) if m.group(1) not in {"www", "app", "w", "jsapi"} else None
    return None


def posting_key(url: str) -> str | None:
    """A platform-wide ID for one posting, used to spot the same job from two sources."""
    if m := re.search(r"greenhouse\.io/.*?(?:/jobs/|[?&]gh_jid=|[?&]token=)(\d+)", url) \
            or re.search(r"[?&]gh_jid=(\d+)", url):  # company sites built on Greenhouse
        return f"gh:{m.group(1)}"
    if m := re.search(r"lever\.co/[^/]+/([0-9a-f-]{36})", url):
        return f"lever:{m.group(1)}"
    if m := re.search(r"ashbyhq\.com/[^/]+/([0-9a-f-]{36})", url):
        return f"ashby:{m.group(1)}"
    if m := re.search(r"//(?:([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com|wd\d+\.myworkdaysite\.com/recruiting/([^/]+))"
                      r"/.*?/(?:job|details)/(?:[^/?#]+/)*?[^/?#]*_([A-Za-z0-9-]+?)(?:/apply\b.*|/?(?:[?#].*)?)$",
                      url, re.I):
        return f"wd:{(m.group(1) or m.group(2)).lower()}:{m.group(3).upper()}"
    if m := re.search(r"smartrecruiters\.com/[^/]+/(\d{6,})", url):
        return f"sr:{m.group(1)}"
    if m := re.search(r"workable\.com/(?:[^/]+/)?j/([0-9A-F]{8,})", url, re.I):
        return f"workable:{m.group(1).upper()}"
    if m := re.search(r"([a-z0-9-]+)\.bamboohr\.com/(?:careers|jobs)/(?:view\.php\?id=)?(\d+)", url, re.I):
        return f"bamboo:{m.group(1).lower()}:{m.group(2)}"
    if m := re.search(r"ats\.rippling\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?[^/]+/jobs/([0-9a-f-]{36})", url):
        return f"rippling:{m.group(1)}"
    if m := re.search(r"breezy\.hr/p/([0-9a-f]{12})", url):
        return f"breezy:{m.group(1)}"
    if m := re.search(r"(?:recruiterbox\.com|hire\.trakstar\.com)/jobs/([a-z0-9]+)", url):
        return f"rbox:{m.group(1)}"
    return None


# ---------- classification ----------

INTERN = re.compile(
    r"\b(interns?|internships?|co-?ops?|coop|apprentice(ship)?s?|student\s+(researcher|engineer|developer)"
    r"|stagiaires?)\b"
    # French "stage" (internship), without catching "Early Stage" or "Stage Manager".
    r"|^\s*stages?\b(?!\s+manager)"
    r"|\bstages?\s+(en|de|d['’]|du|des|et|à|au|pour|-|–|:)"
    r"|[-–(|,:]\s*stages?\s*($|[)\-–|,:])"
    r"|(^|[-–(|,:]\s*)[ée]tudiant(\(e\)|e)?s?\b", re.I)
# Full-time roles that run internship programs rather than being internships.
NOT_INTERN = re.compile(r"\b(internships?|interns?|co-?op)\s+(program\s+)?(manager|coordinator|recruiter|lead|director)"
                        r"|\b(university|campus|early careers?)\s+recruiter\b"
                        r"|\b(coordonnat\w+|conseill\w+|responsable|gestionnaire|recruteu\w+|charg[ée]e? de)\s+"
                        r"(des\s+|de\s+|aux\s+)?(stages|stagiaires|[ée]tudiants)\b", re.I)

# First match wins, so the most specific categories come first. French terms sit beside the English.
CATEGORIES = [
    ("Quant", r"\bquant|\btrad(er|ing)\b"),
    ("AI/ML/Data", r"machine learning|\bml\b|\bai\b|artificial intelligence|\bdata\b|deep learning|computer vision"
                   r"|\bnlp\b|\bllm|research scien|applied scien|analytics|perception|geospatial|\bgis\b"
                   r"|image processing|\bslam\b|state estimation|business intelligence|product analyst|algorithm"
                   r"|researcher|research intern|computational|\bgen ?ai\b"
                   r"|donn[ée]es|apprentissage (automatique|machine|profond)|intelligence artificielle"
                   r"|(?<!, )(?-i:\bIA\b)|vision par ordinateur|analytique|intelligence d['’]affaires"
                   r"|chercheu(r|se)|\brecherche\b|traitement (d['’]images|du langage|des signaux)"),
    ("Hardware", r"hardware|electrical|firmware|embedded|\basic\b|fpga|silicon|semiconductor|\bchip|\brf\b"
                 r"|robotic|mechatronic|avionics|\bic\b|analog|mixed.signal|circuit|vlsi|\brtl\b|\bdft\b"
                 r"|physical design|design verification|photonic|optic|sensor|power electronics|pcb|electronics"
                 r"|validation|digital design|design.for.test"
                 r"|[ée]lectrique|[ée]lectronique|embarqu|micrologiciel|robotique|m[ée]catronique|avionique"
                 r"|semi-?conducteur|photonique|optique|capteurs?"),
    ("Product", r"product manag|technical program|\bapm\b|^product intern|product owner"
                r"|gestion(naire)? de produits?|chef de produits?|propri[ée]taire de produit"),
    # No bare "engineer": on company boards it mostly means mechanical, civil, test or quality roles.
    ("Software", r"software|developer|(software|web|app|application|game) development|\bswe\b|back.?end"
                 r"|front.?end|full.?stack|mobile|\bios\b|android|\bweb\b|devops|\bsre\b|site reliability"
                 r"|security|cyber|cloud|infrastructure|platform eng|computer science|\bit\b|\bqa\b"
                 r"|test automation|programm(?!es?\b)|technical staff|information technology|technology intern"
                 r"|rendering|user interface|\bui\b"
                 r"|network(ing)?\b"
                 r"|(research|forward deployed|solutions|systems"
                 r"|production|tools|build|release|graphics|compiler|kernel|network) engineer"
                 r"|logiciel|d[ée]velopp(eur|euse|ement)|informatique|infonuagique|s[ée]curit[ée] (informatique|de l['’]information)"
                 r"|(?-i:\bTI\b)|technologies? de l['’]information|g[ée]nie (logiciel|informatique)"),
]
CATEGORIES = [(name, re.compile(rx, re.I)) for name, rx in CATEGORIES]
NOT_TECH = re.compile(r"\b(sales|marketing|recruit\w*|talent|human resources|\bhr\b|account(ing|ant)|legal"
                      r"|communications|people ops|finance intern|business development|customer success"
                      r"|fundrais\w*|market research|competitive intelligence|supply chain|procurement"
                      r"|propulsion|quality|mining|geolog\w*|facilities|substation|power generation|nuclear"
                      r"|aerospace|structures|thermal|fluids|water|hvac|(civil|chemical|structural|environmental|process"
                      r"|manufacturing|industrial|mechanical|construction|biomedical) (systems )?engineer\w*"
                      r"|ventes?|recrut\w*|ressources humaines|(?-i:RH)|comptab\w*|juridique|approvisionnement"
                      r"|service (à la )?client\w*|d[ée]veloppement (des affaires|durable|organisationnel|commercial)"
                      r"|g[ée]nie (civil|chimique|m[ée]canique|industriel|des proc[ée]d[ée]s|de la construction"
                      r"|biom[ée]dical|des mines|g[ée]ologique|a[ée]rospatial)|qualit[ée]|actuari\w*|fiscal\w*"
                      r"|sant[ée] et s[ée]curit[ée]|a[ée]rospatial\w*|thermique|hydraulique|environnement\w*)\b", re.I)
SEASONS = {"summer": "Summer", "été": "Summer", "ete": "Summer", "fall": "Fall", "autumn": "Fall",
           "automne": "Fall", "winter": "Winter", "hiver": "Winter", "spring": "Spring", "printemps": "Spring"}
SEASON = r"(?:summer|fall|autumn|winter|spring|[ée]t[ée]|automne|hiver|printemps)"
TERM = re.compile(rf"\b({SEASON})\b[\s,/-]*(?:\w+\s+)?(20\d\d)\b", re.I)


def tech_category(title: str) -> str | None:
    # Judge the role by its main title; " - Customer Success" style suffixes name the team.
    main = re.split(r"\s+[-–—|]\s+|\s*\(", title, maxsplit=1)[0]
    if NOT_TECH.search(main):
        return None
    if category := next((name for name, rx in CATEGORIES if rx.search(main)), None):
        return category
    # A generic main title ("Intern - Sales Analytics", "Stagiaire - Données"): the rest of the title decides.
    if NOT_TECH.search(title):
        return None
    return next((name for name, rx in CATEGORIES if rx.search(title)), None)


def season_name(word: str) -> str:
    return SEASONS.get(word.lower(), word.title())


def terms_from(title: str) -> list[str]:
    terms = [f"{season_name(season)} {year}" for season, year in TERM.findall(title)]
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


def _place(*parts) -> str:
    return ", ".join(p.strip() for p in parts if p and isinstance(p, str) and p.strip())


def _ts(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value / 1000) if value > 1e11 else int(value)
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _job(key, title, url, locations, regions, posted, intern_flag=False) -> dict:
    return {"key": key, "title": title or "", "url": url or "", "locations": locations, "regions": regions,
            "posted": posted, "intern_flag": intern_flag}


def _looks_intern(title: str) -> bool:
    return bool(INTERN.search(title or ""))


# ---------- fetching ----------

def _request(url: str, body: dict | None = None, timeout: int = 30) -> tuple[object, int]:
    """GET (or POST `body`) and parse JSON. Returns (data, bytes downloaded); 404 raises BoardNotFound."""
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            size = len(raw)
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            final = resp.geturl()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise BoardNotFound(url) from exc
        raise
    if urlparse(final).netloc != urlparse(url).netloc:  # BambooHR sends unknown boards to its home page
        raise BoardNotFound(url)
    return json.loads(raw), size


# Details fetched once per posting (dates, every location), kept while the app runs.
_details: dict[str, dict] = {}
DETAILS_PER_BOARD = 40


def _detail(url: str, parse, budget: list[int], timeout: int) -> dict | None:
    if url in _details:
        return _details[url]
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    try:
        data, _ = _request(url, timeout=timeout)
    except (OSError, ValueError, BoardNotFound):
        return None
    _details[url] = parse(data)
    return _details[url]


def _greenhouse(data: dict) -> list[dict]:
    jobs = []
    for j in data.get("jobs", []):
        locs = split_locations((j.get("location") or {}).get("name"))
        jobs.append(_job(f"gh:{j['id']}", j.get("title"), j.get("absolute_url"), locs, regions_for(locs),
                         _ts(j.get("first_published") or j.get("updated_at"))))
    return jobs


def _lever(data: list) -> list[dict]:
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or split_locations(cats.get("location"))
        jobs.append(_job(f"lever:{j['id']}", j.get("text"), j.get("hostedUrl"), locs,
                         regions_for(locs, j.get("country"), j.get("workplaceType") == "remote"),
                         _ts(j.get("createdAt")), (cats.get("commitment") or "").lower().startswith("intern")))
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
        jobs.append(_job(f"ashby:{j['id']}", j.get("title"), j.get("jobUrl"), locs, regions,
                         _ts(j.get("publishedAt")), j.get("employmentType") == "Intern"))
    return jobs


def _workable(data: dict) -> list[dict]:
    jobs = []
    for j in data.get("jobs", []):
        places = j.get("locations") or [j]
        locs, regions = [], set()
        for p in places:
            loc = _place(p.get("city"), p.get("region") or p.get("state"), p.get("country"))
            if loc:
                locs.append(loc)
            regions |= regions_for([loc] if loc else [], p.get("countryCode") or p.get("country"))
        if j.get("telecommuting") and regions:
            regions.add("REMOTE")
        jobs.append(_job(f"workable:{j['shortcode'].upper()}", j.get("title"), j.get("url"), locs, regions,
                         _ts(j.get("published_on") or j.get("created_at")),
                         (j.get("employment_type") or "").lower() == "internship"))
    return jobs


def _breezy(data: list) -> list[dict]:
    jobs = []
    for j in data:
        places = j.get("locations") or [j.get("location") or {}]
        locs, regions = [], set()
        for p in places:
            country = p.get("country") or {}
            loc = _place(p.get("city"), (p.get("state") or {}).get("id"), country.get("name")) or p.get("name") or ""
            if loc:
                locs.append(loc)
            regions |= regions_for([loc] if loc else [], country.get("id"), bool(p.get("is_remote")))
        kind = ((j.get("type") or {}).get("id") or "").lower()
        jobs.append(_job(f"breezy:{j['id']}", j.get("name"), j.get("url"), locs, regions,
                         _ts(j.get("published_date")), "intern" in kind))
    return jobs


PARSERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby, "workable": _workable, "breezy": _breezy}


# ----- Workday -----

WORKDAY_PAGE = 20
WORKDAY_MAX_PAGES = 10
# Facet values that mean internships ("Intern", "COOP-Student (Fixed Term)", "Stagiaire").
WORKDAY_INTERN = re.compile(r"\b(interns?|internships?|co-?op|coop|students?|stagiaires?|stages?|[ée]tudiant\w*"
                            r"|apprentice\w*)\b", re.I)
WORKDAY_COUNTRIES = {"united states of america": "US", "united states": "US", "usa": "US", "canada": "CA"}
WORKDAY_SEARCHES = ("intern", "co-op", "stagiaire")


def _workday_facets(facets: list) -> list[tuple[str, dict]]:
    """Flatten Workday's facet tree into (parameter, value) pairs."""
    pairs = []
    for f in facets or []:
        for v in f.get("values") or []:
            if "facetParameter" in v:
                pairs += _workday_facets([v])
            else:
                pairs.append((f.get("facetParameter", ""), v))
    return pairs


def workday_posted(text: str | None, now: float | None = None) -> int | None:
    """"Posted 3 Days Ago" -> that day (midnight UTC), so the date doesn't move between checks."""
    if not text:
        return None
    today = int(now or time.time()) // 86400 * 86400
    t = text.lower()
    if "today" in t:
        return today
    if "yesterday" in t:
        return today - 86400
    if m := re.search(r"(\d+)\+?\s+days?", t):
        return today - (int(m.group(1)) + ("+" in t)) * 86400
    return None


def _workday_detail(data: dict) -> dict:
    info = data.get("jobPostingInfo") or {}
    locs = [info.get("location")] + (info.get("additionalLocations") or [])
    return {"locations": [l for l in locs if l], "country": (info.get("country") or {}).get("descriptor"),
            "posted": _ts(info.get("startDate"))}


def _fetch_workday(token: str, timeout: int) -> tuple[list[dict], int, int]:
    base, tenant, site = workday_site(token)
    api = f"{base}/wday/cxs/{tenant}/{site}"
    size = 0

    def search(facets: dict, text: str = "", max_pages: int = WORKDAY_MAX_PAGES):
        nonlocal size
        found, offset, total = [], 0, None
        while offset < (total if total is not None else 1) and offset < max_pages * WORKDAY_PAGE:
            data, n = _request(f"{api}/jobs", {"appliedFacets": facets, "limit": WORKDAY_PAGE, "offset": offset,
                                               "searchText": text}, timeout)
            size += n
            if total is None:  # only the first page reports the total
                total = data.get("total") or 0
            page = data.get("jobPostings") or []
            found += page
            if not page:
                break
            offset += WORKDAY_PAGE
        return found, total or 0, data

    first, board_total, data = search({}, max_pages=1)
    pairs = _workday_facets(data.get("facets"))
    # The facet holding Canada / the United States, and the one that marks internships.
    countries: dict[str, tuple[str, str]] = {}
    for param, v in pairs:
        code = WORKDAY_COUNTRIES.get((v.get("descriptor") or "").strip().lower())
        if code and "country" in param.lower():
            countries[code] = (param, v["id"])
    intern_values: dict[str, list[dict]] = collections.defaultdict(list)
    for param, v in pairs:
        if "location" not in param.lower() and WORKDAY_INTERN.search(v.get("descriptor") or ""):
            intern_values[param].append(v)
    intern = max(intern_values.items(), key=lambda kv: sum(v.get("count") or 0 for v in kv[1]), default=None)
    intern_facet = {intern[0]: [v["id"] for v in intern[1]]} if intern else {}

    postings: dict[str, tuple[dict, set[str], bool]] = {}

    def collect(items, country=None, flagged=False):
        for p in items:
            path = p.get("externalPath") or ""
            old = postings.get(path)
            regions = (old[1] if old else set()) | ({country} if country else set())
            postings[path] = (p, regions, flagged or bool(old and old[2]))

    scopes = [(code, {param: [vid]}) for code, (param, vid) in sorted(countries.items())] or [(None, {})]
    for code, place in scopes:
        if intern_facet:
            items, _, _ = search({**intern_facet, **place})
            collect(items, code, flagged=True)
        else:
            items, total, _ = search(place, max_pages=1)
            if total <= 5 * WORKDAY_PAGE:  # small board (or a campus site): read it all
                items, _, _ = search(place, max_pages=5)
                collect(items, code)
            else:
                for text in WORKDAY_SEARCHES:
                    items, _, _ = search(place, text, max_pages=3)
                    collect([i for i in items if _looks_intern(i.get("title"))], code)

    jobs, budget = [], [DETAILS_PER_BOARD]
    for path, (p, regions, flagged) in postings.items():
        segment = path.rstrip("/").rsplit("/", 1)[-1]
        req = segment.rsplit("_", 1)[-1] if "_" in segment else (p.get("bulletFields") or [segment])[0]
        locs, posted = [p.get("locationsText") or ""], workday_posted(p.get("postedOn"))
        # "3 Locations" says nothing about where; the posting itself lists them.
        if re.fullmatch(r"\d+ Locations?", locs[0]) and (flagged or _looks_intern(p.get("title"))):
            if d := _detail(f"{api}{path}", _workday_detail, budget, timeout):
                locs, posted = d["locations"] or locs, d["posted"] or posted
        locs = [l for l in locs if l and not re.fullmatch(r"\d+ Locations?", l)]
        jobs.append(_job(f"wd:{tenant}:{req.upper()}", p.get("title"), f"{base}/{site}{path}", locs,
                         regions | regions_for(locs), posted, flagged))
    return jobs, size, board_total


# ----- SmartRecruiters -----

def _fetch_smartrecruiters(token: str, timeout: int) -> tuple[list[dict], int, int]:
    jobs, size, total = {}, 0, 0
    for country in ("ca", "us"):
        offset, found = 0, None
        while found is None or offset < min(found, 1000):
            data, n = _request(f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
                               f"?limit=100&offset={offset}&country={country}", timeout=timeout)
            size += n
            found = data.get("totalFound") or 0
            for j in data.get("content") or []:
                loc = j.get("location") or {}
                place = _place(loc.get("city"), loc.get("region")) or (loc.get("fullLocation") or "")
                regions = regions_for([place] if place else [], loc.get("country"), bool(loc.get("remote")))
                kind = ((j.get("typeOfEmployment") or {}).get("id"), (j.get("experienceLevel") or {}).get("id"))
                jobs[j["id"]] = _job(f"sr:{j['id']}", j.get("name"), f"https://jobs.smartrecruiters.com/{token}/{j['id']}",
                                     [place] if place else [], regions, _ts(j.get("releasedDate")),
                                     "intern" in kind or "internship" in kind)
            if not data.get("content"):
                break
            offset += 100
        total += found or 0
    # An unknown company gets an empty list, not a 404, so a missing board just looks empty.
    return list(jobs.values()), size, total


# ----- BambooHR, Rippling, Recruiterbox -----

def _fetch_bamboohr(token: str, timeout: int) -> tuple[list[dict], int, int]:
    data, size = _request(f"https://{token}.bamboohr.com/careers/list", timeout=timeout)
    jobs, budget = [], [DETAILS_PER_BOARD]
    for j in data.get("result") or []:
        loc, ats_loc = j.get("location") or {}, j.get("atsLocation") or {}
        place = _place(loc.get("city") or ats_loc.get("city"), loc.get("state") or ats_loc.get("state")
                       or ats_loc.get("province"), ats_loc.get("country"))
        url = f"https://{token}.bamboohr.com/careers/{j['id']}"
        flagged = "intern" in (j.get("employmentStatusLabel") or "").lower()
        posted = None
        if flagged or _looks_intern(j.get("jobOpeningName")):  # the list has no dates; the posting does
            d = _detail(f"{url}/detail", lambda r: {"posted": _ts(((r.get("result") or {}).get("jobOpening") or {})
                                                                   .get("datePosted"))}, budget, timeout)
            posted = d and d["posted"]
        jobs.append(_job(f"bamboo:{token}:{j['id']}", j.get("jobOpeningName"), url, [place] if place else [],
                         regions_for([place] if place else [], remote=bool(j.get("isRemote"))), posted, flagged))
    return jobs, size, len(jobs)


def _fetch_rippling(token: str, timeout: int) -> tuple[list[dict], int, int]:
    jobs, size, page, pages, budget = [], 0, 0, 1, [DETAILS_PER_BOARD]
    api = f"https://ats.rippling.com/api/v2/board/{token}/jobs"
    while page < min(pages, 20):
        data, n = _request(f"{api}?page={page}&pageSize=100", timeout=timeout)
        size += n
        pages = data.get("totalPages") or 1
        for j in data.get("items") or []:
            locs, regions = [], set()
            for p in j.get("locations") or []:
                if p.get("name"):
                    locs.append(p["name"])
                regions |= regions_for([p["name"]] if p.get("name") else [], p.get("countryCode"),
                                       p.get("workplaceType") == "REMOTE")
            posted = None
            if _looks_intern(j.get("name")):
                d = _detail(f"{api}/{j['id']}", lambda r: {"posted": _ts(r.get("createdOn"))}, budget, timeout)
                posted = d and d["posted"]
            jobs.append(_job(f"rippling:{j['id']}", j.get("name"), j.get("url"), locs, regions, posted))
        page += 1
    return jobs, size, len(jobs)


def _fetch_recruiterbox(token: str, timeout: int) -> tuple[list[dict], int, int]:
    jobs, size, offset, total = [], 0, 0, None
    while total is None or offset < min(total, 1000):
        try:
            data, n = _request(f"https://jsapi.recruiterbox.com/v1/openings?client_name={token}"
                               f"&limit=100&offset={offset}", timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 400:  # {"client_name": "Invalid client name"}
                raise BoardNotFound(f"recruiterbox/{token}") from exc
            raise
        size += n
        total = (data.get("meta") or {}).get("total") or 0
        for j in data.get("objects") or []:
            loc = j.get("location") or {}
            place = _place(loc.get("city"), loc.get("state"), loc.get("country"))
            # Recruiterbox doesn't say when a job was posted.
            jobs.append(_job(f"rbox:{j['id']}", (j.get("title") or "").strip(), j.get("hosted_url"),
                             [place] if place else [], regions_for([place] if place else [],
                                                                   remote=bool(j.get("allows_remote"))),
                             None, "intern" in (j.get("position_type") or "").lower()))
        if not data.get("objects"):
            break
        offset += 100
    return jobs, size, total or 0


FETCHERS = {"workday": _fetch_workday, "smartrecruiters": _fetch_smartrecruiters, "bamboohr": _fetch_bamboohr,
            "rippling": _fetch_rippling, "recruiterbox": _fetch_recruiterbox}


def fetch_board(platform: str, token: str, timeout: int = 30) -> tuple[list[dict], int, int]:
    """Return (postings read from the board, bytes downloaded, jobs on the board). Raises BoardNotFound.

    Workday and SmartRecruiters return only their US/Canada internship candidates; the rest return
    every posting.
    """
    if platform in FETCHERS:
        return FETCHERS[platform](token, timeout)
    data, size = _request(FEEDS[platform].format(token=token), timeout=timeout)
    jobs = PARSERS[platform](data)
    return jobs, size, len(jobs)


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


# ---------- careers pages ----------

def _get_text(url: str, timeout: int = 20, limit: int = 3_000_000) -> tuple[str, str]:
    """Fetch a web page as text. Returns (text, final URL)."""
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_AGENT, "Accept-Encoding": "gzip",
                                               "Accept": "text/html,application/xhtml+xml,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(limit)
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace"), resp.geturl()


def find_board(url: str, timeout: int = 20) -> dict | None:
    """Find the job board behind a company's careers page, for pages like company.com/careers.

    Returns {"platform", "token", "name"} (name from the page, if it gives one) or None.
    """
    page, final = _get_text(url if "://" in url else "https://" + url, timeout)
    if board := parse_board_url(final):  # the page redirected to the board itself
        return {"platform": board[0], "token": board[1], "name": None}
    text = html.unescape(page).replace("\\/", "/")
    found: collections.Counter = collections.Counter()
    for m in re.finditer(r"(?:https?:)?//[A-Za-z0-9.-]+\.[a-z]{2,}[^\s\"'<>\\)]*", text):
        link = m.group(0)
        if board := parse_board_url("https:" + link if link.startswith("//") else link):
            found[board] += 1
    name = None
    if m := re.search(r"<meta[^>]+property=[\"']og:site_name[\"'][^>]+content=[\"']([^\"']{2,80})", page):
        # "TS Imagine - Trading, Portfolio & Real-Time Risk…" -> "TS Imagine"
        name = re.split(r"\s+[-|–—:]\s+", html.unescape(m.group(1)).strip())[0]
    if found:
        platform, token = found.most_common(1)[0][0]
        return {"platform": platform, "token": token, "name": name}
    # Recruiterbox's widget loads by number (the page may build its address in pieces); the company's
    # name is inside its script.
    if "recruiterbox.com" in text and (m := re.search(r"/static/client-src-served/widget/(\d+)/", text)):
        script, _ = _get_text(f"https://w.recruiterbox.com/static/client-src-served/widget/{m.group(1)}/rbox_api.js",
                              timeout)
        names = collections.Counter(n for n in re.findall(r"https?://([a-z0-9-]+)\.recruiterbox\.com", script)
                                    if n not in {"app", "w", "jsapi", "www"})
        if names:
            return {"platform": "recruiterbox", "token": names.most_common(1)[0][0], "name": name}
    return None
