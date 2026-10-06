#!/usr/bin/env python3
"""Unattended operation of ratings-v1 (docs/ratings-v1.md §5–§7 and §9).

GitHub Actions runs ``operate`` on a schedule (.github/workflows/ratings.yml). Each run
reads the repository (ledger events, universe parts) and the clock, does what is due and
commits and pushes every public result right after it is made, the push being the
external proof of its time (§5):

- the computability-check gate, once per market (§7): the gate parts at the pinned
  asOf, their merge, collection and ``coverage --gate`` from the check date on, after a
  report-only coverage shows no source failure (a recorded verdict is final);
- the month's registration (§5): each market's part for its T once the month is over in
  that market (US only while SSGA shows T's holdings), an explicit merge, ``collect``
  and ``score`` within registrationWindowSessions sessions after T;
- the official evaluation (``evaluate --through D``, §6) when asked (weekly).

Every step is the scripts/ratings.py command the protocol names, so the registry still
refuses whatever the protocol forbids: this script only decides when. It never passes
--overwrite, never edits the ledger and is not one of the codeFiles a registration
records. Parts are merged with explicit dates and every later step names the merged
file, so no other part of the month (a rehearsal, a part of a wrong T) is ever picked.
Collection errors are collected again until RETRY_SESSIONS sessions after T in their
market and then registered as recorded failures (``score --allow-errors``), US members
without a close on T (halts) at once; KR members without one are retried like errors
(they were ranked at T's close, so their missing close is the source's); nothing is
registered or recorded when more than ERROR_SHARE_MAX of a market failed.

``rehearse`` builds computability-check universes of the latest sessions (or uses the
given ones), collects them and reports their coverage without recording or pushing.

Exit status: 0 when everything due is done or still has time (holdings not posted yet,
collection errors inside their retries); 1 when a due step failed or a deadline passed,
so that the failed run notifies the operator (a condition that can no longer change is
reported as a problem for LASTING_DAYS, then as a note); 2 on usage errors.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
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
# A second series per market so that one late or unpublished bar never moves T (the
# registry checks T against CALENDAR itself when it registers).
SECOND_CALENDAR = {"US": "SPY", "KR": "^KS11"}
CHECK = registry.gate_rule()
# §1: the first registration is the month of the check date (T 2026-10-30); earlier
# months were never to be registered, so they are neither due nor missed.
FIRST_MONTH = CHECK["date"][:7]
# §2: the price source carries KR closes of T from about 18:00 KST.
KR_READY = time(18, 30)
# Sessions after T (in the member's market) during which members with collection
# errors are collected again by later runs before they are registered as failures.
RETRY_SESSIONS = 2
# More failed members than this share of a market is a source failure, never members'
# failures: nothing is registered or recorded then (the run fails instead).
ERROR_SHARE_MAX = 0.05
COLLECT_PASSES = 3
# A condition that can no longer change is a problem (failed run) for this many days
# after it arose, then a note, so that later runs can still report new problems.
LASTING_DAYS = 3
PUBLIC = (
    "data/ratings/universe",
    "data/ratings/ledger.jsonl",
    "data/ratings/v1",
    "data/ratings/periods",
    "data/ratings/evaluation",
)
CODE = ("ratings", "scripts/ratings.py", "scripts/ratings_ops.py")
# What a fresh runner needs again (restored from the Actions cache): kept evaluation
# series with their price originals, unfinished collections, the pinned Siccodes12.
KEEP_SOURCES = ("ken-french-siccodes12",)


class OpsError(RuntimeError):
    """A step could not run; the run fails after reporting it."""


def zone(market: str) -> ZoneInfo:
    return ZoneInfo(rating.PROTOCOL["registration"]["timezones"][market])


def window(sessions: list, as_of: str, today: str) -> dict:
    """Sessions after T before the market-local ``today``, the registry's count (D3);
    ``closes`` is the session on which the window closed (None while open)."""
    after = [s for s in sessions if as_of < s < today]
    closes = after[WINDOW - 1] if len(after) >= WINDOW else None
    return dict(elapsed=len(after), open=closes is None, closes=closes)


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


def code_digest() -> str:
    """SHA-256 over the code a run executes (ratings/, the CLI and this script)."""
    hashed = sha256()
    for name in CODE:
        path = ROOT / name
        files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
        for file in (f for f in files if f.is_file()):
            hashed.update(file.relative_to(ROOT).as_posix().encode() + b"\0")
            hashed.update(file.read_bytes())
    return hashed.hexdigest()


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
        self.worked = False  # collected, built or evaluated: the cache is saved
        self.code = None if runner is not run_cli else code_digest()

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

    def lasting(self, text: str, since: str | None, market: str) -> None:
        """A condition that can no longer change: a problem until LASTING_DAYS after
        ``since`` (a market-local date), a note after that."""
        today = date.fromisoformat(self.today(market))
        if since and (today - date.fromisoformat(since)).days > LASTING_DAYS:
            self.note(f"(since {since}) {text}")
        else:
            self.problem(text)

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
                lines += ([f"**{title}**"] + [f"- {i}" for i in items]) if items else []
            with open(summary, "a") as handle:
                handle.write("\n".join(lines) + "\n")
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a") as handle:
                handle.write(f"worked={str(self.worked).lower()}\n")
        return out

    # --- inputs ----------------------------------------------------------------------

    def today(self, market: str) -> str:
        return self.now.astimezone(zone(market)).date().isoformat()

    def sessions(self, market: str) -> list:
        """The market's sessions through today: the protocol's calendar series and a
        second series, each with its sessions traded without a published close (D17);
        one of them is enough."""
        if self._sessions is not None:
            return self._sessions[market]
        found, failures = set(), []
        for symbol in (CALENDAR[market], SECOND_CALENDAR[market]):
            series = prices.series(symbol, self.today(market), online=True)
            if series["status"] != "ok" and prices.transient_failure(series):
                sleep(60)
                series = prices.series(symbol, self.today(market), online=True)
            if series["status"] == "ok":
                found |= {row[0] for row in series["rows"]}
                found |= set(series.get("unpublishedSessions") or [])
            else:
                failures.append(f"{symbol}: {series.get('error')}")
        if not found:
            raise OpsError(f"{market}: no session calendar ({'; '.join(failures)})")
        return sorted(found)

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

    def publish(self, message: str) -> bool:
        """Commit the public results and push them now (§5 external proof of time).
        A push is verified against origin; a rebase that stops is aborted, and new
        code arriving with a pull stops the run (it was not the code checked)."""
        if not self.push:
            self.note(f"not pushed (no --push): {message}")
            return True
        tracked = git("ls-files", "--", *PUBLIC).stdout.split()
        paths = [
            p
            for p in PUBLIC
            if (ROOT / p).exists()
            or any(t == p or t.startswith(f"{p}/") for t in tracked)
        ]
        git("add", "-A", "--", *paths)
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return True
        git("commit", "-q", "-m", message)
        for _ in range(3):
            if git("push", "-q", "origin", "HEAD:main", check=False).returncode == 0:
                git("fetch", "-q", "origin", "main", check=False)
                ahead = git("rev-list", "--count", "origin/main..HEAD", check=False)
                if ahead.stdout.strip() == "0":
                    self.note(f"pushed: {message}")
                    return True
            pulled = git(
                "pull", "-q", "--rebase", "--autostash", "origin", "main", check=False
            )
            if pulled.returncode != 0:
                git("rebase", "--abort", check=False)
                self.problem(
                    f"push failed, the rebase onto origin/main stopped "
                    f"({pulled.stderr.strip()[-300:]}): {message}"
                )
                return False
            if self.code is not None and code_digest() != self.code:
                self.push = False
                raise OpsError("new code arrived with a pull: the run stops here")
        self.problem(f"push failed after 3 attempts (committed here only): {message}")
        return False

    def discard_universe(self) -> None:
        """Back to the committed universe folder (a part that must not be published)."""
        if self.push:
            git("checkout", "-q", "--", "data/ratings/universe", check=False)
            git("clean", "-q", "-fd", "--", "data/ratings/universe", check=False)

    # --- universe parts ----------------------------------------------------------------

    def part(self, market: str, as_of: str, gate: bool, sessions: list) -> bool:
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
                late = window(sessions, as_of, self.today("US"))["elapsed"] >= 2
                text = f"{label}: SSGA still shows holdings as of {posted}"
                (self.problem if late else self.wait)(text)
                return False
            if posted > as_of:
                self.problem(
                    f"{label}: SSGA already shows holdings as of {posted}; T's "
                    "holdings can no longer be captured"
                )
                return False
        self.worked = True
        args = ["universe", "--as-of", as_of, "--markets", market]
        code, summary, error = self.cli(*args, *(["--gate"] if gate else []))
        if not path.exists():
            info = ((summary or {}).get("markets") or {}).get(market) or {}
            self.problem(f"{label} not built: {info.get('error') or error}")
            return False
        if market == "US":
            info = (json.loads(path.read_text()).get("markets") or {}).get("US") or {}
            if info.get("holdingsAsOf") != as_of:  # SSGA posted during the build
                path.unlink()
                self.discard_universe()
                self.problem(
                    f"{label}: built from SSGA holdings as of "
                    f"{info.get('holdingsAsOf')}: discarded, never published"
                )
                return False
        if code != 0:  # e.g. MonthNotMerged: the part is saved, merged explicitly
            self.note(f"{label} saved; its build did not merge it ({error[-200:]})")
        self.note(f"built the {label}")
        self.publish(f"ratings-v1: {label}")
        return True

    def merge(self, days: dict, gate: bool) -> str | None:
        """Merge exactly these parts (never another part of the month); the merged
        file, published when it changed."""
        flags = [f"--as-of-{m.lower()}" for m in days]
        args = [x for pair in zip(flags, days.values()) for x in pair]
        code, summary, error = self.cli(
            "universe-merge", *args, "--only", *(["--gate"] if gate else [])
        )
        if code != 0 or not (summary or {}).get("file"):
            self.problem(f"merge of {days}: {error}")
            return None
        if summary.get("checks"):
            self.problem(f"merge of {days}: {summary['checks'][:4]}")
            return None
        self.publish(f"ratings-v1: universe {summary['file']}")
        return summary["file"]

    # --- collection --------------------------------------------------------------------

    def collect(self, *args) -> dict:
        """Collect up to COLLECT_PASSES times while members are left with errors or
        uncollected; returns the last summary's markets."""
        self.worked = True
        markets, before = {}, None
        for attempt in range(1, COLLECT_PASSES + 1):
            code, summary, error = self.cli("collect", *args)
            if summary is None:
                raise OpsError(f"collect {' '.join(map(str, args))}: {error}")
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

    @staticmethod
    def source_failure(market: str, stats: dict) -> str | None:
        """Why a market's collection looks like a source failure, not members': KR
        members without a close on T (they were ranked at T's close), or more failed
        members than ERROR_SHARE_MAX."""
        missing = stats.get("noCloseOnAsOf") or 0
        failed = (stats.get("collectionErrors", stats.get("errors")) or 0) + missing
        base = max(stats.get("nonFinancial") or stats.get("eligible") or 0, 1)
        if market == "KR" and missing:
            return f"{missing} KR members without a close on T"
        if failed > ERROR_SHARE_MAX * base:
            return f"{failed} of {base} members failed"
        return None

    # --- the computability-check gate (§7) -------------------------------------------

    def gate(self, sessions: dict) -> None:
        pending = [m for m in MARKETS if registry.gate(m) is None]
        if not pending:
            return
        as_of, have, lost = CHECK["asOf"], [], []
        for market in pending:
            if market not in sessions:
                continue  # its calendar failed: reported
            path = universe.part_path(market, as_of, gate=True)
            span = window(sessions[market], as_of, self.today(market))
            if path.exists():
                have.append(market)
            elif not span["open"]:
                lost.append(market)
                self.lasting(
                    f"{market} gate part for {as_of} was never captured inside its "
                    "window: that market's gate can never be recorded (§7)",
                    span["closes"],
                    market,
                )
            elif self.part(market, as_of, gate=True, sessions=sessions[market]):
                have.append(market)
        if not have:
            return
        merged = self.merge({m: as_of for m in have}, gate=True)
        if merged is None:
            return
        # Each market is collected as soon as its part is in (KR on T's evening, before
        # the KST day rollover; D17); the gate is recorded once every part that can
        # still be built is in, from one merge.
        self.collect("--universe", merged, "--gate", "--markets", *have)
        if [m for m in pending if m not in have + lost]:
            return
        report = ["coverage", "--as-of", as_of, "--gate", "--universe", merged]
        code, summary, error = self.cli(*report, "--offline", "--markets", *have)
        if summary is None:
            self.problem(f"coverage --gate (report only): {error}")
            return
        safe = []
        for market in have:
            entry = (summary.get("markets") or {}).get(market) or {}
            why = self.source_failure(market, entry)
            shown = self.shown(entry)
            if entry.get("verdict") == "incomplete":
                self.problem(f"{market} gate {shown}: incomplete, collected again")
            elif why:
                self.problem(f"{market} gate {shown} not recorded: {why}")
            elif self.today(market) < CHECK["date"]:
                self.wait(f"{market} gate {shown}: recorded from {CHECK['date']}")
            else:
                safe.append(market)
        if not safe:
            return
        code, summary, error = self.cli(*report, "--markets", *safe)
        recorded = []
        for market in safe:
            entry = ((summary or {}).get("markets") or {}).get(market) or {}
            if (entry.get("gate") or {}).get("recorded"):
                recorded.append(f"{market} {self.shown(entry)}")
            else:
                self.problem(
                    f"{market} gate not recorded: {entry.get('gate') or error}"
                )
        if recorded:
            self.note(f"coverage gate recorded: {', '.join(recorded)}")
            self.publish(f"ratings-v1: coverage gate {', '.join(recorded)}")

    @staticmethod
    def shown(entry: dict) -> str:
        rate = entry.get("rate")
        return f"{entry.get('verdict')} {rate:.1%}" if rate is not None else "-"

    # --- the month's registration (§5) -----------------------------------------------

    def month(self, sessions: dict) -> None:
        gates = {m: registry.gate(m) for m in MARKETS}
        if gates["US"] is None:
            return  # D10: nothing is registered before the US gate
        if gates["US"].get("verdict") != "pass":
            self.note("the US coverage gate failed: ratings are not published (§7)")
            return
        kr = (gates["KR"] or {}).get("verdict", "pending")
        markets = [m for m in MARKETS if m == "US" or kr != "fail"]
        markets = [m for m in markets if m in sessions]  # a failed calendar: reported
        done = [r["month"] for r in registry.registrations()]
        last = max(done) if done else ""
        targets = {m: month_target(sessions[m], self.today(m)) for m in markets}
        for market in markets:  # each part as soon as its month is over there
            target = targets[market]
            if not target or target["month"] <= last or target["month"] < FIRST_MONTH:
                continue
            path = universe.part_path(market, target["asOf"])
            if not target["open"]:
                if not path.exists():
                    self.lasting(
                        f"{market} {target['month']}: the window closed without a "
                        "universe part (D3: a missed month is never registered)",
                        target["closes"],
                        market,
                    )
                continue
            try:  # one market's failure never stops the other's part
                self.part(market, target["asOf"], gate=False, sessions=sessions[market])
            except (OpsError, common.FetchError, ValueError, OSError) as exc:
                self.problem(f"{market} part: {type(exc).__name__}: {exc}")
        if "US" not in markets or not targets.get("US"):
            return
        month = targets["US"]["month"]
        if month <= last or month < FIRST_MONTH:
            return
        listed = [m for m in markets if (targets[m] or {}).get("month") == month]
        if not all(targets[m]["open"] for m in listed):
            closes = max(t["closes"] or "" for t in targets.values() if t) or None
            self.lasting(
                f"{month}: the registration window closed unregistered (D3: a missed "
                "month is never registered; evaluation exits at T+6, D4)",
                closes,
                "US",
            )
            return
        built = {
            m: targets[m]["asOf"]
            for m in listed
            if universe.part_path(m, targets[m]["asOf"]).exists()
        }
        if "KR" in listed and kr == "pending":
            if targets["US"]["elapsed"] < WINDOW - 1:
                self.wait(f"{month}: held while the KR coverage gate is not recorded")
                listed = []  # collect early, register later
            else:
                self.problem(
                    f"{month}: KR left out (its coverage gate is not recorded)"
                )
                listed.remove("KR")
                built.pop("KR", None)
        if not listed or set(built) != set(listed):
            if built:  # collect each part as soon as it is in (D17: KR before 00 KST)
                merged = self.merge(built, gate=False)
                if merged:
                    self.collect("--universe", merged, "--markets", *built)
            return
        self.register(month, {m: targets[m] for m in listed})

    def register(self, month: str, targets: dict) -> None:
        days = {m: t["asOf"] for m, t in targets.items()}
        merged = self.merge(days, gate=False)
        if merged is None:
            return
        flags = [x for m, d in days.items() for x in (f"--as-of-{m.lower()}", d)]
        self.collect("--universe", merged, "--markets", *targets)
        code, dry, error = self.cli("score", *flags, "--universe", merged, "--dry-run")
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
        retry = {}
        for market, found in stats.items():
            count = found.get("errors") or 0
            if market == "KR":  # ranked at T's close: a missing close is the source's
                count += found.get("noCloseOnAsOf") or 0
            if count and targets[market]["elapsed"] < RETRY_SESSIONS:
                retry[market] = count
        if retry:
            self.wait(
                f"{month}: members with errors {retry} are collected again by later "
                f"runs until {RETRY_SESSIONS} sessions after T in their market"
            )
            return
        heavy = {}
        for market, found in stats.items():
            failed = found.get("failures") or 0
            if failed > ERROR_SHARE_MAX * max(found.get("eligible") or 0, 1):
                heavy[market] = failed
        if heavy:
            self.problem(
                f"{month}: {heavy} members failed, over {ERROR_SHARE_MAX:.0%} of the "
                "market: a source failure, not registered (collect again)"
            )
            return
        allow = (
            ["--allow-errors"] if any(s.get("failures") for s in stats.values()) else []
        )
        code, summary, error = self.cli("score", *flags, "--universe", merged, *allow)
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
        self.worked = True
        through = min(self.today(m) for m in MARKETS)
        code, summary, error = self.cli("evaluate", "--through", through)
        if summary is None or not summary.get("official"):
            blockers = (summary or {}).get("officialBlockers")
            self.problem(f"evaluation through {through}: {blockers or error}")
            return
        self.note(f"official evaluation through {through}")
        self.publish(f"ratings-v1: evaluation through {through}")
        if code != 0:  # member errors (series_ends_before_entry, no series, ...)
            found = [
                e for p in summary.get("periods") or [] for e in p.get("errors") or []
            ]
            self.problem(
                f"evaluation through {through}: {summary.get('errors')} member errors "
                f"{found[:5]}"
            )

    # --- the Actions cache -------------------------------------------------------------

    def prune(self) -> None:
        """Keep the cache to what a later run reads: kept evaluation series and their
        originals, unfinished collections, the collections a gate event cites and the
        pinned Siccodes12 original."""
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
        for folder in (common.RATINGS / "work").glob("*"):
            stem = folder.name
            if not stem.endswith(universe.GATE_SUFFIX) and stem[:7] in finished:
                shutil.rmtree(folder)
        print(f"ops: pruned {removed} originals not kept for a later run", flush=True)

    # --- runs --------------------------------------------------------------------------

    def calendars(self) -> dict:
        """Each market's sessions; a market whose calendar fails is reported and left
        out, the other goes on."""
        out = {}
        for market in MARKETS:
            try:
                out[market] = self.sessions(market)
            except (OpsError, common.FetchError, ValueError, OSError) as exc:
                self.problem(f"{market} calendar: {type(exc).__name__}: {exc}")
        return out

    def operate(self, evaluate: bool = False) -> None:
        sessions = self.calendars()
        steps = [("gate", self.gate), ("month", self.month)]
        if evaluate:
            steps.append(("evaluate", lambda _: self.evaluate()))
        for name, step in steps:
            try:
                step(sessions)
            except (OpsError, common.FetchError, ValueError, OSError) as exc:
                self.problem(f"{name}: {type(exc).__name__}: {exc}")
                if not self.push and "new code arrived" in str(exc):
                    return

    def rehearse(self, days: dict, limit: int | None) -> None:
        """Computability-check universes of the given asOf (default: the latest
        sessions: SSGA's holdings date, the last KR session with its closes out),
        merged, collected and reported without recording (coverage --offline)."""
        sessions = self.calendars()
        for market in MARKETS:
            if days.get(market) or market not in sessions:
                continue
            if market == "US":
                days[market] = self.holdings_as_of()
            else:
                ready = [
                    s
                    for s in sessions[market]
                    if datetime.combine(date.fromisoformat(s), KR_READY, zone("KR"))
                    <= self.now
                ]
                days[market] = ready[-1] if ready else None
        days = {m: d for m, d in days.items() if d}
        if CHECK["asOf"] in days.values():
            raise OpsError("rehearse never builds the pinned gate asOf")
        for market, as_of in days.items():
            path = universe.part_path(market, as_of, limit, gate=True)
            if path.exists():
                continue
            self.worked = True
            args = ["universe", "--as-of", as_of, "--markets", market, "--gate"]
            code, summary, error = self.cli(
                *args, *(["--limit", limit] if limit else [])
            )
            info = ((summary or {}).get("markets") or {}).get(market) or {}
            if not path.exists():
                self.problem(f"{market} universe {as_of}: {info.get('error') or error}")
                continue
            self.note(f"{market} universe {as_of}: {info.get('counts')}")
        built = {
            m: d
            for m, d in days.items()
            if universe.part_path(m, d, limit, gate=True).exists()
        }
        if not built:
            return
        flags = [x for m, d in built.items() for x in (f"--as-of-{m.lower()}", d)]
        code, summary, error = self.cli(
            "universe-merge",
            *flags,
            "--only",
            "--gate",
            *(["--limit", limit] if limit else []),
        )
        merged = (summary or {}).get("file")
        if not merged:
            self.problem(f"merge {built}: {error}")
            return
        self.collect("--universe", merged, "--gate", "--markets", *built)
        for market, as_of in built.items():
            report = ["coverage", "--as-of", as_of, "--gate", "--offline"]
            code, summary, error = self.cli(
                *report, "--universe", merged, "--markets", market
            )
            entry = ((summary or {}).get("markets") or {}).get(market)
            if not entry:
                self.problem(f"{market} coverage {as_of}: {error}")
                continue
            keys = (
                "verdict",
                "rate",
                "withTwoSignals",
                "nonFinancial",
                "noCloseOnAsOf",
            )
            self.note(f"{market} {as_of}: {({k: entry.get(k) for k in keys})}")
            why = self.source_failure(market, entry)
            if why:
                self.problem(f"{market} {as_of}: looks like a source failure: {why}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="ratings_ops.py", description=__doc__.split("\n")[0]
    )
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("operate", help="do what is due now (scheduled runs)")
    c.add_argument("--push", action="store_true", help="commit and push results")
    c.add_argument("--evaluate", action="store_true", help="official evaluation too")
    c.add_argument("--prune", action="store_true", help="trim the Actions cache")
    c = sub.add_parser("rehearse", help="exercise the pipeline without recording")
    c.add_argument("--as-of-us", help="default: SSGA's holdings date")
    c.add_argument("--as-of-kr", help="default: the last KR session with closes out")
    c.add_argument("--limit", type=int, help="a smoke universe of the first N")
    args = p.parse_args(argv)
    ops = Ops(push=getattr(args, "push", False))
    try:
        if args.command == "operate":
            ops.operate(args.evaluate)
            if args.prune:
                ops.prune()
        else:
            ops.rehearse(dict(US=args.as_of_us, KR=args.as_of_kr), args.limit)
    except (OpsError, common.FetchError, ValueError, OSError) as exc:
        ops.problem(f"{type(exc).__name__}: {exc}")
    except subprocess.CalledProcessError as exc:
        ops.problem(f"git {exc.cmd[1:]}: {(exc.stderr or '').strip()[-300:]}")
    print(json.dumps(ops.report(), ensure_ascii=False, indent=1))
    return 1 if ops.problems else 0


if __name__ == "__main__":
    sys.exit(main())
