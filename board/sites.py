"""Big companies' own career sites, read like job boards.

Amazon, Google, Microsoft, Apple, Meta, TikTok, ByteDance, Goldman Sachs, IBM and Shopify run their
own job sites instead of a shared job board.
Each one is a board on the "site" platform with the company as its token (("site", "amazon")), so
it joins the watchlist and the Companies page like any other board. Each site is searched for its
internships in the US and Canada, using the site's own internship filter.

These sites aren't published for programs to read, so they can change without notice. A reader
that stops matching raises an error rather than finding nothing: the listings already found are
kept, and the Companies page shows the error. A 404 is reported the same way, so a site board is
never switched off as if it no longer existed. Meta, TikTok and ByteDance don't say when a job was
posted, so their postings have no date.

Not here: Tesla (Akamai) and Citadel (Cloudflare) turn away programs, so their internships come
only from the community lists.

Some career sites are only a front for a job board this app already reads (Uber's for Oracle Cloud,
Stripe's for Greenhouse). FRONTS maps their links to that board, so the board is found and its
postings match the ones the community lists link to.
"""

import html
import http.cookiejar
import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

from . import ats


@dataclass(frozen=True)
class Site:
    name: str
    page: str  # the careers page as a person sees it
    link: str  # a regex for the site's job links, after "//"
    key: str  # a regex for a posting's ID in its link; the posting's key is "<token>:<ID>"
    fetch: Callable[[int], tuple[list[dict], int, int]]  # (postings, bytes downloaded, jobs found)
    text: Callable[[str], str | None]  # a posting's description (HTML or text), None if it was taken down


# ---------- Amazon ----------

AMAZON = "https://www.amazon.jobs"


def _amazon_date(text: str | None) -> int | None:
    """"October  9, 2026" (two spaces before a single-digit day) -> that day."""
    try:
        return int(datetime.strptime(" ".join((text or "").split()), "%B %d, %Y").timestamp())
    except ValueError:
        return None


def _amazon(timeout: int) -> tuple[list[dict], int, int]:
    jobs, size, offset, hits = {}, 0, 0, None
    while hits is None or offset < min(hits, 1000):
        data, n = ats._request(f"{AMAZON}/en/search.json?is_intern%5B%5D=1&normalized_country_code%5B%5D=USA"
                               f"&normalized_country_code%5B%5D=CAN&result_limit=100&offset={offset}&sort=recent",
                               timeout=timeout)
        size += n
        hits = data.get("hits") or 0
        page = data.get("jobs") or []
        for j in page:
            # Each location is a JSON string; "US, WA, Seattle" (the plain field) reads as nowhere.
            places = [json.loads(p) for p in j.get("locations") or [] if isinstance(p, str)]
            locs = [p["normalizedLocation"] for p in places if p.get("normalizedLocation")]
            regions = set().union(*(ats.place_regions(None, p.get("countryIso2a")) for p in places))
            jobs[j["id_icims"]] = ats._job(
                f"amazon:{j['id_icims']}", j.get("title"), AMAZON + j["job_path"],
                locs or [j.get("normalized_location") or ""], regions or ats.regions_for([], j.get("country_code")),
                _amazon_date(j.get("posted_date")), True)
        if not page:
            break
        offset += 100
    return list(jobs.values()), size, hits or 0


def _amazon_text(ident: str) -> str | None:
    # There's no posting API; a search for the ID finds it.
    data, _ = ats._request(f"{AMAZON}/en/search.json?base_query={ident}&result_limit=10")
    job = next((j for j in data.get("jobs") or [] if j.get("id_icims") == ident), None)
    if not job:
        return None
    return "\n\n".join(f"<h3>{label}</h3>{job[k]}" if label else job[k] for label, k in [
        ("", "description"), ("Basic qualifications", "basic_qualifications"),
        ("Preferred qualifications", "preferred_qualifications")] if job.get(k))


# ---------- Google ----------

