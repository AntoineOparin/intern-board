import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from board import ats, db, employers, montreal, sources

NOW = int(time.time())


class BoardNamesTest(unittest.TestCase):
    def test_workday_boards_only_for_canadian_internships(self):
        names = sources.board_names([
            ("https://cae.wd3.myworkdayjobs.com/career/job/Montreal/Stagiaire_1", "CAE", ["Montreal, QC"], NOW),
            ("https://big.wd5.myworkdayjobs.com/Ext/job/Austin/Intern_2", "Big Co", ["Austin, TX"], NOW),
            ("https://jobs.smartrecruiters.com/Acme/123", "Acme", ["Austin, TX"], NOW),
            ("https://jobs.lever.co/old/6ed76ce8-4156-4b60-b120-403538bd66cd", "Old", ["Toronto, ON"],
             NOW - 600 * 86400),  # last listed too long ago
            ("https://example.com/careers/1", "Custom", ["Montreal, QC"], NOW),
        ], NOW)
        self.assertEqual(set(names), {("workday", "cae.wd3/career"), ("smartrecruiters", "acme")})

    def test_listed_boards_parse_back_to_themselves(self):
        for boards in (montreal.BOARDS, employers.BOARDS):
            for platform, token, name in boards:
                self.assertIn(platform, ats.PLATFORMS, name)
                self.assertEqual(ats.parse_board_url(ats.board_page(platform, token)), (platform, token), name)
            self.assertEqual(len({(p, t) for p, t, _ in boards}), len(boards))


class SyncBoardsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(db, "DB_PATH", Path(self.tmp.name) / "test.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        db.init()

    def test_seed_and_sync(self):
        raw = [{"url": "https://tsimagine.hire.trakstar.com/jobs/fk0zlh8/", "company_name": "TS Imagine Inc",
                "locations": ["Montreal, QC"], "date_posted": NOW}]
        with db.connect() as conn:
            sources.seed_companies(conn, raw, NOW)
            company = dict(conn.execute("SELECT * FROM companies WHERE platform = 'recruiterbox'").fetchone())
        self.assertEqual(company["name"], "TS Imagine")  # the Montreal list's name wins
        jobs = [{"key": "rbox:fk0zlh8", "title": "Financial Technology Interns - Spring 2027",
                 "url": "https://tsimagine.hire.trakstar.com/jobs/fk0zlh8/", "locations": ["Montréal, Québec, Canada"],
                 "regions": {"CA"}, "posted": None, "intern_flag": False}]
        with mock.patch.object(ats, "fetch_board", return_value=(jobs, 1000, 23)), db.connect() as conn:
            stats = sources.sync_boards(conn, [company], set(), NOW)
            listing = dict(conn.execute("SELECT * FROM listings").fetchone())
            company = dict(conn.execute("SELECT * FROM companies WHERE platform = 'recruiterbox'").fetchone())
        self.assertEqual(stats["kept"], 1)
        self.assertEqual((company["jobs_total"], company["interns"]), (23, 1))
        self.assertEqual((listing["board"], listing["terms"], listing["date_posted"]),
                         ("recruiterbox:tsimagine", ",Spring 2027,", None))


if __name__ == "__main__":
    unittest.main()
