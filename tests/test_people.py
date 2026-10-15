import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException

from board import ai, db, people
from board.people import clean_company, role_keywords, search_links

PROFILE = {
    "name": "Test Student", "email": "test@example.com", "phone": "", "location": "Waterloo, ON", "links": [],
    "education": [{"school": "University of Waterloo", "degree": "BASc", "field": "Computer Engineering",
                   "location": "", "start": "2024", "end": "2029", "gpa": "", "details": []}],
    "experience": [], "projects": [],
    "skills": {"languages": ["Python"], "frameworks": [], "tools": [], "other": []},
    "awards": [], "summary": "A student.",
}


def keywords_of(url: str) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return (qs.get("keywords") or qs.get("q"))[0]


class CompanyNameTest(unittest.TestCase):
    def test_clean_company(self):
        cases = {
            "Stripe": "Stripe",
            "Acme Holdings, Inc.": "Acme Holdings",
            "Foo LLC": "Foo",
            "Foo, L.L.C.": "Foo",
            "Bar Corp.": "Bar",
            "Baz Corporation": "Baz",
            "Qux Ltd": "Qux",
            "Zeta, Inc": "Zeta",
            "Widgets Inc. LLC": "Widgets",
            "Meta (Facebook)": "Meta",
            "Stripe, Inc. (Canada)": "Stripe",
            "Rivian and Volkswagen Group Technologies": "Rivian and Volkswagen Group Technologies",
            "Johnson & Johnson": "Johnson & Johnson",
            "J.M. Smucker": "J.M. Smucker",
            "Brain Co.": "Brain Co.",           # "Co." is part of the brand
            "S&C Electric Company": "S&C Electric Company",
            "  Spaced   Out  ": "Spaced Out",
            "Ann & Robert H. Lurie Children’s Hospital": "Ann & Robert H. Lurie Children's Hospital",
            "C3.ai": "C3.ai",
            "Inc.": "Inc.",                     # never reduce a name to nothing
            "": "",
        }
        for raw, want in cases.items():
            self.assertEqual(clean_company(raw), want, raw)


class RoleKeywordsTest(unittest.TestCase):
    def test_examples(self):
        cases = {
            "Machine Learning Engineer Intern - Ads": ["machine learning engineer", "ads"],
            "Software Engineer Intern": ["software engineer"],
            "Software Engineer Co-op - Observability": ["software engineer", "observability"],
            "Software Engineer, Internship - Production Infrastructure":
                ["software engineer", "production infrastructure"],
            "Summer 2027 Internship - Controls Systems Engineering": ["controls systems engineering"],
            "Embedded Systems Software Engineering Intern - January - August 2027":
                ["embedded systems software engineering"],
            "Compiler Engineer Intern/Co-op": ["compiler engineer"],
            "Platform Applications Engineer Intern/Co-op (Tools & Validation Infrastructure)":
                ["platform applications engineer", "tools & validation infrastructure"],
            "Software Engineer Intern - Software Engineer - AI Infrastructure":
                ["software engineer", "ai infrastructure"],
            "PhD Intern - Software Engineer - Graphics": ["software engineer", "graphics"],
            "Data Scientist Intern - PhD": ["data scientist"],
            "Product Management Intern - S": ["product management"],
            "GNC Hardware Engineering Intern (Summer 2027)": ["gnc hardware engineering"],
            "Machine Learning Engineer – Applied AI Co-op Intern": ["machine learning engineer", "applied ai"],
            "Execution Research Intern - Systematic Execution Research": ["execution research"],
            "Software Engineer Intern - Remote": ["software engineer"],
            "Electrical I&C Engineering Intern": ["electrical i&c engineering"],
        }
        for title, want in cases.items():
            self.assertEqual(role_keywords(title), want, title)

    def test_locations_are_not_teams(self):
        self.assertEqual(role_keywords("Firmware Engineer Intern (Ottawa)", locations="Ottawa, ON"),
                         ["firmware engineer"])
        self.assertEqual(role_keywords("Software Engineer Intern - Toronto, ON", locations="Toronto, ON"),
                         ["software engineer"])
        self.assertEqual(role_keywords("Software Engineer Intern - California"), ["software engineer"])

    def test_fallback_when_title_has_no_role(self):
        self.assertEqual(role_keywords("Co-op", "Software"), ["software engineer"])
        self.assertEqual(role_keywords("Summer 2027 Intern"), ["engineering"])
        self.assertEqual(role_keywords(""), ["engineering"])

    def test_at_most_two(self):
        self.assertLessEqual(len(role_keywords("Mobile App Intern - Mobile Platform - Diagnostics - Tools")), 2)


