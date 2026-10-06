"""scripts/ratings_ops.py: what an unattended run does when (no network, fake CLI)."""

from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from ratings import common, registry, universe

import test_ratings_cli as cli_tests

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "ratings_ops", ROOT / "scripts/ratings_ops.py"
)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)

G = ops.CHECK["asOf"]  # 2026-10-19, a Monday


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


def option(args: list, name: str):
    return args[args.index(name) + 1] if name in args else None


class FakeCli:
    """Records scripts/ratings.py calls. ``universe`` saves the part it was asked for
    (US holdings as of ``holdings`` or T), ``universe-merge`` names the merged file;
    other commands answer from ``answers`` keyed by command, 'score-dry' or
    'coverage-report' (coverage --offline); a callable answer gets the args."""

    def __init__(self, holdings=None, **answers):
        self.calls, self.answers, self.holdings = [], answers, holdings

    def __call__(self, *args):
        args = [str(a) for a in args]
        self.calls.append(args)
        command = args[0]
        if command == "universe":
            as_of, market = option(args, "--as-of"), option(args, "--markets")
            path = universe.part_path(market, as_of, gate="--gate" in args)
            path.parent.mkdir(parents=True, exist_ok=True)
            info = dict(status="ok")
            if market == "US":
                info["holdingsAsOf"] = self.holdings or as_of
            path.write_text(json.dumps(dict(markets={market: info})))
            return 0, dict(markets={market: info}), ""
        if command == "universe-merge":
            days = [option(args, f"--as-of-{m}") for m in ("us", "kr")]
            stem = max(d for d in days if d) + ("-gate" if "--gate" in args else "")
            return 0, dict(file=f"data/ratings/universe/{stem}.json", checks=[]), ""
        key = command
        if command == "score" and "--dry-run" in args:
            key = "score-dry"
        if command == "coverage" and "--offline" in args:
            key = "coverage-report"
        answer = self.answers.get(key)
        if callable(answer):
            return answer(args)
        if answer is None:
            return 2, None, f"no answer for {key}"
        return 0, answer, ""

    def commands(self) -> list:
        """Each call without its dates and file names, for compact assertions."""
        out = []
        for call in self.calls:
            words, skip = [], False
            for word in call:
                if skip:
                    skip = False
                    continue
                if word in ("--universe", "--through"):
                    skip = True
                    continue
                if word.startswith("20") or word == "--markets":
                    continue
                words.append(word)
            out.append(" ".join(words))
        return out


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


def coverage(recorded=True, **entries) -> dict:
    """A coverage answer; ``entries`` override each market's entry."""
    out = {}
    for market in ("US", "KR"):
        entry = dict(
            verdict="pass",
            rate=0.97,
            nonFinancial=200,
            collectionErrors=0,
            noCloseOnAsOf=0,
            gate=dict(recorded=recorded),
        )
        entry.update(entries.get(market) or {})
        out[market] = entry
    return dict(markets=out)


OK_COLLECT = dict(
    markets={"US": dict(state={"ok": 400}), "KR": dict(state={"ok": 170})}
)
PASS = dict(verdict="pass", market="US")


class OpsCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        data = self.root / "data/ratings"
        self.data = data
        for target, name, value in (
            (universe, "UNIVERSE_DIR", data / "universe"),
            (registry, "LEDGER", data / "ledger.jsonl"),
            (registry, "REGISTRATIONS", data / "v1"),
            (common, "RATINGS", data),
            (common, "SOURCES", data / "sources"),
            (ops, "ROOT", self.root),
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

    def run_ops(self, now, cli, holdings=None, evaluate=False, **kwargs):
        runner = ops.Ops(
            runner=cli, now=at(now), sessions=SESSIONS, holdings=holdings, **kwargs
        )
        with mock.patch("builtins.print"):
            runner.operate(evaluate)
        return runner

    def save_part(self, market, as_of, gate=False, holdings=None):
        path = universe.part_path(market, as_of, gate=gate)
        path.parent.mkdir(parents=True, exist_ok=True)
        info = dict(holdingsAsOf=holdings or as_of) if market == "US" else {}
        path.write_text(json.dumps(dict(markets={market: info})))


class CalendarRules(unittest.TestCase):
    def test_month_target_and_window(self):
        sessions = weekdays()
        target = ops.month_target(sessions, "2026-11-02")
        self.assertEqual(
            target,
            dict(month="2026-10", asOf="2026-10-30", elapsed=0, open=True, closes=None),
        )
        # Sessions strictly between T and today count (the registry's D3 count).
        self.assertEqual(ops.month_target(sessions, "2026-11-06")["elapsed"], 4)
        self.assertTrue(ops.month_target(sessions, "2026-11-06")["open"])
        closed = ops.month_target(sessions, "2026-11-09")
        self.assertEqual(
            (closed["elapsed"], closed["open"], closed["closes"]),
            (5, False, "2026-11-06"),
        )
        self.assertIsNone(ops.month_target(sessions, "2026-09-15"))  # no August data
        self.assertEqual(ops.FIRST_MONTH, "2026-10")


class GateRuns(OpsCase):
    def test_nothing_before_the_check_asof(self):
        cli = FakeCli()
        run = self.run_ops("2026-10-07T12:00:00+00:00", cli, holdings="2026-10-06")
        self.assertEqual(cli.calls, [])
        self.assertEqual(run.problems, [])
        self.assertEqual(len(run.waiting), 2)  # KR closes not out, US not posted

    def test_kr_is_collected_on_t_evening_and_both_recorded_later(self):
        # 2026-10-19 10:23 UTC = 19:23 KST: the KR part, merged and collected alone.
        cli = FakeCli(collect=OK_COLLECT)
        run = self.run_ops("2026-10-19T10:23:00+00:00", cli, holdings="2026-10-16")
        self.assertEqual(
            cli.commands(),
            [
                "universe --as-of KR --gate",
                "universe-merge --as-of-kr --only --gate",
                "collect --gate KR",
            ],
        )
        self.assertEqual(run.problems, [])
        # 2026-10-20 14:23 UTC: SSGA posted 10-19; US part, merge of both, collect,
        # a report-only coverage, then the recording one.
        cli = FakeCli(
            collect=OK_COLLECT,
            **{"coverage-report": coverage(recorded=False), "coverage": coverage()},
        )
        run = self.run_ops("2026-10-20T14:23:00+00:00", cli, holdings=G)
        self.assertEqual(
            cli.commands(),
            [
                "universe --as-of US --gate",
                "universe-merge --as-of-us --as-of-kr --only --gate",
                "collect --gate US KR",
                "coverage --as-of --gate --offline US KR",
                "coverage --as-of --gate US KR",
            ],
        )
        merged = [c for c in cli.calls if c[0] == "universe-merge"][0]
        self.assertEqual(option(merged, "--as-of-us"), G)
        self.assertEqual(option(merged, "--as-of-kr"), G)
        for call in cli.calls[2:]:  # every later step names the merged file
            self.assertEqual(
                option(call, "--universe"), f"data/ratings/universe/{G}-gate.json"
            )
        self.assertEqual(run.problems, [])
        self.assertIn("coverage gate recorded: US pass 97.0%, KR pass 97.0%", run.done)

    def test_waits_for_closes_and_ssga_and_alerts_when_stale(self):
        cli = FakeCli()
        # 2026-10-19 09:00 UTC = 18:00 KST: KR closes not out until 18:30.
        run = self.run_ops("2026-10-19T09:00:00+00:00", cli, holdings="2026-10-16")
        self.assertEqual((cli.calls, run.problems), ([], []))
        self.save_part("KR", G, gate=True)
        cli = FakeCli(collect=OK_COLLECT)
        run = self.run_ops("2026-10-20T12:00:00+00:00", cli, holdings="2026-10-16")
        self.assertTrue(any("SSGA still shows" in w for w in run.waiting))
        self.assertEqual(run.problems, [])
        # Two sessions after T without T's holdings: SSGA is stale, a problem.
        run = self.run_ops(
            "2026-10-22T12:00:00+00:00",
            FakeCli(collect=OK_COLLECT),
            holdings="2026-10-16",
        )
        self.assertTrue(any("SSGA still shows" in p for p in run.problems))

    def test_missed_holdings_and_closed_window(self):
        self.save_part("KR", G, gate=True)
        cli = FakeCli(collect=OK_COLLECT)
        run = self.run_ops("2026-10-21T14:00:00+00:00", cli, holdings="2026-10-20")
        self.assertTrue(any("can no longer be captured" in p for p in run.problems))
        self.assertNotIn("coverage", [c[0] for c in cli.calls])
        # The window closed on 10-26 (5th session after 10-19): a problem for three
        # days, then a note; the KR gate is then recorded alone.
        for now, lasting in (("2026-10-28", True), ("2026-11-03", False)):
            cli = FakeCli(
                collect=OK_COLLECT,
                **{"coverage-report": coverage(False), "coverage": coverage()},
            )
            run = self.run_ops(f"{now}T05:00:00+00:00", cli)
            text = "never captured inside its window"
            self.assertEqual(any(text in p for p in run.problems), lasting)
            self.assertEqual(any(text in d for d in run.done), not lasting)
            self.assertIn("coverage --as-of --gate KR", cli.commands())

    def test_a_source_failure_or_an_incomplete_collection_is_never_recorded(self):
        self.save_part("KR", G, gate=True)
        self.save_part("US", G, gate=True)
        cases = {
            "KR halts (ranked at T's close)": dict(KR=dict(noCloseOnAsOf=3)),
            "incomplete": dict(KR=dict(verdict="incomplete", collectionErrors=4)),
        }
        for label, entries in cases.items():
            with self.subTest(label):
                cli = FakeCli(
                    collect=OK_COLLECT,
                    **{
                        "coverage-report": coverage(False, **entries),
                        "coverage": coverage(),
                    },
                )
                run = self.run_ops("2026-10-20T14:23:00+00:00", cli)
                recording = [
                    c for c in cli.calls if c[0] == "coverage" and "--offline" not in c
                ]
                self.assertEqual(len(recording), 1)
                self.assertEqual(recording[0][-1], "US")  # US alone is recorded
                self.assertTrue(any(p.startswith("KR gate") for p in run.problems))
        heavy = dict(US=dict(noCloseOnAsOf=30))  # 15% of the US without T's close
        cli = FakeCli(
            collect=OK_COLLECT, **{"coverage-report": coverage(False, **heavy)}
        )
        run = self.run_ops("2026-10-20T14:23:00+00:00", cli)
        self.assertTrue(any("US gate" in p and "failed" in p for p in run.problems))

    def test_a_us_part_built_from_other_holdings_is_discarded(self):
        self.save_part("KR", G, gate=True)
        cli = FakeCli(holdings="2026-10-20", collect=OK_COLLECT)
        run = self.run_ops("2026-10-20T14:23:00+00:00", cli, holdings=G)
        self.assertFalse(universe.part_path("US", G, gate=True).exists())
        self.assertTrue(any("discarded, never published" in p for p in run.problems))
        self.assertNotIn("coverage", [c[0] for c in cli.calls])

    def test_a_saved_part_whose_build_did_not_merge_goes_on(self):
        """Critical (review 2026-10-07): a part saved while the month's automatic merge
        failed (exit 2) is published and merged explicitly."""
        self.save_part("KR", G, gate=True)
        cli = FakeCli(
            collect=OK_COLLECT,
            **{"coverage-report": coverage(False), "coverage": coverage()},
        )
        plain = cli.__call__

        def universe_exit_2(*args):
            code, summary, error = plain(*args)
            if args[0] == "universe":
                return 2, None, "US part saved (...), month not merged: rulesHash"
            return code, summary, error

        run = self.run_ops("2026-10-20T14:23:00+00:00", universe_exit_2, holdings=G)
        self.assertTrue(any("its build did not merge it" in d for d in run.done))
        self.assertIn("coverage gate recorded: US pass 97.0%, KR pass 97.0%", run.done)


class RealMerges(OpsCase):
    """The merge the driver asks for, done by the real universe.save/universe.merge
    with a rehearsal part of the same month already saved (review 2026-10-07)."""

    def test_a_rehearsal_part_of_the_month_never_blocks_the_gate(self):
        captured = dict(US="2026-10-20T14:30:00+00:00", KR="2026-10-19T10:30:00+00:00")
        members = cli_tests.fake_universe()["members"]
        # The rehearsal parts committed on 2026-10-06 (US of 10-05, KR of 10-06), built
        # under an older RULES text.
        for market, day in (("US", "2026-10-05"), ("KR", "2026-10-06")):
            stray = cli_tests.fake_part(
                market, [m for m in members if m["market"] == market], day
            )
            stray["rulesHash"] = "0" * 64
            path = universe.part_path(market, day, gate=True)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(stray))

        def real(*args):
            args = [str(a) for a in args]
            if args[0] == "universe":
                market, as_of = option(args, "--markets"), option(args, "--as-of")
                part = cli_tests.fake_part(
                    market,
                    [m for m in members if m["market"] == market],
                    as_of,
                    captured[market],
                )
                try:
                    universe.save(part, gate=True)
                except universe.MonthNotMerged as exc:
                    return 2, None, f"part saved, month not merged: {exc.error}"
                return 0, dict(markets={market: part["markets"][market]}), ""
            if args[0] == "universe-merge":
                days = {m: option(args, f"--as-of-{m.lower()}") for m in ("US", "KR")}
                merged = universe.merge(
                    {m: d for m, d in days.items() if d},
                    gate=True,
                    only="--only" in args,
                )
                return 0, dict(file=str(merged.relative_to(self.root)), checks=[]), ""
            return answers(*args)

        answers = FakeCli(
            collect=OK_COLLECT,
            **{"coverage-report": coverage(False), "coverage": coverage()},
        )
        # T's evening: the KR part (its build's own merge meets the rehearsal US part
        # and fails) is merged alone and collected before the KST day rolls over.
        first = self.run_ops("2026-10-19T10:30:00+00:00", real, holdings="2026-10-16")
        self.assertEqual(first.problems, [])
        self.assertTrue(any("its build did not merge it" in d for d in first.done))
        alone = json.loads((self.data / f"universe/{G}-gate.json").read_text())
        self.assertEqual(alone["asOfByMarket"], {"KR": G})
        self.assertEqual([c[0] for c in answers.calls], ["collect"])
        run = self.run_ops("2026-10-20T14:30:00+00:00", real, holdings=G)
        merged = json.loads((self.data / f"universe/{G}-gate.json").read_text())
        self.assertEqual(merged["asOfByMarket"], {"US": G, "KR": G})
        self.assertEqual(run.problems, [])
        self.assertIn("coverage gate recorded: US pass 97.0%, KR pass 97.0%", run.done)


