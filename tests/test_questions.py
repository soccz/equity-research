import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from equitylab import questions, publication
from equitylab.data import canonical, digest
from equitylab.pipeline import load_latest


class QuestionSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_latest()
        cls.companies = {c["id"]: c for c in cls.snapshot["companies"]}

    def test_applicable_designs_retain_financial_and_security_scope(self):
        for c in self.companies.values():
            p = questions.packet(c)
            ids = {v["id"] for v in p["candidates"]}
            self.assertTrue(
                {"cash_conversion", "investment_cycle", "revenue_mix"} <= ids
            )
            self.assertEqual(
                "financial_scope" in ids, c["id"] in ("GM", "F", "CAT", "005380")
            )
            available = c["valuation"]["security"]["status"] == "available"
            self.assertEqual("price_conditions" in ids, available)
            self.assertEqual("security_rights" in ids, not available)
            self.assertEqual(
                "business_scope" in ids,
                c.get("cashScope", {}).get("status") == "review_required",
            )

    def test_model_cannot_write_a_cause_or_choose_unknown_duplicate_scope(self):
        p = questions.packet(self.companies["MSFT"])
        for choice in [
            {"primary": "cash_conversion", "secondary": "cash_conversion"},
            {"primary": "financial_scope", "secondary": "cash_conversion"},
            {"primary": "cash_conversion", "secondary": "invented"},
            {
                "primary": "cash_conversion",
                "secondary": "investment_cycle",
                "cause": "fabricated",
            },
        ]:
            with self.assertRaises(ValueError):
                questions.validate(choice, p)
        valid = {"primary": "cash_conversion", "secondary": "investment_cycle"}
        self.assertEqual(questions.validate(valid, p), valid)

    def test_prompt_does_not_require_model_to_reproduce_filing_facts(self):
        p = questions.packet(self.companies["MSFT"])
        prompt = questions.prompt_packet(p)
        self.assertTrue(prompt["observations"])
        self.assertTrue(prompt["segmentChanges"])
        self.assertNotIn("evidence", prompt["segmentChanges"][0])
        self.assertEqual(
            set(questions.schema(p)["properties"]), {"primary", "secondary"}
        )

    def test_new_price_conditions_invalidate_previous_selection_input(self):
        c = copy.deepcopy(self.companies["MSFT"])
        before = digest(canonical(questions.packet(c)))
        c["researchCase"]["pricing"]["price"] += 1
        self.assertNotEqual(before, digest(canonical(questions.packet(c))))

    def test_private_selection_is_removed_from_public_projection(self):
        result = publication.public_payload(
            dict(
                snapshot=dict(companies=[], contentHash="test"),
                questionSelections={"MSFT": {"private": "selection"}},
            )
        )
        self.assertNotIn("questionSelections", result)
        self.assertNotIn("private", json.dumps(result))
        with patch("equitylab.local_ai.read_reviews", return_value={}), patch.object(
            questions, "read", return_value={"MSFT": {"status": "selected"}}
        ):
            with self.assertRaisesRegex(ValueError, "Private local analysis"):
                publication.build_site()

    def test_archived_response_is_exact_and_new_source_identity_makes_it_stale(self):
        class Client:
            inference_config = dict(think=True, options={"temperature": 0.6})

            def model(self, name):
                return {"digest": "test-model"}

            def call(self, name):
                return {"models": [{"digest": "test-model", "size_vram": 100}]}

            def generate(self, model, messages, schema, archive):
                choice = {"primary": "cash_conversion", "secondary": "investment_cycle"}
                request = dict(
                    model=model,
                    messages=messages,
                    format=schema,
                    **self.inference_config
                )
                response = {"message": {"content": json.dumps(choice)}}
                archive.with_name("selection-request.json").write_bytes(
                    canonical(request)
                )
                archive.write_bytes(canonical(response))
                return choice, {}, response

        c = copy.deepcopy(self.companies["MSFT"])
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            questions, "ROOT", Path(tmp)
        ):
            r = questions.select(c, "snapshot", Client(), "test:local")
            view = questions.read({"companies": [c]})[c["id"]]
            self.assertEqual(view["choice"], r["choice"])
            # Recalculation and canonical snapshot loading reorder mappings but
            # preserve the same evidence. The exact archived request stays intact.
            reordered = json.loads(
                json.dumps(c), object_pairs_hook=lambda pairs: dict(reversed(pairs))
            )
            self.assertEqual(
                questions.read({"companies": [reordered]})[c["id"]]["choice"],
                r["choice"],
            )
            self.assertEqual(
                [q["id"] for q in view["questions"]],
                ["cash_conversion", "investment_cycle"],
            )
            c["financials"]["current"]["cfo"]["sourceHash"] = "corrected-source"
            self.assertEqual(
                questions.read({"companies": [c]})[c["id"]]["status"], "stale"
            )
            raw = next(Path(tmp).rglob("selection-raw.json"))
            raw.write_text("{}")
            with self.assertRaisesRegex(ValueError, "archive changed"):
                questions.read({"companies": [self.companies["MSFT"]]})

    def test_failed_inference_is_visible_and_not_replaced_with_a_default_choice(self):
        class Client:
            inference_config = dict(think=True, options={})

            def model(self, name):
                return {"digest": "test-model"}

            def generate(self, *args, **kwargs):
                raise TimeoutError("local generation did not complete")

        c = self.companies["MSFT"]
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            questions, "ROOT", Path(tmp)
        ):
            r = questions.select(c, "snapshot", Client(), "test:local")
            self.assertEqual(r["status"], "failed")
            self.assertNotIn("choice", r)
            self.assertEqual(
                questions.read({"companies": [c]})[c["id"]]["status"], "failed"
            )


if __name__ == "__main__":
    unittest.main()
