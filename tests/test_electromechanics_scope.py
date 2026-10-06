import copy
import unittest
from unittest.mock import patch

from equitylab import (
    cash_scope,
    coverage_reasoning,
    electromechanics_scope,
    questions,
    valuation,
)
from equitylab.pipeline import load_latest


class ElectromechanicsScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = load_latest()
        cls.as_of = s["asOf"]
        cls.company = copy.deepcopy(
            next(c for c in s["companies"] if c["id"] == "009150")
        )
        cls.company["cashScope"] = cash_scope.build(cls.company, cls.as_of)

    def test_three_original_periods_have_opposite_signs_without_a_selected_value(self):
        scope = self.company["cashScope"]
        self.assertEqual(scope["status"], "review_required")
        self.assertEqual(scope["signReview"]["status"], "source_conflict")
        expected = [2881532000, 475808000, 556263000]
        for row, amount in zip(scope["signReview"]["observations"], expected):
            self.assertEqual(row["xbrl"]["value"], -amount)
            self.assertEqual(row["narrative"]["value"], amount)
            self.assertEqual(row["narrative"]["unit"], "KRW")
            self.assertEqual(row["narrative"]["sourceUnit"], "천원")
            self.assertIsNone(row["selectedValue"])
        self.assertTrue(
            all(r["status"] == "source_conflict" for r in scope["observations"])
        )

    def test_raw_narrative_dashes_and_investing_values_are_preserved(self):
        rows = self.company["cashScope"]["signReview"]["observations"]
        self.assertEqual(
            rows[0]["narrative"]["rows"][2], ["투자현금흐름", "577,306", "(53,728)"]
        )
        self.assertEqual(
            rows[1]["narrative"]["rows"][2], ["투자현금흐름", "-", "548,806"]
        )
        self.assertEqual(
            rows[1]["narrative"]["rows"][3], ["재무현금흐름", "28,826", "-"]
        )

    def test_archived_annual_is_included_in_replay_sources(self):
        for row in self.company["cashScope"]["signReview"]["observations"]:
            d = row["narrative"]
            self.assertTrue(
                any(
                    s["file"] == d["sourceFile"] and s["sha256"] == d["sourceHash"]
                    for s in self.company["sources"]
                )
            )

    def test_new_filing_does_not_inherit_the_review(self):
        c = copy.deepcopy(self.company)
        observations = c["cashScope"]["observations"]
        observations[1]["reportedCfo"]["accession"] = "20261114000000"
        with patch.object(electromechanics_scope, "document_table") as reader:
            review = electromechanics_scope.build(c, observations, self.as_of)
        self.assertEqual(review["status"], "source_review_required")
        self.assertEqual(review["observations"], [])
        reader.assert_not_called()

    def test_changed_xbrl_hash_does_not_inherit_sign_review(self):
        c = copy.deepcopy(self.company)
        fact = c["cashScope"]["observations"][0]["discontinuedCfo"]
        next(s for s in c["sources"] if s["file"] == fact["sourceFile"])[
            "sha256"
        ] = "new"
        review = electromechanics_scope.build(
            c, c["cashScope"]["observations"], self.as_of
        )
        self.assertEqual(review["status"], "source_review_required")

    def test_price_remains_held_and_models_receive_both_values_as_disputed(self):
        c = self.company
        v = valuation.build(c, self.as_of)
        self.assertIsNone(v["priceRequirement"])
        self.assertEqual(v["security"]["status"], "unresolved")
        q = questions.packet(c)["businessScope"]
        coverage = coverage_reasoning.input_packet(c)["businessScopeEvidence"]
        self.assertTrue(all(p["discontinuedCfo"] is None for p in q["periods"]))
        self.assertTrue(
            all(
                p["discontinuedOperatingCash"] is None for p in coverage["observations"]
            )
        )
        for packet in [q, coverage]:
            review = packet["signReview"]
            self.assertEqual(review["status"], "source_conflict")
            self.assertEqual(review["observations"][0]["xbrlValue"], -2881532000)
            self.assertEqual(review["observations"][0]["narrativeValue"], 2881532000)
            self.assertTrue(
                all(p["selectedValue"] is None for p in review["observations"])
            )


if __name__ == "__main__":
    unittest.main()
