import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from equitylab import peer_studies
from equitylab.pipeline import load_latest


class PeerStudiesTests(unittest.TestCase):
    def test_both_sides_have_current_original_passages_and_no_investment_approval(self):
        rows = peer_studies.build(load_latest()["companies"])
        self.assertEqual(len(rows), 21)
        for row in rows:
            self.assertEqual(row["status"], "source_draft")
            self.assertFalse(row["financialApproval"])
            self.assertEqual(len(row["sides"]), 2)
            for side in row["sides"]:
                self.assertEqual(
                    {s["id"] for s in side["sources"]}, set(side["passageIds"])
                )
                self.assertTrue(
                    all(s["sourceHash"] and s["sourceUrl"] for s in side["sources"])
                )

    def test_either_changed_filing_invalidates_the_whole_pair(self):
        companies = copy.deepcopy(load_latest()["companies"])
        next(c for c in companies if c["id"] == "AMZN")["narrative"][
            "accession"
        ] = "new"
        row = next(r for r in peer_studies.build(companies) if r["id"] == "cloud-usage")
        self.assertEqual(row["status"], "stale")
        self.assertEqual({s["company"] for s in row["sides"]}, {"MSFT", "AMZN"})
        self.assertTrue(row["issues"])
