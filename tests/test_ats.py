import io
import json
import time
import unittest
import urllib.error
from unittest import mock

from board import ats
from board.ats import internships, parse_board_url, posting_key, regions_for, tech_category, terms_from


class BoardUrlTest(unittest.TestCase):
    def test_parse(self):
        cases = {
            "https://job-boards.greenhouse.io/cloudflare/jobs/123": ("greenhouse", "cloudflare"),
            "boards.greenhouse.io/Stripe": ("greenhouse", "stripe"),
            "https://boards.greenhouse.io/embed/job_app?for=gemini&token=7875125": ("greenhouse", "gemini"),
            "https://boards-api.greenhouse.io/v1/boards/geotab/jobs": ("greenhouse", "geotab"),
            "https://jobs.lever.co/palantir/6ed76ce8-4156-4b60-b120-403538bd66cd": ("lever", "palantir"),
            "jobs.lever.co/palantir": ("lever", "palantir"),
            "https://jobs.ashbyhq.com/bree/5e79b2fd/application": ("ashby", "bree"),
            "https://api.ashbyhq.com/posting-api/job-board/snowflake": ("ashby", "snowflake"),
            "https://job-boards.eu.greenhouse.io/imc/jobs/4979079101": ("greenhouse", "imc"),
            "https://boards.greenhouse.io/embed/coinbase/jobs/123": ("greenhouse", "coinbase"),
            "https://jobs.eu.lever.co/cirrus/b0eeba19-9950-4e6b-a709-037e271a71fd/apply": ("lever", "eu/cirrus"),
            "https://careers.withwaymo.com/jobs?gh_jid=8189848": ("greenhouse", "waymo"),
            "https://app.careerpuck.com/job-board/domino-data-lab/job/9?gh_jid=1": ("greenhouse", "dominodatalab"),
        }
        for url, want in cases.items():
            self.assertEqual(parse_board_url(url), want, url)
        for url in ["https://boards.greenhouse.io/embed/job_app?token=7625508",
                    "https://example.com/careers/jobs/123", "https://app.careerpuck.com/job-board/acme/job/1"]:
            self.assertIsNone(parse_board_url(url), url)

    def test_posting_key_matches_across_url_styles(self):
        self.assertEqual(posting_key("https://job-boards.greenhouse.io/x/jobs/5309667008"), "gh:5309667008")
        self.assertEqual(posting_key("https://boards.greenhouse.io/embed/job_app?for=x&token=5309667008"),
                         "gh:5309667008")
        self.assertEqual(posting_key("http://jobs.ashbyhq.com/bree/5e79b2fd-164c-4e72-91ef-1b8fd1c5518a/application"),
                         "ashby:5e79b2fd-164c-4e72-91ef-1b8fd1c5518a")
        self.assertEqual(posting_key("https://jobs.eu.lever.co/cirrus/b0eeba19-9950-4e6b-a709-037e271a71fd/apply"),
                         "lever:b0eeba19-9950-4e6b-a709-037e271a71fd")
        self.assertIsNone(posting_key("https://example.com/careers/1"))


class FilterTest(unittest.TestCase):
    def test_tech_category(self):
        cases = {
            "Software Engineer Intern": "Software",
            "Machine Learning Engineer Intern - Ads": "AI/ML/Data",
            "Data Science Intern - Customer Success": "AI/ML/Data",
            "Firmware Engineer Intern (Ottawa)": "Hardware",
            "Quantitative Trader Intern": "Quant",
            "Product Manager Intern": "Product",
            "Member of Technical Staff Intern": "Software",
            "Information Technology Intern": "Software",
        }
        for title, want in cases.items():
            self.assertEqual(tech_category(title), want, title)
        for title in ["Marketing Intern", "Mechanical Engineering Intern", "Propulsion Test Engineering Intern",
                      "Intern - Sales Strategy & Analytics", "Development and Fundraising Intern",
                      "Water Infrastructure Engineering Intern", "Civil Engineering Co-op"]:
            self.assertIsNone(tech_category(title), title)

    def test_terms(self):
        self.assertEqual(terms_from("SWE Intern - Summer 2027"), ["Summer 2027"])
        self.assertEqual(terms_from("Co-op (Winter/January 2027, 12 Months)"), ["Winter 2027"])
        self.assertEqual(terms_from("Software Intern"), [])

    def test_regions(self):
        self.assertEqual(regions_for(["Oakville, Ontario - Canada"]), {"CA"})
        self.assertEqual(regions_for(["US-WA-Bellevue"]), {"US"})
        self.assertEqual(regions_for(["CA-ON-Toronto"]), {"CA"})  # ISO prefix: Canada, not California
        self.assertEqual(regions_for(["Singapore, Singapore"], "SG"), set())
        self.assertEqual(regions_for(["Toronto"], "CA", remote=True), {"CA", "REMOTE"})

    def test_internships(self):
        def job(title, regions=frozenset({"US"}), flag=False):
            return {"key": title, "title": title, "url": "", "locations": [], "regions": set(regions),
                    "posted": None, "intern_flag": flag}
        kept = internships([
            job("Software Engineer Intern"),
            job("Software Engineer"),                          # not an internship
            job("Backend Engineer", flag=True),                # platform says it's an internship
            job("International Software Engineer"),            # "intern" inside another word
            job("Internship Program Manager"),                 # runs the program
            job("Software Engineer Intern", regions=set()),   # outside US/Canada
            job("Marketing Intern"),
        ])
        self.assertEqual([j["title"] for j in kept], ["Software Engineer Intern", "Backend Engineer"])


class FirstSeenTest(unittest.TestCase):
    def test_late_discoveries_are_not_new(self):
        from board.sources import first_seen_for
        now = 1_800_000_000
        self.assertEqual(first_seen_for(now - 3600, now), now)              # posted an hour ago: new
        self.assertEqual(first_seen_for(None, now), now)                    # no date: trust discovery
        self.assertEqual(first_seen_for(now - 55 * 86400, now), now - 55 * 86400)  # found late: not new