GOOGLE = "https://www.google.com/about/careers/applications/jobs/results/"
# The results are JSON inside the page, as positional arrays: [id, title, apply link, …].
_GOOGLE_DATA = re.compile(r"AF_initDataCallback\(\{key: 'ds:(\d+)', hash: '[^']*', data:(.*?), sideChannel: \{\}\}\);"
                          r"</script>", re.S)


def _google_data(page: str, key: str):
    m = next((m for m in _GOOGLE_DATA.finditer(page) if m.group(1) == key), None)
    return json.loads(m.group(2)) if m else None


def _google_job(j) -> bool:
    return isinstance(j, list) and len(j) > 12 and str(j[0]).isdigit() and isinstance(j[1], str) \
        and isinstance(j[9], list)


def _google(timeout: int) -> tuple[list[dict], int, int]:
    jobs, size, number, total = {}, 0, 1, None
    while total is None or (number - 1) * 20 < min(total, 300):
        page, n = ats._request_page(f"{GOOGLE}?location=United%20States&location=Canada&employment_type=INTERN"
                                    f"&page={number}", timeout)
        size += n
        data = _google_data(page, "1")
        if not (isinstance(data, list) and len(data) > 2 and isinstance(data[0] or [], list)
                and all(_google_job(j) for j in data[0] or [])):
            raise ValueError("Google's results page has changed")
        total = data[2] or 0
        for j in data[0] or []:
            # Each place is [display, addresses, city, postal code, region, country code]; "Alberta, CA"
            # would read as California, so the country code decides.
            places = [p for p in j[9] if isinstance(p, list) and p]
            regions = set().union(*(ats.place_regions(p[0], p[5] if len(p) > 5 else None) for p in places))
            posted = j[12][0] if isinstance(j[12], list) and j[12] else None
            jobs[j[0]] = ats._job(f"google:{j[0]}", j[1], f"{GOOGLE}{j[0]}", [p[0] for p in places], regions,
                                  posted, True)
        if not data[0]:
            break
        number += 1
    return list(jobs.values()), size, total or 0


def _google_text(ident: str) -> str | None:
    page, _ = ats._request_page(f"{GOOGLE}{ident}")
    data = _google_data(page, "0")  # a posting that was taken down still loads, without it
    if not (isinstance(data, list) and data and _google_job(data[0]) and data[0][0] == ident):
        return None
    j = data[0]
    return "\n\n".join(part[1] for part in (j[10], j[3], j[4], j[15] if len(j) > 15 else None)
                       if isinstance(part, list) and len(part) > 1 and part[1])


# ---------- Microsoft ----------

# Its site runs on Eightfold, read like ats.py's Eightfold boards (one at a time, with a cookie), but
# with Microsoft's own internship filter and its "United States, Washington, Redmond" places.
MICROSOFT = "https://apply.careers.microsoft.com"


def _cookies():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _microsoft(timeout: int) -> tuple[list[dict], int, int]:
    with ats.EIGHTFOLD_LOCK:
        return _microsoft_search(timeout)


def _microsoft_search(timeout: int) -> tuple[list[dict], int, int]:
    opener, jobs, size, total = _cookies(), {}, 0, 0
    for country, code in (("United States", "US"), ("Canada", "CA")):
        start, count = 0, None
        while count is None or start < min(count, 300):
            data, n = ats.eightfold_get(f"{MICROSOFT}/api/pcsx/search?domain=microsoft.com&query="
                                        f"&location={quote(country)}&filter_employment_type=internship&start={start}",
                                        timeout, opener)
            size += n
            found = data.get("data") or {}
            count = found.get("count") or 0
            page = found.get("positions") or []
            for p in page:
                old = jobs.get(p["id"])
                # "United States, Washington, Redmond" -> "Redmond, Washington, United States"
                locs = [", ".join(reversed(l.split(", "))) for l in p.get("locations") or []]
                regions = (old["regions"] if old else set()) | {code}
                if p.get("workLocationOption") == "remote":
                    regions.add("REMOTE")
                jobs[p["id"]] = ats._job(f"microsoft:{p['id']}", p.get("name"), f"{MICROSOFT}/careers/job/{p['id']}",
                                         list(dict.fromkeys((old["locations"] if old else []) + locs)), regions,
                                         ats._ts(p.get("postedTs")), True)
            if not page:
                break
            start += len(page)
        total += count or 0
    return list(jobs.values()), size, total


