import json
import unittest
import urllib.error
from unittest import mock

from board import ats, postings, sites
from board.ats import internships, parse_board_url, posting_key


def fake(answers):
    """Stand-in for ats._request / ats._request_page: answers by URL, or by (URL, a word in the body)."""
    calls = []

    def answer(url, body=None, timeout=30, **options):
        calls.append((url, body, options))
        text = body.decode() if isinstance(body, bytes) else json.dumps(body) if body is not None else ""
        found = next((a for (u, word), a in ((k if isinstance(k, tuple) else (k, None), v) for k, v in answers.items())
                      if u == url and (word is None or word in text)), None)
        if isinstance(found, Exception):
            raise found
        if found is None:
            raise AssertionError(f"unexpected request: {url} {text[:200]}")
        return found, 100
    return answer, calls


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, None)


class LinksTest(unittest.TestCase):
    def test_sites_are_boards(self):
        cases = {
            "https://amazon.jobs/en/jobs/10517567/software-development-engineer-intern": ("site", "amazon"),
            "https://www.google.com/about/careers/applications/jobs/results/113855697199735494": ("site", "google"),
            "https://apply.careers.microsoft.com/careers/job/1970393556982928": ("site", "microsoft"),
            "https://jobs.apple.com/en-us/details/200664323": ("site", "apple"),
            "https://www.metacareers.com/jobs/1940312740718917": ("site", "meta"),
            "https://lifeattiktok.com/search/7611950589973186821": ("site", "tiktok"),
            "https://jobs.bytedance.com/en/position/7623552847531493685/detail": ("site", "bytedance"),
            "https://higher.gs.com/roles/171566?type=students": ("site", "goldman"),
            "https://careers.ibm.com/careers/JobDetail?jobId=136727": ("site", "ibm"),
            "https://www.shopify.com/careers/intern-dev_1affb074-f055-4f2e-9d4b-000000000000": ("site", "shopify"),
            "https://jobs.uber.com/en/jobs/303922/": ("oracle", "iaziqy.fa.ocs/CX_1"),
            "https://stripe.com/jobs/search?gh_jid=7000": ("greenhouse", "stripe"),
            "https://www.janestreet.com/join-jane-street/apply/7001?gh_jid=7001": ("greenhouse", "janestreet"),
        }
        for url, want in cases.items():
            self.assertEqual(parse_board_url(url), want, url)
        for url in ["https://www.google.com/search?q=intern", "https://www.shopify.com/pricing",
                    "https://www.apple.com/careers/"]:
            self.assertIsNone(parse_board_url(url), url)

    def test_posting_keys(self):
        cases = {
            "https://www.amazon.jobs/en/jobs/10584130/creative-marketing-intern": "amazon:10584130",
            "https://account.amazon.jobs/jobs/10584130/apply": "amazon:10584130",
            "https://www.google.com/about/careers/applications/jobs/results/8180977-people-analytics-intern": "google:8180977",
            "https://apply.careers.microsoft.com/careers?pid=1970393556982928&domain=microsoft.com": "microsoft:1970393556982928",
            "https://jobs.apple.com/en-us/details/200673612-0157/applied-data?team=STDNT": "apple:200673612",
            "https://www.metacareers.com/profile/job_details/1940312740718917/": "meta:1940312740718917",
            "https://joinbytedance.com/search/7623552847531493685": "bytedance:7623552847531493685",
            "https://higher.gs.com/roles/171566?type=students": "goldman:171566",
            "https://careers.ibm.com/en_US/careers/JobDetail?jobId=136727": "ibm:136727",
            "https://www.shopify.com/careers?ashby_jid=1affb074-f055-4f2e-9d4b-000000000000":
                "shopify:1affb074-f055-4f2e-9d4b-000000000000",
            # Uber's site and its Oracle board give the same key.
            "https://jobs.uber.com/en/jobs/303922/": "oracle:iaziqy:303922",
            "https://iaziqy.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/303922": "oracle:iaziqy:303922",
        }
        for url, want in cases.items():
            self.assertEqual(posting_key(url), want, url)

    def test_listed_sites(self):
        for token, site in sites.SITES.items():
            self.assertEqual(parse_board_url(site.page), ("site", token), token)
        self.assertEqual(ats.board_page("site", "amazon"), sites.SITES["amazon"].page)


