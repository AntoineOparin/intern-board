import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from board import contacts, db, prospeo, settings


def person(pid, title, city=None, state=None, country="Canada", email="VERIFIED"):
    return {"person": {"person_id": pid, "full_name": f"Person {pid}", "current_job_title": title,
                       "linkedin_url": f"https://www.linkedin.com/in/{pid}",
                       "location": {"city": city, "state": state, "country": country},
                       "email": {"status": email, "revealed": False}},
            "company": {"name": "Lyft", "logo_url": "https://logo.example/lyft.png"}}


class DomainTest(unittest.TestCase):
    def test_matches_company(self):
        self.assertTrue(contacts.domain_matches_company("lyft.com", "Lyft"))
        self.assertTrue(contacts.domain_matches_company("ea.com", "Electronic Arts"))  # initials
        self.assertTrue(contacts.domain_matches_company("pspinvestments.com", "PSP Investments"))
        self.assertFalse(contacts.domain_matches_company("careerpuck.com", "Lyft"))

    def test_from_listing_url(self):
        self.assertEqual(contacts.domain_from_listing_url("https://jobs.ea.com/x", "Electronic Arts"), "ea.com")
        self.assertIsNone(contacts.domain_from_listing_url("https://app.careerpuck.com/job-board/lyft/job/1", "Lyft"))
        self.assertIsNone(contacts.domain_from_listing_url("https://job-boards.greenhouse.io/lyft/jobs/1", "Lyft"))
        self.assertEqual(contacts.root_domain("www.bbc.co.uk"), "bbc.co.uk")

    def test_team_label(self):
        self.assertEqual(contacts.team_label({"title": "Software Engineer Intern - Ads", "category": "Software"}),
                         "Software engineers")
        self.assertEqual(contacts.team_label({"title": "Research Intern - Machine Learning", "category": "AI/ML/Data"}),
                         "People in research")


class RankTest(unittest.TestCase):
    def test_student_recruiters_near_the_job_first(self):
        listing = {"locations": "Montreal, QC, Canada", "regions": ",CA,"}
        ranked = contacts.rank("recruiters", listing, [
            person("far", "Senior Recruiter", "London", None, "United Kingdom"),
            person("local", "Technical Recruiter", "Montreal", "Quebec"),
            person("campus", "University Recruiter", "Toronto", "Ontario"),
        ])
        self.assertEqual([r["person"]["person_id"] for r in ranked], ["local", "campus", "far"])


class SearchJobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(db, "DB_PATH", Path(self.tmp.name) / "t.db"),
                        mock.patch.object(prospeo, "key", lambda: "pk_test")]
        for p in self.patches:
            p.start()
        db.init()
        with db.connect() as conn:
            conn.execute("INSERT INTO listings (id, source, company, title, url, locations, regions, terms, degrees, "
                         "first_seen) VALUES ('L1', 'simplify', 'Lyft', 'Software Engineer Intern', "
                         "'https://app.careerpuck.com/job-board/lyft/job/1', 'Montreal, QC, Canada', ',CA,', ',', ',', 1)")
            contacts.save_site(conn, "Lyft", "lyft.com", "user")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_country_first_then_fallback(self):
        calls = []

        def fake_search(**kw):
            calls.append(kw.get("countries"))
            if kw.get("countries"):
                return None  # nobody in Canada: free, so the app retries without the country
            return {"results": [person("p1", "University Recruiter", "Seattle", "Washington", "United States")],
                    "pagination": {"total_count": 1}, "free": False}

        with mock.patch.object(prospeo, "search_people", side_effect=fake_search):
            result = contacts.people_search({"listing_id": "L1", "kind": "recruiters"})
        self.assertEqual(calls, [["Canada"], None])
        self.assertEqual(result["count"], 1)
        with db.connect() as conn:
            search = conn.execute("SELECT * FROM people_searches").fetchone()
            site = conn.execute("SELECT * FROM company_sites").fetchone()
        self.assertEqual(search["country_filtered"], 0)
        self.assertEqual(site["logo_url"], "https://logo.example/lyft.png")

    def test_email_reveal_updates_contact(self):
        with mock.patch.object(prospeo, "search_people", return_value={
                "results": [person("p1", "Recruiter", "Montreal", "Quebec")], "pagination": {"total_count": 1}}):
            contacts.people_search({"listing_id": "L1", "kind": "recruiters"})
        with mock.patch.object(prospeo, "reveal_email", return_value={"email": "p1@lyft.com", "status": "VERIFIED",
                                                                       "revealed": True}):
            c = contacts.reveal(contacts.EmailRequest(listing_id="L1", kind="recruiters", person_id="p1"))
        self.assertEqual((c["email"], c["email_status"]), ("p1@lyft.com", "VERIFIED"))
        # No verified email: Prospeo doesn't charge, and the contact is marked so it isn't retried.
        with mock.patch.object(prospeo, "search_people", return_value={
                "results": [person("p2", "Recruiter")], "pagination": {"total_count": 1}}):
            contacts.people_search({"listing_id": "L1", "kind": "recruiters"})
        with mock.patch.object(prospeo, "reveal_email", return_value=None):
            c = contacts.reveal(contacts.EmailRequest(listing_id="L1", kind="recruiters", person_id="p2"))
        self.assertEqual((c["email"], c["email_status"]), (None, "NOT_FOUND"))