def _microsoft_text(ident: str) -> str | None:
    with ats.EIGHTFOLD_LOCK:
        data, _ = ats.eightfold_get(f"{MICROSOFT}/api/pcsx/position_details?position_id={ident}"
                                    f"&domain=microsoft.com&hl=en", opener=_cookies())
    return (data.get("data") or {}).get("jobDescription") or None


# ---------- Apple ----------

APPLE = "https://jobs.apple.com"


def _apple(timeout: int) -> tuple[list[dict], int, int]:
    jobs, size, number, total = {}, 0, 1, None
    while total is None or (number - 1) * 20 < min(total, 400):
        page, n = ats._request_page(f"{APPLE}/en-us/search?team=internships-STDNT-INTRN"
                                    f"&location=united-states-USA+canada-CANC&page={number}", timeout)
        size += n
        m = re.search(r"window\.__staticRouterHydrationData\s*=\s*JSON\.parse\((\".*?\")\);", page, re.S)
        if not m:
            raise ValueError("Apple's search page has changed")
        search = (json.loads(json.loads(m.group(1))).get("loaderData") or {}).get("search") or {}
        total = search.get("totalRecords") or 0
        rows = search.get("searchResults") or []
        for r in rows:  # one row per location
            pid, places = r["positionId"], r.get("locations") or []
            old = jobs.get(pid)
            locs = (old["locations"] if old else []) + [p["name"] for p in places if p.get("name")]
            regions = (old["regions"] if old else set()).union(
                *(ats.place_regions(p.get("name"), p.get("countryName")) for p in places))
            if r.get("homeOffice") and regions:
                regions.add("REMOTE")
            slug = r.get("transformedPostingTitle")
            jobs[pid] = ats._job(f"apple:{pid}", r.get("postingTitle"),
                                 f"{APPLE}/en-us/details/{pid}" + (f"/{slug}" if slug else ""),
                                 list(dict.fromkeys(locs)), regions, ats._ts(r.get("postDateInGMT")), True)
        if not rows:
            break
        number += 1
    return list(jobs.values()), size, total or 0


def _apple_text(ident: str) -> str | None:
    job = ats._request(f"{APPLE}/api/v1/jobDetails/{ident}")[0].get("res") or {}
    return "\n\n".join(f"{label}\n{job[k]}" if label else job[k] for label, k in [
        ("", "jobSummary"), ("", "description"), ("Minimum qualifications", "minimumQualifications"),
        ("Preferred qualifications", "preferredQualifications")] if job.get(k)) or None


# ---------- Meta ----------

META = "https://www.metacareers.com"
# The search is a stored query whose ID changes when Meta updates its site; _meta_query_id() finds
# the current one in the site's scripts.
_meta_query = ["27506805582236862"]
META_QUERY = re.compile(r'CareersJobSearchResultsDataQuery_candidate_portalRelayOperation",\[\],\(function\([^)]*\)'
                        r'\{[a-z]\.exports="(\d+)"')


