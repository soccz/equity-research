import copy
import unittest
from equitylab import innotek_operating, operating_model
from equitylab.pipeline import load_latest


class InnotekOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.as_of = s["asOf"]
        cls.c = copy.deepcopy(next(c for c in s["companies"] if c["id"] == "011070"))
        cls.m = innotek_operating.build(cls.c, cls.as_of)

    def test_all_periods_reconcile_segment_sales_profits_and_cash(self):
        m = self.m
        self.assertEqual(len(m["segments"]), 3)
        self.assertTrue(
            all(
                p["residual"] == p["revenueResidual"] == p["incomeResidual"] == 0
                for p in m["bridge"]["periods"]
            )
        )
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [1331402000000, 398042000000, 878810000000],
        )
        self.assertEqual(m["bridge"]["reportedCfo"], 850634000000)
        self.assertEqual(m["facts"]["revenue"]["value"], 24041265000000)
        self.assertEqual(m["facts"]["operatingIncome"]["value"], 1069572000000)

    def test_receivable_inventory_and_payable_cash_movements_do_not_hide_the_residual(
        self,
    ):
        current = self.m["bridge"]["periods"][1]
        prior = self.m["bridge"]["periods"][2]
        self.assertEqual(current["receivables"], 761354000000)
        self.assertEqual(current["inventory"], -678747000000)
        self.assertEqual(current["payables"], -512930000000)
        self.assertEqual(current["remainingWorking"], -130637000000)
        self.assertEqual(current["working"] - prior["working"], -812372000000)
        self.assertEqual(current["reportedCfo"] - prior["reportedCfo"], -480768000000)
        self.assertEqual(
            current["netIncome"]
            + current["costAdjustments"]
            - current["gainAdjustments"]
            + current["working"],
            current["generated"],
        )

    def test_customer_disclosures_remain_two_values_without_an_invented_name(self):
        e = self.m["manufacturingEvidence"]["customerScope"]
        self.assertEqual(e["status"], "scope_review_required")
        self.assertEqual(e["businessValue"], 8841475000000)
        self.assertEqual(e["note"]["value"], 8888208000000)
        self.assertEqual(e["difference"], 46733000000)
        self.assertNotIn("customerName", e)

    def test_net_trade_receivables_and_trade_payables_exclude_other_balances(self):
        m = self.m
        terms = m["anchors"]["workingStockTerms"]
        self.assertEqual(
            [t["fact"]["value"] for t in terms],
            [2768984000000, 2486047000000, 2262557000000],
        )
        self.assertEqual(m["anchors"]["workingStockNet"], 2992474000000)
        self.assertAlmostEqual(
            m["defaults"]["workingCapital"], 2992474000000 / 24041265000000
        )

    def test_original_financial_expense_sign_is_converted_once(self):
        f = self.m["facts"]["receivableDisposalCost"]
        parts = f["components"]
        self.assertEqual(parts[0]["fact"]["value"], -25927000000)
        self.assertEqual(parts[0]["coefficient"], -1)
        self.assertEqual(parts[1]["fact"]["value"], 8249000000)
        self.assertEqual(parts[2]["fact"]["value"], 6939000000)
        self.assertEqual(f["value"], 27237000000)
        self.assertAlmostEqual(
            self.m["initial"]["years"][0]["netInterest"], -116003000000, places=3
        )

    def test_cash_depreciation_difference_and_unknown_compensation_are_preserved(self):
        m = self.m
        current = m["bridge"]["periods"][1]
        self.assertEqual(current["depreciationCash"], 463986000000)
        self.assertEqual(current["depreciationStatement"], 463985000000)
        self.assertEqual(current["depreciationDifference"], 1000000)
        self.assertIsNone(m["anchors"]["shareCompensationReplacement"])
        self.assertIsNone(m["bridge"]["cashAfterInvestmentLeaseSbc"])
        self.assertAlmostEqual(m["initial"]["years"][0]["cash"], 995133750000, places=3)
        self.assertTrue(m["initial"]["reinvestmentCaution"])

    def test_future_cash_is_sensitive_to_operating_funding_and_reinvestment_assumptions(
        self,
    ):
        m = self.m
        a = copy.deepcopy(m["defaults"])
        for s in a["segments"]:
            s["growthStart"] = s["growthEnd"] = 0.05
        base = operating_model.calculate(m, a)
        a["workingCapital"] += 0.1
        changed = operating_model.calculate(m, a)
        self.assertLess(changed["years"][0]["cash"], base["years"][0]["cash"])
        self.assertLess(changed["price"], base["price"])

    def test_new_source_cannot_inherit_this_interpretation(self):
        c = copy.deepcopy(self.c)
        c["narrative"]["evidenceHash"] = "new"
        self.assertEqual(
            innotek_operating.build(c, self.as_of)["status"], "source_review_required"
        )


if __name__ == "__main__":
    unittest.main()