class MonthRuns(OpsCase):
    NOW = "2026-11-02T13:00:00+00:00"  # Mon 08:00 ET, 22:00 KST: 0 sessions after T

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
                "universe-merge --as-of-us --as-of-kr --only",
                "collect US KR",
                "score --as-of-us --as-of-kr --dry-run",
                "score --as-of-us --as-of-kr",
            ],
        )
        self.assertEqual(
            cli.calls[-1][1:5], ["--as-of-us", "2026-10-30", "--as-of-kr", "2026-10-30"]
        )
        self.assertEqual(
            option(cli.calls[-1], "--universe"), "data/ratings/universe/2026-10-30.json"
        )
        self.assertEqual(run.problems, [])
        self.assertTrue(any(d.startswith("registered 2026-10") for d in run.done))

    def test_kr_is_collected_before_the_us_part(self):
        cli = FakeCli(collect=OK_COLLECT)
        run = self.run_ops(self.NOW, cli, holdings="2026-10-29")
        self.assertEqual(
            cli.commands(),
            ["universe --as-of KR", "universe-merge --as-of-kr --only", "collect KR"],
        )
        self.assertEqual(run.problems, [])

    def test_months_before_the_first_are_neither_due_nor_missed(self):
        cli = FakeCli()
        run = self.run_ops("2026-10-21T05:00:00+00:00", cli, holdings="2026-10-20")
        self.assertEqual((cli.calls, run.problems), ([], []))

    def test_already_registered_month_is_left_alone(self):
        self.registered = [dict(month="2026-10")]
        cli = FakeCli()
        run = self.run_ops(self.NOW, cli, holdings="2026-10-30")
        self.assertEqual((cli.calls, run.problems), ([], []))

    def test_errors_wait_per_market_then_register_as_failures(self):
        self.save_part("US", "2026-10-30")
        self.save_part("KR", "2026-10-30")
        # KR halts (ranked at T's close) are retried like errors: 1 KR session after T.
        for dry in (
            collected(errors=3),
            collected(halted=2, markets=("KR",))
            | dict(
                collection=collected().get("collection")
                | {"KR": collected(halted=2)["collection"]["KR"]}
            ),
        ):
            cli = FakeCli(collect=OK_COLLECT, **{"score-dry": dry})
            run = self.run_ops("2026-11-02T22:00:00+00:00", cli)  # KST Tue 07:00
            self.assertEqual(
                cli.commands()[-1], "score --as-of-us --as-of-kr --dry-run"
            )
            self.assertTrue(any("collected again" in w for w in run.waiting))
            self.assertEqual(run.problems, [])
        # Two sessions after T in each market: registered with the failures recorded.
        cli = FakeCli(
            collect=OK_COLLECT,
            **{"score-dry": collected(errors=3), "score": dict(labels={}, asOf={})},
        )
        run = self.run_ops("2026-11-04T13:00:00+00:00", cli)
        self.assertEqual(cli.calls[-1][-1], "--allow-errors")
        self.assertEqual(run.problems, [])

    def test_us_halts_register_at_once_and_a_source_failure_never(self):
        self.save_part("US", "2026-10-30")
        self.save_part("KR", "2026-10-30")
        dry = collected()
        dry["collection"]["US"].update(noCloseOnAsOf=2, failures=2)
        cli = FakeCli(
            collect=OK_COLLECT, **{"score-dry": dry, "score": dict(labels={}, asOf={})}
        )
        run = self.run_ops(self.NOW, cli)
        self.assertEqual(cli.calls[-1][-1], "--allow-errors")
        self.assertEqual(run.problems, [])
        heavy = collected(errors=40, eligible=170)
        cli = FakeCli(collect=OK_COLLECT, **{"score-dry": heavy})
        run = self.run_ops("2026-11-04T13:00:00+00:00", cli)
        self.assertNotIn("score --as-of-us --as-of-kr", cli.commands())
        self.assertTrue(any("source failure" in p for p in run.problems))

    def test_refusals_and_closed_windows(self):
        self.save_part("US", "2026-10-30")
        self.save_part("KR", "2026-10-30")
        dry = dict(collected(), checks=["US: universe captured ..."])
        cli = FakeCli(collect=OK_COLLECT, **{"score-dry": dry})
        run = self.run_ops(self.NOW, cli)
        self.assertTrue(any("would refuse" in p for p in run.problems))
        cli = FakeCli()
        run = self.run_ops("2026-11-09T05:00:00+00:00", cli)  # 5 sessions after T
        self.assertEqual(cli.calls, [])
        self.assertTrue(any("window closed" in p for p in run.problems))
        run = self.run_ops("2026-11-12T05:00:00+00:00", FakeCli())  # 6 days later
        self.assertEqual(run.problems, [])
        self.assertTrue(any("window closed" in d for d in run.done))

    def test_a_pending_kr_gate_holds_the_month_then_leaves_kr_out(self):
        self.gates["KR"] = None
        cli = FakeCli(collect=OK_COLLECT)
        run = self.run_ops(self.NOW, cli, holdings="2026-10-30")
        self.assertEqual(
            cli.commands(),
            [
                "universe --as-of US",
                "universe --as-of KR",
                "universe-merge --as-of-us --as-of-kr --only",
                "collect US KR",
            ],
        )
        self.assertTrue(
            any("held while the KR coverage gate" in w for w in run.waiting)
        )
        # The window's last session (4 after T): registered without KR, a problem.
        cli = FakeCli(
            collect=OK_COLLECT,
            **{
                "score-dry": collected(markets=("US",)),
                "score": dict(labels={}, asOf={}),
            },
        )
        run = self.run_ops("2026-11-06T13:00:00+00:00", cli)
        self.assertEqual(cli.calls[-1][:3], ["score", "--as-of-us", "2026-10-30"])
        self.assertNotIn("--as-of-kr", cli.calls[-1])
        self.assertTrue(any("KR left out" in p for p in run.problems))

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
                "universe-merge --as-of-us --only",
                "collect US",
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

    def test_one_market_failing_never_stops_the_other(self):
        def ssga_down():
            raise common.FetchError("SSGA: HTTP 503 for ssga-spy-holdings")

        cli = FakeCli(collect=OK_COLLECT)
        run = ops.Ops(runner=cli, now=at(self.NOW), sessions=SESSIONS)
        run.holdings_as_of = ssga_down
        with mock.patch("builtins.print"):
            run.operate()
        self.assertIn("universe --as-of KR", cli.commands())
        self.assertTrue(any("US part" in p and "503" in p for p in run.problems))


