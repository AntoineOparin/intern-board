import unittest

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


if __name__ == "__main__":
    unittest.main()