class AmazonTest(unittest.TestCase):
    def test_reads_internships(self):
        url = ("https://www.amazon.jobs/en/search.json?is_intern%5B%5D=1&normalized_country_code%5B%5D=USA"
               "&normalized_country_code%5B%5D=CAN&result_limit=100&offset=0&sort=recent")
        place = lambda name, iso: json.dumps({"normalizedLocation": name, "countryIso2a": iso})
        page = {"hits": 2, "jobs": [
            {"id_icims": "10584121", "title": "Software Development Engineer Intern, Summer 2027",
             "job_path": "/en/jobs/10584121/sde-intern", "posted_date": "October  9, 2026", "country_code": "CAN",
             "locations": [place("Toronto, Ontario, CAN", "CA"), place("Vancouver, British Columbia, CAN", "CA")]},
            {"id_icims": "10584130", "title": "Creative Marketing Intern", "job_path": "/en/jobs/10584130/x",
             "posted_date": "October 20, 2026", "country_code": "USA", "locations": [place("Seattle, Washington, USA", "US")]}]}
        request, _ = fake({url: page})
        with mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, total = ats.fetch_board("site", "amazon")
        self.assertEqual(total, 2)
        kept = internships(jobs)
        self.assertEqual([(j["key"], j["regions"], j["locations"], j["category"]) for j in kept],
                         [("amazon:10584121", {"CA"}, ["Toronto, Ontario, CAN", "Vancouver, British Columbia, CAN"],
                           "Software")])
        self.assertEqual(kept[0]["url"], "https://www.amazon.jobs/en/jobs/10584121/sde-intern")
        self.assertEqual(kept[0]["posted"], int(sites.datetime(2026, 10, 9).timestamp()))

    def test_description(self):
        url = "https://www.amazon.jobs/en/search.json?base_query=10584121&result_limit=10"
        request, _ = fake({url: {"jobs": [{"id_icims": "10584121", "description": "Build things.",
                                           "basic_qualifications": "- Enrolled in a degree"}]}})
        with mock.patch.object(ats, "_request", side_effect=request):
            self.assertEqual(sites.text("amazon", "10584121"),
                             "Build things.\n\n<h3>Basic qualifications</h3>- Enrolled in a degree")
        request, _ = fake({url: {"jobs": []}})
        with mock.patch.object(ats, "_request", side_effect=request):
            self.assertIsNone(sites.text("amazon", "10584121"))


def google_page(key, data):
    return (f"<script class=\"ds:{key}\" nonce=\"x\">AF_initDataCallback({{key: 'ds:{key}', hash: '2', "
            f"data:{json.dumps(data)}, sideChannel: {{}}}});</script>")


def google_job(id, title, places):
    job = [None] * 21
    job[0], job[1], job[9], job[12] = id, title, places, [1787559294, 0]
    job[10], job[3], job[4] = [None, "<p>About</p>"], [None, "<ul><li>Build</li></ul>"], [None, "<p>Quals</p>"]
    return job


