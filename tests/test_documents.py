import json
import tempfile
import time
import unittest
import warnings
import zipfile
from io import BytesIO
from xml.etree import ElementTree
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from board import ai, db, docx_export, documents, jobs

PROFILE = {
    "name": "Test Person", "email": "t@example.com", "phone": "555 0100", "location": "Waterloo, ON",
    "links": [{"label": "GitHub", "url": "github.com/test"}],
    "education": [{"school": "Uni", "degree": "BASc", "field": "Computer Engineering", "location": "Waterloo, ON",
                   "start": "Sep 2024", "end": "Apr 2029", "gpa": "3.9", "details": ["Courses: OS."]}],
    # Acme is in the legacy flat shape (load() converts it); Club already has points with two phrasings.
    "experience": [
        {"organization": "Acme", "role": "Developer Co-op", "location": "Toronto, ON", "start": "May 2025",
         "end": "Aug 2025", "bullets": ["Cut report time from 14s to 2s.", "Raised coverage to 85%.",
                                        "Wrote 12 integration tests.", "Reviewed pull requests.", "Mentored 2 interns."]},
        {"id": "e-club", "organization": "Club", "role": "TA", "location": "", "start": "Jan 2025", "end": "Apr 2025",
         "points": [{"id": "p-club", "phrasings": ["Ran workshops for 25 students.",
                                                   "Led weekly Git workshops for 25 students."]}]},
    ],
    "projects": [{"name": f"P{i}", "tech": ["Python"], "link": "", "date": "2025", "bullets": [f"Built P{i}."]}
                 for i in range(4)],
    "skills": {"languages": ["Python", "C++"], "frameworks": ["FastAPI"], "tools": ["Docker"], "other": []},
    "awards": ["Dean's list"], "summary": "Student.",
}

