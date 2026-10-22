"""Read internships straight from company job boards.

Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, BambooHR, Rippling, Breezy,
Recruiterbox (now Trakstar Hire) and Oracle Cloud all publish a free, read-only JSON feed of each
company's open postings; iCIMS publishes a search page. Most return the whole board in one request;
Workday, SmartRecruiters, Oracle Cloud and iCIMS are searched for internships instead, since their
boards can hold thousands of jobs.
"""

import collections
import gzip
import html
import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import parse_qs, quote, urlparse
from xml.etree import ElementTree

from .locations import classify

USER_AGENT = "intern-board (personal use)"
# Some careers pages turn away anything that doesn't look like a browser.
BROWSER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"

PLATFORMS = {
    "greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workday": "Workday",
    "smartrecruiters": "SmartRecruiters", "workable": "Workable", "bamboohr": "BambooHR",
    "rippling": "Rippling", "breezy": "Breezy", "recruiterbox": "Recruiterbox", "oracle": "Oracle Cloud",
    "icims": "iCIMS", "jibe": "iCIMS career site", "successfactors": "SuccessFactors", "eightfold": "Eightfold",
    "avature": "Avature", "jazzhr": "JazzHR",
    "site": "Company site",  # big companies' own career sites (sites.py)
}
FEEDS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{token}",
    "breezy": "https://{token}.breezy.hr/json",
}
BOARD_PAGES = {
    "greenhouse": "https://job-boards.greenhouse.io/{token}",
    "ashby": "https://jobs.ashbyhq.com/{token}",
    "smartrecruiters": "https://careers.smartrecruiters.com/{token}",
    "workable": "https://apply.workable.com/{token}/",
    "bamboohr": "https://{token}.bamboohr.com/careers",
    "rippling": "https://ats.rippling.com/{token}/jobs",
    "breezy": "https://{token}.breezy.hr/",
    "recruiterbox": "https://{token}.hire.trakstar.com/",
    "icims": "https://{token}.icims.com/jobs/search?ss=1",
    # These two are recognised by the tag the community lists add to their links.
    "jibe": "https://{token}/jobs?icims=1",
    "successfactors": "https://{token}/search/?q=&ats=successfactors",
    "eightfold": "https://{token}/careers",
    "avature": "https://{token}/SearchJobs/",
    "jazzhr": "https://{token}.applytojob.com/apply",
}


class BoardNotFound(Exception):
    pass


def board_page(platform: str, token: str) -> str:
    """The company's job board as a person sees it."""
    if platform == "workday":
        base, _, site = workday_site(token)
        return f"{base}/{site}"
    if platform == "oracle":
        base, _, site = oracle_site(token)
        return f"{base}/hcmUI/CandidateExperience/en/sites/{site}"
    if platform == "site":
        return sites.SITES[token].page
    if platform == "lever":
        region, _, name = token.rpartition("/")
        return f"https://jobs.{region + '.' if region else ''}lever.co/{name}"
    return BOARD_PAGES[platform].format(token=token)


def lever_api(token: str) -> str:
    """"eu/cirrus" -> "https://api.eu.lever.co/v0/postings/cirrus"."""
    region, _, name = token.rpartition("/")
    return f"https://api.{region + '.' if region else ''}lever.co/v0/postings/{name}"


def workday_site(token: str) -> tuple[str, str, str]:
    """"cae.wd3/career" -> ("https://cae.wd3.myworkdayjobs.com", "cae", "career")."""
    host, site = token.split("/", 1)
    return f"https://{host}.myworkdayjobs.com", host.split(".")[0], site


def oracle_site(token: str) -> tuple[str, str, str]:
    """"hdks.fa.ca2/CX_1" -> ("https://hdks.fa.ca2.oraclecloud.com", "hdks", "CX_1")."""
    host, site = token.split("/", 1)
    return f"https://{host}.oraclecloud.com", host.split(".")[0], site


# ---------- URLs ----------

