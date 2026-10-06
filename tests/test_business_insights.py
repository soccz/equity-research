import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from equitylab import business_insights
from equitylab.pipeline import load_latest


class BusinessInsightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.companies = {c["id"]: c for c in load_latest()["companies"]}

    def test_every_authored_reading_points_to_current_actual_passages(self):
        ids = [
            r["company"]
            for r in json.loads(
                (business_insights.ROOT / "data/business-insights.json").read_text()
            )["cases"]
        ]
        self.assertEqual(len(ids), 60)
        self.assertEqual(set(ids), set(self.companies))
        for id in ids:
            c = self.companies[id]
            r = business_insights.build(c)
            self.assertEqual(r["status"], "source_draft")
            self.assertEqual(
                r["accession"], c["financials"]["current"]["cfo"]["accession"]
            )
            self.assertEqual({x["id"] for x in r["sources"]}, set(r["passageIds"]))
            self.assertTrue(r["countercase"])
            self.assertTrue(r["changeCondition"])
            self.assertIn("로컬 모델 생성문", r["scope"])

    def test_updated_filing_and_corpus_cannot_silently_reuse_authored_claims(self):
        c = copy.deepcopy(self.companies["GOOGL"])
        c["narrative"]["evidenceHash"] = "0" * 64
        self.assertEqual(business_insights.build(c)["status"], "stale")

    def test_unknown_passage_is_rejected_instead_of_merely_linking_a_filing(self):
        c = self.companies["MSFT"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data").mkdir()
            (root / "data/business-insights.json").write_text(
                json.dumps(
                    dict(
                        cases=[
                            dict(
                                company="MSFT",
                                accession=c["narrative"]["accession"],
                                corpusHash=c["narrative"]["evidenceHash"],
                                passageIds=["fabricated"],
                            )
                        ]
                    )
                )
            )
            with patch.object(business_insights, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "unknown"):
                    business_insights.build(c)


if __name__ == "__main__":
    unittest.main()
