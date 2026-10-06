import copy, json, sys, unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import micron_operating as mu
from equitylab.operating_model import calculate


class MicronOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = json.loads(
            (Path(__file__).parent / "company-candidate.json").read_text()
        )
        cls.model = mu.build(copy.deepcopy(cls.company), "2026-09-29")

    def test_all_periods_and_recast_segments_reconcile(self):
        m = self.model
        self.assertEqual(m["bridge"]["reportedCfo"], 51_432_000_000)
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [17_525_000_000, 45_702_000_000, 11_795_000_000],
        )
        self.assertEqual(sum(s["revenue"] for s in m["segments"]), 90_274_000_000)
        self.assertEqual([p["residual"] for p in m["bridge"]["periods"]], [0, 0, 0])
        self.assertEqual(
            sum(p["value"] for p in m["bridge"]["parts"]), m["bridge"]["reportedCfo"]
        )

    def test_noncurrent_tax_timing_does_not_become_customer_funding(self):
        self.assertEqual(self.model["anchors"]["workingCashEffect"], -14_697_000_000)
        self.assertEqual(self.model["anchors"]["revenueIncrease"], 52_896_000_000)
        self.assertAlmostEqual(
            self.model["defaults"]["workingCapital"], 14_697 / 52_896
        )
        self.assertIn("5.203bn", self.model["anchorSummary"])
        self.assertTrue(
            any("$422 million" in p["text"] for p in self.model["passages"])
        )

    def test_historical_incentives_are_not_silently_netted_from_future_capex(self):
        m = self.model
        self.assertEqual(m["facts"]["governmentIncentives"]["value"], 3_700_000_000)
        self.assertEqual(m["facts"]["capex"]["value"], 25_260_000_000)
        self.assertEqual(m["initial"]["years"][0]["capex"], 25_260_000_000)
        self.assertIn("정부지원 가산", m["observedResidualLabel"])

    def test_missing_current_lease_and_ppe_remain_missing(self):
        a = self.model["anchors"]
        self.assertIsNone(a["trailingFinanceLeasePrincipalPaid"])
        self.assertIsNone(a["trailingPpeDepreciation"])
        self.assertEqual(a["annualFinanceLeasePaid"]["value"], 323_000_000)
        self.assertEqual(a["annualPpeDepreciation"]["decimals"], "-7")
        self.assertAlmostEqual(
            a["assumedPpeDepreciation"], 9_011_000_000 * 8_280 / 8_352
        )
        self.assertEqual(self.model["defaults"]["leaseStart"], 323 / 37_378)

    def test_segment_margin_stress_has_a_separate_tax_effect(self):
        m = self.model
        a = copy.deepcopy(m["defaults"])
        a["segments"][0]["marginEnd"] -= 0.1
        r = calculate(m, a)
        for i, (old, new) in enumerate(zip(m["initial"]["years"], r["years"]), 1):
            self.assertAlmostEqual(
                old["cash"] - new["cash"],
                31_345_000_000 * 0.1 * i / 5 * (1 - a["tax"]),
                places=3,
            )
            self.assertEqual(old["segments"][1:], new["segments"][1:])

    def test_opposite_cash_errors_cannot_cancel_across_periods(self):
        original = mu.select

        def altered(rows, tag, start, end, *args):
            r = original(rows, tag, start, end, *args)
            if (
                r
                and tag == "OtherOperatingActivitiesCashFlowStatement"
                and end == "2025-08-28"
            ):
                return dict(r, value=r["value"] + 1e8)
            if (
                r
                and tag == "IncreaseDecreaseInOtherNoncurrentLiabilities"
                and end == "2026-05-28"
            ):
                return dict(r, value=r["value"] - 1e8)
            return r

        with patch.object(mu, "select", side_effect=altered):
            with self.assertRaisesRegex(ValueError, "period cash"):
                mu.build(copy.deepcopy(self.company), "2026-09-29")

    def test_changed_sources_cannot_inherit_the_review(self):
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(mu.build(c, "2026-09-29")["status"], "source_review_required")
        c = copy.deepcopy(self.company)
        c["segmentHistory"]["review"]["annualSource"]["sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "identity"):
            mu.build(c, "2026-09-29")


if __name__ == "__main__":
    unittest.main(verbosity=2)
