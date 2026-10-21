import json
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from board import ai, db, jobs, profile

LEGACY = {
    "name": "Test Person", "email": "t@example.com", "phone": "", "location": "Waterloo, ON", "links": [],
    "education": [{"school": "Uni", "degree": "BASc", "field": "CE", "location": "", "start": "2024", "end": "2029",
                   "gpa": "", "details": []}],
    "experience": [{"organization": "Acme", "role": "Developer Co-op", "location": "Toronto, ON", "start": "May 2025",
                    "end": "Aug 2025", "bullets": ["Cut report time from 14s to 2s.", "Raised coverage to 85%."]}],
    "projects": [{"name": "Trailmap", "tech": ["Go"], "link": "", "date": "2024",
                  "bullets": ["Built a route planner used by 30 club members.", " "]}],
    "skills": {"languages": ["Python"], "frameworks": [], "tools": [], "other": []},
    "awards": [], "summary": "Student.",
}


def points_of(data, section, i):
    return data[section][i]["points"]


class NormalizeTest(unittest.TestCase):
    def test_bullets_become_points_with_stable_ids(self):
        a, b = profile.normalize(LEGACY), profile.normalize(LEGACY)
        acme = a["experience"][0]
        self.assertNotIn("bullets", acme)
        self.assertFalse(acme["missing_from_resume"])
        self.assertEqual([pt["phrasings"] for pt in acme["points"]],
                         [["Cut report time from 14s to 2s."], ["Raised coverage to 85%."]])
        self.assertTrue(acme["id"].startswith("e-") and all(pt["id"].startswith("p-") for pt in acme["points"]))
        self.assertEqual(a, b)  # ids come from the content, so documents can refer to them before any save
        self.assertEqual(profile.normalize(a), a)  # idempotent
        self.assertEqual(len(points_of(a, "projects", 0)), 1)  # the blank bullet is gone
        self.assertTrue(a["projects"][0]["id"].startswith("j-"))
        self.assertEqual(profile.normalize("nope"), {})
        self.assertEqual(profile.normalize({"name": "x"}), {"name": "x"})

    def test_points_keep_ids_and_absorb_stray_bullets(self):
        entry = {"organization": "Acme", "role": "Dev", "id": "e-1",
                 "points": [{"id": "p-1", "phrasings": ["Cut  report time from 14s to 2s.", "  ", "Cut report time from 14s to 2s"]},
                            {"id": "p-1", "phrasings": ["Raised coverage to 85%."]}, {"phrasings": []}, "Shipped v2."],
                 "bullets": ["Raised coverage to 85%.", "Mentored 2 interns."]}
        out = profile.normalize({"experience": [entry]})["experience"][0]
        self.assertEqual(out["id"], "e-1")
        ids = [pt["id"] for pt in out["points"]]
        self.assertEqual(ids[0], "p-1")
        self.assertEqual(len(set(ids)), 4)  # the duplicate id was replaced
        self.assertEqual([pt["phrasings"] for pt in out["points"]],
                         [["Cut report time from 14s to 2s."], ["Raised coverage to 85%."], ["Shipped v2."],
                          ["Mentored 2 interns."]])

    def test_flat_data_and_prompt_text(self):
        flat = profile.flat_data(LEGACY)
        self.assertEqual(flat["experience"][0]["bullets"], ["Cut report time from 14s to 2s.", "Raised coverage to 85%."])
        self.assertNotIn("points", flat["experience"][0])
        self.assertNotIn("id", flat["experience"][0])
        self.assertNotIn("bullets", profile.flat_data(LEGACY, bullets=False)["experience"][0])
        with_variants = profile.normalize(LEGACY)
        with_variants["experience"][0]["points"][0]["phrasings"].append("Reduced report time from 14s to 2s.")
        text = profile.as_prompt_text({"data": with_variants, "preferences": {}})
        self.assertIn("Cut report time", text)
        self.assertNotIn("Reduced report time", text)  # prompts other than tailoring see the primary phrasing only

    def test_find_point(self):
        data = profile.normalize(LEGACY)
        pid = data["experience"][0]["points"][1]["id"]
        section, entry, point = profile.find_point(data, pid)
        self.assertEqual((section, entry["organization"], point["phrasings"]), ("experience", "Acme", ["Raised coverage to 85%."]))
        with self.assertRaisesRegex(ValueError, "no longer exists"):
            profile.find_point(data, "p-nope")


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.old = profile.normalize(LEGACY)
        self.old["experience"][0]["points"][0]["phrasings"].append("Reduced report time from 14s to 2s.")
        self.old["experience"].append({"organization": "Club", "role": "TA", "location": "", "start": "", "end": "",
                                       "bullets": ["Ran workshops."]})
        self.old = profile.normalize(self.old)

    def test_matched_entries_keep_points_and_gain_new_ones(self):
        new = json.loads(json.dumps(LEGACY))
        new["experience"][0].update({"organization": "ACME", "location": "", "start": "May 2025", "end": "Sep 2025",
                                     "bullets": ["Cut report time from 14 s to 2 s", "Shipped the billing service."]})
        new["projects"][0].update({"tech": ["Go", "SQLite"], "bullets": ["Built a route planner used by 30 club members."]})
        new["skills"]["languages"] = ["Python", "Go"]
        merged = profile.merge_profile(self.old, new)
        acme = merged["experience"][0]
        old_acme = self.old["experience"][0]
        self.assertEqual(acme["id"], old_acme["id"])
        self.assertEqual(acme["organization"], "ACME")  # facts come from the file ...
        self.assertEqual((acme["location"], acme["end"]), ("Toronto, ON", "Sep 2025"))  # ... unless the file left them blank
        self.assertEqual(acme["points"][:2], old_acme["points"])  # phrasings and ids survive
        self.assertEqual([pt["phrasings"][0] for pt in acme["points"]],
                         ["Cut report time from 14s to 2s.", "Raised coverage to 85%.", "Shipped the billing service."])
        self.assertFalse(acme["missing_from_resume"])
        self.assertEqual(merged["projects"][0]["tech"], ["Go", "SQLite"])
        self.assertEqual(len(merged["projects"][0]["points"]), 1)
        self.assertEqual(merged["skills"]["languages"], ["Python", "Go"])

    def test_entries_missing_from_the_file_are_kept_and_flagged(self):
        new = json.loads(json.dumps(LEGACY))
        new["experience"].insert(0, {"organization": "New Co", "role": "Intern", "location": "", "start": "", "end": "",
                                     "bullets": ["Did things."]})
        merged = profile.merge_profile(self.old, new)
        self.assertEqual([(e["organization"], e["missing_from_resume"]) for e in merged["experience"]],
                         [("New Co", False), ("Acme", False), ("Club", True)])
        self.assertEqual(merged["experience"][2]["id"], self.old["experience"][1]["id"])
        # When it comes back, the flag clears and its points are kept.
        again = profile.merge_profile(merged, {**new, "experience": new["experience"] + [
            {"organization": "club", "role": "T.A.", "location": "", "start": "", "end": "", "bullets": ["Ran workshops."]}]})
        club = next(e for e in again["experience"] if e["organization"] == "club")
        self.assertFalse(club["missing_from_resume"])
        self.assertEqual(club["points"], self.old["experience"][1]["points"])
        self.assertEqual(profile.merge_profile({}, new)["experience"][0]["organization"], "New Co")


