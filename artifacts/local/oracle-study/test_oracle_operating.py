import copy
import unittest

from equitylab import oracle_operating, operating_model
from equitylab.pipeline import load_latest


class OracleOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.c = copy.deepcopy(next(c for c in s["companies"] if c["id"] == "ORCL"))
        cls.as_of = s["asOf"]
        cls.m = oracle_operating.build(cls.c, cls.as_of)

    def test_each_period_and_three_segments_reconcile_before_trailing_combination(self):
        m = self.m
        self.assertEqual(len(m["segments"]), 3)
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [31977000000, 23103000000, 8140000000],
        )
        self.assertTrue(
            all(
                p["residual"] == p["revenueResidual"] == p["incomeResidual"] == 0
                for p in m["bridge"]["periods"]
            )
        )
        self.assertEqual(sum(s["revenue"] for s in m["segments"]), 71776000000)
        self.assertEqual(m["bridge"]["reportedCfo"], 46940000000)
        self.assertEqual(m["facts"]["operatingIncome"]["value"], 23057000000)
        self.assertEqual(m["anchors"]["reportedCorporateCost"], 16746000000)
        self.assertEqual(
            m["facts"]["cfo"]["components"][0]["fact"]["filedAt"], "2026-06-22"
        )

    def test_customer_financing_adjustment_is_not_gross_receipts_or_normal_cash(self):
        e = self.m["capacityEvidence"]
        self.assertEqual(e["financingPrepayments"]["value"], 15955000000)
        self.assertEqual(e["periods"][1]["financingPrepayments"], 11363000000)
        self.assertEqual(e["currentGrossPrepayments"], 11400000000)
        self.assertEqual(e["periods"][1]["cashWithoutFinancingAdjustment"], 11740000000)
        self.assertEqual(e["uncommencedLeases"], 288000000000)
        self.assertIsNone(self.m["bridge"]["cashAfterInvestmentLeaseSbc"])

    def test_finance_lease_total_less_accrued_interest_is_only_a_proxy(self):
        m = self.m
        self.assertEqual(m["facts"]["leaseCash"]["value"], 552000000)
        self.assertEqual(m["facts"]["leaseInterest"]["value"], 357000000)
        self.assertEqual(m["anchors"]["financeLeasePrincipalProxy"], 195000000)
        self.assertIsNone(m["anchors"]["actualFinanceLeasePayment"])
        first = m["initial"]["years"][0]
        self.assertAlmostEqual(first["leasePrincipal"], 195000000, places=4)
        self.assertAlmostEqual(first["netInterest"], -5104000000, places=4)
        self.assertIn("리스 발생이자 포함", m["netInterestLabel"])

    def test_capex_exceeding_revenue_is_not_clipped_or_converted_to_zero_value(self):
        m = self.m
        a = copy.deepcopy(m["defaults"])
        self.assertGreater(a["capexStart"], 1)
        self.assertEqual(m["initial"]["years"][0]["capex"], 75660000000)
        self.assertAlmostEqual(m["initial"]["years"][0]["cash"], -51737250000, places=3)
        self.assertIsNone(m["initial"]["equityValue"])
        a["capexStart"] = a["capexEnd"] = 1.5
        result = operating_model.calculate(m, a)
        self.assertAlmostEqual(result["years"][0]["capex"], 71776000000 * 1.5, places=3)
        self.assertLess(result["years"][0]["cash"], m["initial"]["years"][0]["cash"])
        a["capexEnd"] = 2.001
        with self.assertRaises(ValueError):
            operating_model.calculate(m, a)

    def test_missing_financing_balance_is_not_an_observed_zero_and_positive_path_still_holds_price(
        self,
    ):
        m = self.m
        self.assertIsNone(m["anchors"]["workingStockNet"])
        a = copy.deepcopy(m["defaults"])
        a["capexStart"] = a["capexEnd"] = 0.15
        result = operating_model.calculate(m, a)
        self.assertGreater(result["years"][0]["cash"], 0)
        self.assertIsNone(result["price"])
        self.assertIsNone(result["requiredTerminalCash"])
        self.assertEqual(m["security"]["status"], "unresolved")

    def test_expanded_capex_bound_does_not_expand_other_assumptions(self):
        m = self.m
        for key in ["depreciation", "leaseStart", "leaseEnd"]:
            a = copy.deepcopy(m["defaults"])
            a[key] = 1.01
            with self.assertRaises(ValueError):
                operating_model.calculate(m, a)
        for value in [True, 0, 4, float("inf")]:
            bad = dict(m, capexLimit=value)
            with self.assertRaises(ValueError):
                operating_model.calculate(bad, m["defaults"])

    def test_new_filing_requires_new_source_review(self):
        c = copy.deepcopy(self.c)
        c["narrative"]["accession"] = "future"
        self.assertEqual(
            oracle_operating.build(c, self.as_of)["status"], "source_review_required"
        )


if __name__ == "__main__":
    unittest.main()