def _meta_search(token: str, timeout: int) -> tuple[object, int]:
    variables = {"isLoggedIn": False, "viewasUserID": None, "search_input": {
        "q": None, "divisions": [], "offices": [], "roles": ["Internship"], "leadership_levels": [], "saved_jobs": [],
        "saved_searches": [], "sub_teams": [], "teams": [], "is_leadership": False, "is_remote_only": False,
        "sort_by_new": False, "page": 1, "results_per_page": None}}
    form = urlencode({"lsd": token, "fb_api_caller_class": "RelayModern", "server_timestamps": "true",
                      "fb_api_req_friendly_name": "CareersJobSearchResultsDataQuery", "doc_id": _meta_query[0],
                      "variables": json.dumps(variables)}).encode()
    return ats._request(f"{META}/graphql", form, timeout, headers={
        "Content-Type": "application/x-www-form-urlencoded", "X-FB-LSD": token, "Origin": META,
        "X-FB-Friendly-Name": "CareersJobSearchResultsDataQuery", "Referer": f"{META}/jobsearch/"})


def _meta_query_id(page: str, timeout: int) -> str:
    scripts = re.findall(r"https://static\.xx\.fbcdn\.net/rsrc\.php/[^\"'\s]+\.js[^\"'\s]*", page.replace("\\/", "/"))
    for url in list(dict.fromkeys(scripts))[:20]:
        script, _ = ats._request_page(url, timeout)
        if m := META_QUERY.search(script):
            return m.group(1)
    raise ValueError("Meta's job search has changed: its query wasn't found")


def _meta(timeout: int) -> tuple[list[dict], int, int]:
    page, size = ats._request_page(f"{META}/jobsearch/", timeout)
    m = re.search(r'"LSD",\[\],\{"token":"([^"]+)"', page)
    if not m:
        raise ValueError("Meta's search page has changed")
    try:
        data, n = _meta_search(m.group(1), timeout)
    except ats.BoardNotFound:  # a stale query ID answers 404
        _meta_query[0] = _meta_query_id(page, timeout)
        data, n = _meta_search(m.group(1), timeout)
    size += n
    found = ((data.get("data") or {}).get("job_search_with_featured_jobs") or {}).get("all_jobs")
    if not isinstance(found, list):
        raise ValueError("Meta's job search has changed")
    # The search doesn't say when a job was posted.
    jobs = [ats._job(f"meta:{j['id']}", j.get("title"), f"{META}/jobs/{j['id']}", j.get("locations") or [],
                     ats.regions_for(j.get("locations") or []), None, True) for j in found]
    return jobs, size, len(jobs)


def _meta_text(ident: str) -> str | None:
    posting = ats.ld_job(ats._request_page(f"{META}/jobs/{ident}")[0])
    if not posting:
        return None
    return "\n\n".join(f"<h3>{label}</h3>{posting[k]}" if label else posting[k] for label, k in [
        ("", "description"), ("Responsibilities", "responsibilities"), ("Qualifications", "qualifications")]
        if isinstance(posting.get(k), str))


# ---------- TikTok and ByteDance ----------

# One career-site system serves both. Its search returns each posting's full text; there is no API
# for one posting, so the text is kept from the last search, or read from the posting's page.
_atsx_texts: dict[str, str] = {}


