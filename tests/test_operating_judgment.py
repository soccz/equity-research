import copy
import unittest

from equitylab.operating_judgment import build
from equitylab.pipeline import load_latest
from equitylab.research_case import build as case


class OperatingJudgmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.companies = {c["id"]: c for c in load_latest()["companies"]}

    def test_terminal_requirement_reconciles_market_after_explicit_years(self):
        for ident in ["MSFT", "META", "TSLA", "000270"]:
            c = self.companies[ident]
            r = build(c)
            a = r["assumptions"]
            implied = (
                r["firstFiveYearsPv"]
                + r["requiredTerminalCash"]
                / (a["discount"] - a["terminal"])
                / (1 + a["discount"]) ** 5
            )
            self.assertAlmostEqual(
                implied / c["valuation"]["security"]["marketCapProxy"], 1
            )
            self.assertFalse(r["financialApproval"])
            self.assertNotIn("requiredAnnualCash", r)

    def test_negative_cash_and_security_hold_are_different_states(self):
        negative = build(self.companies["AMZN"])
        self.assertEqual(negative["state"], "현금 전환 가정 필요")
        self.assertLess(negative["referenceTerminalCash"], 0)
        self.assertIsNotNone(negative["requiredTerminalCash"])
        held = build(self.companies["GOOGL"])
        self.assertEqual(held["state"], "증권 범위 보완")
        self.assertGreater(held["referenceTerminalCash"], 0)
        self.assertIsNone(held["requiredTerminalCash"])
        self.assertIsNone(held["referencePrice"])

    def test_cash_scope_hold_has_priority_even_with_existing_model(self):
        c = copy.deepcopy(self.companies["MSFT"])
        c["cashScope"] = dict(status="review_required", reason="사업 분리 재대사")
        r = build(c)
        self.assertEqual(r["state"], "사업 범위 대사")
        self.assertIsNone(r["requiredTerminalCash"])
        self.assertIsNone(r["referencePrice"])

    def test_cash_definition_hold_is_not_misreported_as_share_rights(self):
        from equitylab import adobe_operating, salesforce_operating

        for ident, module in [("ADBE", adobe_operating), ("CRM", salesforce_operating)]:
            c = copy.deepcopy(self.companies[ident])
            c["operatingModel"] = module.build(c, "2026-09-29")
            self.assertEqual(c["valuation"]["security"]["status"], "available")
            r = build(c)
            self.assertEqual(r["state"], "현금 항목 범위 대사")
            self.assertEqual(r["statement"], c["operatingModel"]["priceHoldReason"])
            self.assertIsNone(r["requiredTerminalCash"])
            self.assertIsNone(r["referencePrice"])

    def test_lower_price_is_only_an_assumption_review_not_an_approved_preference(self):
        c = copy.deepcopy(self.companies["MSFT"])
        c["operatingModel"]["security"]["marketCapProxy"] = 1e9
        r = build(c)
        self.assertEqual(r["state"], "가정 충족 여부 검토")
        self.assertFalse(r["financialApproval"])

    def test_case_uses_filing_bound_business_countercase_and_issuer_model(self):
        c = self.companies["000270"]
        r = case(c, list(self.companies.values()))
        self.assertEqual(r["pricing"]["basis"], "issuer_operating_cash_path")
        self.assertEqual(r["countercase"], c["businessInsight"]["countercase"])
        self.assertEqual(
            r["businessEvidenceHash"], c["businessInsight"]["evidenceHash"]
        )
        self.assertEqual(r["nextEvidence"][0], c["businessInsight"]["changeCondition"])
        self.assertTrue(all(w["expected"] is None for w in r["watch"]))
        changed = copy.deepcopy(c)
        changed["businessInsight"]["corpusHash"] = "old"
        self.assertNotIn(
            "businessEvidenceHash", case(changed, list(self.companies.values()))
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
