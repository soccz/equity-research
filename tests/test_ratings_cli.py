"""scripts/ratings.py offline: fakes replace the downloads; data/ratings is a temp folder.

The clock is fixed (CLOCK: two days after T = 2026-09-30, inside the registration
window) for the CLI, the registry and the ledger. IntegrationTests replays real trimmed
originals (the fundamentals and prices fixtures, read-only) through the real modules:
universe file -> collect -> score -> coverage.
"""

import contextlib
from datetime import date, datetime, time, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from equitylab import ledger
from equitylab.data import ROOT, canonical, digest
from ratings import (
    common,
    evaluate,
    fundamentals,
    prices,
    rating,
    registry,
    sectors,
    universe,
)

spec = importlib.util.spec_from_file_location(
    "ratings_cli", ROOT / "scripts/ratings.py"
)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

AS_OF = "2026-09-30"  # a Wednesday: the month's last session
# 12:00 UTC on Fri Oct 2 is 08:00 in New York and 21:00 in Seoul: after T's closes and
# one session (Oct 1) into the five-session registration window.
CLOCK = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
THROUGH = "2026-10-16"
# Evaluations run the morning after THROUGH, when its closes have settled.
EVALUATED = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
FIXTURES = ROOT / "tests/fixtures/ratings"
KSIC = digest(sectors.KSIC_REFERENCE.read_bytes())
# D5': Korea captured at 19:00 KST on T, the US at 09:00 New York on Thu Oct 1 (SSGA
# posts T's holdings on the next US business day).
CAPTURED = dict(US="2026-10-01T13:00:00+00:00", KR="2026-09-30T10:00:00+00:00")
GATE_AS_OF = "2026-10-19"  # PROTOCOL decisions.computabilityCheck.asOf (a Monday)


def manifest(key: str, retrieved="2026-10-01T08:00:00+00:00", provider="test") -> dict:
    return dict(
        key=key,
        url=f"https://example.invalid/{key}",
        sha256=digest(key.encode()),
        file=f"data/ratings/sources/{key}.json",
        bytes=1,
        provider=provider,
        retrievedAt=retrieved,
    )


def us_member(rank, status="eligible", reason=None, sector="BusEq") -> dict:
    cik = f"{rank:010d}"
    return dict(
        id=f"US:{cik}",
        market="US",
        name=f"US {rank}",
        ticker=f"U{rank}",
        priceSymbol=f"U{rank}",
        cik=cik,
        sic="3571",
        sector=sector,
        fiscalYearEnd="1231",
        shareClasses=[dict(ticker=f"U{rank}", priceSymbol=f"U{rank}", kind="common")],
        weight=10.0 / rank,
        rank=rank,
        status=status,
        reason=reason,
        error=None,
    )


def kr_member(rank, status="eligible", reason=None, preferred=False) -> dict:
    code = f"{rank:05d}0"
    classes = [
        dict(ticker=code, priceSymbol=f"{code}.KS", kind="common", listedShares=10**6)
    ]
    if preferred:
        other = code[:5] + "5"
        classes.append(
            dict(
                ticker=other,
                priceSymbol=f"{other}.KS",
                kind="preferred",
                listedShares=10**5,
            )
        )
    return dict(
        id=f"KR:{code}",
        market="KR",
        name=f"KR {rank}",
        ticker=code,
        priceSymbol=f"{code}.KS",
        corpCode=f"{rank:08d}",
        ksic="26410",
        sector="Money" if status == "excluded" else "BusEq",
        fiscalYearEnd="1231",
        shareClasses=classes,
        rank=rank,
        status=status,
        reason=reason,
        error=None,
    )


def fake_part(
    market: str, members: list, as_of=AS_OF, captured=None, online=True
) -> dict:
    """One market's own build, built online (M2; ``online`` False: replayed offline)
    and captured after its close of T (D5')."""
    captured = captured or CAPTURED[market]
    rules = json.loads(json.dumps(universe.RULES))
    if market == "US":
        info = dict(holdingsAsOf=as_of, ff12Hash=sectors.FF12_DEFINITION_SHA256)
        sources = [manifest("ssga-spy-holdings", captured, "SSGA")]
    else:
        info = dict(rankingBasis="T_close")
        sources = [
            manifest("naver-kospi-marketvalue-p1", captured, "Naver Finance"),
            manifest("yahoo-000010.KS", captured, "Yahoo Finance"),
            dict(manifest("ksic-ff12"), sha256=KSIC),
        ]
    return dict(
        version="ratings-v1",
        asOf=as_of,
        asOfByMarket={market: as_of},
        builtAt=captured,
        completedAt=captured,
        status="ok",
        rules=rules,
        rulesHash=digest(canonical(rules)),
        markets={
            market: dict(status="ok", error=None, asOf=as_of, online=online, **info)
        },
        sources=sources,
        members=members,
    )


def fake_universe(us=6, kr=4, limit=None, as_of=AS_OF, captured=None) -> dict:
    """The month's merged universe: each market fixed at its own T after its close,
    with the pinned rules and sector references."""
    captured = captured or CAPTURED
    members = [us_member(r) for r in range(1, us + 1)]
    members.append(us_member(us + 1, "excluded", "financial_sic", "Money"))
    korean = [kr_member(r, preferred=r == 1) for r in range(1, kr + 1)]
    korean.append(kr_member(kr + 1, "excluded", "financial_ksic"))
    built = registry.merge_universe(
        dict(
            US=fake_part("US", members, as_of, captured["US"]),
            KR=fake_part("KR", korean, as_of, captured["KR"]),
        ),
        now=max(captured.values()),
    )
    if limit is not None:
        built["limit"] = limit
    return built


def weekdays(through: str, n: int = 300) -> list:
    out, day = [], date.fromisoformat(through)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day -= timedelta(days=1)
    return out[::-1]


def chart(symbol: str, rows: list, zone: str, currency: str) -> bytes:
    """A Yahoo chart original that prices._parse turns back into ``rows``."""
    stamps = [
        int(
            datetime.combine(
                date.fromisoformat(d), time(10), ZoneInfo(zone)
            ).timestamp()
        )
        for d, _, _ in rows
    ]
    result = dict(
        meta=dict(symbol=symbol, exchangeTimezoneName=zone, currency=currency),
        timestamp=stamps,
        indicators=dict(
            quote=[dict(close=[r[2] for r in rows])],
            adjclose=[dict(adjclose=[r[1] for r in rows])],
        ),
        events={},
    )
    return json.dumps(dict(chart=dict(result=[result], error=None))).encode()


class Fakes:
    """Stand-ins for fundamentals.collect and prices.series with chosen failures.

    ``gap`` symbols lack a close on T; ``thin`` members have no cash-flow facts (one
    signal); ``start`` maps symbols to the first session they still return (a reset
    history); ``scale`` multiplies a symbol's closes. Series are retrieved at the CLI's
    clock and stored as Yahoo chart originals; ``late`` symbols are retrieved a day
    after their window ends (a collect that crossed local midnight).
    """

    def __init__(
        self,
        fail=(),
        boom=(),
        price_fail=(),
        gap=(),
        thin=(),
        start=None,
        scale=None,
        late=(),
    ):
        self.fail, self.boom, self.price_fail = set(fail), set(boom), set(price_fail)
        self.gap, self.thin, self.late = set(gap), set(thin), set(late)
        self.start, self.scale = dict(start or {}), dict(scale or {})
        self.calls = []

    def collect(self, member, as_of, online=True):
        self.calls.append(("collect", member["id"]))
        if member["id"] in self.boom:
            raise RuntimeError("boom")
        us, rank = member["market"] == "US", member["rank"]
        record = dict(
            id=member["id"],
            market=member["market"],
            asOf=as_of,
            status="ok",
            error=None,
            missing=[],
            currency="USD" if us else "KRW",
            cfoTTM=100.0 * rank,
            capexTTM=10.0 * rank,
            assets=1000.0 + 37 * rank**2,
            shares=1000.0 if us else None,
            sharesBasis="cover" if us else None,
            sharesAsOf="2026-07-20" if us else None,
            listedShares=None,
            periodEnd="2026-06-30",
            filedAt="2026-08-14",
            method="ytd",
            filings=[dict(filedAt="2026-08-14")],
            sources=[manifest(f"facts-{member['id'].replace(':', '-')}")],
            notes=[],
        )
        if member["id"] in self.fail:
            record.update(
                status="error",
                error=f"SEC: HTTP 404 for sec-facts-CIK{member.get('cik')}",
                cfoTTM=None,
                capexTTM=None,
                assets=None,
                shares=None,
                filedAt=None,
                filings=[],
            )
        if member["id"] in self.thin:
            record.update(status="insufficient", cfoTTM=None, capexTTM=None)
        return record

    def series(self, symbol, through, online=True, *, start=None):
        self.calls.append(("series", symbol, through, start))
        if symbol in self.price_fail:
            return dict(
                symbol=symbol,
                status="error",
                error=f"query2: Yahoo Finance: HTTP 404 for yahoo-{symbol}-{through}",
                rows=[],
                source=None,
                splits=[],
                notes=[],
            )
        step = 0.01 * (sum(map(ord, symbol)) % 7 + 1)
        first, end = (d.isoformat() for d in prices._window(through, start))
        factor = self.scale.get(symbol, 1.0)
        rows = [
            [d, (50.0 + i * step) * factor, (50.0 + i * step) * factor]
            for i, d in enumerate(weekdays(through))
            if first <= d
            and not (symbol in self.gap and d == AS_OF)
            and d >= self.start.get(symbol, "")
        ]
        korean = symbol.endswith((".KS", ".KQ"))
        zone = "Asia/Seoul" if korean else "America/New_York"
        currency = "KRW" if korean else "USD"
        key = prices.source_key(symbol, through, start)
        blob = chart(symbol, rows, zone, currency)
        stored = common.store(blob, key, "fake:", "test", ".json")
        retrieved = cli.clock() + timedelta(days=1 if symbol in self.late else 0)
        return dict(
            symbol=symbol,
            status="ok",
            error=None,
            rows=rows,
            source=dict(stored, retrievedAt=retrieved.isoformat()),
            currency=currency,
            timezone=zone,
            window={"from": first, "through": end},
            splits=[],
            notes=[],
        )

    def patch(self):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(fundamentals, "collect", self.collect))
        stack.enter_context(mock.patch.object(prices, "series", self.series))
        return stack

    def collected(self) -> list:
        return [c[1] for c in self.calls if c[0] == "collect"]


