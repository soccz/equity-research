import copy
import json
import unittest
from equitylab.pipeline import load_latest
from equitylab.security import load, parse, number
from equitylab.valuation import build
from equitylab.data import ROOT


class ShareTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_latest()
        cls.companies = {c["id"]: c for c in cls.snapshot["companies"]}

    def test_naver_issued_less_treasury_and_explicit_aggregate(self):
        c = copy.deepcopy(self.companies["035420"])
        result = load(c, self.snapshot["asOf"])
        self.assertEqual(result["shares"]["issued"], 156944242)
        self.assertEqual(result["shares"]["treasury"], 7139909)
        self.assertEqual(result["shares"]["value"], 149804333)
        self.assertTrue(result["aggregateComplete"])
        self.assertIsNone(result["classes"][1]["fact"]["value"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(
            build(c, self.snapshot["asOf"])["security"]["status"], "available"
        )

    def test_dash_does_not_become_zero_without_an_exhaustive_aggregate(self):
        self.assertIsNone(number("-"))
        c = copy.deepcopy(self.companies["035420"])
        source = load(c, self.snapshot["asOf"])["source"]
        body = json.loads((ROOT / source["file"]).read_text())
        body["list"] = [r for r in body["list"] if r["se"] != "합계"]
        result = parse(c, body, source)
        self.assertFalse(result["aggregateComplete"])
        self.assertTrue(result["issues"])

    def test_issuer_receipt_period_and_arithmetic_are_fail_closed(self):
        c = copy.deepcopy(self.companies["035420"])
        source = load(c, self.snapshot["asOf"])["source"]
        original = json.loads((ROOT / source["file"]).read_text())
        for field, value in [
            ("corp_code", "99999999"),
            ("rcept_no", "20261231000001"),
            ("stlm_dt", "2026-12-31"),
            ("distb_stock_co", "1"),
        ]:
            body = copy.deepcopy(original)
            body["list"][0][field] = value
            with self.assertRaises(ValueError):
                parse(c, body, source)

    def test_preferred_stock_rights_are_not_assigned_to_common(self):
        c = copy.deepcopy(self.companies["005930"])
        result = load(c, self.snapshot["asOf"])
        self.assertTrue(result["issues"])
        self.assertTrue(
            any(not r["common"] and r["fact"]["value"] for r in result["classes"])
        )
        self.assertEqual(
            build(c, self.snapshot["asOf"])["security"]["status"], "unresolved"
        )

    def test_missing_treasury_remains_missing_with_equal_issued_outstanding(self):
        c = copy.deepcopy(self.companies["373220"])
        result = load(c, self.snapshot["asOf"])
        self.assertTrue(result["aggregateComplete"])
        self.assertIsNone(result["shares"]["treasury"])
        self.assertEqual(result["shares"]["issued"], result["shares"]["value"])
        self.assertEqual(result["issues"], [])

    def test_voting_label_requires_both_exact_ordinary_share_facts(self):
        c = copy.deepcopy(self.companies["068270"])
        result = load(c, self.snapshot["asOf"])
        self.assertEqual(result["shares"]["value"], 228570251)
        self.assertEqual(result["issues"], [])
        self.assertEqual(len(result["classes"][0]["classEvidence"]), 2)
        source = result["source"]
        body = json.loads((ROOT / source["file"]).read_text())
        self.assertIsNone(parse(c, body, source)["shares"])
        # A single coincident amount is not enough to identify the class.
        proof = result["classes"][0]["classEvidence"][:1]
        self.assertIsNone(parse(c, body, source, proof)["shares"])

    def test_conflicting_share_notes_hold_price_even_with_balanced_api_table(self):
        for cid in ("012450", "034020"):
            c = copy.deepcopy(self.companies[cid])
            security = build(c, self.snapshot["asOf"])["security"]
            self.assertEqual(security["status"], "unresolved")
            self.assertTrue(any("충돌" in t or "다름" in t for t in security["issues"]))

    def test_explicit_common_label_with_particle_keeps_preferred_rights_separate(self):
        c = copy.deepcopy(self.companies["009150"])
        table = load(c, self.snapshot["asOf"])
        self.assertEqual(table["shares"]["value"], 72693696)
        self.assertTrue(table["classes"][0]["common"])
        self.assertFalse(table["classes"][1]["common"])
        self.assertTrue(any("우선주" in t for t in table["issues"]))
        self.assertFalse(any("보통주)" in t for t in table["issues"]))
        self.assertEqual(
            build(c, self.snapshot["asOf"])["security"]["status"], "unresolved"
        )

    def test_all_korean_sources_preserve_current_filing_and_add_to_replay(self):
        for original in self.companies.values():
            if original["market"] != "KR":
                continue
            c = copy.deepcopy(original)
            result = load(c, self.snapshot["asOf"])
            self.assertEqual(
                result["source"]["accession"],
                c["financials"]["current"]["cfo"]["accession"],
            )
            self.assertIn(result["source"], c["sources"])
            self.assertIsNone(load(c, "2020-01-01"))


if __name__ == "__main__":
    unittest.main()
