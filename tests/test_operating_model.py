import copy
import json
import unittest
from pathlib import Path

from equitylab.operating_model import build, calculate


class OperatingModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        pointer = json.loads((root / "data/latest.json").read_text())
        s = json.loads((root / pointer["snapshot"]).read_text())
        cls.company = next(c for c in s["companies"] if c["id"] == "MSFT")
        cls.model = build(copy.deepcopy(cls.company), s["asOf"])

    def test_actual_source_bridge_has_no_unexplained_cash(self):
        b = self.model["bridge"]
        self.assertEqual(b["reportedCfo"], 182_935_000_000)
        self.assertEqual(sum(p["value"] for p in b["parts"]), b["reportedCfo"])
        self.assertEqual(b["cashAfterInvestmentLeaseSbc"], 51_481_000_000)
        self.assertEqual(self.model["anchors"]["daOtherDifference"], -466_000_000)

    def test_zero_growth_cash_uses_business_profits_not_reported_cfo(self):
        r = self.model["initial"]
        a = self.model["defaults"]
        # Separate manual arithmetic from the path implementation: stock pay is
        # already expensed in operating income and is not added to future cash.
        expected = (
            (155_237_000_000 + 250_000_000) * (1 - 32_185 / 165_934)
            + 39_000_000_000
            - 115_948_000_000
            - 3_101_000_000
        )
        self.assertAlmostEqual(r["years"][0]["cash"], expected, places=3)
        self.assertEqual(r["years"][0]["workingCapital"], 0)
        self.assertNotEqual(
            r["years"][0]["cash"], self.model["bridge"]["cashAfterInvestmentLeaseSbc"]
        )
        # Terminal growth entails extra operating-capital investment.
        self.assertAlmostEqual(
            r["terminal"]["workingCapital"],
            331_839_000_000 * 0.02 * a["workingCapital"],
            places=3,
        )
        self.assertGreater(r["terminal"]["workingCapital"], 0)

    def test_business_growth_and_reinvestment_have_distinct_effects(self):
        a = copy.deepcopy(self.model["defaults"])
        a["segments"][1]["growthStart"] = 0.1
        a["segments"][1]["growthEnd"] = 0.1
        r = calculate(self.model, a)
        self.assertAlmostEqual(
            r["years"][0]["segments"][1]["revenue"], 137_791_000_000 * 1.1, places=3
        )
        self.assertEqual(r["years"][0]["segments"][0]["revenue"], 139_996_000_000)
        a["capexEnd"] += 0.05
        self.assertLess(calculate(self.model, a)["equityValue"], r["equityValue"])

    def test_required_terminal_cash_reconciles_observed_market_cap(self):
        r, a = self.model["initial"], self.model["defaults"]
        cap = (
            r["explicitPv"]
            + r["requiredTerminalCash"]
            / (a["discount"] - a["terminal"])
            / (1 + a["discount"]) ** 5
        )
        self.assertAlmostEqual(cap, self.model["security"]["marketCapProxy"], places=2)

    def test_missing_invalid_and_negative_paths_do_not_become_zero_values(self):
        for key, value in [
            ("tax", None),
            ("capexEnd", float("nan")),
            ("discount", 0.01),
            ("leaseEnd", -0.01),
        ]:
            a = copy.deepcopy(self.model["defaults"])
            a[key] = value
            with self.assertRaises(ValueError):
                calculate(self.model, a)
        a = copy.deepcopy(self.model["defaults"])
        a["capexEnd"] = 1
        r = calculate(self.model, a)
        self.assertIsNone(r["price"])
        self.assertLess(r["terminal"]["cash"], 0)

    def test_unsupported_or_new_filing_requires_new_source_review(self):
        c = copy.deepcopy(self.company)
        c["narrative"]["accession"] = "another-filing"
        self.assertEqual(build(c, "2026-09-29")["status"], "source_review_required")
        c["id"] = "unsupported"
        self.assertIsNone(build(c, "2026-09-29"))


if __name__ == "__main__":
    unittest.main()