class MorePlatformsTest(unittest.TestCase):
    def test_parse(self):
        cases = {
            "https://cae.wd3.myworkdayjobs.com/career/job/Montreal-St-Laurent/Stagiaire_123040-1": ("workday", "cae.wd3/career"),
            "https://rbc.wd3.myworkdayjobs.com/en-US/RBCEARLYTALENT1": ("workday", "rbc.wd3/rbcearlytalent1"),
            "https://wd1.myworkdaysite.com/recruiting/snapchat/snap/job/LA/Intern_Q1": ("workday", "snapchat.wd1/snap"),
            "https://jobs.smartrecruiters.com/Ubisoft2/744000156420839-programmer": ("smartrecruiters", "ubisoft2"),
            "careers.smartrecruiters.com/Gameloft": ("smartrecruiters", "gameloft"),
            "https://apply.workable.com/nuvei/j/7DE79BE9A8/": ("workable", "nuvei"),
            "https://ludia.bamboohr.com/careers/225": ("bamboohr", "ludia"),
            "https://ats.rippling.com/dialogue/jobs/ceae3af1-66d0-40f0-9d9a-dcbecfa578c1": ("rippling", "dialogue"),
            "https://navaide.breezy.hr/p/3fe610df21d6-ai-developer": ("breezy", "navaide"),
            "https://tsimagine.hire.trakstar.com/jobs/fk0zlh8/": ("recruiterbox", "tsimagine"),
            "https://jsapi.recruiterbox.com/v1/openings?client_name=tsimagine": ("recruiterbox", "tsimagine"),
            "https://hdks.fa.ca2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/9412": ("oracle", "hdks.fa.ca2/CX_1"),
            "https://fa-etbx-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/nfcu/job/32107":
                ("oracle", "fa-etbx-saasfaprod1.fa.ocs/nfcu"),
            "https://egup.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/sites/CX/requisitions": ("oracle", "egup.fa.us2/CX"),
            "https://careers-kinaxis.icims.com/jobs/35329/job?mobile=true&needsRedirect=false": ("icims", "careers-kinaxis"),
            "https://careersus-shure.icims.com/jobs/search?ss=1": ("icims", "careersus-shure"),
        }
        for url, want in cases.items():
            self.assertEqual(parse_board_url(url), want, url)
        for url in ["https://cae.wd3.myworkdayjobs.com/", "https://apply.workable.com/j/7DE79BE9A8",
                    "https://www.bamboohr.com/careers", "https://w.recruiterbox.com/static/x.js",
                    "https://login.oraclecloud.com/", "https://www.icims.com/careers"]:
            self.assertIsNone(parse_board_url(url), url)

    def test_posting_keys(self):
        cases = {
            # The same Workday job from SimplifyJobs and from the board: one key, whatever the URL style.
            "https://cae.wd3.myworkdayjobs.com/career/job/Montreal-St-Laurent/Programme-Stage_120714": "wd:cae:120714",
            "https://cae.wd3.myworkdayjobs.com/en-US/career/job/Montreal-St-Laurent/Programme-Stage_120714/apply": "wd:cae:120714",
            "https://x.wd1.myworkdayjobs.com/Ext/job/New_York/Software_Intern_R123?source=list": "wd:x:R123",
            "https://wd1.myworkdaysite.com/recruiting/snapchat/snap/job/LA/PM-Intern_Q126PMI-1/": "wd:snapchat:Q126PMI-1",
            "https://jobs.smartrecruiters.com/PAConsulting/744000156517869": "sr:744000156517869",
            "https://apply.workable.com/nuvei/j/7de79be9a8/apply": "workable:7DE79BE9A8",
            "https://ludia.bamboohr.com/careers/225/": "bamboo:ludia:225",
            "https://ats.rippling.com/dialogue/jobs/ceae3af1-66d0-40f0-9d9a-dcbecfa578c1": "rippling:ceae3af1-66d0-40f0-9d9a-dcbecfa578c1",
            "https://navaide.breezy.hr/p/3fe610df21d6-ai-developer": "breezy:3fe610df21d6",
            "https://tsimagine.hire.trakstar.com/jobs/fk0zlh8/": "rbox:fk0zlh8",
            "https://app.careerpuck.com/job-board/lyft/job/88?gh_jid=8843341002": "gh:8843341002",
            "https://hdks.fa.ca2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/9412": "oracle:hdks:9412",
            "https://hdks.fa.ca2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions/preview/9412/?x=1":
                "oracle:hdks:9412",
            "https://careers-kinaxis.icims.com/jobs/35329/job?mobile=true&needsRedirect=false": "icims:careers-kinaxis:35329",
            "https://careers-kinaxis.icims.com/jobs/35329/intern-developer/job": "icims:careers-kinaxis:35329",
        }
        for url, want in cases.items():
            self.assertEqual(posting_key(url), want, url)

    def test_board_page(self):
        self.assertEqual(ats.board_page("workday", "cae.wd3/career"), "https://cae.wd3.myworkdayjobs.com/career")
        self.assertEqual(ats.board_page("recruiterbox", "tsimagine"), "https://tsimagine.hire.trakstar.com/")
        self.assertEqual(ats.board_page("lever", "eu/cirrus"), "https://jobs.eu.lever.co/cirrus")
        self.assertEqual(ats.board_page("lever", "palantir"), "https://jobs.lever.co/palantir")
        self.assertEqual(ats.lever_api("eu/cirrus"), "https://api.eu.lever.co/v0/postings/cirrus")
        self.assertEqual(ats.board_page("oracle", "hdks.fa.ca2/CX_1"),
                         "https://hdks.fa.ca2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1")
        self.assertEqual(ats.board_page("icims", "careers-kinaxis"), "https://careers-kinaxis.icims.com/jobs/search?ss=1")


