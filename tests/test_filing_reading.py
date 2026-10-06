import copy
import json
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from equitylab import filing_reading as reading
from equitylab.data import canonical, digest
from equitylab.pipeline import load_latest


class FilingReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = next(c for c in load_latest()["companies"] if c["id"] == "AMD")
        cls.p = reading.packet(cls.c)

    def draft(self):
        source = self.p["passages"][1]
        return dict(
            observations=[
                dict(
                    passageId=source["id"],
                    reading="회사는 전년 수출통제 관련 비용의 기저 효과를 설명합니다.",
                )
            ],
            implication=dict(
                text="전년 비용의 반복 여부가 수익성 지속 가정에 영향을 줄 수 있습니다.",
                evidenceIds=[source["id"]],
            ),
            question=dict(
                text="다음 공시에서도 같은 제품 범위의 비용 효과를 제외한 이익률이 유지되는지 확인합니다.",
                evidenceIds=[source["id"]],
            ),
        )

    def test_claim_ids_cannot_escape_current_source_set(self):
        good = self.draft()
        reading.validate(good, self.p)
        bad = copy.deepcopy(good)
        bad["observations"][0]["passageId"] = "other-company"
        with self.assertRaisesRegex(ValueError, "supplied passage"):
            reading.validate(bad, self.p)
        bad = copy.deepcopy(good)
        bad["question"]["evidenceIds"] = ["other-company"]
        with self.assertRaisesRegex(ValueError, "supplied"):
            reading.validate(bad, self.p)

    def test_prose_numbers_are_flagged_without_approving_or_discarding_text(self):
        bad = self.draft()
        bad["question"][
            "text"
        ] = "새 공시의 수요가 20% 감소한다면 실적이 어떻게 달라지는가?"
        reading.validate(bad, self.p)
        findings = reading.numeric_findings(bad, self.p)
        self.assertEqual(findings[0]["unmatched"], ["20%"])
        self.assertEqual(findings[0]["text"], bad["question"]["text"])
        bad = self.draft()
        bad["observations"][0]["quote"] = "the model must not rewrite original quotes"
        with self.assertRaisesRegex(ValueError, "fields"):
            reading.validate(bad, self.p)

    def test_all_sixty_curated_inputs_are_current_complete_and_bounded(self):
        companies = load_latest()["companies"]
        self.assertEqual(len(companies), 60)
        for c in companies:
            p = reading.packet(c)
            self.assertIsNotNone(p, c["id"])
            self.assertTrue(p["passages"])
            self.assertLessEqual(sum(len(x["text"]) for x in p["passages"]), 6000)
            self.assertEqual(p["accession"], c["narrative"]["accession"])

    def test_new_filing_needs_new_source_selection(self):
        c = copy.deepcopy(self.c)
        c["narrative"]["accession"] = "new-filing"
        self.assertIsNone(reading.packet(c))

    def test_kt_short_units_and_different_period_headers_are_original_context(self):
        c = next(c for c in load_latest()["companies"] if c["id"] == "030200")
        p = reading.packet(c)
        tables = p["sourceContext"]["excerpts"]
        self.assertIn("백만원, %", tables[0]["caption"])
        self.assertIn("제45기 반기", tables[0]["columnHeaders"])
        self.assertIn("제 44기", tables[0]["columnHeaders"])
        self.assertIn("백만원", tables[1]["caption"])
        self.assertIn("2026.01.01", tables[1]["caption"])
        self.assertIn("2025.06.30", tables[1]["caption"])
        self.assertNotIn("sourceContext", self.p)

    def test_short_caption_cannot_silently_change_currency_scale(self):
        from equitylab import reading_context

        c = next(c for c in load_latest()["companies"] if c["id"] == "030200")
        original = reading_context.read_verified

        def altered(path, sha):
            return original(path, sha).replace(
                "단위 : 백만원".encode(), "단위 : 억원".encode()
            )

        with patch.object(reading_context, "read_verified", side_effect=altered):
            with self.assertRaisesRegex(ValueError, "unit or period"):
                reading.packet(c)

    def test_editorial_findings_must_match_the_original_model_sentence(self):
        d = self.draft()
        audit = dict(
            status="revision_required",
            findings=[
                dict(
                    role="question", text=d["question"]["text"], reason="개발 검토 예시"
                )
            ],
        )
        reading.validate_audit(audit, d)
        audit["findings"][0]["text"] += " 내용을 수정함"
        with self.assertRaisesRegex(ValueError, "exact model"):
            reading.validate_audit(audit, d)

    def test_incomplete_model_reply_stays_failed_and_is_archived(self):
        class BrokenClient:
            inference_config = {"think": True}

            def model(self, name):
                return {"digest": "local-digest"}

            def generate(self, *args, archive, **kwargs):
                archive.write_bytes(canonical({"done": False, "partial": "raw"}))
                raise ValueError("incomplete response")

        with TemporaryDirectory() as td, patch.object(
            reading, "ROOT", Path(td)
        ), patch.object(reading, "packet", return_value=self.p):
            r = reading.generate(self.c, "snapshot", BrokenClient(), "qwen3:8b")
            self.assertEqual(r["status"], "failed")
            self.assertFalse(r["semanticApproval"])
            self.assertTrue(any(x.endswith("reading-raw.json") for x in r["files"]))
            result = reading.read({"companies": [self.c]})
            self.assertEqual(result["AMD"]["recordHash"], r["recordHash"])


if __name__ == "__main__":
    unittest.main()