class ApiTest(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(db, "DB_PATH", Path(self.tmp.name) / "test.db")
        self.patch.start()
        db.init()
        with db.connect() as conn:
            conn.execute("INSERT INTO profile (id, data, resume_text, version, updated_at) VALUES (1, ?, 'resume text', 3, 0)",
                         (json.dumps(LEGACY),))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def version(self):
        with db.connect() as conn:
            return conn.execute("SELECT version FROM profile").fetchone()[0]

    def test_load_normalises_legacy_rows_without_writing(self):
        with db.connect() as conn:
            p = profile.load(conn)
            raw = conn.execute("SELECT data FROM profile").fetchone()[0]
        self.assertIn("points", p["data"]["experience"][0])
        self.assertIn("bullets", json.loads(raw)["experience"][0])
        self.assertEqual(profile.get_profile()["data"], p["data"])

    def test_update_bumps_version_only_when_facts_change(self):
        data = profile.get_profile()["data"]
        data["experience"][0]["points"][0]["phrasings"].append("Reduced report time from 14s to 2s.")
        saved = profile.update_profile(profile.ProfileUpdate(data=data))
        self.assertEqual(saved["version"], 3)  # an extra phrasing isn't a new fact
        self.assertEqual(len(saved["data"]["experience"][0]["points"][0]["phrasings"]), 2)
        with db.connect() as conn:
            self.assertIn("points", json.loads(conn.execute("SELECT data FROM profile").fetchone()[0])["experience"][0])

        data = saved["data"]
        data["experience"][0]["points"][0]["phrasings"].reverse()  # a new primary phrasing is
        self.assertEqual(profile.update_profile(profile.ProfileUpdate(data=data))["version"], 4)
        data["experience"][0]["end"] = "Sep 2025"
        self.assertEqual(profile.update_profile(profile.ProfileUpdate(data=data))["version"], 5)
        data["experience"][0]["points"].append({"phrasings": ["Mentored 2 interns."]})
        self.assertEqual(profile.update_profile(profile.ProfileUpdate(data=data))["version"], 6)
        self.assertEqual(profile.update_profile(profile.ProfileUpdate(preferences={"school": "Uni"}))["version"], 7)
        # The raw JSON editor may still send flat bullets.
        saved = profile.update_profile(profile.ProfileUpdate(data=LEGACY))
        self.assertEqual([pt["phrasings"] for pt in saved["data"]["experience"][0]["points"]],
                         [["Cut report time from 14s to 2s."], ["Raised coverage to 85%."]])
        with self.assertRaises(HTTPException) as ctx:
            profile.update_profile(profile.ProfileUpdate(data={"summary": "x" * 300_000}))
        self.assertEqual(ctx.exception.status_code, 413)

    def test_extract_merges_into_the_saved_profile(self):
        with db.connect() as conn:
            data = profile.load(conn)["data"]
        data["experience"][0]["points"][0]["phrasings"].append("Reduced report time from 14s to 2s.")
        profile.update_profile(profile.ProfileUpdate(data=data))
        extracted = json.loads(json.dumps(LEGACY))
        extracted["experience"][0]["bullets"].append("Mentored 2 interns.")
        with mock.patch.object(profile.ai, "ask", return_value=extracted) as ask:
            jobs.HANDLERS["extract_profile"]({})
        self.assertIn("resume text", ask.call_args.args[0])
        p = profile.get_profile()
        acme = p["data"]["experience"][0]
        self.assertEqual(acme["points"][0]["phrasings"][1], "Reduced report time from 14s to 2s.")
        self.assertEqual(acme["points"][2]["phrasings"], ["Mentored 2 interns."])
        self.assertEqual(p["preferences"]["school"], "Uni")
        self.assertEqual(p["version"], 4)

    def test_suggest_phrasings_keeps_only_same_fact_suggestions(self):
        data = profile.get_profile()["data"]
        pid = data["experience"][0]["points"][0]["id"]
        answer = {"phrasings": ["Reduced report time from 14s to 2s by caching results.",   # same numbers: kept
                                "Cut report time from 14s to 2s, an 86% drop.",           # new number
                                "Cut report time from 14s to 2s.",                        # already there
                                "Leveraged caching to cut report time from 14s to 2s.",   # filler
                                "Cut report time.",                                        # dropped a number
                                "   "]}
        with mock.patch.object(profile.ai, "ask", return_value=answer) as ask:
            result = jobs.HANDLERS["suggest_phrasings"]({"point_id": pid})
        prompt = ask.call_args.args[0]
        self.assertIn(ai.HONESTY_RULES, prompt)
        self.assertIn("BULLET: Cut report time from 14s to 2s.", prompt)
        self.assertIn("Developer Co-op at Acme", prompt)
        self.assertEqual(ask.call_args.kwargs["schema"], profile.SUGGEST_SCHEMA)
        self.assertEqual(result, {"point_id": pid, "suggestions": ["Reduced report time from 14s to 2s by caching results."],
                                  "dropped": 5})
        # Nothing was saved: the user keeps or discards each suggestion in the editor.
        self.assertEqual(profile.get_profile()["data"], data)
        self.assertEqual(self.version(), 3)
        with self.assertRaisesRegex(ValueError, "no longer exists"):
            jobs.HANDLERS["suggest_phrasings"]({"point_id": "p-nope"})
        data["experience"][0]["points"][0]["phrasings"] += [f"Phrasing {i} of 14s to 2s." for i in range(5)]
        profile.update_profile(profile.ProfileUpdate(data=data))
        with self.assertRaisesRegex(ValueError, "already has 6"):
            jobs.HANDLERS["suggest_phrasings"]({"point_id": pid})
        with db.connect() as conn:
            conn.execute("UPDATE profile SET data = '{}'")
        with self.assertRaisesRegex(ValueError, "Profile tab"):
            jobs.HANDLERS["suggest_phrasings"]({"point_id": pid})


if __name__ == "__main__":
    unittest.main()
