import copy
import importlib.util
from pathlib import Path
import unittest
from equitylab.pipeline import load_latest
from equitylab.operating_model import calculate

spec = importlib.util.spec_from_file_location("sds_candidate", Path(__file__).with_name("sds_operating.py"))
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class SdsOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = next(c for c in load_latest()["companies"] if c["id"] == "018260")
        cls.model = candidate.build(copy.deepcopy(cls.company), "2026-09-29")

    def test_all_three_periods_reconcile_cfo_and_preserve_precision(self):
        m = self.model
        self.assertEqual(m["bridge"]["reportedCfo"], 1235571475659)
        self.assertEqual([p["reportedCfo"] for p in m["bridge"]["periods"]], [1203327812666,599257941995,567014279002])
        self.assertEqual([p["revenueResidual"] for p in m["bridge"]["periods"]], [-289,128,-225])
        self.assertEqual([p["indirectPrecisionResidual"] for p in m["bridge"]["periods"]], [1411,-559,836])
        self.assertEqual(m["facts"]["dividends"]["value"], 65650000)

    def test_annual_segment_context_uses_current_source_table(self):
        m = self.model
        self.assertEqual([s["evidence"][0]["components"][0]["fact"]["value"] for s in m["segments"]], [7797903360000,7974695401000])
        self.assertEqual(m["consolidation"]["periods"][0]["unallocatedOperatingIncome"],3973962000)
        self.assertNotEqual(m["segments"][0]["evidence"][0]["components"][0]["fact"]["value"],7717530406000)

    def test_working_stock_avoids_contract_asset_double_count_and_flow_extrapolation(self):
        m = self.model
        self.assertEqual(m["anchors"]["workingStockNet"],1935340466532)
        self.assertEqual(len(m["anchors"]["workingStockTerms"]),5)
        self.assertAlmostEqual(m["defaults"]["workingCapital"],.1382503358357757)
        self.assertEqual(m["anchors"]["currentTradeCashEffect"],111253061000)
        self.assertGreater(m["anchors"]["annualFlowCoefficient"],1)
        self.assertNotEqual(m["defaults"]["workingCapital"],m["anchors"]["annualFlowCoefficient"])

    def test_retirement_cost_is_not_all_of_the_profit_decline_or_cash(self):
        r = self.model["sdsEvidence"]["retirement"]
        self.assertEqual(r["sellingCost"]+r["productionCost"],123700000000)
        self.assertEqual(r["remainingProfitDifference"],-64859976916)
        self.assertIn("즉시 현금 회복 전망이 아닙니다",r["scope"])
        self.assertNotIn("normalizationPath",self.model)

    def test_cash_path_keeps_capital_hold_under_growth_and_margin_changes(self):
        m = self.model
        self.assertAlmostEqual(m["initial"]["years"][0]["cash"],617934198527.1176,places=2)
        a = copy.deepcopy(m["defaults"])
        a["segments"][0]["growthStart"] = .1
        a["segments"][0]["marginEnd"] = .12
        r = calculate(m,a)
        self.assertIsNone(r["price"])
        self.assertIsNone(r["requiredTerminalCash"])
        self.assertGreater(r["years"][0]["workingCapital"],0)
        self.assertNotEqual(r["years"][0]["cash"],m["initial"]["years"][0]["cash"])

    def test_business_scope_preserves_government_ownership_and_trade_payable_policy(self):
        text = " ".join(p["text"] for p in self.model["passages"])
        self.assertIn("정부 소유의 GPU",text)
        self.assertIn("3개월 이내로 동일",text)
        self.assertIn("매입채무의 조건이 실질적으로 변동되지",text)

    def test_new_sources_require_review(self):
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "different"
        self.assertEqual(candidate.build(c,"2026-09-29")["status"],"source_review_required")


if __name__ == "__main__":
    unittest.main()