class FrenchTest(unittest.TestCase):
    def test_internship_titles(self):
        for title in ["Stagiaire - Développement logiciel", "Stage en génie logiciel (Été 2027)",
                      "Développeur(se) Full Stack - Stage", "Programme CAE Tech - Stage et bourse d'études",
                      "Étudiant(e) en génie informatique"]:
            self.assertTrue(ats.INTERN.search(title), title)
        for title in ["Stage Manager", "Early Stage Investor", "Conseiller(ère) à la vie étudiante",
                      "Coordonnatrice des stages"]:
            self.assertFalse(ats.INTERN.search(title) and not ats.NOT_INTERN.search(title), title)

    def test_categories(self):
        cases = {
            "Stagiaire - Développement logiciel": "Software", "Stagiaire en science des données": "AI/ML/Data",
            "Stagiaire - Intelligence artificielle": "AI/ML/Data", "Stagiaire en génie électrique": "Hardware",
            "Stagiaire - Gestion de produit": "Product", "Stagiaire - Analyste TI": "Software",
            "Stagiaire en sécurité informatique": "Software",
        }
        for title, want in cases.items():
            self.assertEqual(tech_category(title), want, title)
        for title in ["Stagiaire en ressources humaines", "Stagiaire - Génie mécanique", "Programme de stages en finance",
                      "Intern - Cedar Rapids, IA"]:
            self.assertIsNone(tech_category(title), title)

    def test_terms(self):
        self.assertEqual(terms_from("Stage en développement - Hiver 2027"), ["Winter 2027"])
        self.assertEqual(terms_from("Stagiaire, été 2027"), ["Summer 2027"])
        self.assertEqual(terms_from("Stage d'automne 2026"), ["Fall 2026"])


def fake_requests(responses):
    """Stand-in for ats._request: answers by URL (and by the facets a Workday search applies)."""
    calls = []

    def request(url, body=None, timeout=30):
        calls.append((url, body))
        key = (url, repr(sorted((body or {}).get("appliedFacets", {}).items())) if body else None)
        answer = responses.get(key, responses.get(url))
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise AssertionError(f"unexpected request: {key}")
        return answer, 100
    return request, calls


class WorkdayTest(unittest.TestCase):
    API = "https://cae.wd3.myworkdayjobs.com/wday/cxs/cae/career"

    def facets(self, *pairs):
        return repr(sorted(pairs))

    def test_reads_internships_by_country(self):
        listing = lambda title, path, where, posted="Posted Today": {
            "title": title, "externalPath": path, "locationsText": where, "postedOn": posted}
        first = {"total": 384, "jobPostings": [listing("BI Analyst", "/job/x/BI_1", "Montreal")], "facets": [
            {"facetParameter": "workerSubType", "values": [
                {"descriptor": "Regular", "id": "reg", "count": 350},
                {"descriptor": "COOP-Student (Fixed Term)", "id": "coop", "count": 20},
                {"descriptor": "Student (Fixed Term)", "id": "student", "count": 6}]},
            {"facetParameter": "jobFamilyGroup", "values": [{"descriptor": "Student", "id": "fam", "count": 14}]},
            {"facetParameter": "locationMainGroup", "values": [{"facetParameter": "Location_Country", "values": [
                {"descriptor": "Canada", "id": "ca", "count": 200},
                {"descriptor": "United States of America", "id": "us", "count": 150},
                {"descriptor": "India", "id": "in", "count": 4}]}]},
        ]}
        intern = ["coop", "student"]
        canada = {"total": 2, "jobPostings": [
            listing("Stagiaire - Développeur Full Stack", "/job/Montreal-St-Laurent/Stagiaire_123", "Montreal (St. Laurent)",
                    "Posted 3 Days Ago"),
            listing("Software Engineering Intern", "/job/x/SWE-Intern_456", "2 Locations")]}
        us = {"total": 1, "jobPostings": [listing("Software Engineering Intern", "/job/x/SWE-Intern_456", "2 Locations")]}
        detail = {"jobPostingInfo": {"location": "Montreal (St. Laurent)", "additionalLocations": ["Tampa, FL, USA"],
                                     "startDate": "2026-10-01"}}
        request, calls = fake_requests({
            (f"{self.API}/jobs", repr([])): first,
            (f"{self.API}/jobs", self.facets(("Location_Country", ["ca"]), ("workerSubType", intern))): canada,
            (f"{self.API}/jobs", self.facets(("Location_Country", ["us"]), ("workerSubType", intern))): us,
            f"{self.API}/job/x/SWE-Intern_456": detail,
        })
        ats._details.clear()
        with mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, total = ats.fetch_board("workday", "cae.wd3/career")
        self.assertEqual(total, 384)
        by_key = {j["key"]: j for j in jobs}
        self.assertEqual(set(by_key), {"wd:cae:123", "wd:cae:456"})
        both = by_key["wd:cae:456"]
        self.assertEqual(both["regions"], {"CA", "US"})
        self.assertEqual(both["locations"], ["Montreal (St. Laurent)", "Tampa, FL, USA"])
        self.assertEqual(both["url"], "https://cae.wd3.myworkdayjobs.com/career/job/x/SWE-Intern_456")
        self.assertTrue(both["intern_flag"])
        self.assertEqual([j["title"] for j in internships(jobs)],
                         ["Stagiaire - Développeur Full Stack", "Software Engineering Intern"])
        self.assertEqual(sum(1 for url, _ in calls if url.endswith("SWE-Intern_456")), 1)  # one detail fetch

    def test_posted(self):
        now = 1_800_000_000
        today = now // 86400 * 86400
        self.assertEqual(ats.workday_posted("Posted Today", now), today)
        self.assertEqual(ats.workday_posted("Posted Yesterday", now), today - 86400)
        self.assertEqual(ats.workday_posted("Posted 5 Days Ago", now), today - 5 * 86400)
        self.assertEqual(ats.workday_posted("Posted 30+ Days Ago", now), today - 31 * 86400)  # older than shown
        self.assertIsNone(ats.workday_posted(None, now))


