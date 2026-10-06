import copy
import unittest
from equitylab.comparable import trailing_year


class ComparableTests(unittest.TestCase):
    def setUp(self):
        self.company = dict(
            currency="USD",
            financials=dict(
                start="2026-01-01",
                end="2026-06-30",
                priorStart="2025-01-01",
                priorEnd="2025-06-30",
                days=181,
            ),
        )
        self.facts = []
        for metric in ("revenue", "operating_income", "net_income", "cfo", "capex"):
            for start, end, value in [
                ("2025-01-01", "2025-12-31", 100),
                ("2026-01-01", "2026-06-30", 80),
                ("2025-01-01", "2025-06-30", 30),
            ]:
                self.facts.append(
                    dict(
                        metric=metric,
                        start=start,
                        end=end,
                        value=value,
                        unit="USD",
                        filedAt="2026-08-01",
                        accession="fixture",
                        priority=0,
                        tag=(
                            "PaymentsToAcquirePropertyPlantAndEquipment"
                            if metric == "capex"
                            else metric
                        ),
                    )
                )

    def test_year_bridge_does_not_annualize_first_half(self):
        r = trailing_year(self.company, self.facts, "2026-09-29")
        self.assertEqual(r["status"], "ready")
        self.assertEqual(
            (r["start"], r["end"], r["days"]), ("2025-07-01", "2026-06-30", 365)
        )
        self.assertEqual(r["values"]["cfo"]["value"], 150)
        self.assertNotEqual(r["values"]["cfo"]["value"], 80 * 2)

    def test_future_correction_cannot_change_asof_numbers(self):
        future = dict(
            self.facts[0], value=999, filedAt="2026-10-01", accession="future"
        )
        r = trailing_year(self.company, self.facts + [future], "2026-09-29")
        self.assertEqual(r["values"]["revenue"]["value"], 150)

    def test_missing_year_does_not_fall_back_to_older_annual_report(self):
        missing = [
            f
            for f in self.facts
            if not (f["metric"] == "cfo" and f["end"] == "2025-12-31")
        ]
        missing.append(
            dict(self.facts[0], metric="cfo", start="2024-01-01", end="2024-12-31")
        )
        r = trailing_year(self.company, missing, "2026-09-29")
        self.assertIsNone(r["values"]["cfo"])
        self.assertIsNone(r["metrics"]["cashMargin"])
        self.assertEqual(r["status"], "partial")

    def test_investment_definition_change_blocks_cash_comparison(self):
        facts = copy.deepcopy(self.facts)
        next(f for f in facts if f["metric"] == "capex")[
            "tag"
        ] = "PaymentsToAcquireProductiveAssets"
        r = trailing_year(self.company, facts, "2026-09-29")
        self.assertIsNone(r["values"]["capex"])
        self.assertIsNone(r["metrics"]["cashMargin"])

    def test_53_week_reporting_keeps_actual_dates(self):
        c = copy.deepcopy(self.company)
        c["financials"].update(start="2025-06-29", end="2026-07-04", days=371)
        facts = [dict(f, start="2025-06-29", end="2026-07-04") for f in self.facts[:1]]
        r = trailing_year(c, facts, "2026-09-29")
        self.assertEqual(r["days"], 371)
        self.assertEqual(r["method"], "reported")


if __name__ == "__main__":
    unittest.main()
