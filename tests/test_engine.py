import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from equitylab import data, ledger, pipeline, research
from equitylab import dart, fundamental


class ResearchContractTests(unittest.TestCase):
    def test_dart_latest_period_wins_over_late_older_period_correction(self):
        c = next(c for c in data.UNIVERSE if c["id"] == "000660")
        common = dict(corp_code=c["dartCorpCode"], stock_code=c["id"])
        rows = [
            dict(
                common,
                report_nm="반기보고서 (2026.06)",
                rcept_dt="20260814",
                rcept_no="20260814003509",
            ),
            dict(
                common,
                report_nm="[기재정정]사업보고서 (2025.12)",
                rcept_dt="20260910",
                rcept_no="20260910000001",
            ),
        ]
        selected, code = dart.choose_filing(rows, c, "2026-09-29")
        self.assertEqual(selected["rcept_no"], "20260814003509")
        self.assertEqual(code, "11012")

    def test_dart_exception_does_not_reveal_credential(self):
        key = "a" * 40
        with patch.dict("os.environ", {"DART_API_KEY": key}), patch.object(
            dart, "urlopen", side_effect=RuntimeError("url with key " + key)
        ):
            with self.assertRaises(RuntimeError) as caught:
                dart.request("list.json", {})
        self.assertNotIn(key, str(caught.exception))

    def test_fundamental_future_filings_cannot_change_historical_signal(self):
        c = next(c for c in data.UNIVERSE if c["id"] == "MU")
        facts, _ = data.sec_facts(c, False)
        day = "2025-08-25"
        before = fundamental.signal(facts, day)
        changed = copy.deepcopy(facts)
        for f in changed:
            if f["filedAt"] >= day:
                f["value"] *= 1000
        self.assertEqual(before, fundamental.signal(changed, day))

    def test_every_historical_financial_fact_precedes_signal_day(self):
        snapshot = pipeline.load_latest()
        for e in snapshot["fundamentalExperiments"]:
            self.assertGreater(e["windowCount"], 0)
            for w in e["windows"]:
                for s in w["signals"].values():
                    self.assertLess(s["filedAt"], w["signalDate"])
                    for f in s["evidence"]:
                        self.assertLess(f["filedAt"], w["signalDate"])
                self.assertGreaterEqual(
                    w["returns"]["oracle_one"] + 1e-12, max(w["returns"].values())
                )

    def test_future_filing_excluded_and_restatement_asof(self):
        rows = [
            dict(
                metric="cfo",
                start="2025-01-01",
                end="2025-06-30",
                filedAt=d,
                value=v,
                priority=0,
                accession=d,
            )
            for d, v in [("2025-08-14", 100), ("2026-08-14", 900)]
        ]
        self.assertEqual(
            data.select_fact(rows, "cfo", "2025-01-01", "2025-06-30", "2025-09-01")[
                "value"
            ],
            100,
        )
        self.assertEqual(
            data.select_fact(rows, "cfo", "2025-01-01", "2025-06-30", "2026-09-01")[
                "value"
            ],
            900,
        )
        self.assertIsNone(
            data.select_fact(rows, "cfo", "2025-01-01", "2025-06-30", "2025-07-01")
        )

    def test_statement_matches_cumulative_period_not_latest_quarter(self):
        facts = []
        for start, end, value in [
            ("2026-01-01", "2026-06-30", 200),
            ("2025-01-01", "2025-06-30", 100),
        ]:
            for metric in ["revenue", "cfo", "capex"]:
                facts.append(
                    dict(
                        metric=metric,
                        start=start,
                        end=end,
                        value=value,
                        filedAt="2026-08-14",
                        priority=0,
                        accession="a",
                        standard="K-IFRS",
                    )
                )
        facts.append(dict(facts[0], start="2026-04-01", value=999))
        result = data.statement(facts, "2026-09-29")
        self.assertEqual(result["current"]["revenue"]["value"], 200)
        self.assertEqual(result["previous"]["cfo"]["value"], 100)
        self.assertEqual(result["days"], 181)

    def test_wrong_duration_is_not_silently_used(self):
        row = dict(
            start="2026-01-01",
            end="2026-06-30",
            value=50,
            filedAt="2026-08-14",
            priority=0,
            accession="a",
            standard="K-IFRS",
        )
        facts = [
            dict(row, metric="cfo"),
            dict(row, metric="capex"),
            dict(row, metric="revenue", start="2026-04-01"),
        ]
        with self.assertRaises(ValueError):
            data.statement(facts, "2026-09-29")

    def test_raw_dart_matches_independent_known_hynix_cells(self):
        facts, _ = data.dart_facts(
            next(c for c in data.UNIVERSE if c["id"] == "000660")
        )
        result = data.statement(facts, "2026-09-29")
        self.assertEqual(result["current"]["revenue"]["value"], 131895033000000)
        self.assertEqual(result["current"]["cfo"]["value"], 91742501000000)
        self.assertEqual(result["previous"]["capex"]["value"], 10615739000000)
        self.assertTrue(all(f["basis"] == "consolidated" for f in facts))

    def test_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory(dir=data.work_temp()) as folder:
            p = Path(folder) / "source"
            p.write_bytes(b"altered")
            with self.assertRaises(ValueError):
                data.read_verified(p, data.digest(b"original"))

    def test_wrong_korean_issuer_is_rejected(self):
        imports = json.loads((data.ROOT / "data/dart-imports.json").read_text())
        item = next(i for i in imports if i["ticker"] == "000660")
        with self.assertRaises(ValueError):
            data.parse_dart(
                (data.ROOT / item["file"]).read_bytes(), {**item, "ticker": "005930"}
            )

    def test_first_observation_is_not_regraded_against_a_later_period(self):
        with tempfile.TemporaryDirectory(dir=data.work_temp()) as folder:
            root = Path(folder)
            path = root / "data/ledger/conditions.jsonl"
            r = ledger.append(
                path, dict(eventId="registered", type="registration", company="MU")
            )
            ledger.append(
                path,
                dict(
                    eventId="first",
                    type="observation",
                    registrationHash=r["hash"],
                    status="not_met",
                ),
            )
            with patch.object(pipeline, "ROOT", root), patch.object(
                pipeline,
                "load_latest",
                return_value={"companies": [dict(id="MU", status="ready")]},
            ), patch.object(pipeline, "export"):
                with patch.object(
                    ledger, "evaluate", side_effect=AssertionError("Must not regrade")
                ):
                    pipeline.observe()
            self.assertEqual(len(ledger.read(path)), 2)
            self.assertEqual(ledger.read(path)[1]["status"], "not_met")

    def test_signed_cash_and_negative_profit(self):
        fact = lambda v: dict(value=v)
        f = dict(
            current={
                k: fact(v)
                for k, v in dict(
                    revenue=100, cfo=10, capex=15, net_income=-2, operating_income=4
                ).items()
            },
            previous={
                k: fact(v)
                for k, v in dict(
                    revenue=100, cfo=20, capex=10, net_income=1, operating_income=4
                ).items()
            },
        )
        result = pipeline.financial_metrics(f)
        self.assertEqual(result["cashAfterInvestment"], -5)
        self.assertAlmostEqual(result["cashMarginChange"], -0.15)
        self.assertIsNone(result["cashConversion"])

    def test_ledger_detects_tampering_and_register_is_idempotent(self):
        with tempfile.TemporaryDirectory(dir=data.work_temp()) as folder:
            p = Path(folder) / "events.jsonl"
            event = dict(eventId="one", type="registration", expected=None)
            first = ledger.append(p, event)
            self.assertEqual(first, ledger.append(p, event))
            self.assertEqual(len(ledger.read(p)), 1)
            with self.assertRaises(ValueError):
                ledger.append(p, {**event, "expected": True})
            records = ledger.read(p)
            records[0]["expected"] = True
            with self.assertRaises(ValueError):
                ledger.verify_records(records)

    def test_future_observation_and_prediction_are_separate(self):
        r = dict(
            recordedAt="2026-09-30T10:00:00+00:00",
            periodEnd="2026-06-30",
            expected=None,
            investmentScope="유형자산 취득",
        )
        c = dict(
            financials=dict(end="2026-09-30", filedAt="2026-11-14"),
            metrics=dict(cashMarginChange=-0.1),
            investmentScope="유형자산 취득",
        )
        o = ledger.evaluate(r, c)
        self.assertEqual(o["status"], "not_met")
        self.assertIsNone(o["predictionCorrect"])
        c["financials"]["filedAt"] = "2026-09-30"
        self.assertEqual(ledger.evaluate(r, c)["status"], "pending")
        c["investmentScope"] = "유형·무형자산 취득"
        self.assertEqual(ledger.evaluate(r, c)["status"], "unresolved")

    def test_registration_uses_the_filing_markets_calendar_date(self):
        r = dict(
            recordedAt="2026-09-30T16:00:00+00:00",
            periodEnd="2026-06-30",
            investmentScope="유형자산 취득",
        )
        c = dict(
            market="KR",
            financials=dict(end="2026-09-30", filedAt="2026-10-01"),
            metrics=dict(cashMarginChange=0.1),
            investmentScope="유형자산 취득",
        )
        self.assertEqual(ledger.evaluate(r, c)["status"], "pending")
        c["financials"]["filedAt"] = "2026-10-02"
        self.assertEqual(ledger.evaluate(r, c)["status"], "met")

    def test_experiment_oracle_is_upper_bound_and_windows_do_not_overlap(self):
        snapshot = pipeline.load_latest()
        for e in snapshot["experiments"]:
            for i, w in enumerate(e["windows"]):
                self.assertLess(w["signalDate"], w["entryDate"])
                self.assertLess(w["entryDate"], w["endDate"])
                self.assertLessEqual(w["endDate"], snapshot["asOf"])
                self.assertGreaterEqual(
                    w["returns"]["oracle"] + 1e-12, max(w["returns"].values())
                )
                if i:
                    self.assertEqual(e["windows"][i - 1]["endDate"], w["entryDate"])

    def test_future_perturbation_does_not_change_past_signal(self):
        companies = copy.deepcopy(pipeline.load_latest()["companies"])
        before = research.run_experiment(companies, "US")
        end = before["windows"][0]["signalDate"]
        for c in companies:
            if c["id"] == "MU":
                for p in c["prices"]:
                    if p["date"] > end:
                        p["adjustedClose"] *= 3
        after = research.run_experiment(companies, "US")
        for key in ["momentum63", "momentum_risk"]:
            self.assertEqual(
                before["windows"][0]["picks"][key], after["windows"][0]["picks"][key]
            )

    def test_all_snapshot_facts_available_and_reconcilable(self):
        s = pipeline.load_latest()
        self.assertEqual(len(s["companies"]), 8)
        self.assertEqual(s["failures"], [])
        for c in s["companies"]:
            f = c["financials"]
            self.assertLessEqual(f["filedAt"], s["asOf"])
            for value in f["current"].values():
                if value:
                    self.assertEqual(
                        (value["start"], value["end"]), (f["start"], f["end"])
                    )
                    self.assertLessEqual(value["filedAt"], s["asOf"])
            self.assertAlmostEqual(
                c["metrics"]["cashAfterInvestment"],
                f["current"]["cfo"]["value"] - f["current"]["capex"]["value"],
            )
            self.assertTrue(all(p["date"] <= s["asOf"] for p in c["prices"]))

    def test_failed_refresh_preserves_latest_complete_snapshot(self):
        with tempfile.TemporaryDirectory(dir=data.work_temp()) as folder:
            root = Path(folder)
            (root / "data/runs").mkdir(parents=True)
            (root / "data/latest.json").write_text("last complete")
            with patch.object(pipeline, "ROOT", root), patch.object(
                pipeline, "UNIVERSE", [dict(id="TEST", market="US")]
            ), patch.object(
                pipeline, "sec_facts", side_effect=ValueError("source unavailable")
            ):
                result = pipeline.run("2026-09-29")
            self.assertEqual((root / "data/latest.json").read_text(), "last complete")
            self.assertEqual(len(result["failures"]), 1)
            self.assertEqual(len(list((root / "data/runs").glob("*/snapshot.json"))), 1)

    def test_render_failure_does_not_publish_a_new_latest_snapshot(self):
        with tempfile.TemporaryDirectory(dir=data.work_temp()) as folder:
            root = Path(folder)
            (root / "data/runs").mkdir(parents=True)
            (root / "data/latest.json").write_text("last complete")
            with patch.object(pipeline, "ROOT", root), patch.object(
                pipeline, "UNIVERSE", []
            ), patch.object(
                pipeline, "export", side_effect=RuntimeError("render failed")
            ):
                with self.assertRaisesRegex(RuntimeError, "render failed"):
                    pipeline.run("2026-09-29")
            self.assertEqual((root / "data/latest.json").read_text(), "last complete")


if __name__ == "__main__":
    unittest.main()
