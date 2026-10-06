import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from equitylab.pipeline import load_latest

STAGE = Path(__file__).resolve().parent


def module(file, name):
    spec = importlib.util.spec_from_file_location("equitylab." + name, STAGE / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


calc = module("operating_model_candidate.py", "samsung_candidate_calc")
samsung = module("samsung_operating.py", "samsung_candidate")


class SamsungCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.company = copy.deepcopy(
            next(c for c in s["companies"] if c["id"] == "005930")
        )
        with patch("equitylab.operating_model.calculate", calc.calculate):
            cls.model = samsung.build(copy.deepcopy(cls.company), s["asOf"])

    def test_cash_reconciles_each_period_before_adding_trailing_values(self):
        m = self.model
        self.assertEqual(m["bridge"]["reportedCfo"], 196_729_338_000_000)
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [85_315_148_000_000, 145_355_192_000_000, 33_941_002_000_000],
        )
        self.assertTrue(all(p["residual"] == 0 for p in m["bridge"]["periods"]))
        self.assertEqual(
            sum(p["value"] for p in m["bridge"]["parts"]), m["bridge"]["reportedCfo"]
        )

    def test_internal_sales_are_not_external_revenue_or_deducted_twice_from_profit(
        self,
    ):
        m = self.model
        y = m["initial"]["years"][0]
        self.assertEqual(y["segmentRevenue"], 528_412_216_000_000)
        self.assertEqual(y["internalRevenue"], 43_140_184_000_000)
        self.assertEqual(y["revenue"], 485_272_032_000_000)
        self.assertEqual(y["operatingIncome"], 178_817_010_000_000)
        self.assertEqual(y["workingCapital"], 0)

    def test_unallocated_profit_stays_distinct_from_disclosed_segment_profit(self):
        m = self.model
        self.assertEqual(
            [p["unallocatedOperatingIncome"] for p in m["consolidation"]["periods"]],
            [242_924_000_000, 36_860_000_000, 131_863_000_000],
        )
        self.assertEqual(
            m["consolidation"]["unallocatedOperatingIncome"], 147_921_000_000
        )
        self.assertEqual(m["defaults"]["otherProfitStart"], 0)
        a = copy.deepcopy(m["defaults"])
        a["otherProfitStart"] = a["otherProfitEnd"] = (
            m["consolidation"]["unallocatedOperatingIncome"]
            / m["consolidation"]["reportedRevenue"]
        )
        y = calc.calculate(m, a)["years"][0]
        self.assertAlmostEqual(y["operatingIncome"], 178_964_931_000_000, delta=1)

    def test_working_capital_uses_previous_consolidated_revenue_including_terminal(
        self,
    ):
        m = self.model
        a = copy.deepcopy(m["defaults"])
        a["eliminationEnd"] += 0.05
        r = calc.calculate(m, a)
        prior = m["consolidation"]["reportedRevenue"]
        for y in [*r["years"], r["terminal"]]:
            self.assertAlmostEqual(
                y["workingCapital"],
                (y["revenue"] - prior) * a["workingCapital"],
                delta=0.01,
            )
            self.assertAlmostEqual(
                y["revenue"], y["segmentRevenue"] - y["internalRevenue"], delta=0.01
            )
            prior = y["revenue"]
        self.assertLess(r["years"][1]["workingCapital"], 0)

    def test_reported_lease_and_minority_proxy_are_each_deducted_once(self):
        m = self.model
        y = m["initial"]["years"][0]
        self.assertEqual(m["facts"]["lease"]["value"], 1_334_514_000_000)
        self.assertAlmostEqual(y["minority"], 1_048_052_000_000, delta=0.01)
        self.assertAlmostEqual(
            y["cash"],
            y["operatingIncome"]
            + y["netInterest"]
            - y["tax"]
            + y["depreciation"]
            - y["workingCapital"]
            - y["capex"]
            - y["leasePrincipal"]
            - y["minority"],
            delta=0.01,
        )
        self.assertIsNone(m["anchors"]["actualShareCompensationReplacement"])
        self.assertIsNone(m["bridge"]["cashAfterInvestmentLeaseSbc"])
        self.assertIsNone(m["initial"]["price"])

    def test_invalid_elimination_and_other_profit_inputs_are_rejected(self):
        for key, value in [
            ("eliminationStart", 1),
            ("eliminationEnd", -0.001),
            ("otherProfitStart", 0.101),
            ("otherProfitEnd", -0.101),
            ("minority", 1.1),
        ]:
            a = copy.deepcopy(self.model["defaults"])
            a[key] = value
            with self.assertRaisesRegex(ValueError, "consolidation"):
                calc.calculate(self.model, a)

    def test_changed_annual_cash_or_corpus_requires_a_new_review(self):
        original = samsung.select

        def changed(rows, tag, start, end, *args):
            r = original(rows, tag, start, end, *args)
            return (
                dict(r, value=r["value"] + 1e6)
                if r
                and tag == "AdjustmentsForReconcileProfitLoss"
                and end == "2025-12-31"
                else r
            )

        with patch.object(samsung, "select", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "cash or segment"):
                samsung.build(copy.deepcopy(self.company), "2026-09-29")
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(
            samsung.build(c, "2026-09-29")["status"], "source_review_required"
        )


if __name__ == "__main__":
    unittest.main()