class GoogleTest(unittest.TestCase):
    URL = sites.GOOGLE + "?location=United%20States&location=Canada&employment_type=INTERN&page="

    def test_reads_internships(self):
        jobs = [google_job("91436104816698054", "Software Engineering Intern, Summer 2027",
                           [["Waterloo, ON, Canada", [], "Waterloo", None, "ON", "CA"]]),
                # Province-only places would read as California without the country code.
                google_job("81809776362562246", "Software Engineering Intern, Fall 2026",
                           [["Alberta, CA", [], None, None, "AB", "CA"], ["Austin, TX, USA", [], "Austin", None, "TX", "US"]])]
        request, _ = fake({self.URL + "1": google_page("1", [jobs, None, 2, 20])})
        with mock.patch.object(ats, "_request_page", side_effect=request):
            found, _, total = ats.fetch_board("site", "google")
        self.assertEqual(total, 2)
        by_key = {j["key"]: j for j in found}
        self.assertEqual(by_key["google:91436104816698054"]["regions"], {"CA"})
        self.assertEqual(by_key["google:81809776362562246"]["regions"], {"CA", "US"})
        self.assertEqual(by_key["google:91436104816698054"]["posted"], 1787559294)

    def test_changed_page_is_an_error(self):
        request, _ = fake({self.URL + "1": google_page("1", [[["not", "a", "job"]], None, 1, 20])})
        with mock.patch.object(ats, "_request_page", side_effect=request), self.assertRaises(ValueError):
            ats.fetch_board("site", "google")

    def test_description(self):
        page = google_page("0", [google_job("91436104816698054", "x", [])])
        request, _ = fake({sites.GOOGLE + "91436104816698054": page, sites.GOOGLE + "5": "<html>no ds:0</html>"})
        with mock.patch.object(ats, "_request_page", side_effect=request):
            self.assertEqual(sites.text("google", "91436104816698054"),
                             "<p>About</p>\n\n<ul><li>Build</li></ul>\n\n<p>Quals</p>")
            self.assertIsNone(sites.text("google", "5"))  # taken down: the page loads without the posting


class MicrosoftTest(unittest.TestCase):
    def url(self, country, start=0):
        return (f"{sites.MICROSOFT}/api/pcsx/search?domain=microsoft.com&query=&location={country}"
                f"&filter_employment_type=internship&start={start}")

    def test_retries_after_429_and_reads_both_countries(self):
        us = {"data": {"count": 1, "positions": [
            {"id": 1970393557040909, "name": "Software Engineering Intern", "postedTs": 1792540800,
             "locations": ["United States, Washington, Redmond"], "workLocationOption": "onsite"}]}}
        ca = {"data": {"count": 1, "positions": [
            {"id": 1970393557041012, "name": "Stagiaire, génie logiciel", "postedTs": 1792540800,
             "locations": ["Canada, Québec, Montreal"], "workLocationOption": "remote"}]}}
        attempts = []

        def request(url, body=None, timeout=30, opener=None):
            attempts.append(url)
            if len(attempts) == 1:
                raise http_error(429)  # the first visit: a cookie and "try again"
            if "start=1" in url:
                return {"data": {"count": 1, "positions": []}}, 10
            return (us if "United%20States" in url else ca), 100

        with mock.patch.object(ats, "_request", side_effect=request), mock.patch.object(ats.time, "sleep"):
            jobs, _, total = ats.fetch_board("site", "microsoft")
        self.assertEqual(attempts[:2], [self.url("United%20States")] * 2)
        self.assertEqual(total, 2)
        by_key = {j["key"]: j for j in jobs}
        self.assertEqual(by_key["microsoft:1970393557040909"]["locations"], ["Redmond, Washington, United States"])
        self.assertEqual(by_key["microsoft:1970393557041012"]["regions"], {"CA", "REMOTE"})
        self.assertEqual(by_key["microsoft:1970393557040909"]["url"],
                         "https://apply.careers.microsoft.com/careers/job/1970393557040909")


