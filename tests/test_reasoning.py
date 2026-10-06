import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from equitylab import dossier, local_ai, model_evaluation, pipeline, reasoning
from equitylab.data import ROOT, canonical, digest


class ReasoningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.company = copy.deepcopy(
            next(c for c in pipeline.load_latest()["companies"] if c["id"] == "MU")
        )
        cls.company["dossier"] = dossier.build(cls.company, "2026-09-29")
        cls.temp_root = ROOT / "data/cache/tmp"
        cls.temp_root.mkdir(parents=True, exist_ok=True)

    def test_signed_observations_do_not_invent_a_cause(self):
        rows = {r["id"]: r for r in reasoning.observations(self.company)}
        self.assertEqual(rows["receivables"]["current"], -19_953_000_000)
        self.assertIn("현금 사용", rows["receivables"]["text"])
        self.assertEqual(rows["revenue"]["current"], 78_959_000_000)
        for row in rows.values():
            self.assertEqual(row["change"], row["current"] - row["previous"])
            self.assertNotIn("악화", row["text"])
        bad = copy.deepcopy(self.company)
        next(e for e in bad["dossier"]["evidence"] if e["id"] == "current.cfo")[
            "unit"
        ] = "KRW"
        with self.assertRaises(ValueError):
            reasoning.observations(bad)

    def test_missing_period_cannot_become_a_full_input_packet(self):
        c = copy.deepcopy(self.company)
        c["dossier"]["evidence"] = [
            e for e in c["dossier"]["evidence"] if e["id"] != "previous.receivables"
        ]
        with self.assertRaises(ValueError):
            reasoning.input_packet(c)

    def test_criticism_must_match_each_exact_sentence_once(self):
        items = [
            {
                "id": "hypothesis",
                "role": "hypothesis",
                "text": "성장에 따른 시차일 수 있다.",
            }
        ]
        correct = {
            "assessments": [
                {
                    "id": "hypothesis",
                    "classification": "conditional",
                    "quote": items[0]["text"],
                    "reason": "가능한 설명으로 한정한다.",
                }
            ]
        }
        self.assertTrue(reasoning.all_accepted(correct, items))
        for changes in [{"quote": "회수 악화가 확실하다."}, {"id": "unmentioned"}]:
            result = copy.deepcopy(correct)
            result["assessments"][0].update(changes)
            with self.assertRaises(ValueError):
                reasoning.validate_assessments(result, items)
        duplicate = {"assessments": correct["assessments"] * 2}
        with self.assertRaises(ValueError):
            reasoning.validate_assessments(
                duplicate,
                items
                + [{"id": "missing", "role": "missing", "text": "회수 자료가 없다."}],
            )

    def test_observation_cannot_pass_as_a_conditional_guess(self):
        a = {"classification": "conditional"}
        self.assertFalse(reasoning.accepted(a, "observation"))
        self.assertTrue(reasoning.accepted(a, "hypothesis"))
        self.assertFalse(
            reasoning.accepted({"classification": "supported"}, "hypothesis")
        )
        for value in ("unsupported", "contradicted", "unresolved"):
            self.assertFalse(
                reasoning.accepted({"classification": value}, "hypothesis")
            )

    def test_explicit_uncertainty_is_necessary_but_not_sufficient(self):
        a = {"classification": "conditional"}
        direct = "새 고객 계약이 체결되어 현금 사용이 늘었다."
        conditional = "새 고객 계약 때문일 수 있으나 확인되지 않았다."
        self.assertFalse(reasoning.accepted(a, "hypothesis", direct))
        self.assertTrue(reasoning.accepted(a, "hypothesis", conditional))
        # A hedge never overrides a substantive contradiction found by the model.
        self.assertFalse(
            reasoning.accepted(
                {"classification": "contradicted"}, "hypothesis", conditional
            )
        )

    def test_model_cannot_choose_or_forge_observation_citations(self):
        p = reasoning.input_packet(self.company)
        notes = dict(
            hypothesis="성장에 따른 시차일 수 있다.",
            alternative="회수가 지연됐을 수도 있다.",
            distinguish="연체와 대손의 변화를 확인한다.",
            missing="연령별 잔액이 없다.",
        )
        linked = reasoning.attach_evidence(notes, p["evidence"])
        reasoning.validate_notes(linked, p["evidence"])
        self.assertEqual(len(linked["evidence"]), 6)
        with self.assertRaises(ValueError):
            reasoning.attach_evidence(
                {**notes, "evidence": ["invented"]}, p["evidence"]
            )
        with self.assertRaises(ValueError):
            reasoning.validate_notes(
                {**linked, "alternative": linked["hypothesis"]}, p["evidence"]
            )

    def test_failed_json_or_truncated_response_is_archived(self):
        client = local_ai.LocalClient()
        responses = [
            {"done": True, "done_reason": "length", "message": {"content": "{broken"}},
            {"done": True, "done_reason": "stop", "message": {"content": "not json"}},
        ]
        with tempfile.TemporaryDirectory(dir=self.temp_root) as folder:
            out = Path(folder) / "attempt-raw.json"
            for response in responses:
                with patch.object(
                    client, "call", return_value=response
                ), self.assertRaises(ValueError):
                    client.generate("test:local", [], {}, archive=out)
                self.assertEqual(json.loads(out.read_text()), response)
                request = json.loads(out.with_name("attempt-request.json").read_text())
                self.assertFalse(request["think"])
                self.assertEqual(request["options"]["num_ctx"], 4096)

    def test_generation_and_self_review_cannot_bypass_missing_evaluation(self):
        client = local_ai.LocalClient()
        notes = dict(
            hypothesis="성장에 따른 시차일 수 있다.",
            alternative="회수가 지연됐을 수도 있다.",
            distinguish="연체와 대손의 변화를 확인한다.",
            missing="연령별 잔액이 없다.",
        )
        items = reasoning.review_items(notes)
        result = {
            "assessments": [
                dict(
                    id=i["id"],
                    classification=(
                        "supported" if i["role"] == "missing" else "conditional"
                    ),
                    quote=i["text"],
                    reason="역할에 부합하는 문장이다.",
                )
                for i in items
            ]
        }
        with tempfile.TemporaryDirectory(dir=self.temp_root) as folder, patch.object(
            local_ai, "ROOT", Path(folder)
        ), patch.object(client, "model", return_value={"digest": "test"}), patch.object(
            client, "call", return_value={"version": "test", "models": []}
        ), patch.object(
            local_ai,
            "ask_recorded",
            side_effect=[(notes, {})]
            + [({"assessments": [a]}, {}) for a in result["assessments"]],
        ), patch.object(
            model_evaluation,
            "gate_for",
            return_value={"status": "missing_or_stale", "passed": False},
        ):
            r = local_ai.review(self.company, "snapshot", client, "test:local")
            snapshot = {"companies": [self.company]}
            self.assertFalse(local_ai.read_reviews(snapshot)["MU"]["displayEligible"])
            archive = next(
                (Path(folder) / "data/local-reviews/MU").glob("*/review.json")
            )
            original_bytes = archive.read_bytes()
            with patch.object(
                model_evaluation, "gate_for", return_value={"passed": True}
            ):
                current = local_ai.read_reviews(snapshot)["MU"]
                self.assertTrue(current["displayEligible"])
                self.assertEqual(current["status"], "evaluation_required")
            self.assertEqual(archive.read_bytes(), original_bytes)
            self.assertFalse(local_ai.read_reviews(snapshot)["MU"]["displayEligible"])
        self.assertEqual(r["status"], "evaluation_required")
        self.assertFalse(r["independentReview"])

    def test_gate_rejects_a_different_runtime_or_changed_protocol(self):
        client = local_ai.LocalClient()
        report = dict(
            modelDigest="test",
            inferenceConfig=client.inference_config,
            protocolHash=reasoning.protocol_hash(),
            suiteHash=digest(model_evaluation.SUITE.read_bytes()),
            gatePassed=True,
            status="completed",
            recordHash="record",
            counts={},
            scope="synthetic",
        )
        with patch.object(model_evaluation, "read_evaluation", return_value=report):
            self.assertTrue(
                model_evaluation.gate_for("test", client.inference_config)["passed"]
            )
            self.assertFalse(
                model_evaluation.gate_for("other-model", client.inference_config)[
                    "passed"
                ]
            )
            self.assertFalse(
                model_evaluation.gate_for(
                    "test", local_ai.LocalClient(thinking=True).inference_config
                )["passed"]
            )
            with patch.object(reasoning, "protocol_hash", return_value="changed"):
                self.assertFalse(
                    model_evaluation.gate_for("test", client.inference_config)["passed"]
                )

    def test_evaluation_rejects_tampering_before_returning_results(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as folder, patch.object(
            model_evaluation, "ROOT", Path(folder)
        ):
            root = Path(folder) / "data/local-evaluations"
            root.mkdir(parents=True)
            report = {"gatePassed": True}
            hashed = digest(canonical(report))
            (root / "evaluation.json").write_bytes(
                canonical({**report, "gatePassed": False, "recordHash": hashed})
            )
            (root / "latest.json").write_bytes(
                canonical(
                    {"file": "data/local-evaluations/evaluation.json", "hash": hashed}
                )
            )
            with self.assertRaises(ValueError):
                model_evaluation.read_evaluation()
