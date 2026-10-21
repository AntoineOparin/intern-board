import json
import unittest

from board import community


NEGAR = """\
| Company | Role | Location | Apply | Date Posted |
|--------|------|----------|:-----:|--------------|
| Magnet Forensics | Software Developer Co-op (Winter 2027) | Waterloo, ON / Ottawa, ON | [![Apply](https://img.shields.io/badge/-Apply-blue)](https://jobs.lever.co/magnetforensics/6eba87dc-f110-47b2-8015-31311ca60f52/) | Oct 10, 2026 |
| ↳ | Data Engineering Intern (Summer/Fall 2027) | Remote, Canada | [![Apply](https://img.shields.io/badge/-Apply-blue)](https://example.com/jobs/2) | Oct 9, 2026 |
| Varian | Performance Engineering Co-op | Ottawa, ON | Closed🔒 | Oct 9, 2026 |
| Somewhere | Software Intern | London, UK | [Apply](https://example.com/jobs/3) | Oct 9, 2026 |
"""

ZAPPLY = """\
<details>
<summary><h3>💻 <strong>Software Engineering</strong></h3></summary>

| Company | Role | Location | Posted | Visa | **Apply** |
|---------|------|----------|--------|------|----------|
| **RTX** | Software Engineering Co-op (Summer/Fall 2027) | IA-CEDAR RAPIDS | 2d | ✅ Sponsor | [<img src="images/apply.png" alt="Apply">](https://zapply.jobs/l/d/rtx-1?s=gh) |
| **Acme** | Marketing Intern | Boston, MA | 3h |  | [<img src="images/apply.png" alt="Apply">](https://zapply.jobs/l/d/acme-2?s=gh) |
</details>
<details>
<summary><h3>💼 <strong>Business &amp; Operations</strong></h3></summary>

| Company | Role | Location | Posted | Visa | **Apply** |
|---------|------|----------|--------|------|----------|
| **Bank** | Software Engineer Intern | New York, NY | 1d |  | [<img src="images/apply.png" alt="Apply">](https://zapply.jobs/l/d/bank-3?s=gh) |
</details>
"""


class CommunityTest(unittest.TestCase):
    def test_negarprh(self):
        rows = community.parse_negarprh(NEGAR)
        self.assertEqual([(r["company"], r["title"]) for r in rows], [
            ("Magnet Forensics", "Software Developer Co-op (Winter 2027)"),
            ("Magnet Forensics", "Data Engineering Intern (Summer/Fall 2027)"),  # "↳" = same company
        ])  # closed and non-US/Canada rows are skipped
        self.assertEqual(rows[0]["posting_key"], "lever:6eba87dc-f110-47b2-8015-31311ca60f52")
        self.assertEqual(rows[0]["regions"], ",CA,")
        self.assertEqual(rows[1]["terms"], ",Summer 2027,Fall 2027,")
        self.assertIn("REMOTE", rows[1]["regions"])

    def test_zapply(self):
        now = 1_800_000_000
        rows = community.parse_zapply(ZAPPLY, now)
        # Marketing isn't tech; "Business & Operations" isn't a tech section.
        self.assertEqual([r["company"] for r in rows], ["RTX"])
        self.assertEqual(rows[0]["locations"], "Cedar Rapids, IA")
        self.assertEqual(rows[0]["sponsorship"], "May Offer Sponsorship")  # an estimate, not the employer's word
        self.assertEqual(rows[0]["date_posted"], (now - 2 * 86400) // 3600 * 3600)

    def test_zapply_locations(self):
        self.assertEqual(community.zapply_location("IA-CEDAR RAPIDS"), ["Cedar Rapids, IA"])
        self.assertEqual(community.zapply_location("CA-SAN DIEGO"), ["San Diego, CA"])  # California here
        self.assertEqual(community.zapply_location("Santa Clara, California -..."), ["Santa Clara, California"])
        self.assertEqual(community.zapply_location("Georgia, US Offsite, More..."), ["United States"])
        self.assertEqual(community.zapply_location("Greater London"), [])

    def test_michelleokolie(self):
        raw = json.dumps([
            {"id": "a", "active": True, "is_visible": True, "company_name": "Google", "title": "Software Developer Intern",
             "url": "https://example.com/1", "locations": ["Waterloo, ON"], "season": "Summer", "date_posted": 1},
            {"id": "b", "active": False, "company_name": "Old", "title": "SWE Intern", "url": "https://example.com/2",
             "locations": ["Toronto, ON"], "date_posted": 1},
        ])
        rows = community.parse_michelleokolie(raw)
        self.assertEqual([r["id"] for r in rows], ["michelleokolie:a"])
        self.assertEqual(rows[0]["terms"], ",Summer 2027,")

    def test_frogg(self):
        raw = json.dumps([
            {"company": "CAE", "role": "Stagiaire - Développeur Full Stack", "location": "Montréal, QC, Canada",
             "term": "Winter 2027", "status": "open", "date_posted": "2026-10-20",
             "link": "https://cae.wd3.myworkdayjobs.com/career/job/Montreal/Stagiaire_123?source=frogg"},
            {"company": "Old Co", "role": "Software Intern", "location": "Toronto, ON", "term": "Summer 2027",
             "status": "closed", "date_posted": "2026-09-01", "link": "https://example.com/1"},
        ])
        rows = community.parse_frogg(raw)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["company"], row["regions"], row["category"], row["terms"], row["posting_key"]),
                         ("CAE", ",CA,", "Software", ",Winter 2027,", "wd:cae:123"))

    def test_name_key(self):
        self.assertEqual(community.name_key("Shopify Inc.", "Software Engineer Intern (Summer 2027)"),
                         community.name_key("Shopify", "Software Engineer Intern"))


if __name__ == "__main__":
    unittest.main()