class RecruiterboxTest(unittest.TestCase):
    def test_reads_openings(self):
        url = "https://jsapi.recruiterbox.com/v1/openings?client_name=tsimagine&limit=100&offset=0"
        page = {"meta": {"total": 2}, "objects": [
            {"id": "fk0zlh8", "title": "Financial Technology Interns - Spring 2027", "position_type": "full_time",
             "location": {"city": "Montréal", "state": "Québec", "country": "Canada"}, "allows_remote": False,
             "hosted_url": "https://tsimagine.hire.trakstar.com/jobs/fk0zlh8/"},
            {"id": "fk0zlsd", "title": "Sales Executive", "position_type": "full_time",
             "location": {"city": "Greater London", "state": "England", "country": "United Kingdom"},
             "hosted_url": "https://tsimagine.hire.trakstar.com/jobs/fk0zlsd/"}]}
        request, _ = fake_requests({url: page})
        with mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, total = ats.fetch_board("recruiterbox", "tsimagine")
        kept = internships(jobs)
        self.assertEqual(total, 2)
        self.assertEqual([(j["key"], j["regions"], j["category"], j["terms"]) for j in kept],
                         [("rbox:fk0zlh8", {"CA"}, "Software", ["Spring 2027"])])

    def test_unknown_company(self):
        error = urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(b"{}"))
        request, _ = fake_requests({"https://jsapi.recruiterbox.com/v1/openings?client_name=nope&limit=100&offset=0": error})
        with mock.patch.object(ats, "_request", side_effect=request), self.assertRaises(ats.BoardNotFound):
            ats.fetch_board("recruiterbox", "nope")


class OracleTest(unittest.TestCase):
    API = ("https://hdks.fa.ca2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
           "?onlyData=true&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber=CX_1,limit=100,")

    @staticmethod
    def req(id, title, where, country, posted="2026-10-15", more=()):
        return {"Id": id, "Title": title, "PrimaryLocation": where, "PrimaryLocationCountry": country,
                "PostedDate": posted, "WorkplaceType": "", "secondaryLocations": [
                    {"Name": n, "CountryCode": c} for n, c in more]}

    def test_small_board_is_read_whole(self):
        page = {"items": [{"TotalJobsCount": 3, "requisitionList": [
            self.req("9412", "Cloud Engineer - Winter 2027 Co-op/Intern", "Waterloo, ONT, Canada", "CA",
                     more=[("Toronto, ONT, Canada", "CA")]),
            self.req("9329", "Manager, Enterprise Communications", "Waterloo, ONT, Canada", "CA"),
            self.req("9500", "Software Intern", "Rotterdam, NL", "NL")]}]}
        request, calls = fake_requests({f"{self.API}offset=0": page})
        with mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, total = ats.fetch_board("oracle", "hdks.fa.ca2/CX_1")
        self.assertEqual((total, len(jobs), len(calls)), (3, 3, 1))
        kept = internships(jobs)
        self.assertEqual([(j["key"], j["regions"], j["locations"]) for j in kept],
                         [("oracle:hdks:9412", {"CA"}, ["Waterloo, ONT, Canada", "Toronto, ONT, Canada"])])
        self.assertEqual(kept[0]["url"], "https://hdks.fa.ca2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/9412")
        self.assertEqual(kept[0]["terms"], ["Winter 2027"])

    def test_big_board_is_searched(self):
        first = {"items": [{"TotalJobsCount": 4000, "requisitionList": [self.req("1", "Director", "NY", "US")]}]}
        found = {"items": [{"TotalJobsCount": 2, "requisitionList": [
            self.req("26011084", "Software Engineer Intern - Summer 2027", "Sunrise, FL, United States", "US"),
            self.req("26011085", "Internal Audit Manager", "Sunrise, FL, United States", "US")]}]}
        empty = {"items": [{"TotalJobsCount": 0, "requisitionList": []}]}
        request, calls = fake_requests({
            f"{self.API}offset=0": first, f"{self.API}offset=0,keyword=intern": found,
            f"{self.API}offset=0,keyword=co-op": empty, f"{self.API}offset=0,keyword=stagiaire": empty})
        with mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, total = ats.fetch_board("oracle", "hdks.fa.ca2/CX_1")
        self.assertEqual(total, 4000)
        self.assertEqual([j["key"] for j in jobs], ["oracle:hdks:26011084"])  # "Internal" isn't an internship
        self.assertEqual(len(calls), 4)


ICIMS_CARD = """<li class="iCIMS_JobCardItem"><div class="row">
<div class="col-xs-6 header left"><span class="sr-only field-label">Location</span>
<span >
{where}</span></div>
<div class="col-xs-12 title"><a href="https://careers-acme.icims.com/jobs/{id}/slug/job?in_iframe=1" class="iCIMS_Anchor"
title="{id} - {title}"><span class="sr-only field-label">Title</span><h3 >
{title}</h3></a></div>
<dl class="iCIMS_JobHeaderGroup">{posted}
<div class="iCIMS_JobHeaderTag"><dt class="iCIMS_JobHeaderField">Position Type</dt>
<dd class="iCIMS_JobHeaderData"><span >
{kind}</span></dd></div>
<div class="iCIMS_JobHeaderTag"><dt class="iCIMS_JobHeaderField">Remote</dt>
<dd class="iCIMS_JobHeaderData"><span >
{remote}</span></dd></div></dl></div></li>"""
ICIMS_POSTED = """<div class="iCIMS_JobHeaderTag"><dt class="iCIMS_JobHeaderField">Posted Date</dt>
<dd class="iCIMS_JobHeaderData"><span title="10/19/2026 10:47 AM">2 days ago</span></dd></div>"""