def _atsx(api: str, site_path: str, public: str, prefix: str):
    """A reader for one of these sites: its API, its "website-path" header, posting pages, key prefix."""
    headers = {"website-path": site_path}

    def fetch(timeout: int) -> tuple[list[dict], int, int]:
        # The location filter takes only city codes; the list holds the cities with open jobs.
        filters, size = ats._request(f"{api}/config/job/filters", {}, timeout, headers=headers)
        if not isinstance((filters.get("data") or {}).get("city_list"), list):
            raise ValueError("The career site's filters have changed")
        cities = []
        for city in filters["data"]["city_list"]:
            top = city
            while top.get("parent"):
                top = top["parent"]
            if top.get("en_name") in ("United States of America", "Canada"):
                cities.append(city["code"])
        jobs, offset, count = {}, 0, None
        while cities and (count is None or offset < min(count, 2000)):
            data, n = ats._request(f"{api}/search/job/posts", {
                "recruitment_id_list": ["202"], "job_category_id_list": [], "subject_id_list": [],  # 202: interns
                "location_code_list": cities, "keyword": "", "limit": 100, "offset": offset}, timeout, headers=headers)
            size += n
            found = data.get("data") or {}
            count = found.get("count") or 0
            page = found.get("job_post_list") or []
            for j in page:
                place, node = [], j.get("city_info") or {}
                while node:  # city -> state -> country
                    place.append(node.get("en_name"))
                    node = node.get("parent")
                loc = ats._place(*place)
                jobs[j["id"]] = ats._job(f"{prefix}:{j['id']}", j.get("title"), f"{public}{j['id']}",
                                         [loc] if loc else [], ats.place_regions(loc, place[-1] if place else None),
                                         None, (j.get("recruit_type") or {}).get("id") == "202")
                _atsx_texts[f"{prefix}:{j['id']}"] = "\n\n".join(
                    f"<h3>{label}</h3>{j[k]}" for label, k in [("Responsibilities", "description"),
                                                                ("Qualifications", "requirement")] if j.get(k))
            if not page:
                break
            offset += 100
        return list(jobs.values()), size, count or 0

    def text(ident: str) -> str | None:
        if f"{prefix}:{ident}" in _atsx_texts:
            return _atsx_texts[f"{prefix}:{ident}"]
        page, _ = ats._request_page(f"{public}{ident}")
        blocks = re.findall(r'<p class="[^"]*whitespace-pre-line[^"]*"[^>]*>(.*?)</p>', page, re.S)
        return "\n\n".join(b.replace("\n", "<br>") for b in blocks) or None

    return fetch, text


_tiktok = _atsx("https://api.lifeattiktok.com/api/v1/public/supplier", "tiktok", "https://lifeattiktok.com/search/",
                "tiktok")
_bytedance = _atsx("https://jobs.bytedance.com/api/v1/public/supplier", "en", "https://joinbytedance.com/search/",
                   "bytedance")


# ---------- Goldman Sachs ----------

GOLDMAN = "https://higher.gs.com"
GOLDMAN_API = "https://api-higher.gs.com/gateway/api/v1/graphql"
GOLDMAN_ROLES = ("query GetCampusRoles($searchQueryInput: RoleSearchQueryInput!) { roleSearch(searchQueryInput: "
                 "$searchQueryInput) { totalCount items { corporateTitle jobTitle locations { state country city } "
                 "division externalSource { sourceId } startDate } } }")
GOLDMAN_ROLE = ("query GetRoleById($externalSourceId: String!, $externalSourceFetch: Boolean) { role(externalSourceId: "
                "$externalSourceId, externalSourceFetch: $externalSourceFetch) { descriptionHtml } }")


def _goldman(timeout: int) -> tuple[list[dict], int, int]:
    jobs, size, number, total = {}, 0, 0, None
    while total is None or number * 100 < min(total, 1000):
        data, n = ats._request(GOLDMAN_API, {"operationName": "GetCampusRoles", "query": GOLDMAN_ROLES, "variables": {
            "searchQueryInput": {
                "page": {"pageSize": 100, "pageNumber": number}, "sort": {"sortStrategy": "POSTED_DATE", "sortOrder": "DESC"},
                "filters": [{"filterCategoryType": "LOCATION", "filters": [{"filter": c, "subFilters": []}
                                                                           for c in ("United States", "Canada")]},
                            # Summer Analyst and Associate are the internships; "New Analyst" is for graduates.
                            {"filterCategoryType": "EXPERIENCE_LEVEL", "filters": [
                                {"filter": t, "subFilters": []} for t in ("Summer Analyst", "Summer Associate")]}],
                "experiences": ["CAMPUS"], "searchTerm": ""}}}, timeout)
        size += n
        found = (data.get("data") or {}).get("roleSearch")
        if not isinstance(found, dict):
            raise ValueError("Goldman Sachs's job search has changed")
        total = found.get("totalCount") or 0
        for r in found.get("items") or []:
            sid = r["externalSource"]["sourceId"]
            # "2027 | Americas | Bellevue | Engineering | Summer Analyst" -> "Summer Analyst 2027, Engineering"
            title, parts = r.get("jobTitle") or "", [p.strip() for p in (r.get("jobTitle") or "").split("|")]
            if len(parts) >= 4 and re.fullmatch(r"20\d\d", parts[0]):
                title = f"{parts[-1]} {parts[0]}, {parts[-2]}"
            places = r.get("locations") or []
            # Its titles rarely name the work; the Engineering Division is its technology arm.
            category = None
            if r.get("division") == "Engineering Division":
                category = "Quant" if re.search(r"\bquant", title, re.I) else "Software"
            jobs[sid] = ats._job(f"goldman:{sid}", title, f"{GOLDMAN}/roles/{sid}",
                                 [ats._place(p.get("city"), p.get("state"), p.get("country")) for p in places],
                                 set().union(*(ats.place_regions(None, p.get("country")) for p in places)),
                                 ats._ts(r.get("startDate")), (r.get("corporateTitle") or "").startswith("Summer"),
                                 category)
        if not found.get("items"):
            break
        number += 1
    return list(jobs.values()), size, total or 0


