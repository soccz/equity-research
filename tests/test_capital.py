import copy
import unittest

from equitylab.capital import build
from equitylab.pipeline import load_latest
from equitylab.business import build as business_build


class CapitalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_latest()
        cls.companies = {c["id"]: c for c in cls.snapshot["companies"]}

    def test_all_registered_companies_use_their_exact_current_filing(self):
        for c in self.companies.values():
            result = build(copy.deepcopy(c), self.snapshot["asOf"])
            core = c["financials"]["current"]["cfo"]
            self.assertEqual(result["status"], "ready", c["id"])
            for field in result["balances"].values():
                if field["current"]:
                    self.assertEqual(field["current"]["start"], None)
                    self.assertEqual(field["current"]["end"], core["end"])
                    self.assertEqual(field["current"]["accession"], core["accession"])
            for field in result["flows"].values():
                if field["current"]:
                    self.assertEqual(field["current"]["start"], core["start"])
                    self.assertEqual(field["current"]["end"], core["end"])

    def test_conflicting_dividend_disclosures_are_not_silently_selected(self):
        result = build(copy.deepcopy(self.companies["NVDA"]), self.snapshot["asOf"])
        self.assertIsNone(result["flows"]["dividends"]["current"])
        self.assertTrue(
            any(
                g["metric"] == "dividends" and "상충" in g["reason"]
                for g in result["gaps"]
            )
        )

    def test_sbc_proxy_is_not_cash_and_does_not_double_deduct_repurchases(self):
        c = copy.deepcopy(self.companies["MSFT"])
        result = build(c, self.snapshot["asOf"])
        q, f = result["cash"], result["flows"]
        self.assertFalse(q["sbcIsCash"])
        self.assertEqual(
            q["afterReportedLeasePayments"],
            c["metrics"]["cashAfterInvestment"]
            - f["leasePrincipal"]["current"]["value"],
        )
        self.assertEqual(
            q["afterSbcExpenseProxy"],
            q["afterReportedLeasePayments"] - f["sbc"]["current"]["value"],
        )

    def test_missing_lease_payment_is_not_treated_as_zero(self):
        result = build(copy.deepcopy(self.companies["AAPL"]), self.snapshot["asOf"])
        self.assertIsNone(result["flows"]["leasePrincipal"]["current"])
        self.assertIsNone(result["cash"]["afterReportedLeasePayments"])

    def test_us_segment_adjustments_reconcile_without_double_counting_products(self):
        for symbol in ["NVDA", "AAPL", "GOOGL"]:
            b = business_build(
                copy.deepcopy(self.companies[symbol]), self.snapshot["asOf"]
            )
            for r in b["reconciliations"].values():
                self.assertEqual(r["unexplained"], 0, symbol)
                self.assertEqual(r["status"], "reconciled")
            if b["products"]:
                self.assertEqual(b["productReconciliation"]["unexplained"], 0)
        a = business_build(copy.deepcopy(self.companies["AAPL"]), self.snapshot["asOf"])
        self.assertEqual(len(a["segments"]), 5)
        self.assertEqual(len(a["products"]), 5)
        self.assertEqual(
            a["reconciliations"]["operatingIncome"]["reportedAdjustment"], -40718000000
        )

    def test_korean_segment_difference_and_gross_revenue_are_explicit(self):
        b = business_build(
            copy.deepcopy(self.companies["005930"]), self.snapshot["asOf"]
        )
        self.assertEqual(
            b["reconciliations"]["revenue"]["reportedAdjustment"], -27108541000000
        )
        self.assertEqual(
            b["reconciliations"]["operatingIncome"]["unexplained"], 36860000000
        )
        self.assertEqual(
            b["reconciliations"]["operatingIncome"]["status"], "unresolved_difference"
        )
        self.assertIn("내부거래", b["segmentRevenueBasis"])

    def test_added_cloud_chip_and_cdmo_segments_reconcile(self):
        for symbol, expected_segments in [("AMZN", 3), ("AMD", 3), ("207940", 1)]:
            b = business_build(
                copy.deepcopy(self.companies[symbol]), self.snapshot["asOf"]
            )
            self.assertEqual(len(b["segments"]), expected_segments)
            for item in b["reconciliations"].values():
                self.assertEqual(item["unexplained"], 0, symbol)
        amd = business_build(
            copy.deepcopy(self.companies["AMD"]), self.snapshot["asOf"]
        )
        self.assertEqual(
            amd["reconciliations"]["operatingIncome"]["reportedAdjustment"], -2117000000
        )

    def test_broadcom_disclosed_costs_reconcile_and_korean_residuals_remain(self):
        broadcom = business_build(
            copy.deepcopy(self.companies["AVGO"]), self.snapshot["asOf"]
        )
        check = broadcom["reconciliations"]["operatingIncome"]
        self.assertEqual(check["reportedAdjustment"], -12543000000)
        self.assertEqual(check["unexplained"], 0)
        self.assertEqual(len(broadcom["adjustmentComponents"]["operatingIncome"]), 4)
        for symbol, expected in [
            ("068270", -247),
            ("329180", -465000),
        ]:
            b = business_build(
                copy.deepcopy(self.companies[symbol]), self.snapshot["asOf"]
            )
            self.assertEqual(
                b["reconciliations"]["operatingIncome"]["unexplained"], expected
            )
        b = business_build(
            copy.deepcopy(self.companies["068270"]), self.snapshot["asOf"]
        )
        self.assertEqual(
            b["reconciliations"]["revenue"]["reportedAdjustment"], -1844064074000
        )
        self.assertIn("내부거래", b["segmentRevenueBasis"])


if __name__ == "__main__":
    unittest.main()
