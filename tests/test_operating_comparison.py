import copy
import unittest

from equitylab.operating_comparison import summarize
from equitylab.peer_studies import build
from equitylab.pipeline import load_latest


class OperatingComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        snapshot = load_latest()
        cls.companies = copy.deepcopy(snapshot["companies"])
        from equitylab.hynix_operating import build as hynix
        from equitylab.valuation import build as valuation

        c = next(c for c in cls.companies if c["id"] == "000660")
        c["valuation"] = valuation(c, snapshot["asOf"])
        c["operatingModel"] = hynix(c, snapshot["asOf"])
        from equitylab import amd_operating, cash_scope

        c = next(c for c in cls.companies if c["id"] == "AMD")
        c["cashScope"] = cash_scope.build(c, snapshot["asOf"])
        c["valuation"] = valuation(c, snapshot["asOf"])
        c["operatingModel"] = amd_operating.build(c, snapshot["asOf"])

        from equitylab import samsung_operating

        c = next(c for c in cls.companies if c["id"] == "005930")
        c["operatingModel"] = samsung_operating.build(c, snapshot["asOf"])

        from equitylab import (
            applied_operating,
            lam_operating,
            broadcom_operating,
            mobis_operating,
            naver_operating,
            jnj_operating,
            celltrion_operating,
            servicenow_operating,
            sds_operating,
            oracle_operating,
            adobe_operating,
            salesforce_operating,
            txn_operating,
            adi_operating,
        )

        for cid, module in [
            ("AMAT", applied_operating),
            ("LRCX", lam_operating),
            ("AVGO", broadcom_operating),
            ("012330", mobis_operating),
            ("035420", naver_operating),
            ("JNJ", jnj_operating),
            ("068270", celltrion_operating),
            ("NOW", servicenow_operating),
            ("018260", sds_operating),
            ("ORCL", oracle_operating),
            ("ADBE", adobe_operating),
            ("CRM", salesforce_operating),
            ("TXN", txn_operating),
            ("ADI", adi_operating),
        ]:
            c = next(c for c in cls.companies if c["id"] == cid)
            c["operatingModel"] = module.build(c, snapshot["asOf"])

    def test_only_reconciled_company_models_support_a_paired_cash_comparison(self):
        rows = build(copy.deepcopy(self.companies))
        ready = [
            r
            for r in rows
            if r["operatingComparison"]["status"] == "research_workspace"
        ]
        self.assertEqual(
            {r["id"] for r in ready},
            {
                "auto-demand",
                "cloud-usage",
                "advertising-ai-cash",
                "memory-price-volume",
                "accelerator-contract-cash",
                "electronics-mix",
                "semiconductor-equipment",
                "ai-customer-financing",
                "auto-supply-service",
                "advertising-platforms",
                "innovator-biosimilar",
                "enterprise-delivery",
                "cloud-build-operate",
                "software-contracts",
                "analog-manufacturing",
            },
        )
        for r in ready:
            self.assertFalse(r["financialApproval"])
            comparison = r["operatingComparison"]
            self.assertEqual(
                comparison["sameSourcePeriod"],
                r["id"]
                not in {
                    "memory-price-volume",
                    "accelerator-contract-cash",
                    "electronics-mix",
                    "semiconductor-equipment",
                    "ai-customer-financing",
                    "innovator-biosimilar",
                    "cloud-build-operate",
                    "software-contracts",
                    "analog-manufacturing",
                },
            )
            self.assertTrue(comparison["samePriceDate"])
            self.assertEqual(comparison["studyHash"], r["evidenceHash"])
            for s in comparison["sides"]:
                result = s["initial"]
                cash = result["cashPath"]
                a = s["defaults"]
                if s["security"]["marketCapProxy"] is None:
                    self.assertIsNone(cash["price"])
                    self.assertIsNone(result["requiredCashMargin"])
                    self.assertIsNone(result["marginGap"])
                    self.assertIsInstance(result["terminalCashMargin"], float)
                    continue
                if (
                    cash.get("investmentBridge", {}).get("status")
                    == "investment_unassessed"
                ):
                    self.assertEqual(s["company"], "035420")
                    self.assertGreater(cash["price"], 0)
                    self.assertIsNone(result["requiredCashMargin"])
                    self.assertIsNone(result["marginGap"])
                    self.assertIsNone(result["valueToMarket"])
                    continue
                implied = (
                    cash["explicitPv"]
                    + cash["requiredTerminalCash"]
                    / (a["discount"] - a["terminal"])
                    / (1 + a["discount"]) ** 5
                )
                self.assertAlmostEqual(implied / s["security"]["marketCapProxy"], 1)
                self.assertAlmostEqual(
                    result["requiredCashMargin"] - result["terminalCashMargin"],
                    result["marginGap"],
                )

    def test_negative_cash_paths_are_not_zero_valuations_or_automatic_opinions(self):
        rows = build(copy.deepcopy(self.companies))
        sides = [s for r in rows for s in r["operatingComparison"].get("sides", [])]
        for s in sides:
            if s["company"] in {"TSLA", "AMZN"}:
                self.assertLess(s["initial"]["terminalCashMargin"], 0)
                self.assertIsNone(s["initial"]["valueToMarket"])
                self.assertGreater(s["initial"]["requiredCashMargin"], 0)

    def test_currency_scale_does_not_create_a_relative_margin_advantage(self):
        c = next(c for c in self.companies if c["id"] == "TSLA")
        m = copy.deepcopy(c["operatingModel"])
        before = summarize(m, m["defaults"])
        for segment in m["segments"]:
            segment["revenue"] *= 1000
        m["security"]["marketCapProxy"] *= 1000
        after = summarize(m, m["defaults"])
        for k in [
            "terminalCashMargin",
            "requiredCashMargin",
            "marginGap",
            "explicitCoverage",
        ]:
            self.assertAlmostEqual(before[k], after[k])

    def test_price_change_changes_the_contract_and_missing_model_stays_missing(self):
        original = next(
            r for r in build(copy.deepcopy(self.companies)) if r["id"] == "auto-demand"
        )["operatingComparison"]
        companies = copy.deepcopy(self.companies)
        c = next(c for c in companies if c["id"] == "TSLA")
        c["priceSummary"]["close"] *= 1.1
        c["operatingModel"]["security"]["marketCapProxy"] *= 1.1
        changed = next(r for r in build(companies) if r["id"] == "auto-demand")[
            "operatingComparison"
        ]
        self.assertNotEqual(original["evidenceHash"], changed["evidenceHash"])
        self.assertGreater(
            changed["sides"][0]["initial"]["requiredCashMargin"],
            original["sides"][0]["initial"]["requiredCashMargin"],
        )
        c["operatingModel"] = None
        held = next(r for r in build(companies) if r["id"] == "auto-demand")[
            "operatingComparison"
        ]
        self.assertEqual(held["status"], "source_review_required")
        self.assertEqual(held["missingModels"], ["TSLA"])


if __name__ == "__main__":
    unittest.main()
