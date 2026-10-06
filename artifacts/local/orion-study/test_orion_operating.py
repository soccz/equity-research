import copy
import unittest
from equitylab import orion_operating as candidate
from equitylab.operating_model import calculate
from equitylab.pipeline import load_latest


class OrionOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = copy.deepcopy(
            next(c for c in load_latest()["companies"] if c["id"] == "271560")
        )
        cls.m = candidate.build(cls.c, "2026-09-29")

    def test_exact_cash_bridge_preserves_all_three_periods(self):
        m = self.m
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [537328134910, 283530566965, 153541318575],
        )
        self.assertEqual(m["bridge"]["reportedCfo"], 667317383300)
        self.assertEqual(sum(p["value"] for p in m["bridge"]["parts"]), 667317383300)
        self.assertTrue(
            all(
                sum(x["value"] for x in p["parts"]) == p["reportedCfo"]
                for p in m["bridge"]["periods"]
            )
        )

    def test_geographies_use_same_half_year_and_not_fictitious_profits(self):
        m = self.m
        self.assertEqual(len(m["segments"]), 1)
        rows = m["confectioneryEvidence"]["geographies"]
        self.assertEqual(
            [r["current"]["value"] for r in rows],
            [555788380000, 778765787000, 489386847000],
        )
        self.assertEqual(
            [r["previous"]["value"] for r in rows],
            [549122816000, 631589207000, 398226751000],
        )
        self.assertTrue(all(r["operatingMargin"] is None for r in rows))
        self.assertTrue(all(r["previous"]["end"] == "2025-06-30" for r in rows))
        self.assertEqual(m["confectioneryEvidence"]["geographyResiduals"], [134, 272])

    def test_negative_acquisition_arithmetic_is_not_cash_release(self):
        m = self.m
        e = m["confectioneryEvidence"]
        self.assertEqual(
            [f["value"] for f in e["acquisitionPeriods"]], [10737930000, 0, 10738104000]
        )
        self.assertEqual(e["acquisitionArithmetic"], -174000)
        self.assertEqual(e["acquisitionAdopted"], 0)
        self.assertEqual(e["consideration"]["value"], 10738104000)
        self.assertEqual(e["acquiredCash"]["value"], 174000)
        self.assertEqual(e["acquisitionReconciliationResidual"], 0)
        self.assertEqual(e["acquisitionProxyRatio"], 10737930000 / 3332442536373)
        a = copy.deepcopy(m["defaults"])
        a["capexStart"] -= e["acquisitionProxyRatio"]
        a["capexEnd"] -= e["acquisitionProxyRatio"]
        self.assertAlmostEqual(
            calculate(m, a)["years"][0]["cash"] - m["initial"]["years"][0]["cash"],
            3577444776235 * e["acquisitionProxyRatio"],
            places=3,
        )

    def test_associates_book_and_july_rights_are_not_repeated_operating_cash(self):
        m = self.m
        e = m["confectioneryEvidence"]
        self.assertEqual(e["associateBook"]["value"], 684549079742)
        self.assertEqual(e["equityIncome"]["value"], -54138434278)
        self.assertEqual(e["dividends"]["value"], 1399500000)
        post = e["postBalanceInvestment"]
        self.assertEqual(post["preferred"] + post["convertible"], post["total"])
        self.assertEqual(post["total"], 125000000000)
        self.assertEqual(post["disclosedAcquisitionDate"], "2026-07-24")
        self.assertFalse(post["cashSettlementConfirmed"])
        self.assertEqual(
            m["segments"][0]["revenue"] * m["segments"][0]["margin"], 603474729165
        )
        self.assertEqual(m["security"]["status"], "unresolved")
        self.assertIsNone(m["initial"]["price"])
        self.assertIsNone(m["initial"]["requiredTerminalCash"])
        self.assertEqual(
            self.c["valuation"]["security"],
            next(c for c in load_latest()["companies"] if c["id"] == "271560")[
                "valuation"
            ]["security"],
        )

    def test_interest_cost_and_lease_principal_have_separate_cash_effects(self):
        m = self.m
        self.assertAlmostEqual(
            m["initial"]["years"][0]["netInterest"], -15338925430, places=3
        )
        a = copy.deepcopy(m["defaults"])
        a["netInterest"] = 0
        self.assertAlmostEqual(
            calculate(m, a)["years"][0]["cash"] - m["initial"]["years"][0]["cash"],
            15338925430 * 0.75,
            places=3,
        )
        a = copy.deepcopy(m["defaults"])
        a["leaseStart"] = a["leaseEnd"] = 0
        self.assertAlmostEqual(
            calculate(m, a)["years"][0]["cash"] - m["initial"]["years"][0]["cash"],
            13499532710,
            places=3,
        )

    def test_depreciation_and_minority_do_not_add_associate_losses(self):
        m = self.m
        self.assertAlmostEqual(
            m["defaults"]["depreciation"] * 3577444776235, 171771436437
        )
        self.assertAlmostEqual(
            m["initial"]["years"][0]["minority"], 7030834159, places=3
        )
        self.assertAlmostEqual(
            m["initial"]["years"][0]["cash"], 286460215242.2923, places=3
        )
        self.assertEqual(m["anchors"]["workingStockNet"], 348532380454)
        self.assertIsNone(m["anchors"]["shareCompensationReplacement"])

    def test_new_filings_and_past_dates_require_new_review(self):
        c = copy.deepcopy(self.c)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(
            candidate.build(c, "2026-09-29")["status"], "source_review_required"
        )
        with self.assertRaises(ValueError):
            candidate.build(copy.deepcopy(self.c), "2026-08-17")


if __name__ == "__main__":
    unittest.main(verbosity=2)
