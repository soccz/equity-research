#!/usr/bin/env python3
"""Unattended operation of ratings-v1 (docs/ratings-v1.md §5–§7 and §9).

GitHub Actions runs ``operate`` on a schedule (.github/workflows/ratings.yml). Each run
reads the repository (ledger events, universe parts) and the clock, does what is due and
commits and pushes every public result right after it is made, the push being the
external proof of its time (§5):

- the computability-check gate, once per market (§7): both gate parts at the pinned
  asOf, their collection and ``coverage --gate`` from the check date on;
- the month's registration (§5): each market's part for its T once the month is over in
  that market (US only while SSGA shows T's holdings), ``collect --month`` and
  ``score`` within registrationWindowSessions sessions after T;
- the weekly official evaluation (``evaluate --through D``, §6).

Every step is the scripts/ratings.py command the protocol names, so the registry still
refuses whatever the protocol forbids: this script only decides when. It never passes
--overwrite, never edits the ledger and is not one of the codeFiles a registration
records. Collection errors left after the retries are registered as recorded failures
(``score --allow-errors``) only from RETRY_SESSIONS sessions after T, members without a
close on T (halts) at once, and never when more than ERROR_SHARE_MAX of a market failed.

``rehearse`` exercises the same commands on a past computability-check universe and a
smoke universe of the latest sessions without recording or pushing anything.

Exit status: 0 when everything due is done or still has time (holdings not posted yet,
collection errors inside their retries); 1 when a due step failed or a deadline passed,
so that the failed run notifies the operator; 2 on usage errors.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from time import sleep
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ratings import common, prices, rating, registry, universe  # noqa: E402

CLI = [sys.executable, str(ROOT / "scripts/ratings.py")]
MARKETS = common.MARKETS
WINDOW = int(registry.setting("registrationWindowSessions"))
CALENDAR = registry.setting("sessionCalendar")
CHECK = registry.gate_rule()
# §1: the first registration is the month of the check date (T 2026-10-30); earlier
# months were never to be registered, so they are neither due nor missed.
FIRST_MONTH = CHECK["date"][:7]
# §2: the price source carries KR closes of T from about 18:00 KST.
KR_READY = time(18, 30)
# Sessions after T during which members with collection errors are collected again by
# later runs before they are registered as recorded failures.
RETRY_SESSIONS = 2
# More failed members than this share of a market is a source failure, never members'
# failures: nothing is registered with --allow-errors then (the run fails instead).
ERROR_SHARE_MAX = 0.05
COLLECT_PASSES = 3
EVALUATION_WEEKDAY = 5  # Saturday (UTC): the weekly official evaluation
PUBLIC = (
    "data/ratings/universe",
    "data/ratings/ledger.jsonl",
    "data/ratings/v1",
    "data/ratings/periods",
    "data/ratings/evaluation",
)
# What a fresh runner needs again (restored from the Actions cache): kept evaluation
# series with their price originals, unfinished collections, the pinned Siccodes12.
KEEP_SOURCES = ("ken-french-siccodes12",)


class OpsError(RuntimeError):
    """A step could not run; the run fails after reporting it."""


def zone(market: str) -> ZoneInfo:
    return ZoneInfo(rating.PROTOCOL["registration"]["timezones"][market])


def window(sessions: list, as_of: str, today: str) -> dict:
    """Sessions after T before the market-local ``today``, the registry's count (D3)."""
    elapsed = len([s for s in sessions if as_of < s < today])
    return dict(elapsed=elapsed, open=elapsed < WINDOW)


def month_target(sessions: list, today: str) -> dict | None:
    """The month that ended last before ``today`` with its T (its last session) and
    window, or None without a session in it."""
    month = (date.fromisoformat(today).replace(day=1) - timedelta(days=1)).strftime(
        "%Y-%m"
    )
    days = [s for s in sessions if s.startswith(f"{month}-")]
    if not days:
        return None
    return dict(month=month, asOf=days[-1], **window(sessions, days[-1], today))


