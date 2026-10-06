import copy
import unittest
from bs4 import BeautifulSoup
from equitylab.business_drivers import build, table_numbers, bridge, row
from equitylab.business_insights import build as insight
from equitylab.narrative import load
from equitylab.pipeline import load_latest


class BusinessDriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.companies = {c["id"]: c for c in load_latest()["companies"]}

    def test_foundry_loss_improvement_preserves_adverse_product_effect_and_residual(
        self,
    ):
        result = insight(self.companies["INTC"])["drivers"]
        values = [r["value"] for r in result["charts"][0]["rows"]]
        self.assertEqual(values, [-5488, 1800, -830, -8, -4526])
        self.assertEqual(values[-1] - values[0], 962)
        self.assertFalse(result["financialApproval"])
        self.assertIn("($ In Millions)", result["sourceTable"]["text"])
        self.assertIn("잔차", result["charts"][0]["rows"][3]["basis"])

    def test_qct_and_auto_bridges_keep_quarter_and_nine_month_contributions_distinct(
        self,
    ):
        result = insight(self.companies["QCOM"])["drivers"]
        full, quarter, ytd = result["charts"]
        self.assertEqual(
            [r["value"] for r in full["rows"]], [8993, -1242, 604, 149, 8504]
        )
        self.assertEqual([r["value"] for r in quarter["rows"]], [984, 381, 223, 1588])
        self.assertEqual([r["value"] for r in ytd["rows"]], [2904, 560, 551, 4015])
        self.assertIn("3분기", quarter["period"])
        self.assertIn("9개월", ytd["period"])

    def test_changed_company_explanation_cannot_silently_retain_old_amount(self):
        c = self.companies["INTC"]
        ps = copy.deepcopy(load(c)["passages"])
        p = next(p for p in ps if p["id"] == "79e1f12b2bd591286d1c")
        p["text"] = p["text"].replace(
            "$830 million of lower product profit", "unquantified product effect"
        )
        with self.assertRaisesRegex(ValueError, "explanation changed"):
            build(c, ps)

    def test_loss_parentheses_are_negative_and_changed_columns_fail(self):
        table = BeautifulSoup(
            "<table><tr><td>Operating loss</td><td>(100)</td><td>(240)</td></tr></table>",
            "html.parser",
        ).table
        self.assertEqual(table_numbers(table, "Operating loss", 2), [-100, -240])
        with self.assertRaisesRegex(ValueError, "columns changed"):
            table_numbers(table, "Operating loss", 4)
        with self.assertRaisesRegex(ValueError, "do not reconcile"):
            bridge(
                "test",
                "period",
                [row("start", 10, "start"), row("change", 4), row("end", 15, "end")],
                "",
                [],
            )

    def test_changed_filing_holds_the_numerical_bridge_together_with_authored_reading(
        self,
    ):
        c = copy.deepcopy(self.companies["QCOM"])
        c["narrative"]["accession"] = "changed"
        result = insight(c)
        self.assertEqual(result["status"], "stale")
        self.assertNotIn("drivers", result)