class AppleTest(unittest.TestCase):
    def test_merges_locations(self):
        rows = [{"positionId": "200673612", "postingTitle": "Software Engineering Internship", "postDateInGMT":
                 "2026-08-27T20:41:24.044Z", "transformedPostingTitle": "software-engineering-internship",
                 "locations": [{"name": where, "countryName": "United States of America"}]}
                for where in ("Austin", "Cupertino")]
        data = {"loaderData": {"search": {"searchResults": rows, "totalRecords": 2}}}
        page = f"<script>window.__staticRouterHydrationData = JSON.parse({json.dumps(json.dumps(data))});</script>"
        url = f"{sites.APPLE}/en-us/search?team=internships-STDNT-INTRN&location=united-states-USA+canada-CANC&page=1"
        request, _ = fake({url: page})
        with mock.patch.object(ats, "_request_page", side_effect=request):
            jobs, _, total = ats.fetch_board("site", "apple")
        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0]["locations"], jobs[0]["regions"]), (["Austin", "Cupertino"], {"US"}))
        self.assertEqual(jobs[0]["url"], "https://jobs.apple.com/en-us/details/200673612/software-engineering-internship")


class MetaTest(unittest.TestCase):
    PAGE = ('<link rel="preload" href="https://static.xx.fbcdn.net/rsrc.php/v4/a.js" as="script">'
            '["LSD",[],{"token":"AdSo2QZ"}]')
    RESULTS = {"data": {"job_search_with_featured_jobs": {"all_jobs": [
        {"id": "1078644001656413", "title": "Research Scientist Intern (PhD)", "locations": ["Menlo Park, CA"]},
        {"id": "2281070982817094", "title": "Software Engineer Intern", "locations": ["London, UK"]}]}}}

    def setUp(self):
        self.addCleanup(lambda saved=list(sites._meta_query): sites._meta_query.__setitem__(slice(None), saved))

    def test_reads_internships(self):
        pages, _ = fake({f"{sites.META}/jobsearch/": self.PAGE})
        request, calls = fake({f"{sites.META}/graphql": self.RESULTS})
        with mock.patch.object(ats, "_request_page", side_effect=pages), mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, _ = ats.fetch_board("site", "meta")
        self.assertIn(b"lsd=AdSo2QZ", calls[0][1])
        self.assertEqual(calls[0][2]["headers"]["X-FB-LSD"], "AdSo2QZ")
        self.assertEqual([(j["key"], j["regions"]) for j in internships(jobs)], [("meta:1078644001656413", {"US"})])

    def test_finds_the_new_query_id(self):
        sites._meta_query[0] = "1"
        script = '__d("CareersJobSearchResultsDataQuery_candidate_portalRelayOperation",[],(function(t,n,r,o,a,i){a.exports="42"}),null);'
        pages, _ = fake({f"{sites.META}/jobsearch/": self.PAGE, "https://static.xx.fbcdn.net/rsrc.php/v4/a.js": script})

        def request(url, body=None, timeout=30, **options):
            if b"doc_id=42" not in body:
                raise ats.BoardNotFound(url)  # a stale ID answers 404
            return self.RESULTS, 100

        with mock.patch.object(ats, "_request_page", side_effect=pages), mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, _ = ats.fetch_board("site", "meta")
        self.assertEqual(len(jobs), 2)
        self.assertEqual(sites._meta_query[0], "42")

    def test_no_query_id_is_an_error_not_a_missing_board(self):
        pages, _ = fake({f"{sites.META}/jobsearch/": self.PAGE, "https://static.xx.fbcdn.net/rsrc.php/v4/a.js": "x"})
        with mock.patch.object(ats, "_request_page", side_effect=pages), \
                mock.patch.object(ats, "_request", side_effect=ats.BoardNotFound("graphql")), self.assertRaises(ValueError):
            ats.fetch_board("site", "meta")