def parse_board_url(url: str) -> tuple[str, str] | None:
    """Return (platform, board token) for a company's job board or posting URL."""
    u = urlparse(url if "://" in url else "https://" + url)
    host, parts = u.netloc.lower().split(":")[0], [p for p in u.path.split("/") if p]
    # EU boards (job-boards.eu.greenhouse.io) are served by the same API.
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io",
                "job-boards.eu.greenhouse.io"}:
        token = parse_qs(u.query).get("for", [None])[0]
        if not token and parts and parts[0] != "embed":
            token = parts[0]
        if not token and len(parts) >= 3 and parts[0] == "embed" and parts[2] == "jobs":  # embed/TOKEN/jobs/ID
            token = parts[1]
        return ("greenhouse", token.lower()) if token else None
    if host == "boards-api.greenhouse.io" and len(parts) >= 3:
        return "greenhouse", parts[2].lower()
    if (m := re.fullmatch(r"(?:jobs|api)\.(eu\.)?lever\.co", host)) and parts:
        token = (parts[2] if parts[0] == "v0" and len(parts) > 2 else parts[0]).lower()
        return "lever", f"eu/{token}" if m.group(1) else token
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
    # Oracle Cloud: HOST.oraclecloud.com/hcmUI/CandidateExperience/[en/]sites/SITE/... (the site keeps its case)
    if (m := re.fullmatch(r"([a-z0-9-]+(?:\.[a-z0-9-]+)*)\.oraclecloud\.com", host)) \
            and "CandidateExperience" in parts and "sites" in parts[:-1]:
        return "oracle", f"{m.group(1)}/{parts[parts.index('sites') + 1]}"
    if m := re.fullmatch(r"([a-z0-9-]+)\.icims\.com", host):
        return ("icims", m.group(1)) if m.group(1) not in {"www", "api", "login", "help", "community"} else None
    query = parse_qs(u.query)
    if query.get("icims") == ["1"] and re.fullmatch(r"/(?:[a-z0-9-]+/)?jobs(?:/\d+)?/?", u.path):
        return "jibe", host
    if query.get("ats") == ["successfactors"] and parts and parts[0] in {"job", "search"}:
        return "successfactors", host
    if host in EIGHTFOLD_SITES:
        return "eightfold", EIGHTFOLD_SITES[host][0]
    if re.fullmatch(r"[a-z0-9-]+\.eightfold\.ai", host):
        return "eightfold", host
    if (m := re.fullmatch(r"([a-z0-9-]+)\.applytojob\.com", host)) and m.group(1) not in {"www", "app"}:
        return "jazzhr", m.group(1)
    return sites.board_for(f"//{host}{u.path}") or _avature_board(host, parts)


def _avature_board(host: str, parts: list[str]) -> tuple[str, str] | None:
    """Avature: HOST/[en_US/]PORTAL/JobDetail/…, on *.avature.net or the company's own domain."""
    at = next((i for i, p in enumerate(parts) if p in {"JobDetail", "SearchJobs", "OpenRoles"}), None)
    if at is None or not 1 <= at <= 2 or at == 2 and not re.fullmatch(r"[a-z]{2}_[A-Z]{2}", parts[0]):
        return ("avature", f"{avature_host(host)}/careers") if host.endswith(".avature.net") and not parts else None
    return "avature", "/".join([avature_host(host)] + parts[:at])


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
    if m := re.search(r"//([a-z0-9-]+)[a-z0-9.-]*\.oraclecloud\.com/hcmUI/CandidateExperience/(?:[^/]+/)?sites/[^/]+"
                      r"/(?:job|requisitions/preview)/(\d+)", url, re.I):
        return f"oracle:{m.group(1).lower()}:{m.group(2)}"
    if m := re.search(r"//([a-z0-9-]+)\.icims\.com/jobs/(\d+)", url, re.I):
        return f"icims:{m.group(1).lower()}:{m.group(2)}"
    if m := re.search(r"//([^/?#]+)/(?:[a-z0-9-]+/)?jobs/(\d+)/?\?(?:[^#]*&)?icims=1", url, re.I):
        return f"jibe:{m.group(1).lower()}:{m.group(2)}"
    if m := re.search(r"//([^/?#]+)/job/[^/?#]+/(\d{6,})/?\?(?:[^#]*&)?ats=successfactors", url, re.I):
        return f"sf:{m.group(1).lower()}:{m.group(2)}"
    if m := re.search(r"//(?:[a-z0-9-]+\.eightfold\.ai|explore\.jobs\.netflix\.net|careers\.qualcomm\.com)"
                      r"/careers(?:/job/|\?(?:[^#]*&)?pid=)(\d+)", url, re.I):
        return f"eightfold:{m.group(1)}"
    if m := re.search(r"applytojob\.com/apply/([A-Za-z0-9]{10})(?:[/?#]|$)", url):
        return f"jazz:{m.group(1)}"
    if key := sites.posting_key(url):
        return key
    if m := re.search(r"//([^/?#]+)/(?:[^/?#]+/){1,2}JobDetail(?:/(?:[^?#]*/)?(\d+)/?(?:[?#]|$)|\?(?:[^#]*&)?jobId=(\d+))", url):
        return f"avature:{avature_host(m.group(1).lower())}:{m.group(2) or m.group(3)}"
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


def place_regions(place: str | None, country: str | None) -> set[str]:
    """By the country code when there is one: "Rotterdam, NL" would read as Newfoundland."""
    return regions_for([], country) if country else regions_for([place] if place else [])


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


def _job(key, title, url, locations, regions, posted, intern_flag=False, category=None) -> dict:
    """`category` is used when the title matches none (a site that names its divisions)."""
    return {"key": key, "title": title or "", "url": url or "", "locations": locations, "regions": regions,
            "posted": posted, "intern_flag": intern_flag, "category": category}


def _looks_intern(title: str) -> bool:
    return bool(INTERN.search(title or ""))


# ---------- fetching ----------

