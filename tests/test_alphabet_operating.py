import copy
import importlib.util
import unittest
from unittest.mock import patch
from equitylab.pipeline import load_latest
from equitylab import alphabet_operating as candidate
from equitylab import operating_model as engine


class AlphabetOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_latest()
        cls.company = next(c for c in cls.snapshot["companies"] if c["id"] == "GOOGL")
        cls.model = candidate.build(copy.deepcopy(cls.company), cls.snapshot["asOf"])

    def test_exact_cash_and_corporate_scope(self):
        m = self.model
        self.assertEqual(m["bridge"]["reportedCfo"], 185_675_000_000)
        self.assertEqual(sum(p["value"] for p in m["bridge"]["parts"]), 185_675_000_000)
        self.assertTrue(
            all(
                p["residual"] == p["incomeResidual"] == 0
                for p in m["bridge"]["periods"]
            )
        )
        first, second, _ = m["bridge"]["periods"]
        self.assertIn(
            "IncreaseDecreaseInAccruedRevenueShare", {p["tag"] for p in first["parts"]}
        )
        self.assertNotIn(
            "IncreaseDecreaseInInventories", {p["tag"] for p in first["parts"]}
        )
        self.assertIn(
            "IncreaseDecreaseInInventories", {p["tag"] for p in second["parts"]}
        )
        self.assertEqual(m["anchors"]["revenueAdjustment"], -349_000_000)
        y = m["initial"]["years"][0]
        self.assertAlmostEqual(
            y["segmentOperatingIncome"] - y["corporateCost"], 147_628_000_000, places=3
        )
        self.assertAlmostEqual(y["corporateCost"], 21_541_000_000, places=3)

    def test_lease_prepayment_is_added_only_when_separately_reported(self):
        f = self.model["facts"]
        self.assertEqual(f["leaseCash"]["value"], 3_361_000_000)
        self.assertEqual(
            [c["fact"]["value"] for c in f["leaseCash"]["components"]],
            [1_988_000_000, 840_000_000, 302_000_000, 835_000_000],
        )
        self.assertEqual(
            [c["coefficient"] for c in f["leaseCash"]["components"]], [1, 1, -1, 1]
        )
        self.assertNotIn(
            1_100_000_000, [c["fact"]["value"] for c in f["leaseCash"]["components"]]
        )

    def test_corporate_change_flows_through_tax_once(self):
        m = self.model
        a = copy.deepcopy(m["defaults"])
        a["corporateStart"] += 0.01
        a["corporateEnd"] += 0.01
        r = engine.calculate(m, a)
        for old, new in zip(
            [*m["initial"]["years"], m["initial"]["terminal"]],
            [*r["years"], r["terminal"]],
        ):
            self.assertAlmostEqual(
                old["cash"] - new["cash"],
                old["revenue"] * 0.01 * (1 - a["tax"]),
                places=3,
            )
            self.assertEqual(old["segments"], new["segments"])
        self.assertIsNone(r["price"])

    def test_loss_segment_not_clipped_and_rights_never_bypassed(self):
        m = self.model
        self.assertLess(m["defaults"]["segments"][2]["marginEnd"], -5)
        a = copy.deepcopy(m["defaults"])
        a["capexEnd"] = 0.05
        self.assertGreater(engine.calculate(m, a)["equityValue"], 0)
        self.assertIsNone(engine.calculate(m, a)["price"])
        self.assertIsNone(engine.calculate(m, a)["requiredTerminalCash"])
        del a["corporateEnd"]
        with self.assertRaises(ValueError):
            engine.calculate(m, a)
        a = copy.deepcopy(m["defaults"])
        a["corporateStart"] = -0.01
        with self.assertRaises(ValueError):
            engine.calculate(m, a)

    def test_each_period_checked_before_netting(self):
        original = candidate.select

        def altered(rows, tag, start, end, dimensions, unit):
            r = original(rows, tag, start, end, dimensions, unit)
            if r and tag == "ShareBasedCompensation":
                if end == "2025-12-31":
                    return dict(r, value=r["value"] + 1e6)
                if end == "2026-06-30":
                    return dict(r, value=r["value"] - 1e6)
            return r

        with patch.object(candidate, "select", side_effect=altered):
            with self.assertRaisesRegex(ValueError, "period cash"):
                candidate.build(copy.deepcopy(self.company), self.snapshot["asOf"])
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "new"
        self.assertEqual(
            candidate.build(c, self.snapshot["asOf"])["status"],
            "source_review_required",
        )

    def test_other_models_preserve_stored_financial_results(self):
        for c in self.snapshot["companies"]:
            m = c.get("operatingModel")
            if c["id"] != "GOOGL" and m and m["status"] == "research_workspace":
                self.assertEqual(
                    engine.calculate(m, m["defaults"]), m["initial"], c["id"]
                )

    def test_historical_lease_caption_cannot_be_replaced(self):
        original = candidate.read_verified

        def changed(path, expected):
            if path.suffix == ".html":
                return b"<html>unreviewed finance lease wording</html>"
            return original(path, expected)

        with patch.object(candidate, "read_verified", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "lease caption"):
                candidate.build(copy.deepcopy(self.company), self.snapshot["asOf"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