class TikTokTest(unittest.TestCase):
    API = "https://api.lifeattiktok.com/api/v1/public/supplier"

    def test_searches_us_and_canada_cities(self):
        country = lambda name: {"code": "CN", "en_name": name}
        filters = {"data": {"city_list": [
            {"code": "CT_94", "en_name": "Seattle", "parent": {"en_name": "Washington", "parent": country("United States of America")}},
            {"code": "CT_242", "en_name": "Toronto", "parent": {"en_name": "Ontario", "parent": country("Canada")}},
            {"code": "CT_11", "en_name": "London", "parent": country("United Kingdom")}]}}
        posts = {"data": {"count": 1, "job_post_list": [
            {"id": "7694360097210861829", "title": "Machine Learning Engineer Intern - 2027 Summer",
             "recruit_type": {"id": "202", "en_name": "Intern"}, "description": "Build ranking.", "requirement": "Python.",
             "city_info": {"en_name": "Ashburn", "parent": {"en_name": "Virginia",
                                                           "parent": country("United States of America")}}}]}}
        request, calls = fake({f"{self.API}/config/job/filters": filters, f"{self.API}/search/job/posts": posts})
        with mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, total = ats.fetch_board("site", "tiktok")
        self.assertEqual(calls[1][1]["location_code_list"], ["CT_94", "CT_242"])
        self.assertEqual(calls[1][2]["headers"], {"website-path": "tiktok"})
        self.assertEqual((total, jobs[0]["locations"], jobs[0]["regions"], jobs[0]["intern_flag"]),
                         (1, ["Ashburn, Virginia, United States of America"], {"US"}, True))
        self.assertEqual(jobs[0]["url"], "https://lifeattiktok.com/search/7694360097210861829")
        self.assertEqual(sites.text("tiktok", "7694360097210861829"),
                         "<h3>Responsibilities</h3>Build ranking.\n\n<h3>Qualifications</h3>Python.")

    def test_description_from_the_page(self):
        page = ('<h3>Responsibilities</h3><p class="tt-text whitespace-pre-line">Build things.\nShip them.</p>'
                '<p class="tt-text whitespace-pre-line">Know Go.</p>')
        request, _ = fake({"https://lifeattiktok.com/search/123": page})
        with mock.patch.object(ats, "_request_page", side_effect=request):
            self.assertEqual(postings._plain(sites.text("tiktok", "123")), "Build things.\nShip them.\n\nKnow Go.")


class GoldmanTest(unittest.TestCase):
    def test_titles_and_categories(self):
        role = lambda sid, title, division: {
            "externalSource": {"sourceId": sid}, "jobTitle": title, "corporateTitle": "Summer Analyst",
            "division": division, "startDate": "2026-08-16T03:38:49.569352846Z",
            "locations": [{"city": "Bellevue", "state": "WA", "country": "United States"}]}
        data = {"data": {"roleSearch": {"totalCount": 2, "items": [
            role("177808", "2027 | Americas | Bellevue | Engineering | Summer Analyst", "Engineering Division"),
            role("185000", "2027 | Americas | New York City Area | Global Banking & Markets | Summer Analyst",
                 "Global Banking & Markets")]}}}
        request, _ = fake({sites.GOLDMAN_API: data})
        with mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, _ = ats.fetch_board("site", "goldman")
        kept = internships(jobs)
        self.assertEqual([(j["key"], j["title"], j["category"], j["terms"], j["regions"]) for j in kept],
                         [("goldman:177808", "Summer Analyst 2027, Engineering", "Software", ["Summer 2027"], {"US"})])
        self.assertEqual(kept[0]["url"], "https://higher.gs.com/roles/177808")


class IbmTest(unittest.TestCase):
    def test_country_decides(self):
        data = {"hits": {"total": {"value": 2}, "hits": [
            {"_source": {"field_text_01": 136727, "title": "Software Developer Intern", "field_keyword_05": "United States",
                         "field_keyword_19": "POUGHKEEPSIE, US", "field_keyword_18": "Internship", "dcdate": "2026-10-19",
                         "url": "https://careers.ibm.com/careers/JobDetail?jobId=136727"}},
            {"_source": {"field_text_01": 136728, "title": "Software Developer Intern", "field_keyword_05": "Canada",
                         "field_keyword_19": "Multiple Cities", "field_keyword_17": "Remote",
                         "field_keyword_18": "Internship", "dcdate": "2026-10-19", "url": "u"}}]}}
        request, _ = fake({(sites.IBM_API, '"from": 0'): data,
                           (sites.IBM_API, '"from": 100'): {"hits": {"total": {"value": 2}, "hits": []}}})
        with mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, total = ats.fetch_board("site", "ibm")
        self.assertEqual(total, 2)
        self.assertEqual([(j["locations"], j["regions"]) for j in jobs],
                         [(["Poughkeepsie, United States"], {"US"}), (["Canada"], {"CA", "REMOTE"})])


