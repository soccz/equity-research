import copy
import unittest
from unittest.mock import patch
from equitylab.pipeline import load_latest
from equitylab.operating_model import calculate

from equitylab import lam_operating as lam


class LamOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.company = copy.deepcopy(
            next(c for c in s["companies"] if c["id"] == "LRCX")
        )
        cls.model = lam.build(copy.deepcopy(cls.company), s["asOf"])

    def test_reported_annual_cash_and_comparative_year_are_separate(self):
        m = self.model
        self.assertEqual(m["sourcePeriod"], ["2025-06-30", "2026-06-28"])
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]], [5857657000, 6173264000]
        )
        self.assertEqual(sum(p["value"] for p in m["bridge"]["parts"]), 5857657000)
        self.assertEqual(m["bridge"]["reportedCfo"], 5857657000)
        self.assertEqual(m["bridge"]["cashAfterInvestmentLeaseSbc"], 4499900000)

    def test_single_segment_gross_profit_is_not_service_operating_income(self):
        m = self.model
        y = m["initial"]["years"][0]
        self.assertEqual(len(m["segments"]), 1)
        self.assertEqual(y["grossProfit"], 12120049000)
        self.assertAlmostEqual(y["otherOperating"], 394741000, delta=0.01)
        self.assertEqual(y["research"], 2375873000)
        self.assertEqual(y["selling"], 1149640000)
        self.assertEqual(y["operatingIncome"], 8199795000)
        self.assertEqual(m["facts"]["gross"]["value"], 11725308000)

    def test_warranty_beginning_precedes_the_fiscal_period(self):
        m = self.model
        p = m["anchors"]["warrantyPeriods"][0]
        self.assertEqual(p["opening"]["end"], "2025-06-29")
        self.assertEqual(p["opening"]["value"], 265466000)
        self.assertEqual(p["issued"]["value"] + p["adjustment"]["value"], 275077000)
        self.assertEqual(p["settled"]["value"], 250830000)
        self.assertEqual(p["closing"]["value"], 289713000)
        self.assertEqual(
            p["opening"]["value"]
            + p["issued"]["value"]
            + p["adjustment"]["value"]
            - p["settled"]["value"],
            p["closing"]["value"],
        )

    def test_warranty_settlement_replaces_accrual_without_repeating_working_cash(self):
        m = self.model
        y = m["initial"]["years"][0]
        self.assertEqual(m["anchors"]["workingCashEffect"], -1874593000)
        self.assertEqual(y["warrantyAccrual"], 275077000)
        self.assertEqual(y["warrantyUse"], 250830000)
        a = copy.deepcopy(m["defaults"])
        a["warrantyUseStart"] += 0.01
        a["warrantyUseEnd"] += 0.01
        stressed = calculate(m, a)
        self.assertAlmostEqual(
            y["cash"] - stressed["years"][0]["cash"], m["segments"][0]["revenue"] * 0.01
        )
        self.assertEqual(y["workingCapital"], 0)
        self.assertEqual(y["operatingIncome"], stressed["years"][0]["operatingIncome"])

    def test_only_identified_finance_lease_principal_is_deducted(self):
        m = self.model
        y = m["initial"]["years"][0]
        self.assertEqual(y["leasePrincipal"], 4971000)
        self.assertAlmostEqual(y["capex"], 966405000, delta=0.01)
        self.assertEqual(y["depreciation"], 441533000)
        self.assertEqual(y["netInterest"], 39305000)
        self.assertAlmostEqual(y["cash"], 6003293000)

    def test_source_changes_and_wrong_cash_or_reserve_signs_fail(self):
        for tag in [
            "OtherNoncashIncomeExpense",
            "StandardProductWarrantyAccrualPreexistingIncreaseDecrease",
        ]:
            original = lam.select

            def changed(rows, name, start, end, *args):
                r = original(rows, name, start, end, *args)
                return (
                    dict(r, value=-r["value"])
                    if r and name == tag and end == "2026-06-28"
                    else r
                )

            with patch.object(lam, "select", side_effect=changed):
                with self.assertRaises(ValueError):
                    lam.build(copy.deepcopy(self.company), "2026-09-29")
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(lam.build(c, "2026-09-29")["status"], "source_review_required")

    def test_research_cost_and_warranty_changes_both_affect_cash(self):
        m = self.model
        a = copy.deepcopy(m["defaults"])
        a["researchEnd"] += 0.05
        a["warrantyUseEnd"] += 0.01
        r = calculate(m, a)
        base = m["initial"]
        y = r["years"][-1]
        self.assertAlmostEqual(
            base["years"][-1]["cash"] - y["cash"],
            y["revenue"] * (0.05 * (1 - a["tax"]) + 0.01),
            delta=0.01,
        )
        self.assertNotEqual(y["cash"], base["years"][-1]["cash"])


if __name__ == "__main__":
    unittest.main()
