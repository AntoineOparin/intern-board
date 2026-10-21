import io
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
        }
        for url, want in cases.items():
            self.assertEqual(parse_board_url(url), want, url)
        for url in ["https://boards.greenhouse.io/embed/job_app?token=7625508",
                    "https://amazon.jobs/en/jobs/123", "https://boards.eu.greenhouse.io/nice/jobs/1"]:
            self.assertIsNone(parse_board_url(url), url)

    def test_posting_key_matches_across_url_styles(self):
        self.assertEqual(posting_key("https://job-boards.greenhouse.io/x/jobs/5309667008"), "gh:5309667008")
        self.assertEqual(posting_key("https://boards.greenhouse.io/embed/job_app?for=x&token=5309667008"),
                         "gh:5309667008")
        self.assertEqual(posting_key("http://jobs.ashbyhq.com/bree/5e79b2fd-164c-4e72-91ef-1b8fd1c5518a/application"),
                         "ashby:5e79b2fd-164c-4e72-91ef-1b8fd1c5518a")
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
        }
        for url, want in cases.items():
            self.assertEqual(parse_board_url(url), want, url)
        for url in ["https://cae.wd3.myworkdayjobs.com/", "https://apply.workable.com/j/7DE79BE9A8",
                    "https://www.bamboohr.com/careers", "https://w.recruiterbox.com/static/x.js"]:
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
        }
        for url, want in cases.items():
            self.assertEqual(posting_key(url), want, url)

    def test_board_page(self):
        self.assertEqual(ats.board_page("workday", "cae.wd3/career"), "https://cae.wd3.myworkdayjobs.com/career")
        self.assertEqual(ats.board_page("recruiterbox", "tsimagine"), "https://tsimagine.hire.trakstar.com/")


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
