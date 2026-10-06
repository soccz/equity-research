import copy
from pathlib import Path
import tempfile
import unittest
from equitylab import research_case, research_journal, ledger
from equitylab.pipeline import load_latest


class ResearchCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_latest()
        cls.companies = {c["id"]: c for c in cls.snapshot["companies"]}

    def test_peer_comparison_uses_actual_trailing_year_and_preserves_scope(self):
        rows = research_case.peer_rows(
            self.companies["MU"], list(self.companies.values())
        )
        self.assertEqual([r["id"] for r in rows], ["000660"])
        r = rows[0]
        self.assertIn("회계 기준·현금 분류 차이", r["cautions"])
        a = self.companies["MU"]["trailingYear"]["metrics"]["cashMargin"]
        b = self.companies["000660"]["trailingYear"]["metrics"]["cashMargin"]
        self.assertAlmostEqual(r["differences"]["cashMargin"], a - b)
        self.assertEqual(
            r["evidenceHash"], self.companies["000660"]["trailingYear"]["evidenceHash"]
        )

    def test_missing_peer_data_never_becomes_zero_or_a_negative_view(self):
        rows = copy.deepcopy(list(self.companies.values()))
        next(c for c in rows if c["id"] == "000660")["trailingYear"][
            "status"
        ] = "unresolved"
        self.assertEqual(research_case.peer_rows(self.companies["MU"], rows), [])

    def test_different_investment_definitions_hold_cash_ranking(self):
        peer = copy.deepcopy(self.companies["000660"])
        peer["trailingYear"]["investmentScope"] = "유형·무형 통합 취득"
        r = research_case.peer_rows(self.companies["MU"], [peer])[0]
        self.assertFalse(r["investmentComparable"])
        self.assertIsNone(r["differences"]["cashMargin"])
        self.assertIsNone(r["differences"]["investmentMargin"])
        self.assertIsNotNone(r["differences"]["cfoMargin"])
        self.assertIn("정의를 일치시킨 뒤", r["conclusion"])

    def test_business_condition_tracks_a_named_segment_without_forecasting(self):
        c = self.companies["MSFT"]
        case = research_case.build(c, list(self.companies.values()))
        self.assertEqual(len(case["watch"]), 2)
        self.assertTrue(case["watch"][1]["segmentId"])
        self.assertTrue(all(w["expected"] is None for w in case["watch"]))
        self.assertEqual(
            case["driver"]["operatingIncome"],
            max(
                abs(x["current"]["operatingIncome"]["value"])
                for x in c["business"]["segments"]
            ),
        )
        self.assertIn(
            "클라우드를 포함한 연결 회사 비교; 클라우드 사업부 단독 우열 아님",
            case["peers"][0]["cautions"],
        )

    def test_journal_is_idempotent_and_keeps_revisions(self):
        s = copy.deepcopy(self.snapshot)
        s["companies"] = [s["companies"][0]]
        c = s["companies"][0]
        c["researchCase"] = research_case.build(c, s["companies"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            added = research_journal.register(s, path)
            before = path.read_bytes()
            self.assertTrue(added)
            self.assertEqual(research_journal.register(s, path), [])
            self.assertEqual(before, path.read_bytes())
            c["researchCase"]["evidenceHash"] = "changed"
            c["researchCase"]["pricing"]["statement"] = "changed assumption"
            added = research_journal.register(s, path)
            self.assertEqual(len(added), 1)
            rows = ledger.read(path)
            revisions = [r for r in rows if r["type"] == "case"]
            self.assertEqual(revisions[1]["previousRevisionHash"], revisions[0]["hash"])
            self.assertNotEqual(
                revisions[0]["case"]["pricing"]["statement"],
                revisions[1]["case"]["pricing"]["statement"],
            )
            view = research_journal.payload(s, path)
            self.assertTrue(
                all(w["observation"]["status"] == "pending" for w in view["watches"])
            )

    def test_same_day_and_old_period_cannot_be_scored(self):
        c = copy.deepcopy(self.companies["MSFT"])
        record = dict(
            recordedAt="2026-07-29T00:00:00-04:00",
            periodEnd="2026-03-31",
            investmentScope=c["investmentScope"],
            condition=dict(metric="cashMarginChange", baseline=0),
        )
        self.assertEqual(research_journal.evaluate(record, c)["status"], "pending")
        record["recordedAt"] = "2026-07-28T00:00:00-04:00"
        result = research_journal.evaluate(record, c)
        self.assertEqual(result["status"], "not_met")
        self.assertIsNone(result["predictionCorrect"])
        record["periodEnd"] = c["financials"]["end"]
        self.assertEqual(research_journal.evaluate(record, c)["status"], "pending")

    def test_segment_scope_change_is_unresolved_not_a_bad_prediction(self):
        c = copy.deepcopy(self.companies["MSFT"])
        c["researchCase"] = research_case.build(c, list(self.companies.values()))
        record = dict(
            recordedAt="2026-07-28T00:00:00-04:00",
            periodEnd="2026-03-31",
            investmentScope=c["investmentScope"],
            segmentIds=["changed"],
            condition=c["researchCase"]["watch"][1],
        )
        result = research_journal.evaluate(record, c)
        self.assertEqual(result["status"], "unresolved")
        self.assertIsNone(result["predictionCorrect"])


if __name__ == "__main__":
    unittest.main()
