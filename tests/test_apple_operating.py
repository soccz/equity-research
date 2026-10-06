import copy
import unittest
from unittest.mock import patch

from equitylab import apple_operating as apple
from equitylab.operating_model import calculate
from equitylab.pipeline import load_latest


class AppleOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_latest()
        cls.company = next(c for c in cls.snapshot["companies"] if c["id"] == "AAPL")
        cls.model = apple.build(copy.deepcopy(cls.company), cls.snapshot["asOf"])

    def test_reported_cash_and_product_profit_each_period(self):
        m = self.model
        self.assertEqual(m["bridge"]["reportedCfo"], 146_724_000_000)
        self.assertEqual(sum(p["value"] for p in m["bridge"]["parts"]), 146_724_000_000)
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [111_482_000_000, 116_996_000_000, 81_754_000_000],
        )
        self.assertEqual(
            [s["revenue"] for s in m["segments"]], [346_345_000_000, 120_478_000_000]
        )
        self.assertEqual(
            [s["grossProfit"] for s in m["segments"]], [135_516_000_000, 91_607_000_000]
        )
        self.assertEqual(m["sourcePeriod"], ["2025-06-29", "2026-06-27"])
        self.assertEqual(m["growthLabel"], "최근 9개월 전년 대비")

    def test_lease_balance_and_maturity_do_not_become_paid_cash(self):
        a = self.model["anchors"]
        self.assertEqual(a["annualCurrentFinanceLeaseLiability"]["value"], 538_000_000)
        self.assertEqual(
            a["annualNextYearGrossFinanceLeasePayments"]["value"], 563_000_000
        )
        self.assertIsNone(a["trailingFinanceLeasePrincipalPaid"])
        self.assertIsNone(a["trailingPpeDepreciation"])
        self.assertEqual(
            self.model["defaults"]["leaseStart"], 538_000_000 / 416_161_000_000
        )
        self.assertEqual(
            self.model["defaults"]["depreciation"], 8_000_000_000 / 416_161_000_000
        )
        self.assertIn("금융리스 원금 차감 전", self.model["observedResidualLabel"])
        self.assertIsNone(self.model["cashAnchors"][-1]["value"])

    def test_product_margin_and_lease_stress_have_separate_cash_effects(self):
        m = self.model
        changed = copy.deepcopy(m["defaults"])
        changed["segments"][0]["marginEnd"] -= 0.01
        r = calculate(m, changed)
        for i, (old, new) in enumerate(zip(m["initial"]["years"], r["years"]), 1):
            expected = m["segments"][0]["revenue"] * 0.01 * i / 5 * (1 - changed["tax"])
            self.assertAlmostEqual(old["cash"] - new["cash"], expected, places=3)
            self.assertEqual(old["segments"][1], new["segments"][1])
        changed = copy.deepcopy(m["defaults"])
        changed["leaseStart"] += 0.001
        changed["leaseEnd"] += 0.001
        r = calculate(m, changed)
        for old, new in zip(m["initial"]["years"], r["years"]):
            self.assertAlmostEqual(
                old["cash"] - new["cash"], old["revenue"] * 0.001, places=3
            )
            self.assertEqual(old["tax"], new["tax"])

    def test_offsetting_period_errors_are_rejected(self):
        original = apple.select

        def altered(rows, tag, start, end, dimensions, unit):
            r = original(rows, tag, start, end, dimensions, unit)
            if r and tag == "OtherNoncashIncomeExpense":
                if end == "2025-09-27":
                    return dict(r, value=r["value"] + 1e6)
                if end == "2026-06-27":
                    return dict(r, value=r["value"] - 1e6)
            return r

        with patch.object(apple, "select", side_effect=altered):
            with self.assertRaisesRegex(ValueError, "period product/income/cash"):
                apple.build(copy.deepcopy(self.company), self.snapshot["asOf"])

    def test_missing_fact_does_not_use_zero_or_another_period(self):
        original = apple.select

        def missing(rows, tag, start, end, dimensions, unit):
            if tag == "IncreaseDecreaseInOtherReceivables" and end == "2026-06-27":
                return None
            return original(rows, tag, start, end, dimensions, unit)

        with patch.object(apple, "select", side_effect=missing):
            with self.assertRaisesRegex(ValueError, "Apple source missing"):
                apple.build(copy.deepcopy(self.company), self.snapshot["asOf"])

    def test_changed_corpus_requires_review_and_original_caption_is_required(self):
        c = copy.deepcopy(self.company)
        c["narrative"]["evidenceHash"] = "future"
        self.assertEqual(
            apple.build(c, self.snapshot["asOf"])["status"], "source_review_required"
        )
        original = apple.extract

        def changed(blob):
            return [
                dict(p, text="lease payment") if p["ordinal"] == 664 else p
                for p in original(blob)
            ]

        with patch.object(apple, "extract", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "caption changed"):
                apple.build(copy.deepcopy(self.company), self.snapshot["asOf"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
