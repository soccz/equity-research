import copy
import unittest
from equitylab import narrative, memory_research, business
from equitylab.pipeline import load_latest


class NarrativeTests(unittest.TestCase):
    def test_hidden_filing_content_is_excluded_and_inline_text_preserved(self):
        raw = b'<html><head><title>Hidden document title long enough</title></head><body><ix:header><div>Hidden taxonomy data must never be read as narrative.</div></ix:header><div style="display: none">Hidden facts are not management explanations here.</div><p>Revenue increased with <span>prices</span> and unchanged volume.</p></body></html>'
        rows = narrative.extract(raw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["text"], "Revenue increased with prices and unchanged volume."
        )

    def test_table_rows_retain_cell_separation_without_becoming_prose(self):
        raw = "<TITLE>주요 제품 및 가격 변화에 관한 설명</TITLE><TABLE><TR><TD>DRAM 및 NAND 제품의 당기와 비교 기간</TD><TD>100</TD><TD>90</TD></TR></TABLE>".encode()
        row = narrative.extract(raw)[0]
        self.assertEqual(row["kind"], "table")
        self.assertIn(" | 100 | 90", row["text"])
        self.assertIn("가격 변화", row["heading"])

    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_latest()
        cls.companies = copy.deepcopy(cls.snapshot["companies"])
        for c in cls.companies:
            if c["id"] in ["MU", "000660"]:
                c["narrative"] = narrative.build(c, cls.snapshot["asOf"])

    def test_archived_corpus_hash_is_reproducible_and_source_bound(self):
        c = next(c for c in self.companies if c["id"] == "MU")
        body = narrative.load(c)
        self.assertGreater(len(body["passages"]), 500)
        self.assertEqual(
            body["accession"], c["financials"]["current"]["cfo"]["accession"]
        )
        corrupt = copy.deepcopy(c)
        corrupt["narrative"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            narrative.load(corrupt)

    def test_new_filing_does_not_reuse_prior_management_text(self):
        c = copy.deepcopy(next(c for c in self.companies if c["id"] == "MU"))
        c["financials"]["current"]["cfo"]["accession"] = "different"
        self.assertEqual(narrative.build(c, self.snapshot["asOf"])["status"], "stale")

    def test_memory_cash_excludes_received_dividends_only_once(self):
        c = next(c for c in self.companies if c["id"] == "000660")
        case = memory_research.build(c, self.companies)
        kr = next(r for r in case["comparisons"] if r["company"] == "000660")
        us = next(r for r in case["comparisons"] if r["company"] == "MU")
        self.assertAlmostEqual(
            (kr["reportedCashMargin"] - kr["exDividendCashMargin"]) * kr["revenue"],
            13983648000000,
            delta=0.02,
        )
        self.assertIsNone(us["exDividendCashMargin"])
        self.assertIn("DRAM 비교 기준", case["claims"][0]["basis"])

    def test_memory_sensitivity_uses_product_not_sum_of_price_and_volume(self):
        r = memory_research.sensitivity(-0.2, 0.25)
        self.assertAlmostEqual(r["revenueChange"], 0)
        self.assertAlmostEqual(r["volumeToOffsetPrice"], 0.25)
        with self.assertRaises(ValueError):
            memory_research.sensitivity(-1, 0.2)

    def test_micron_products_and_segments_reconcile_but_remain_distinct_axes(self):
        c = copy.deepcopy(next(c for c in self.companies if c["id"] == "MU"))
        b = business.build(c, self.snapshot["asOf"])
        self.assertEqual(len(b["segments"]), 5)
        self.assertEqual(len(b["products"]), 3)
        self.assertEqual(
            b["reconciliations"]["operatingIncome"]["reportedAdjustment"], -966000000
        )
        self.assertEqual(b["reconciliations"]["operatingIncome"]["unexplained"], 0)
        self.assertEqual(b["productReconciliation"]["status"], "reconciled")


if __name__ == "__main__":
    unittest.main()