def _goldman_text(ident: str) -> str | None:
    data, _ = ats._request(GOLDMAN_API, {"operationName": "GetRoleById", "query": GOLDMAN_ROLE,
                                         "variables": {"externalSourceId": ident, "externalSourceFetch": False}})
    return ((data.get("data") or {}).get("role") or {}).get("descriptionHtml") or None


# ---------- IBM ----------

IBM = "https://www.ibm.com/careers/search"
IBM_API = "https://www-api.ibm.com/search/api/v2"


def _ibm(timeout: int) -> tuple[list[dict], int, int]:
    jobs, size, offset, total = {}, 0, 0, None
    while total is None or offset < min(total, 1000):
        data, n = ats._request(IBM_API, {
            "appId": "careers", "scopes": ["careers2"], "query": {"bool": {"must": []}},
            "post_filter": {"bool": {"must": [{"term": {"field_keyword_18": "Internship"}},
                                              {"terms": {"field_keyword_05": ["United States", "Canada"]}}]}},
            "size": 100, "from": offset, "sort": [{"dcdate": "desc"}], "lang": "zz", "sm": {"query": "", "lang": "zz"},
            # Only listed fields come back: id, title, link, place ("POUGHKEEPSIE, US"), country, level, workplace
            "_source": ["_id", "title", "url", "field_keyword_05", "field_keyword_17", "field_keyword_18",
                        "field_keyword_19", "field_text_01", "dcdate"]}, timeout)
        size += n
        hits = data.get("hits")
        if not isinstance(hits, dict):
            raise ValueError("IBM's job search has changed")
        total = (hits.get("total") or {}).get("value") or 0
        for h in hits.get("hits") or []:
            j = h.get("_source") or {}
            country, where = j.get("field_keyword_05"), j.get("field_keyword_19") or ""
            city = where.rsplit(",", 1)[0].strip() if "," in where else ""
            regions = ats.place_regions(None, country)
            if j.get("field_keyword_17") == "Remote" and regions:
                regions.add("REMOTE")
            jobs[str(j["field_text_01"])] = ats._job(
                f"ibm:{j['field_text_01']}", j.get("title"), j.get("url"),
                [ats._place(city.title() if city.isupper() else city, country)], regions, ats._ts(j.get("dcdate")),
                j.get("field_keyword_18") == "Internship")
        if not hits.get("hits"):
            break
        offset += 100
    return list(jobs.values()), size, total or 0


def _ibm_text(ident: str) -> str | None:
    return None  # posting pages sit behind a browser check; the search has only a 250-character snippet


# ---------- Shopify ----------

SHOPIFY = "https://www.shopify.com/careers"


