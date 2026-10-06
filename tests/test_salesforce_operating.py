import copy
import unittest
from equitylab import salesforce_operating, operating_model
from equitylab.pipeline import load_latest


class SalesforceOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.as_of = s["asOf"]
        cls.c = copy.deepcopy(next(c for c in s["companies"] if c["id"] == "CRM"))
        cls.m = salesforce_operating.build(cls.c, cls.as_of)

    def test_all_periods_cash_and_product_economics_reconcile(self):
        m = self.m
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [14996000000, 7970000000, 7216000000],
        )
        self.assertTrue(
            all(
                p["residual"] == p["incomeResidual"] == p["revenueResidual"] == 0
                for p in m["bridge"]["periods"]
            )
        )
        self.assertEqual(m["bridge"]["reportedCfo"], 15750000000)
        self.assertEqual(m["facts"]["revenue"]["value"], 43938000000)
        self.assertEqual(m["facts"]["operatingIncome"]["value"], 8735000000)
        self.assertLess(m["segments"][1]["margin"], 0)

    def test_strategic_profit_is_removed_from_cash_and_not_operating_profit(self):
        p = self.m["bridge"]["periods"][1]
        self.assertEqual(p["netIncome"], 5633000000)
        self.assertEqual(p["investmentProfit"], 3171000000)
        row = next(x for x in p["components"] if x["label"] == "전략 투자 손익 제거")
        self.assertEqual(row["value"], -3171000000)
        self.assertEqual(p["operatingIncome"], 4678000000)

    def test_current_contractual_interest_replaces_old_debt_cost(self):
        e = self.m["salesforceEvidence"]
        self.assertEqual(e["debtPrincipal"], 39500000000)
        self.assertEqual(e["debtAnnualInterest"], 1824275000)
        self.assertEqual(e["floatingPrincipal"], 6000000000)
        self.assertEqual(e["annualFinanceLeaseInterest"]["value"], 25000000)
        self.assertEqual(e["annualInterestProxy"], 1849275000)
        undrawn = next(
            t for t in e["debt"] if t["label"] == "Revolving Loan Credit Agreement"
        )
        self.assertIsNone(undrawn["rate"])
        self.assertIsNone(undrawn["annualInterest"])

    def test_financing_cash_statement_is_not_replaced_by_narrow_lease_note(self):
        e = self.m["salesforceEvidence"]
        self.assertEqual(
            self.m["facts"]["financingPrincipal"]["components"][0]["fact"]["value"],
            584000000,
        )
        self.assertEqual(e["annualFinanceLeasePrincipal"]["value"], 367000000)
        self.assertEqual(e["annualFinancingDifference"], 217000000)
        self.assertEqual(e["financingObligationPrincipal"], 612000000)
        self.assertIsNone(e["financeLeasePrincipal"])
        self.assertIsNone(self.m["anchors"]["actualFinanceLeasePrincipal"])

    def test_rou_addback_requires_a_separate_operating_lease_cash_assumption(self):
        m = self.m
        e = m["salesforceEvidence"]
        self.assertEqual(e["operatingLeaseCashAdjustment"], 574000000)
        self.assertEqual(e["leaseTotalProxy"], 1186000000)
        self.assertAlmostEqual(
            m["initial"]["years"][0]["leasePrincipal"], 1186000000, places=3
        )
        a = copy.deepcopy(m["defaults"])
        a["leaseStart"] = a["leaseEnd"] = (
            e["financingObligationPrincipal"] / m["facts"]["revenue"]["value"]
        )
        without = operating_model.calculate(m, a)
        self.assertAlmostEqual(
            without["years"][0]["cash"] - m["initial"]["years"][0]["cash"],
            574000000,
            places=3,
        )

    def test_commissions_are_subtracted_once_and_excluded_from_working_stock(self):
        m = self.m
        e = m["salesforceEvidence"]
        self.assertEqual(
            [t["label"] for t in e["workingStockTerms"]],
            ["순매출채권", "계약자산", "유동 계약부채"],
        )
        self.assertEqual(e["workingStockNet"], -11612000000)
        self.assertEqual(m["facts"]["commissions"]["value"], 3097000000)
        self.assertEqual(m["facts"]["commissionAmortization"]["value"], 2281000000)
        self.assertAlmostEqual(m["initial"]["years"][0]["cash"], -4229706250, places=3)

    def test_positive_cash_cannot_bypass_the_unresolved_financing_scope(self):
        m = self.m
        a = copy.deepcopy(m["defaults"])
        a["capexStart"] = a["capexEnd"] = m["salesforceEvidence"][
            "reinvestmentExcludingAcquisitionRatio"
        ]
        r = operating_model.calculate(m, a)
        self.assertGreater(r["years"][0]["cash"], 0)
        self.assertIsNone(r["price"])
        self.assertIsNone(r["requiredTerminalCash"])
        self.assertIn("2.17억", m["priceHoldReason"])
        self.assertEqual(self.c["valuation"]["security"]["status"], "available")

    def test_new_filing_cannot_inherit_contract_interpretation(self):
        c = copy.deepcopy(self.c)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(
            salesforce_operating.build(c, self.as_of)["status"],
            "source_review_required",
        )


if __name__ == "__main__":
    unittest.main()
