import json
import tempfile
import time
import unittest
import warnings
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from board import ai, db, documents, jobs

PROFILE = {
    "name": "Test Person", "email": "t@example.com", "phone": "555 0100", "location": "Waterloo, ON",
    "links": [{"label": "GitHub", "url": "github.com/test"}],
    "education": [{"school": "Uni", "degree": "BASc", "field": "Computer Engineering", "location": "Waterloo, ON",
                   "start": "Sep 2024", "end": "Apr 2029", "gpa": "3.9", "details": ["Courses: OS."]}],
    "experience": [
        {"organization": "Acme", "role": "Developer Co-op", "location": "Toronto, ON", "start": "May 2025",
         "end": "Aug 2025", "bullets": ["Cut report time from 14s to 2s.", "Raised coverage to 85%."]},
        {"organization": "Club", "role": "TA", "location": "", "start": "Jan 2025", "end": "Apr 2025",
         "bullets": ["Ran workshops for 25 students."]},
    ],
    "projects": [{"name": f"P{i}", "tech": ["Python"], "link": "", "date": "2025", "bullets": [f"Built P{i}."]}
                 for i in range(4)],
    "skills": {"languages": ["Python", "C++"], "frameworks": ["FastAPI"], "tools": ["Docker"], "other": []},
    "awards": ["Dean's list"], "summary": "Student.",
}

RESUME_ANSWER = {
    "experience": [{"source_index": 0, "bullets": ["Cut report time from 14s to 2s.", "Raised coverage to 85%.",
                                                   "Served 9000 users.", "a", "b"]},
                   {"source_index": 7, "bullets": ["Made up role."]},
                   {"source_index": 0, "bullets": ["Duplicate."]}],
    "projects": [{"source_index": i, "bullets": [f"Built P{i}."]} for i in (3, 0, 1, 2)],
    "skills": [{"label": "Languages", "items": ["c++", "Python", "Rust"]}, {"label": "Tools", "items": ["Kubernetes"]}],
    "notes": {"emphasized": ["Backend work."], "gaps": ["No Go experience."], "description_used": True},
}

LETTER_ANSWER = {
    "greeting": "Dear Cresta hiring team,",
    "paragraphs": [" ".join(["word"] * 80)] * 3 + ["I cut report time from 14s to 2s."],
    "closing": "Sincerely,",
    "notes": {"drew_on": ["Acme"], "gaps": [], "description_used": True},
}