RESUME_ANSWER = {
    # Acme: a duplicate point, an unknown point and an out-of-range phrasing are dropped, and picks cap at 4.
    "experience": [{"source_index": 0, "picks": [{"point": 1, "phrasing": 0}, {"point": 0, "phrasing": 5},
                                                 {"point": 0, "phrasing": 0}, {"point": 9, "phrasing": 0},
                                                 {"point": 2, "phrasing": 0}, {"point": 3, "phrasing": 0},
                                                 {"point": 4, "phrasing": 0}]},
                   {"source_index": 7, "picks": [{"point": 0, "phrasing": 0}]},
                   {"source_index": 0, "picks": []},
                   {"source_index": 1, "picks": [{"point": 0, "phrasing": 1}]}],
    "projects": [{"source_index": i, "picks": [{"point": 0, "phrasing": 0}]} for i in (3, 0, 1, 2)],
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
        # Every point and phrasing is listed once, in the index; the profile JSON carries no bullets.
        self.assertIn("experience[1]: TA at Club (Jan 2025 – Apr 2025)\n  point 0, phrasing 0: Ran workshops for 25 "
                      "students.\n  point 0, phrasing 1: Led weekly Git workshops for 25 students.", prompt)
        self.assertNotIn('"bullets"', prompt)
        self.assertNotIn('"phrasings"', prompt)
        self.assertEqual(ask.call_args.kwargs["schema"], documents.RESUME_SCHEMA)

        doc = documents.get_document(result["document_id"])
        self.assertEqual(doc["kind"], "resume")
        self.assertEqual(doc["title"], "Resume · Cresta")
        self.assertEqual(doc["profile_version"], 3)
        c = doc["content"]
        self.assertEqual(c["header"], {"name": "Test Person", "contact": ["Waterloo, ON", "555 0100", "t@example.com"],
                                       "links": [{"label": "GitHub", "url": "github.com/test"}]})
        # Unknown and duplicate indexes are dropped; bullets capped at 4; projects capped at 3.
        self.assertEqual([e["organization"] for e in c["experience"]], ["Acme", "Club"])
        acme, club = c["experience"]
        self.assertEqual(acme["dates"], "May 2025 – Aug 2025")
        # Picks are copied verbatim, in Claude's order, one per point, capped at 4.
        self.assertEqual(acme["bullets"], ["Raised coverage to 85%.", "Cut report time from 14s to 2s.",
                                           "Wrote 12 integration tests.", "Reviewed pull requests."])
        self.assertEqual([r["phrasing"] for r in acme["refs"]], [0, 0, 0, 0])
        self.assertEqual(len({r["point_id"] for r in acme["refs"]}), 4)
        self.assertTrue(acme["source_id"].startswith("e-"))
        self.assertEqual(club["bullets"], ["Led weekly Git workshops for 25 students."])
        self.assertEqual(club["refs"], [{"point_id": "p-club", "phrasing": 1}])
        self.assertEqual(club["source_id"], "e-club")
        self.assertEqual([p["name"] for p in c["projects"]], ["P3", "P0", "P1"])
        self.assertEqual(c["projects"][0]["bullets"], ["Built P3."])
        # Only skills the profile lists, with the profile's spelling.
        self.assertEqual(c["skills"], [{"label": "Languages", "items": ["C++", "Python"]}])
        self.assertEqual(c["education"][0]["degree"], "BASc, Computer Engineering")
        self.assertEqual(c["education"][0]["details"], ["GPA: 3.9", "Courses: OS."])
        self.assertTrue(c["notes"]["description_used"])
        self.assertEqual(c["notes"]["gaps"], ["No Go experience."])
        # Verbatim text can't introduce numbers the profile doesn't have.
        self.assertEqual(c["notes"]["checks"], [])

    def test_bullets_claude_writes_are_ignored(self):
        answer = {**RESUME_ANSWER, "experience": [{"source_index": 1, "picks": [], "bullets": ["Served 9000 users."]}]}
        result, _ = self.run_job("tailor_resume", {"listing_id": "gh:1"}, answer)
        club = documents.get_document(result["document_id"])["content"]["experience"][0]
        self.assertEqual(club["bullets"], ["Ran workshops for 25 students."])  # primary phrasing fallback
        self.assertEqual(club["refs"], [{"point_id": "p-club", "phrasing": 0}])

    def test_resume_without_description_and_without_selections(self):
        answer = {"experience": [], "projects": [], "skills": [], "notes": {"emphasized": [], "gaps": [],
                                                                            "description_used": True}}
        result, ask = self.run_job("tailor_resume", {"listing_id": "gh:1"}, answer, description=None)
        self.assertIn("JOB DESCRIPTION: not available", ask.call_args.args[0])
        c = documents.get_document(result["document_id"])["content"]
        self.assertFalse(c["notes"]["description_used"])
        self.assertEqual(len(c["experience"]), 2)  # falls back to every role with its first points
        self.assertEqual(c["experience"][0]["bullets"], ["Cut report time from 14s to 2s.", "Raised coverage to 85%.",
                                                         "Wrote 12 integration tests.", "Reviewed pull requests."])
        self.assertEqual(c["experience"][1]["bullets"], ["Ran workshops for 25 students."])
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

    # ---------- formatting and Word ----------
    def formatted_resume(self):
        r, _ = self.run_job("tailor_resume", {"listing_id": "gh:1"}, RESUME_ANSWER)
        doc_id = r["document_id"]
        content = documents.get_document(doc_id)["content"]
        content["experience"][0]["bullets"][0] = [{"t": "Cut report time "}, {"t": "from 14s to 2s", "b": True},
                                                  {"t": " & <more>", "c": "#1f3a5f", "u": True}]
        content["header"]["name"] = [{"t": "Test\nPerson", "i": True}]
        content["headings"] = {"skills": "Technical skills"}
        content["format"] = {"page": {"margins": {"top": 0.75, "right": 0.6, "bottom": 0.75, "left": 0.6},
                                      "size": 10.5, "lineHeight": 1.15, "font": "Georgia"},
                             "styles": {"header.name": {"align": "left", "size": 2.5},
                                        "experience.0.bullets.0": {"after": 1, "align": "justify"},
                                        "experience.0": {"before": 0.5, "after": 1}}}
        return doc_id, content

    def test_formatting_is_saved(self):
        doc_id, content = self.formatted_resume()
        saved = documents.update_document(doc_id, documents.DocumentUpdate(content=content))
        self.assertEqual(saved["content"]["format"], content["format"])
        self.assertEqual(saved["content"]["experience"][0]["bullets"][0][1], {"t": "from 14s to 2s", "b": True})

        r, _ = self.run_job("cover_letter", {"listing_id": "gh:1", "tone": "formal"}, LETTER_ANSWER)
        letter = documents.get_document(r["document_id"])["content"]
        letter["paragraphs"][0] = [{"t": "Bold", "b": True}, {"t": " start."}]
        documents.update_document(r["document_id"], documents.DocumentUpdate(content=letter))

    def test_bad_formatting_is_refused(self):
        doc_id, content = self.formatted_resume()
        bad = [
            ("experience", 0, [{"t": "x", "script": "alert(1)"}]),
            ("experience", 0, [{"t": "x", "c": "red"}]),
            ("experience", 0, [{"t": "x", "b": "yes"}]),
            ("format", None, {"page": {"margins": {"top": 3}}}),
            ("format", None, {"page": {"font": "Comic Sans"}}),
            ("format", None, {"page": {"size": 30}}),
            ("format", None, {"styles": {"../x": {"align": "left"}}}),
            ("format", None, {"styles": {"header.name": {"align": "middle"}}}),
            ("format", None, {"styles": {"header.name": {"size": True}}}),
            ("format", None, {"other": 1}),
            ("headings", None, {"awards": "Prizes"}),
        ]
        for field, index, value in bad:
            c = json.loads(json.dumps(content))
            if field == "experience":
                c["experience"][0]["bullets"][index] = value
            else:
                c[field] = value
            with self.subTest(value=value), self.assertRaises(HTTPException) as ctx:
                documents.update_document(doc_id, documents.DocumentUpdate(content=c))
            self.assertEqual(ctx.exception.status_code, 422)

    def docx_xml(self, data: bytes, part="word/document.xml"):
        with zipfile.ZipFile(BytesIO(data)) as z:
            self.assertIn("[Content_Types].xml", z.namelist())
            for name in z.namelist():
                if name.endswith(".xml") or name.endswith(".rels"):
                    ElementTree.fromstring(z.read(name))  # every part is well-formed XML
            return z.read(part).decode()

    def test_word_download_keeps_the_formatting(self):
        doc_id, content = self.formatted_resume()
        documents.update_document(doc_id, documents.DocumentUpdate(content=content))
        res = documents.download_docx(doc_id, fs=10.5, sp=0.85)
        self.assertEqual(res.media_type, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        disposition = res.headers["content-disposition"]
        self.assertIn('filename="Test Person - Resume - Cresta.docx"', disposition)
        self.assertIn("filename*=UTF-8''Test%20Person%20%E2%80%93%20Resume", disposition)

        xml = self.docx_xml(res.body)
        self.assertIn('<w:pgMar w:top="1080" w:right="864" w:bottom="1080" w:left="864"', xml)
        self.assertIn("<w:b/><w:sz w:val=\"21\"/>", xml)  # the bold run at 10.5pt
        self.assertIn("from 14s to 2s", xml)
        self.assertIn("&amp; &lt;more&gt;", xml)
        self.assertIn('<w:color w:val="1F3A5F"/><w:sz w:val="21"/><w:szCs w:val="21"/><w:u w:val="single"/>', xml)
        self.assertIn('<w:jc w:val="both"/>', xml)
        self.assertIn('<w:jc w:val="left"/>', xml)
        self.assertIn('<w:sz w:val="52"/>', xml)  # the name at 2.5 x 10.5pt
        self.assertIn("<w:br/>", xml)
        self.assertIn("Technical skills", xml)
        self.assertIn('w:numId w:val="1"', xml)
        self.assertIn('Georgia', self.docx_xml(res.body, "word/styles.xml"))

    def test_word_download_of_unformatted_documents(self):
        r1, _ = self.run_job("tailor_resume", {"listing_id": "gh:1"}, RESUME_ANSWER)
        r2, _ = self.run_job("cover_letter", {"listing_id": "gh:1", "tone": "formal"}, LETTER_ANSWER)
        resume = self.docx_xml(documents.download_docx(r1["document_id"]).body)
        self.assertIn("Cut report time from 14s to 2s.", resume)
        self.assertIn("<w:caps/>", resume)  # section headings
        self.assertIn('<w:pgMar w:top="720" w:right="720"', resume)
        letter = self.docx_xml(documents.download_docx(r2["document_id"]).body)
        self.assertIn("Dear Cresta hiring team,", letter)
        self.assertIn("Sincerely,", letter)
        with self.assertRaises(HTTPException) as ctx:
            documents.download_docx("missing")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_runs_helpers(self):
        self.assertEqual(docx_export.runs_of("a"), [{"t": "a"}])
        self.assertEqual(docx_export.runs_of(""), [])
        self.assertEqual(docx_export.plain([{"t": "a", "b": True}, {"t": "b"}]), "ab")

    def test_posting_status(self):
        self.assertFalse(documents.posting_status("gh:1")["available"])
        documents.postings.save("gh:1", "y" * 80)
        status = documents.posting_status("gh:1")
        self.assertTrue(status["available"])
        self.assertEqual((status["source"], status["chars"]), ("pasted", 80))


if __name__ == "__main__":
    unittest.main()
