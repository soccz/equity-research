import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from equitylab.segment_history import build, definition_texts
from equitylab.data import digest


class SegmentPeriodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / "data/latest.json").read_text())
        cls.snapshot = json.loads((root / p["snapshot"]).read_text())
        cls.companies = {c["id"]: c for c in cls.snapshot["companies"]}

    def model(self, symbol):
        return build(copy.deepcopy(self.companies[symbol]), self.snapshot["asOf"])

    def test_seven_issuer_specific_bridges_reconcile_both_consolidated_metrics(self):
        for symbol in ["MU", "NVDA", "GOOGL", "AAPL", "AMZN", "AMD", "AVGO"]:
            h = self.model(symbol)
            self.assertEqual(h["status"], "ready", symbol)
            self.assertTrue(
                all(r["residual"] == 0 for r in h["reconciliations"].values())
            )
            for s in h["segments"]:
                for key in ["revenue", "operatingIncome"]:
                    a, current, prior = s[key]["components"]
                    self.assertEqual(
                        [
                            a["coefficient"],
                            current["coefficient"],
                            prior["coefficient"],
                        ],
                        [1, 1, -1],
                    )
                    self.assertNotEqual(
                        a["fact"]["accession"], current["fact"]["accession"]
                    )
                    self.assertEqual(
                        current["fact"]["accession"], prior["fact"]["accession"]
                    )

    def test_amd_context_and_cost_sign_change_are_explicit_source_components(self):
        h = self.model("AMD")
        annual = h["segments"][0]["revenue"]["components"][0]["fact"]
        self.assertIn(
            ("StatementBusinessSegmentsAxis", "DatacenterMember"), annual["dimensions"]
        )
        adjustment = h["reconciliations"]["operatingIncome"]["adjustments"][0][
            "series"
        ]["components"][0]
        self.assertEqual(adjustment["fact"]["value"], 4_007_000_000)
        self.assertEqual(adjustment["coefficient"], -1)
        self.assertIn("비용", adjustment["label"])

    def test_broadcom_unallocated_costs_are_deducted_once_in_all_three_periods(self):
        r = self.model("AVGO")["reconciliations"]["operatingIncome"]
        self.assertEqual(len(r["adjustments"]), 4)
        self.assertEqual(r["adjustment"], -16_956_000_000)
        self.assertEqual(r["residual"], 0)

    def test_unknown_new_or_future_source_cannot_reuse_definition_review(self):
        c = copy.deepcopy(self.companies["MU"])
        c["narrative"]["evidenceHash"] = "changed"
        self.assertEqual(
            build(c, self.snapshot["asOf"])["status"], "definition_review_required"
        )
        with self.assertRaises(ValueError):
            build(copy.deepcopy(self.companies["MU"]), "2020-01-01")

    def test_missing_annual_fact_keeps_a_gap_instead_of_annualizing_ytd(self):
        from equitylab.segment_history import select

        def without_annual(rows, tag, start, end, dimensions, unit):
            if end == "2025-08-28":
                return None
            return select(rows, tag, start, end, dimensions, unit)

        with patch("equitylab.segment_history.select", side_effect=without_annual):
            h = self.model("MU")
        self.assertEqual(h["status"], "partial")
        self.assertIsNone(h["segments"][0]["revenue"])

    def test_korean_bridges_preserve_issuer_specific_contexts_and_cash_boundaries(self):
        for symbol in ["066570", "005380", "207940"]:
            h = self.model(symbol)
            self.assertEqual(h["status"], "ready", symbol)
            self.assertTrue(
                all(r["residual"] == 0 for r in h["reconciliations"].values())
            )
            for note in h["review"]["annualNotes"]:
                self.assertIn("ConsolidatedMember", note["context"])
                self.assertTrue(note["context"].startswith("CFY2025dFY"))
        auto = self.model("005380")
        self.assertEqual(auto["reconciliations"]["revenue"]["adjustments"], [])
        self.assertIn(
            "NetRevenue",
            auto["segments"][0]["revenue"]["components"][0]["fact"]["context"],
        )
        self.assertEqual(
            auto["reconciliations"]["operatingIncome"]["adjustment"], 621_137_000_000
        )
        self.assertIn("총 영업현금", self.model("207940")["review"]["note"])
        self.assertIn("현금", self.model("066570")["review"]["note"])

    def test_korean_tag_aliases_and_nonzero_gaps_remain_visible(self):
        h = self.model("005930")
        self.assertEqual(h["status"], "partial")
        self.assertEqual(
            h["reconciliations"]["operatingIncome"]["residual"], 147_921_000_000
        )
        dims = h["segments"][0]["revenue"]["components"][0]["fact"]["dimensions"]
        self.assertTrue(any("DsDivisionMember" in m for _, m in dims))
        ct = self.model("068270")
        self.assertEqual(ct["reconciliations"]["operatingIncome"]["residual"], -600)
        self.assertEqual(
            [p["residual"] for p in ct["reconciliations"]["revenue"]["periods"]],
            [-119, -98, -291],
        )
        hd = self.model("329180")
        self.assertEqual(hd["reconciliations"]["operatingIncome"]["residual"], -518_000)
        self.assertIn("합병 전후", hd["review"]["note"])
        self.assertIn("2025년 12월 1일", hd["review"]["note"])

    def test_offsetting_period_gaps_do_not_masquerade_as_a_reconciliation(self):
        from equitylab.segment_history import select

        c = self.companies["MU"]
        fact = c["business"]["segments"][0]["current"]["revenue"]
        ends = {
            c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]["end"],
            c["financials"]["priorEnd"],
        }

        def alter(rows, tag, start, end, dimensions, unit):
            r = select(rows, tag, start, end, dimensions, unit)
            if (
                r
                and tag == fact["tag"]
                and sorted(map(tuple, dimensions))
                == sorted(map(tuple, fact["dimensions"]))
                and end in ends
            ):
                return dict(r, value=r["value"] + 1_000_000)
            return r

        with patch("equitylab.segment_history.select", side_effect=alter):
            h = self.model("MU")
        self.assertEqual(h["reconciliations"]["revenue"]["residual"], 0)
        self.assertEqual(
            h["reconciliations"]["revenue"]["status"], "unresolved_difference"
        )
        self.assertEqual(h["status"], "partial")

    def test_definition_text_cannot_move_to_a_separate_statement_context(self):
        spec = {
            "annualNotes": [
                {
                    "tag": "Definition",
                    "context": "consolidated",
                    "sha256": digest(b"same words"),
                }
            ]
        }
        self.assertEqual(
            definition_texts(
                b'<x><Definition contextRef="consolidated">same words</Definition></x>',
                spec,
            )[0]["text"],
            "same words",
        )
        with self.assertRaises(ValueError):
            definition_texts(
                b'<x><Definition contextRef="separate">same words</Definition></x>',
                spec,
            )


if __name__ == "__main__":
    unittest.main()
