import copy
from pathlib import Path
import tempfile
import unittest

from equitylab.data import canonical, digest
from equitylab import note_audit, ledger


class NoteAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "holds.jsonl"
        self.record = dict(
            company="test",
            evidenceHash="input-a",
            notes=dict(hypothesis="투자가 현금 증가의 주요 원인이다."),
        )
        self.record["recordHash"] = digest(canonical(self.record))

    def test_hold_is_bound_to_original_sentence_and_cannot_approve_it(self):
        saved = note_audit.hold(
            self.record, "hypothesis", "원인 근거 없음", "검토자", self.path
        )
        self.assertFalse(saved["independentFinancialApproval"])
        self.assertEqual(note_audit.findings(self.record, self.path), [saved])
        self.assertEqual(self.record["notes"]["hypothesis"], saved["quote"])
        note_audit.hold(
            self.record, "hypothesis", "원인 근거 없음", "검토자", self.path
        )
        self.assertEqual(len(ledger.read(self.path)), 1)

    def test_new_inference_does_not_inherit_a_previous_sentence_hold(self):
        note_audit.hold(
            self.record, "hypothesis", "원인 근거 없음", "검토자", self.path
        )
        newer = copy.deepcopy(self.record)
        newer["notes"]["hypothesis"] = "시점 효과일 가능성이 있다."
        del newer["recordHash"]
        newer["recordHash"] = digest(canonical(newer))
        self.assertEqual(note_audit.findings(newer, self.path), [])

    def test_modified_record_or_empty_reason_cannot_enter_ledger(self):
        changed = copy.deepcopy(self.record)
        changed["notes"]["hypothesis"] = "다른 문장"
        with self.assertRaises(ValueError):
            note_audit.hold(changed, "hypothesis", "오류", "검토자", self.path)
        with self.assertRaises(ValueError):
            note_audit.hold(self.record, "hypothesis", " ", "검토자", self.path)
        with self.assertRaises(ValueError):
            note_audit.hold(self.record, "approve", "오류", "검토자", self.path)


if __name__ == "__main__":
    unittest.main()