def icims_page(*cards, pages=1):
    return (f'<div class="iCIMS_JobsTable"><ul class="container-fluid iCIMS_JobsTable">{"".join(cards)}</ul>'
            f"<p>Page 1 of {pages}</p></div>")


def icims_card(id, title, where, kind="Intern", remote="No", posted=True):
    return ICIMS_CARD.format(id=id, title=title, where=where, kind=kind, remote=remote,
                             posted=ICIMS_POSTED if posted else "")


class IcimsTest(unittest.TestCase):
    SEARCH = "https://careers-acme.icims.com/jobs/search?ss=1&searchKeyword={}&in_iframe=1&pr=0"

    def fetch(self, pages):
        empty = icims_page()
        get = lambda url, timeout=30: (pages.get(url, empty), 100)
        ats._details.clear()
        with mock.patch.object(ats, "_request_page", side_effect=get) as calls:
            jobs = ats.fetch_board("icims", "careers-acme")[0]
        return jobs, [c.args[0] for c in calls.call_args_list]

    def test_reads_cards(self):
        search = icims_page(
            icims_card("35572", "Intern Cloud Developer, Platform Engineering", "CA-ON-Ottawa"),
            icims_card("35465", "Intern AI &amp; ML Researcher", "CA-Remote", remote="Yes", posted=False),
            icims_card("35310", "Intern Software Developer", "NL-Rotterdam"),
            icims_card("35400", "Senior Developer", "US-TX-Dallas", kind="Full-Time"))
        jobs, _ = self.fetch({self.SEARCH.format("intern"): search})
        kept = {j["key"]: j for j in internships(jobs)}
        self.assertEqual(set(kept), {"icims:careers-acme:35572", "icims:careers-acme:35465"})
        ottawa, remote = kept["icims:careers-acme:35572"], kept["icims:careers-acme:35465"]
        self.assertEqual((ottawa["regions"], ottawa["url"]), ({"CA"}, "https://careers-acme.icims.com/jobs/35572/job"))
        self.assertTrue(ottawa["intern_flag"])
        self.assertEqual(time.strftime("%Y-%m-%d", time.localtime(ottawa["posted"])), "2026-10-19")
        self.assertEqual((remote["title"], remote["regions"], remote["posted"]),
                         ("Intern AI & ML Researcher", {"CA", "REMOTE"}, None))

    def test_multiple_locations_come_from_the_posting(self):
        search = icims_page(icims_card("1", "Software Intern", "Multiple Locations"),
                            icims_card("2", "Data Intern", "Multiple Locations"))
        ld = lambda *places: ('<script type="application/ld+json">' + json.dumps({"@type": "JobPosting", "jobLocation": [
            {"address": {"addressLocality": l, "addressRegion": r, "addressCountry": c}} for l, r, c in places]})
            + "</script>")
        jobs, _ = self.fetch({
            self.SEARCH.format("intern"): search,
            "https://careers-acme.icims.com/jobs/1/job?in_iframe=1": ld(("Niles", "IL", "US"), ("Ottawa", "ON", "CA")),
            "https://careers-acme.icims.com/jobs/2/job?in_iframe=1": ld(("Rotterdam", "UNAVAILABLE", "NL"))})
        by_key = {j["key"]: j for j in jobs}
        self.assertEqual(by_key["icims:careers-acme:1"]["regions"], {"US", "CA"})
        self.assertEqual(by_key["icims:careers-acme:1"]["locations"], ["Niles, IL, US", "Ottawa, ON, CA"])
        self.assertEqual(by_key["icims:careers-acme:2"]["regions"], set())  # NL is the Netherlands here

    def test_pages(self):
        full = icims_page(*[icims_card(str(i), f"Intern {i}", "US-NY-New York") for i in range(20)], pages=2)
        last = icims_page(icims_card("99", "Intern 99", "US-NY-New York"), pages=2)
        jobs, urls = self.fetch({self.SEARCH.format("intern"): full,
                                 self.SEARCH.format("intern").replace("pr=0", "pr=1"): last})
        self.assertEqual(len(jobs), 21)
        self.assertEqual(sum("searchKeyword=intern&" in u for u in urls), 2)

    def test_portal_that_sends_visitors_elsewhere(self):
        page = "<script>window.top.location.href = 'https://www.atlassian.com/company/careers/all-jobs';</script>"
        with mock.patch.object(ats, "_request_page", return_value=(page, 100)), self.assertRaises(ats.BoardNotFound):
            ats.fetch_board("icims", "campus-globalcareers-atlassian")


