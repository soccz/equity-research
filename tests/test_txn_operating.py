import copy
import unittest
from equitylab import txn_operating as candidate
from equitylab.operating_model import calculate
from equitylab.pipeline import load_latest


class TiOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = copy.deepcopy(
            next(c for c in load_latest()["companies"] if c["id"] == "TXN")
        )
        cls.m = candidate.build(cls.company, "2026-09-29")

    def test_all_three_period_cash_and_business_totals_reconcile(self):
        m = self.m
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [7153000000, 4223000000, 2709000000],
        )
        self.assertEqual(sum(x["value"] for x in m["bridge"]["parts"]), 8667000000)
        self.assertTrue(
            all(
                p["residual"] == p["revenueResidual"] == p["incomeResidual"] == 0
                for p in m["bridge"]["periods"]
            )
        )
        self.assertEqual(
            [s["evidence"][1]["value"] for s in m["segments"]],
            [6511000000, 469000000, 274000000],
        )

    def test_member_names_and_software_tags_are_source_period_specific(self):
        m = self.m
        parts = m["segments"][0]["evidence"][0]["components"]
        self.assertEqual(parts[0]["fact"]["dimensions"][0][1], "AnalogMember")
        self.assertEqual(parts[1]["fact"]["dimensions"][0][1], "AnalogSegmentMember")
        tags = [
            p["fact"]["tag"] for p in m["facts"]["softwareAmortization"]["components"]
        ]
        self.assertEqual(
            tags,
            [
                "CapitalizedComputerSoftwareAmortization1",
                "AmortizationOfIntangibleAssets",
                "AmortizationOfIntangibleAssets",
            ],
        )
        self.assertEqual(m["facts"]["softwareAmortization"]["value"], 82000000)
        self.assertIn(
            "Amortization of capitalized software",
            next(p["text"] for p in m["passages"] if p["id"] == "1e3d1680399b74d24a2c"),
        )

    def test_itc_tax_cash_is_already_in_cfo_and_must_not_be_added_twice(self):
        e = self.m["incentiveEvidence"]
        self.assertEqual(e["taxCredit"], 433000000)
        self.assertEqual(e["incentives"], 1179000000)
        self.assertEqual(e["issuerFreeCash"], 6534000000)
        self.assertEqual(e["withoutChips"], 4922000000)
        self.assertEqual(
            e["issuerFreeCash"] - e["withoutChips"], e["taxCredit"] + e["incentives"]
        )
        self.assertEqual(e["periods"][1]["issuerFreeCash"], 4137000000)
        self.assertEqual(e["periods"][1]["withoutChips"], 2732000000)

    def test_assets_and_depreciation_do_not_repeat_the_annual_grant_benefit(self):
        m = self.m
        self.assertEqual(m["incentiveEvidence"]["annualDepreciationBenefit"], 353000000)
        self.assertEqual(m["facts"]["depreciation"]["value"], 2122000000)
        self.assertAlmostEqual(m["defaults"]["depreciation"], 2204000000 / 19453000000)
        self.assertAlmostEqual(m["defaults"]["capexStart"], 3345000000 / 19453000000)
        self.assertAlmostEqual(m["initial"]["years"][0]["cash"], 3876500000)
        self.assertEqual(m["defaults"]["tax"], 0.25)

    def test_interest_cost_is_a_negative_cash_effect_not_income(self):
        m = self.m
        self.assertEqual(m["facts"]["interest"]["value"], 564000000)
        self.assertLess(m["defaults"]["netInterest"], 0)
        self.assertAlmostEqual(m["initial"]["years"][0]["netInterest"], -564000000)
        a = copy.deepcopy(m["defaults"])
        a["netInterest"] = 0
        self.assertAlmostEqual(
            calculate(m, a)["years"][0]["cash"] - m["initial"]["years"][0]["cash"],
            564000000 * 0.75,
        )

    def test_incentive_receivables_are_not_repeating_working_capital(self):
        a = self.m["anchors"]
        self.assertEqual(a["workingStockNet"], 6445000000)
        self.assertEqual(len(a["workingStockTerms"]), 3)
        self.assertEqual(
            [p["fact"]["value"] for p in a["workingStockTerms"]],
            [2520000000, 4605000000, 680000000],
        )
        self.assertIsNone(a["actualFinanceLeasePrincipal"])

    def test_reinvestment_change_does_not_rewrite_historical_chips_receipts(self):
        m = self.m
        a = copy.deepcopy(m["defaults"])
        a["capexEnd"] = 0.10
        self.assertGreater(
            calculate(m, a)["terminal"]["cash"], m["initial"]["terminal"]["cash"]
        )
        self.assertEqual(m["incentiveEvidence"]["incentives"], 1179000000)
        self.assertEqual(m["bridge"]["reportedCfo"], 8667000000)

    def test_current_source_scope_and_publication_date_are_required(self):
        c = copy.deepcopy(self.company)
        c["narrative"]["accession"] = "new"
        self.assertEqual(
            candidate.build(c, "2026-09-29")["status"], "source_review_required"
        )
        with self.assertRaises(ValueError):
            candidate.build(copy.deepcopy(self.company), "2026-01-01")


if __name__ == "__main__":
    unittest.main(verbosity=2)