class EvaluationAndCache(OpsCase):
    def test_evaluation_only_when_asked(self):
        self.gates = {"US": dict(PASS), "KR": dict(PASS)}
        self.registered = [dict(month="2026-10")]
        cli = FakeCli(evaluate=dict(official=True))
        # Saturday 02:53 UTC: Friday 22:53 ET, Saturday 11:53 KST.
        run = self.run_ops("2026-11-14T02:53:00+00:00", cli, evaluate=True)
        self.assertEqual(cli.calls, [["evaluate", "--through", "2026-11-13"]])
        self.assertEqual(run.problems, [])
        cli = FakeCli()
        self.run_ops("2026-11-14T04:53:00+00:00", cli)
        self.assertEqual(cli.calls, [])
        cli = FakeCli(evaluate=dict(official=False, officialBlockers=["offline"]))
        run = self.run_ops("2026-11-14T02:53:00+00:00", cli, evaluate=True)
        self.assertTrue(any("offline" in p for p in run.problems))
        errors = dict(
            official=True,
            errors=1,
            periods=[dict(errors=[dict(id="US:1", reason="series_ends_before_entry")])],
        )
        cli = FakeCli(evaluate=lambda args: (1, errors, ""))
        run = self.run_ops("2026-11-14T02:53:00+00:00", cli, evaluate=True)
        self.assertTrue(any("series_ends_before_entry" in p for p in run.problems))

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
        self.gates = {"US": dict(PASS), "KR": None}
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
            sorted(p.name for p in (self.data / "work").iterdir()),
            ["2026-10-19-gate", "2026-11-30"],
        )


