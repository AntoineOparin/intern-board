import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from board import ai, db, profile, ranking

NOW = time.time()
PROFILE = {
    "name": "Test Person", "email": "", "phone": "", "location": "Waterloo, ON", "links": [],
    "education": [{"school": "University of Waterloo", "degree": "Bachelor of Applied Science",
                   "field": "Computer Engineering", "location": "", "start": "", "end": "", "gpa": "",
                   "details": []}],
    "experience": [{"organization": "Northwind", "role": "Software Developer Co-op", "location": "",
                    "start": "", "end": "", "bullets": []}],
    "projects": [{"name": "CPU", "tech": ["SystemVerilog"], "link": "", "date": "", "bullets": []}],
    "skills": {"languages": ["Python", "C++", "Go"], "frameworks": ["FastAPI"], "tools": ["AWS (EC2, S3)"],
               "other": []},
    "awards": [], "summary": "Computer engineering student who builds Python services.",
}


def listing(id, title, category="Software", terms=",Summer 2027,", regions=",US,", degrees=",Bachelor's,",
            posted=NOW - 3 * 86400, active=1):
    return {"id": id, "source": "simplify", "company": f"Co {id}", "title": title, "url": f"https://x/{id}",
            "locations": "Toronto, ON", "regions": regions, "category": category, "terms": terms,
            "degrees": degrees, "sponsorship": None, "date_posted": posted, "first_seen": posted, "active": active}


class TempDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(db, "DB_PATH", Path(self.tmp.name) / "test.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        db.init()

    def add_listings(self, *rows):
        with db.connect() as conn:
            for r in rows:
                conn.execute(f"INSERT INTO listings ({', '.join(r)}) VALUES ({', '.join('?' * len(r))})",
                             list(r.values()))

    def set_profile(self, data=PROFILE, **prefs):
        with db.connect() as conn:
            profile._save(conn, data=json.dumps(data), preferences=json.dumps({**profile.DEFAULT_PREFERENCES, **prefs}))
            return profile.load(conn)

    def matches(self):
        with db.connect() as conn:
            return {r["listing_id"]: dict(r) for r in conn.execute("SELECT * FROM matches")}


class ScorerTest(unittest.TestCase):
    def scorer(self, **prefs):
        return ranking.Scorer({"data": PROFILE, "preferences": {**profile.DEFAULT_PREFERENCES, **prefs},
                               "version": 1}, now=NOW)

    def test_skills_in_title_raise_score_and_reason(self):
        s = self.scorer()
        hit, reason = s.score(listing("a", "Backend Intern - Python, FastAPI"))
        miss, _ = s.score(listing("b", "Marketing Intern", category="Product"))
        self.assertGreater(hit, miss)
        self.assertIn("Matches Python, FastAPI", reason)

    def test_skill_word_boundaries(self):
        s = self.scorer()
        _, reason = s.score(listing("a", "Software Engineer Intern (C++)"))
        self.assertIn("C++", reason)
        _, reason = s.score(listing("b", "Intern, AWS Platform"))
        self.assertIn("AWS", reason)  # "AWS (EC2, S3)" normalised
        _, reason = s.score(listing("c", "Good engineering intern"))
        self.assertNotIn("Go", reason)

    def test_preferences(self):
        s = self.scorer(regions=["CA"], terms=["Summer 2027"], categories=["Software"], target_roles=["backend"])
        good, reason = s.score(listing("a", "Backend Engineer Intern", regions=",CA,"))
        bad, bad_reason = s.score(listing("b", "Backend Engineer Intern", regions=",US,", terms=",Fall 2027,",
                                          category="Quant"))
        self.assertGreater(good, bad + 30)
        self.assertIn("Canada", reason)
        self.assertIn("Summer 2027", reason)
        self.assertIn("backend role", reason)
        self.assertIn("Outside your regions", bad_reason)

    def test_degree_and_past_terms(self):
        s = self.scorer()
        self.assertEqual(s.degree, "Bachelor's")
        phd, reason = s.score(listing("a", "Research Intern", degrees=",PhD,"))
        ok, _ = s.score(listing("b", "Research Intern"))
        self.assertLess(phd, ok - 20)
        self.assertIn("PhD only", reason)
        _, reason = s.score(listing("c", "Software Intern", terms=",Winter 2025,"))
        self.assertIn("already started", reason)

    def test_score_bounds(self):
        s = self.scorer(regions=["CA"], terms=["Fall 2030"], categories=["Quant"])
        low, _ = s.score(listing("a", "PhD Research", degrees=",PhD,", terms=",Winter 2020,", posted=NOW - 400 * 86400))
        high, _ = s.score(listing("b", "Python C++ Go FastAPI", category="Quant", regions=",CA,", terms=",Fall 2030,"))
        self.assertGreaterEqual(low, 0)
        self.assertLessEqual(high, 100)


class QuickStoreTest(TempDB):
    def test_no_profile_does_nothing(self):
        self.add_listings(listing("a", "Python Intern"))
        with db.connect() as conn:
            self.assertEqual(ranking.compute_quick(conn), 0)
            st = ranking.status(conn)
        self.assertFalse(st["has_profile"])
        self.assertEqual(self.matches(), {})

    def test_status_fills_missing_and_never_overwrites_claude(self):
        self.add_listings(listing("a", "Python Intern"), listing("b", "Sales Intern"), listing("c", "Old", active=0))
        p = self.set_profile()
        with db.connect() as conn:
            st = ranking.status(conn)
            self.assertEqual((st["computed"], st["quick"], st["active"]), (2, 2, 2))
            self.assertEqual(ranking.status(conn)["computed"], 0)  # nothing missing the second time
            conn.execute("UPDATE matches SET method = 'claude', score = 99 WHERE listing_id = 'a'")
            conn.commit()
            ranking.compute_quick(conn)
        m = self.matches()
        self.assertEqual((m["a"]["method"], m["a"]["score"]), ("claude", 99))
        self.assertEqual(m["b"]["profile_version"], p["version"])
        # A new profile version replaces the old Claude score with a fresh quick one.
        p2 = self.set_profile(regions=["CA"])
        with db.connect() as conn:
            self.assertEqual(ranking.status(conn)["computed"], 2)
        m = self.matches()
        self.assertEqual((m["a"]["method"], m["a"]["profile_version"]), ("quick", p2["version"]))


class RankJobTest(TempDB):
    def setUp(self):
        super().setUp()
        self.add_listings(*[listing(f"l{i}", f"Python Intern {i}" if i < 30 else f"Sales Intern {i}")
                            for i in range(45)])
        self.p = self.set_profile()

    def test_requires_profile(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM profile")
        with self.assertRaises(ValueError):
            ranking.rank_listings({"limit": 5})

    def test_batches_validates_ids_and_stores(self):
        prompts = []

        def fake_ask(prompt, **kw):
            self.assertEqual(kw["model"], "sonnet")
            self.assertIs(kw["schema"], ranking.RANK_SCHEMA)
            prompts.append(prompt)
            n = prompt.count("\nid=")
            results = [{"id": i, "score": 150 if i == 1 else 70, "reason": "" if i == 3 else f"Reason {i}"}
                       for i in range(1, n + 1)]
            results += [{"id": 999, "score": 50, "reason": "bogus"}, {"id": 2, "score": 1, "reason": "dup"},
                        {"id": "x", "score": 5, "reason": "bad"}]
            return {"results": results}

        with mock.patch.object(ai, "ask", side_effect=fake_ask):
            r = ranking.rank_listings({"limit": 25})
        self.assertEqual(len(prompts), 2)  # 20 + 5
        self.assertIn("CANDIDATE PROFILE", prompts[0])
        self.assertEqual((r["requested"], r["ranked"], r["skipped"]), (25, 23, 2))  # id 3 has no reason in each batch
        m = self.matches()
        claude = [v for v in m.values() if v["method"] == "claude"]
        self.assertEqual(len(claude), 23)
        self.assertTrue(all(0 <= v["score"] <= 100 for v in claude))
        self.assertTrue(all(v["profile_version"] == self.p["version"] for v in claude))
        # The top quick scores (Python titles) were the ones sent.
        self.assertTrue(all("Python" in p for p in prompts[0].split("LISTINGS")[1].splitlines()[1:]))

        # A second run skips listings Claude already scored.
        with mock.patch.object(ai, "ask", side_effect=fake_ask):
            ranking.rank_listings({"limit": 40})
        self.assertEqual(sum(v["method"] == "claude" for v in self.matches().values()), 23 + 21)  # 22 left; the first batch drops id 3

    def test_filters_and_errors(self):
        self.add_listings(listing("ca", "Python Intern", regions=",CA,"))
        with mock.patch.object(ai, "ask", return_value={"results": [{"id": 1, "score": 80, "reason": "Fits."}]}) as ask:
            r = ranking.rank_listings({"limit": 40, "region": "CA"})
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(r["ranked"], 1)
        self.assertEqual(self.matches()["ca"]["method"], "claude")
        with mock.patch.object(ai, "ask", side_effect=ai.AIError("Usage limit")):
            with self.assertRaisesRegex(ai.AIError, "Usage limit"):
                ranking.rank_listings({"limit": 5})
        with self.assertRaises(ValueError):
            ranking.rank_listings({"region": "EU"})


if __name__ == "__main__":
    unittest.main()
