import copy
import unittest
from equitylab.pipeline import load_latest
from equitylab.operating_model import calculate
from equitylab import naver_operating as naver


class NaverOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.company = next(c for c in s["companies"] if c["id"] == "035420")
        cls.model = naver.build(copy.deepcopy(cls.company), s["asOf"])

    def test_three_cash_periods_reconcile_without_inventing_interim_adjustments(self):
        m = self.model
        self.assertEqual(m["bridge"]["reportedCfo"], 3157421983625)
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [3095806604677, 1186557718996, 1124942340048],
        )
        self.assertEqual(
            sum(p["value"] for p in m["bridge"]["parts"]), m["bridge"]["reportedCfo"]
        )
        for p in m["bridge"]["periods"]:
            self.assertEqual(
                p["combinedNoncashAndWorking"], p["generated"] - p["netIncome"]
            )
            self.assertEqual(p["residual"], 0)
        self.assertIsNone(m["bridge"]["cashAfterInvestmentLeaseSbc"])

    def test_one_reportable_segment_does_not_invent_service_profit(self):
        m = self.model
        self.assertEqual(len(m["segments"]), 1)
        self.assertEqual(m["segments"][0]["revenue"], 12962954994050)
        self.assertAlmostEqual(
            m["initial"]["years"][0]["operatingIncome"], 2243349860301, delta=0.001
        )
        self.assertFalse(m.get("grossProfitPath", False))

    def test_annual_trade_proxy_excludes_customer_financing_and_preserves_missing_sbc(
        self,
    ):
        m = self.model
        self.assertEqual(m["anchors"]["workingPeriod"], ["2025-01-01", "2025-12-31"])
        self.assertEqual(m["anchors"]["workingCashEffect"], -13554845000)
        self.assertEqual(
            m["anchors"]["excludedOtherLiabilityCash"]["value"], 607686013000
        )
        self.assertEqual(m["anchors"]["annualSbc"]["value"], 157431856000)
        self.assertIsNone(m["anchors"]["actualShareCompensationReplacement"])
        self.assertAlmostEqual(m["defaults"]["workingCapital"], 0.010448601603659737)

    def test_restricted_customer_funds_are_balances_not_an_added_equity_asset(self):
        m = self.model
        self.assertEqual(
            [p["value"] for p in m["customerFunds"]["periods"]],
            [162541e6, 385584e6, 639676e6],
        )
        self.assertEqual(
            [p["currency"] for p in m["customerFunds"]["additionalRestrictions"]],
            ["JPY", "CAD"],
        )
        base = calculate(m, m["defaults"])
        changed = copy.deepcopy(m)
        changed["customerFunds"]["periods"][-1]["value"] *= 2
        self.assertEqual(base, calculate(changed, changed["defaults"]))

    def test_minority_loss_is_not_repeated_and_positive_burden_is_deducted_once(self):
        m = self.model
        self.assertEqual(m["anchors"]["reportedMinorityProfit"], -130517336300)
        self.assertEqual(m["defaults"]["minority"], 0)
        a = copy.deepcopy(m["defaults"])
        a["minority"] = 0.02
        r = calculate(m, a)
        for base, stress in zip(
            m["initial"]["years"] + [m["initial"]["terminal"]],
            r["years"] + [r["terminal"]],
        ):
            self.assertAlmostEqual(
                base["cash"] - stress["cash"], stress["revenue"] * 0.02, delta=0.001
            )
            self.assertEqual(base["tax"], stress["tax"])
        for bad in [-0.01, 1.01, float("nan")]:
            a["minority"] = bad
            with self.assertRaises(ValueError):
                calculate(m, a)

    def test_assets_leases_and_cash_interest_have_distinct_paths(self):
        m = self.model
        y = m["initial"]["years"][0]
        self.assertAlmostEqual(y["cash"], 505427839303.5, delta=0.001)
        self.assertAlmostEqual(y["capex"], 1806502744447, delta=0.001)
        self.assertAlmostEqual(y["leasePrincipal"], 228197843927, delta=0.001)
        self.assertAlmostEqual(y["depreciation"], 839477694000, delta=0.001)
        self.assertAlmostEqual(y["netInterest"], 102375289599, delta=0.001)
        self.assertEqual(m["facts"]["dividends"]["value"], 29012935152)

    def test_source_revision_requires_a_new_review(self):
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(
            naver.build(c, "2026-09-29")["status"], "source_review_required"
        )