class MoreLinksTest(unittest.TestCase):
    def test_parse(self):
        cases = {
            "https://careers.amd.com/jobs/86868?icims=1": ("jibe", "careers.amd.com"),
            "https://careers.kpmg.ca/students/jobs/34407?lang=en-us&icims=1": ("jibe", "careers.kpmg.ca"),
            "https://jobs.l3harris.com/job/Greenville-Application-Developer-Intern-TX-75402/1425609500/?ats=successfactors":
                ("successfactors", "jobs.l3harris.com"),
            "https://qualcomm.eightfold.ai/careers/job/446716226621": ("eightfold", "qualcomm.eightfold.ai"),
            "https://careers.qualcomm.com/careers?pid=446716226621&domain=qualcomm.com": ("eightfold", "qualcomm.eightfold.ai"),
            "https://explore.jobs.netflix.net/careers/job/790315673635": ("eightfold", "explore.jobs.netflix.net"),
            "https://jobs.ea.com/en_US/careers/JobDetail/Analytics-Intern/216252": ("avature", "jobs.ea.com/en_US/careers"),
            "https://bnc.avature.net/en_CA/careers/JobDetail/35546": ("avature", "emplois.bnc.ca/en_CA/careers"),
            "https://careers.twosigma.com/careers/JobDetail/New-York-Intern/14016": ("avature", "careers.twosigma.com/careers"),
            "https://neboagency.applytojob.com/apply/VhgOaS6Nx3/UX-Designer-Internship": ("jazzhr", "neboagency"),
        }
        for url, want in cases.items():
            self.assertEqual(parse_board_url(url), want, url)
            self.assertEqual(parse_board_url(ats.board_page(*want)), want, want)
        # Without the lists' tag these paths are too common to trust.
        for url in ["https://careers.amd.com/jobs/86868", "https://www.akunacapital.com/careers/job/8018847/?gh_jid=1",
                    "https://example.com/job/Some-Title/1425609500/", "https://example.com/a/b/c/JobDetail/x/1"]:
            self.assertNotIn((parse_board_url(url) or ("",))[0], {"jibe", "successfactors", "eightfold", "avature"}, url)

    def test_posting_keys(self):
        cases = {
            "https://careers.amd.com/jobs/86868?icims=1": "jibe:careers.amd.com:86868",
            "https://jobs.l3harris.com/job/Greenville-Intern-TX-75402/1425609500/?ats=successfactors":
                "sf:jobs.l3harris.com:1425609500",
            "https://careers.qualcomm.com/careers?pid=446716226621&domain=qualcomm.com": "eightfold:446716226621",
            "https://jobs.ea.com/en_US/careers/JobDetail/Analytics-Intern/216252": "avature:jobs.ea.com:216252",
            # The *.avature.net name and the company's domain are one board.
            "https://bnc.avature.net/en_CA/careers/JobDetail/35546": "avature:emplois.bnc.ca:35546",
            "https://emplois.bnc.ca/en_CA/careers/JobDetail/59935-ETUDIANT-STAGIAIRE-CADRE/35546": "avature:emplois.bnc.ca:35546",
            "https://delta.avature.net/en_US/careers/JobDetail?jobId=32774": "avature:delta.avature.net:32774",
            "https://neboagency.applytojob.com/apply/VhgOaS6Nx3/UX-Designer-Internship": "jazz:VhgOaS6Nx3",
        }
        for url, want in cases.items():
            self.assertEqual(posting_key(url), want, url)


class JibeTest(unittest.TestCase):
    def test_reads_search(self):
        job = lambda id, title, where, code, more=(): {"data": {
            "req_id": id, "title": title, "full_location": where, "country_code": code, "posted_date": "2026-10-11T03:36:00+0000",
            "additional_locations": [{"city": c, "state": st, "country_code": cc} for c, st, cc in more],
            "description": "<p>About</p>", "qualifications": "<p>Quals</p>"}}
        search = {"totalCount": 2, "jobs": [
            job("91867", "2027 Masters Compiler Engineering Intern / Co-op", "Austin, Texas; Boxborough, Massachusetts", "US"),
            job("93000", "Software Engineering Co-op", "Markham, Ontario", "CA", more=[("Austin", "Texas", "US")])]}
        empty = {"totalCount": 0, "jobs": []}
        request, _ = fake_requests({
            "https://careers.amd.com/api/jobs?keywords=intern&page=1&limit=50": search,
            "https://careers.amd.com/api/jobs?keywords=co-op&page=1&limit=50": empty})
        with mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, _ = ats.fetch_board("jibe", "careers.amd.com")
        by_key = {j["key"]: j for j in jobs}
        first = by_key["jibe:careers.amd.com:91867"]
        self.assertEqual(first["locations"], ["Austin, Texas, US", "Boxborough, Massachusetts, US"])
        self.assertEqual(first["url"], "https://careers.amd.com/jobs/91867?icims=1")
        self.assertEqual(by_key["jibe:careers.amd.com:93000"]["regions"], {"CA", "US"})
        self.assertEqual(ats.jibe_text("careers.amd.com", "91867"), "<p>About</p>\n\n<p>Quals</p>")


SF_TABLE = """<span class="paginationLabel">Results <b>1 – 2</b> of <b>2</b></span>
<tr class="data-row"><td class="colTitle"><span class="jobTitle hidden-phone">
<a href="/job/Kirkland-Software-Engineer-Intern-WA-98033/1450066233/" class="jobTitle-link">Software Engineer Intern</a></span>
<div class="jobdetail-phone visible-phone"><a class="jobTitle-link" href="/job/Kirkland-Software-Engineer-Intern-WA-98033/1450066233/">Software Engineer Intern</a>
<span class="jobLocation visible-phone"><span class="jobLocation"> Kirkland, WA, US, 98033 </span></span></div></td>
<td class="colDate"><span class="jobDate">Oct 21, 2026 </span></td></tr>
<tr class="data-row"><td class="colTitle"><a href="/job/Ottawa-Firmware-Intern-ON-K2K/1450066299/" class="jobTitle-link">Firmware Intern</a>
<span class="jobLocation"> Ottawa, ON, CA, K2K 2W7 </span></td></tr>"""
SF_TILES = """<span id="tile-search-results-label">Showing 1 to 1 of 1 Jobs</span>
<li class="job-tile job-id-1432659600"><a class="jobTitle-link fontcolor" href="/job/Huntsville-Intern%2C-Software-Engineer-AL-35806/1432659600/">
Intern, Software Engineer </a>
<span id="job-1432659600-desktop-section-location-label" aria-describedby="job-1432659600-desktop-section-location-value"> Location </span>
<div id="job-1432659600-desktop-section-location-value">Huntsville, AL, US, 35806 </div></li>"""


