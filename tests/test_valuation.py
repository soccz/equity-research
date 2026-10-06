import copy
import math
import unittest
from equitylab.pipeline import load_latest
from equitylab.valuation import build, scenario, share_scope, implied_growth
from equitylab.dossier import price_requirements
from equitylab.xbrl import company_filing


class ValuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_latest()
        cls.companies = {c["id"]: c for c in cls.snapshot["companies"]}

    def test_cash_is_not_a_zero_price_when_negative(self):
        self.assertIsNone(scenario(100, 0.1, 0.2, 0.01, 0.05, 0.12, 10)["price"])
        self.assertAlmostEqual(
            scenario(100, 0.3, 0.1, 0.02, 0.05, 0.12, 10)["cash"], 18
        )
        for k in [0, 0.02, float("nan")]:
            with self.assertRaises(ValueError):
                scenario(100, 0.3, 0.1, 0.02, 0.05, k, 10)
        with self.assertRaises(ValueError):
            scenario(100, 0.3, 0.1, 0.02, 0.05, 0.12, True)

    def test_higher_burden_or_discount_reduces_conditional_price(self):
        base = scenario(100, 0.3, 0.1, 0.02, 0.05, 0.12, 10)["price"]
        self.assertLess(scenario(100, 0.3, 0.1, 0.04, 0.05, 0.12, 10)["price"], base)
        self.assertLess(scenario(100, 0.3, 0.1, 0.02, 0.05, 0.15, 10)["price"], base)
        self.assertGreater(scenario(100, 0.3, 0.1, 0.02, 0.1, 0.12, 10)["price"], base)

    def test_implied_growth_recovers_price_and_reports_unsolved_ranges(self):
        for horizon in [5, 10, 15, 20]:
            for growth in [-0.2, 0, 0.15, 0.7]:
                cash = price_requirements(1000, growth, 0.12, 0.03, horizon)[
                    "requiredBaseCash"
                ]
                result = implied_growth(1000, cash, 0.12, 0.03, horizon)
                self.assertEqual(result["status"], "solved")
                self.assertAlmostEqual(result["growth"], growth, places=11)
        self.assertEqual(implied_growth(1000, -1, 0.12)["status"], "nonpositive_cash")
        self.assertEqual(implied_growth(1e12, 1, 0.12)["status"], "above_range")

    def test_latest_header_shares_preserve_own_date(self):
        c = copy.deepcopy(self.companies["MSFT"])
        _, rows = company_filing(c, self.snapshot["asOf"])
        v = share_scope(c, rows)
        self.assertEqual(v["status"], "available")
        self.assertEqual(v["shares"]["value"], 7425545491)
        self.assertEqual(v["shares"]["end"], "2026-07-23")
        self.assertEqual(v["shareAgeDays"], 68)

    def test_issued_and_weighted_average_shares_are_not_substitutes(self):
        c = copy.deepcopy(self.companies["000660"])
        _, rows = company_filing(c, self.snapshot["asOf"])
        v = share_scope(c, rows)
        self.assertEqual(v["shares"]["value"], 711075500)
        rows = [r for r in rows if r["tag"] != "NumberOfSharesOutstanding"]
        v = share_scope(c, rows)
        self.assertIsNone(v["shares"])
        self.assertIsNone(v["marketCapProxy"])

    def test_multiclass_and_financial_subsidiaries_hold_price(self):
        for symbol in ["GOOGL", "005930", "005380", "GM", "F", "CAT", "030200"]:
            c = copy.deepcopy(self.companies[symbol])
            _, rows = company_filing(c, self.snapshot["asOf"])
            v = share_scope(c, rows)
            self.assertEqual(v["status"], "unresolved", symbol)
            self.assertIsNone(v["marketCapProxy"])
            self.assertTrue(v["issues"])

    def test_preferred_class_dimension_is_not_mistaken_for_no_preferred_stock(self):
        c = copy.deepcopy(self.companies["ORCL"])
        _, rows = company_filing(c, self.snapshot["asOf"])
        result = share_scope(c, rows)
        self.assertEqual(result["status"], "unresolved")
        self.assertIsNone(result["marketCapProxy"])
        self.assertEqual(result["preferredEvidence"][0]["value"], 50_000)
        self.assertIn(
            "MandatoryConvertible", result["preferredEvidence"][0]["dimensions"][0][1]
        )
        # Authorized capacity alone is not proof that preferred stock was issued.
        without_issued = [
            r for r in rows if r["tag"] != "PreferredStockSharesOutstanding"
        ]
        self.assertEqual(share_scope(c, without_issued)["status"], "available")

    def test_historical_anchors_do_not_overlap_and_missing_is_explicit(self):
        for original in self.companies.values():
            c = copy.deepcopy(original)
            v = build(c, self.snapshot["asOf"])
            self.assertEqual(v["status"], "workspace", c["id"])
            for recent, old in zip(v["history"], v["history"][1:]):
                self.assertLess(old["end"], recent["start"])
            self.assertEqual(
                v["defaults"]["burdenMargin"], sum(a["ratio"] for a in v["adjustments"])
            )
            self.assertTrue(all(a["id"] != "buybacks" for a in v["adjustments"]))
            for case in v["cases"]:
                self.assertTrue(math.isfinite(case["cash"]))
                if v["security"]["status"] != "available":
                    self.assertIsNone(case["price"])
            if c["id"] == "AAPL":
                self.assertIn("재무활동 리스 지급", v["unknownAdjustments"])


if __name__ == "__main__":
    unittest.main()
