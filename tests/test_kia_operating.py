import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from equitylab.kia_operating import build, select
from equitylab.operating_model import calculate


class KiaOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        pointer = json.loads((root / "data/latest.json").read_text())
        snapshot = json.loads((root / pointer["snapshot"]).read_text())
        cls.company = next(c for c in snapshot["companies"] if c["id"] == "000270")
        cls.as_of = snapshot["asOf"]
        cls.model = build(copy.deepcopy(cls.company), cls.as_of)

    def test_cash_and_each_provision_period_reconcile_with_original_amounts(self):
        m = self.model
        self.assertEqual(m["bridge"]["reportedCfo"], 10_868_500_000_000)
        self.assertEqual(
            sum(p["value"] for p in m["bridge"]["parts"]), 10_868_500_000_000
        )
        for p in m["bridge"]["parts"]:
            self.assertEqual(
                p["value"],
                sum(
                    x["coefficient"] * x["fact"]["value"]
                    for x in p["fact"]["components"]
                ),
            )
        for p in m["warranty"]["periods"]:
            self.assertEqual(
                p["closing"]["value"],
                p["opening"]["value"] + p["added"] - p["used"] + p["other"],
            )
        current = m["warranty"]["periods"][1]
        self.assertEqual(current["closing"]["value"], 9_289_232_000_000)
        self.assertEqual(current["cashAdjustment"], 2_017_760_000_000)
        self.assertEqual(current["sellingExpense"], 2_105_752_000_000)
        self.assertEqual(m["warranty"]["additionsLessCashAdjustment"], 911_285_000_000)

    def test_half_year_proxy_excludes_warranty_and_annual_cash_includes_intangibles(
        self,
    ):
        m = self.model
        revenue = m["segments"][0]["revenue"]
        self.assertEqual(revenue, 119_312_710_000_000)
        self.assertEqual(len(m["segments"]), 1)
        self.assertEqual(m["anchors"]["revenueIncrease"], 5_171_791_000_000)
        self.assertEqual(m["anchors"]["workingCashEffect"], 1_472_078_000_000)
        self.assertAlmostEqual(
            m["defaults"]["capexStart"] * revenue, 5_202_111_000_000, delta=0.01
        )
        self.assertAlmostEqual(
            m["defaults"]["leaseStart"] * revenue, 74_115_000_000, delta=0.01
        )
        self.assertNotEqual(m["defaults"]["workingCapital"], 0)

    def test_extra_warranty_use_reduces_cash_once_without_changing_reported_margin(
        self,
    ):
        m = self.model
        a = copy.deepcopy(m["defaults"])
        a["warrantyUseStart"] += 0.01
        a["warrantyUseEnd"] += 0.01
        r = calculate(m, a)
        for before, after in zip(
            m["initial"]["years"] + [m["initial"]["terminal"]],
            r["years"] + [r["terminal"]],
        ):
            self.assertEqual(after["operatingIncome"], before["operatingIncome"])
            self.assertAlmostEqual(
                before["cash"] - after["cash"], after["revenue"] * 0.01, delta=0.01
            )
        self.assertLess(r["price"], m["initial"]["price"])
        a.pop("warrantyAccrual")
        with self.assertRaises(ValueError):
            calculate(m, a)

    def test_source_change_or_offsetting_period_errors_do_not_pass(self):
        def corrupted(rows, tag, start, end, dimensions=(), unit=None):
            result = select(rows, tag, start, end, dimensions, unit)
            if (
                result
                and tag == "ProvisionUsedOtherProvisions"
                and end in {"2025-12-31", "2025-06-30"}
            ):
                return dict(result, value=result["value"] + 1_000_000)
            return result

        with patch("equitylab.kia_operating.select", side_effect=corrupted):
            with self.assertRaises(ValueError):
                build(copy.deepcopy(self.company), self.as_of)
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "different"
        self.assertEqual(build(c, self.as_of)["status"], "source_review_required")


if __name__ == "__main__":
    unittest.main()
