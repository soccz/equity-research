import unittest, copy
from equitylab.operating_model import calculate

from equitylab import qualcomm_operating as candidate
from equitylab.pipeline import load_latest


class QualcommOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = next(c for c in load_latest()["companies"] if c["id"] == "QCOM")
        cls.model = candidate.build(copy.deepcopy(cls.company), "2026-09-29")

    def test_three_period_cash_reconciles_with_actual_other_item_sign(self):
        m = self.model
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [14012000000, 8405000000, 10016000000],
        )
        self.assertEqual(m["bridge"]["reportedCfo"], 12401000000)
        self.assertEqual(m["bridge"]["periods"][0]["parts"][6]["value"], -57000000)
        for part in m["bridge"]["parts"]:
            self.assertEqual(
                part["value"],
                sum(
                    x["coefficient"] * x["fact"]["value"]
                    for x in part["fact"]["components"]
                ),
            )

    def test_period_tax_benefit_is_not_future_tax_rate(self):
        e = self.model["qualcommEvidence"]
        p = e["periods"][1]
        self.assertEqual(p["reportedPretax"], 8241000000)
        self.assertEqual(p["tax"], -4136000000)
        self.assertEqual(p["netIncome"], 12377000000)
        self.assertEqual(p["taxCashAdjustment"], -5550000000)
        self.assertEqual(self.model["defaults"]["tax"], 0.25)

    def test_chips_licensing_and_nonreportable_segments_are_different(self):
        s = self.model["segments"]
        self.assertEqual(
            [x["revenue"] for x in s], [38014000000, 5662000000, 393000000]
        )
        self.assertEqual(
            [x["evidence"][1]["value"] for x in s],
            [10855000000, 4120000000, -443000000],
        )
        self.assertLess(s[-1]["margin"], -1)
        self.assertEqual(self.model["marginLabel"], "세전이익률")

    def test_investment_gains_excluded_but_qsi_cost_retained(self):
        m = self.model
        e = m["qualcommEvidence"]
        self.assertEqual(e["reportedPretax"], 11212000000)
        self.assertEqual(e["excludedQsiInvestment"]["value"], 930000000)
        self.assertEqual(e["excludedUnallocatedInvestment"]["value"], 744000000)
        self.assertEqual(e["qsiOperatingCost"]["value"], 12000000)
        self.assertEqual(e["researchPretax"], 9538000000)
        self.assertEqual(e["reportedOperatingAfterInterest"], 9530000000)
        self.assertEqual(e["remainingAllocatedDifference"], 8000000)
        self.assertAlmostEqual(m["initial"]["years"][0]["pretaxIncome"], 9538000000)
        self.assertNotIn("operatingIncome", m["initial"]["years"][0])

    def test_historical_licensing_settlement_is_not_deleted(self):
        f = self.model["qualcommEvidence"]["unallocatedRevenue"]
        self.assertEqual(
            [x["fact"]["value"] for x in f["components"]], [143000000, 0, 143000000]
        )
        self.assertEqual(f["value"], 0)

    def test_investment_scope_and_missing_lease_are_explicit(self):
        m = self.model
        self.assertAlmostEqual(m["initial"]["years"][0]["cash"], 5136500000)
        self.assertEqual(m["facts"]["acquisitionAndInvestments"]["value"], 1605000000)
        self.assertIsNone(m["anchors"]["actualFinanceLeasePayment"])
        self.assertEqual(m["anchors"]["workingStockNet"], 9789000000)
        a = copy.deepcopy(m["defaults"])
        a["netInterest"] = 0.01
        with self.assertRaises(ValueError):
            calculate(m, a)

    def test_changed_source_and_early_dates_require_review(self):
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "new"
        self.assertEqual(
            candidate.build(c, "2026-09-29")["status"], "source_review_required"
        )
        with self.assertRaises((ValueError, TypeError)):
            candidate.build(self.company, "2026-07-28")


if __name__ == "__main__":
    unittest.main()
