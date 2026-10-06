import copy
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
from equitylab import dossier, pipeline, reasoning, receivables as ar, ledger
from equitylab import receivable_tracking as tracking


class ReceivableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.companies = {
            c["id"]: copy.deepcopy(c)
            for c in pipeline.load_latest()["companies"]
            if c["id"] in ("MU", "000660")
        }
        for c in cls.companies.values():
            c["dossier"] = dossier.build(c, "2026-09-29")

    def test_micron_trade_and_total_scope_are_not_interchangeable(self):
        d = self.companies["MU"]["dossier"]["receivables"]
        self.assertEqual(
            d["current"]["balances"]["closing"]["tradeNet"]["value"], 26_894_000_000
        )
        self.assertEqual(
            d["current"]["balances"]["closing"]["totalNet"]["value"], 31_025_000_000
        )
        self.assertEqual(d["current"]["openingDate"], "2025-08-28")
        self.assertEqual(d["current"]["days"], 273)
        self.assertAlmostEqual(
            d["current"]["metrics"]["averageDaysProxy"], 58.87587862055
        )
        self.assertEqual(d["reconciliation"]["balanceChange"], 21_760_000_000)
        self.assertEqual(d["reconciliation"]["unexplainedDifference"], 1_807_000_000)
        self.assertIsNone(d["current"]["metrics"]["allowanceRate"])
        self.assertEqual(d["notes"][0]["kind"], "management_attribution")

    def test_hynix_gross_impairment_and_net_have_matching_dimensions(self):
        d = self.companies["000660"]["dossier"]["receivables"]
        balances = d["current"]["balances"]["closing"]
        self.assertEqual(balances["tradeGross"]["value"], 47_823_937_000_000)
        self.assertEqual(balances["tradeAllowance"]["value"], -2_542_000_000)
        self.assertEqual(balances["tradeNet"]["value"], 47_821_395_000_000)
        self.assertEqual(d["current"]["openingDate"], "2025-12-31")
        self.assertEqual(d["previous"]["end"], "2025-06-30")
        self.assertEqual(
            d["reconciliation"]["unexplainedDifference"], 6_279_786_000_000
        )
        self.assertLess(d["averageDaysChange"], 0)
        self.assertGreater(
            d["current"]["metrics"]["closingDaysProxy"],
            d["previous"]["metrics"]["closingDaysProxy"],
        )
        self.assertEqual({n["id"] for n in d["notes"]}, {"transfers", "creditPolicy"})

    def test_dates_not_context_names_and_unrelated_dimensions_rejected(self):
        base = '<d:explicitMember dimension="ifrs:ConsolidatedAndSeparateFinancialStatementsAxis">ifrs:ConsolidatedMember</d:explicitMember>'
        extra = '<d:explicitMember dimension="ifrs:RelatedPartyAxis">ifrs:ParentMember</d:explicitMember>'
        typed = '<d:typedMember dimension="ifrs:CustomerAxis"><customer>A</customer></d:typedMember>'
        xml = f'<x:xbrl xmlns:x="{ar.NS["x"]}" xmlns:d="{ar.NS["d"]}">'
        for name, dims in [
            ("PFY2025eHY", base),
            (
                "separate",
                base.replace("ifrs:ConsolidatedMember", "ifrs:SeparateMember"),
            ),
            ("party", base + extra),
            ("typed", base + typed),
        ]:
            xml += f'<x:context id="{name}"><x:entity><x:segment>{dims}</x:segment></x:entity><x:period><x:instant>2025-12-31</x:instant></x:period></x:context>'
        xml += "</x:xbrl>"
        contexts, _ = ar.contexts(ET.fromstring(xml), "KRW")
        self.assertEqual(set(contexts), {"PFY2025eHY"})
        self.assertEqual(contexts["PFY2025eHY"]["end"], "2025-12-31")

    def test_future_restatement_cannot_change_a_selected_balance(self):
        row = dict(
            key="tradeNet",
            end="2025-12-31",
            accession="a",
            filedAt="2026-03-01",
            value=100,
        )
        future = dict(row, accession="b", filedAt="2026-10-01", value=500)
        self.assertEqual(
            ar.select([row, future], "tradeNet", "2025-12-31", "2026-09-29")["value"],
            100,
        )
        self.assertIsNone(
            ar.select([row], "tradeNet", "2025-12-31", "2026-09-29", "different-filing")
        )
        with self.assertRaises(ValueError):
            ar.select(
                [row, dict(row, value=101)], "tradeNet", "2025-12-31", "2026-09-29"
            )

    def test_missing_opening_balance_is_not_zero_or_comparable_period(self):
        rev = dict(
            start="2026-01-01",
            end="2026-06-30",
            filedAt="2026-08-01",
            accession="a",
            value=1000,
        )
        wrong = dict(
            key="tradeNet",
            end="2025-06-30",
            filedAt="2026-08-01",
            accession="a",
            value=99,
        )
        right = dict(wrong, end="2026-06-30", value=100)
        view = ar.period_view(rev, [wrong, right], True)
        self.assertIsNone(view["metrics"])
        self.assertIsNone(view["balances"]["opening"]["tradeNet"])

    def test_inconsistent_gross_net_is_rejected_instead_of_relabelled(self):
        rev = dict(
            start="2026-01-01",
            end="2026-06-30",
            filedAt="2026-08-01",
            accession="a",
            value=1000,
        )
        row = dict(end="2026-06-30", filedAt="2026-08-01", accession="a")
        values = [
            dict(row, key=k, value=v)
            for k, v in [("tradeNet", 100), ("tradeGross", 110), ("tradeAllowance", -2)]
        ]
        with self.assertRaises(ValueError):
            ar.period_view(rev, values, True)

    def test_model_receives_available_allowance_and_correct_remaining_gaps(self):
        c = self.companies["000660"]
        packet = reasoning.input_packet(c)
        compact = reasoning.compact_packet(packet)
        self.assertFalse(any("대손" in g for g in packet["missingEvidence"]))
        self.assertEqual(
            compact["receivableDiagnostics"]["periods"][1]["tradeNet"]["closing"],
            47.821395,
        )
        self.assertGreater(
            compact["receivableDiagnostics"]["periods"][1]["metrics"]["allowanceRate"],
            0,
        )
        self.assertIn("실제 회수일수", compact["receivableDiagnostics"]["definition"])
        original = c["dossier"]["evidenceHash"]
        changed = copy.deepcopy(c["dossier"]["receivables"])
        changed["notes"][0]["text"] += " changed"
        self.assertNotEqual(
            original,
            ar.digest(
                ar.canonical(dict(facts=c["dossier"]["evidence"], receivables=changed))
            ),
        )

    def registration(self):
        return dict(
            metric=tracking.CONTRACT["metric"],
            contract=tracking.CONTRACT,
            contractHash=ar.digest(ar.canonical(tracking.CONTRACT)),
            periodEnd="2025-06-30",
            recordedAt="2026-08-13T00:00:00+00:00",
            expected=None,
        )

    def test_registration_keeps_original_baseline_on_repeated_runs(self):
        snapshot = dict(
            companies=list(self.companies.values()),
            contentHash="initial",
            asOf="2026-09-29",
        )
        with tempfile.TemporaryDirectory(
            dir=ar.ROOT / "data/cache/tmp"
        ) as folder, patch.object(tracking, "ROOT", Path(folder)):
            rows = tracking.register(snapshot)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(r["expected"] is None for r in rows))
            second = tracking.register(dict(snapshot, contentHash="new-run"))
            self.assertEqual(second, [])
            saved = ledger.read(Path(folder) / "data/ledger/conditions.jsonl")
            self.assertTrue(all(r["snapshotHash"] == "initial" for r in saved))
            self.assertTrue(
                all(
                    ledger.evaluate(r, self.companies[r["company"]])["status"]
                    == "pending"
                    for r in saved
                )
            )

    def test_condition_and_prediction_are_separate_with_source_evidence(self):
        registration = self.registration()
        result = ledger.evaluate(registration, self.companies["000660"])
        self.assertEqual(result["status"], "met")
        self.assertIsNone(result["predictionCorrect"])
        self.assertAlmostEqual(result["value"], -14.0424711632)
        self.assertEqual(result["unit"], "days")
        self.assertEqual(len(result["evidence"]), 6)
        self.assertFalse(
            ledger.evaluate(
                dict(registration, expected=False), self.companies["000660"]
            )["predictionCorrect"]
        )

    def test_same_local_day_and_previously_known_filing_are_not_future_scores(self):
        registration = self.registration()
        for recorded in ("2026-08-13T15:00:00+00:00", "2026-09-30T00:00:00+00:00"):
            result = ledger.evaluate(
                dict(registration, recordedAt=recorded), self.companies["000660"]
            )
            self.assertEqual(result["status"], "pending")
            self.assertIsNone(result["predictionCorrect"])

    def test_missing_balance_and_changed_contract_remain_unresolved(self):
        registration = self.registration()
        company = copy.deepcopy(self.companies["000660"])
        company["dossier"]["receivables"]["current"]["balances"]["opening"][
            "tradeNet"
        ] = None
        self.assertEqual(ledger.evaluate(registration, company)["status"], "unresolved")
        self.assertEqual(
            ledger.evaluate(
                dict(registration, contractHash="changed"), self.companies["000660"]
            )["status"],
            "unresolved",
        )

    def test_future_amendment_and_wrong_currency_block_condition_grading(self):
        for changes in ({"filedAt": "2027-01-01"}, {"unit": "USD"}):
            company = copy.deepcopy(self.companies["000660"])
            company["dossier"]["receivables"]["previous"]["balances"]["opening"][
                "tradeNet"
            ].update(changes)
            result = ledger.evaluate(self.registration(), company)
            self.assertEqual(result["status"], "unresolved")


if __name__ == "__main__":
    unittest.main()
