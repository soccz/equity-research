import copy
import json
import unittest
from equitylab import data, filing_labels
from equitylab.pipeline import load_latest


class SupplementalSourceTests(unittest.TestCase):
    def test_ford_primary_filing_supplies_missing_half_year_without_segment_mixing(
        self,
    ):
        c = next(c for c in data.UNIVERSE if c["id"] == "F")
        rows, sources = data.sec_facts(c, False)
        s = data.statement(rows, "2026-09-29")
        self.assertEqual((s["start"], s["end"]), ("2026-01-01", "2026-06-30"))
        self.assertEqual(s["current"]["revenue"]["value"], 91549000000)
        self.assertEqual(s["current"]["cfo"]["value"], 5661000000)
        self.assertEqual(s["current"]["capex"]["value"], 4758000000)
        self.assertEqual(s["current"]["cfo"]["filedAt"], "2026-07-29")
        self.assertEqual(s["current"]["revenue"]["dimensions"], [])
        self.assertTrue(any("submissions" in src["url"] for src in sources))
        before = data.statement(rows, "2026-07-28")
        self.assertEqual(before["end"], "2026-03-31")

    def test_lilly_caption_matches_amount_period_and_unit_not_only_a_substring(self):
        c = next(c for c in load_latest()["companies"] if c["id"] == "LLY")
        result = filing_labels.investment_definition(copy.deepcopy(c))
        self.assertEqual(result["evidence"]["value"], 5259000000)
        fact = c["financials"]["current"]["capex"]
        source = result["source"]
        html = data.read_verified(data.ROOT / source["file"], source["sha256"]).decode()
        for change in [
            dict(value=3207000000),
            dict(start="2026-04-01"),
            dict(unit="KRW"),
        ]:
            with self.subTest(change=change), self.assertRaisesRegex(
                ValueError, "caption"
            ):
                filing_labels.verify_caption(
                    html, {**fact, **change}, result["evidence"]["caption"]
                )

    def test_conflicting_primary_filing_and_companyfacts_cannot_be_silently_selected(
        self,
    ):
        from equitylab.sec_supplements import supplement

        c = next(c for c in data.UNIVERSE if c["id"] == "F")
        rows, _ = data.sec_facts(c, False)
        r = next(
            r
            for r in rows
            if r.get("provenance") == "primary_filing_supplement"
            and r["metric"] == "cfo"
        )
        with self.assertRaisesRegex(ValueError, "disagrees"):
            supplement(c, [dict(r, value=r["value"] + 100)])


if __name__ == "__main__":
    unittest.main()