def run_cli(*args) -> tuple[int, dict | None, str]:
    """Run scripts/ratings.py: (exit code, its JSON summary, its stderr). Progress on
    stderr is echoed as it comes; stdout holds only the summary."""
    proc = subprocess.Popen(
        CLI + [str(a) for a in args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lines = []

    def echo():
        for line in proc.stderr:
            sys.stderr.write(line)
            lines.append(line)

    reader = threading.Thread(target=echo)
    reader.start()
    out = proc.stdout.read()
    code = proc.wait()
    reader.join()
    try:
        summary = json.loads(out) if out.strip() else None
    except json.JSONDecodeError:
        summary = None
    return code, summary, "".join(lines[-20:]).strip()


def git(*args, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check, capture_output=True, text=True
    )


class Ops:
    def __init__(
        self, *, push=False, runner=run_cli, now=None, sessions=None, holdings=None
    ):
        self.push = push
        self.runner = runner
        self.now = now or datetime.now(timezone.utc)
        self._sessions = sessions  # tests: {market: [YYYY-MM-DD, ...]}
        self._holdings = holdings  # tests: the date of SSGA's posted holdings
        self.done, self.waiting, self.problems = [], [], []

    # --- reporting -----------------------------------------------------------------

    def note(self, text: str) -> None:
        self.done.append(text)
        print(f"ops: {text}", flush=True)

    def wait(self, text: str) -> None:
        self.waiting.append(text)
        print(f"ops: waiting: {text}", flush=True)

    def problem(self, text: str) -> None:
        self.problems.append(text)
        print(f"ops: PROBLEM: {text}", flush=True)

    def report(self) -> dict:
        out = dict(
            at=self.now.isoformat(timespec="seconds"),
            done=self.done,
            waiting=self.waiting,
            problems=self.problems,
        )
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            lines = [f"### ratings-v1 operation {out['at']}"]
            for title, items in (
                ("Problems", self.problems),
                ("Done", self.done),
                ("Waiting", self.waiting),
            ):
                lines += [f"**{title}**"] + [f"- {i}" for i in items] if items else []
            with open(summary, "a") as handle:
                handle.write("\n".join(lines) + "\n")
        return out

    # --- inputs ----------------------------------------------------------------------

    def today(self, market: str) -> str:
        return self.now.astimezone(zone(market)).date().isoformat()

    def sessions(self, market: str) -> list:
        if self._sessions is not None:
            return self._sessions[market]
        for attempt in range(3):  # D17: an unpublished close flaps within minutes
            series = prices.series(CALENDAR[market], self.today(market), online=True)
            if series["status"] == "ok":
                return [row[0] for row in series["rows"]]
            sleep(90 * (attempt + 1))
        raise OpsError(
            f"{market}: no {CALENDAR[market]} sessions ({series.get('error')})"
        )

    def holdings_as_of(self) -> str:
        if self._holdings is not None:
            return self._holdings
        blob, _ = common.fetch(
            universe.SPY_URL, "ssga-spy-holdings", provider="SSGA", suffix=".xlsx"
        )
        return universe.spy_holdings(blob)["asOf"]

    def cli(self, *args) -> tuple[int, dict | None, str]:
        print(f"ops: ratings.py {' '.join(map(str, args))}", flush=True)
        return self.runner(*args)

    # --- publication -----------------------------------------------------------------

    def publish(self, message: str) -> None:
        """Commit the public results and push them now (§5 external proof of time)."""
        if not self.push:
            self.note(f"not pushed (no --push): {message}")
            return
        paths = [p for p in PUBLIC if (ROOT / p).exists()]
        git("add", "-A", "--", *paths)
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return
        git("commit", "-m", message)
        for _ in range(3):
            if git("push", "origin", "HEAD:main", check=False).returncode == 0:
                self.note(f"pushed: {message}")
                return
            git("pull", "--rebase", "--autostash", "origin", "main", check=False)
        self.problem(f"push failed (committed in this runner only): {message}")

    # --- universe parts ----------------------------------------------------------------

    def part(self, market: str, as_of: str, gate: bool) -> bool:
        """Build the market's part for T unless it is saved; True when it exists."""
        path = universe.part_path(market, as_of, gate=gate)
        if path.exists():
            return True
        label = f"{market} {'gate ' if gate else ''}universe part for {as_of}"
        if market == "KR":
            ready = datetime.combine(date.fromisoformat(as_of), KR_READY, zone("KR"))
            if self.now < ready:
                self.wait(f"{label}: T's closes are out from {ready.isoformat()}")
                return False
        else:
            if self.today("US") <= as_of:
                self.wait(f"{label}: SSGA posts T's holdings the next business day")
                return False
            posted = self.holdings_as_of()
            if posted < as_of:
                self.wait(f"{label}: SSGA still shows holdings as of {posted}")
                return False
            if posted > as_of:
                self.problem(
                    f"{label}: SSGA already shows holdings as of {posted}; T's "
                    "holdings can no longer be captured"
                )
                return False
        args = ["universe", "--as-of", as_of, "--markets", market]
        code, summary, error = self.cli(*args, *(["--gate"] if gate else []))
        if code != 0 or not path.exists():
            info = ((summary or {}).get("markets") or {}).get(market) or {}
            self.problem(f"{label} not built: {info.get('error') or error}")
            return False
        info = ((summary or {}).get("markets") or {}).get(market) or {}
        if market == "US" and info.get("holdingsAsOf") != as_of:
            self.problem(
                f"{label} saved with SSGA holdings as of {info.get('holdingsAsOf')} "
                "(posted during the build): the registry refuses it"
            )
        self.note(f"built the {label}")
        self.publish(f"ratings-v1: {label}")
        return True

    # --- collection --------------------------------------------------------------------

    def collect(self, *args) -> dict:
        """Collect up to COLLECT_PASSES times while members are left with errors or
        uncollected; returns the last summary's markets."""
        markets, before = {}, None
        for attempt in range(1, COLLECT_PASSES + 1):
            code, summary, error = self.cli("collect", *args)
            if summary is None:
                raise OpsError(f"collect {' '.join(args)}: {error}")
            markets = summary.get("markets") or {}
            left = {
                m: {k: v for k, v in (s.get("state") or {}).items() if k != "ok"}
                for m, s in markets.items()
            }
            left = {m: state for m, state in left.items() if state}
            if not left:
                return markets
            self.note(f"collect pass {attempt}: not ok {left}")
            count = sum(sum(state.values()) for state in left.values())
            if before is not None and count >= before:
                break  # nothing improved: later runs try again
            before = count
        return markets

    # --- the computability-check gate (§7) -------------------------------------------

    def gate(self, sessions: dict) -> None:
        pending = [m for m in MARKETS if registry.gate(m) is None]
        if not pending:
            return
        as_of = CHECK["asOf"]
        ready = True
        for market in pending:
            today = self.today(market)
            path = universe.part_path(market, as_of, gate=True)
            if not path.exists() and not window(sessions[market], as_of, today)["open"]:
                self.problem(
                    f"{market} gate part for {as_of} was not captured inside its "
                    "window: the gate can never be recorded (§7 needs ratings-v2)"
                )
                ready = False
                continue
            ready = self.part(market, as_of, gate=True) and ready
        if not ready:
            return
        self.collect("--as-of", as_of, "--gate", "--markets", *pending)
        code, summary, error = self.cli(
            "coverage", "--as-of", as_of, "--gate", "--markets", *pending
        )
        if summary is None:
            self.problem(f"coverage --gate: {error}")
            return
        recorded = []
        for market in pending:
            entry = (summary.get("markets") or {}).get(market) or {}
            outcome = entry.get("gate") or {}
            rate = entry.get("rate")
            shown = f"{entry.get('verdict')} {rate:.1%}" if rate is not None else "-"
            if outcome.get("recorded"):
                recorded.append(f"{market} {shown}")
            elif self.today(market) < CHECK["date"]:
                self.wait(f"{market} gate {shown}: recorded from {CHECK['date']}")
            else:
                self.problem(f"{market} gate not recorded ({shown}): {outcome}")
        if recorded:
            self.note(f"coverage gate recorded: {', '.join(recorded)}")
            self.publish(f"ratings-v1: coverage gate {', '.join(recorded)}")

    # --- the month's registration (§5) -----------------------------------------------

    def month(self, sessions: dict) -> None:
        gates = {m: registry.gate(m) for m in MARKETS}
        if gates["US"] is None:
            return  # D10: nothing is registered before the gates
        if gates["US"].get("verdict") != "pass":
            self.note("the US coverage gate failed: ratings are not published (§7)")
            return
        markets = ["US"] + (
            ["KR"] if (gates["KR"] or {}).get("verdict") == "pass" else []
        )
        done = [r["month"] for r in registry.registrations()]
        last = max(done) if done else ""
        targets = {m: month_target(sessions[m], self.today(m)) for m in markets}
        for market in markets:  # each part as soon as its month is over there
            target = targets[market]
            if target is None or target["month"] <= last:
                continue
            if target["month"] < FIRST_MONTH:
                continue
            path = universe.part_path(market, target["asOf"])
            if not target["open"]:
                if not path.exists():
                    self.problem(
                        f"{market} {target['month']}: the window closed without a "
                        "universe part (D3: a missed month is never registered)"
                    )
                continue
            self.part(market, target["asOf"], gate=False)
        month = (targets["US"] or {}).get("month")
        if not month or month <= last or month < FIRST_MONTH:
            return
        if any((targets[m] or {}).get("month") != month for m in markets):
            return
        if not all(targets[m]["open"] for m in markets):
            self.problem(
                f"{month}: the registration window closed unregistered (D3: a "
                "missed month is never registered; evaluation exits at T+6, D4)"
            )
            return
        if all(universe.part_path(m, targets[m]["asOf"]).exists() for m in markets):
            self.register(month, {m: targets[m] for m in markets})

    def register(self, month: str, targets: dict) -> None:
        flags = []
        for market, target in targets.items():
            flags += [f"--as-of-{market.lower()}", target["asOf"]]
        self.collect("--month", month, "--markets", *targets)
        code, dry, error = self.cli("score", *flags, "--dry-run")
        if code != 0 or dry is None:
            self.problem(f"{month}: dry run failed: {error}")
            return
        if dry.get("checks"):
            self.problem(f"{month}: the registry would refuse: {dry['checks'][:6]}")
            return
        stats = dry.get("collection") or {}
        unready = {
            m: s for m, s in stats.items() if s.get("notCollected") or s.get("stale")
        }
        if unready:
            self.problem(f"{month}: members not collected or stale: {unready}")
            return
        errors = {m: s["errors"] for m, s in stats.items() if s.get("errors")}
        failures = {m: s["failures"] for m, s in stats.items() if s.get("failures")}
        elapsed = max(t["elapsed"] for t in targets.values())
        if errors and elapsed < RETRY_SESSIONS:
            self.wait(
                f"{month}: collection errors {errors} are collected again by later "
                f"runs until {RETRY_SESSIONS} sessions after T"
            )
            return
        heavy = {
            m: n
            for m, n in failures.items()
            if n > ERROR_SHARE_MAX * max(stats[m].get("eligible") or 0, 1)
        }
        if heavy:
            self.problem(
                f"{month}: {heavy} members failed, over {ERROR_SHARE_MAX:.0%} of the "
                "market: a source failure, not registered (collect again)"
            )
            return
        allow = ["--allow-errors"] if failures else []
        code, summary, error = self.cli("score", *flags, *allow)
        if code != 0 or summary is None:
            self.problem(f"{month}: registration refused: {error}")
            return
        labels = summary.get("labels")
        self.note(f"registered {month} {summary.get('asOf')}: {labels}")
        self.publish(f"ratings-v1: registration {month}")

    # --- evaluation (§6) ---------------------------------------------------------------

    def evaluate(self) -> None:
        if not registry.registrations():
            return
        through = min(self.today(m) for m in MARKETS)
        code, summary, error = self.cli("evaluate", "--through", through)
        if summary is None or not summary.get("official"):
            blockers = (summary or {}).get("officialBlockers")
            self.problem(f"evaluation through {through}: {blockers or error}")
            return
        self.note(f"official evaluation through {through}")
        self.publish(f"ratings-v1: evaluation through {through}")

    # --- the Actions cache -------------------------------------------------------------

    def prune(self) -> None:
        """Keep the cache to what a later run reads: kept evaluation series and their
        originals, unfinished collections and the pinned Siccodes12 original."""
        keep = set()
        for path in (common.RATINGS / "series").glob("*.json"):
            for original in json.loads(path.read_text()).get("originals") or []:
                keep.add(Path((original.get("source") or {}).get("file", "")).name)
        removed = 0
        for path in common.SOURCES.glob("*"):
            if path.name in keep or path.name.startswith(KEEP_SOURCES):
                continue
            path.unlink()
            removed += 1
        finished = {r["month"] for r in registry.registrations()}
        gated = all(registry.gate(m) is not None for m in MARKETS)
        for folder in (common.RATINGS / "work").glob("*"):
            stem = folder.name
            if (stem.endswith("-gate") and gated) or stem[:7] in finished:
                shutil.rmtree(folder)
        print(f"ops: pruned {removed} originals not kept for a later run", flush=True)

    # --- runs --------------------------------------------------------------------------

    def operate(self, evaluate: str = "auto") -> None:
        sessions = {m: self.sessions(m) for m in MARKETS}
        for step in (self.gate, self.month):
            try:
                step(sessions)
            except (OpsError, common.FetchError, ValueError, OSError) as exc:
                self.problem(f"{step.__name__}: {type(exc).__name__}: {exc}")
        due = evaluate == "yes" or (
            evaluate == "auto" and self.now.weekday() == EVALUATION_WEEKDAY
        )
        if due:
            try:
                self.evaluate()
            except (OpsError, common.FetchError, ValueError, OSError) as exc:
                self.problem(f"evaluate: {type(exc).__name__}: {exc}")

    def rehearse(self, gate_days: dict, smoke: int | None) -> None:
        """Collect and check past gate universes and build smoke parts of the latest
        sessions: nothing is recorded (their asOf is not the pinned one) or pushed."""
        for market, as_of in gate_days.items():
            if as_of == CHECK["asOf"]:
                raise OpsError("rehearse never runs on the pinned gate asOf")
            self.collect("--as-of", as_of, "--gate", "--markets", market)
            code, summary, error = self.cli(
                "coverage", "--as-of", as_of, "--gate", "--markets", market
            )
            entry = ((summary or {}).get("markets") or {}).get(market)
            if not entry:
                self.problem(f"{market} coverage {as_of}: {error}")
                continue
            keys = ("verdict", "rate", "withTwoSignals", "nonFinancial")
            self.note(f"{market} {as_of}: {({k: entry.get(k) for k in keys})}")
        if not smoke:
            return
        for market in MARKETS:
            today, cal = self.today(market), self.sessions(market)
            past = [s for s in cal if s < today]
            if market == "KR":
                ready = [
                    s
                    for s in cal
                    if datetime.combine(date.fromisoformat(s), KR_READY, zone("KR"))
                    <= self.now
                ]
                as_of = ready[-1] if ready else None
            else:
                as_of = self.holdings_as_of() if past else None
            if not as_of:
                self.problem(f"{market}: no session for a smoke universe")
                continue
            code, summary, error = self.cli(
                "universe",
                "--as-of",
                as_of,
                "--markets",
                market,
                "--gate",
                "--limit",
                smoke,
            )
            info = ((summary or {}).get("markets") or {}).get(market) or {}
            if code != 0:
                self.problem(f"{market} smoke universe {as_of}: {info or error}")
            else:
                self.note(
                    f"{market} smoke universe {as_of}: {info.get('status')} "
                    f"{info.get('counts')}"
                )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="ratings_ops.py", description=__doc__.split("\n")[0]
    )
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("operate", help="do what is due now (scheduled runs)")
    c.add_argument("--push", action="store_true", help="commit and push results")
    c.add_argument("--evaluate", choices=("auto", "yes", "no"), default="auto")
    c.add_argument("--prune", action="store_true", help="trim the Actions cache")
    c = sub.add_parser("rehearse", help="exercise the pipeline without recording")
    c.add_argument(
        "--gate-universe",
        nargs="*",
        default=["US=2026-10-05", "KR=2026-10-06"],
        help="MARKET=asOf of past computability-check universes to collect",
    )
    c.add_argument("--smoke", type=int, default=20, help="0: no smoke universe")
    args = p.parse_args(argv)
    ops = Ops(push=getattr(args, "push", False))
    try:
        if args.command == "operate":
            ops.operate(args.evaluate)
            if args.prune:
                ops.prune()
        else:
            days = dict(item.split("=", 1) for item in args.gate_universe)
            ops.rehearse(days, args.smoke)
    except (OpsError, common.FetchError, ValueError, OSError) as exc:
        ops.problem(f"{type(exc).__name__}: {exc}")
    print(json.dumps(ops.report(), ensure_ascii=False, indent=1))
    return 1 if ops.problems else 0


if __name__ == "__main__":
    sys.exit(main())
