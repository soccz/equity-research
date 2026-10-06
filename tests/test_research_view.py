import copy
import unittest
from equitylab import pipeline, research_view, dart, data, dart_corrections


class ResearchViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.companies = {c["id"]: c for c in pipeline.load_latest()["companies"]}

    def test_cash_conditions_do_not_generate_an_investment_preference(self):
        for c in self.companies.values():
            if c["status"] != "ready":
                continue
            v = research_view.build(c)
            self.assertIn(v["state"], ["관찰", "자료 확인"])
            self.assertIsNone(v["confirmation"]["expected"])
            self.assertFalse(v["financialApproval"])
            self.assertEqual(
                v["observations"][2]["value"], c["metrics"]["cashMarginChange"]
            )

    def test_missing_growth_is_data_gap_not_negative(self):
        c = copy.deepcopy(self.companies["MSFT"])
        c["metrics"]["revenueGrowth"] = None
        c["assessment"]["issues"] = ["비교 기간 미확보"]
        v = research_view.build(c)
        self.assertEqual(v["state"], "자료 확인")
        self.assertIsNone(v["observations"][0]["value"])

    def test_share_class_gaps_keep_price_unresolved(self):
        self.assertEqual(
            research_view.build(self.companies["005380"])["priceStatus"], "unresolved"
        )
        self.assertEqual(
            research_view.build(self.companies["MSFT"])["priceStatus"],
            "operating_workspace",
        )
        p = research_view.build(self.companies["MSFT"])["priceRequirement"]
        model = self.companies["MSFT"]["operatingModel"]
        self.assertEqual(p["kind"], "operating_terminal")
        self.assertEqual(
            p["referenceTerminalCash"], model["initial"]["terminal"]["cash"]
        )
        self.assertEqual(
            p["requiredTerminalCash"], model["initial"]["requiredTerminalCash"]
        )
        self.assertNotIn("requiredAnnualCash", p)
        self.assertEqual(p["assumptions"], model["defaults"])
        self.assertIsNone(
            research_view.build(self.companies["005380"])["priceRequirement"]
        )

    def test_attachment_correction_does_not_replace_annual_financials(self):
        c = next(c for c in data.UNIVERSE if c["id"] == "012450")
        rows = [
            dict(
                corp_code=c["dartCorpCode"],
                stock_code=c["id"],
                rcept_dt=d,
                rcept_no=r,
                report_nm=n,
            )
            for d, r, n in [
                ("20260316", "20260316001112", "사업보고서 (2025.12)"),
                ("20260319", "20260319000633", "[첨부정정]사업보고서 (2025.12)"),
            ]
        ]
        filing, code = dart.choose_filing(rows, c, "2026-09-29")
        self.assertEqual(filing["rcept_no"], "20260316001112")
        self.assertEqual(code, "11011")
        self.assertEqual(dart_corrections.notes(c, "2026-03-18"), [])
        self.assertEqual(len(dart_corrections.notes(c, "2026-03-19")), 1)
        # Unreviewed later corrections must continue to win by filing date.
        rows.append(
            dict(
                rows[0],
                rcept_no="20260401000100",
                rcept_dt="20260401",
                report_nm="[기재정정]사업보고서 (2025.12)",
            )
        )
        self.assertEqual(
            dart.choose_filing(rows, c, "2026-09-29")[0]["rcept_no"], "20260401000100"
        )