class SuccessFactorsTest(unittest.TestCase):
    def fetch(self, page):
        pages = {"https://x.example/search/?q=&title=intern&startrow=0": page}
        with mock.patch.object(ats, "_request_page", side_effect=lambda url, timeout=30, **o: (pages.get(url, ""), 100)):
            return ats.fetch_board("successfactors", "x.example")[0]

    def test_table_layout(self):
        jobs = {j["key"]: j for j in self.fetch(SF_TABLE)}
        kirkland, ottawa = jobs["sf:x.example:1450066233"], jobs["sf:x.example:1450066299"]
        self.assertEqual((kirkland["title"], kirkland["locations"], kirkland["regions"]),
                         ("Software Engineer Intern", ["Kirkland, WA, US"], {"US"}))
        self.assertEqual(time.strftime("%Y-%m-%d", time.localtime(kirkland["posted"])), "2026-10-21")
        self.assertEqual(kirkland["url"], "https://x.example/job/Kirkland-Software-Engineer-Intern-WA-98033/1450066233/?ats=successfactors")
        self.assertEqual(ottawa["regions"], {"CA"})  # "CA" after a province is Canada

    def test_tile_layout(self):
        [job] = self.fetch(SF_TILES)
        self.assertEqual((job["title"], job["locations"], job["regions"]),
                         ("Intern, Software Engineer", ["Huntsville, AL, US"], {"US"}))

    def test_filled_posting(self):
        with mock.patch.object(ats, "_request_page", return_value=("<p>Sorry, this position has been filled.</p>", 1)):
            self.assertIsNone(ats.successfactors_text("https://x.example/job/a/1/"))
        page = '<h1 itemprop="title">Intern</h1><span class="jobdescription"><p>Build <span>things</span>.</p></span>'
        with mock.patch.object(ats, "_request_page", return_value=(page, 1)):
            self.assertEqual(ats.successfactors_text("https://x.example/job/a/1/"), "<p>Build <span>things</span>.</p>")