class FreshnessAndCreditsTest(SearchJobTest):
    def search(self, people):
        with mock.patch.object(prospeo, "search_people", return_value={"results": people, "pagination": {"total_count": len(people)}}):
            contacts.people_search({"listing_id": "L1", "kind": "recruiters"})

    def rows(self):
        with db.connect() as conn:
            return {r["person_id"]: dict(r) for r in conn.execute("SELECT * FROM contacts ORDER BY rank")}

    def test_search_again_keeps_paid_emails_and_added_people(self):
        self.search([person("p1", "Recruiter", "Montreal"), person("p2", "Recruiter", "Montreal")])
        with mock.patch.object(prospeo, "reveal_email", return_value={"email": "p1@lyft.com", "status": "VERIFIED"}):
            contacts.reveal(contacts.EmailRequest(listing_id="L1", kind="recruiters", person_id="p1"))
        added = contacts.add_contact(contacts.NewContact(listing_id="L1", kind="recruiters", full_name="Sam Lee",
                                                         linkedin_url="linkedin.com/in/samlee"))
        # A new search returns p2 and p3; p1 (whose email you paid for) dropped out of the results.
        self.search([person("p2", "Recruiter", "Montreal"), person("p3", "University Recruiter", "Montreal")])
        rows = self.rows()
        self.assertEqual(set(rows), {"p1", "p2", "p3", added["person_id"]})
        self.assertEqual(rows["p1"]["email"], "p1@lyft.com")
        self.assertEqual(rows[added["person_id"]]["linkedin_url"], "https://linkedin.com/in/samlee")

    def test_out_of_credits_message_names_renewal(self):
        with mock.patch.object(prospeo, "search_people", side_effect=prospeo.ProspeoError("INSUFFICIENT_CREDITS")), \
             mock.patch.object(prospeo, "account", return_value={"next_quota_renewal_date": "2026-11-15 18:37:57+00:00"}):
            with self.assertRaises(ValueError) as ctx:
                contacts.people_search({"listing_id": "L1", "kind": "recruiters"})
        self.assertIn("out of Prospeo credits until November 15", str(ctx.exception))
        self.assertIn("add someone yourself", str(ctx.exception))

    def test_recheck_spots_a_move_and_a_dead_email(self):
        self.search([person("p1", "Recruiter", "Montreal")])
        with mock.patch.object(prospeo, "reveal_email", return_value={"email": "p1@lyft.com", "status": "VERIFIED"}):
            contacts.reveal(contacts.EmailRequest(listing_id="L1", kind="recruiters", person_id="p1"))
        moved = {"person": {"current_job_title": "Recruiter", "email": {"email": "p1@uber.com", "status": "VERIFIED"}},
                 "company": {"name": "Uber", "website": "https://www.uber.com"}, "free_enrichment": True}
        with mock.patch.object(prospeo, "enrich_person", return_value=moved):
            c = contacts.recheck(contacts.EmailRequest(listing_id="L1", kind="recruiters", person_id="p1"))
        self.assertEqual((c["moved_to"], c["email"], c["charged"]), ("Uber", "p1@uber.com", False))
        with mock.patch.object(prospeo, "enrich_person", return_value=None):
            c = contacts.recheck(contacts.EmailRequest(listing_id="L1", kind="recruiters", person_id="p1"))
        self.assertEqual(c["email_status"], "NO_LONGER_VERIFIED")

    def test_add_contact_validation(self):
        from fastapi import HTTPException
        for bad in [{"linkedin_url": "example.com/sam"}, {"email": "not-an-email"}]:
            with self.assertRaises(HTTPException):
                contacts.add_contact(contacts.NewContact(listing_id="L1", kind="recruiters", full_name="Sam", **bad))


class EnvTest(unittest.TestCase):
    def test_set_and_remove_keep_other_lines(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(settings, "ENV_PATH", Path(d) / ".env"):
            settings.ENV_PATH.write_text("# comment\nOTHER=1\n")
            settings.set("PROSPEO_API_KEY", "pk_abc")
            self.assertEqual(settings.get("PROSPEO_API_KEY"), "pk_abc")
            self.assertEqual(oct(settings.ENV_PATH.stat().st_mode & 0o777), "0o600")
            settings.set("PROSPEO_API_KEY", None)
            self.assertEqual(settings.ENV_PATH.read_text(), "# comment\nOTHER=1\n")
            with mock.patch.dict(os.environ, {"OTHER": "env"}):
                self.assertEqual(settings.get("OTHER"), "env")  # real environment wins


if __name__ == "__main__":
    unittest.main()