class Publication(unittest.TestCase):
    """publish() against a real bare remote: verified pushes, a rebase that stops
    is aborted and reported, never reported as pushed."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        self.remote, self.work, self.other = (
            base / "remote.git",
            base / "work",
            base / "other",
        )
        env = dict(
            GIT_AUTHOR_NAME="t",
            GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="t",
            GIT_COMMITTER_EMAIL="t@example.invalid",
        )
        patcher = mock.patch.dict("os.environ", env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.git(base, "init", "-q", "--bare", "-b", "main", str(self.remote))
        for clone in (self.work, self.other):
            self.git(base, "clone", "-q", str(self.remote), str(clone))
        (self.work / "data/ratings").mkdir(parents=True)
        (self.work / "data/ratings/ledger.jsonl").write_text("a\n")
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-q", "-m", "start")
        self.git(self.work, "push", "-q", "origin", "HEAD:main")
        self.git(self.other, "pull", "-q", "origin", "main")
        patcher = mock.patch.object(ops, "ROOT", self.work)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def git(where, *args):
        return subprocess.run(
            ["git", *args], cwd=where, check=True, capture_output=True, text=True
        )

    def ops(self):
        run = ops.Ops(push=True, runner=lambda *a: (0, {}, ""), sessions=SESSIONS)
        return run

    def remote_log(self):
        return self.git(self.work, "log", "--format=%s", "origin/main").stdout.split(
            "\n"
        )

    def test_push_after_another_push_and_a_stopped_rebase(self):
        run = self.ops()
        (self.work / "data/ratings/ledger.jsonl").write_text("a\nb\n")
        with mock.patch("builtins.print"):
            self.assertTrue(run.publish("first"))
        self.assertEqual(self.remote_log()[0], "first")
        # Someone else pushed a different file meanwhile: rebased, then pushed.
        self.git(self.other, "pull", "-q", "origin", "main")
        (self.other / "README").write_text("x")
        self.git(self.other, "add", "-A")
        self.git(self.other, "commit", "-q", "-m", "other")
        self.git(self.other, "push", "-q", "origin", "HEAD:main")
        (self.work / "data/ratings/v1").mkdir()
        (self.work / "data/ratings/v1/2026-10.json").write_text("{}")
        with mock.patch("builtins.print"):
            self.assertTrue(run.publish("second"))
        self.git(self.work, "fetch", "-q")
        self.assertEqual(self.remote_log()[:2], ["second", "other"])
        # A conflicting push: the rebase stops, is aborted, and nothing is "pushed".
        self.git(self.other, "pull", "-q", "origin", "main")
        (self.other / "data/ratings/ledger.jsonl").write_text("a\nb\nX\n")
        self.git(self.other, "commit", "-q", "-am", "conflict")
        self.git(self.other, "push", "-q", "origin", "HEAD:main")
        (self.work / "data/ratings/ledger.jsonl").write_text("a\nb\nc\n")
        with mock.patch("builtins.print"):
            self.assertFalse(run.publish("third"))
        self.assertTrue(
            any("rebase onto origin/main stopped" in p for p in run.problems)
        )
        self.assertFalse(any("pushed: third" in d for d in run.done))
        status = self.git(self.work, "status").stdout
        self.assertNotIn("rebase in progress", status)


class Main(unittest.TestCase):
    def test_exit_status_and_git_errors(self):
        def failing(self, evaluate=False):
            raise subprocess.CalledProcessError(1, ["git", "commit"], stderr="boom")

        with mock.patch.object(ops.Ops, "operate", failing), mock.patch(
            "builtins.print"
        ), mock.patch.object(ops, "code_digest", lambda: "0"):
            self.assertEqual(ops.main(["operate"]), 1)
        with mock.patch.object(
            ops.Ops, "operate", lambda self, evaluate=False: None
        ), mock.patch("builtins.print"), mock.patch.object(
            ops, "code_digest", lambda: "0"
        ):
            self.assertEqual(ops.main(["operate"]), 0)


if __name__ == "__main__":
    unittest.main()
