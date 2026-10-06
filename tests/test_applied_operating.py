import copy
import unittest
from unittest.mock import patch

from equitylab import applied_operating as applied
from equitylab.operating_model import calculate
from equitylab.pipeline import load_latest


class AppliedOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        snapshot = load_latest()
        cls.company = next(c for c in snapshot["companies"] if c["id"] == "AMAT")
        cls.model = applied.build(copy.deepcopy(cls.company), snapshot["asOf"])

    def test_cash_is_reconciled_in_each_original_period(self):
        b = self.model["bridge"]
        self.assertEqual(
            [p["reportedCfo"] for p in b["periods"]], [7958e6, 5568e6, 5130e6]
        )
        self.assertEqual(b["reportedCfo"], 8396e6)
        self.assertEqual(sum(p["value"] for p in b["parts"]), 8396e6)
        self.assertTrue(
            all(
                p["residual"] == p["incomeResidual"] == p["revenueResidual"] == 0
                for p in b["periods"]
            )
        )

    def test_recast_changes_segment_allocation_not_consolidated_growth(self):
        rows = self.model["anchors"]["recastSegments"]
        self.assertEqual(
            [r["reportedAnnualRevenue"]["value"] for r in rows],
            [20798e6, 6385e6, 1185e6],
        )
        self.assertEqual([r["annualRevenue"] for r in rows], [21441e6, 5742e6, 1185e6])
        self.assertEqual(
            [r["reportedAnnualOperatingIncome"]["value"] for r in rows],
            [7379e6, 1792e6, -882e6],
        )
        self.assertEqual(
            [r["annualOperatingIncome"] for r in rows], [6909e6, 1547e6, -167e6]
        )
        for old, new in [
            ("reportedAnnualRevenue", "annualRevenue"),
            ("reportedAnnualOperatingIncome", "annualOperatingIncome"),
        ]:
            self.assertEqual(
                sum(r[old]["value"] for r in rows), sum(r[new] for r in rows)
            )
        self.assertTrue(all(r["sourceUrl"].endswith("#page=23") for r in rows))

    def test_recast_quarters_match_current_comparatives_before_trailing_sum(self):
        m = self.model
        self.assertEqual(m["sourcePeriod"], ["2025-07-28", "2026-07-26"])
        self.assertEqual(
            [s["revenue"] for s in m["segments"]], [23025e6, 6511e6, 1301e6]
        )
        self.assertAlmostEqual(
            m["initial"]["years"][0]["operatingIncome"], 9141e6, delta=0.01
        )
        wrong = copy.deepcopy(applied.SEGMENTS)
        wrong[0][2][0] -= 100
        with patch.object(applied, "SEGMENTS", wrong):
            with self.assertRaisesRegex(ValueError, "quarter sum"):
                applied.build(copy.deepcopy(self.company), "2026-09-29")

    def test_finance_lease_unknown_is_not_the_annual_reported_zero(self):
        a = self.model["anchors"]
        self.assertIsNone(a["actualFinanceLeasePrincipal"])
        self.assertEqual(a["annualFinanceLeasePrincipal"], 0)
        self.assertEqual(a["annualFinanceLeaseEvidence"]["end"], "2025-10-26")
        self.assertEqual(
            a["annualFinanceLeaseEvidence"]["sourceHash"], applied.ANNUAL_SHA
        )

    def test_cash_statement_adjustments_differ_from_expenses(self):
        m = self.model
        f = m["facts"]
        self.assertEqual(f["restructuring"]["components"][0]["fact"]["value"], 179e6)
        self.assertEqual(f["sbc"]["components"][0]["fact"]["value"], 668e6)
        self.assertEqual(m["anchors"]["workingCashEffect"], -2340e6)
        self.assertEqual(f["capex"]["value"], 2773e6)
        self.assertAlmostEqual(m["initial"]["years"][0]["cash"], 5067820000, delta=0.01)

    def test_investment_and_lease_assumptions_change_cash_without_duplicate_settlement(
        self,
    ):
        m = self.model
        a = copy.deepcopy(m["defaults"])
        a["leaseStart"] = a["leaseEnd"] = 0.01
        result = calculate(m, a)
        self.assertAlmostEqual(
            m["initial"]["years"][0]["cash"] - result["years"][0]["cash"],
            308.37e6,
            delta=0.01,
        )
        self.assertEqual(
            result["years"][0]["operatingIncome"],
            m["initial"]["years"][0]["operatingIncome"],
        )
        self.assertEqual(
            m["anchors"]["legalSettlementExpense"], m["anchors"]["legalSettlementPaid"]
        )

    def test_wrong_deferred_tax_sign_and_changed_source_fail(self):
        original = applied.select

        def changed(rows, tag, start, end, *args):
            r = original(rows, tag, start, end, *args)
            return (
                dict(r, value=-r["value"])
                if r and tag == "IncreaseDecreaseInDeferredIncomeTaxes"
                else r
            )

        with patch.object(applied, "select", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "reconciliation failed"):
                applied.build(copy.deepcopy(self.company), "2026-09-29")
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(
            applied.build(c, "2026-09-29")["status"], "source_review_required"
        )


if __name__ == "__main__":
    unittest.main()
