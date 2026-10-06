import copy
import unittest
from unittest.mock import patch
from equitylab import alphabet_capital as capital
from equitylab.pipeline import load_latest
from equitylab.xbrl import company_filing
from equitylab.valuation import share_scope


class AlphabetCapitalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_latest()
        cls.company = next(c for c in cls.snapshot["companies"] if c["id"] == "GOOGL")
        cls.review = capital.build(copy.deepcopy(cls.company))

    def test_unadjusted_conversion_at_both_breakpoints(self):
        for t in self.review["terms"]:
            for price in [150, t["initialPrice"] - 0.01]:
                self.assertEqual(capital.conversion(t, price), t["maximumRate"])
            for price in [700, t["thresholdPrice"] + 0.01]:
                self.assertEqual(capital.conversion(t, price), t["minimumRate"])
            self.assertEqual(capital.conversion(t, 400), 2.5)
            self.assertEqual(capital.conversion(t, t["initialPrice"]), t["maximumRate"])
            self.assertEqual(
                capital.conversion(t, t["thresholdPrice"]), t["minimumRate"]
            )

    def test_stock_classes_are_not_interchangeable(self):
        a, b = self.review["terms"]
        self.assertEqual([a["commonClass"], b["commonClass"]], ["A", "C"])
        self.assertNotEqual(capital.conversion(a, 440), capital.conversion(b, 440))
        self.assertTrue(all(t["currentOutstandingExact"] is None for t in [a, b]))
        self.assertEqual(a["annualDividendPerPreferred"], 62.5)
        self.assertIn("실제 현금 유출", self.review["dividendScope"])

    def test_nonfinite_nonpositive_and_boolean_prices_rejected(self):
        for p in [0, -1, float("nan"), float("inf"), True, "400"]:
            with self.assertRaises(ValueError):
                capital.conversion(self.review["terms"][0], p)

    def test_contract_review_does_not_release_price_hold(self):
        c = copy.deepcopy(self.company)
        _, rows = company_filing(c, self.snapshot["asOf"])
        scope = share_scope(c, rows)
        self.assertEqual(scope["status"], "unresolved")
        self.assertIsNone(scope["marketCapProxy"])
        self.assertEqual(
            scope["capitalReview"]["evidenceHash"], self.review["evidenceHash"]
        )
        self.assertFalse(scope["capitalReview"]["financialApproval"])
        self.assertTrue(any("우선주" in x for x in scope["issues"]))

    def test_new_current_filing_never_inherits_old_rights(self):
        c = copy.deepcopy(self.company)
        c["financials"]["current"]["cfo"]["accession"] = "new"
        self.assertIsNone(capital.build(c))
        c = copy.deepcopy(self.company)
        c["priceSummary"]["lastDate"] = "2026-01-01"
        self.assertIsNone(capital.build(c))

    def test_contract_mutation_fails_instead_of_using_default_terms(self):
        original = capital.extract

        def changed(blob):
            rows = original(blob)
            for r in rows:
                r["text"] = r["text"].replace("$62.50", "$63.50")
            return rows

        with patch.object(capital, "extract", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "terms differ"):
                capital.build(copy.deepcopy(self.company))

    def test_both_exhibits_and_current_filing_are_archived_for_replay(self):
        c = copy.deepcopy(self.company)
        capital.build(c)
        hashes = {s["sha256"] for s in c["sources"]}
        self.assertTrue(
            {capital.CURRENT_HASH, *[t[3] for t in capital.TERMS]}.issubset(hashes)
        )
