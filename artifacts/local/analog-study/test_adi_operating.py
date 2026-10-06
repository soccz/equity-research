import copy
import unittest
from equitylab import adi_operating as candidate
from equitylab.operating_model import calculate
from equitylab.pipeline import load_latest


class AdiOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = copy.deepcopy(
            next(c for c in load_latest()["companies"] if c["id"] == "ADI")
        )
        cls.m = candidate.build(cls.c, "2026-09-29")

    def test_three_exact_cash_and_profit_periods_reconcile(self):
        m = self.m
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [4812202000, 3844515000, 3111392000],
        )
        self.assertEqual(m["bridge"]["reportedCfo"], 5545325000)
        self.assertEqual(sum(p["value"] for p in m["bridge"]["parts"]), 5545325000)
        self.assertEqual(m["facts"]["operatingIncome"]["value"], 4934886000)
        self.assertTrue(
            all(
                p["residual"] == p["incomeResidual"] == 0
                for p in m["bridge"]["periods"]
            )
        )

    def test_market_sales_are_not_fictitious_independent_profit_segments(self):
        m = self.m
        self.assertEqual(len(m["segments"]), 1)
        rows = m["analogEvidence"]["markets"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(sum(x["current"]["value"] for x in rows), 10805627000)
        self.assertEqual(sum(x["previous"]["value"] for x in rows), 7943590000)
        self.assertTrue(all(x["operatingMargin"] is None for x in rows))
        self.assertTrue(all(x["current"]["start"] == "2025-11-02" for x in rows))

    def test_interim_working_cash_stays_aggregate_while_annual_details_are_preserved(
        self,
    ):
        ps = self.m["bridge"]["periods"]
        self.assertEqual([len(p["workingParts"]) for p in ps], [7, 1, 1])
        self.assertEqual(
            [p["workingCash"] for p in ps], [481009000, -940740000, -8008000]
        )
        self.assertEqual(self.m["analogEvidence"]["workingCash"], -451723000)
        self.assertEqual(ps[1]["workingParts"][0]["fact"]["value"], 940740000)
        self.assertEqual(ps[1]["parts"][-1]["value"], -19377000)

    def test_amortization_uses_cash_statement_precision_and_is_added_once(self):
        m = self.m
        self.assertEqual(m["analogEvidence"]["annualAmortization"]["value"], 1592044000)
        self.assertEqual(m["analogEvidence"]["annualAmortization"]["decimals"], "-3")
        self.assertAlmostEqual(m["defaults"]["depreciation"], 1970999000 / 13881744000)
        self.assertAlmostEqual(m["initial"]["years"][0]["cash"], 3222570750)
        self.assertEqual(m["facts"]["amortization"]["value"], 1550223000)

    def test_acquisition_sensitivity_retains_other_investment_and_gaap_costs(self):
        m = self.m
        a = copy.deepcopy(m["defaults"])
        a["capexStart"] = a["capexEnd"] = m["analogEvidence"][
            "reinvestmentExcludingAcquisitionRatio"
        ]
        result = calculate(m, a)
        self.assertAlmostEqual(
            result["years"][0]["cash"] - m["initial"]["years"][0]["cash"], 1536049000
        )
        self.assertEqual(m["facts"]["special"]["value"], 23766000)
        self.assertEqual(m["facts"]["otherInvesting"]["value"], 42577000)
        self.assertEqual(a["sellingStart"], m["defaults"]["sellingStart"])

    def test_interest_expense_reduces_cash_once_after_assumed_tax(self):
        m = self.m
        self.assertLess(m["defaults"]["netInterest"], 0)
        self.assertAlmostEqual(m["initial"]["years"][0]["netInterest"], -350849000)
        a = copy.deepcopy(m["defaults"])
        a["netInterest"] = 0
        self.assertAlmostEqual(
            calculate(m, a)["years"][0]["cash"] - m["initial"]["years"][0]["cash"],
            350849000 * 0.75,
        )

    def test_sale_note_mda_difference_is_not_silently_normalized(self):
        e = self.m["analogEvidence"]
        self.assertEqual(
            (e["saleGainNote"], e["saleGainMda"], e["saleGainDifference"]),
            (24200000, 24400000, 200000),
        )
        self.assertEqual(self.m["anchors"]["workingStockNet"], 3638906000)
        self.assertIsNone(self.m["anchors"]["actualFinanceLeasePrincipal"])

    def test_new_filings_and_early_dates_need_a_new_review(self):
        c = copy.deepcopy(self.c)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(
            candidate.build(c, "2026-09-29")["status"], "source_review_required"
        )
        with self.assertRaises(ValueError):
            candidate.build(copy.deepcopy(self.c), "2025-11-24")


if __name__ == "__main__":
    unittest.main(verbosity=2)
