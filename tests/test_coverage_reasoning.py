import copy
import json
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from equitylab import (
    coverage_reasoning as protocol,
    local_ai,
    model_evaluation,
    pipeline,
    publication,
)
from equitylab.data import ROOT, digest, work_temp


class CoverageReasoningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.companies = {
            c["id"]: c
            for c in pipeline.load_latest()["companies"]
            if c["status"] == "ready"
        }

    def test_all_companies_have_same_currency_fact_bound_inputs(self):
        for c in self.companies.values():
            p = protocol.input_packet(c)
            self.assertEqual(len(p["evidence"]), 6)
            self.assertEqual(len(p["computedObservations"]), 3)
            for fact in p["evidence"]:
                self.assertEqual(fact["unit"], c["currency"])
                self.assertTrue(fact["sourceHash"])
            for o in p["computedObservations"]:
                if o["comparisonAvailable"]:
                    self.assertEqual(o["change"], o["current"] - o["previous"])

    def test_currency_corruption_and_nan_fail_before_inference(self):
        for changes in [{"unit": "JPY"}, {"value": float("nan")}]:
            c = copy.deepcopy(self.companies["MSFT"])
            c["financials"]["current"]["cfo"].update(changes)
            with self.assertRaises(ValueError):
                protocol.input_packet(c)

    def test_fact_and_business_changes_invalidate_notes(self):
        original = self.companies["MSFT"]
        c = copy.deepcopy(original)
        c["financials"]["current"]["cfo"]["value"] += 1
        self.assertNotEqual(protocol.evidence_hash(original), protocol.evidence_hash(c))
        c = copy.deepcopy(original)
        c["business"]["evidenceHash"] = "different source"
        self.assertNotEqual(protocol.evidence_hash(original), protocol.evidence_hash(c))

    def test_dictionary_insertion_order_does_not_change_the_model_packet(self):
        original = self.companies["MSFT"]
        reordered = copy.deepcopy(original)
        for key in ["balances", "flows"]:
            reordered["capital"][key] = dict(
                reversed(list(original["capital"][key].items()))
            )
        self.assertEqual(
            protocol.input_packet(original), protocol.input_packet(reordered)
        )
        self.assertEqual(
            protocol.evidence_hash(original), protocol.evidence_hash(reordered)
        )

    def test_model_cannot_forge_references_or_repeat_alternative(self):
        facts = protocol.evidence(self.companies["MSFT"])
        notes = dict(
            hypothesis="증설 때문일 수 있다.",
            alternative="교체 투자 가능성도 있다.",
            distinguish="설비 구성으로 구별한다.",
            missing="설비별 투자 자료가 필요하다.",
        )
        linked = protocol.attach_evidence(notes, facts)
        protocol.validate_notes(linked, facts)
        for bad in [
            {**linked, "evidence": ["forged"]},
            {**linked, "alternative": notes["hypothesis"]},
        ]:
            with self.assertRaises(ValueError):
                protocol.validate_notes(bad, facts)

    def test_company_evaluation_cannot_reuse_receivable_protocol(self):
        client = local_ai.LocalClient(thinking=True)
        result = dict(
            modelDigest="test",
            inferenceConfig=client.inference_config,
            protocolHash=protocol.protocol_hash(),
            suiteHash=digest(protocol.SUITE.read_bytes()),
            gatePassed=True,
            status="completed",
            recordHash="record",
            counts={},
            scope="synthetic",
        )
        transfer = dict(result, suiteHash=digest(protocol.TRANSFER_SUITE.read_bytes()))
        with patch.object(
            model_evaluation,
            "read_evaluation",
            side_effect=lambda name: (
                transfer if name == "coverage-transfer-evaluations" else result
            ),
        ):
            self.assertTrue(
                model_evaluation.gate_for(
                    "test",
                    client.inference_config,
                    protocol=protocol,
                    suite_path=protocol.SUITE,
                    archive_name="coverage-evaluations",
                )["passed"]
            )
            self.assertFalse(
                model_evaluation.gate_for("test", client.inference_config)["passed"]
            )
        with patch.object(
            model_evaluation,
            "read_evaluation",
            side_effect=lambda name: (
                None if name == "coverage-transfer-evaluations" else result
            ),
        ):
            self.assertFalse(
                model_evaluation.gate_for(
                    "test",
                    client.inference_config,
                    protocol=protocol,
                    suite_path=protocol.SUITE,
                    archive_name="coverage-evaluations",
                )["passed"]
            )

    def test_critique_can_quote_input_numbers_without_allowing_numbers_in_notes(self):
        item = dict(id="observation", role="observation", text="영업현금은 증가했다.")
        result = dict(
            analysis="30에서 45로 증가",
            assessments=[
                dict(
                    id=item["id"],
                    quote=item["text"],
                    classification="supported",
                    reason="입력 30→45와 일치",
                )
            ],
        )
        protocol.validate_assessments(result, [item])
        self.assertTrue(protocol.all_accepted(result, [item]))
        facts = protocol.evidence(self.companies["MSFT"])
        notes = dict(
            hypothesis="매출 30% 증가 때문일 수 있다.",
            alternative="다른 원인일 수 있다.",
            distinguish="공시를 확인한다.",
            missing="세부 자료가 없다.",
        )
        with self.assertRaises(ValueError):
            protocol.validate_notes(protocol.attach_evidence(notes, facts), facts)

    def test_private_notes_removed_from_public_projection(self):
        p = dict(
            snapshot=dict(contentHash="a", companies=[]),
            localReviews={"MU": {"private": "receivables"}},
            coverageReviews={"MSFT": {"private": "business"}},
        )
        out = publication.public_payload(p)
        self.assertNotIn("private", json.dumps(out))
        self.assertIn("coverageReviews", p)

    def test_synthetic_suite_is_balanced_and_ids_unique(self):
        suite = json.loads(protocol.SUITE.read_text())
        cases = suite["cases"]
        self.assertEqual(sum(c["accept"] for c in cases), 6)
        self.assertEqual(len(cases), 12)
        self.assertEqual(len({c["id"] for c in cases}), 12)
        self.assertEqual(suite["gate"]["maxFalseAccepts"], 0)

    def test_all_attempts_evaluation_keeps_invalid_responses_and_fails_gate(self):
        client = local_ai.LocalClient()
        with tempfile.TemporaryDirectory(dir=work_temp()) as folder, patch.object(
            model_evaluation, "ROOT", Path(folder)
        ), patch.object(client, "model", return_value={"digest": "test"}), patch.object(
            client, "call", return_value={"models": []}
        ), patch.object(
            local_ai, "ask_recorded", side_effect=ValueError("malformed response")
        ) as ask:
            result = model_evaluation.evaluate(
                client,
                "test:local",
                protocol=protocol,
                suite_path=protocol.SUITE,
                archive_name="coverage-evaluations",
                fail_fast=False,
            )
        self.assertEqual(ask.call_count, 12)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["counts"]["invalidResponses"], 12)
        self.assertFalse(result["gatePassed"])
