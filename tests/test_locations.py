import unittest

from board.locations import classify, classify_all


class ClassifyTest(unittest.TestCase):
    def test_us(self):
        for loc in ["NYC", "SF", "LA", "San Jose, CA", "Austin, TX", "United States", "Utah", "Illinois",
                    "Washington, DC", "Boston, MA, USA", "South SF", "Carlsbad, Ca",
                    "Arlington County, Arlington, VA", "Long Island City, Queens, NY"]:
            self.assertEqual(classify(loc), {"US"}, loc)

    def test_canada(self):
        for loc in ["Toronto, ON, Canada", "Montreal, QC, Canada", "Waterloo, ON", "Canada", "Ontario"]:
            self.assertEqual(classify(loc), {"CA"}, loc)

    def test_ca_means_california_not_canada(self):
        self.assertEqual(classify("Palo Alto, CA"), {"US"})
        self.assertEqual(classify("Montreal, CA"), {"CA"})  # unless the city is Canadian
        self.assertEqual(classify("Toronto, ON, CA"), {"CA"})
        self.assertEqual(classify("Montréal, Quebec, CAN"), {"CA"})

    def test_montreal_as_company_boards_write_it(self):
        for loc in ["Montréal, Québec", "Montreal", "Montréal", "Montreal (St. Laurent)", "Montreal, QC (Hybrid)",
                    "Montréal, QC - Hybride", "Hybrid - Montreal", "Greater Montreal Area", "Laval, Québec",
                    "Quebec City", "Toronto"]:
            self.assertEqual(classify(loc), {"CA"}, loc)
        self.assertEqual(classify("Télétravail - Canada"), {"REMOTE", "CA"})
        self.assertEqual(classify("Seattle"), {"US"})
        for loc in ["London", "Waterloo", "Cambridge"]:  # more than one country has these
            self.assertEqual(classify(loc), set(), loc)

    def test_remote(self):
        self.assertEqual(classify("Remote"), {"REMOTE"})
        self.assertEqual(classify("Remote in USA"), {"REMOTE", "US"})
        self.assertEqual(classify("Remote in Canada"), {"REMOTE", "CA"})
        self.assertEqual(classify("Remote in UK"), set())
        self.assertEqual(classify("Remote in Germany"), set())

    def test_elsewhere(self):
        for loc in ["London, UK", "Berlin, Germany", "Bangalore, KA, India", "Paris, France"]:
            self.assertEqual(classify(loc), set(), loc)

    def test_multi(self):
        self.assertEqual(classify_all(["London, UK", "Toronto, ON, Canada", "NYC"]), {"US", "CA"})
        self.assertEqual(classify_all(["London, UK"]), set())


if __name__ == "__main__":
    unittest.main()
