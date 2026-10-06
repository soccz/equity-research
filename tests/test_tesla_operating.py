import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from equitylab.tesla_operating import build, select
from equitylab.operating_model import calculate


class TeslaOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / "data/latest.json").read_text())
        s = json.loads((root / p["snapshot"]).read_text())
        cls.company = next(c for c in s["companies"] if c["id"] == "TSLA")
        cls.as_of = s["asOf"]
        cls.model = build(copy.deepcopy(cls.company), cls.as_of)

    def test_cash_product_and_unallocated_costs_reconcile_every_period(self):
        m = self.model
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [14_747e6, 8_634e6, 4_696e6],
        )
        self.assertEqual(m["bridge"]["reportedCfo"], 18_685e6)
        for p in m["bridge"]["parts"]:
            self.assertEqual(
                p["value"],
                sum(
                    x["coefficient"] * x["fact"]["value"]
                    for x in p["fact"]["components"]
                ),
            )
        self.assertEqual(sum(s["revenue"] for s in m["segments"]), 103_619e6)
        self.assertEqual(sum(s["grossProfit"] for s in m["segments"]), 19_534e6)
        self.assertEqual(m["initial"]["years"][0]["operatingIncome"], 4_372e6)
        self.assertNotIn("operatingIncome", m["initial"]["years"][0]["segments"][0])
        self.assertEqual(m["facts"]["otherOperating"]["value"], 400e6)

    def test_same_taxonomy_tag_does_not_mix_comprehensive_income_and_cash(self):
        m = self.model
        gain = m["facts"]["equityGain"]
        self.assertEqual(gain["value"], 1_005e6)
        self.assertEqual(gain["excludedAnnualSameTag"]["value"], -7e6)
        self.assertIn("net of tax", gain["excludedAnnualLabel"]["text"])
        self.assertEqual(
            m["facts"]["ProfitLoss"]["components"][0]["fact"]["value"], 3_855e6
        )
        self.assertEqual(m["facts"]["tax"]["components"][0]["fact"]["value"], 1_423e6)

    def test_future_cash_keeps_sbc_and_leased_asset_costs_and_deducts_minority_once(
        self,
    ):
        m = self.model
        r = m["initial"]["years"][0]
        self.assertEqual(r["depreciation"], 5_440e6)
        self.assertEqual(r["minority"], 153e6)
        expected = (
            (4_372e6 + 1_410e6) * (1 - m["defaults"]["tax"])
            + 5_440e6
            - 12_923e6
            - 103_619e6 * 7 / 50_623
            - 74e6
            - 153e6
        )
        self.assertAlmostEqual(r["cash"], expected, places=4)
        self.assertIsNone(m["initial"]["price"])
        a = copy.deepcopy(m["defaults"])
        a["minority"] = 0
        self.assertAlmostEqual(
            calculate(m, a)["years"][0]["cash"] - r["cash"], 153e6, places=4
        )

    def test_credit_shutdown_and_investment_floor_have_explicit_cost_effects(self):
        m = self.model
        a = copy.deepcopy(m["defaults"])
        a["segments"][1]["growthStart"] = a["segments"][1]["growthEnd"] = -1
        ratio = 103_619 / (103_619 - 1_485)
        for key in [
            "researchStart",
            "researchEnd",
            "sellingStart",
            "sellingEnd",
            "otherOperatingStart",
            "otherOperatingEnd",
        ]:
            a[key] *= ratio
        r = calculate(m, a)
        self.assertTrue(
            all(y["segments"][1]["revenue"] == 0 for y in r["years"] + [r["terminal"]])
        )
        self.assertAlmostEqual(
            r["years"][0]["operatingIncome"], (4_372 - 1_485) * 1e6, places=4
        )
        a = copy.deepcopy(m["defaults"])
        a["capexStart"] = a["capexEnd"] = m["investmentStress"]["minimumRatio"]
        self.assertAlmostEqual(
            calculate(m, a)["years"][0]["capex"],
            25e9 + 103_619e6 * 7 / 50_623,
            places=4,
        )
        a.pop("researchEnd")
        with self.assertRaises(ValueError):
            calculate(m, a)

    def test_source_changes_and_cancelling_period_errors_are_rejected(self):
        def corrupted(rows, tag, start, end, dimensions=(), unit=None):
            r = select(rows, tag, start, end, dimensions, unit)
            if (
                r
                and tag == "ResearchAndDevelopmentExpense"
                and end in {"2025-12-31", "2025-06-30"}
            ):
                return dict(r, value=r["value"] + 1e6)
            return r

        with patch("equitylab.tesla_operating.select", side_effect=corrupted):
            with self.assertRaises(ValueError):
                build(copy.deepcopy(self.company), self.as_of)
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(build(c, self.as_of)["status"], "source_review_required")


if __name__ == "__main__":
    unittest.main()
