import copy
import unittest
from unittest.mock import patch

from equitylab.pipeline import load_latest
from equitylab import jnj_operating as jnj
from equitylab.operating_model import calculate


class JnjOperatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.c = next(c for c in s["companies"] if c["id"] == "JNJ")
        cls.asof = s["asOf"]
        cls.m = jnj.build(copy.deepcopy(cls.c), cls.asof)

    def test_cash_reconciles_three_periods_without_removing_the_same_talc_reversal_twice(
        self,
    ):
        m = self.m
        self.assertEqual(
            [p["reportedCfo"] for p in m["bridge"]["periods"]],
            [24530e6, 11130e6, 8052e6],
        )
        self.assertTrue(all(p["residual"] == 0 for p in m["bridge"]["periods"]))
        self.assertEqual(m["bridge"]["reportedCfo"], 27608e6)
        self.assertEqual(m["facts"]["pretax"]["value"], 25196e6)
        self.assertEqual(m["facts"]["unallocated"]["value"], 1778e6)

    def test_pretax_income_is_preserved_in_each_year_and_segment(self):
        r = calculate(self.m, self.m["defaults"])
        first = r["years"][0]
        self.assertEqual(first["segmentPretaxIncome"], 26974e6)
        self.assertEqual(first["pretaxIncome"], 25196e6)
        self.assertNotIn("operatingIncome", first)
        self.assertNotIn("segmentOperatingIncome", first)
        for y in r["years"] + [r["terminal"]]:
            self.assertTrue(
                all(
                    "pretaxIncome" in x and "operatingIncome" not in x
                    for x in y["segments"]
                )
            )
        self.assertEqual(first["netInterest"], 0)

    def test_interest_cannot_be_deducted_again_or_mixed_with_operating_profit_paths(
        self,
    ):
        for interest in [-0.01, 0.01]:
            a = copy.deepcopy(self.m["defaults"])
            a["netInterest"] = interest
            with self.assertRaisesRegex(ValueError, "already include interest"):
                calculate(self.m, a)
        for flag in ["grossProfitPath", "normalizationPath", "consolidationPath"]:
            bad = copy.deepcopy(self.m)
            bad[flag] = True
            with self.assertRaisesRegex(ValueError, "profit bases"):
                calculate(bad, bad["defaults"])

    def test_amortization_addback_keeps_broader_cash_reinvestment_and_sbc_cost(self):
        m = self.m
        r = calculate(m, m["defaults"])
        first = r["years"][0]
        self.assertEqual(
            [x["fact"]["value"] for x in m["anchors"]["investmentComponents"]],
            [5364e6, 3346e6, 16e6, 289e6],
        )
        self.assertEqual(first["depreciation"], 7751e6)
        self.assertEqual(first["capex"], 9015e6)
        self.assertEqual(first["tax"], 6299e6)
        self.assertEqual(first["cash"], 17633e6)
        self.assertEqual(m["facts"]["sbc"]["value"], 1414e6)
        self.assertEqual(m["bridge"]["cashAfterInvestmentLeaseSbc"], 17179e6)
        self.assertIsNone(m["anchors"]["actualFinanceLeasePrincipal"])

    def test_a_single_pretax_margin_change_recalculates_income_and_tax_without_interest(
        self,
    ):
        a = copy.deepcopy(self.m["defaults"])
        a["segments"][0]["marginEnd"] += 0.01
        r = calculate(self.m, a)["years"][0]
        expected_pretax = 25196e6 + 63136e6 * 0.01 / 5
        self.assertAlmostEqual(r["pretaxIncome"], expected_pretax, places=4)
        self.assertAlmostEqual(r["cash"], 17633e6 + 63136e6 * 0.01 / 5 * 0.75, places=4)
        self.assertEqual(r["netInterest"], 0)

    def test_working_capital_proxy_excludes_other_assets_liabilities_and_collateral(
        self,
    ):
        m = self.m
        self.assertEqual(m["anchors"]["workingCashEffect"], -2949e6)
        self.assertAlmostEqual(m["defaults"]["workingCapital"], 2949 / 3736)
        self.assertTrue(any("기타 영업자산" in r for r in [m["anchorSummary"]]))
        self.assertEqual(m["sourcePeriod"], ["2025-06-30", "2026-06-28"])
        self.assertNotEqual(m["sourcePeriod"], ["2025-07-01", "2026-06-30"])

    def test_new_narrative_or_modified_current_cash_requires_fresh_review(self):
        c = copy.deepcopy(self.c)
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(jnj.build(c, self.asof)["status"], "source_review_required")
        source, rows = jnj.company_filing(copy.deepcopy(self.c), self.asof)
        rows = copy.deepcopy(rows)
        for r in rows:
            if (
                r["tag"] == "NetCashProvidedByUsedInOperatingActivities"
                and r["start"] == "2025-12-29"
            ):
                r["value"] += 1e6
        with patch.object(jnj, "company_filing", return_value=(source, rows)):
            with self.assertRaisesRegex(ValueError, "bridge mismatch"):
                jnj.build(copy.deepcopy(self.c), self.asof)