def _shopify_jobs(timeout: int = 30) -> tuple[list[dict], int]:
    """Its job feed (built for LinkedIn): every opening, with its full description."""
    page, size = ats._request_page(f"{SHOPIFY}/feed.xml", timeout)
    return [{c.tag: (c.text or "").strip() for c in job} for job in ElementTree.fromstring(page).iter("job")], size


def _shopify(timeout: int) -> tuple[list[dict], int, int]:
    found, size = _shopify_jobs(timeout)
    jobs = []
    for j in found:
        where = j.get("location") or ""
        # Places are regions: "Canada", "United States", or "NAMER" / "Remote - Americas" for both.
        regions = ats.regions_for([where]) or ({"US", "CA"} if re.search(r"namer|americas", where, re.I) else set())
        if "remote" in (j.get("workplaceTypes") or "").lower() and regions:
            regions.add("REMOTE")
        try:
            posted = int(datetime.strptime(j.get("listDate") or "", "%m/%d/%Y").timestamp())
        except ValueError:
            posted = None
        jobs.append(ats._job(f"shopify:{j['partnerJobId']}", html.unescape(j.get("title") or ""),
                             (j.get("applyUrl") or "").split("?")[0], [where] if where else [], regions, posted,
                             j.get("experienceLevel") == "INTERNSHIP"))
    return jobs, size, len(jobs)


def _shopify_text(ident: str) -> str | None:
    return next((j.get("description") for j in _shopify_jobs()[0] if j.get("partnerJobId") == ident), None) or None


# ---------- the table ----------

SITES = {
    "amazon": Site("Amazon", f"{AMAZON}/en/search?is_intern[]=1", r"(?:www\.|account\.)?amazon\.jobs/",
                   r"amazon\.jobs/(?:[a-z]{2}(?:-[a-z]{2})?/)?jobs/(\d+)", _amazon, _amazon_text),
    "google": Site("Google", f"{GOOGLE}?employment_type=INTERN",
                   r"(?:www\.)?google\.com/about/careers/|careers\.google\.com/",
                   r"(?:google\.com/about/careers/applications|careers\.google\.com)/jobs/results/(\d+)",
                   _google, _google_text),
    "microsoft": Site("Microsoft", f"{MICROSOFT}/careers?filter_employment_type=internship",
                      r"(?:apply\.|jobs\.)?careers\.microsoft\.com/",
                      r"apply\.careers\.microsoft\.com/careers(?:/job/|\?(?:.*&)?pid=)(\d+)", _microsoft,
                      _microsoft_text),
    "apple": Site("Apple", f"{APPLE}/en-us/search?team=internships-STDNT-INTRN", r"jobs\.apple\.com/",
                  r"jobs\.apple\.com/[a-z]{2}-[a-z]{2}/details/(\d+)", _apple, _apple_text),
    "meta": Site("Meta", f"{META}/jobsearch/?roles[0]=Internship", r"(?:www\.)?metacareers\.com/",
                 r"metacareers\.com/(?:v2/)?(?:jobs|profile/job_details)/(\d+)", _meta, _meta_text),
    "tiktok": Site("TikTok", "https://lifeattiktok.com/search?recruitment_id_list=202", r"(?:www\.)?lifeattiktok\.com/",
                   r"lifeattiktok\.com/search/(\d{15,22})", *_tiktok),
    "bytedance": Site("ByteDance", "https://joinbytedance.com/search?recruitment_id_list=202",
                      r"jobs\.bytedance\.com/|(?:www\.)?joinbytedance\.com/",
                      r"(?:jobs\.bytedance\.com/(?:[a-z]{2}(?:-[A-Z]{2})?/)?position/|joinbytedance\.com/search/)(\d{15,22})",
                      *_bytedance),
    "goldman": Site("Goldman Sachs", f"{GOLDMAN}/results?EXPERIENCE_LEVEL=Summer%20Analyst|Summer%20Associate",
                    r"higher\.gs\.com/", r"higher\.gs\.com/roles/(\d+)", _goldman, _goldman_text),
    "ibm": Site("IBM", f"{IBM}?field_keyword_18[0]=Internship", r"careers\.ibm\.com/|(?:www\.)?ibm\.com/careers",
                r"careers\.ibm\.com/(?:[a-z]{2}_[A-Z]{2}/)?careers/JobDetail\?jobId=(\d+)", _ibm, _ibm_text),
    "shopify": Site("Shopify", SHOPIFY, r"(?:www\.)?shopify\.com/careers",
                    r"shopify\.com/careers(?:/[a-z0-9-]+_|\?(?:.*&)?ashby_jid=)([0-9a-f-]{36})", _shopify, _shopify_text),
}