class EightfoldTest(unittest.TestCase):
    HOST = "https://qualcomm.eightfold.ai/api/pcsx/search?domain=qualcomm.com"

    def setUp(self):
        ats._eightfold_kind.clear()
        self.addCleanup(ats._eightfold_kind.clear)
        patcher = mock.patch.object(ats.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_finds_the_internship_filter(self):
        first = {"data": {"count": 900, "positions": [], "filterDef": {"allFilters": [
            {"filterName": "seniority", "options": [{"label": "Intern", "value": "Intern"}, {"label": "Senior", "value": "S"}]}]}}}
        position = lambda id, where: {"id": id, "name": "Software Engineering Internship - Summer 2027",
                                      "standardizedLocations": [where], "postedTs": 1790121600}
        us = {"data": {"count": 1, "positions": [position(446720740529, "San Diego, CA, US")]}}
        ca = {"data": {"count": 1, "positions": [position(446720740600, "Markham, ON, CA")]}}
        answers = {f"{self.HOST}&start=0": first,
                   f"{self.HOST}&filter_seniority=Intern&location=United%20States&start=0": us,
                   f"{self.HOST}&filter_seniority=Intern&location=United%20States&start=1": {"data": {"count": 1, "positions": []}},
                   f"{self.HOST}&filter_seniority=Intern&location=Canada&start=0": ca,
                   f"{self.HOST}&filter_seniority=Intern&location=Canada&start=1": {"data": {"count": 1, "positions": []}}}
        attempts = []

        def request(url, body=None, timeout=30, opener=None):
            attempts.append(url)
            if len(attempts) == 1:
                raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
            return answers[url], 100

        with mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, _ = ats.fetch_board("eightfold", "qualcomm.eightfold.ai")
        by_key = {j["key"]: j for j in jobs}
        self.assertEqual(by_key["eightfold:446720740600"]["regions"], {"CA"})
        self.assertEqual(by_key["eightfold:446720740529"]["url"], "https://qualcomm.eightfold.ai/careers/job/446720740529")
        self.assertTrue(all(j["intern_flag"] for j in jobs))

    def test_older_api(self):
        netflix = "https://explore.jobs.netflix.net"
        position = lambda id, name: {"id": id, "name": name, "locations": ["Los Gatos,California,United States of America"],
                                     "t_create": 1790121600}
        us = {"count": 2, "positions": [position(790318904468, "Software Engineer Intern - Summer 2027"),
                                        position(790318904469, "CG Experimental Artist- Ink")]}
        empty = {"count": 0, "positions": []}

        def request(url, body=None, timeout=30, opener=None):
            if "/api/pcsx/" in url:
                raise urllib.error.HTTPError(url, 403, "Not authorized for PCSX", {}, None)
            if url.endswith("num=1"):  # finding which API the board answers
                return empty, 10
            if "United%20States&start=0" in url:
                return us, 100
            return empty, 10

        with mock.patch.object(ats, "_request", side_effect=request):
            jobs, _, _ = ats.fetch_board("eightfold", "explore.jobs.netflix.net")
        self.assertEqual([j["key"] for j in jobs], ["eightfold:790318904468"])  # the keyword search is fuzzy


EA_CARD = """<article class="article article--result"><h3><a class="link link_result"
href="https://jobs.ea.com/en_US/careers/JobDetail/Software-Engineer-Intern/{id}"> {title} </a></h3>
<span class="list-item-location">{where}</span><span class="list-item-workerType">Intern - Temporary Employee</span>
<a class="button button--primary" href="https://jobs.ea.com/en_US/careers/JobDetail/Software-Engineer-Intern/{id}"> More Information </a>
<a href="https://jobs.ea.com/_linkedinApiv2?shareUrl=https%3A%2F%2Fjobs.ea.com%2Fen_US%2Fcareers%2FJobDetail%2Fx%2F{id}">LinkedIn</a>
</article>"""


class AvatureTest(unittest.TestCase):
    def setUp(self):
        ats._avature_search.clear()
        self.addCleanup(ats._avature_search.clear)

    def fetch(self, token, pages):
        with mock.patch.object(ats, "_request_page",
                               side_effect=lambda url, timeout=30, **o: (pages.get(url, "<html></html>"), 100)):
            return ats.fetch_board("avature", token)[0]

    def test_cards(self):
        page = EA_CARD.format(id="216190", title="Software Engineer Intern - Gameplay/UI", where="Montreal, Canada") \
            + EA_CARD.format(id="216191", title="Software Engineer Intern - Tools", where="Birmingham, United Kingdom")
        jobs = self.fetch("jobs.ea.com/en_US/careers",
                          {"https://jobs.ea.com/en_US/careers/SearchJobs/?search=internship&jobOffset=0": page})
        by_key = {j["key"]: j for j in jobs}
        self.assertEqual(set(by_key), {"avature:jobs.ea.com:216190", "avature:jobs.ea.com:216191"})
        montreal = by_key["avature:jobs.ea.com:216190"]
        self.assertEqual((montreal["title"], montreal["locations"], montreal["regions"], montreal["intern_flag"]),
                         ("Software Engineer Intern - Gameplay/UI", ["Montreal, Canada"], {"CA"}, True))

    def test_table_and_places_in_links(self):
        bnc = """<tr><th scope="row"><a class="link" href="https://emplois.bnc.ca/en_CA/careers/JobDetail/59935-ETUDIANT/35546"
            title="Student Intern"> Student Intern </a><a class="toggle"></a></th><td> Montreal, Quebec </td><td> Hybrid </td></tr>"""
        jobs = self.fetch("emplois.bnc.ca/en_CA/careers",
                          {"https://emplois.bnc.ca/en_CA/careers/SearchJobs/?search=internship&jobOffset=0": bnc})
        self.assertEqual([(j["title"], j["locations"], j["regions"]) for j in jobs],
                         [("Student Intern", ["Montreal, Quebec"], {"CA"})])
        two_sigma = """<a href="https://careers.twosigma.com/careers/JobDetail/New-York-New-York-United-States-Software-Engineering-Internship/14016">
            Software Engineering Internship</a>"""
        ats._avature_search["careers.twosigma.com/careers"] = "https://careers.twosigma.com/careers/OpenRoles/"
        jobs = self.fetch("careers.twosigma.com/careers",
                          {"https://careers.twosigma.com/careers/OpenRoles/?search=internship&jobOffset=0": two_sigma})
        self.assertEqual([(j["locations"], j["regions"]) for j in jobs], [(["New York, United States"], {"US"})])

    def test_search_page_from_the_form(self):
        home = '<form id="tpt_jobSortableForm" action="https://careers.twosigma.com/careers/OpenRoles" method="get">'

        def page(url, timeout=30, **options):
            if url.endswith("/SearchJobs/"):
                raise ats.BoardNotFound(url)
            return (home if url == "https://careers.twosigma.com/careers" else ""), 100

        with mock.patch.object(ats, "_request_page", side_effect=page):
            self.assertEqual(ats._avature_search_page("careers.twosigma.com/careers", 30),
                             "https://careers.twosigma.com/careers/OpenRoles/")


class JazzHrTest(unittest.TestCase):
    FEED = """<?xml version="1.0" encoding="utf-8"?><jobs><company>Nebo</company>
      <job><id>job_20250904133323_OGKCMOGIVTQGWUSZ</id><title>Back-End Engineering Intern</title>
        <url>https://neboagency.applytojob.com/apply/VhgOaS6Nx3/BackEnd-Engineering-Intern</url><city>Atlanta</city>
        <state>GA</state><country>United States</country><type>Internship</type><description>&lt;p&gt;Build&lt;/p&gt;</description></job>
      <job><id>job_2</id><title>Account Director</title><url>https://neboagency.applytojob.com/apply/AAAAAAAAAA/Account</url>
        <city>Atlanta</city><state>GA</state><country>United States</country><type>Full Time</type></job></jobs>"""

    def test_feed(self):
        with mock.patch.object(ats, "_request_page", return_value=(self.FEED, 100)) as get:
            jobs, _, total = ats.fetch_board("jazzhr", "neboagency")
        get.assert_called_once_with("https://app.jazz.co/feeds/export/jobs/neboagency", 30)
        self.assertEqual(total, 2)
        self.assertEqual([(j["key"], j["locations"], j["regions"], j["intern_flag"]) for j in internships(jobs)],
                         [("jazz:VhgOaS6Nx3", ["Atlanta, GA, United States"], {"US"}, True)])


class FindBoardTest(unittest.TestCase):
    def test_link_on_the_page(self):
        page = """<meta property="og:site_name" content="Acme | Careers"><script
            src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>"""
        with mock.patch.object(ats, "_get_text", return_value=(page, "https://acme.com/careers")):
            self.assertEqual(ats.find_board("acme.com/careers"), {"platform": "greenhouse", "token": "acme", "name": "Acme"})

    def test_recruiterbox_widget(self):
        # TS Imagine's page builds the widget address in pieces; the name is inside the widget's script.
        page = """<script>var s, src=['/static/client-src-served/widget/84735/rbox_api.js'];
            s.src = _rbox.host_protocol + '//w.recruiterbox.com' + src[i];</script>"""
        script = "var u = 'https://tsimagine.recruiterbox.com/integrations/v1/indeed_questions/';"
        pages = {"https://tsimagine.com/careers/": (page, "https://tsimagine.com/careers/"),
                 "https://w.recruiterbox.com/static/client-src-served/widget/84735/rbox_api.js": (script, "")}
        with mock.patch.object(ats, "_get_text", side_effect=lambda url, timeout=20: pages[url]):
            found = ats.find_board("https://tsimagine.com/careers/")
        self.assertEqual((found["platform"], found["token"]), ("recruiterbox", "tsimagine"))

    def test_nothing_found(self):
        with mock.patch.object(ats, "_get_text", return_value=("<html>Jobs coming soon</html>", "https://x.com/jobs")):
            self.assertIsNone(ats.find_board("https://x.com/jobs"))


if __name__ == "__main__":
    unittest.main()
