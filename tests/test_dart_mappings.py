import copy
import json
import unittest

from equitylab import data, dart_mappings
from equitylab.company_analysis import investment_scope


class ReviewedDartExtensionTests(unittest.TestCase):
    def test_kt_current_preserves_reported_scope_and_comparatives(self):
        imports = json.loads((data.ROOT / "data/dart-imports.json").read_text())
        item = next(x for x in imports if x["filing"]["rcept_no"] == "20260814003463")
        rows = data.parse_dart(
            data.read_verified(data.ROOT / item["file"], item["sha256"]), item
        )
        statement = data.statement(rows, "2026-09-29")
        current, prior = statement["current"]["capex"], statement["previous"]["capex"]
        self.assertEqual(current["value"], 1_184_005e6)
        self.assertEqual(prior["value"], 2_029_371e6)
        self.assertEqual(investment_scope(current), "유형자산·투자부동산 취득")
        self.assertIn("무형 취득은 별도", current["scopeNote"])
        self.assertIn("1,184,005", current["captionPassage"]["text"])
        self.assertEqual(current["basis"], "consolidated")
        self.assertNotEqual(investment_scope(current), "유형자산 취득")

    def test_mapping_never_transfers_to_a_new_receipt_or_issuer(self):
        base = dict(
            ticker="030200",
            filing=dict(rcept_no="20260814003463"),
            sha256=dart_mappings.KT_CURRENT["sha256"],
        )
        for ticker, receipt in [
            ("017670", "20260814003463"),
            ("030200", "20261114000000"),
        ]:
            item = copy.deepcopy(base)
            item.update(ticker=ticker, filing=dict(rcept_no=receipt))
            self.assertEqual(dart_mappings.reviewed(item), {})
        base["sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "source changed"):
            dart_mappings.reviewed(base)

    def test_kt_annual_uses_its_own_original_caption(self):
        contract = dart_mappings.KT_ANNUAL
        item = dict(
            ticker=contract["ticker"],
            filing=dict(rcept_no=contract["accession"]),
            sha256=contract["sha256"],
        )
        result = next(iter(dart_mappings.reviewed(item).values()))
        self.assertIn("3,596,545", result["captionPassage"]["text"])
        self.assertIn("20260323001553", result["captionSource"]["url"])
