import copy
import unittest
from equitylab import cash_scope, valuation, research_case
from equitylab.pipeline import load_latest


class CashScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.companies = {c["id"]: copy.deepcopy(c) for c in s["companies"]}
        for key in ["207940", "006400", "051910", "AMD", "GE"]:
            c = cls.companies[key]
            c["cashScope"] = cash_scope.build(c, s["asOf"])

    def test_samsung_bio_annual_and_half_year_discontinued_cash_are_distinct(self):
        scope = self.companies["207940"]["cashScope"]
        self.assertEqual(scope["status"], "review_required")
        rows = scope["observations"]
        self.assertEqual(rows[0]["discontinuedCfo"]["value"], 288690842357)
        self.assertIsNone(rows[1]["discontinuedCfo"])
        self.assertEqual(rows[2]["discontinuedCfo"]["value"], 181510968855)

    def test_separate_financials_with_opposite_sign_are_not_used(self):
        prior = self.companies["006400"]["cashScope"]["observations"][-1]
        self.assertEqual(prior["discontinuedCfo"]["value"], 11748714000)
        self.assertNotEqual(prior["discontinuedCfo"]["value"], -15343689000)

    def test_lg_chem_aggregate_is_not_added_to_its_subcomponents(self):
        current = self.companies["051910"]["cashScope"]["observations"][1]
        self.assertEqual(current["discontinuedCfo"]["value"], -22160000000)
        self.assertEqual(len(current["discontinuedCfo"]["dimensions"]), 1)

    def test_price_and_relative_cash_judgment_wait_for_consistent_business_scope(self):
        c = self.companies["207940"]
        v = valuation.build(c, "2026-09-29")
        self.assertEqual(v["status"], "workspace")
        self.assertEqual(v["security"]["status"], "unresolved")
        self.assertIsNone(v["priceRequirement"])
        self.assertTrue(all(p["price"] is None for p in v["cases"]))
        comparisons = research_case.peer_rows(c, list(self.companies.values()))
        self.assertTrue(comparisons)
        self.assertTrue(
            all(p["differences"]["cashMargin"] is None for p in comparisons)
        )
        self.assertTrue(all("중단영업" in p["conclusion"] for p in comparisons))

    def test_same_context_conflict_is_not_silently_resolved(self):
        fact = self.companies["207940"]["cashScope"]["observations"][0][
            "discontinuedCfo"
        ]
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            cash_scope.select_discontinued(
                [fact, dict(fact, value=1)], "KR", fact["start"], fact["end"], "KRW"
            )

    def test_amd_extension_and_archived_annual_do_not_hide_discontinued_cash(self):
        scope = self.companies["AMD"]["cashScope"]
        self.assertEqual(scope["status"], "review_required")
        self.assertEqual(
            [o["discontinuedCfo"]["value"] for o in scope["observations"]],
            [1_216_000_000, 0, 549_000_000],
        )
        self.assertTrue(all(o["status"] == "reported" for o in scope["observations"]))
        self.assertEqual(
            scope["observations"][0]["discontinuedCfo"]["accession"],
            "0000002488-26-000018",
        )
        self.assertEqual(
            scope["observations"][2]["discontinuedCfo"]["accession"],
            "0000002488-26-000123",
        )
        v = valuation.build(self.companies["AMD"], "2026-09-29")
        self.assertIsNone(v["priceRequirement"])
        self.assertEqual(v["security"]["status"], "unresolved")

    def test_us_segment_cash_is_not_a_consolidated_discontinued_total(self):
        fact = self.companies["AMD"]["cashScope"]["observations"][-1]["discontinuedCfo"]
        segmented = dict(
            fact, dimensions=[("StatementBusinessSegmentsAxis", "ManufacturingMember")]
        )
        self.assertIsNone(
            cash_scope.select_discontinued(
                [segmented], "US", fact["start"], fact["end"], "USD"
            )
        )

    def test_ge_negative_discontinued_cash_is_not_an_absent_value(self):
        scope = self.companies["GE"]["cashScope"]
        self.assertEqual(scope["status"], "review_required")
        self.assertEqual(
            [o["discontinuedCfo"]["value"] for o in scope["observations"][1:]],
            [-108_000_000, -136_000_000],
        )
        self.assertIsNone(
            valuation.build(self.companies["GE"], "2026-09-29")["priceRequirement"]
        )


if __name__ == "__main__":
    unittest.main()
