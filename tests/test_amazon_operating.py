import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from equitylab.amazon_operating import build
from equitylab.operating_model import calculate


class AmazonOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / "data/latest.json").read_text())
        s = json.loads((root / p["snapshot"]).read_text())
        cls.company = next(c for c in s["companies"] if c["id"] == "AMZN")
        cls.as_of = s["asOf"]
        cls.model = build(copy.deepcopy(cls.company), cls.as_of)

    def test_three_period_and_reported_trailing_cash_match_without_residual(self):
        m = self.model
        self.assertEqual(m["bridge"]["reportedCfo"], 161_403_000_000)
        self.assertEqual(sum(p["value"] for p in m["bridge"]["parts"]), 161_403_000_000)
        self.assertEqual(m["bridge"]["cashAfterInvestmentLeaseSbc"], -28_825_000_000)
        self.assertTrue(all(p["residual"] == 0 for p in m["bridge"]["periods"]))
        for r in m["facts"].values():
            if r["directTrailingFact"]:
                self.assertEqual(r["value"], r["directTrailingFact"]["value"])
        self.assertEqual(
            m["facts"]["tax"]["components"][1]["fact"]["value"], 27_759_000_000
        )

    def test_content_operating_lease_and_financing_costs_are_not_double_counted(self):
        m = self.model
        a = m["defaults"]
        revenue = sum(s["revenue"] for s in m["segments"])
        self.assertAlmostEqual(a["depreciation"] * revenue, 49_741_000_000, places=3)
        self.assertEqual(m["facts"]["daOther"]["value"], 75_200_000_000)
        self.assertAlmostEqual(a["capexStart"] * revenue, 169_007_000_000, places=3)
        self.assertAlmostEqual(a["leaseStart"] * revenue, 1_907_000_000, places=3)
        expected = (
            (93_712_000_000 + 1_329_000_000) * (1 - 39_615 / 175_466)
            + 49_741_000_000
            - 169_007_000_000
            - 1_907_000_000
        )
        self.assertAlmostEqual(m["initial"]["years"][0]["cash"], expected, places=3)
        self.assertIsNone(m["initial"]["price"])
        self.assertEqual(m["initial"]["status"], "nonpositive_terminal_or_value")

    def test_half_year_operating_capital_proxy_does_not_mix_a_trailing_denominator(
        self,
    ):
        m = self.model
        self.assertEqual(m["anchors"]["workingCashEffect"], -23_434_000_000)
        self.assertEqual(m["anchors"]["revenueIncrease"], 58_756_000_000)
        self.assertAlmostEqual(m["defaults"]["workingCapital"], 23_434 / 58_756)
        self.assertIn("최근 반기", m["growthLabel"])
        a = copy.deepcopy(m["defaults"])
        a["capexEnd"] = 0.05
        self.assertGreater(
            calculate(m, a)["terminal"]["cash"], m["initial"]["terminal"]["cash"]
        )
        self.assertTrue(calculate(m, a)["reinvestmentCaution"])

    def test_energy_periods_do_not_turn_unquantified_into_zero_or_aws_profit(self):
        e = self.model["energyNormalization"]
        self.assertEqual([p["value"] for p in e["periods"]], [None, 599_000_000, None])
        self.assertIsNone(e["trailingGain"])
        self.assertIn("was not significant", e["annualPolicy"]["text"])
        self.assertEqual([p["net"] for p in e["balances"]], [-27_000_000, 572_000_000])
        self.assertEqual(e["balanceChange"], 599_000_000)
        self.assertEqual(e["balanceGainGap"], 0)
        self.assertTrue(all(not p["assets"]["dimensions"] for p in e["balances"]))

    def test_partial_exclusion_changes_future_profit_and_tax_once_not_reported_cash(
        self,
    ):
        m = self.model
        a = copy.deepcopy(m["defaults"])
        a["excludedProfitStart"] = a["excludedProfitEnd"] = m["energyNormalization"][
            "knownPartRatio"
        ]
        r = calculate(m, a)
        y, old = r["years"][0], m["initial"]["years"][0]
        self.assertAlmostEqual(y["excludedProfit"], 599_000_000, places=4)
        self.assertAlmostEqual(
            y["unadjustedOperatingIncome"], old["operatingIncome"], places=4
        )
        self.assertAlmostEqual(
            old["operatingIncome"] - y["operatingIncome"], 599_000_000, places=4
        )
        self.assertAlmostEqual(old["tax"] - y["tax"], 599_000_000 * a["tax"], places=4)
        self.assertAlmostEqual(
            old["cash"] - y["cash"], 599_000_000 * (1 - a["tax"]), places=4
        )
        self.assertEqual(y["segments"], old["segments"])
        self.assertEqual(m["bridge"]["reportedCfo"], 161_403_000_000)
        self.assertAlmostEqual(
            r["terminal"]["excludedProfit"], 599_000_000 * 1.02, places=4
        )
        self.assertGreater(
            r["requiredTerminalCash"], m["initial"]["requiredTerminalCash"]
        )

    def test_normalization_inputs_are_explicit_and_losses_have_no_assumed_tax_credit(
        self,
    ):
        m = self.model
        a = copy.deepcopy(m["defaults"])
        del a["excludedProfitEnd"]
        with self.assertRaises(ValueError):
            calculate(m, a)
        a = copy.deepcopy(m["defaults"])
        a["excludedProfitStart"] = -0.001
        with self.assertRaises(ValueError):
            calculate(m, a)
        a["excludedProfitStart"] = a["excludedProfitEnd"] = 0.5
        r = calculate(m, a)
        self.assertLess(r["years"][0]["operatingIncome"], 0)
        self.assertEqual(r["years"][0]["tax"], 0)
        self.assertIsNone(r["price"])

    def test_reported_trailing_disagreement_or_unreviewed_scope_is_rejected(self):
        from equitylab.amazon_operating import select

        def altered(rows, tag, start, end, dimensions, unit):
            r = select(rows, tag, start, end, dimensions, unit)
            if (
                r
                and tag == "NetCashProvidedByUsedInOperatingActivities"
                and start == "2025-07-01"
            ):
                return dict(r, value=r["value"] + 1_000_000)
            return r

        with patch("equitylab.amazon_operating.select", side_effect=altered):
            with self.assertRaises(ValueError):
                build(copy.deepcopy(self.company), self.as_of)
        c = copy.deepcopy(self.company)
        c["segmentHistory"]["status"] = "partial"
        self.assertEqual(build(c, self.as_of)["status"], "source_review_required")
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "new"
        self.assertEqual(build(c, self.as_of)["status"], "source_review_required")


if __name__ == "__main__":
    unittest.main()
