import tempfile
import unittest
from pathlib import Path
from unittest import mock

from board import db, main, postings, visa


class DetectTest(unittest.TestCase):
    def verdict(self, text):
        found = visa.detect(text)
        return found and found[0]

    def test_refusals(self):
        for text in [
            "We are unable to sponsor visas for this role.",
            "Applicants must be authorized to work in the U.S. without the need for employer sponsorship now or in the future.",
            "This position is not eligible for visa sponsorship.",
            "Sponsorship is not available for this internship.",
            "No visa sponsorship.",
            "The company will not provide immigration sponsorship, including CPT.",
            "Candidates must not require sponsorship now or in the future.",
        ]:
            self.assertEqual(self.verdict(text), visa.NO, text)

    def test_citizenship_and_clearance(self):
        for text in [
            "Must be a U.S. citizen.",
            "U.S. citizenship is required for this position.",
            "Applicants must be able to obtain and maintain a Secret security clearance.",
            "Active TS/SCI clearance required.",
            "Due to ITAR, candidates must be U.S. persons.",
        ]:
            self.assertEqual(self.verdict(text), visa.CITIZEN, text)

    def test_offers(self):
        for text in ["Visa sponsorship is available for this role.", "We offer visa sponsorship.",
                     "We are open to sponsoring candidates."]:
            self.assertEqual(self.verdict(text), visa.OFFERS, text)

    def test_says_nothing(self):
        for text in [
            "", None, "Build services in Python. Summer 2027, 12 weeks.",
            # Equal-opportunity boilerplate names citizenship without requiring it.
            "We do not discriminate on the basis of race, religion, national origin or U.S. citizenship status.",
            "U.S. citizenship is not required.",
            "Ability to obtain a security clearance is a plus.",
            "We offer sponsorship for professional certifications.",
            "Will you now or in the future require sponsorship?",  # an application question, not a policy
        ]:
            self.assertIsNone(self.verdict(text), text)

    def test_a_refusal_outweighs_a_general_offer(self):
        text = "We offer visa sponsorship for full-time roles.\nThis internship is not eligible for sponsorship."
        self.assertEqual(visa.detect(text), (visa.NO, "This internship is not eligible for sponsorship."))

    def test_leftover_entities_become_text(self):
        self.assertEqual(visa.detect("Great team.&#xa;&#xa;U.S. citizenship is required.&#xa;Apply"),
                         (visa.CITIZEN, "U.S. citizenship is required."))

    def test_quote_is_the_sentence(self):
        verdict, quote = visa.detect("About us. We build things. We cannot sponsor H-1B visas at this time. Apply now.")
        self.assertEqual(quote, "We cannot sponsor H-1B visas at this time.")


def row(id, *, sponsorship=None, regions=",US,", source="simplify", url=None, date_posted=None, **extra):
    import time
    now = int(time.time())
    return {"id": id, "source": source, "company": f"Co {id}", "title": "Software Intern", "url": url or f"https://x/{id}",
            "locations": extra.pop("locations", "Austin, TX"), "regions": regions, "category": "Software", "terms": ",", "degrees": ",",
            "sponsorship": sponsorship, "date_posted": date_posted or now, "first_seen": now, "active": 1, **extra}


class ListingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(db, "DB_PATH", Path(self.tmp.name) / "test.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        db.init()
        self.add(row("a", sponsorship="Other"),
                 row("b", sponsorship="Other", visa=visa.NO, visa_quote="We cannot sponsor visas.", visa_checked=1),
                 row("c", sponsorship=visa.MAYBE, source="zapply"),
                 row("s", sponsorship="Other", visa=visa.OFFERS, visa_quote="Visa sponsorship is available.", visa_checked=1),
                 row("d", sponsorship="U.S. Citizenship is Required"),
                 row("e", sponsorship=visa.MAYBE, source="zapply", visa=visa.CITIZEN,
                     visa_quote="Must be a U.S. citizen.", visa_checked=1),
                 row("f", regions=",CA,"))

    def add(self, *rows):
        with db.connect() as conn:
            for r in rows:
                conn.execute(f"INSERT INTO listings ({', '.join(r)}) VALUES ({', '.join('?' * len(r))})",
                             list(r.values()))

    def ids(self, **filters):
        return sorted(l["id"] for l in main.listings(**filters, offset=0, limit=50)["items"])

    def test_filter(self):
        self.assertEqual(self.ids(), list("abcdefs"))
        self.assertEqual(self.ids(sponsorship="offers"), ["s"])
        self.assertEqual(self.ids(sponsorship="likely"), ["c", "s"])  # with Zapply's estimate
        self.assertEqual(self.ids(sponsorship="open"), ["a", "c", "f", "s"])

    def test_the_posting_wins_and_says_where_it_came_from(self):
        items = {l["id"]: l for l in main.listings(offset=0, limit=50)["items"]}
        self.assertEqual(items["e"]["sponsorship"], visa.CITIZEN)
        self.assertEqual(items["e"]["sponsorship_note"], "The posting says: “Must be a U.S. citizen.”")
        self.assertEqual(items["c"]["sponsorship_note"], "Zapply's estimate, not a statement from the employer.")
        self.assertIsNone(items["a"]["sponsorship"])  # "Other" means unknown
        self.assertNotIn("visa", items["a"])

    def test_search_ignores_accents(self):
        self.add(row("m", locations="Montréal, Québec, Canada", regions=",CA,"))
        self.assertEqual(self.ids(q="montreal quebec"), ["m"])
        self.assertEqual(self.ids(q="MONTRÉAL"), ["m"])

    def test_meta_counts(self):
        counts = {c["value"]: c["count"] for c in main.meta()["sponsorship"]}
        self.assertEqual(counts, {None: 2, visa.NO: 1, visa.MAYBE: 1, visa.OFFERS: 1, visa.CITIZEN: 2})

    def test_check_reads_us_postings_once(self):
        self.add(row("g", url="https://job-boards.greenhouse.io/acme/jobs/123"))
        texts = {"g": "We are unable to sponsor visas.", "a": None}
        with mock.patch.object(postings, "api_text", side_effect=lambda l, cache: texts.get(l["id"])) as read:
            result = visa.check_pending()
            self.assertEqual(result["checked"], 4)  # a, c, d, g: US and not read yet; f is in Canada
            self.assertEqual(visa.check_pending()["checked"], 0)
        self.assertEqual(read.call_count, 4)
        with db.connect() as conn:
            got = conn.execute("SELECT visa, visa_quote FROM listings WHERE id = 'g'").fetchone()
        self.assertEqual(tuple(got), (visa.NO, "We are unable to sponsor visas."))

    def test_zapply_links_are_followed_to_the_posting(self):
        self.add(row("z", source="zapply", sponsorship=visa.MAYBE, url="https://zapply.jobs/l/d/workday-acme-ext-R1?s=gh"))
        seen = []
        with mock.patch.object(postings, "_resolve", return_value="https://acme.wd5.myworkdayjobs.com/Ext/job/X/Intern_R1"), \
                mock.patch.object(postings, "_get_json", side_effect=lambda url: seen.append(url) or {
                    "jobPostingInfo": {"jobDescription": "<p>We cannot sponsor visas.</p>"}}):
            self.assertEqual(postings.api_text({"id": "z", "url": "https://zapply.jobs/l/d/workday-acme-ext-R1?s=gh",
                                                "posting_key": None, "board": None}), "We cannot sponsor visas.")
        self.assertEqual(seen, ["https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/ext/job/X/Intern_R1"])

    def test_network_errors_are_retried(self):
        with mock.patch.object(postings, "api_text", side_effect=TimeoutError):
            self.assertEqual(visa.check_pending()["failed"], 3)
        with mock.patch.object(postings, "api_text", return_value=None):
            self.assertEqual(visa.check_pending()["checked"], 3)


if __name__ == "__main__":
    unittest.main()