def _download(url: str, body: dict | bytes | None = None, timeout: int = 30, accept: str = "application/json",
              headers: dict | None = None, opener=None, any_host: bool = False) -> tuple[bytes, int]:
    """GET (or POST `body`: JSON, or bytes as they are). Returns (content, bytes downloaded); 404 raises
    BoardNotFound. `headers` are added to the request; `opener` keeps cookies for sites that need them;
    `any_host` allows a redirect to another site (otherwise that means the board doesn't exist)."""
    sent = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept": accept}
    data = body if isinstance(body, bytes) else None
    if isinstance(body, dict):
        data = json.dumps(body).encode()
        sent["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers={**sent, **(headers or {})})
    try:
        with (opener.open if opener else urllib.request.urlopen)(req, timeout=timeout) as resp:
            raw = resp.read()
            size = len(raw)
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            final = resp.geturl()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise BoardNotFound(url) from exc
        raise
    if not any_host and urlparse(final).netloc != urlparse(url).netloc:  # BambooHR sends unknown boards home
        raise BoardNotFound(url)
    return raw, size


def _request(url: str, body: dict | bytes | None = None, timeout: int = 30, **options) -> tuple[object, int]:
    """GET (or POST `body`) and parse JSON. Returns (data, bytes downloaded); 404 raises BoardNotFound.

    `options` are _download()'s `headers`, `opener` and `any_host`."""
    raw, size = _download(url, body, timeout, **options)
    return json.loads(raw), size


def _request_page(url: str, timeout: int = 30, **options) -> tuple[str, int]:
    """GET a web page. Returns (text, bytes downloaded); 404 raises BoardNotFound."""
    raw, size = _download(url, timeout=timeout, accept="text/html,*/*", **options)
    return raw.decode("utf-8", errors="replace"), size


def inner_html(page: str, opening: str) -> list[str]:
    """The contents of each element whose opening tag matches the regex `opening` (say
    `<div class="description"[^>]*>`), nested elements of the same kind included."""
    found = []
    for m in re.finditer(opening, page):
        tag = re.match(r"<(\w+)", m.group(0)).group(1)
        depth = 1
        for t in re.finditer(rf"<(/?){tag}\b[^>]*>", page[m.end():]):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                found.append(page[m.end():m.end() + t.start()])
                break
    return found


def ld_job(page: str) -> dict | None:
    """The schema.org JobPosting a posting page describes itself with, if it has one."""
    for m in re.finditer(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


# Details fetched once per posting (dates, every location), kept while the app runs.
_details: dict[str, dict] = {}
DETAILS_PER_BOARD = 40


def _detail(url: str, parse, budget: list[int], timeout: int, page: bool = False) -> dict | None:
    """`parse` gets the posting's JSON, or its web page if `page` is set."""
    if url in _details:
        return _details[url]
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    try:
        data, _ = _request_page(url, timeout) if page else _request(url, timeout=timeout)
    except (OSError, ValueError, BoardNotFound):
        return None
    _details[url] = parse(data)
    return _details[url]


def _greenhouse(data: dict) -> list[dict]:
    jobs = []
    for j in data.get("jobs", []):
        locs = split_locations((j.get("location") or {}).get("name"))
        # Jane Street's titles are bare ("Software Engineer"); its custom fields say "Summer Internship".
        kind = " ".join(str(m.get("value")) for m in j.get("metadata") or []
                        if re.search(r"employment|job type|position type|worker sub ?type", m.get("name") or "", re.I))
        jobs.append(_job(f"gh:{j['id']}", j.get("title"), j.get("absolute_url"), locs, regions_for(locs),
                         _ts(j.get("first_published") or j.get("updated_at")), bool(re.search(r"\bintern", kind, re.I))))
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


# ----- Oracle Cloud -----

ORACLE_PAGE = 100
ORACLE_SEARCHES = ("intern", "co-op", "stagiaire")


def _fetch_oracle(token: str, timeout: int) -> tuple[list[dict], int, int]:
    base, tenant, site = oracle_site(token)
    api = f"{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    size = 0

    def search(keyword: str = "", first: int = 0, pages: int = 3) -> tuple[list[dict], int]:
        nonlocal size
        found, offset, total = [], first * ORACLE_PAGE, None
        while offset < (total if total is not None else offset + 1) and offset < (first + pages) * ORACLE_PAGE:
            finder = f"findReqs;siteNumber={site},limit={ORACLE_PAGE},offset={offset}"
            if keyword:  # matched loosely ("intern" finds "Internal Audit"), so titles are checked below
                finder += f",keyword={keyword}"
            data, n = _request(f"{api}?onlyData=true&expand=requisitionList.secondaryLocations&finder={finder}",
                               timeout=timeout)
            size += n
            result = (data.get("items") or [{}])[0]
            total = result.get("TotalJobsCount") or 0
            page = result.get("requisitionList") or []
            found += page
            if not page:
                break
            offset += ORACLE_PAGE
        return found, total or 0

    items, board_total = search(pages=1)
    if board_total <= 3 * ORACLE_PAGE:  # small board: read it all
        items += search(first=1, pages=2)[0] if board_total > ORACLE_PAGE else []
    else:
        items = [i for text in ORACLE_SEARCHES for i in search(text)[0] if _looks_intern(i.get("Title"))]

    jobs = {}
    for r in items:
        places = [(r.get("PrimaryLocation"), r.get("PrimaryLocationCountry"))]
        places += [(p.get("Name"), p.get("CountryCode")) for p in r.get("secondaryLocations") or []]
        locs = [loc for loc, _ in places if loc]
        regions = set().union(*(place_regions(loc, country) for loc, country in places))
        if "remote" in (r.get("WorkplaceType") or "").lower() and regions:
            regions.add("REMOTE")
        jobs[r["Id"]] = _job(f"oracle:{tenant}:{r['Id']}", r.get("Title"),
                             f"{base}/hcmUI/CandidateExperience/en/sites/{site}/job/{r['Id']}", locs, regions,
                             _ts(r.get("PostedDate")))
    return list(jobs.values()), size, board_total


# ----- iCIMS -----

ICIMS_SEARCHES = ("intern", "co-op", "stagiaire")
ICIMS_MAX_PAGES = 5  # of 20 postings each
ICIMS_PAGE = 20


def _icims_field(card: str, label: str) -> str:
    """A card's field: "<span class="sr-only field-label">Location</span> <span>CA-Remote</span>", or a
    <dt>label</dt><dd>value</dd> pair."""
    m = re.search(rf"(?:field-label\">|<dt[^>]*>){label}(?:</span>)?\s*(?:</dt>\s*<dd[^>]*>)?\s*<span[^>]*>\s*"
                  r"([^<]*?)\s*<", card)
    return html.unescape(m.group(1)) if m else ""


def _icims_cards(page: str) -> list[dict]:
    cards = []
    for card in re.split(r"<li class=\"iCIMS_JobCardItem\"", page)[1:]:
        link = re.search(r"href=\"([^\"]*?/jobs/(\d+)/[^\"]*)\"", card)
        title = re.search(r"<h3[^>]*>\s*(.*?)\s*</h3>", card, re.S)
        if not link or not title:
            continue
        posted = re.search(r"title=\"(\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2} [AP]M)\"", card)
        cards.append({
            "id": link.group(2), "title": html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip(),
            "locations": split_locations(_icims_field(card, "(?:Job )?Locations?")),
            "posted": int(datetime.strptime(posted.group(1), "%m/%d/%Y %I:%M %p").timestamp()) if posted else None,
            "intern": "intern" in _icims_field(card, "Position Type").lower(),
            "remote": _icims_field(card, "Remote").lower() == "yes",
        })
    return cards


def _icims_detail(page: str) -> dict:
    # Its datePosted can be years old on a posting reopened every season, so only the places are used.
    places = (ld_job(page) or {}).get("jobLocation") or []
    locs, regions = [], set()
    for p in places if isinstance(places, list) else [places]:
        a = (p or {}).get("address") or {}
        place = _place(*[a.get(k) for k in ("addressLocality", "addressRegion") if a.get(k) != "UNAVAILABLE"])
        country = a.get("addressCountry") if isinstance(a.get("addressCountry"), str) else None
        if place:
            locs.append(_place(place, country))
        regions |= place_regions(place, country)
    return {"locations": locs, "regions": regions}


def _fetch_icims(token: str, timeout: int) -> tuple[list[dict], int, int]:
    base = f"https://{token}.icims.com"
    found: dict[str, dict] = {}
    size = 0
    for text in ICIMS_SEARCHES:
        for n in range(ICIMS_MAX_PAGES):
            page, got = _request_page(f"{base}/jobs/search?ss=1&searchKeyword={text}&in_iframe=1&pr={n}", timeout)
            size += got
            if n == 0 and text == ICIMS_SEARCHES[0] and "iCIMS_" not in page:
                raise BoardNotFound(base)  # the portal only sends visitors to the company's own careers site
            cards = _icims_cards(page)
            for c in cards:
                found.setdefault(c["id"], c)
            pages = re.search(r"Page \d+ of (\d+)", page)
            if len(cards) < ICIMS_PAGE or pages and n + 1 >= int(pages.group(1)):
                break

    jobs, budget = [], [DETAILS_PER_BOARD]
    for c in found.values():
        locs = c["locations"]
        regions = regions_for(locs, remote=c["remote"])
        # "Multiple Locations" or no location on the card: the posting lists them.
        vague = not locs or re.search(r"multiple|\blocations\b", " ".join(locs), re.I)
        if (c["intern"] or _looks_intern(c["title"])) and not regions and vague:
            if d := _detail(f"{base}/jobs/{c['id']}/job?in_iframe=1", _icims_detail, budget, timeout, page=True):
                locs, regions = d["locations"] or locs, set(d["regions"])
                if c["remote"] and regions:
                    regions.add("REMOTE")
        jobs.append(_job(f"icims:{token}:{c['id']}", c["title"], f"{base}/jobs/{c['id']}/job", locs, regions,
                         c["posted"], c["intern"]))
    return jobs, size, len(jobs)


# ----- iCIMS career sites ("Jibe": careers.amd.com/jobs/86868?icims=1) -----

JIBE_SEARCHES = ("intern", "co-op")
JIBE_PAGE = 50
# The search returns each posting's text; there's no API for one posting, so it's kept from the
# last search, or read from the posting's page.
_jibe_texts: dict[str, str] = {}


def _fetch_jibe(token: str, timeout: int) -> tuple[list[dict], int, int]:
    jobs, size = {}, 0
    for text in JIBE_SEARCHES:  # full text, so titles are checked later
        for page in range(1, 5):
            data, n = _request(f"https://{token}/api/jobs?keywords={text}&page={page}&limit={JIBE_PAGE}", timeout=timeout)
            size += n
            found = [j.get("data") or {} for j in data.get("jobs") or []]
            for j in found:
                if not (ident := j.get("req_id") or j.get("slug")):  # a few postings carry neither
                    continue
                places = [(p, j.get("country_code"))  # "Austin, Texas; Boxborough, Massachusetts"
                          for p in split_locations(j.get("full_location") or _place(j.get("city"), j.get("state")))]
                places += [(_place(a.get("city"), a.get("state")), a.get("country_code"))
                           for a in j.get("additional_locations") or [] if isinstance(a, dict)]
                key = f"jibe:{token}:{ident}"
                jobs[key] = _job(key, j.get("title"), f"https://{token}/jobs/{ident}?icims=1",
                                 list(dict.fromkeys(_place(loc, c) for loc, c in places if loc)),
                                 set().union(*(place_regions(loc, c) for loc, c in places)),
                                 _ts((j.get("posted_date") or "").replace("+0000", "+00:00") or None))
                _jibe_texts[key] = "\n\n".join(j[k] for k in ("description", "responsibilities", "qualifications")
                                                if j.get(k))
            if len(found) < JIBE_PAGE or page * JIBE_PAGE >= (data.get("totalCount") or 0):
                break
    return list(jobs.values()), size, len(jobs)


def jibe_text(token: str, ident: str) -> str | None:
    if f"jibe:{token}:{ident}" in _jibe_texts:
        return _jibe_texts[f"jibe:{token}:{ident}"]
    page, _ = _request_page(f"https://{token}/jobs/{ident}?lang=en-us")
    return (ld_job(page) or {}).get("description") or None


# ----- SuccessFactors career sites (jobs.l3harris.com/job/…/1425609500/?ats=successfactors) -----

SF_SEARCHES = ("intern", "co-op")
SF_MAX_PAGES = 3


def _sf_rows(page: str) -> list[dict]:
    """Search results, in the table layout (25 a page) or the tile layout (100). Each title link
    appears once per screen size."""
    links = list(re.finditer(r"<a\s[^>]*jobTitle-link[^>]*>(.*?)</a>", page, re.S))
    starts: dict[str, tuple[int, str, str]] = {}
    for m in links:
        if (href := re.search(r'href="(/job/[^"]+/(\d+)/)"', m.group(0))) and href.group(2) not in starts:
            starts[href.group(2)] = (m.start(), href.group(1), html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip())
    order = sorted(starts.items(), key=lambda kv: kv[1][0])
    rows = []
    for i, (ident, (start, path, title)) in enumerate(order):
        row = page[start:order[i + 1][1][0] if i + 1 < len(order) else len(page)]
        where = re.search(r'class="jobLocation"[^>]*>\s*([^<]+?)\s*<', row) \
            or re.search(r'id="job-\d+-\w+-section-location-value"[^>]*>\s*([^<]+?)\s*<', row)
        posted = re.search(r'class="jobDate"[^>]*>\s*([^<]+?)\s*<', row)
        rows.append({"id": ident, "path": path, "title": title, "where": html.unescape(where.group(1)) if where else "",
                     "posted": posted.group(1) if posted else None})
    return rows


def _fetch_successfactors(token: str, timeout: int) -> tuple[list[dict], int, int]:
    jobs, size = {}, 0
    for text in SF_SEARCHES:  # title= searches titles only
        start = 0
        for _ in range(SF_MAX_PAGES):
            page, n = _request_page(f"https://{token}/search/?q=&title={text}&startrow={start}", timeout)
            size += n
            rows = _sf_rows(page)
            for r in rows:
                # "Chelmsford, MA, US, 1824": the third part is the country code.
                parts = [p.strip() for p in r["where"].split(",")]
                country = parts[2] if len(parts) >= 3 and re.fullmatch(r"[A-Z]{2}", parts[2]) else None
                loc = ", ".join(parts[:3]) if country else r["where"]
                try:
                    posted = int(datetime.strptime(r["posted"], "%b %d, %Y").timestamp()) if r["posted"] else None
                except ValueError:
                    posted = None
                jobs[r["id"]] = _job(f"sf:{token}:{r['id']}", r["title"], f"https://{token}{r['path']}?ats=successfactors",
                                     [loc] if loc else [], place_regions(loc, country), posted)
            total = re.search(r"of\s*(?:<b>)?\s*([\d,]+)\s*(?:</b>)?\s*(?:Jobs)?\s*</span>", page)
            start += len(rows)
            if not rows or not total or start >= int(total.group(1).replace(",", "")):
                break
    return list(jobs.values()), size, len(jobs)


def successfactors_text(url: str) -> str | None:
    page, _ = _request_page(url)
    if 'itemprop="title"' not in page:  # "Sorry, this position has been filled."
        return None
    return "\n\n".join(inner_html(page, r'<span class="jobdescription"[^>]*>')) or None


# ----- Eightfold (qualcomm.eightfold.ai, explore.jobs.netflix.net) -----

# Career sites on Eightfold under the company's own name: host -> (board, company domain). Boards
# on *.eightfold.ai use the company's .com domain unless their careers page says otherwise.
EIGHTFOLD_SITES = {"explore.jobs.netflix.net": ("explore.jobs.netflix.net", "netflix.com"),
                   "careers.qualcomm.com": ("qualcomm.eightfold.ai", "qualcomm.com")}
EIGHTFOLD_COUNTRIES = (("United States", "US"), ("Canada", "CA"))
# Eightfold turns away more than a few requests a minute from one address (Microsoft's site too),
# so boards on it are read one at a time, a second apart.
EIGHTFOLD_LOCK = threading.Lock()
_eightfold_kind: dict[str, tuple[str, str]] = {}  # host -> ("pcsx" or "v2", domain)


def eightfold_get(url: str, timeout: int = 30, opener=None) -> tuple[object, int]:
    """A first visit often gets 429 and a cookie; the retry with it goes through."""
    for attempt in range(3):
        try:
            data = _request(url, timeout=timeout, opener=opener)
            time.sleep(1)
            return data
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 2:
                raise
            time.sleep(3)


def _eightfold_site(host: str, timeout: int, opener) -> tuple[str, str]:
    """Which of its two APIs a board answers, and its company domain."""
    if host in _eightfold_kind:
        return _eightfold_kind[host]
    domain = EIGHTFOLD_SITES.get(host, (host, None))[1] or f"{host.split('.')[0]}.com"
    for attempt in range(2):
        for kind, url in (("pcsx", f"https://{host}/api/pcsx/search?domain={domain}&start=0"),
                          ("v2", f"https://{host}/api/apply/v2/jobs?domain={domain}&start=0&num=1")):
            try:
                eightfold_get(url, timeout, opener)
            except BoardNotFound:  # the wrong domain
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 422):  # the other API, or no domain
                    continue
                raise
            _eightfold_kind[host] = (kind, domain)
            return kind, domain
        if attempt == 0:  # the careers page names the domain
            page, _ = _request_page(f"https://{host}/careers", timeout, opener=opener, any_host=True)
            m = re.search(r'id="pcsx-data"[^>]*>\s*\{\s*"domain":\s*"([^"]+)"', html.unescape(page)) \
                or re.search(r'"domain":\s*"([a-z0-9.-]+\.[a-z]{2,})"', html.unescape(page))
            if not m:
                break
            domain = m.group(1)
    raise BoardNotFound(f"eightfold/{host}")


def _eightfold_facet(data: dict) -> tuple[str, str] | None:
    """The filter that means internships ("Seniority: Intern", "Employment type: INTERNSHIP")."""
    for f in ((data.get("data") or {}).get("filterDef") or {}).get("allFilters") or []:
        for o in f.get("options") or []:
            if re.search(r"\bintern(ship)?s?\b", str(o.get("label")), re.I) and f.get("filterName"):
                return f["filterName"], str(o.get("value"))
    return None


def _fetch_eightfold(token: str, timeout: int) -> tuple[list[dict], int, int]:
    with EIGHTFOLD_LOCK:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        kind, domain = _eightfold_site(token, timeout, opener)
        jobs, size, total = {}, 0, 0
        facet = None
        if kind == "pcsx":
            first, size = eightfold_get(f"https://{token}/api/pcsx/search?domain={domain}&start=0", timeout, opener)
            facet = _eightfold_facet(first)
        for country, code in EIGHTFOLD_COUNTRIES:
            start, count = 0, None
            while count is None or start < min(count, 60):
                if kind == "pcsx":
                    search = f"filter_{facet[0]}={quote(facet[1])}" if facet else "query=intern"
                    url = f"https://{token}/api/pcsx/search?domain={domain}&{search}&location={quote(country)}&start={start}"
                else:
                    url = (f"https://{token}/api/apply/v2/jobs?domain={domain}&query=intern&location={quote(country)}"
                           f"&start={start}&num=10")
                data, n = eightfold_get(url, timeout, opener)
                size += n
                found = data.get("data") or {} if kind == "pcsx" else data
                count = found.get("count") or 0
                page = found.get("positions") or []
                for p in page:
                    old = jobs.get(p["id"])
                    # "San Diego, CA, US" (pcsx) or "Los Gatos,California,United States of America" (v2)
                    locs = p.get("standardizedLocations") or p.get("locations") or []
                    regions = (old["regions"] if old else set()) | {code}
                    if (p.get("workLocationOption") or p.get("work_location_option")) == "remote":
                        regions.add("REMOTE")
                    jobs[p["id"]] = _job(f"eightfold:{p['id']}", p.get("name"), f"https://{token}/careers/job/{p['id']}",
                                         list(dict.fromkeys((old["locations"] if old else []) + locs)), regions,
                                         _ts(p.get("postedTs") or p.get("t_create")), bool(facet))
                if not page:
                    break
                start += len(page)
            total += count or 0
    # The keyword search is fuzzy ("#Software Engineer"), so without the filter titles decide.
    return [j for j in jobs.values() if facet or _looks_intern(j["title"])], size, total


def eightfold_text(token: str, ident: str) -> str | None:
    with EIGHTFOLD_LOCK:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        kind, domain = _eightfold_site(token, 30, opener)
        if kind == "pcsx":
            data, _ = eightfold_get(f"https://{token}/api/pcsx/position_details?position_id={ident}&domain={domain}&hl=en",
                                    opener=opener)
            return (data.get("data") or {}).get("jobDescription") or None
        data, _ = eightfold_get(f"https://{token}/api/apply/v2/jobs/{ident}?domain={domain}", opener=opener)
        return data.get("job_description") or None


# ----- Avature (jobs.ea.com/en_US/careers/JobDetail/…/216252, *.avature.net) -----

# Boards on *.avature.net that move to the company's own domain; links use either name.
AVATURE_HOSTS = {"bnc.avature.net": "emplois.bnc.ca", "twosigma.avature.net": "careers.twosigma.com",
                 "metlife.avature.net": "www.metlifecareers.com", "pomerleau.avature.net": "jobs.pomerleau.ca"}
# "internship" first: "intern" also finds "internal" and "international" (National Bank: 262 results).
AVATURE_SEARCHES = ("internship", "intern", "co-op", "stagiaire")
AVATURE_MAX_PAGES = 5
_avature_search: dict[str, str] = {}  # board -> its search page (Two Sigma's is OpenRoles)
AVATURE_LINK = re.compile(r'<a\b[^>]*href="(https?://[^"/]+/[^"]*?/JobDetail(?:/[^"?#]*?)?/(\d+)/?|'
                          r'https?://[^"/]+/[^"]*?/JobDetail\?(?:[^"#]*?&amp;|[^"#]*?&)?jobId=(\d+))"[^>]*>(.*?)</a>', re.S)


def avature_host(host: str) -> str:
    return AVATURE_HOSTS.get(host, host)


def _avature_cards(page: str) -> list[dict]:
    """Search results. Templates differ; each card links to the posting (often twice, with "More
    information"), and names its place in a "…location…" element or the cell after the title."""
    links = [(m.start(), html.unescape(m.group(1)), m.group(2) or m.group(3),
              html.unescape(re.sub(r"<[^>]+>", " ", m.group(4))).split()) for m in AVATURE_LINK.finditer(page)]
    firsts: dict[str, int] = {}
    titles: dict[str, str] = {}
    urls: dict[str, str] = {}
    for start, url, ident, words in links:
        firsts.setdefault(ident, start)
        urls.setdefault(ident, url)
        titles.setdefault(ident, "")
        if len(" ".join(words)) > len(titles[ident]):
            titles[ident] = " ".join(words)
    order = sorted(firsts.items(), key=lambda kv: kv[1])
    cards = []
    for i, (ident, start) in enumerate(order):
        card = page[start:order[i + 1][1] if i + 1 < len(order) else len(page)]
        places = re.findall(r'class="[^"]*(?:location|list-item-\d+)[^"]*"[^>]*>\s*([^<]{2,80}?)\s*</', card) \
            or re.findall(r"</th>\s*<td[^>]*>\s*([^<]{2,80}?)\s*</td>", card)
        if not places and (where := _avature_slug_place(urls[ident])):
            places = [where]
        kind = re.search(r'class="[^"]*workerType[^"]*"[^>]*>\s*([^<]+)', card)
        cards.append({"id": ident, "url": urls[ident], "title": titles[ident],
                      "places": list(dict.fromkeys(html.unescape(p).strip() for p in places)),
                      "intern": bool(kind and re.search(r"\bintern", kind.group(1), re.I))})
    return cards


def _avature_slug_place(url: str) -> str | None:
    """"…/JobDetail/New-York-New-York-United-States-Software-Engineering-Internship/14016" -> "New York, United States"."""
    m = re.search(r"/JobDetail/([A-Za-z-]+?)-(United-States|Canada)-", url)
    if not m:
        return None
    words = m.group(1).split("-")
    if len(words) % 2 == 0 and words[:len(words) // 2] == words[len(words) // 2:]:  # city and state share a name
        words = words[:len(words) // 2]
    return f"{' '.join(words)}, {m.group(2).replace('-', ' ')}"


def _avature_search_page(token: str, timeout: int) -> str:
    if token not in _avature_search:
        try:
            _request_page(f"https://{token}/SearchJobs/", timeout, any_host=True)
            _avature_search[token] = f"https://{token}/SearchJobs/"
        except BoardNotFound:  # the form on the portal's home page says where its search is
            home, _ = _request_page(f"https://{token}", timeout, any_host=True)
            m = re.search(r'<form[^>]+id="tpt_jobSortableForm"[^>]*action="([^"]+)"', home) \
                or re.search(r'<form[^>]+action="([^"]+)"[^>]*id="tpt_jobSortableForm"', home)
            if not m:
                raise
            _avature_search[token] = html.unescape(m.group(1)).rstrip("/") + "/"
    return _avature_search[token]


def _fetch_avature(token: str, timeout: int) -> tuple[list[dict], int, int]:
    search, found, size = _avature_search_page(token, timeout), {}, 0
    for text in AVATURE_SEARCHES:
        url = f"{search}?search={text}&jobOffset=0"
        for _ in range(AVATURE_MAX_PAGES):
            page, n = _request_page(url, timeout, any_host=True)
            size += n
            cards = _avature_cards(page)
            for c in cards:
                found.setdefault(c["id"], c)
            nxt = re.search(r'<a[^>]*paginationNextLink[^>]*href="([^"]+)"|<a[^>]*href="([^"]+)"[^>]*paginationNextLink', page)
            # Results come best first: a page with no internships ends the search.
            if not nxt or not any(_looks_intern(c["title"]) for c in cards):
                break
            url = html.unescape(nxt.group(1) or nxt.group(2))
    jobs = []
    for c in found.values():
        host = avature_host(urlparse(c["url"]).netloc)
        jobs.append(_job(f"avature:{host}:{c['id']}", c["title"], c["url"], c["places"], regions_for(c["places"]),
                         None, c["intern"]))
    return jobs, size, len(jobs)


def avature_text(url: str) -> str | None:
    page, _ = _request_page(url, any_host=True)
    blocks = inner_html(page, r'<div class="article__content__view__field__value"[^>]*>')
    return "\n\n".join(blocks) or None


# ----- JazzHR (*.applytojob.com) -----

def jazzhr_feed(token: str, timeout: int = 30) -> tuple[list[dict], int]:
    """The company's whole board, with each posting's text."""
    page, size = _request_page(f"https://app.jazz.co/feeds/export/jobs/{token}", timeout)
    return [{c.tag: (c.text or "").strip() for c in job} for job in ElementTree.fromstring(page).iter("job")], size


def _fetch_jazzhr(token: str, timeout: int) -> tuple[list[dict], int, int]:
    found, size = jazzhr_feed(token, timeout)
    jobs = []
    for j in found:
        code = re.search(r"/apply/([A-Za-z0-9]{10})", j.get("url") or "")
        if not code:
            continue
        place = _place(j.get("city"), j.get("state"))
        # No date: its ID holds when the job was created, which can be months before it was posted.
        jobs.append(_job(f"jazz:{code.group(1)}", j.get("title"), j.get("url"), [_place(place, j.get("country"))],
                         place_regions(place, j.get("country")), None, (j.get("type") or "").lower() == "internship"))
    return jobs, size, len(jobs)


FETCHERS = {"workday": _fetch_workday, "smartrecruiters": _fetch_smartrecruiters, "bamboohr": _fetch_bamboohr,
            "rippling": _fetch_rippling, "recruiterbox": _fetch_recruiterbox, "oracle": _fetch_oracle,
            "icims": _fetch_icims, "jibe": _fetch_jibe, "successfactors": _fetch_successfactors,
            "eightfold": _fetch_eightfold, "avature": _fetch_avature, "jazzhr": _fetch_jazzhr}


def fetch_board(platform: str, token: str, timeout: int = 30) -> tuple[list[dict], int, int]:
    """Return (postings read from the board, bytes downloaded, jobs on the board). Raises BoardNotFound.

    Workday and SmartRecruiters return only their US/Canada internship candidates, and big Oracle
    Cloud boards and iCIMS only their internship candidates; the rest return every posting.
    """
    if platform == "site":
        return sites.fetch(token, timeout)
    if platform in FETCHERS:
        return FETCHERS[platform](token, timeout)
    feed = f"{lever_api(token)}?mode=json" if platform == "lever" else FEEDS[platform].format(token=token)
    data, size = _request(feed, timeout=timeout)
    jobs = PARSERS[platform](data)
    return jobs, size, len(jobs)


def internships(jobs: list[dict]) -> list[dict]:
    """Keep tech internships located in the US or Canada."""
    kept = []
    for j in jobs:
        title = j["title"]
        if not (INTERN.search(title) or j["intern_flag"]) or NOT_INTERN.search(title):
            continue
        category = tech_category(title) or j.get("category")
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
    # Career sites that are themselves iCIMS (Jibe) or SuccessFactors sites, on the company's domain.
    host = urlparse(final).netloc.lower()
    if "jibecdn.com" in page or 'ng-app="jibeapply"' in page:
        return {"platform": "jibe", "token": host, "name": name}
    if "rmkcdn.successfactors.com" in page:
        return {"platform": "successfactors", "token": host, "name": name}
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


from . import sites  # noqa: E402 (it builds on this module, so it's imported last)
