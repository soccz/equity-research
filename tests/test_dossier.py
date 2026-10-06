import copy
import unittest
from equitylab import dossier, pipeline
from equitylab.local_ai import LocalClient, validate_draft, validate_critic


class DossierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = pipeline.load_latest()
        cls.companies = {c["id"]: c for c in cls.snapshot["companies"]}

    def test_micron_reported_cash_bridge_and_receivable_sign(self):
        d = dossier.build(self.companies["MU"], self.snapshot["asOf"])
        parts = {p["id"]: p["value"] for p in d["current"]["parts"]}
        self.assertEqual(parts["receivables"], -19_953_000_000)
        self.assertEqual(parts["inventory"], -212_000_000)
        self.assertEqual(parts["cfo"], 45_702_000_000)
        self.assertEqual(d["current"]["residual"], 0)
        self.assertTrue(d["current"]["reconciled"])

    def test_korean_notes_use_consolidated_reported_amounts_and_common_shares(self):
        d = dossier.build(self.companies["000660"], self.snapshot["asOf"])
        parts = {p["id"]: p["value"] for p in d["current"]["parts"]}
        self.assertEqual(parts["fair_value"], -63_178_974_000_000)
        self.assertEqual(parts["receivables"], -23_342_531_000_000)
        self.assertEqual(parts["da"], 7_340_867_000_000)
        self.assertEqual(d["pricing"]["shares"]["value"], 711_075_500)
        self.assertGreater(d["current"]["residual"], 0)
        self.assertEqual(d["current"]["parts"][-2]["kind"], "residual")
        self.assertFalse(d["current"]["missing"])

    def test_same_filing_required_and_conflicts_rejected(self):
        row = dict(
            tag="x",
            start=None,
            end="2026-01-01",
            accession="a",
            unit="shares",
            value=12,
        )
        self.assertIsNone(
            dossier.select_unique([row], "x", None, "2026-01-01", "b", "shares")
        )
        self.assertIsNone(
            dossier.select_unique([row], "x", None, "2026-01-01", "a", "USD")
        )
        with self.assertRaises(ValueError):
            dossier.select_unique(
                [row, {**row, "value": 13}], "x", None, "2026-01-01", "a", "shares"
            )

    def test_cash_requirement_known_perpetuity_and_discount_direction(self):
        # With no growth in either phase, a level perpetuity is cash / required return.
        r = dossier.price_requirements(1000, 0, 0.1, 0)
        self.assertAlmostEqual(r["requiredBaseCash"], 100)
        self.assertAlmostEqual(r["presentValue"], 1000)
        self.assertGreater(
            dossier.price_requirements(1000, 0.1, 0.14)["requiredBaseCash"],
            dossier.price_requirements(1000, 0.1, 0.08)["requiredBaseCash"],
        )
        for args in [
            (1000, 0.1, 0.02, 0.02),
            (float("nan"), 0.1, 0.1, 0.02),
            (-1, 0.1, 0.1, 0.02),
        ]:
            with self.assertRaises(ValueError):
                dossier.price_requirements(*args)

    def test_model_endpoint_cannot_use_external_host_or_credentials(self):
        for url in [
            "https://api.openai.com",
            "http://localhost:11434",
            "http://127.0.0.1.evil.test",
            "http://user@127.0.0.1",
            "http://127.0.0.1/?proxy=x",
        ]:
            with self.assertRaises(ValueError):
                LocalClient(url)
        LocalClient("http://127.0.0.1:11435")

    def test_unknown_reference_and_unverified_numeral_fail(self):
        d = {
            "summary": "공시를 검토한다.",
            "claims": [
                {
                    "text": "채권 회수 시차를 점검한다.",
                    "evidence": ["current.receivables"],
                    "alternative": "성장에 따른 회수 시차일 수 있다.",
                    "check": "다음 공시의 채권 회수와 대손을 확인한다.",
                }
            ],
        }
        ev = [{"id": "current.receivables"}]
        validate_draft(d, ev)
        for change in [{"evidence": ["invented"]}, {"text": "수익률은 99%이다."}]:
            bad = copy.deepcopy(d)
            bad["claims"][0].update(change)
            with self.assertRaises(ValueError):
                validate_draft(bad, ev)

    def test_public_payload_excludes_private_model_notes(self):
        from equitylab.publication import public_payload

        source = {
            "snapshot": {"companies": [], "contentHash": "example"},
            "localReviews": {"MU": {"private": "notes"}},
        }
        self.assertNotIn("localReviews", public_payload(source))
        self.assertIn("localReviews", source)

    def test_critique_cannot_pass_a_challenged_claim(self):
        r = {
            "verdict": "usable_with_caveats",
            "issues": ["자체 점검이다."],
            "unsupportedClaims": [0],
        }
        with self.assertRaises(ValueError):
            validate_critic(r, 1)
        r["verdict"] = "revise"
        validate_critic(r, 1)
