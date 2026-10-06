"""Expanded coverage must not silently alter accounting or research scope."""

import copy
import unittest
from equitylab import company_analysis as analysis, data, pipeline


def fact(metric, value, start="2026-01-01", end="2026-06-30", **extra):
    return dict(
        metric=metric,
        value=value,
        start=start,
        end=end,
        filedAt="2026-08-01",
        priority=0,
        accession="current",
        standard="US GAAP",
        tag="us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        **extra,
    )


class CoverageTests(unittest.TestCase):
    def test_ttm_cash_cannot_be_paired_with_half_year_revenue(self):
        rows = [fact(m, v) for m, v in [("revenue", 200), ("cfo", 40), ("capex", 25)]]
        rows.append(fact("cfo", 900, start="2025-07-01"))
        s = data.statement(rows, "2026-09-29")
        self.assertEqual((s["start"], s["days"]), ("2026-01-01", 181))
        self.assertEqual(s["current"]["cfo"]["value"], 40)

    def test_incomplete_latest_period_cannot_reuse_previous_period(self):
        rows = [fact(m, 100) for m in ("revenue", "cfo", "capex")]
        rows.append(fact("cfo", 200, end="2026-09-30"))
        with self.assertRaisesRegex(ValueError, "Same-period"):
            data.statement(rows, "2026-10-10")

    def test_profit_identity_handles_loss_to_profit_without_growth_ratio(self):
        previous = {
            "revenue": fact("revenue", 100),
            "operating_income": fact("operating_income", -10),
        }
        current = {
            "revenue": fact("revenue", 120),
            "operating_income": fact("operating_income", 6),
        }
        result = analysis.profit_bridge(current, previous)
        self.assertAlmostEqual(result["revenueEffect"], -2)
        self.assertAlmostEqual(result["marginEffect"], 18)
        self.assertAlmostEqual(result["change"], 16)
        previous["operating_income"] = None
        self.assertIsNone(analysis.profit_bridge(current, previous))

    def test_changed_investment_definition_withholds_margin_comparison(self):
        current = {
            m: fact(m, v)
            for m, v in [
                ("revenue", 100),
                ("cfo", 30),
                ("capex", 10),
                ("net_income", 20),
                ("operating_income", 20),
            ]
        }
        previous = copy.deepcopy(current)
        previous["capex"]["tag"] = "us-gaap:PaymentsToAcquireProductiveAssets"
        m = pipeline.financial_metrics(dict(current=current, previous=previous))
        self.assertIsNone(m["cashMarginChange"])
        self.assertFalse(m["investmentComparable"])
        self.assertEqual(m["cashAfterInvestment"], 20)

    def test_missing_growth_is_unknown_not_a_negative_observation(self):
        c = copy.deepcopy(pipeline.load_latest()["companies"][0])
        c["metrics"]["revenueGrowth"] = None
        result = pipeline.assessment(c, "2026-09-29")
        self.assertIsNone(result["gates"][0]["passed"])
        self.assertNotEqual(result["priority"], "심층 조사 후보")

    def test_future_restatement_cannot_change_history(self):
        c = copy.deepcopy(pipeline.load_latest()["companies"][0])
        rows = [
            fact(m, v, "2025-01-01", "2025-12-31")
            for m, v in [("revenue", 100), ("cfo", 20), ("capex", 5)]
        ]
        before = analysis.build(c, rows, "2026-09-29")["annual"]
        rows.append(dict(rows[0], value=900, filedAt="2026-10-01"))
        self.assertEqual(before, analysis.build(c, rows, "2026-09-29")["annual"])
        self.assertEqual(before[0]["cashMargin"], 0.15)
        self.assertIsNone(before[0]["operatingMargin"])

    def test_expanded_coverage_has_official_identity_provenance(self):
        s = pipeline.load_latest()
        self.assertEqual(len(s["companies"]), 60)
        self.assertEqual(sum(c["market"] == "US" for c in s["companies"]), 30)
        self.assertEqual(sum(c["market"] == "KR" for c in s["companies"]), 30)
        self.assertEqual(
            {c["id"] for c in s["companies"]}, {c["id"] for c in data.UNIVERSE}
        )
        self.assertEqual(len(s["registrySources"]), 2)
        for source in s["registrySources"]:
            data.read_verified(data.ROOT / source["file"], source["sha256"])
        for c in s["companies"]:
            self.assertEqual(c["status"], "ready")
            self.assertTrue(c["analysis"]["questions"])
            bridge = c["analysis"]["profitBridge"]
            if bridge:
                self.assertAlmostEqual(
                    (bridge["revenueEffect"] + bridge["marginEffect"]) / 1e9,
                    bridge["change"] / 1e9,
                    places=7,
                )
            for row in c["analysis"]["annual"]:
                for f in row["evidence"]:
                    self.assertEqual((f["start"], f["end"]), (row["start"], row["end"]))
                    self.assertLessEqual(f["filedAt"], s["asOf"])

    def test_expanded_current_coverage_does_not_expand_old_performance_claims(self):
        s = pipeline.load_latest()
        cohort = {"MU", "NVDA", "GOOGL", "AAPL", "000660", "005930", "035420", "066570"}
        self.assertEqual(set(s["researchCohort"]["members"]), cohort)
        for experiment in s["experiments"]:
            self.assertEqual(len(experiment["members"]), 4)
            self.assertTrue(set(experiment["members"]).issubset(cohort))

    def test_actual_amazon_values_retain_one_reporting_period(self):
        c = next(c for c in pipeline.load_latest()["companies"] if c["id"] == "AMZN")
        s = c["financials"]
        self.assertEqual((s["start"], s["end"]), ("2026-01-01", "2026-06-30"))
        self.assertEqual(s["current"]["cfo"]["value"], 71419000000)
        self.assertEqual(s["current"]["capex"]["value"], 98411000000)
        self.assertEqual(c["investmentScope"], "유형·무형자산 취득")

    def test_cross_market_peers_keep_accounting_and_period_cautions(self):
        companies = pipeline.load_latest()["companies"]
        c = next(c for c in companies if c["id"] == "MU")
        p = next(p for p in analysis.peers(c, companies) if p["id"] == "000660")
        self.assertIn("회계 기준 차이", p["cautions"])
        self.assertIn("누적 기간 길이 차이", p["cautions"])
        self.assertFalse(p["directComparison"])


if __name__ == "__main__":
    unittest.main()