class SearchLinksTest(unittest.TestCase):
    def setUp(self):
        self.result = search_links("Acme, Inc.", "Machine Learning Engineer Intern - Ads", "University of Waterloo")
        self.groups = {g["id"]: g for g in self.result["groups"]}

    def test_groups(self):
        self.assertEqual(list(self.groups), ["recruiters", "team", "alumni", "google"])
        for g in self.result["groups"]:
            self.assertTrue(g["title"] and g["hint"])
            for item in g["items"]:
                self.assertTrue(item["label"] and item["hint"] and item["url"])

    def test_url_formats(self):
        for g in self.result["groups"]:
            for item in g["items"]:
                url = urlparse(item["url"])
                self.assertEqual(url.scheme, "https")
                self.assertNotIn(" ", item["url"])
                if g["id"] == "google":
                    self.assertEqual((url.netloc, url.path), ("www.google.com", "/search"))
                    self.assertIn("q", parse_qs(url.query))
                else:
                    self.assertEqual((url.netloc, url.path), ("www.linkedin.com", "/search/results/people/"))
                    self.assertEqual(list(parse_qs(url.query)), ["keywords"])

    def test_queries(self):
        kw = lambda gid: [keywords_of(i["url"]) for i in self.groups[gid]["items"]]
        self.assertEqual(kw("recruiters"), ["Acme university recruiter", "Acme technical recruiter",
                                            "Acme campus recruiting"])
        self.assertEqual(kw("team"), ["Acme machine learning engineer", "Acme ads"])
        self.assertEqual(kw("alumni"), ["Acme University of Waterloo"])
        google = kw("google")
        self.assertIn('site:linkedin.com/in "Acme" "university recruiter"', google)
        self.assertIn('site:linkedin.com/in "Acme" "machine learning engineer"', google)
        self.assertTrue(any("engineering blog" in q for q in google))
        self.assertTrue(any("careers" in q for q in google))

    def test_alumni_without_school(self):
        alumni = next(g for g in search_links("Acme", "Software Engineer Intern", "")["groups"] if g["id"] == "alumni")
        self.assertEqual(alumni["items"], [])
        self.assertIn("Profile", alumni["note"])

    def test_odd_company_names_encode(self):
        r = search_links("AT&T (Mobility) LLC", "Software Engineer Intern", "")
        url = r["groups"][0]["items"][0]["url"]
        self.assertIn("AT%26T", url)            # & must not split the query string
        self.assertEqual(keywords_of(url), "AT&T university recruiter")
        r = search_links("Rivian and Volkswagen Group Technologies", "Embedded Systems Software Engineering Intern", "")
        self.assertEqual(keywords_of(r["groups"][0]["items"][0]["url"]),
                         "Rivian and Volkswagen Group Technologies university recruiter")
        r = search_links('Quote "Co" OR NOT', "Software Engineer Intern", "")
        self.assertEqual(keywords_of(r["groups"][0]["items"][0]["url"]), "Quote Co or not university recruiter")