class DocumentsTest(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # db.connect() leaves closing to GC
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(db, "DB_PATH", Path(self.tmp.name) / "test.db")
        self.patch.start()
        db.init()
        with db.connect() as conn:
            conn.execute("INSERT INTO listings (id, source, company, title, url, locations, regions, terms, degrees, "
                         "first_seen) VALUES ('gh:1', 'board', 'Cresta', 'Software Engineer Intern', "
                         "'https://example.com', 'Toronto', ',CA,', ',Summer 2027,', ',', 0)")
            conn.execute("INSERT INTO profile (id, data, version, updated_at) VALUES (1, ?, 3, 0)",
                         (json.dumps(PROFILE),))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def run_job(self, kind, payload, answer, description="Build backend services in Python and Go. " * 3):
        with mock.patch.object(documents.postings, "description",
                               return_value={"text": description, "source": "api"}), \
                mock.patch.object(documents.ai, "ask", return_value=answer) as ask:
            result = jobs.HANDLERS[kind](payload)
        return result, ask

    # ---------- resume ----------
    def test_tailor_resume_saves_document_with_profile_facts(self):
        result, ask = self.run_job("tailor_resume", {"listing_id": "gh:1"}, RESUME_ANSWER)
        prompt = ask.call_args.args[0]
        self.assertIn(ai.HONESTY_RULES, prompt)
        self.assertIn("Build backend services", prompt)
        self.assertIn("experience[1]: TA at Club", prompt)
        self.assertEqual(ask.call_args.kwargs["schema"], documents.RESUME_SCHEMA)

        doc = documents.get_document(result["document_id"])
        self.assertEqual(doc["kind"], "resume")
        self.assertEqual(doc["title"], "Resume · Cresta")
        self.assertEqual(doc["profile_version"], 3)
        c = doc["content"]
        self.assertEqual(c["header"], {"name": "Test Person", "contact": ["Waterloo, ON", "555 0100", "t@example.com"],
                                       "links": [{"label": "GitHub", "url": "github.com/test"}]})
        # Unknown and duplicate indexes are dropped; bullets capped at 4; projects capped at 3.
        self.assertEqual([e["organization"] for e in c["experience"]], ["Acme"])
        self.assertEqual(c["experience"][0]["dates"], "May 2025 – Aug 2025")
        self.assertEqual(len(c["experience"][0]["bullets"]), 4)
        self.assertEqual([p["name"] for p in c["projects"]], ["P3", "P0", "P1"])
        # Only skills the profile lists, with the profile's spelling.
        self.assertEqual(c["skills"], [{"label": "Languages", "items": ["C++", "Python"]}])
        self.assertEqual(c["education"][0]["degree"], "BASc, Computer Engineering")
        self.assertEqual(c["education"][0]["details"], ["GPA: 3.9", "Courses: OS."])
        self.assertTrue(c["notes"]["description_used"])
        self.assertEqual(c["notes"]["gaps"], ["No Go experience."])
        # 9000 isn't in the profile, so it's flagged.
        self.assertEqual(len(c["notes"]["checks"]), 1)
        self.assertIn("9000", c["notes"]["checks"][0])

    def test_resume_without_description_and_without_selections(self):
        answer = {"experience": [], "projects": [], "skills": [], "notes": {"emphasized": [], "gaps": [],
                                                                            "description_used": True}}
        result, ask = self.run_job("tailor_resume", {"listing_id": "gh:1"}, answer, description=None)
        self.assertIn("JOB DESCRIPTION: not available", ask.call_args.args[0])
        c = documents.get_document(result["document_id"])["content"]
        self.assertFalse(c["notes"]["description_used"])
        self.assertEqual(len(c["experience"]), 2)  # falls back to every role with its own bullets
        self.assertEqual(c["skills"][0], {"label": "Languages", "items": ["Python", "C++"]})
        self.assertEqual(c["notes"]["checks"], [])

    def test_pasted_description_is_saved_first(self):
        with mock.patch.object(documents.postings, "save") as save:
            self.run_job("tailor_resume", {"listing_id": "gh:1", "description": "x" * 60}, RESUME_ANSWER)
        save.assert_called_once_with("gh:1", "x" * 60)
        with self.assertRaises(ValueError):
            self.run_job("tailor_resume", {"listing_id": "gh:1", "description": "too short"}, RESUME_ANSWER)

    def test_errors(self):
        with self.assertRaises(ValueError):
            self.run_job("tailor_resume", {"listing_id": "nope"}, RESUME_ANSWER)
        with db.connect() as conn:
            conn.execute("DELETE FROM profile")
        with self.assertRaisesRegex(ValueError, "Profile tab"):
            self.run_job("tailor_resume", {"listing_id": "gh:1"}, RESUME_ANSWER)

    # ---------- cover letter ----------
    def test_cover_letter(self):
        result, ask = self.run_job("cover_letter", {"listing_id": "gh:1", "tone": "conversational"}, LETTER_ANSWER)
        prompt = ask.call_args.args[0]
        self.assertIn(ai.HONESTY_RULES, prompt)
        self.assertIn(documents.TONE_GUIDE["conversational"], prompt)
        self.assertIn("Dear Cresta hiring team", prompt)
        doc = documents.get_document(result["document_id"])
        c = doc["content"]
        self.assertEqual(doc["title"], "Cover letter · Cresta")
        self.assertEqual(c["tone"], "conversational")
        self.assertEqual(c["signature"], "Test Person")
        self.assertEqual(len(c["paragraphs"]), 4)
        self.assertEqual(c["notes"]["word_count"], 248)
        self.assertEqual(c["notes"]["checks"], [])

    def test_cover_letter_flags(self):
        answer = {**LETTER_ANSWER, "paragraphs": ["I am writing to express my interest. Last summer we grew 400%."]}
        result, _ = self.run_job("cover_letter", {"listing_id": "gh:1", "tone": "formal"}, answer)
        checks = documents.get_document(result["document_id"])["content"]["notes"]["checks"]
        self.assertEqual(len(checks), 4)  # unknown number, filler phrase, relative date, length
        with self.assertRaisesRegex(ValueError, "Unknown tone"):
            self.run_job("cover_letter", {"listing_id": "gh:1", "tone": "angry"}, LETTER_ANSWER)
        with self.assertRaises(ai.AIError):
            self.run_job("cover_letter", {"listing_id": "gh:1"}, {**LETTER_ANSWER, "paragraphs": [" "]})

    # ---------- API ----------
    def test_list_update_delete(self):
        r1, _ = self.run_job("tailor_resume", {"listing_id": "gh:1"}, RESUME_ANSWER)
        time.sleep(0.01)
        r2, _ = self.run_job("cover_letter", {"listing_id": "gh:1", "tone": "formal"}, LETTER_ANSWER)
        with db.connect() as conn:  # another feature's kind must not show up
            conn.execute("INSERT INTO documents (id, listing_id, kind, content, created_at, updated_at) "
                         "VALUES ('out1', 'gh:1', 'outreach', '{}', 0, 0)")
        items = documents.list_documents("gh:1")["items"]
        self.assertEqual({i["id"] for i in items}, {r1["document_id"], r2["document_id"]})
        self.assertNotIn("content", items[0])
        self.assertFalse(items[0]["stale"])
        self.assertEqual(documents.list_documents("other")["items"], [])
        with self.assertRaises(HTTPException):
            documents.get_document("out1")
        with self.assertRaises(HTTPException):
            documents.delete_document("out1")

        doc = documents.get_document(r2["document_id"])
        self.assertEqual(doc["listing"]["company"], "Cresta")
        content = {**doc["content"], "paragraphs": ["Edited."]}
        saved = documents.update_document(r2["document_id"], documents.DocumentUpdate(content=content))
        self.assertEqual(saved["content"]["paragraphs"], ["Edited."])
        with self.assertRaises(HTTPException) as ctx:
            documents.update_document(r2["document_id"], documents.DocumentUpdate(content={"greeting": "Hi"}))
        self.assertEqual(ctx.exception.status_code, 422)

        documents.delete_document(r1["document_id"])
        with self.assertRaises(HTTPException):
            documents.get_document(r1["document_id"])
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM documents WHERE kind = 'outreach'").fetchone()[0], 1)

    def test_posting_status(self):
        self.assertFalse(documents.posting_status("gh:1")["available"])
        documents.postings.save("gh:1", "y" * 80)
        status = documents.posting_status("gh:1")
        self.assertTrue(status["available"])
        self.assertEqual((status["source"], status["chars"]), ("pasted", 80))


if __name__ == "__main__":
    unittest.main()