class ShopifyTest(unittest.TestCase):
    FEED = """<?xml version="1.0"?><source>
      <job><partnerJobId>1affb074-f055-4f2e-9d4b-000000000001</partnerJobId><title>Software Engineering Intern</title>
        <applyUrl>https://www.shopify.com/careers/swe-intern_1affb074-f055-4f2e-9d4b-000000000001?utm_source=x</applyUrl>
        <location>NAMER</location><workplaceTypes>Remote</workplaceTypes><experienceLevel>INTERNSHIP</experienceLevel>
        <listDate>10/20/2026</listDate><description>&lt;p&gt;Build commerce.&lt;/p&gt;</description></job>
      <job><partnerJobId>1affb074-f055-4f2e-9d4b-000000000002</partnerJobId><title>Engineer, Internal Tools</title>
        <applyUrl>https://www.shopify.com/careers/tools_1affb074-f055-4f2e-9d4b-000000000002</applyUrl>
        <location>Ireland</location><experienceLevel>MID_SENIOR_LEVEL</experienceLevel></job>
    </source>"""

    def test_feed(self):
        request, _ = fake({f"{sites.SHOPIFY}/feed.xml": self.FEED})
        with mock.patch.object(ats, "_request_page", side_effect=request):
            jobs, _, total = ats.fetch_board("site", "shopify")
            description = sites.text("shopify", "1affb074-f055-4f2e-9d4b-000000000001")
        kept = internships(jobs)
        self.assertEqual(total, 2)
        self.assertEqual([(j["key"], j["regions"], j["url"]) for j in kept],
                         [("shopify:1affb074-f055-4f2e-9d4b-000000000001", {"US", "CA", "REMOTE"},
                           "https://www.shopify.com/careers/swe-intern_1affb074-f055-4f2e-9d4b-000000000001")])
        self.assertEqual(description, "<p>Build commerce.</p>")


class SiteErrorsTest(unittest.TestCase):
    def test_a_404_is_an_error_not_a_missing_board(self):
        with mock.patch.object(ats, "_request", side_effect=ats.BoardNotFound("x")), self.assertRaises(ValueError):
            ats.fetch_board("site", "amazon")

    def test_unknown_site(self):
        with self.assertRaises(ats.BoardNotFound):
            ats.fetch_board("site", "nope")


class PostingTextTest(unittest.TestCase):
    def test_site_postings(self):
        with mock.patch.object(sites, "text", return_value="<p>We sponsor visas.</p>") as text:
            self.assertEqual(postings.api_text({"url": "https://jobs.apple.com/en-us/details/200664323",
                                                "board": "site:apple", "posting_key": "apple:200664323"}),
                             "We sponsor visas.")
        text.assert_called_once_with("apple", "200664323")

    def test_greenhouse_id_without_a_board_name(self):
        seen = []
        with mock.patch.object(postings, "_resolve", return_value=
                               "https://job-boards.greenhouse.io/embed/job_app?for=coinbase&token=8300829") as resolve, \
                mock.patch.object(postings, "_get_json", side_effect=lambda url: seen.append(url) or {"content": "&lt;p&gt;Hi&lt;/p&gt;"}):
            text = postings.api_text({"url": "https://boards.greenhouse.io/embed/job_app?token=8300829",
                                      "board": None, "posting_key": None})
        resolve.assert_called_once_with("https://boards.greenhouse.io/embed/job_app?token=8300829")
        self.assertEqual(seen, ["https://boards-api.greenhouse.io/v1/boards/coinbase/jobs/8300829"])
        self.assertEqual(text, "Hi")


if __name__ == "__main__":
    unittest.main()