class Store(unittest.TestCase):
    """Every data/ratings path of the CLI and the modules points into a temp folder;
    the CLI, the registry and the ledger share one fixed clock."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()  # 22tb is a symlink; ROOT is resolved
        data = self.root / "data/ratings"
        self.clock = CLOCK
        test = self

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return test.clock if tz is None else test.clock.astimezone(tz)

        self.Clock = Clock
        for target, name, value in (
            (common, "ROOT", self.root),
            (cli, "ROOT", self.root),
            (common, "SOURCES", data / "sources"),
            (universe, "UNIVERSE_DIR", data / "universe"),
            (registry, "REGISTRATIONS", data / "v1"),
            (registry, "LEDGER", data / "ledger.jsonl"),
            (registry, "DRY_RUNS", data / "dry-run"),
            (registry, "_clock", lambda: self.clock),
            (ledger, "datetime", Clock),
            (cli, "clock", lambda: self.clock),
            (cli, "WORK", data / "work"),
            (cli, "EVALUATIONS", data / "evaluation"),
            (cli, "SERIES", data / "series"),
            (cli, "PERIODS", data / "periods"),
            (cli, "FORWARD_CHECKS", data / "forward-check"),
            (os, "fsync", lambda fd: None),  # durability is not under test; slow disk
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(
            os.environ,
            SEC_USER_AGENT="ratings-test test@example.invalid",
            DART_API_KEY="test-key-never-sent",
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data = data

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([str(a) for a in argv])
        text = out.getvalue().strip()
        return code, json.loads(text) if text else None, err.getvalue()

    def save_universe(self, built, name=AS_OF) -> Path:
        path = self.data / f"universe/{name}.json"
        common.write_json(path, built)
        return path

    def save_gate_universe(
        self, as_of=AS_OF, captured=None, offline=(), overwrite=False, **sizes
    ) -> dict:
        """H1: the computability-check universe as 'universe --gate' saves it: each
        market's part in <T>-gate/ (universe.save), merged into <asOf>-gate.json;
        ``offline`` markets were built offline (M2)."""
        captured = captured or CAPTURED
        built = fake_universe(as_of=as_of, captured=captured, **sizes)
        for market in ("US", "KR"):
            members = [m for m in built["members"] if m["market"] == market]
            part = fake_part(
                market, members, as_of, captured[market], online=market not in offline
            )
            universe.save(part, overwrite=overwrite, gate=True)
        return json.loads(universe.merged_path(as_of, gate=True).read_text())

    def lines(self, market, as_of=AS_OF, gate=False) -> list:
        folder = f"{as_of}-gate" if gate else as_of
        path = self.data / f"work/{folder}/{market}.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def collect(self, fakes, *extra, online=False):
        with fakes.patch():
            offline = () if online else ("--offline",)
            return self.run_cli("collect", "--as-of", AS_OF, *offline, *extra)

    def score(self, *extra, fakes=None):
        with (fakes or Fakes()).patch():
            return self.run_cli(
                "score", "--as-of-us", AS_OF, "--as-of-kr", AS_OF, *extra
            )

    def gates(self, US="pass", KR="pass"):
        """Coverage-gate events as registry.record_gate writes them (D10')."""
        for market, verdict in (("US", US), ("KR", KR)):
            ledger.append(
                self.data / "ledger.jsonl",
                dict(
                    eventId=f"ratings-v1:coverage-gate:{market}",
                    type=registry.GATE_TYPE,
                    market=market,
                    asOf=GATE_AS_OF,
                    rate=0.99 if verdict == "pass" else 0.5,
                    threshold=cli.GATE[market],
                    verdict=verdict,
                    universeSha256="0" * 64,
                    protocolHash=rating.PROTOCOL_HASH,
                ),
            )

    def register_month(self) -> Path:
        """A formal registration: full universe collected online, gates passed."""
        self.save_universe(fake_universe())
        self.collect(Fakes(), online=True)
        self.gates()
        code, summary, err = self.score()
        self.assertEqual((code, summary and summary["kind"]), (0, "registration"), err)
        return self.root / summary["file"]


class CollectTests(Store):
    def test_limit_checkpoints_failures_and_reruns(self):
        self.save_universe(fake_universe())
        fakes = Fakes(
            fail={"US:0000000002"}, boom={"KR:000030"}, price_fail={"000015.KS"}
        )
        code, summary, progress = self.collect(fakes, "--limit", "3")
        self.assertEqual(code, 0)
        us, kr = self.lines("US"), self.lines("KR")
        self.assertEqual([r["rank"] for r in us], [1, 2, 3])  # first three by rank
        self.assertEqual([r["status"] for r in us], ["ok", "error", "ok"])
        self.assertIn("fundamentals: SEC: HTTP 404", us[1]["errors"][0])
        # Korea prices every listed class; failures are recorded, never fatal. L5: a
        # preferred class without a series is priced at the common close, so its
        # failure is kept apart and is no checkpoint error.
        self.assertEqual(list(kr[0]["prices"]), ["000010.KS", "000015.KS"])
        self.assertEqual([r["status"] for r in kr], ["ok", "ok", "error"])
        self.assertEqual(
            (kr[0]["errors"], list(kr[0]["classFailures"])), ([], ["000015.KS"])
        )
        self.assertEqual(kr[2]["errors"], ["unexpected RuntimeError: boom"])
        self.assertEqual(summary["markets"]["US"]["state"], {"error": 1, "ok": 2})
        self.assertEqual(summary["markets"]["US"]["eligible"], 6)
        self.assertEqual(summary["markets"]["US"]["elapsedSeconds"]["n"], 3)
        # Five price originals were retrieved now; the stored facts pointers are older.
        self.assertEqual(summary["downloads"], {"test": 5})
        self.assertIn("US 2/3 US:0000000002 U2 error", progress)

        retry = Fakes()
        code, summary, _ = self.collect(retry, "--limit", "3")
        self.assertEqual(code, 0)
        self.assertEqual(retry.collected(), ["US:0000000002", "KR:000030"])
        self.assertEqual(summary["markets"]["US"]["skipped"], {"collected": 2})
        self.assertEqual(summary["markets"]["KR"]["state"], {"ok": 3})
        self.assertEqual(len(self.lines("US")), 4)  # appended, history kept

    def test_skip_failed_and_changed_identity(self):
        self.save_universe(fake_universe())
        self.collect(Fakes(fail={"US:0000000001"}), "--limit", "2", "--markets", "US")
        again = Fakes()
        _, summary, _ = self.collect(
            again, "--limit", "2", "--markets", "US", "--skip-failed"
        )
        self.assertEqual(again.collected(), [])
        self.assertEqual(
            summary["markets"]["US"]["skipped"], {"collected": 1, "failed": 1}
        )
        rebuilt = fake_universe()
        rebuilt["members"][1][
            "priceSymbol"
        ] = "U2X"  # a rebuilt universe voids the record
        self.save_universe(rebuilt)
        again = Fakes()
        self.collect(again, "--limit", "2", "--markets", "US", "--skip-failed")
        self.assertEqual(again.collected(), ["US:0000000002"])

    def test_torn_line_is_isolated(self):
        self.save_universe(fake_universe())
        path = self.data / f"work/{AS_OF}/US.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text('{"id": "US:0000000001", "torn')
        _, summary, _ = self.collect(Fakes(), "--limit", "1", "--markets", "US")
        self.assertEqual(summary["markets"]["US"]["unreadableLines"], 1)
        records, bad = cli.read_checkpoints(path)
        self.assertEqual((list(records), bad), (["US:0000000001"], 1))

    def test_online_run_needs_credentials_before_any_download(self):
        self.save_universe(fake_universe())
        fakes = Fakes()
        with mock.patch.dict(os.environ), fakes.patch():
            os.environ.pop("SEC_USER_AGENT", None)
            code, summary, err = self.run_cli(
                "collect", "--as-of", AS_OF, "--markets", "US"
            )
        self.assertEqual((code, summary, fakes.calls), (2, None, []))
        self.assertIn("SEC_USER_AGENT", err)
        self.assertFalse((self.data / "work").exists())

    def test_month_universe_lookup(self):
        with self.assertRaisesRegex(cli.CliError, "No universe for 2026-09"):
            cli.load_universe(AS_OF)
        self.save_universe(fake_universe(limit=5), f"{AS_OF}-limit5")
        self.assertEqual(cli.universe_file("2026-09-29").name, f"{AS_OF}-limit5.json")
        self.save_universe(fake_universe())
        self.assertEqual(cli.universe_file(AS_OF).name, f"{AS_OF}.json")
        with self.assertRaisesRegex(cli.CliError, "Several universes"):
            cli.universe_file("2026-09-29")
        # H1: the computability-check universe and the month's never stand in for
        # each other.
        with self.assertRaisesRegex(cli.CliError, "No computability-check universe"):
            cli.universe_file(AS_OF, gate=True)
        self.save_universe(fake_universe(), f"{AS_OF}-gate")
        self.assertEqual(cli.universe_file(AS_OF).name, f"{AS_OF}.json")
        self.assertEqual(cli.universe_file(AS_OF, gate=True).name, f"{AS_OF}-gate.json")
        self.assertEqual(
            cli.universe_file("2026-09-29", gate=True).name, f"{AS_OF}-gate.json"
        )
        with self.assertRaises(cli.CliError) as caught:  # the gate file is not one
            cli.universe_file("2026-09-29")
        self.assertIn("Several universes", str(caught.exception))
        self.assertNotIn("-gate", str(caught.exception))
        (self.data / f"universe/{AS_OF}.json").unlink()
        self.assertEqual(cli.universe_file(AS_OF).name, f"{AS_OF}-limit5.json")

    def test_month_lookup_prefers_the_full_merge(self):
        """L4: --month takes the month's single merge without a -limit<N> suffix (a
        smoke build beside it is no ambiguity), and the gate's likewise with --gate;
        a T lookup without its exact file stays ambiguous."""
        self.save_universe(fake_universe(limit=5), f"{AS_OF}-limit5")
        self.assertEqual(cli.universe_file("2026-09").name, f"{AS_OF}-limit5.json")
        self.save_universe(fake_universe())
        self.assertEqual(cli.universe_file("2026-09").name, f"{AS_OF}.json")
        with self.assertRaisesRegex(cli.CliError, "Several universes"):
            cli.universe_file("2026-09-29")
        self.save_universe(fake_universe(limit=3), f"{AS_OF}-gate-limit3")
        self.assertEqual(
            cli.universe_file("2026-09", gate=True).name, f"{AS_OF}-gate-limit3.json"
        )
        self.save_universe(fake_universe(), f"{AS_OF}-gate")
        self.assertEqual(
            cli.universe_file("2026-09", gate=True).name, f"{AS_OF}-gate.json"
        )
        self.assertEqual(cli.universe_file("2026-09").name, f"{AS_OF}.json")
        with Fakes().patch():
            code, summary, err = self.run_cli(
                "collect", "--month", "2026-09", "--markets", "KR", "--offline"
            )
        self.assertEqual(code, 0, err)
        self.assertEqual(summary["universe"], f"data/ratings/universe/{AS_OF}.json")
        # Two full merges of the month stay ambiguous: pass --universe.
        self.save_universe(fake_universe(as_of="2026-09-29"), "2026-09-29")
        with self.assertRaisesRegex(
            cli.CliError, "Several universes .* pass --universe"
        ):
            cli.universe_file("2026-09")

    def test_the_refusal_hint_follows_the_universe_given(self):
        """L4: --as-of that is not every market's T is refused; with --universe the
        hint is to leave out --as-of, never to give --month."""
        days = {"US": "2026-12-31", "KR": "2026-12-30"}
        members = fake_universe()["members"]
        parts = {
            market: fake_part(
                market,
                [m for m in members if m["market"] == market],
                days[market],
                captured,
            )
            for market, captured in (
                ("US", "2027-01-04T14:00:00+00:00"),
                ("KR", "2026-12-30T10:00:00+00:00"),
            )
        }
        december = registry.merge_universe(parts, now="2027-01-04T14:30:00+00:00")
        path = self.save_universe(december, "2026-12-31")
        self.clock = datetime(2027, 1, 4, 15, 0, tzinfo=timezone.utc)
        fakes = Fakes()
        with fakes.patch():
            code, _, err = self.run_cli(
                "collect", "--universe", path, "--as-of", "2026-12-31", "--offline"
            )
        self.assertEqual((code, fakes.calls), (2, []))
        self.assertIn(f"leave out --as-of (--universe {path} alone collects", err)
        self.assertNotIn("--month", err)
        self.assertIn("--as-of 2026-12-30 --markets KR", err)
        with Fakes().patch():
            code, summary, err = self.run_cli(
                "collect", "--universe", path, "--offline"
            )
        self.assertEqual((code, summary["asOfByMarket"]), (0, days), err)

    def test_a_preferred_class_without_a_series_is_priced_at_the_common_close(self):
        """L5: a Korean preferred class whose series fails (here HTTP 404) leaves the
        member's checkpoint ok: the rating prices the class at the common close
        (class_price_proxy) and the class's failure is kept with it; the member
        registers without --allow-errors. A failed common stays a checkpoint error."""
        self.save_universe(fake_universe())
        _, summary, _ = self.collect(Fakes(price_fail={"000015.KS"}), online=True)
        record = {r["id"]: r for r in self.lines("KR")}["KR:000010"]
        self.assertEqual((record["status"], record["errors"]), ("ok", []))
        self.assertEqual(list(record["classFailures"]), ["000015.KS"])
        self.assertIn("HTTP 404", record["classFailures"]["000015.KS"])
        self.assertEqual(summary["markets"]["KR"]["state"], {"ok": 4})
        self.assertEqual(sum(summary["markets"]["KR"]["classFailures"].values()), 1)
        self.gates()
        code, summary, err = self.score()
        self.assertEqual((code, summary and summary["kind"]), (0, "registration"), err)
        self.assertEqual(summary["collection"]["KR"]["errors"], 0)
        rows = json.loads((self.root / summary["file"]).read_text())["rows"]
        row = {r["id"]: r for r in rows}["KR:000010"]
        self.assertIn("class_price_proxy", row["issues"])
        self.assertEqual(list(row["collection"]["classFailures"]), ["000015.KS"])
        proxied = [c for c in row["inputs"]["shareClasses"] if c["priceProxy"]]
        self.assertEqual([c["priceSymbol"] for c in proxied], ["000015.KS"])
        self.assertIsNotNone(row["marketCap"])
        # The common's own series failing is still an error, collected again.
        self.collect(
            Fakes(price_fail={"000010.KS"}), "--refresh", "--markets", "KR", online=True
        )
        record = {r["id"]: r for r in self.lines("KR")}["KR:000010"]
        self.assertEqual(record["status"], "error")
        self.assertTrue(record["errors"][0].startswith("prices 000010.KS: "))
        self.assertEqual(record["classFailures"], {})

    def test_each_market_is_collected_at_its_own_t(self):
        """N8: December's universe holds KR at Dec 30 and the US at Dec 31. collect
        takes each market's T from it (--month), so score finds both collected; an
        --as-of that is not the T of every market collected is refused, not used."""
        days = {"US": "2026-12-31", "KR": "2026-12-30"}
        members = fake_universe()["members"]
        parts = {
            market: fake_part(
                market,
                [m for m in members if m["market"] == market],
                days[market],
                captured,
            )
            for market, captured in (
                ("US", "2027-01-04T14:00:00+00:00"),  # 09:00 New York, Mon Jan 4
                ("KR", "2026-12-30T10:00:00+00:00"),  # 19:00 Seoul on T
            )
        }
        december = registry.merge_universe(parts, now="2027-01-04T14:30:00+00:00")
        self.save_universe(december, "2026-12-31")
        self.clock = datetime(2027, 1, 4, 15, 0, tzinfo=timezone.utc)
        fakes = Fakes()
        with fakes.patch():
            code, _, err = self.run_cli("collect", "--as-of", "2026-12-31", "--offline")
        self.assertEqual((code, fakes.calls), (2, []))
        self.assertIn(
            "--as-of 2026-12-31 is not the T of KR (2026-12-30) in "
            "data/ratings/universe/2026-12-31.json",
            err,
        )
        self.assertIn("give --month 2026-12 instead of --as-of", err)
        self.assertIn("--as-of 2026-12-30 --markets KR", err)
        self.assertFalse((self.data / "work").exists())
        code, _, err = self.run_cli("collect", "--offline")
        self.assertEqual(code, 2)
        self.assertIn("give --month YYYY-MM", err)
        with Fakes().patch():
            code, summary, _ = self.run_cli(
                "collect", "--month", "2026-12", "--offline"
            )
        self.assertEqual((code, summary["asOfByMarket"]), (0, days))
        self.assertEqual({m: summary["markets"][m]["asOf"] for m in days}, days)
        for market, day in days.items():
            lines = self.lines(market, day)
            self.assertEqual({r["asOf"] for r in lines}, {day})
            self.assertEqual(len(lines), 6 if market == "US" else 4)
        self.assertFalse((self.data / "work/2026-12-31/KR.jsonl").exists())
        # --as-of stays for one market at its own T (and for months of one T).
        with Fakes().patch():
            code, summary, _ = self.run_cli(
                "collect", "--as-of", "2026-12-30", "--markets", "KR", "--offline"
            )
        self.assertEqual((code, summary["asOfByMarket"]), (0, {"KR": "2026-12-30"}))
        self.assertEqual(summary["markets"]["KR"]["skipped"], {"collected": 4})
        # score reads every member at its market's T: nothing is "not collected".
        with Fakes().patch():
            code, scored, err = self.run_cli(
                "score",
                "--as-of-us",
                "2026-12-31",
                "--as-of-kr",
                "2026-12-30",
                "--dry-run",
                "--offline",
            )
        self.assertEqual(code, 0, err)
        self.assertEqual(
            {m: scored["collection"][m]["notCollected"] for m in days},
            {"US": 0, "KR": 0},
        )

    def test_a_kr_series_read_before_the_share_capture_is_collected_again(self):
        """N6: Korea's part was rebuilt (shares captured Oct 3) after its members were
        collected (series retrieved Oct 2): their market caps are withheld
        (capture_after_retrieval), never kept with a flag, and collect gathers them
        again, which clears it."""
        self.save_universe(fake_universe(us=1, kr=2))
        self.collect(Fakes(), "--markets", "KR", online=True)  # Oct 2, 21:00 KST
        later = dict(CAPTURED, KR="2026-10-03T10:00:00+00:00")  # 19:00 KST Oct 3
        self.save_universe(fake_universe(us=1, kr=2, captured=later))
        self.clock = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        _, scored, _ = self.score("--dry-run")
        self.assertEqual(scored["issues"]["KR"].get("capture_after_retrieval"), 2)
        rows = json.loads((self.root / scored["file"]).read_text())["rows"]
        korean = [r for r in rows if r["market"] == "KR" and r["status"] == "eligible"]
        self.assertEqual([r["marketCap"] for r in korean], [None, None])
        again = Fakes()
        _, summary, _ = self.collect(again, "--markets", "KR", online=True)
        self.assertEqual(again.collected(), ["KR:000010", "KR:000020"])
        self.assertEqual(
            summary["markets"]["KR"]["recollected"], {"capture_after_retrieval": 2}
        )
        _, scored, _ = self.score("--dry-run")
        self.assertNotIn("capture_after_retrieval", scored["issues"]["KR"])
        rows = json.loads((self.root / scored["file"]).read_text())["rows"]
        korean = [r for r in rows if r["market"] == "KR" and r["status"] == "eligible"]
        self.assertTrue(all(r["marketCap"] for r in korean))
        quiet = Fakes()
        self.collect(quiet, "--markets", "KR", online=True)
        self.assertEqual(quiet.collected(), [])

    def test_series_run_through_the_retrieval_date(self):
        """D7: closes are split-adjusted to the retrieval date, so the signal series
        are fetched through it (from LOOKBACK_DAYS before T)."""
        self.save_universe(fake_universe())
        fakes = Fakes()
        self.collect(fakes, "--limit", "1", online=True)
        windows = {(c[2], c[3]) for c in fakes.calls if c[0] == "series"}
        self.assertEqual(windows, {("2026-10-02", "2025-08-26")})
        self.assertEqual(cli.window_start(AS_OF), "2025-08-26")
        record = self.lines("US")[0]
        self.assertEqual(
            (record["pricesThrough"], record["online"]), ("2026-10-02", True)
        )

    def test_stale_checkpoints_are_collected_again(self):
        """D9: only checkpoints collected online after T's close with a close on T are
        current; collect re-collects the others (--refresh: all)."""
        self.save_universe(fake_universe(us=2, kr=1))
        self.collect(Fakes())  # offline: usable by dry runs only
        again = Fakes()
        _, summary, _ = self.collect(again, online=True)
        ids = ["US:0000000001", "US:0000000002", "KR:000010"]
        self.assertEqual(again.collected(), ids)
        self.assertEqual(summary["markets"]["US"]["recollected"], {"stale": 2})
        quiet = Fakes()
        self.collect(quiet, online=True)
        self.assertEqual(quiet.collected(), [])
        # 19:00 UTC on Sep 30 is 15:00 in New York (before the close), 04:00 in Seoul.
        self.clock = datetime(2026, 9, 30, 19, 0, tzinfo=timezone.utc)
        early = Fakes()
        _, summary, _ = self.collect(early, "--refresh", online=True)
        self.assertEqual(early.collected(), ids)
        self.clock = CLOCK
        later = Fakes()
        self.collect(later, online=True)
        self.assertEqual(later.collected(), ids[:2])  # Korea had closed at 06:30 UTC
        gap = Fakes(gap={"U1"})
        self.collect(gap, "--refresh", online=True)
        again = Fakes()
        self.collect(again, online=True)
        self.assertEqual(again.collected(), ["US:0000000001"])  # no close on T
        # D11': a checkpoint of another protocol or other code is collected again.
        record = self.lines("US")[-1]
        self.assertEqual(
            (record["protocolHash"], record["codeDigest"]),
            (rating.PROTOCOL_HASH, registry.code_digest()),
        )
        with mock.patch.object(rating, "PROTOCOL_HASH", "0" * 64):
            other = Fakes()
            self.collect(other, online=True)
        self.assertEqual(other.collected(), ids)
        with mock.patch.object(registry, "code_digest", return_value="1" * 64):
            other = Fakes()
            _, summary, _ = self.collect(other, online=True)
        self.assertEqual(other.collected(), ids)
        self.assertEqual(summary["markets"]["KR"]["recollected"], {"stale": 1})


class ScoreTests(Store):
    def test_partial_collection_only_dry_runs_as_a_smoke_test(self):
        built = fake_universe()
        self.save_universe(built)
        self.collect(Fakes(), "--limit", "3")
        code, _, err = self.score()
        self.assertEqual(code, 2)
        self.assertIn("--dry-run", err)
        self.assertFalse((self.data / "v1").exists())
        code, summary, _ = self.score("--dry-run")
        self.assertEqual(code, 0)
        path = self.root / summary["file"]
        self.assertEqual(path, self.data / f"dry-run/{AS_OF}-smoke.json")
        content = registry.read(path)
        self.assertEqual((content["kind"], content["run"]["smoke"]), ("dry-run", True))
        self.assertEqual(content["run"]["collection"]["US"]["notCollected"], 3)
        self.assertEqual(content["run"]["collection"]["US"]["stale"], 3)  # offline
        self.assertIn(
            "US: no coverage gate in the ledger (run coverage)", summary["checks"]
        )
        rows = {r["id"]: r for r in content["rows"]}
        self.assertEqual(set(rows), {m["id"] for m in built["members"]})
        late = rows["US:0000000005"]
        self.assertEqual(
            (late["issues"], late["labelReason"]), (["not_collected"], "insufficient")
        )
        labels = content["labels"]["US"]
        self.assertEqual(
            (labels["scored"], labels["insufficient"], labels["excluded"]), (3, 3, 1)
        )
        keys = {m["key"] for m in content["inputs"]["prices"]}
        self.assertIn("yahoo-U1-2026-10-02-from-2025-08-26", keys)
        self.assertIn(manifest("facts-KR-000010"), content["inputs"]["fundamentals"])
        self.assertFalse((self.data / "ledger.jsonl").exists())

    def test_complete_month_registers_once(self):
        path = self.register_month()
        self.assertEqual(path, self.data / "v1/2026-09.json")
        blob = path.read_bytes()
        events = ledger.read(self.data / "ledger.jsonl")
        self.assertEqual(
            [e["eventId"] for e in events],
            [
                "ratings-v1:coverage-gate:US",
                "ratings-v1:coverage-gate:KR",
                "ratings-v1:2026-09",
            ],
        )
        self.assertEqual(events[-1]["fileSha256"], digest(blob))
        self.assertEqual(events[-1]["recordedAt"], CLOCK.isoformat())
        content = json.loads(blob)
        self.assertEqual(content["labels"]["US"]["computableRate"], 1.0)
        self.assertEqual(content["calendar"]["US"]["sessionsAfterAsOf"], ["2026-10-01"])
        self.assertIn("scripts/ratings.py", content["codeFiles"])
        # D8': the checkpoint files the rows were read from, by SHA-256 and length.
        for market in ("US", "KR"):
            work = self.data / f"work/{AS_OF}/{market}.jsonl"
            self.assertEqual(
                content["checkpoints"][market],
                dict(
                    file=f"data/ratings/work/{AS_OF}/{market}.jsonl",
                    sha256=digest(work.read_bytes()),
                    bytes=len(work.read_bytes()),
                    records=6 if market == "US" else 4,
                    unreadableLines=0,
                ),
            )
        self.assertEqual(
            {
                r["collection"]["stale"] == []
                for r in content["rows"]
                if "collection" in r
            },
            {True},
        )
        code, summary, _ = self.score()  # identical rerun: same file, same event
        self.assertEqual((code, path.read_bytes()), (0, blob))
        self.assertEqual(summary["collection"]["US"]["closeOnAsOf"], 6)
        self.assertEqual(len(ledger.read(self.data / "ledger.jsonl")), 3)
        code, summary, _ = self.score("--dry-run")
        content = json.loads((self.root / summary["file"]).read_text())
        self.assertEqual(Path(summary["file"]).name, f"{AS_OF}.json")
        self.assertFalse(content["run"]["smoke"])
        self.assertEqual(content["issues"], [])

    def test_collection_errors_need_explicit_acceptance(self):
        self.save_universe(fake_universe())
        self.collect(Fakes(fail={"US:0000000003"}), online=True)
        self.gates()
        code, _, err = self.score()
        self.assertEqual(code, 2)
        self.assertIn("--allow-errors", err)
        code, summary, _ = self.score("--allow-errors")
        self.assertEqual(code, 0)
        row = next(
            r
            for r in registry.read(self.root / summary["file"])["rows"]
            if r["id"] == "US:0000000003"
        )
        self.assertEqual(row["collection"]["status"], "error")
        self.assertIn("fundamentals_error", row["issues"])
        self.assertEqual(row["labelReason"], "insufficient")

    def test_interrupted_registration_is_completed_only_by_a_prompt_rerun(self):
        """#1: a file linked without its ledger event keeps its stamp only when the
        same registration is completed within the clock tolerance."""
        self.save_universe(fake_universe())
        self.collect(Fakes(), online=True)
        self.gates()
        with mock.patch.object(ledger, "append", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.score()
        path = self.data / "v1/2026-09.json"
        self.assertTrue(path.exists())
        self.clock = CLOCK + timedelta(minutes=30)
        code, _, err = self.score()
        self.assertEqual(code, 2)
        self.assertIn("no ledger event and is stamped", err)
        self.clock = CLOCK + timedelta(minutes=5)
        code, summary, _ = self.score()
        self.assertEqual((code, summary["kind"]), (0, "registration"))
        event = ledger.read(self.data / "ledger.jsonl")[-1]
        self.assertEqual(
            (event["eventId"], event["registeredAt"]),
            ("ratings-v1:2026-09", CLOCK.isoformat()),
        )

    def test_offline_or_early_checkpoints_never_register(self):
        """D9: offline or pre-close checkpoints back dry runs only; a missing close on T
        is a recorded failure that needs --allow-errors."""
        self.save_universe(fake_universe())
        self.gates()
        self.collect(Fakes())
        code, _, err = self.score()
        self.assertEqual(code, 2)
        self.assertIn("offline or before T's close", err)
        code, summary, _ = self.score("--dry-run")
        self.assertEqual((code, summary["kind"]), (0, "dry-run"))
        self.collect(Fakes(gap={"U2"}), online=True)
        code, _, err = self.score()
        self.assertEqual(code, 2)
        self.assertIn("no close on asOf {'US': 1}", err)
        code, summary, _ = self.score("--allow-errors")
        self.assertEqual((code, summary["kind"]), (0, "registration"))
        self.assertEqual(summary["collection"]["US"]["noCloseOnAsOf"], 1)
        # D9': a halt is not staleness; the registry would refuse a stale row.
        row = next(
            r
            for r in registry.read(self.root / summary["file"])["rows"]
            if r["id"] == "US:0000000002"
        )
        self.assertEqual(
            (row["collection"]["stale"], row["collection"]["closeOnAsOf"]), ([], False)
        )
        # ... and it gets no price-based signal, never an earlier close.
        self.assertIn("no_price_on_as_of", row["issues"])
        self.assertEqual(
            (row["signals"]["momentum12_1"], row["signals"]["fcfYield"]), (None, None)
        )

    def test_checkpoints_read_before_the_kr_share_capture_never_register(self):
        """L1: Korea's part rebuilt (shares captured Oct 3) after its members were
        collected (Oct 2): their checkpoints are stale (capture_after_retrieval), so a
        registration refuses them even with --allow-errors until collect gathers them
        again."""
        self.save_universe(fake_universe())
        self.collect(Fakes(), online=True)  # Oct 2, 21:00 KST
        later = dict(CAPTURED, KR="2026-10-03T10:00:00+00:00")  # 19:00 KST Oct 3
        self.save_universe(fake_universe(captured=later))
        self.clock = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        self.gates()
        code, _, err = self.score("--allow-errors")
        self.assertEqual(code, 2)
        self.assertIn("before the universe's share capture", err)
        self.assertIn("{'KR': 4}", err)
        code, summary, _ = self.score("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(
            {m: summary["collection"][m]["stale"] for m in ("US", "KR")},
            {"US": 0, "KR": 4},
        )
        content = json.loads((self.root / summary["file"]).read_text())
        stale = {
            r["id"]: r["collection"]["stale"]
            for r in content["rows"]
            if "collection" in r
        }
        self.assertEqual(
            {i: v for i, v in stale.items() if i.startswith("KR:")},
            {f"KR:{k:05d}0": ["capture_after_retrieval"] for k in range(1, 5)},
        )
        self.assertTrue(any("stale checkpoints" in i for i in content["issues"]))
        again = Fakes()
        _, summary, _ = self.collect(again, online=True)
        self.assertEqual(
            summary["markets"]["KR"]["recollected"], {"capture_after_retrieval": 4}
        )
        self.assertEqual(again.collected(), [f"KR:{k:05d}0" for k in range(1, 5)])
        code, summary, err = self.score()
        self.assertEqual((code, summary and summary["kind"]), (0, "registration"), err)

    def test_checkpoints_of_other_code_never_register(self):
        """D9', D11': --allow-errors never accepts a stale checkpoint, and checkpoints
        collected by other code are stale."""
        self.save_universe(fake_universe())
        self.collect(Fakes(), online=True)
        self.gates()
        with mock.patch.object(registry, "code_digest", return_value="0" * 64):
            code, _, err = self.score("--allow-errors")
            self.assertEqual(code, 2)
            self.assertIn("under another protocol or code {'US': 6, 'KR': 4}", err)
            code, summary, _ = self.score("--dry-run")
        self.assertEqual(code, 0)
        content = json.loads((self.root / summary["file"]).read_text())
        stale = {
            r["id"]: r["collection"]["stale"]
            for r in content["rows"]
            if "collection" in r
        }
        self.assertEqual(set(map(tuple, stale.values())), {("code_changed",)})
        self.assertTrue(any("stale checkpoints" in i for i in content["issues"]))
        self.assertFalse((self.data / "v1").exists())

    def test_signals_get_split_events_and_the_retrieval_date(self):
        """D7, D7', L4: the CLI passes split events, the retrieval date, each series'
        window and the KR listed shares' capture date to rating.signals."""
        self.save_universe(fake_universe(us=2, kr=1))
        self.collect(Fakes(), online=True)
        seen, original = {}, rating.signals

        def spy(member, facts, series, as_of, **kwargs):
            seen[member["id"]] = kwargs
            return original(member, facts, series, as_of, **kwargs)

        with mock.patch.object(rating, "signals", side_effect=spy):
            self.assertEqual(self.score("--dry-run")[0], 0)
        window = {"from": "2025-08-26", "through": "2026-10-02"}
        # Korea was captured at 19:00 KST on T (CAPTURED), after the KRX close.
        captured = {"KR": AS_OF}
        self.assertEqual(
            seen["US:0000000001"],
            dict(
                splits_by_symbol={"U1": []},
                retrieved_on="2026-10-02",
                windows_by_symbol={"U1": window},
                capture_dates_by_market=captured,
            ),
        )
        self.assertEqual(
            seen["KR:000010"],
            dict(
                splits_by_symbol={"000010.KS": [], "000015.KS": []},
                retrieved_on="2026-10-02",
                windows_by_symbol={"000010.KS": window, "000015.KS": window},
                capture_dates_by_market=captured,
            ),
        )

    def test_a_window_ending_before_its_retrieval_withholds_the_us_cap(self):
        """M2: a collect that crossed local midnight retrieved U1 on Oct 3 with a window
        through Oct 2, so a split on Oct 3 would be unseen: no market cap (D7')."""
        self.save_universe(fake_universe(us=2, kr=1))
        self.collect(Fakes(late={"U1", "000010.KS"}), online=True)
        code, summary, _ = self.score("--dry-run")
        self.assertEqual(code, 0)
        rows = {r["id"]: r for r in registry.read(self.root / summary["file"])["rows"]}
        late, fine = rows["US:0000000001"], rows["US:0000000002"]
        self.assertEqual((late["marketCap"], late["signals"]["fcfYield"]), (None, None))
        self.assertIn("splits_unknown", late["issues"])
        self.assertEqual(late["inputs"]["windowThrough"], "2026-10-02")
        self.assertIsNotNone(fine["marketCap"])
        self.assertNotIn("splits_unknown", fine["issues"])
        self.assertIn("splits_unchecked", rows["KR:000010"]["issues"])

    def test_t_and_the_window_are_checked_on_the_benchmark(self):
        """D3: the benchmark series fetched for the registration must show T as the
        month's last session and the registration inside its five-session window."""
        self.save_universe(fake_universe())
        self.collect(Fakes(), online=True)
        self.gates()
        code, _, err = self.score(fakes=Fakes(price_fail={"^SP500TR"}))
        self.assertEqual(code, 2)
        self.assertIn("no ^SP500TR series", err)
        code, _, err = self.score("--offline")
        self.assertEqual(code, 2)
        self.assertIn("checks T against the benchmark online", err)
        self.clock = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        code, _, err = self.score()
        self.assertEqual(code, 2)
        self.assertIn("window closed on 2026-10-07", err)
        self.clock = CLOCK
        self.assertEqual(self.score()[0], 0)

    def test_failed_korean_gate_leaves_korea_out(self):
        """D10: KR below its threshold leaves v1; the registration covers the US."""
        self.save_universe(fake_universe())
        self.collect(Fakes(), online=True)
        code, _, err = self.score()
        self.assertEqual(code, 2)
        self.assertIn("no coverage gate", err)
        self.gates(US="pass", KR="fail")
        code, summary, _ = self.score()
        self.assertEqual(code, 0)
        self.assertEqual(
            (summary["asOf"], list(summary["leftOut"])), ({"US": AS_OF}, ["KR"])
        )
        content = registry.read(self.data / "v1/2026-09.json")
        self.assertEqual({r["market"] for r in content["rows"]}, {"US"})

    def test_failed_us_gate_blocks_registration(self):
        self.save_universe(fake_universe())
        self.collect(Fakes(), online=True)
        self.gates(US="fail", KR="pass")
        code, _, err = self.score()
        self.assertEqual(code, 2)
        self.assertIn("US coverage gate failed", err)
        self.assertFalse((self.data / "v1").exists())

    def test_unprofiled_members_are_rated_without_collection(self):
        """D6: a universe_fetch_error member stays eligible, is not collected and is
        rated insufficient; it does not make the collection partial."""
        built = fake_universe(us=20)
        built["members"][4].update(issues=["universe_fetch_error"], fetchError="sec")
        self.save_universe(built)
        fakes = Fakes()
        self.collect(fakes, online=True)
        self.assertNotIn("US:0000000005", fakes.collected())
        self.gates()
        code, summary, err = self.score()
        self.assertEqual((code, summary and summary["kind"]), (0, "registration"), err)
        stats = summary["collection"]["US"]
        self.assertEqual((stats["fetchErrors"], stats["notCollected"]), (1, 0))
        row = next(
            r
            for r in registry.read(self.root / summary["file"])["rows"]
            if r["id"] == "US:0000000005"
        )
        self.assertEqual(row["labelReason"], "insufficient")
        # L6: why it has no signal, never the halt or price codes of an empty row.
        self.assertEqual(row["issues"], ["universe_fetch_error", "not_collected"])
        labels = summary["labels"]["US"]
        self.assertEqual((labels["nonFinancial"], labels["scored"]), (20, 19))

    def test_limited_universe_and_wrong_as_of_cannot_register(self):
        self.save_universe(fake_universe(limit=5), f"{AS_OF}-limit5")
        self.collect(Fakes())
        code, _, err = self.score()
        self.assertEqual(code, 2)
        code, summary, _ = self.score("--dry-run")
        self.assertEqual((code, summary["smoke"]), (0, True))
        with self.assertRaisesRegex(ValueError, "limited"):
            registry.register(
                {"US": AS_OF}, fake_universe(limit=5), [], [], dry_run=False
            )
        code, _, err = self.run_cli(
            "score", "--as-of-us", AS_OF, "--as-of-kr", "2026-10-01", "--dry-run"
        )
        self.assertEqual(code, 2)
        self.assertIn("one month", err)

    def test_registry_run_field_is_for_dry_runs(self):
        built = fake_universe()
        rows = [rating.signals(m, None, {}, AS_OF) for m in built["members"]]
        rated = rating.score(rows)
        with self.assertRaisesRegex(ValueError, "dry runs only"):
            registry.register({"US": AS_OF, "KR": AS_OF}, built, rated, [], run={})
        path = registry.register(
            {"US": AS_OF, "KR": AS_OF},
            built,
            rated,
            [],
            dry_run=True,
            run=dict(tag="t1"),
        )
        self.assertEqual(path.name, f"{AS_OF}-t1.json")
        self.assertEqual(json.loads(path.read_text())["run"], {"tag": "t1"})
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            registry.register(
                {"US": AS_OF, "KR": AS_OF},
                built,
                rated,
                [],
                dry_run=True,
                run=dict(tag="../x"),
            )


class CoverageTests(Store):
    """§7 on the computability-check universe (H1: <asOf>-gate.json, collected into
    work/<asOf>-gate/); a rehearsal at any other asOf records nothing."""

    def gate_universe(self, built=None):
        self.save_universe(built or fake_universe(), f"{AS_OF}-gate")

    def coverage(self, *extra):
        return self.run_cli("coverage", "--as-of", AS_OF, "--gate", *extra)

    def test_gate_counts_two_signals_over_every_non_financial_member(self):
        self.gate_universe()
        self.collect(Fakes(thin={"US:0000000001"}), "--gate", online=True)
        code, result, _ = self.coverage()
        self.assertEqual(code, 0)
        self.assertEqual(result["universe"], f"data/ratings/universe/{AS_OF}-gate.json")
        us, kr = result["markets"]["US"], result["markets"]["KR"]
        self.assertEqual(
            (us["nonFinancial"], us["withTwoSignals"], us["labelled"]), (6, 5, 5)
        )
        self.assertAlmostEqual(us["rate"], 5 / 6)
        self.assertEqual((us["threshold"], us["verdict"]), (0.9, "fail"))
        self.assertEqual((kr["rate"], kr["verdict"]), (1.0, "pass"))
        self.assertEqual(us["signalsAvailable"]["momentum12_1"], 6)
        self.assertEqual(us["issues"]["fundamentals_insufficient"], 1)
        saved = json.loads((self.data / f"work/{AS_OF}-gate/coverage.json").read_text())
        self.assertEqual(saved["markets"]["US"]["verdict"], "fail")
        # Only the pinned asOf can set the gate: any other month is a rehearsal.
        self.assertEqual(
            us["gate"]["reason"], f"rehearsal: the gate is computed at {GATE_AS_OF}"
        )
        # D10': a collection error is no verdict at all (retry), never a final fail.
        self.collect(Fakes(fail={"US:0000000002"}), "--gate", "--refresh", online=True)
        _, result, _ = self.coverage()
        us = result["markets"]["US"]
        self.assertEqual((us["collectionErrors"], us["verdict"]), (1, "incomplete"))

    def test_coverage_runs_on_the_gate_universe_only(self):
        """H1: coverage needs --gate and reads the gate universe and its checkpoints,
        never the month's universe or the month's checkpoints."""
        self.save_universe(fake_universe())
        self.collect(Fakes(), online=True)
        code, _, err = self.run_cli("coverage", "--as-of", AS_OF)
        self.assertEqual(code, 2)
        self.assertIn("computability-check universe only", err)
        code, _, err = self.coverage()
        self.assertEqual(code, 2)
        self.assertIn("No computability-check universe for 2026-09", err)
        self.gate_universe()
        _, result, _ = self.coverage()  # the month's checkpoints do not count
        self.assertEqual(result["markets"]["US"]["notCollected"], 6)
        self.collect(Fakes(), "--gate", online=True)
        _, result, _ = self.coverage()
        self.assertEqual(
            (result["markets"]["US"]["notCollected"], result["markets"]["US"]["rate"]),
            (0, 1.0),
        )
        self.assertEqual(len(self.lines("US", gate=True)), 6)
        self.assertEqual(len(self.lines("US")), 6)  # the month's file is untouched

    def test_partial_or_offline_collection_is_incomplete_not_failed(self):
        self.gate_universe()
        self.collect(Fakes(), "--gate", "--limit", "2", online=True)
        _, result, _ = self.coverage("--markets", "US")
        us = result["markets"]["US"]
        self.assertEqual(list(result["markets"]), ["US"])
        self.assertEqual(
            (us["collected"], us["notCollected"], us["verdict"]), (2, 4, "incomplete")
        )
        self.assertAlmostEqual(
            us["rate"], 2 / 6
        )  # the uncollected count as not computable
        self.assertEqual(us["rateCollected"], 1.0)
        self.collect(Fakes(), "--gate")  # offline: complete, but no verdict
        _, result, _ = self.coverage("--markets", "US")
        us = result["markets"]["US"]
        self.assertEqual(
            (us["notCollected"], us["stale"], us["verdict"]), (0, 4, "incomplete")
        )

    def test_denominator_is_every_non_financial_member(self):
        """D6: profile failures and any non-financial exclusion stay in the
        denominator as not computable."""
        built = fake_universe()
        built["members"][5]["issues"] = ["universe_fetch_error"]
        built["members"].append(us_member(9, "excluded", "submissions_unavailable"))
        self.gate_universe(built)
        fakes = Fakes()
        self.collect(fakes, "--gate", online=True)
        self.assertNotIn("US:0000000006", fakes.collected())
        _, result, _ = self.coverage("--markets", "US")
        us = result["markets"]["US"]
        self.assertEqual(
            (us["nonFinancial"], us["eligible"], us["fetchErrors"], us["collected"]),
            (7, 6, 1, 5),
        )
        self.assertEqual((us["withTwoSignals"], us["notCollected"]), (5, 0))
        self.assertAlmostEqual(us["rate"], 5 / 7)
        self.assertEqual(us["verdict"], "fail")
        # L6: the unprofiled member's row names why, not halt or price codes.
        self.assertEqual(us["issues"].get("universe_fetch_error"), 1, us["issues"])
        self.assertNotIn("no_price_on_as_of", us["issues"])


# 12:00 UTC on Tue Oct 20 is 08:00 in New York and 21:00 in Seoul: the check date in
# both markets. Mon Oct 19's universe: Korea captured at 19:00 KST that day, the US at
# 07:00 New York on Oct 20, once SSGA posted Oct 19's holdings.
CHECKED = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
GATE_CAPTURE = dict(US="2026-10-20T11:00:00+00:00", KR="2026-10-19T10:00:00+00:00")


class GateRecordingTests(Store):
    """D10': the gate is recorded once per market, on or after the check date, at the
    pinned asOf, from the computability-check universe (H1) that passes the
    registration checks and a complete collection; the registry computes the verdict
    and the event names what re-verifies it (L1)."""

    def month(self, captured=GATE_CAPTURE) -> dict:
        self.clock = CHECKED
        return self.save_gate_universe(GATE_AS_OF, captured)

    def gather(self, fakes, *extra):
        with fakes.patch():
            return self.run_cli("collect", "--as-of", GATE_AS_OF, "--gate", *extra)

    def coverage(self, *extra):
        with Fakes().patch():
            return self.run_cli("coverage", "--as-of", GATE_AS_OF, "--gate", *extra)

    def gate_events(self) -> list:
        return [
            e
            for e in ledger.read(self.data / "ledger.jsonl")
            if e["type"] == registry.GATE_TYPE
        ]

    def test_gate_is_recorded_once_from_a_complete_collection(self):
        built = self.month()
        self.gather(Fakes(fail={"US:0000000001"}))
        code, result, _ = self.coverage()
        self.assertEqual(code, 0)
        us, kr = result["markets"]["US"], result["markets"]["KR"]
        self.assertEqual((us["verdict"], us["gate"]["recorded"]), ("incomplete", False))
        self.assertIn("incomplete collection", us["gate"]["reason"])
        self.assertIsNone(registry.gate("US"))
        self.assertEqual(
            (kr["gate"]["recorded"], kr["gate"]["event"]["verdict"]), (True, "pass")
        )
        event = registry.gate("KR")
        self.assertEqual(
            (event["asOf"], event["computable"], event["nonFinancial"], event["rate"]),
            (GATE_AS_OF, 4, 4, 1.0),
        )
        self.assertEqual(
            (event["threshold"], event["protocolHash"]), (0.8, rating.PROTOCOL_HASH)
        )
        self.assertEqual(event["universeSha256"], digest(canonical(built)))
        self.assertEqual(
            event["universeFile"], f"data/ratings/universe/{GATE_AS_OF}-gate.json"
        )
        # L1: the merge, its part files and the checkpoint file the counts came from.
        self.assertEqual(event["mergedAt"], built["mergedAt"])
        self.assertEqual(
            event["universeParts"],
            {m: built["markets"][m]["part"] for m in ("US", "KR")},
        )
        part = self.data / f"universe/{GATE_AS_OF}-gate/KR.json"
        self.assertEqual(
            event["universeParts"]["KR"],
            dict(
                file=f"data/ratings/universe/{GATE_AS_OF}-gate/KR.json",
                sha256=digest(part.read_bytes()),
            ),
        )
        work = self.data / f"work/{GATE_AS_OF}-gate/KR.jsonl"
        blob = work.read_bytes()
        self.assertEqual(
            event["checkpoints"],
            dict(
                KR=dict(
                    file=f"data/ratings/work/{GATE_AS_OF}-gate/KR.jsonl",
                    sha256=digest(blob),
                    bytes=len(blob),
                    records=4,
                    unreadableLines=0,
                )
            ),
        )
        # The error is retried; one member now has a single signal: 5 of 6 fails.
        self.gather(Fakes(thin={"US:0000000002"}), "--refresh")
        _, result, _ = self.coverage()
        us = result["markets"]["US"]
        self.assertEqual((us["gate"]["recorded"], us["verdict"]), (True, "fail"))
        self.assertEqual(registry.gate("US")["verdict"], "fail")
        self.assertAlmostEqual(registry.gate("US")["rate"], 5 / 6)
        self.gather(Fakes(), "--refresh")  # fixed afterwards: the verdict is final
        _, result, _ = self.coverage()
        us = result["markets"]["US"]
        self.assertEqual((us["verdict"], us["gate"]["recorded"]), ("pass", False))
        self.assertEqual(us["gate"]["event"]["verdict"], "fail")
        self.assertIn("final", us["gate"]["reason"])
        self.assertEqual(len(self.gate_events()), 2)
        # The checkpoint file only grows: its first bytes still re-verify the gate.
        kept = registry.gate("KR")["checkpoints"]["KR"]
        self.assertGreater(len(work.read_bytes()), kept["bytes"])
        self.assertEqual(digest(work.read_bytes()[: kept["bytes"]]), kept["sha256"])

    def test_rehearsals_and_offline_runs_record_nothing(self):
        self.month()
        # 21:00 UTC on Oct 19 is 17:00 that day in New York but 06:00 on Oct 20 in
        # Seoul: the check date is market-local.
        self.clock = datetime(2026, 10, 19, 21, 0, tzinfo=timezone.utc)
        self.gather(Fakes())
        _, result, _ = self.coverage("--offline")
        for market in ("US", "KR"):
            self.assertFalse(result["markets"][market]["gate"]["recorded"])
        self.assertIn("rehearsal before", result["markets"]["US"]["gate"]["reason"])
        self.assertIn("offline", result["markets"]["KR"]["gate"]["reason"])
        self.assertEqual(self.gate_events(), [])
        _, result, _ = self.coverage()
        self.assertIn("rehearsal before", result["markets"]["US"]["gate"]["reason"])
        self.assertTrue(result["markets"]["KR"]["gate"]["recorded"])
        self.assertEqual([e["market"] for e in self.gate_events()], ["KR"])

    def test_a_universe_failing_the_registration_checks_sets_no_gate(self):
        # The US part was captured at 15:00 New York on T, before the close.
        self.month(dict(GATE_CAPTURE, US="2026-10-19T19:00:00+00:00"))
        self.gather(Fakes())
        code, result, _ = self.coverage()
        self.assertEqual(code, 1)
        us = result["markets"]["US"]["gate"]
        self.assertTrue(us["refused"])
        self.assertIn("not after the 2026-10-19 close", us["reason"])
        self.assertIsNone(registry.gate("US"))
        self.assertTrue(result["markets"]["KR"]["gate"]["recorded"])

    def test_a_part_rebuilt_without_its_merge_sets_no_gate(self):
        """N7: 'universe --gate --overwrite' rewrote the KR part but its re-merge
        failed, so the merged file records the old part's SHA-256: no gate is recorded
        (the event would name a part that is no longer on disk) until universe-merge
        --gate records the part again."""
        self.month()
        self.gather(Fakes())
        part = self.data / f"universe/{GATE_AS_OF}-gate/KR.json"
        rebuilt = json.loads(part.read_text())
        rebuilt["completedAt"] = "2026-10-20T11:05:00+00:00"
        common.write_json(part, rebuilt)
        code, result, _ = self.coverage()
        self.assertEqual(code, 1)
        for market in ("US", "KR"):
            gate = result["markets"][market]["gate"]
            self.assertTrue(gate["refused"], market)
            self.assertIn(
                f"KR: part data/ratings/universe/{GATE_AS_OF}-gate/KR.json on disk",
                gate["reason"],
            )
        self.assertEqual(self.gate_events(), [])
        code, _, _ = self.run_cli("universe-merge", "--as-of", GATE_AS_OF, "--gate")
        self.assertEqual(code, 0)
        code, result, _ = self.coverage()
        self.assertEqual(code, 0)
        self.assertEqual(
            [result["markets"][m]["gate"]["recorded"] for m in ("US", "KR")],
            [True, True],
        )
        event = registry.gate("KR")
        self.assertEqual(
            event["universeParts"]["KR"]["sha256"], digest(part.read_bytes())
        )

    def test_a_gate_part_built_offline_sets_no_gate(self):
        """M2: the KR part of the computability-check universe was replayed offline
        from stored originals: the KR gate is refused; the US part built online sets
        its gate."""
        self.clock = CHECKED
        self.save_gate_universe(GATE_AS_OF, GATE_CAPTURE, offline=("KR",))
        self.gather(Fakes())
        code, result, _ = self.coverage()
        self.assertEqual(code, 1)
        kr = result["markets"]["KR"]["gate"]
        self.assertTrue(kr["refused"])
        self.assertIn("KR: universe part not built online (online False)", kr["reason"])
        self.assertIsNone(registry.gate("KR"))
        self.assertTrue(result["markets"]["US"]["gate"]["recorded"])

    def test_a_kr_capture_after_the_collection_sets_no_gate(self):
        """L1: the gate's KR part rebuilt (shares captured Oct 21) after its members
        were collected (Oct 20): the checkpoints are stale, the verdict incomplete
        and nothing is recorded until collect gathers them again."""
        self.month()
        self.gather(Fakes())
        later = dict(GATE_CAPTURE, KR="2026-10-21T10:00:00+00:00")  # 19:00 KST
        self.clock = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
        self.save_gate_universe(GATE_AS_OF, later, overwrite=True)
        _, result, _ = self.coverage()
        kr = result["markets"]["KR"]
        self.assertEqual((kr["stale"], kr["verdict"]), (4, "incomplete"))
        self.assertFalse(kr["gate"]["recorded"])
        self.assertIsNone(registry.gate("KR"))
        self.gather(Fakes())
        _, result, _ = self.coverage()
        kr = result["markets"]["KR"]
        self.assertEqual((kr["stale"], kr["verdict"]), (0, "pass"))
        self.assertTrue(kr["gate"]["recorded"])

    def test_a_preferred_class_without_a_series_completes_the_gate(self):
        """L5: a preferred class Yahoo lacks is priced at the common close, so its
        member is no collection error and the gate is complete."""
        self.month()
        self.gather(Fakes(price_fail={"000015.KS"}))
        _, result, _ = self.coverage()
        kr = result["markets"]["KR"]
        self.assertEqual((kr["collectionErrors"], kr["verdict"]), (0, "pass"))
        self.assertTrue(kr["gate"]["recorded"])

    def test_checkpoints_of_other_code_are_stale_for_the_gate(self):
        """D11': a checkpoint collected under another code digest is not current."""
        self.month()
        self.gather(Fakes())
        with mock.patch.object(registry, "code_digest", return_value="0" * 64):
            _, result, _ = self.coverage()
        us = result["markets"]["US"]
        self.assertEqual((us["stale"], us["verdict"]), (6, "incomplete"))
        self.assertEqual(self.gate_events(), [])


class UniverseCommandTests(Store):
    def builder(self, failed=(), captured=None):
        """universe.build for one market at a time, as the CLI calls it."""
        calls = []

        def build(as_of, online=True, markets=("US", "KR"), limit=None):
            calls.append(dict(as_of=as_of, markets=tuple(markets), limit=limit))
            (market,) = markets
            members = [us_member(1)] if market == "US" else [kr_member(1)]
            stamps = captured or CAPTURED
            built = fake_part(market, members, as_of, stamps[market])
            if market in failed:
                built.update(status="error")
                built["markets"][market] = dict(status="error", error="FetchError: x")
            if limit is not None:
                built["limit"] = limit
            return built

        return calls, build

    def month(self, name: str) -> dict:
        return json.loads((self.data / f"universe/{name}.json").read_text())

    def test_each_market_is_saved_as_its_own_part(self):
        """D5': Korea is captured on T's evening, the US once SSGA posts T's holdings:
        two builds, two parts, one month file that keeps each market's times."""
        calls, build = self.builder()
        with mock.patch.object(universe, "build", build):
            code, summary, _ = self.run_cli(
                "universe", "--as-of", AS_OF, "--offline", "--markets", "KR"
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                summary["parts"], {"KR": f"data/ratings/universe/{AS_OF}/KR.json"}
            )
            self.assertEqual(
                summary["markets"]["KR"]["capturedAt"]["last"], CAPTURED["KR"]
            )
            self.assertEqual(list(self.month(AS_OF)["markets"]), ["KR"])
            code, _, err = self.run_cli(
                "universe", "--as-of", AS_OF, "--offline", "--markets", "KR"
            )
            self.assertEqual(code, 2)
            self.assertIn("--overwrite", err)
            self.assertEqual(len(calls), 1)  # refused before building again
            code, summary, _ = self.run_cli(
                "universe", "--as-of", AS_OF, "--offline", "--markets", "US"
            )
            self.assertEqual((code, list(summary["parts"])), (0, ["US"]))
            self.assertEqual(summary["file"], f"data/ratings/universe/{AS_OF}.json")
        self.assertEqual([c["markets"] for c in calls], [("KR",), ("US",)])
        merged = self.month(AS_OF)
        self.assertEqual(cli.load_universe(AS_OF)[1], merged)
        us, kr = merged["markets"]["US"], merged["markets"]["KR"]
        self.assertEqual(
            (us["capturedAt"]["first"], kr["capturedAt"]["first"]),
            (CAPTURED["US"], CAPTURED["KR"]),
        )
        part = self.data / f"universe/{AS_OF}/KR.json"
        self.assertEqual(
            kr["part"],
            dict(
                file=f"data/ratings/universe/{AS_OF}/KR.json",
                sha256=digest(part.read_bytes()),
            ),
        )
        self.assertEqual([m["market"] for m in merged["members"]], ["US", "KR"])

    def test_merge_rewrites_the_month_from_its_parts(self):
        _, build = self.builder()
        with mock.patch.object(universe, "build", build):
            self.run_cli("universe", "--as-of", AS_OF, "--offline")
        stamp = self.month(AS_OF)["mergedAt"]
        code, summary, _ = self.run_cli("universe-merge", "--as-of", AS_OF)
        self.assertEqual(code, 0)
        self.assertEqual(summary["file"], f"data/ratings/universe/{AS_OF}.json")
        self.assertEqual(summary["checks"], [])  # the timing preview passes
        self.assertEqual(summary["mergedAt"], stamp)  # same parts: unchanged
        # Korea captured again: the month follows its new part.
        later = dict(CAPTURED, KR="2026-10-01T10:00:00+00:00")
        _, build = self.builder(captured=later)
        with mock.patch.object(universe, "build", build):
            self.run_cli(
                "universe",
                "--as-of",
                AS_OF,
                "--offline",
                "--markets",
                "KR",
                "--overwrite",
            )
        code, summary, _ = self.run_cli("universe-merge", "--as-of", AS_OF)
        self.assertEqual(code, 0)
        self.assertEqual(summary["markets"]["KR"]["capturedAt"]["last"], later["KR"])
        # A preview of the registry's timing check: a US part captured before the
        # close is reported before anything is collected.
        early = dict(CAPTURED, US="2026-09-30T19:00:00+00:00")
        _, build = self.builder(captured=early)
        with mock.patch.object(universe, "build", build):
            self.run_cli(
                "universe",
                "--as-of",
                AS_OF,
                "--offline",
                "--markets",
                "US",
                "--overwrite",
            )
        _, summary, _ = self.run_cli("universe-merge", "--as-of", AS_OF)
        self.assertTrue(any("not after the" in c for c in summary["checks"]))

    def test_merge_previews_a_part_built_offline(self):
        """M2: a part built with --offline replays stored originals; universe-merge
        reports the registration check that refuses it."""
        calls = []

        def build(as_of, online=True, markets=("US", "KR"), limit=None):
            calls.append(online)
            (market,) = markets
            members = [us_member(1)] if market == "US" else [kr_member(1)]
            return fake_part(market, members, as_of, CAPTURED[market], online=online)

        with mock.patch.object(universe, "build", build):
            self.run_cli("universe", "--as-of", AS_OF, "--offline", "--markets", "KR")
            with mock.patch.object(cli, "credentials"):
                self.run_cli("universe", "--as-of", AS_OF, "--markets", "US")
        self.assertEqual(calls, [False, True])
        code, summary, _ = self.run_cli("universe-merge", "--as-of", AS_OF)
        self.assertEqual(code, 0)
        self.assertEqual(
            [c for c in summary["checks"] if "online" in c],
            [
                "KR: universe part not built online (online False): build it again "
                "without --offline ('universe --markets KR', with --gate for the "
                "computability-check universe) and merge it"
            ],
        )
        self.assertIs(self.month(AS_OF)["markets"]["US"]["online"], True)

    def test_failed_builds_limits_and_months_of_two_sessions(self):
        _, build = self.builder(failed={"KR"})
        with mock.patch.object(universe, "build", build):
            code, summary, _ = self.run_cli(
                "universe", "--as-of", "2026-08-31", "--offline"
            )
        self.assertEqual(
            (code, summary["markets"]["KR"]["error"]), (1, "FetchError: x")
        )
        self.assertEqual(list(summary["parts"]), ["US"])  # a failed build is not saved
        self.assertFalse((self.data / "universe/2026-08-31/KR.json").exists())
        self.assertEqual(list(self.month("2026-08-31")["markets"]), ["US"])
        _, build = self.builder()
        with mock.patch.object(universe, "build", build):
            self.run_cli("universe", "--as-of", AS_OF, "--offline", "--limit", "5")
            # December: the KRX closes on Dec 30, New York trades on Dec 31.
            self.run_cli(
                "universe", "--as-of", "2026-12-30", "--offline", "--markets", "KR"
            )
            self.run_cli(
                "universe", "--as-of", "2026-12-31", "--offline", "--markets", "US"
            )
        self.assertEqual(self.month(f"{AS_OF}-limit5")["limit"], 5)
        self.assertFalse((self.data / f"universe/{AS_OF}.json").exists())
        code, summary, _ = self.run_cli(
            "universe-merge", "--as-of", AS_OF, "--limit", "5"
        )
        self.assertEqual(
            (code, Path(summary["file"]).name), (0, f"{AS_OF}-limit5.json")
        )
        merged = self.month("2026-12-31")
        self.assertEqual(
            merged["asOfByMarket"], {"US": "2026-12-31", "KR": "2026-12-30"}
        )
        self.assertFalse((self.data / "universe/2026-12-30.json").exists())
        code, summary, _ = self.run_cli(
            "universe-merge", "--as-of", "2026-12-31", "--as-of-kr", "2026-12-30"
        )
        self.assertEqual(
            (code, summary["file"]), (0, "data/ratings/universe/2026-12-31.json")
        )
        code, _, err = self.run_cli(
            "universe-merge", "--as-of", "2026-12-31", "--as-of-kr", "2026-12-29"
        )
        self.assertEqual(code, 2)
        self.assertIn("No KR universe part for 2026-12-29", err)
        code, _, err = self.run_cli("universe-merge")
        self.assertEqual(code, 2)
        self.assertIn("give --as-of", err)

    def test_the_gate_universe_and_the_months_never_touch_each_other(self):
        """H1: the computability-check universe (Oct 19) is saved apart, so October's
        universe (Oct 30, Korea first) neither merges it in nor deletes it, and
        re-merging the gate universe leaves October's file alone."""
        gate_capture = dict(
            US="2026-10-20T11:00:00+00:00", KR="2026-10-19T10:00:00+00:00"
        )
        _, build = self.builder(captured=gate_capture)
        with mock.patch.object(universe, "build", build):
            code, summary, _ = self.run_cli(
                "universe", "--as-of", GATE_AS_OF, "--offline", "--gate"
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            summary["parts"],
            {
                m: f"data/ratings/universe/{GATE_AS_OF}-gate/{m}.json"
                for m in ("US", "KR")
            },
        )
        self.assertEqual(
            summary["file"], f"data/ratings/universe/{GATE_AS_OF}-gate.json"
        )
        gate = self.month(f"{GATE_AS_OF}-gate")
        self.assertEqual(
            gate["markets"]["US"]["part"]["file"],
            f"data/ratings/universe/{GATE_AS_OF}-gate/US.json",
        )
        october = dict(US="2026-11-02T13:00:00+00:00", KR="2026-10-30T10:00:00+00:00")
        _, build = self.builder(captured=october)
        with mock.patch.object(universe, "build", build):
            code, _, _ = self.run_cli(
                "universe", "--as-of", "2026-10-30", "--offline", "--markets", "KR"
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                self.month("2026-10-30")["asOfByMarket"], {"KR": "2026-10-30"}
            )
            code, _, _ = self.run_cli(
                "universe", "--as-of", "2026-10-30", "--offline", "--markets", "US"
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            self.month("2026-10-30")["asOfByMarket"],
            {"US": "2026-10-30", "KR": "2026-10-30"},
        )
        self.assertEqual(self.month(f"{GATE_AS_OF}-gate"), gate)
        month = self.month("2026-10-30")
        # A gate rebuild (Korea captured again) re-merges the gate file only.
        later = dict(gate_capture, KR="2026-10-20T10:00:00+00:00")
        _, build = self.builder(captured=later)
        with mock.patch.object(universe, "build", build):
            code, _, _ = self.run_cli(
                "universe",
                "--as-of",
                GATE_AS_OF,
                "--offline",
                "--gate",
                "--markets",
                "KR",
                "--overwrite",
            )
        self.assertEqual(code, 0)
        code, summary, _ = self.run_cli(
            "universe-merge", "--as-of", GATE_AS_OF, "--gate"
        )
        self.assertEqual(
            (code, summary["file"], summary["gate"]),
            (0, f"data/ratings/universe/{GATE_AS_OF}-gate.json", True),
        )
        self.assertEqual(summary["markets"]["KR"]["capturedAt"]["last"], later["KR"])
        self.assertEqual(self.month("2026-10-30"), month)
        self.assertEqual(cli.universe_file("2026-10-01").name, "2026-10-30.json")
        self.assertEqual(
            cli.universe_file("2026-10-01", gate=True).name, f"{GATE_AS_OF}-gate.json"
        )

    def test_a_saved_part_whose_month_cannot_merge_is_reported_as_saved(self):
        """H1: save() wrote the part but could not merge the month: 'part saved, month
        not merged' (exit 2), never 'not saved'; universe-merge finishes it."""
        _, build = self.builder()
        with mock.patch.object(universe, "build", build):
            for day in ("2026-08-27", "2026-08-28"):  # two US parts in August
                code, _, _ = self.run_cli(
                    "universe", "--as-of", day, "--offline", "--markets", "US"
                )
                self.assertEqual(code, 0)
            code, summary, err = self.run_cli(
                "universe", "--as-of", "2026-08-31", "--offline", "--markets", "KR"
            )
        self.assertEqual((code, summary), (2, None))
        self.assertIn(
            "KR part saved (data/ratings/universe/2026-08-31/KR.json), month not "
            "merged: ",
            err,
        )
        self.assertIn("Several US universe parts", err)
        self.assertNotIn("not saved", err)
        self.assertTrue((self.data / "universe/2026-08-31/KR.json").exists())
        self.assertFalse((self.data / "universe/2026-08-31.json").exists())
        code, _, _ = self.run_cli(
            "universe-merge", "--as-of", "2026-08-31", "--as-of-us", "2026-08-28"
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            self.month("2026-08-31")["asOfByMarket"],
            {"US": "2026-08-28", "KR": "2026-08-31"},
        )

    def test_online_build_needs_the_dart_key_first(self):
        build = mock.Mock()
        with mock.patch.dict(os.environ), mock.patch.object(universe, "build", build):
            for name in ("DART_API_KEY", "EQUITY_DART_ENV"):
                os.environ.pop(name, None)
            code, _, err = self.run_cli("universe", "--as-of", AS_OF, "--markets", "KR")
        self.assertEqual(code, 2)
        self.assertIn("DART_API_KEY not configured", err)
        build.assert_not_called()

    def test_limit_profiles_only_the_largest_issuers(self):
        import test_ratings_universe as harness  # the universe fixtures, read-only

        sources = harness.Sources()
        patches = mock.patch.multiple(
            universe,
            fetch=sources.fetch,
            fetch_json=sources.fetch_json,
            latest=sources.latest,
            store=sources.store,
            dart_request=sources.dart_request,
            ensure_dart_key=mock.Mock(),
            SPY_MIN_WEIGHT=1.0,
            DART_RETRY_PAUSE=0,
        )
        with patches, mock.patch.object(
            sectors, "fetch", sources.fetch
        ), mock.patch.dict(universe.RULES["KR"], top=10):
            built = universe.build("2026-10-02", online=False, limit=2)
            with self.assertRaises(ValueError):
                universe.build("2026-10-02", online=False, limit=0)
        self.assertEqual(built["limit"], 2)
        us = [m["ticker"] for m in built["members"] if m["market"] == "US"]
        kr = [m["rank"] for m in built["members"] if m["market"] == "KR"]
        self.assertEqual((us, kr), (["NVDA", "AAPL"], [1, 2]))  # largest SPY weights
        profiled = [
            c["key"] for c in sources.calls if c["key"].startswith("sec-submissions")
        ]
        self.assertEqual(len(profiled), 2)
        self.assertEqual(universe.save(built).name, "2026-10-02-limit2.json")


class EvaluationTests(Store):
    def evaluate(self, *extra, fakes=None, offline=False):
        """An evaluation the morning after THROUGH (online unless ``offline``)."""
        self.clock = EVALUATED
        flags = ("--offline",) if offline else ()
        with (fakes or Fakes()).patch():
            return self.run_cli("evaluate", "--through", THROUGH, *flags, *extra)

    def kept(self, symbol: str) -> dict:
        return json.loads((self.data / f"series/yahoo-{symbol}.json").read_text())

    def test_evaluate_without_registrations_writes_nothing(self):
        code, summary, _ = self.run_cli(
            "evaluate", "--through", "2026-10-05", "--offline"
        )
        self.assertEqual((code, summary["status"]), (0, "no_registrations"))
        self.assertFalse((self.data / "evaluation").exists())

    def test_evaluate_registrations_by_default_and_saves_the_result(self):
        self.register_month()
        code, summary, _ = self.evaluate()
        self.assertEqual(
            (code, summary["dryRunIncluded"], summary["official"]), (0, False, True)
        )
        self.assertEqual(
            summary["registrations"], [dict(month="2026-09", kind="registration")]
        )
        saved = json.loads((self.data / f"evaluation/{THROUGH}.json").read_text())
        self.assertEqual({p["status"] for p in saved["periods"]}, {"in_progress"})
        self.assertEqual({p["entry"] for p in saved["periods"]}, {"2026-10-05"})
        self.assertEqual(saved["series"]["^SP500TR"]["status"], "ok")
        head = ledger.read(self.data / "ledger.jsonl")[-1]["hash"]
        self.assertEqual(saved["ledger"], dict(head=head, events=3, registrations=1))
        self.assertTrue(saved["official"])
        # D12': it was online and is valued through the last session it saw.
        self.assertEqual((saved["online"], saved["officialBlockers"]), (True, []))
        self.assertEqual(saved["valuedThrough"], {"US": THROUGH, "KR": THROUGH})
        members = {m["id"]: m for p in saved["periods"] for m in p["members"]}
        kept = self.kept("U1")["originals"]
        self.assertEqual(
            members["US:0000000001"]["seriesSha256"], kept[0]["source"]["sha256"]
        )

    def test_evaluate_dry_run_file_fetches_members_and_benchmarks(self):
        self.save_universe(fake_universe())
        self.collect(Fakes(), "--limit", "2")
        _, scored, _ = self.score("--dry-run")
        out = self.root / "evaluation.json"
        fakes = Fakes()
        code, summary, _ = self.evaluate(
            "--files", self.root / scored["file"], "--out", out, fakes=fakes
        )
        self.assertEqual((code, summary["dryRunIncluded"]), (0, True))
        self.assertFalse(summary["official"])
        fetched = {c[1]: c[3] for c in fakes.calls}
        self.assertIn("^SP500TR", fetched)
        self.assertIn("069500.KS", fetched)
        self.assertIn("U6", fetched)  # every eligible row, collected or not
        self.assertNotIn("U7", fetched)  # excluded
        self.assertEqual(set(fetched.values()), {AS_OF})  # window starts at asOf
        statuses = {(p["market"], p["status"]) for p in summary["periods"]}
        self.assertEqual(statuses, {("US", "in_progress"), ("KR", "in_progress")})
        self.assertEqual(json.loads(out.read_text())["through"], THROUGH)
        self.assertFalse((self.data / "series").exists())  # official runs only

    def test_registrations_come_from_the_ledger(self):
        """D12: a ledgered registration whose file is gone, or a file without its
        event, stops the evaluation instead of silently changing it."""
        path = self.register_month()
        blob = path.read_bytes()
        path.unlink()
        code, _, err = self.evaluate()
        self.assertEqual(code, 2)
        self.assertIn("2026-09.json is missing", err)
        path.write_bytes(blob)
        (self.data / "v1/2026-08.json").write_bytes(blob)
        code, _, err = self.evaluate()
        self.assertEqual(code, 2)
        self.assertIn("without a ledger event", err)
        self.assertFalse((self.data / "evaluation").exists())

    def test_official_output_is_the_whole_ledger_without_dry_runs(self):
        """#11: dry runs never mix with registrations, and data/ratings/evaluation only
        holds evaluations of the full ledger."""
        path = self.register_month()
        _, dry, _ = self.score("--dry-run")
        dry_path = self.root / dry["file"]
        code, _, err = self.evaluate("--files", path, dry_path)
        self.assertEqual(code, 2)
        self.assertIn("mixes", err)
        target = self.data / "evaluation/dry.json"
        code, _, err = self.evaluate("--files", dry_path, "--out", target)
        self.assertEqual(code, 2)
        self.assertIn("whole ledger only", err)
        code, summary, _ = self.evaluate("--files", dry_path)
        self.assertEqual((code, summary["official"], summary["file"]), (0, False, None))
        self.assertFalse((self.data / "evaluation").exists())
        code, summary, _ = self.evaluate("--files", path)
        self.assertEqual((code, summary["official"]), (0, True))
        self.assertEqual(summary["file"], f"data/ratings/evaluation/{THROUGH}.json")

    def test_official_output_needs_an_online_run_with_fresh_benchmarks(self):
        """D12': an offline run, or one whose benchmark came from storage, is reported
        but never written as official and never touches the kept series."""
        self.register_month()
        target = self.data / f"evaluation/{THROUGH}.json"
        code, _, err = self.evaluate("--out", target, offline=True)
        self.assertEqual(code, 2)
        self.assertIn("online", err)
        code, summary, _ = self.evaluate(offline=True)
        self.assertEqual((code, summary["official"]), (0, False))
        self.assertEqual(summary["officialBlockers"], ["offline run"])
        self.assertEqual((summary["file"], summary["online"]), (None, False))
        self.assertFalse((self.data / "series").exists())
        self.assertEqual(self.evaluate()[0], 0)  # official: keeps every series
        blob = target.read_bytes()
        kept = self.kept("_5ESP500TR")
        code, summary, _ = self.evaluate(fakes=Fakes(price_fail={"^SP500TR"}))
        self.assertEqual((code, summary["official"]), (0, False))
        self.assertEqual(summary["storedSeries"], ["^SP500TR"])
        self.assertIn("['^SP500TR']", summary["officialBlockers"][0])
        self.assertEqual(target.read_bytes(), blob)
        self.assertEqual(self.kept("_5ESP500TR"), kept)

    def test_series_are_kept_merged_and_reparsed_when_a_download_fails(self):
        """D12': kept series grow by original (never shrink, official runs only); a
        failed download falls back to a kept original re-parsed after its hash is
        verified; a member without any series is a counted error."""
        self.register_month()
        self.assertEqual(self.evaluate()[0], 0)
        kept = self.kept("U1")
        self.assertEqual((len(kept["originals"]), "rows" in kept), (1, False))
        self.assertTrue((self.data / "series/yahoo-_5ESP500TR.json").exists())
        code, summary, _ = self.evaluate(fakes=Fakes(price_fail={"U1"}))
        self.assertEqual(
            (code, summary["storedSeries"], summary["errors"]), (0, ["U1"], 0)
        )
        saved = json.loads((self.data / f"evaluation/{THROUGH}.json").read_text())
        members = {m["id"]: m for p in saved["periods"] for m in p["members"]}
        self.assertEqual(members["US:0000000001"]["flags"], ["stored_series"])
        self.assertEqual(
            saved["series"]["U1"]["stored"]["file"], "data/ratings/series/yahoo-U1.json"
        )
        # A reset history (from Oct 7) is kept beside the full one, never instead of
        # it; the fallback re-parses the original that reaches back to asOf.
        self.assertEqual(self.evaluate(fakes=Fakes(start={"U1": "2026-10-07"}))[0], 1)
        self.assertEqual(len(self.kept("U1")["originals"]), 2)
        code, summary, _ = self.evaluate(fakes=Fakes(price_fail={"U1"}))
        self.assertEqual((code, summary["errors"]), (0, 0))
        stored = json.loads((self.data / f"evaluation/{THROUGH}.json").read_text())
        self.assertLess(stored["series"]["U1"]["stored"]["first"], AS_OF)
        (self.data / "series/yahoo-U2.json").unlink()
        code, summary, _ = self.evaluate(fakes=Fakes(price_fail={"U2"}))
        self.assertEqual((code, summary["status"], summary["errors"]), (1, "errors", 1))
        self.assertEqual(
            summary["periods"][0]["errors"],
            [dict(id="US:0000000002", symbol="U2", reason="no_price_series")],
        )
        # The original is verified by its SHA-256 before it is parsed again.
        original = self.root / self.kept("U3")["originals"][0]["source"]["file"]
        edited = json.loads(original.read_bytes())  # closes tripled after the fact
        adjusted = edited["chart"]["result"][0]["indicators"]["adjclose"][0]
        adjusted["adjclose"] = [3 * value for value in adjusted["adjclose"]]
        original.write_text(json.dumps(edited))
        code, summary, _ = self.evaluate(fakes=Fakes(price_fail={"U2", "U3"}))
        self.assertEqual((code, summary["errors"], summary["storedSeries"]), (1, 2, []))

    def test_a_reset_history_is_an_error_for_an_open_period(self):
        """D12': a held member whose fresh series no longer covers its open period is
        an error, never no_entry_price."""
        self.register_month()
        code, summary, _ = self.evaluate(fakes=Fakes(start={"U1": "2026-10-07"}))
        self.assertEqual((code, summary["errors"]), (1, 1))
        self.assertEqual(
            summary["periods"][0]["errors"],
            [dict(id="US:0000000001", symbol="U1", reason="series_not_covering")],
        )

    def test_completed_periods_are_frozen_and_kept(self):
        """D12': the first official run after September completes freezes it; a later
        reset history of a member changes nothing but a flag."""
        self.register_month()
        october = fake_universe(
            as_of="2026-10-30",
            captured=dict(
                US="2026-11-02T13:00:00+00:00", KR="2026-10-30T10:00:00+00:00"
            ),
        )
        self.save_universe(october, "2026-10-30")
        self.clock = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)
        with Fakes().patch():
            self.run_cli("collect", "--as-of", "2026-10-30")
            code, summary, err = self.run_cli(
                "score", "--as-of-us", "2026-10-30", "--as-of-kr", "2026-10-30"
            )
        self.assertEqual((code, summary and summary["kind"]), (0, "registration"), err)
        self.clock = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)

        def run(fakes=None):
            with (fakes or Fakes()).patch():
                return self.run_cli("evaluate", "--through", "2026-11-13")

        code, summary, _ = run()
        self.assertEqual((code, summary["official"]), (0, True))
        self.assertEqual(
            summary["frozenNow"],
            [
                "data/ratings/periods/US/2026-09.json",
                "data/ratings/periods/KR/2026-09.json",
            ],
        )
        frozen = self.data / "periods/US/2026-09.json"
        blob = frozen.read_bytes()
        record = json.loads(blob)
        self.assertEqual(
            (record["entry"], record["exit"], record["status"]),
            ("2026-10-05", "2026-11-03", "complete"),
        )
        first = json.loads((self.data / "evaluation/2026-11-13.json").read_text())
        code, summary, _ = run(Fakes(start={"U1": "2026-10-20"}))
        self.assertEqual((code, summary["errors"], summary["frozenNow"]), (0, 0, []))
        self.assertEqual(frozen.read_bytes(), blob)
        later = json.loads((self.data / "evaluation/2026-11-13.json").read_text())
        september = [p for p in later["periods"] if p["month"] == "2026-09"]
        self.assertEqual({bool(p["frozen"]) for p in september}, {True})
        us = next(p for p in september if p["market"] == "US")
        before = next(
            p
            for p in first["periods"]
            if (p["market"], p["month"]) == ("US", "2026-09")
        )
        self.assertEqual(us["portfolios"], before["portfolios"])
        member = next(m for m in us["members"] if m["id"] == "US:0000000001")
        self.assertEqual(
            member["revised_after_freeze"], dict(reason="series_not_covering")
        )
        self.assertEqual(later["summary"]["US"]["revisedAfterFreeze"], 1)

    def register_october(self):
        """October registered on Nov 2 (inside its window), so September completes
        on Nov 3, October's entry session."""
        october = fake_universe(
            as_of="2026-10-30",
            captured=dict(
                US="2026-11-02T13:00:00+00:00", KR="2026-10-30T10:00:00+00:00"
            ),
        )
        self.save_universe(october, "2026-10-30")
        self.clock = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)
        with Fakes().patch():
            self.run_cli("collect", "--as-of", "2026-10-30")
            code, summary, err = self.run_cli(
                "score", "--as-of-us", "2026-10-30", "--as-of-kr", "2026-10-30"
            )
        self.assertEqual((code, summary and summary["kind"]), (0, "registration"), err)

    def test_member_errors_freeze_as_unresolved_after_the_grace(self):
        """L3: a member without any series holds September back (counted, exit 1)
        while the evaluation date is at most 30 days past its exit (Nov 3); then the
        period is frozen with it unresolved and stops being an error."""
        self.register_month()
        self.register_october()

        def run(through):
            self.clock = datetime.combine(
                date.fromisoformat(through) + timedelta(days=1), time(12), timezone.utc
            )
            with Fakes(price_fail={"U2"}).patch():  # never downloaded, never kept
                return self.run_cli("evaluate", "--through", through)

        code, summary, _ = run("2026-11-13")
        self.assertEqual((code, summary["official"]), (1, True))
        self.assertEqual(summary["frozenNow"], ["data/ratings/periods/KR/2026-09.json"])
        held = summary["frozenHeld"]
        self.assertEqual(
            [(h["market"], h["month"], h["state"]) for h in held],
            [("US", "2026-09", "wait")],
        )
        self.assertIn("2026-12-04", held[0]["reason"])
        self.assertEqual(run("2026-12-03")[1]["frozenNow"], [])  # 30 days after exit
        code, summary, _ = run("2026-12-04")
        self.assertEqual(
            (code, summary["frozenNow"]), (1, ["data/ratings/periods/US/2026-09.json"])
        )
        record = json.loads((self.data / "periods/US/2026-09.json").read_text())
        self.assertEqual(
            (record["flags"], record["unresolved"]),
            (["frozen_with_unresolved"], ["US:0000000002"]),
        )
        member = next(m for m in record["members"] if m["id"] == "US:0000000002")
        self.assertEqual(
            (member["reason"], member["error"]), ("unresolved", "no_price_series")
        )
        code, summary, _ = run("2026-12-04")
        self.assertEqual(
            (code, summary["frozenNow"], summary["frozenHeld"]), (1, [], [])
        )
        september = [p for p in summary["periods"] if p["month"] == "2026-09"]
        self.assertEqual(
            [(p["frozen"], p["errors"]) for p in september], [(True, [])] * 2
        )
        self.assertEqual(summary["errors"], 1)  # U2 in the open October period only
        self.assertEqual(summary["summary"]["US"]["unresolvedMembers"], 1)

    def test_a_period_held_back_never_holds_back_later_ones(self):
        """L3: a later complete period is frozen while an earlier one waits out its
        grace (here freezeGraceDays 60); a period error that is not a member's (a
        frozen record that does not match) stops freezing in that market."""
        import test_ratings_evaluate as fixtures  # the evaluation fixtures, read-only

        own = json.loads(canonical(rating.PROTOCOL))
        own["evaluation"]["freezeGraceDays"] = 60
        november = [
            r for r in fixtures.november_rows("US") if r["id"] != "US:B"
        ]  # B was delisted before November's entry
        registrations = [
            fixtures.registration(
                "2026-10",
                fixtures.OCTOBER_AT,
                fixtures.october_rows("US"),
                protocol=own,
            ),  # H: no price series at all
            fixtures.registration(
                "2026-11", fixtures.NOVEMBER_AT, november, protocol=own
            ),
            fixtures.registration(
                "2026-12", fixtures.DECEMBER_AT, november, protocol=own
            ),
        ]

        def result():
            return evaluate.evaluate(registrations, fixtures.series(), "2027-01-15")

        self.clock = datetime(2027, 1, 16, 12, 0, tzinfo=timezone.utc)  # after it (N2)
        blocked = result()
        october = blocked["periods"][0]
        self.assertEqual(
            (october["status"], october["errors"][0]["id"]), ("complete", "US:H")
        )
        october["errors"].append(dict(reason="frozen_period_mismatch", detail="x"))
        self.assertEqual(
            cli.freeze_periods(blocked),
            (
                [],
                [
                    dict(
                        market="US",
                        month="2026-10",
                        state="blocked",
                        reason=("frozen_period_mismatch"),
                    )
                ],
            ),
        )
        written, held = cli.freeze_periods(result())
        self.assertEqual(written, ["data/ratings/periods/US/2026-11.json"])
        self.assertEqual(
            [(h["month"], h["state"]) for h in held], [("2026-10", "wait")]
        )
        self.assertIn("2027-02-01", held[0]["reason"])  # Dec 2 + 61 days
        self.assertFalse((self.data / "periods/US/2026-10.json").exists())

    def test_a_market_freezes_only_on_or_after_its_own_date(self):
        """N2: an official run at 08:30 in Seoul on Nov 13 is dated Nov 13 while New
        York is still on Nov 12: Korea's September is frozen, the US's waits for a
        run on or after Nov 13 New York time."""
        self.register_month()
        self.register_october()
        self.clock = datetime(2026, 11, 12, 23, 30, tzinfo=timezone.utc)
        with Fakes().patch():
            code, summary, _ = self.run_cli("evaluate", "--through", "2026-11-13")
        self.assertEqual((code, summary["official"]), (0, True))
        self.assertEqual(summary["frozenNow"], ["data/ratings/periods/KR/2026-09.json"])
        held = summary["frozenHeld"]
        self.assertEqual(
            [(h["market"], h["month"], h["state"]) for h in held],
            [("US", "2026-09", "after_local_date")],
        )
        self.assertIn("after US's local date 2026-11-12", held[0]["reason"])
        self.assertFalse((self.data / "periods/US/2026-09.json").exists())
        self.clock = datetime(2026, 11, 13, 14, 0, tzinfo=timezone.utc)  # 09:00 NY
        with Fakes().patch():
            code, summary, _ = self.run_cli("evaluate", "--through", "2026-11-13")
        self.assertEqual(
            (code, summary["frozenNow"], summary["frozenHeld"]),
            (0, ["data/ratings/periods/US/2026-09.json"], []),
        )

    def test_an_evaluation_date_after_today_is_never_official(self):
        """L3: a later evaluation date would freeze periods before their grace."""
        self.register_month()
        self.clock = EVALUATED  # Oct 17 in both markets
        with Fakes().patch():
            code, summary, _ = self.run_cli("evaluate", "--through", "2026-10-19")
        self.assertEqual((code, summary["official"]), (0, False))
        self.assertEqual(
            summary["officialBlockers"],
            ["evaluation date 2026-10-19 is after 2026-10-17"],
        )
        self.assertFalse((self.data / "evaluation").exists())
        self.assertFalse((self.data / "series").exists())

    def test_forward_check_reads_the_frozen_study_only(self):
        study = ROOT / "data/forward-study.json"
        before = study.read_bytes()
        fakes = Fakes(price_fail={"000660.KS"})  # falls back to the KOSDAQ symbol
        with fakes.patch():
            code, summary, _ = self.run_cli(
                "forward-check", "--through", "2026-10-05", "--offline"
            )
        self.assertEqual((code, summary["status"], summary["matches"]), (0, "ok", True))
        self.assertEqual(study.read_bytes(), before)
        self.assertEqual(summary["studySha256"], digest(before))
        self.assertEqual(len(summary["results"]), 4)
        self.assertEqual({r["status"] for r in summary["results"]}, {"pending"})
        saved = json.loads((self.data / "forward-check/2026-10-05.json").read_text())
        self.assertEqual(saved["series"]["000660.KQ"]["status"], "ok")
        self.assertIn("000660.KS", summary["seriesErrors"])
        later = (date.fromisoformat("2026-09-30") + timedelta(days=45)).isoformat()
        with Fakes().patch():
            code, summary, _ = self.run_cli(
                "forward-check", "--through", later, "--offline"
            )
        observed = [r for r in summary["results"] if r["horizon"] == 21]
        self.assertEqual({r["status"] for r in observed}, {"observed"})
        self.assertEqual(
            (code, summary["matches"], summary["differences"]), (0, True, [])
        )

    def test_forward_check_reports_a_disagreement_with_the_study(self):
        """D13: the ratings return functions are compared with the study evaluator."""
        original = evaluate.holding

        def shifted(rows, entry, exit):
            out = original(rows, entry, exit)
            if "return" in out:
                out["return"] += 0.001
            return out

        later = (date.fromisoformat("2026-09-30") + timedelta(days=45)).isoformat()
        with Fakes().patch(), mock.patch.object(
            evaluate, "holding", side_effect=shifted
        ):
            code, summary, _ = self.run_cli(
                "forward-check", "--through", later, "--offline"
            )
        self.assertEqual(
            (code, summary["status"], summary["matches"]), (1, "ok", False)
        )
        self.assertTrue(
            any(
                d["field"].startswith("companyReturns.") for d in summary["differences"]
            )
        )

    def test_forward_check_reports_a_tampered_study(self):
        contract = json.loads((ROOT / "data/forward-study.json").read_text())
        contract["oneWayCost"] = 0.0
        tampered = self.root / "forward-study.json"
        tampered.write_text(json.dumps(contract))
        fakes = Fakes()
        with mock.patch.object(cli, "FORWARD_STUDY", tampered), fakes.patch():
            code, summary, _ = self.run_cli(
                "forward-check", "--through", "2026-10-05", "--offline"
            )
        self.assertEqual((code, summary["status"]), (1, "invalid"))
        self.assertIn("protocolHash", summary["error"])
        self.assertEqual(fakes.calls, [])  # verified before any download
        self.assertFalse((self.data / "forward-check").exists())


