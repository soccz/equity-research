"""scripts/ratings_ops.py: what an unattended run does when (no network, fake CLI)."""

from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ratings import common, registry, universe

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "ratings_ops", ROOT / "scripts/ratings_ops.py"
)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


def weekdays(first="2026-09-01", last="2026-12-31") -> list:
    day, end, out = date.fromisoformat(first), date.fromisoformat(last), []
    while day <= end:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


SESSIONS = {"US": weekdays(), "KR": weekdays()}


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)


class FakeCli:
    """Records scripts/ratings.py calls; ``universe`` saves the part it was asked for,
    other commands answer from ``answers`` (command, or 'score-dry')."""

    def __init__(self, **answers):
        self.calls, self.answers = [], answers

    def __call__(self, *args):
        args = [str(a) for a in args]
        self.calls.append(args)
        command = args[0]
        if command == "universe":
            as_of, market = args[args.index("--as-of") + 1], args[-1]
            market = args[args.index("--markets") + 1]
            path = universe.part_path(market, as_of, gate="--gate" in args)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}")
            info = dict(status="ok", holdingsAsOf=as_of if market == "US" else None)
            return 0, dict(markets={market: info}), ""
        key = "score-dry" if command == "score" and "--dry-run" in args else command
        answer = self.answers.get(key)
        if callable(answer):
            return answer(args)
        if answer is None:
            return 2, None, f"no answer for {key}"
        return 0, answer, ""

    def commands(self) -> list:
        return [
            " ".join(a for a in call if not a.startswith("20") and a != "--markets")
            for call in self.calls
        ]


def collected(errors=0, halted=0, eligible=200, markets=("US", "KR")) -> dict:
    stats = dict(
        eligible=eligible,
        notCollected=0,
        stale=0,
        errors=errors,
        noCloseOnAsOf=halted,
        failures=errors + halted,
        fetchErrors=0,
    )
    return dict(checks=[], collection={m: dict(stats) for m in markets})


OK_COLLECT = dict(
    markets={"US": dict(state={"ok": 400}), "KR": dict(state={"ok": 170})}
)
PASS = dict(verdict="pass", market="US")


class OpsCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        data = Path(folder.name) / "data/ratings"
        self.data = data
        for target, name, value in (
            (universe, "UNIVERSE_DIR", data / "universe"),
            (registry, "LEDGER", data / "ledger.jsonl"),
            (registry, "REGISTRATIONS", data / "v1"),
            (common, "RATINGS", data),
            (common, "SOURCES", data / "sources"),
            (ops, "ROOT", Path(folder.name)),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.gates = {"US": None, "KR": None}
        self.registered = []
        for name, value in (
            ("gate", lambda market: self.gates[market]),
            ("registrations", lambda strict=True: list(self.registered)),
        ):
            patcher = mock.patch.object(registry, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_ops(self, now, cli, holdings=None, evaluate="no", **kwargs):
        runner = ops.Ops(
            runner=cli, now=at(now), sessions=SESSIONS, holdings=holdings, **kwargs
        )
        with mock.patch("builtins.print"):
            runner.operate(evaluate)
        return runner

    def save_part(self, market, as_of, gate=False):
        path = universe.part_path(market, as_of, gate=gate)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")


class CalendarRules(unittest.TestCase):
    def test_month_target_and_window(self):
        sessions = weekdays()
        target = ops.month_target(sessions, "2026-11-02")
        self.assertEqual(
            target, dict(month="2026-10", asOf="2026-10-30", elapsed=0, open=True)
        )
        # Sessions strictly between T and today count (the registry's D3 count).
        self.assertEqual(ops.month_target(sessions, "2026-11-06")["elapsed"], 4)
        self.assertTrue(ops.month_target(sessions, "2026-11-06")["open"])
        closed = ops.month_target(sessions, "2026-11-09")
        self.assertEqual((closed["elapsed"], closed["open"]), (5, False))
        self.assertIsNone(ops.month_target(sessions, "2026-09-15"))  # no August data
        self.assertEqual(ops.FIRST_MONTH, "2026-10")


class GateRuns(OpsCase):
    def test_nothing_before_the_check_asof(self):
        cli = FakeCli()
        run = self.run_ops("2026-10-07T12:00:00+00:00", cli, holdings="2026-10-06")
        self.assertEqual(cli.calls, [])
        self.assertEqual(run.problems, [])
        self.assertEqual(len(run.waiting), 2)  # KR closes not out, US not posted

    def test_gate_parts_collection_and_record(self):
        coverage = dict(
            markets={
                m: dict(verdict="pass", rate=0.97, gate=dict(recorded=True))
                for m in ("US", "KR")
            }
        )
        cli = FakeCli(collect=OK_COLLECT, coverage=coverage)
        # 2026-10-20 15:00 UTC: 11:00 ET (SSGA posted 10-19), 00:00 KST 10-21.
        run = self.run_ops("2026-10-20T15:00:00+00:00", cli, holdings="2026-10-19")
        self.assertEqual(
            cli.commands(),
            [
                "universe --as-of US --gate",
                "universe --as-of KR --gate",
                "collect --as-of --gate US KR",
                "coverage --as-of --gate US KR",
            ],
        )
        self.assertEqual(run.problems, [])
        self.assertIn("coverage gate recorded: US pass 97.0%, KR pass 97.0%", run.done)

    def test_kr_part_waits_for_closes_and_us_for_ssga(self):
        cli = FakeCli()
        # 2026-10-19 09:00 UTC = 18:00 KST: KR closes not out until 18:30.
        run = self.run_ops("2026-10-19T09:00:00+00:00", cli, holdings="2026-10-16")
        self.assertEqual(cli.calls, [])
        self.assertEqual(run.problems, [])
        # 10-20 08:00 ET: SSGA still shows 10-16; the KR part is built meanwhile.
        cli = FakeCli()
        run = self.run_ops("2026-10-20T12:00:00+00:00", cli, holdings="2026-10-16")
        self.assertEqual(cli.commands(), ["universe --as-of KR --gate"])
        self.assertTrue(any("SSGA still shows" in w for w in run.waiting))
        self.assertEqual(run.problems, [])

    def test_missed_ssga_holdings_and_closed_window_are_problems(self):
        self.save_part("KR", "2026-10-19", gate=True)
        cli = FakeCli()
        run = self.run_ops("2026-10-21T15:00:00+00:00", cli, holdings="2026-10-20")
        self.assertEqual(cli.calls, [])
        self.assertTrue(any("can no longer be captured" in p for p in run.problems))
        cli = FakeCli()
        run = self.run_ops("2026-10-27T15:00:00+00:00", cli, holdings="2026-10-26")
        self.assertTrue(any("can never be recorded" in p for p in run.problems))

    def test_incomplete_gate_on_the_check_date_is_a_problem(self):
        self.save_part("KR", "2026-10-19", gate=True)
        self.save_part("US", "2026-10-19", gate=True)
        coverage = dict(
            markets={
                "US": dict(verdict="pass", rate=0.97, gate=dict(recorded=True)),
                "KR": dict(
                    verdict="incomplete",
                    rate=0.5,
                    gate=dict(recorded=False, reason="incomplete collection"),
                ),
            }
        )
        cli = FakeCli(collect=OK_COLLECT, coverage=coverage)
        run = self.run_ops("2026-10-20T15:00:00+00:00", cli, holdings="2026-10-19")
        self.assertIn("coverage gate recorded: US pass 97.0%", run.done)
        self.assertTrue(any("KR gate not recorded" in p for p in run.problems))


class MonthRuns(OpsCase):
    NOW = "2026-11-02T15:00:00+00:00"  # Mon 10:00 ET, 00:00 KST Tue: 0 sessions after T

    def setUp(self):
        super().setUp()
        self.gates = {"US": dict(PASS), "KR": dict(PASS, market="KR")}

    def test_registration_with_both_parts(self):
        registered = dict(labels={"US": {"preferred": 134}}, asOf={})
        cli = FakeCli(
            collect=OK_COLLECT, **{"score-dry": collected(), "score": registered}
        )
        run = self.run_ops(self.NOW, cli, holdings="2026-10-30")
        self.assertEqual(
            cli.commands(),
            [
                "universe --as-of US",
                "universe --as-of KR",
                "collect --month US KR",
                "score --as-of-us --as-of-kr --dry-run",
                "score --as-of-us --as-of-kr",
            ],
        )
        self.assertEqual(
            cli.calls[-1][1:5], ["--as-of-us", "2026-10-30", "--as-of-kr", "2026-10-30"]
        )
        self.assertEqual(run.problems, [])
        self.assertTrue(any(d.startswith("registered 2026-10") for d in run.done))

    def test_months_before_the_first_are_neither_due_nor_missed(self):
        cli = FakeCli()
        run = self.run_ops("2026-10-21T15:00:00+00:00", cli, holdings="2026-10-20")
        self.assertEqual((cli.calls, run.problems), ([], []))

    def test_already_registered_month_is_left_alone(self):
        self.registered = [dict(month="2026-10")]
        cli = FakeCli()
        run = self.run_ops(self.NOW, cli, holdings="2026-10-30")
        self.assertEqual((cli.calls, run.problems), ([], []))

    def test_collection_errors_wait_then_register_as_failures(self):
        self.save_part("US", "2026-10-30")
        self.save_part("KR", "2026-10-30")
        answers = {"collect": OK_COLLECT, "score-dry": collected(errors=3)}
        cli = FakeCli(**answers)
        run = self.run_ops(self.NOW, cli)
        self.assertEqual(cli.commands()[-1], "score --as-of-us --as-of-kr --dry-run")
        self.assertTrue(any("collected again" in w for w in run.waiting))
        self.assertEqual(run.problems, [])
        # Two sessions after T (Wed 11-04): registered with the failures recorded.
        cli = FakeCli(**answers, score=dict(labels={}, asOf={}))
        run = self.run_ops("2026-11-04T15:00:00+00:00", cli)
        self.assertEqual(cli.calls[-1][-1], "--allow-errors")
        self.assertEqual(run.problems, [])

    def test_halts_only_register_at_once_and_a_source_failure_never(self):
        self.save_part("US", "2026-10-30")
        self.save_part("KR", "2026-10-30")
        cli = FakeCli(
            collect=OK_COLLECT,
            **{"score-dry": collected(halted=2), "score": dict(labels={}, asOf={})},
        )
        run = self.run_ops(self.NOW, cli)
        self.assertEqual(cli.calls[-1][-1], "--allow-errors")
        self.assertEqual(run.problems, [])
        heavy = collected(errors=40, eligible=170)
        cli = FakeCli(collect=OK_COLLECT, **{"score-dry": heavy})
        run = self.run_ops("2026-11-04T15:00:00+00:00", cli)
        self.assertNotIn("score --as-of-us --as-of-kr", cli.commands())
        self.assertTrue(any("source failure" in p for p in run.problems))

    def test_refusals_and_closed_windows_are_problems(self):
        self.save_part("US", "2026-10-30")
        self.save_part("KR", "2026-10-30")
        dry = dict(collected(), checks=["US: universe captured ..."])
        cli = FakeCli(collect=OK_COLLECT, **{"score-dry": dry})
        run = self.run_ops(self.NOW, cli)
        self.assertTrue(any("would refuse" in p for p in run.problems))
        cli = FakeCli()
        run = self.run_ops("2026-11-09T15:00:00+00:00", cli)  # 5 sessions after T
        self.assertEqual(cli.calls, [])
        self.assertTrue(any("window closed" in p for p in run.problems))

    def test_failed_gates(self):
        self.gates["KR"] = dict(verdict="fail", market="KR")
        cli = FakeCli(
            collect=OK_COLLECT,
            **{
                "score-dry": collected(markets=("US",)),
                "score": dict(labels={}, asOf={}),
            },
        )
        run = self.run_ops(self.NOW, cli, holdings="2026-10-30")
        self.assertEqual(
            cli.commands(),
            [
                "universe --as-of US",
                "collect --month US",
                "score --as-of-us --dry-run",
                "score --as-of-us",
            ],
        )
        self.assertEqual(run.problems, [])
        self.gates["US"] = dict(verdict="fail", market="US")
        cli = FakeCli()
        run = self.run_ops(self.NOW, cli, holdings="2026-10-30")
        self.assertEqual((cli.calls, run.problems), ([], []))
        self.assertTrue(any("not published" in d for d in run.done))


class EvaluationAndCache(OpsCase):
    def test_weekly_evaluation_through_the_earlier_local_date(self):
        self.gates = {"US": dict(PASS), "KR": dict(PASS)}
        self.registered = [dict(month="2026-10")]
        cli = FakeCli(evaluate=dict(official=True))
        # Saturday 02:53 UTC: Friday 22:53 ET, Saturday 11:53 KST.
        run = self.run_ops("2026-11-14T02:53:00+00:00", cli, evaluate="auto")
        self.assertEqual(cli.calls, [["evaluate", "--through", "2026-11-13"]])
        self.assertEqual(run.problems, [])
        cli = FakeCli(evaluate=dict(official=False, officialBlockers=["offline"]))
        run = self.run_ops("2026-11-14T02:53:00+00:00", cli, evaluate="auto")
        self.assertTrue(any("offline" in p for p in run.problems))
        cli = FakeCli()
        self.run_ops("2026-11-13T02:53:00+00:00", cli, evaluate="auto")  # Friday
        self.assertEqual(cli.calls, [])

    def test_prune_keeps_what_a_later_run_reads(self):
        sources, series = self.data / "sources", self.data / "series"
        sources.mkdir(parents=True)
        series.mkdir(parents=True)
        kept = sources / "yahoo-AAPL-2026-11-13-0123456789abcdef.json"
        for name in (
            kept.name,
            "yahoo-AAPL-2026-11-13.manifest.json",
            "sec-facts-0000320193-aaaaaaaaaaaaaaaa.json",
            "ken-french-siccodes12-d801141acf039f2e.zip",
            "ken-french-siccodes12-pinned.manifest.json",
        ):
            (sources / name).write_text("x")
        original = dict(source=dict(file=f"data/ratings/sources/{kept.name}"))
        (series / "yahoo-AAPL.json").write_text(
            json.dumps(dict(symbol="AAPL", originals=[original]))
        )
        for stem in ("2026-10-19-gate", "2026-10-30", "2026-11-30"):
            (self.data / "work" / stem).mkdir(parents=True)
        self.gates = {"US": dict(PASS), "KR": dict(PASS)}
        self.registered = [dict(month="2026-10")]
        with mock.patch("builtins.print"):
            ops.Ops(sessions=SESSIONS).prune()
        self.assertEqual(
            sorted(p.name for p in sources.iterdir()),
            [
                "ken-french-siccodes12-d801141acf039f2e.zip",
                "ken-french-siccodes12-pinned.manifest.json",
                kept.name,
            ],
        )
        self.assertEqual(
            [p.name for p in (self.data / "work").iterdir()], ["2026-11-30"]
        )


if __name__ == "__main__":
    unittest.main()
