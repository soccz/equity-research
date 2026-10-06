import copy
import importlib.util
from pathlib import Path
import unittest
from equitylab.pipeline import load_latest
from equitylab.operating_model import calculate

spec=importlib.util.spec_from_file_location("now_candidate",Path(__file__).with_name("servicenow_operating.py"))
candidate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class ServiceNowOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company=next(c for c in load_latest()["companies"] if c["id"]=="NOW")
        cls.model=candidate.build(copy.deepcopy(cls.company),"2026-09-29")

    def test_three_cash_periods_preserve_tax_and_investment_adjustment_signs(self):
        m=self.model
        self.assertEqual([x["reportedCfo"] for x in m["bridge"]["periods"]],[5444000000,2257000000,2393000000])
        self.assertEqual(m["bridge"]["reportedCfo"],5308000000)
        self.assertEqual(sum(x["value"] for x in m["bridge"]["parts"]),5308000000)
        self.assertEqual(m["bridge"]["parts"][-1]["value"],-355000000)
        self.assertEqual(len(m["bridge"]["parts"][-1]["fact"]["components"]),2)

    def test_revenue_groups_reconcile_to_common_gaap_costs(self):
        m=self.model
        self.assertEqual(sum(s["revenue"] for s in m["segments"]),14732000000)
        self.assertEqual(m["facts"]["operatingIncome"]["value"],1680000000)
        self.assertLess(m["segments"][1]["margin"],0)
        self.assertIn("독립 보고부문이 아닙니다",m["businessCaption"])

    def test_commission_asset_amortization_and_acquisition_cash_are_separate(self):
        m=self.model;f=m["facts"]
        self.assertEqual(f["commissionAmortization"]["value"],668000000)
        self.assertEqual(f["commissions"]["value"],843000000)
        self.assertEqual(f["acquisitions"]["value"],9784000000)
        self.assertEqual(f["da"]["value"],1071000000)
        self.assertAlmostEqual(m["defaults"]["capexStart"]*14732000000,11364000000)
        self.assertAlmostEqual(m["defaults"]["depreciation"]*14732000000,1739000000)
        self.assertIsNone(m["anchors"]["actualFinanceLeasePayment"])

    def test_current_coupon_is_not_the_old_cash_interest_or_effective_yield(self):
        e=self.model["softwareEvidence"]
        self.assertEqual(sum(x["principal"] for x in e["coupons"]),5500000000)
        self.assertEqual(e["bondAnnualCoupon"],228650000)
        self.assertEqual(e["commercialPaperAnnualProxy"],83580000)
        self.assertEqual(e["annualInterestProxy"],312230000)
        self.assertEqual(e["commercialPaperRemainingDays"],81)
        self.assertNotEqual(e["annualInterestProxy"],self.model["facts"]["interestPaid"]["value"])
        self.assertEqual(e["coupons"][0]["coupon"],.014)
        self.assertEqual(e["coupons"][0]["effectiveRate"],.0153)

    def test_customer_advance_funding_is_a_dated_assumption(self):
        m=self.model
        self.assertEqual(m["anchors"]["workingStockNet"],-6153000000)
        self.assertAlmostEqual(m["defaults"]["workingCapital"],-.4176622318761879)
        self.assertIn("영구 무상 자금",m["anchorSummary"])

    def test_unadjusted_acquisition_cash_keeps_negative_path_visible(self):
        m=self.model
        self.assertAlmostEqual(m["initial"]["years"][0]["cash"],-8599172500)
        self.assertIsNone(m["initial"]["price"])
        a=copy.deepcopy(m["defaults"]);a["capexStart"]=a["capexEnd"]=.1
        r=calculate(m,a)
        self.assertGreater(r["years"][0]["cash"],0)
        self.assertNotEqual(r["years"][0]["cash"],m["initial"]["years"][0]["cash"])

    def test_new_filing_cannot_reuse_acquisition_terms(self):
        c=copy.deepcopy(self.company);c["narrative"]["evidenceHash"]="changed"
        self.assertEqual(candidate.build(c,"2026-09-29")["status"],"source_review_required")


if __name__=="__main__":unittest.main()