class ProtocolTests(unittest.TestCase):
    def test_module_rules_are_hashed_copies(self):
        rules = rating.PROTOCOL["moduleRules"]
        self.assertEqual(
            rules["fundamentals"], json.loads(json.dumps(fundamentals.RULES))
        )
        self.assertEqual(rules["universe"], json.loads(json.dumps(universe.RULES)))
        self.assertEqual(
            rules["sectorReferences"]["ksicReferenceSha256"],
            digest(sectors.KSIC_REFERENCE.read_bytes()),
        )
        self.assertEqual(rules["prices"]["lookbackDays"], prices.LOOKBACK_DAYS)
        gate = rating.PROTOCOL["decisions"]["computabilityCheck"]["thresholds"]
        self.assertEqual((gate, cli.GATE), ({"US": 0.9, "KR": 0.8}, gate))
        with mock.patch.dict(universe.RULES["KR"], top=10):  # not aliased
            self.assertEqual(
                common.protocol_hash(rating.PROTOCOL), rating.PROTOCOL_HASH
            )
        changed = json.loads(canonical(rating.PROTOCOL))
        changed["moduleRules"]["fundamentals"]["filedBeforeAsOf"] = False
        self.assertNotEqual(common.protocol_hash(changed), rating.PROTOCOL_HASH)

    def test_decided_settings_come_from_the_protocol(self):
        for name in (
            "registrationWindowSessions",
            "missedRegistrationExitSession",
            "universeFetchErrorMaxShare",
            "sessionCalendar",
            "codeFiles",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    registry.setting(name), registry.setting(name, rating.PROTOCOL)
                )
                found = rating.PROTOCOL.get(name) or next(
                    v[name]
                    for v in rating.PROTOCOL.values()
                    if isinstance(v, dict) and name in v
                )
                self.assertEqual(registry.setting(name), found)
        self.assertEqual(registry.setting("registrationWindowSessions"), 5)


