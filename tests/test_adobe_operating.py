import copy
import unittest
from equitylab import adobe_operating, operating_model
from equitylab.pipeline import load_latest


class AdobeOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.as_of = s["asOf"]
        cls.c = copy.deepcopy(next(c for c in s["companies"] if c["id"] == "ADBE"))
        cls.m = adobe_operating.build(cls.c, cls.as_of)

    def test_product_and_all_period_cash_reconcile(self):
        m = self.m
        self.assertEqual(len(m["segments"]), 3)
        self.assertTrue(m["grossProfitPath"])
        for p in m["bridge"]["periods"]:
            self.assertEqual(
                (
                    p["residual"],
                    p["incomeResidual"],
                    p["revenueResidual"],
                    p["costResidual"],
                ),
                (0, 0, 0, 0),
            )
        self.assertEqual(m["facts"]["revenue"]["value"], 25970000000)
        self.assertEqual(m["facts"]["operatingIncome"]["value"], 9271000000)
        self.assertEqual(m["bridge"]["reportedCfo"], 10806000000)
        self.assertEqual(sum(p["value"] for p in m["bridge"]["parts"]), 10806000000)
        self.assertLess(m["segments"][2]["margin"], 0)

    def test_other_noncash_sign_is_preserved_and_inverted_once(self):
        current = self.m["bridge"]["periods"][1]
        row = next(
            p for p in current["components"] if p["label"].startswith("기타 비현금")
        )
        self.assertEqual(row["fact"]["value"], -94000000)
        self.assertEqual(row["value"], 94000000)
        self.assertIsNone(self.m["bridge"]["periods"][0]["impairment"])
        self.assertEqual(current["impairment"]["value"], 70000000)

    def test_contract_amortization_is_not_added_back_twice(self):
        m = self.m
        e = m["creativeEvidence"]
        self.assertEqual(e["annualContractAmortization"]["value"], 282000000)
        self.assertEqual(e["annualPpeDepreciation"]["value"], 236000000)
        self.assertEqual(e["annualDaUnallocated"], -10000000)
        self.assertAlmostEqual(
            m["defaults"]["depreciation"],
            236000000 / 23769000000 + 221000000 / 25970000000,
        )
        self.assertNotAlmostEqual(
            m["defaults"]["depreciation"], m["facts"]["cashDa"]["value"] / 25970000000
        )
        self.assertEqual(e["contractCostCurrent"]["value"], 815000000)
        self.assertEqual(e["contractCostOpening"]["value"], 721000000)

    def test_stock_balances_do_not_mix_rounded_note_and_full_balance_sheet(self):
        e = self.m["creativeEvidence"]
        self.assertEqual(
            [x["fact"]["value"] for x in e["workingStockTerms"]],
            [2081000000, 238000000, 815000000, 529000000, 7094000000, 110000000],
        )
        self.assertEqual(e["workingStockNet"], -4599000000)
        self.assertEqual(len(e["workingStockTerms"]), 6)

    def test_investment_and_costs_stay_in_future_cash(self):
        m = self.m
        self.assertEqual(m["facts"]["acquisitions"]["value"], 1560000000)
        self.assertAlmostEqual(
            m["initial"]["years"][0]["cash"],
            5463103506.668349 - 25970000000 * 80000000 / 19776000000,
            places=3,
        )
        self.assertIsNone(m["anchors"]["actualFinanceLeasePrincipal"])
        a = copy.deepcopy(m["defaults"])
        a["capexStart"] = a["capexEnd"] = m["creativeEvidence"][
            "reinvestmentExcludingAcquisitionRatio"
        ]
        r = operating_model.calculate(m, a)
        self.assertAlmostEqual(
            r["years"][0]["cash"] - m["initial"]["years"][0]["cash"],
            1560000000,
            places=3,
        )

    def test_broad_asset_purchase_caption_and_inconsistent_periods_hold_price(self):
        m = self.m
        e = m["creativeEvidence"]
        f = e["otherPurchases"]
        self.assertEqual(
            [p["fact"]["value"] for p in f["components"]],
            [134000000, 80000000, 216000000],
        )
        self.assertEqual(f["arithmeticValue"], -2000000)
        self.assertIsNone(f["value"])
        self.assertEqual(f["status"], "period_scope_review_required")
        self.assertAlmostEqual(e["currentOtherPurchaseRatio"], 80000000 / 19776000000)
        self.assertGreater(m["initial"]["years"][0]["cash"], 0)
        self.assertIsNone(m["initial"]["price"])
        self.assertIsNone(m["initial"]["requiredTerminalCash"])
        self.assertIn("무형·기타", m["priceHoldReason"])
        self.assertTrue(
            any(p["id"] == "282f169dc8010e44113c" for p in m["historicalPassages"])
        )

    def test_future_customer_funding_is_an_editable_assumption(self):
        m = self.m
        a = copy.deepcopy(m["defaults"])
        for s in a["segments"]:
            s["growthStart"] = s["growthEnd"] = 0.05
        funded = operating_model.calculate(m, a)
        a["workingCapital"] = 0
        unfunded = operating_model.calculate(m, a)
        self.assertGreater(funded["years"][0]["cash"], unfunded["years"][0]["cash"])

    def test_new_filing_requires_new_source_review(self):
        c = copy.deepcopy(self.c)
        c["narrative"]["accession"] = "new"
        self.assertEqual(
            adobe_operating.build(c, self.as_of)["status"], "source_review_required"
        )


if __name__ == "__main__":
    unittest.main()
