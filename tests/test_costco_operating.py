import copy
import unittest
from equitylab import costco_operating as candidate
from equitylab.operating_model import calculate
from equitylab.pipeline import load_latest


class CostcoOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = copy.deepcopy(
            next(c for c in load_latest()["companies"] if c["id"] == "COST")
        )
        cls.m = candidate.build(cls.c, "2026-09-29")

    def test_52_week_cash_and_all_36_week_components_reconcile(self):
        m = self.m
        self.assertEqual(m["sourcePeriod"], ["2025-05-12", "2026-05-10"])
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [13335000000, 11133000000, 9468000000],
        )
        self.assertEqual(m["bridge"]["reportedCfo"], 15000000000)
        self.assertTrue(
            all(
                sum(x["value"] for x in p["parts"]) == p["reportedCfo"]
                for p in m["bridge"]["periods"]
            )
        )
        self.assertEqual(m["bridge"]["periods"][0]["parts"][4]["value"], -117000000)
        self.assertEqual(m["bridge"]["periods"][1]["parts"][4]["value"], 36000000)

    def test_membership_is_inside_segment_revenue_not_free_extra_profit(self):
        m = self.m
        self.assertEqual(sum(s["revenue"] for s in m["segments"]), 293587000000)
        self.assertAlmostEqual(
            sum(s["revenue"] * s["margin"] for s in m["segments"]),
            11225000000,
            places=3,
        )
        self.assertEqual(m["retailEvidence"]["membership"]["value"], 5781000000)
        self.assertEqual(
            m["retailEvidence"]["membership"]["value"]
            + m["retailEvidence"]["merchandise"]["value"],
            293587000000,
        )
        self.assertEqual(len(m["segments"]), 3)

    def test_renewal_window_is_not_a_forward_probability(self):
        e = self.m["retailEvidence"]
        self.assertEqual(e["renewalWindowMonths"], [7, 18])
        self.assertIsNone(e["renewalFutureProbability"])
        self.assertEqual(e["deferredMembership"]["value"], 3157000000)
        self.assertEqual(e["deferredMembership"]["end"], "2026-05-10")

    def test_retail_balance_proxy_preserves_supplier_and_fee_funding(self):
        m = self.m
        self.assertEqual(
            [r["fact"]["value"] for r in m["anchors"]["workingStockTerms"]],
            [3750000000, 19418000000, 22363000000, 3157000000],
        )
        self.assertEqual(m["anchors"]["workingStockNet"], -2352000000)
        self.assertLess(m["defaults"]["workingCapital"], 0)
        self.assertIn("재보험", m["anchors"]["workingStockTerms"][0]["label"])

    def test_annual_finance_amort_proxy_does_not_add_all_lease_cost(self):
        m = self.m
        e = m["retailEvidence"]
        self.assertEqual(e["annualFinanceAmortization"]["value"], 102000000)
        self.assertEqual(e["annualFinanceAmortization"]["end"], "2025-08-31")
        self.assertIsNone(e["actualTrailingFinanceAmortization"])
        self.assertAlmostEqual(
            m["defaults"]["depreciation"],
            2565000000 / 293587000000 + 102000000 / 275235000000,
        )
        self.assertEqual(m["facts"]["leaseNoncash"]["value"], 316000000)
        self.assertEqual(e["annualLeaseTimingDifference"], 16000000)
        self.assertAlmostEqual(
            m["initial"]["years"][0]["cash"], 4703051111.777208, places=3
        )

    def test_interest_and_finance_principal_reduce_cash_once(self):
        m = self.m
        a = copy.deepcopy(m["defaults"])
        a["netInterest"] = 0
        self.assertAlmostEqual(
            calculate(m, a)["years"][0]["cash"] - m["initial"]["years"][0]["cash"],
            146000000 * 0.75,
            places=3,
        )
        a = copy.deepcopy(m["defaults"])
        a["leaseStart"] = a["leaseEnd"] = 0
        self.assertAlmostEqual(
            calculate(m, a)["years"][0]["cash"] - m["initial"]["years"][0]["cash"],
            86000000,
            places=3,
        )

    def test_investment_and_share_compensation_are_not_extra_cash_rewards(self):
        m = self.m
        self.assertEqual(m["facts"]["capex"]["value"], 6194000000)
        self.assertAlmostEqual(m["defaults"]["capexStart"], 6194000000 / 293587000000)
        self.assertEqual(m["facts"]["otherInvesting"]["value"], -102000000)
        self.assertEqual(m["anchors"]["shareCompensationReplacement"], 911000000)

    def test_new_filing_or_early_date_cannot_reuse_review(self):
        c = copy.deepcopy(self.c)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(
            candidate.build(c, "2026-09-29")["status"], "source_review_required"
        )
        with self.assertRaises(ValueError):
            candidate.build(copy.deepcopy(self.c), "2026-06-02")


if __name__ == "__main__":
    unittest.main(verbosity=2)