class OutreachTest(unittest.TestCase):
    """The outreach job with ai.ask mocked, against a throwaway database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = mock.patch.object(db, "DB_PATH", Path(self.tmp.name) / "board.db")
        self.db_patch.start()
        db.init()
        now = int(time.time())
        with db.connect() as conn:
            conn.execute("INSERT INTO profile (id, data, preferences, version, updated_at) VALUES (1, ?, ?, 3, ?)",
                         (json.dumps(PROFILE), json.dumps({"school": "University of Waterloo"}), now))
            conn.execute("INSERT INTO listings (id, source, company, title, url, locations, regions, terms, degrees, "
                         "first_seen) VALUES ('t:1', 'test', 'Acme Inc.', 'Software Engineer Intern - Ads', "
                         "'https://example.com/1', 'Toronto, ON', ',CA,', ',Summer 2027,', ',,', ?)", (now,))
            conn.execute("INSERT INTO documents (id, listing_id, kind, title, content, created_at, updated_at) "
                         "VALUES ('cover1', 't:1', 'cover_letter', 'CL', '{}', ?, ?)", (now, now))

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def run_job(self, answers, **payload):
        payload = {"listing_id": "t:1", "recipient_type": "recruiter", "channel": "linkedin_note", **payload}
        with mock.patch.object(people.ai, "ask", side_effect=answers) as ask:
            return people.outreach(payload), ask

    BRIEF = {"recipient_cares_about": "Filling intern roles with eligible students.",
             "hook": {"text": "You recruit for the Ads team", "basis": "their_title"},
             "proof": {"fact": "Built a Python service", "label": "Python service", "requirement": "Python experience"},
             "ask": "Is Summer 2027 open to 2029 grads?", "avoid": ["Saying they applied"]}

    def test_linkedin_note_saved(self):
        note = "Hi there, I'm a Waterloo student applying to Acme's Ads internship. Could I ask one question?"
        result, ask = self.run_job([self.BRIEF, {"subject": "ignored", "body": note + "\n\n\n"}])
        self.assertEqual(ask.call_count, 2)  # brief, then write; the checks passed so no repair
        brief_call, write_call = ask.call_args_list
        self.assertEqual(brief_call.kwargs["model"], "sonnet")
        self.assertIn("has NOT applied", brief_call.args[0])
        prompt, kwargs = write_call.args[0], write_call.kwargs
        self.assertIn(ai.HONESTY_RULES, prompt)
        self.assertIn("You recruit for the Ads team", prompt)
        self.assertIn("HARD LIMIT: 200 characters", prompt)  # free LinkedIn accounts
        self.assertIn("Today is " + time.strftime("%B"), prompt)
        self.assertEqual(kwargs["schema"]["properties"]["body"]["maxLength"], 200)
        self.assertFalse(kwargs["schema"]["additionalProperties"])
        self.assertEqual((result["subject"], result["body"], result["checks"], result["limit"]), ("", note, [], 200))
        self.assertIn("You recruit for the Ads team", result["angle"])
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (result["document_id"],)).fetchone()
        self.assertEqual((row["kind"], row["listing_id"], row["profile_version"]), ("outreach", "t:1", 3))
        self.assertEqual(row["title"], "LinkedIn note · recruiter")
        content = json.loads(row["content"])
        self.assertEqual((content["body"], content["person_id"], content["checks"]), (note, None, []))

    def test_premium_allows_300(self):
        with db.connect() as conn:
            conn.execute("UPDATE profile SET preferences = ?", (json.dumps({"school": "x", "linkedin_premium": True}),))
        result, ask = self.run_job([self.BRIEF, {"subject": "", "body": "Hi there, " + "a" * 270}])
        self.assertEqual(ask.call_args_list[1].kwargs["schema"]["properties"]["body"]["maxLength"], 300)
        self.assertEqual(result["limit"], 300)

    def test_failed_checks_trigger_one_repair(self):
        bad = "Hi there! I hope this finds you well. I applied and cut costs by 87%."
        good = "Hi there, I'm a Waterloo student applying to Acme's Ads internship. Could I ask one question?"
        result, ask = self.run_job([self.BRIEF, {"subject": "", "body": bad}, {"subject": "", "body": good}])
        self.assertEqual(ask.call_count, 3)
        repair_prompt = ask.call_args_list[2].args[0]
        for issue in ["exclamation", "hope this", "haven't applied", "87"]:
            self.assertIn(issue, repair_prompt)
        self.assertEqual((result["body"], result["checks"]), (good, []))

    def test_unfixable_long_note_fails(self):
        with self.assertRaisesRegex(ValueError, "over LinkedIn's 200"):
            self.run_job([self.BRIEF, {"subject": "", "body": "x" * 260}, {"subject": "", "body": "y" * 230}])
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM documents WHERE kind = 'outreach'").fetchone()[0], 0)

    def test_remaining_soft_issues_are_reported_not_fatal(self):
        long_email = "Hi Sam,\n\n" + "word " * 140
        result, _ = self.run_job([self.BRIEF, {"subject": "Ads intern", "body": long_email},
                                  {"subject": "Ads intern", "body": long_email}], channel="email")
        self.assertTrue(any("words" in c for c in result["checks"]))

    def test_email_with_name_and_context(self):
        body = "Hi Sam,\n\nI'm applying to the Ads internship. Could we talk for 15 minutes?\n\nThanks,\nTest Student"
        result, ask = self.run_job([self.BRIEF, {"subject": "Ads intern, Summer 2027", "body": body}],
                                   channel="email", recipient_type="engineer", recipient_name="  Sam   Lee ",
                                   context="met at the Waterloo career fair")
        brief_prompt, write_prompt = ask.call_args_list[0].args[0], ask.call_args_list[1].args[0]
        self.assertIn("Name: Sam Lee", brief_prompt)
        self.assertIn("met at the Waterloo career fair", write_prompt)
        self.assertIn("60-110 words", write_prompt)
        self.assertEqual(result["checks"], [])  # "15 minutes" and "2027" aren't invented facts
        self.assertEqual(result["subject"], "Ads intern, Summer 2027")
        with db.connect() as conn:
            title = conn.execute("SELECT title FROM documents WHERE id = ?", (result["document_id"],)).fetchone()[0]
        self.assertEqual(title, "Email · engineer · Sam Lee")

    def test_rewrite_avoids_previous_angle(self):
        first, _ = self.run_job([self.BRIEF, {"subject": "", "body": "Hi there, one question about Ads?"}])
        _, ask = self.run_job([self.BRIEF, {"subject": "", "body": "Hi there, a different note?"}],
                              previous_id=first["document_id"])
        self.assertIn("choose a clearly different hook or proof", ask.call_args_list[0].args[0])
        self.assertIn("You recruit for the Ads team", ask.call_args_list[0].args[0])

    def test_applied_status_reaches_prompt(self):
        with db.connect() as conn:
            conn.execute("INSERT INTO tracker (listing_id, status, updated_at) VALUES ('t:1', 'interviewing', 0)")
        body = "Hi there,\n\nI applied to the Ads internship. Is there anything else you need?\n\nThanks,\nTest Student"
        result, ask = self.run_job([self.BRIEF, {"subject": "Ads internship application", "body": body}],
                                   channel="follow_up")
        self.assertIn("has applied", ask.call_args_list[0].args[0])
        self.assertIn("Never write \"just following up\"", ask.call_args_list[1].args[0])
        self.assertEqual(result["checks"], [])  # saying "I applied" is fine once they have

    def test_follow_up_requires_applied(self):
        with db.connect() as conn:
            conn.execute("INSERT INTO tracker (listing_id, status, updated_at) VALUES ('t:1', 'saved', 0)")
        with self.assertRaisesRegex(ValueError, "after you apply"):
            self.run_job([], channel="follow_up")

    def test_validation(self):
        for bad, msg in [({"recipient_type": "ceo"}, "who"), ({"channel": "sms"}, "message type"),
                         ({"listing_id": "nope"}, "no longer exists"), ({"recipient_name": "x" * 81}, "under 80"),
                         ({"context": 5}, "text")]:
            with self.assertRaisesRegex(ValueError, msg):
                self.run_job([], **bad)

    def test_requires_resume(self):
        with db.connect() as conn:
            conn.execute("UPDATE profile SET data = '{}'")
        with self.assertRaisesRegex(ValueError, "resume"):
            self.run_job([])

    def test_ai_errors_propagate(self):
        with self.assertRaises(ai.AIError):
            self.run_job(ai.AIError("limit reached"))

    def test_draft_endpoints_only_touch_outreach(self):
        result, _ = self.run_job([self.BRIEF, {"subject": "", "body": "Hi there, note."}])
        doc_id = result["document_id"]
        items = people.list_drafts("t:1")["items"]
        self.assertEqual([d["id"] for d in items], [doc_id])
        self.assertEqual(items[0]["channel"], "linkedin_note")

        updated = people.update_draft(doc_id, people.DraftUpdate(body="  Edited note.\r\n"))
        self.assertEqual((updated["body"], updated["chars"]), ("Edited note.", 12))
        with self.assertRaises(HTTPException):
            people.update_draft(doc_id, people.DraftUpdate(body="   "))
        with self.assertRaises(HTTPException):
            people.update_draft(doc_id, people.DraftUpdate())
        # Another feature's document is invisible to these endpoints.
        for call in (lambda: people.update_draft("cover1", people.DraftUpdate(body="x")),
                     lambda: people.delete_draft("cover1")):
            with self.assertRaises(HTTPException) as cm:
                call()
            self.assertEqual(cm.exception.status_code, 404)

        self.assertEqual(people.delete_draft(doc_id), {"ok": True})
        self.assertEqual(people.list_drafts("t:1")["items"], [])
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM documents WHERE id = 'cover1'").fetchone()[0], 1)

    def test_links_endpoint(self):
        r = people.links("t:1")
        self.assertEqual(r["company"], "Acme")
        self.assertEqual(r["school"], "University of Waterloo")
        with self.assertRaises(HTTPException):
            people.links("missing")


if __name__ == "__main__":
    unittest.main()