# Career sites in front of a job board this app reads: (link regex, the board, posting ID regex,
# posting key prefix). The key matches the one the board's own links give. Sites that pass the
# Greenhouse ID along (?gh_jid=…) need no regex: ats.posting_key() reads it.
FRONTS = [
    (r"jobs\.uber\.com/", ("oracle", "iaziqy.fa.ocs/CX_1"), r"jobs\.uber\.com/(?:[a-z]{2}(?:-[a-z]{2})?/)?jobs/(\d+)",
     "oracle:iaziqy"),
    (r"careers\.withwaymo\.com/", ("greenhouse", "waymo"), None, None),
    (r"(?:www\.)?stripe\.com/jobs", ("greenhouse", "stripe"), None, None),
    (r"(?:www\.)?pinterestcareers\.com/", ("greenhouse", "pinterest"), None, None),
    # CareerPuck's names aren't the Greenhouse ones ("domino-data-lab" is "dominodatalab").
    (r"app\.careerpuck\.com/job-board/lyft(?:/|$)", ("greenhouse", "lyft"), None, None),
    (r"app\.careerpuck\.com/job-board/domino-data-lab(?:/|$)", ("greenhouse", "dominodatalab"), None, None),
    (r"(?:www\.)?epicgames\.com/(?:site/[a-z-]+/)?careers", ("greenhouse", "epicgames"), None, None),
    (r"(?:www\.)?d2l\.com/careers", ("greenhouse", "d2l"), None, None),
    (r"(?:www\.)?tower-research\.com/open-positions", ("greenhouse", "towerresearchcapital"), None, None),
    (r"(?:www\.)?zipline\.com/open-roles", ("greenhouse", "flyzipline"), None, None),
    (r"(?:www\.)?janestreet\.com/join-jane-street", ("greenhouse", "janestreet"), None, None),
]


def board_for(url: str) -> tuple[str, str] | None:
    """("site", token) for a career site's link, or the board a front sits on. `url` starts with "//"."""
    for token, site in SITES.items():
        if re.match(rf"//(?:{site.link})", url, re.I):
            return "site", token
    for link, board, _, _ in FRONTS:
        if re.match(rf"//(?:{link})", url, re.I):
            return board
    return None


def posting_key(url: str) -> str | None:
    for token, site in SITES.items():
        if m := re.search(site.key, url, re.I):
            return f"{token}:{m.group(1)}"
    for _, _, key, prefix in FRONTS:
        if key and (m := re.search(key, url, re.I)):
            return f"{prefix}:{m.group(1)}"
    return None


def fetch(token: str, timeout: int) -> tuple[list[dict], int, int]:
    if token not in SITES:
        raise ats.BoardNotFound(f"site/{token}")
    try:
        return SITES[token].fetch(timeout)
    except ats.BoardNotFound as exc:  # a page that moved, not a company that's gone
        raise ValueError(f"{SITES[token].name}'s career site answered 404; it may have changed") from exc


def text(token: str, ident: str) -> str | None:
    """A posting's description. Network errors are raised; a posting that's gone gives None."""
    try:
        return SITES[token].text(ident)
    except ats.BoardNotFound:
        return None
