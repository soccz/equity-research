import copy
import unittest
from equitylab import walmart_operating as candidate
from equitylab.operating_model import calculate
from equitylab.pipeline import load_latest


class WalmartOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = copy.deepcopy(
            next(c for c in load_latest()["companies"] if c["id"] == "WMT")
        )
        cls.m = candidate.build(cls.c, "2026-09-29")

    def test_three_cash_bridges_start_with_consolidated_income(self):
        m = self.m
        self.assertEqual(m["sourcePeriod"], ["2025-08-01", "2026-07-31"])
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [41565000000, 19710000000, 18352000000],
        )
        self.assertEqual(m["bridge"]["reportedCfo"], 42923000000)
        self.assertEqual(m["bridge"]["periods"][1]["parts"][0]["value"], 12019000000)
        for p in m["bridge"]["periods"]:
            self.assertEqual(sum(r["value"] for r in p["parts"]), p["reportedCfo"])
        self.assertEqual(m["bridge"]["periods"][0]["parts"][1]["value"], 14203000000)
        self.assertEqual(m["bridge"]["periods"][0]["parts"][3]["value"], 2277000000)

    def test_corporate_income_and_costs_reconcile_without_a_fake_segment_margin(self):
        e = self.m["retailerEvidence"]
        p = e["periods"][1]
        self.assertEqual(len(e["geographies"]), 3)
        self.assertEqual(len(self.m["segments"]), 1)
        self.assertEqual(p["corporateIncome"], 49000000)
        self.assertEqual(p["corporateCosts"], 1583000000)
        self.assertEqual(p["segmentRevenue"] + p["corporateIncome"], 365688000000)
        self.assertAlmostEqual(
            self.m["initial"]["years"][0]["operatingIncome"], 32280000000, places=3
        )

    def test_tariff_refund_removal_is_gross_sensitivity_not_normalized_profit(self):
        e = self.m["retailerEvidence"]
        self.assertEqual(e["tariffRefundApprox"], 2900000000)
        self.assertEqual(e["profitExcludingGrossRefund"], 13976000000)
        self.assertIsNone(e["refundUseQuantified"])
        self.assertIn("정상 영업이익이 아닙니다", e["refundScope"])
        a = copy.deepcopy(self.m["defaults"])
        a["segments"][0]["marginEnd"] -= (
            2900000000 / self.m["facts"]["revenue"]["value"]
        )
        changed = calculate(self.m, a)
        self.assertAlmostEqual(
            self.m["initial"]["years"][4]["cash"] - changed["years"][4]["cash"],
            2900000000 * 0.75,
            places=3,
        )
        self.assertIsNone(changed["price"])

    def test_membership_and_other_is_not_pure_membership(self):
        e = self.m["retailerEvidence"]
        self.assertEqual(e["annualMembershipApprox"], 4400000000)
        self.assertEqual(e["annualMembershipOther"]["value"], 6750000000)
        self.assertIsNone(e["actualTrailingMembership"])
        self.assertEqual(self.m["facts"]["membershipOther"]["value"], 7374000000)

    def test_annual_lease_proxy_preserves_unresolved_interest_scope(self):
        m = self.m
        e = m["retailerEvidence"]
        self.assertEqual(e["annualFinanceInterestFace"]["value"], 481000000)
        self.assertEqual(e["annualFinanceInterestNote"]["value"], 383000000)
        self.assertEqual(e["annualFinanceInterestDifference"], 98000000)
        self.assertIsNone(e["actualTrailingFinancePrincipal"])
        self.assertEqual(e["otherFinancing"]["value"], -3249000000)
        self.assertAlmostEqual(m["defaults"]["leaseStart"], 891000000 / 713163000000)
        self.assertEqual(e["annualLeaseTimingDifference"], 119000000)
        self.assertIsNone(m["initial"]["price"])
        self.assertIsNone(m["initial"]["requiredTerminalCash"])

    def test_depreciation_contains_finance_assets_and_interest_is_a_cost(self):
        m = self.m
        self.assertAlmostEqual(
            m["defaults"]["depreciation"], 15093000000 / 735840000000
        )
        a = copy.deepcopy(m["defaults"])
        a["netInterest"] = 0
        self.assertAlmostEqual(
            calculate(m, a)["years"][0]["cash"] - m["initial"]["years"][0]["cash"],
            2003000000 * 0.75,
            places=3,
        )
        self.assertIsNone(m["retailerEvidence"]["actualTrailingSbc"])
        self.assertEqual(m["retailerEvidence"]["annualSbc"]["value"], 3603000000)

    def test_reinvestment_and_working_capital_keep_their_scopes(self):
        m = self.m
        e = m["retailerEvidence"]
        self.assertEqual(e["workingStockNet"], 8357000000)
        self.assertIsNone(e["actualTrailingAcquisitions"])
        self.assertAlmostEqual(
            m["defaults"]["capexStart"],
            (29414000000 + 331000000) / 735840000000 + 53000000 / 713163000000,
        )
        self.assertAlmostEqual(
            m["initial"]["years"][0]["cash"], 6658732895.915821, places=3
        )

    def test_new_source_or_past_date_does_not_inherit_approval(self):
        c = copy.deepcopy(self.c)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(
            candidate.build(c, "2026-09-29")["status"], "source_review_required"
        )
        with self.assertRaises(ValueError):
            candidate.build(copy.deepcopy(self.c), "2026-08-27")
        self.assertNotEqual(self.m["security"], self.c["valuation"]["security"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