class IntegrationTests(Store):
    """Real modules on stored originals (no network): the CLI's view of one month."""

    FACTS = (
        ("sec-facts-CIK0000320193", "fundamentals/sec-facts-CIK0000320193.json", "SEC"),
        ("sec-facts-CIK0001045810", "fundamentals/sec-facts-CIK0001045810.json", "SEC"),
        (
            "dart-acnt-00126380-2026-11012-CFS",
            "fundamentals/dart-acnt-00126380-2026-11012-CFS.json",
            "OpenDART",
        ),
        (
            "dart-acnt-00126380-2025-11011-CFS",
            "fundamentals/dart-acnt-00126380-2025-11011-CFS.json",
            "OpenDART",
        ),
    )
    PRICES = (
        ("AAPL", "US", "prices/yahoo-AAPL-2026-10-05.json"),
        ("005930.KS", "KR", "prices/yahoo-005930.KS-2026-10-05.json"),
    )

    def originals(self):
        """Fixture originals under the keys an offline collect at CLOCK asks for,
        stamped at the CLI's clock as a download at CLOCK would be (M2: a window
        through the retrieval date)."""
        with mock.patch.object(common, "datetime", self.Clock):
            for key, name, provider in self.FACTS:
                blob = (FIXTURES / name).read_bytes()
                common.store(blob, key, f"fixture:{name}", provider, ".json")
            for symbol, market, name in self.PRICES:
                start = cli.window_start(AS_OF)
                key = prices.source_key(symbol, cli.today(market), start)
                blob = (FIXTURES / name).read_bytes()
                common.store(blob, key, f"fixture:{name}", "Yahoo Finance", ".json")

    def universe(self) -> dict:
        built = fake_universe(us=0, kr=0)
        apple = dict(
            us_member(2),
            id="US:0000320193",
            name="Apple Inc.",
            ticker="AAPL",
            priceSymbol="AAPL",
            cik="0000320193",
            fiscalYearEnd="0926",
            shareClasses=[dict(ticker="AAPL", priceSymbol="AAPL", kind="common")],
        )
        nvidia = dict(
            us_member(1),
            id="US:0001045810",
            name="NVIDIA CORP",
            ticker="NVDA",
            priceSymbol="NVDA",
            cik="0001045810",
            fiscalYearEnd="0125",
            shareClasses=[dict(ticker="NVDA", priceSymbol="NVDA", kind="common")],
        )
        samsung = dict(
            kr_member(1),
            id="KR:005930",
            name="삼성전자",
            ticker="005930",
            priceSymbol="005930.KS",
            corpCode="00126380",
            shareClasses=[
                dict(
                    ticker="005930",
                    priceSymbol="005930.KS",
                    kind="common",
                    listedShares=5_846_278_608,
                ),
                dict(
                    ticker="005935",
                    priceSymbol="005935.KS",
                    kind="preferred",
                    listedShares=802_371_203,
                ),
            ],
        )
        built["members"] = [nvidia, apple, *built["members"], samsung]
        return built

    def test_one_month_from_stored_originals(self):
        self.originals()
        self.save_universe(self.universe())
        code, summary, _ = self.run_cli("collect", "--as-of", AS_OF, "--offline")
        self.assertEqual(code, 0)
        us = {r["id"]: r for r in self.lines("US")}
        apple = us["US:0000320193"]
        self.assertEqual(apple["status"], "ok")
        self.assertIn(apple["fundamentals"]["status"], ("ok", "insufficient"))
        rows = apple["prices"]["AAPL"]["rows"]
        self.assertIn(AS_OF, [r[0] for r in rows])
        # Through the retrieval date (08:00 New York on Oct 2): its last settled session.
        self.assertEqual(apple["prices"]["AAPL"]["window"]["through"], "2026-10-02")
        self.assertEqual(rows[-1][0], "2026-10-01")
        self.assertEqual(
            apple["prices"]["AAPL"]["source"]["retrievedAt"], CLOCK.isoformat()
        )
        nvidia = us["US:0001045810"]  # facts stored, prices not: recorded failure
        self.assertIn(nvidia["fundamentals"]["status"], ("ok", "insufficient"))
        self.assertIn("No stored original for yahoo-NVDA", nvidia["errors"][0])
        self.assertEqual(summary["markets"]["KR"]["methods"], {"ytd": 1})

        code, summary, _ = self.score("--dry-run", fakes=Fakes())
        self.assertEqual((code, summary["smoke"]), (0, False))
        content = registry.read(self.root / summary["file"])
        rows = {r["id"]: r for r in content["rows"]}
        signals = rows["US:0000320193"]["signals"]
        self.assertAlmostEqual(signals["fcfYield"], 0.0281232, places=6)
        self.assertAlmostEqual(signals["cashProfitability"], 0.3828255, places=6)
        self.assertAlmostEqual(
            signals["momentum12_1"],
            prices.momentum_12_1(apple["prices"]["AAPL"]["rows"], AS_OF),
            places=12,
        )
        # One priced US member: FCF and momentum have no cross-sectional spread, so
        # their z is undefined and Apple keeps one z (cash profitability): no label.
        apple_row = rows["US:0000320193"]
        self.assertEqual(
            (apple_row["label"], apple_row["labelReason"]), (None, "insufficient")
        )
        self.assertIn("momentum12_1_z_undefined", apple_row["issues"])
        self.assertIsNotNone(apple_row["z"]["cashProfitability"])
        self.assertIn("class_price_proxy", rows["KR:005930"]["issues"])
        self.assertAlmostEqual(
            rows["KR:005930"]["signals"]["momentum12_1"], 2.4512616, places=6
        )
        facts = {m["key"]: m for m in content["inputs"]["fundamentals"]}
        blob = (FIXTURES / "fundamentals/sec-facts-CIK0000320193.json").read_bytes()
        self.assertEqual(facts["sec-facts-CIK0000320193"]["sha256"], digest(blob))

        # The computability check runs on its own universe and checkpoints (H1).
        self.save_universe(self.universe(), f"{AS_OF}-gate")
        self.run_cli("collect", "--as-of", AS_OF, "--gate", "--offline")
        _, coverage, _ = self.run_cli("coverage", "--as-of", AS_OF, "--gate")
        us, kr = coverage["markets"]["US"], coverage["markets"]["KR"]
        self.assertEqual(
            (us["nonFinancial"], us["withTwoSignals"], us["stale"], us["verdict"]),
            (2, 1, 2, "incomplete"),  # collected offline: no verdict
        )
        self.assertEqual(
            (kr["nonFinancial"], kr["withTwoSignals"], kr["verdict"]),
            (1, 1, "incomplete"),
        )


if __name__ == "__main__":
    unittest.main()
