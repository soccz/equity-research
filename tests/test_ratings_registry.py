from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from equitylab import ledger
from equitylab.data import canonical, digest

from ratings import common, registry, sectors
from ratings import universe as universes
from ratings.rating import PREFER, PROTOCOL, PROTOCOL_HASH, score

AS_OF = {"US": "2026-10-30", "KR": "2026-10-30"}  # a Friday: the month's last session
# 12:00 UTC is 07:00 in New York and 21:00 in Seoul: both local dates are Nov 2.
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
# D5': Korea is captured on T's evening in Seoul (19:00), the US once SSGA posts T's
# holdings on the next US business day (06:30 New York on Mon Nov 2): two captures no
# single build could make.
CAPTURED = {"US": "2026-11-02T10:30:00+00:00", "KR": "2026-10-30T10:00:00+00:00"}
CALENDAR = PROTOCOL["registration"]["sessionCalendar"]
FINANCIAL = {"US": "financial_sic", "KR": "financial_ksic"}
KSIC = digest(sectors.KSIC_REFERENCE.read_bytes())
CHECKPOINTS = {
    m: dict(file=f"data/ratings/work/2026-10-30/{m}.jsonl", sha256=digest(m.encode()))
    for m in ("US", "KR")
}
GATE_AS_OF = "2026-10-19"  # PROTOCOL decisions.computabilityCheck.asOf (a Monday)


def manifest(key: str, **extra) -> dict:
    out = dict(
        key=key,
        url=f"https://example.invalid/{key}",
        sha256=digest(key.encode()),
        file=f"data/ratings/sources/{key}-{digest(key.encode())[:16]}.json",
        provider="test",
    )
    out.update(extra)
    return out


def weekdays(start: str, end: str) -> list:
    day, out = date.fromisoformat(start), []
    while day <= date.fromisoformat(end):
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def calendar(market: str, when: datetime, skip=(), extra=()) -> dict:
    """A prices.series() result of the market's session calendar fetched at ``when``."""
    zone = ZoneInfo(PROTOCOL["registration"]["timezones"][market])
    local = when.astimezone(zone).date().isoformat()
    days = sorted(
        set(d for d in weekdays("2026-08-03", local) if d not in skip) | set(extra)
    )
    return dict(
        symbol=CALENDAR[market],
        status="ok",
        rows=[[d, 100.0, 100.0] for d in days if d <= local],
        window=dict(through=local),
        source=dict(manifest(f"yahoo-{market}-{local}"), retrievedAt=when.isoformat()),
    )


def member(key: str, market: str, status: str = "eligible", **extra) -> dict:
    out = dict(
        id=key,
        market=market,
        name=key,
        ticker=key,
        priceSymbol=key,
        sector="Money" if status == "excluded" else "S",
        shareClasses=[],
        status=status,
        reason=None if status == "eligible" else FINANCIAL[market],
    )
    out.update(extra)
    return out


def part(market: str, as_of: str, members: list, captured: str) -> dict:
    """One market's own build (universe.build for that market alone), built online
    (M2: a part replayed offline is refused)."""
    rules = json.loads(json.dumps(universes.RULES))
    info, sources = dict(status="ok", asOf=as_of, online=True), []
    if market == "US":
        info.update(holdingsAsOf=as_of, ff12Hash=sectors.FF12_DEFINITION_SHA256)
        sources.append(
            manifest("ssga-spy-holdings", provider="SSGA", retrievedAt=captured)
        )
    else:
        info.update(rankingBasis="T_close")
        sources += [
            manifest(
                "naver-kospi-marketvalue-p1",
                provider="Naver Finance",
                retrievedAt=captured,
            ),
            manifest("yahoo-000010.KS", provider="Yahoo Finance", retrievedAt=captured),
            manifest("ksic-ff12", sha256=KSIC, provider="ratings-v1 reference"),
        ]
    return dict(
        version="test-universe",
        asOf=as_of,
        asOfByMarket={market: as_of},
        builtAt=captured,
        completedAt=captured,
        status="ok",
        rules=rules,
        rulesHash=digest(canonical(rules)),
        markets={market: info},
        sources=sources,
        members=members,
    )


def part_files(as_of: str, gate: bool = False) -> dict:
    """``{market: {file, sha256}}`` of the saved parts, as universe.merge records them
    (H1: the computability-check universe's parts are in <T>-gate/)."""
    stem = f"{as_of}-gate" if gate else as_of
    return {
        m: dict(
            file=f"data/ratings/universe/{stem}/{m}.json",
            sha256=digest(f"{stem}/{m}".encode()),
        )
        for m in ("US", "KR")
    }


def universe(
    as_of: str = "2026-10-30", us: int = 6, kr: int = 6, captured=None, gate=False
):
    """The month's merged universe: each market built apart after its own close
    (``gate``: the computability-check universe, merged from <T>-gate/ parts)."""
    captured = captured or CAPTURED
    us_members = [member(f"US:{k:010d}", "US") for k in range(1, us + 1)]
    us_members.append(member("US:0000000099", "US", "excluded"))
    kr_members = [member(f"KR:{k * 10:06d}", "KR") for k in range(1, kr + 1)]
    kr_members.append(member("KR:000990", "KR", "excluded"))
    return registry.merge_universe(
        {
            "US": part("US", as_of, us_members, captured["US"]),
            "KR": part("KR", as_of, kr_members, captured["KR"]),
        },
        files=part_files(as_of, gate),
        now="2026-11-02T11:00:00+00:00",
    )


def rated(base: dict | None = None, as_of: dict = AS_OF) -> list:
    rows = []
    for k, m in enumerate((base or universe())["members"]):
        value = None if registry.fetch_error(m) else float(k)
        rows.append(
            dict(
                id=m["id"],
                market=m["market"],
                sector=m["sector"],
                priceSymbol=m["priceSymbol"],
                status=m["status"],
                reason=m["reason"],
                asOf=as_of[m["market"]],
                signals=dict(
                    fcfYield=value, cashProfitability=value, momentum12_1=None
                ),
                issues=[],
            )
        )
    return score(rows)


def gate_event(market: str, verdict: str = "pass", **changes) -> dict:
    """A coverage-gate event as record_gate writes it (D10')."""
    event = dict(
        eventId=f"ratings-v1:coverage-gate:{market}",
        type=registry.GATE_TYPE,
        market=market,
        asOf=GATE_AS_OF,
        rate=0.95 if verdict == "pass" else 0.5,
        threshold=0.9 if market == "US" else 0.8,
        verdict=verdict,
        universeSha256="0" * 64,
        protocolHash=PROTOCOL_HASH,
    )
    event.update(changes)
    return event


class Ledgered(unittest.TestCase):
    """The registry's store and clock point into a temp folder and a fixed time."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.clock = NOW
        for name, value in (
            ("REGISTRATIONS", self.root / "v1"),
            ("LEDGER", self.root / "ledger.jsonl"),
            ("DRY_RUNS", self.root / "dry-run"),
            ("_clock", lambda: self.clock),
        ):
            patcher = mock.patch.object(registry, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(os, "fsync", lambda fd: None)  # slow disk
        patcher.start()
        self.addCleanup(patcher.stop)
        self.universe = universe()
        self.rows = rated(self.universe)
        self.inputs = [manifest("prices-AAA"), manifest("facts-1")]

    def gates(self, US="pass", KR="pass", **changes):
        for market, verdict in (("US", US), ("KR", KR)):
            if verdict:
                ledger.append(registry.LEDGER, gate_event(market, verdict, **changes))

    def register(self, **kwargs):
        when = kwargs.get("now", self.clock)
        args = dict(
            as_of=AS_OF,
            universe=self.universe,
            rated=self.rows,
            inputs=self.inputs,
            now=when,
            calendars={m: calendar(m, when) for m in ("US", "KR")},
            checkpoints=CHECKPOINTS,
        )
        args.update(kwargs)
        return registry.register(**args)

    def files(self) -> list:
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))

    def events(self, kind=registry.EVENT_TYPE) -> list:
        return [e for e in ledger.read(registry.LEDGER) if e["type"] == kind]

    def refused(self, pattern, **kwargs):
        """Refused as a registration; the same issue is kept by a dry run."""
        with self.assertRaisesRegex(ValueError, pattern):
            self.register(**kwargs)
        content = json.loads(self.register(dry_run=True, **kwargs).read_text())
        self.assertTrue(
            any(re.search(pattern, issue) for issue in content["issues"]),
            content["issues"],
        )
        self.assertEqual(self.events(), [])
        return content


class Gated(Ledgered):
    def setUp(self):
        super().setUp()
        self.gates()


class RegistryTests(Gated):
    def test_refuses_registration_until_as_of_has_passed_locally(self):
        # 03:00 UTC on Oct 31 is still Oct 30 in New York (23:00) but Oct 31 in Seoul.
        self.clock = datetime(2026, 10, 31, 3, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "'US'") as caught:
            self.register()
        self.assertNotIn("'KR'", str(caught.exception))
        # With KR's asOf on Oct 31, 10:00 UTC passes New York but not Seoul (19:00).
        self.clock = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
        as_of = {"US": "2026-10-30", "KR": "2026-10-31"}
        with self.assertRaisesRegex(ValueError, "'KR'"):
            self.register(as_of=as_of, rated=rated(self.universe, as_of))
        with self.assertRaises(ValueError):
            self.register(
                dry_run=True, now=datetime(2026, 10, 30, 23, tzinfo=timezone.utc)
            )
        self.assertEqual([f for f in self.files() if f != "ledger.jsonl"], [])

    def test_time_must_be_aware_and_current(self):
        with self.assertRaises(ValueError):
            self.register(now=datetime(2026, 11, 2, 12, 0))
        with self.assertRaisesRegex(ValueError, "backdating"):
            self.register(now=NOW - timedelta(days=1))
        dry = self.register(now=NOW - timedelta(days=1), dry_run=True)
        self.assertTrue(dry.exists())
        self.assertEqual(self.events(), [])

    def test_registration_is_written_once_and_ledgered(self):
        path = self.register()
        self.assertEqual(path, self.root / "v1/2026-10.json")
        blob = path.read_bytes()
        content = json.loads(blob)
        self.assertEqual(content["kind"], "registration")
        self.assertEqual(content["protocolHash"], PROTOCOL_HASH)
        self.assertEqual(content["asOf"], AS_OF)
        self.assertEqual(content["registeredAt"], NOW.isoformat())
        self.assertEqual(
            content["registrationDay"], {"US": "2026-11-02", "KR": "2026-11-02"}
        )
        self.assertEqual(
            content["universe"]["sha256"], digest(canonical(self.universe))
        )
        self.assertEqual(
            content["universe"]["counts"]["US"],
            dict(members=7, eligible=6, excluded=1, financialExcluded=1, fetchErrors=0),
        )
        self.assertEqual(
            content["universe"]["timing"]["KR"]["capturedAt"],
            dict(first=CAPTURED["KR"], last=CAPTURED["KR"], stamps=2),
        )
        self.assertEqual(content["checkpoints"], CHECKPOINTS)
        self.assertEqual(len(content["rows"]), 14)
        labels = content["labels"]["KR"]
        self.assertEqual(
            (labels[PREFER], labels["excluded"], labels["scored"]), (2, 1, 6)
        )
        self.assertEqual(labels["computableRate"], 1.0)
        self.assertEqual(
            [m["key"] for m in content["inputs"]], ["facts-1", "prices-AAA"]
        )
        self.assertEqual(content["gates"]["US"]["verdict"], "pass")
        self.assertEqual(content["gates"]["US"]["protocolHash"], PROTOCOL_HASH)
        self.assertEqual(content["calendar"]["US"]["sessionsAfterAsOf"], [])
        self.assertNotIn("issues", content)
        events = ledger.read(registry.LEDGER)
        self.assertEqual(len(events), 3)  # two gates, then the registration
        event = events[-1]
        self.assertEqual(event["eventId"], "ratings-v1:2026-10")
        self.assertEqual(event["type"], "rating-registration")
        self.assertEqual(event["month"], "2026-10")
        self.assertEqual(event["fileSha256"], digest(blob))
        self.assertEqual(event["protocolHash"], PROTOCOL_HASH)
        self.assertEqual(event["universeSha256"], content["universe"]["sha256"])
        self.assertEqual(event["asOf"], AS_OF)
        block = dict(
            eventId=event["eventId"],
            recordedAt=event["recordedAt"],
            hash=event["hash"],
            sequence=2,
        )
        self.assertEqual(registry.read(path), dict(content, ledger=block))
        self.assertEqual(registry.registrations(), [dict(content, ledger=block)])
        self.assertEqual(
            registry.ledger_head(), dict(head=event["hash"], events=3, registrations=1)
        )

    def test_identical_rerun_is_idempotent_and_revisions_are_refused(self):
        path = self.register()
        blob = path.read_bytes()
        self.clock = NOW + timedelta(minutes=30)
        self.assertEqual(self.register(), path)
        self.assertEqual(path.read_bytes(), blob)
        self.assertEqual(len(self.events()), 1)
        changed = [dict(r) for r in self.rows]
        first = next(r for r in changed if r["label"] == PREFER)
        first["label"], first["labelReason"] = "관찰", "tercile"
        with self.assertRaisesRegex(ValueError, "different content"):
            self.register(rated=changed)
        with self.assertRaisesRegex(ValueError, "different content"):
            self.register(inputs=self.inputs + [manifest("late-original")])
        recollected = dict(CHECKPOINTS, US=dict(CHECKPOINTS["US"], sha256="a" * 64))
        with self.assertRaisesRegex(ValueError, "different content"):
            self.register(checkpoints=recollected)
        self.assertEqual(path.read_bytes(), blob)
        self.assertEqual(len(self.events()), 1)

    def test_missing_file_with_ledger_event_is_refused(self):
        path = self.register()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            self.register()
        self.assertFalse(path.exists())

    def test_tampered_file_fails_verification(self):
        path = self.register()
        content = json.loads(path.read_text())
        content["rows"][0]["label"] = PREFER
        path.write_text(
            json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True)
        )
        with self.assertRaisesRegex(ValueError, "ledger"):
            registry.read(path)
        with self.assertRaises(ValueError):
            self.register()

    def test_dry_run_stays_out_of_the_ledger(self):
        path = self.register(dry_run=True)
        self.assertEqual(path, self.root / "dry-run/2026-10-30.json")
        content = json.loads(path.read_text())
        self.assertEqual((content["kind"], content["issues"]), ("dry-run", []))
        self.assertEqual(self.events(), [])
        self.assertFalse((self.root / "v1").exists())
        self.assertEqual(registry.read(path)["kind"], "dry-run")
        self.assertNotIn("ledger", registry.read(path))

    def test_rows_must_cover_the_universe_for_the_registered_asof(self):
        with self.assertRaisesRegex(ValueError, "cover the universe"):
            self.register(rated=self.rows[1:])
        stale = [dict(r) for r in self.rows]
        stale[0]["asOf"] = "2026-09-30"
        with self.assertRaisesRegex(ValueError, "asOf"):
            self.register(rated=stale)
        with self.assertRaisesRegex(ValueError, "not being registered"):
            self.register(as_of={"US": "2026-10-30"})
        us_only = [r for r in self.rows if r["market"] == "US"]
        path = self.register(as_of={"US": "2026-10-30"}, rated=us_only)
        self.assertEqual(set(json.loads(path.read_text())["labels"]), {"US"})
        with self.assertRaisesRegex(ValueError, "one month"):
            self.register(as_of={"US": "2026-10-30", "KR": "2026-11-02"})
        unscored = [dict(r, labelReason=None) for r in self.rows]
        with self.assertRaisesRegex(ValueError, "scored"):
            self.register(rated=unscored)

    def test_failed_or_other_month_universe_is_refused(self):
        failed = universe()
        failed.update(status="error")
        failed["markets"]["KR"] = dict(status="error", error="HTTP 500")
        with self.assertRaisesRegex(ValueError, "HTTP 500"):
            self.register(universe=failed)
        us_rows = [r for r in rated(failed) if r["market"] == "US"]
        path = self.register(
            universe=failed, as_of={"US": "2026-10-30"}, rated=us_rows, dry_run=True
        )
        self.assertEqual(set(json.loads(path.read_text())["labels"]), {"US"})
        with self.assertRaisesRegex(ValueError, "not in 2026-10"):
            self.register(universe=dict(self.universe, asOf="2026-09-30"))
        self.assertEqual(self.events(), [])

    def test_non_json_values_and_bare_inputs_are_refused(self):
        broken = [dict(r) for r in self.rows]
        broken[0] = dict(broken[0], marketCap=float("nan"))
        with self.assertRaises(ValueError):
            self.register(rated=broken)
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.register(inputs=[dict(url="https://example.invalid/x")])
        grouped = self.register(
            dry_run=True, inputs={"prices": [manifest("p")], "facts": [manifest("f")]}
        )
        self.assertEqual(
            set(json.loads(grouped.read_text())["inputs"]), {"prices", "facts"}
        )
        self.assertEqual(self.events(), [])

    def test_previous_labels_come_per_market_from_the_latest_registration(self):
        """D16: a month that left a market out keeps that market's previous labels."""
        self.assertEqual(registry.previous_labels("2026-11"), {})
        self.register()
        october = {r["id"]: r["label"] for r in self.rows}
        self.assertEqual(registry.previous_labels("2026-11"), october)
        self.assertEqual(registry.previous_labels("2026-10"), {})
        # November registers the US only (Korea left out): all 관찰 this time.
        later = universe("2026-11-30", captured=NOVEMBER)
        as_of = {"US": "2026-11-30"}
        us_rows = [
            dict(r, label="관찰", labelReason="tercile") if r["label"] else r
            for r in rated(later, {"US": "2026-11-30", "KR": "2026-11-30"})
            if r["market"] == "US"
        ]
        self.clock = datetime(2026, 12, 1, 23, 0, tzinfo=timezone.utc)
        self.register(as_of=as_of, universe=later, rated=us_rows)
        previous = registry.previous_labels("2026-12")
        self.assertEqual(
            {k: v for k, v in previous.items() if k.startswith("US:")},
            {r["id"]: r["label"] for r in us_rows},
        )
        self.assertIn("관찰", previous.values())
        self.assertEqual(
            {k: v for k, v in previous.items() if k.startswith("KR:")},
            {k: v for k, v in october.items() if k.startswith("KR:")},
        )


# Nov 30's captures: Korea at 19:00 KST that day, the US at 08:00 New York on Dec 1.
NOVEMBER = dict(US="2026-12-01T13:00:00+00:00", KR="2026-11-30T10:00:00+00:00")


class BackdatingTests(Gated):
    """An interrupted registration (file linked, no ledger event) is never backdated."""

    def interrupted(self) -> Path:
        with mock.patch.object(
            registry.ledger, "append", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.register()
        path = self.root / "v1/2026-10.json"
        self.assertTrue(path.exists())
        self.assertEqual(self.events(), [])
        return path

    def test_unledgered_file_is_completed_only_near_its_stamp(self):
        path = self.interrupted()
        with self.assertRaisesRegex(ValueError, "without a ledger event"):
            registry.registrations()
        self.clock = NOW + timedelta(minutes=30)  # still inside the window
        with self.assertRaisesRegex(ValueError, "no ledger event and is stamped"):
            self.register()
        self.assertEqual(self.events(), [])
        self.clock = NOW + timedelta(minutes=5)
        self.assertEqual(self.register(), path)
        (event,) = self.events()
        self.assertEqual(event["registeredAt"], NOW.isoformat())

    def test_a_hand_written_older_stamp_is_refused(self):
        path = self.interrupted()
        content = json.loads(path.read_text())
        content["registeredAt"] = (NOW - timedelta(days=2)).isoformat()
        path.write_text(json.dumps(content, ensure_ascii=False, sort_keys=True))
        with self.assertRaisesRegex(ValueError, "no ledger event"):
            self.register()
        self.assertEqual(self.events(), [])


class LedgerReadTests(Gated):
    """Registrations are read from the ledger: every event needs its unaltered file."""

    def test_deleted_retyped_or_unledgered_files_are_errors(self):
        path = self.register()
        blob = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            registry.registrations()
        with self.assertRaisesRegex(ValueError, "missing"):
            registry.previous_labels("2026-11")
        content = json.loads(blob)
        content["kind"] = "dry-run"
        path.write_text(json.dumps(content, ensure_ascii=False, sort_keys=True))
        with self.assertRaisesRegex(ValueError, "kind 'dry-run'"):
            registry.read(path)
        with self.assertRaisesRegex(ValueError, "does not match"):
            registry.registrations()
        path.write_bytes(blob)
        self.assertEqual(len(registry.registrations()), 1)
        (self.root / "v1/2026-09.json").write_bytes(blob)
        with self.assertRaisesRegex(ValueError, r"without a ledger event.*2026-09"):
            registry.registrations()


class CheckpointTests(Gated):
    """D8' checkpoint files and D9' stale checkpoints."""

    def test_checkpoint_files_are_recorded(self):
        content = self.refused(
            "KR: no checkpoint file SHA-256", checkpoints={"US": CHECKPOINTS["US"]}
        )
        self.assertEqual(content["checkpoints"], {"US": CHECKPOINTS["US"]})
        bad = dict(CHECKPOINTS, US=dict(CHECKPOINTS["US"], sha256=None))
        self.refused("US: no checkpoint file SHA-256", checkpoints=bad)
        path = self.register()
        self.assertEqual(json.loads(path.read_text())["checkpoints"], CHECKPOINTS)

    def test_rows_from_stale_checkpoints_are_refused(self):
        rows = [dict(r) for r in self.rows]
        for row in rows:
            row["collection"] = dict(status="ok", stale=[])
        rows[0]["collection"] = dict(status="ok", stale=["offline"])
        rows[3]["collection"] = dict(status="ok", stale=["code_changed"])
        self.refused(r"2 rows come from stale checkpoints", rated=rows)
        rows[0]["collection"] = rows[3]["collection"] = dict(status="ok", stale=[])
        self.assertTrue(self.register(rated=rows).exists())


class WindowTests(Gated):
    """D3: T is the month's last session, the month is over, the window is open and
    months strictly increase."""

    def test_registration_window_closes_after_five_sessions(self):
        # Fri Nov 6 is the fifth session after Fri Oct 30: still inside the window
        # (06:00 UTC is Nov 6 in New York, 01:00, and in Seoul, 15:00).
        self.clock = datetime(2026, 11, 6, 6, 0, tzinfo=timezone.utc)
        dry = self.register(dry_run=True)
        self.assertEqual(json.loads(dry.read_text())["issues"], [])
        self.clock = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "window closed on 2026-11-06"):
            self.register()
        dry = json.loads(self.register(dry_run=True).read_text())
        self.assertEqual(len(dry["calendar"]["US"]["sessionsAfterAsOf"]), 5)
        self.assertTrue(any("window closed" in i for i in dry["issues"]))
        self.assertEqual(self.events(registry.EVENT_TYPE), [])

    def test_as_of_must_be_the_last_session_of_an_ended_month(self):
        as_of = {"US": "2026-10-29", "KR": "2026-10-29"}
        with self.assertRaisesRegex(ValueError, "not the last session"):
            self.register(as_of=as_of, rated=rated(self.universe, as_of))
        holiday = {m: calendar(m, NOW, skip={"2026-10-30"}) for m in ("US", "KR")}
        with self.assertRaisesRegex(ValueError, "2026-10-30 is not a .* session"):
            self.register(calendars=holiday)
        # Sat Oct 31 08:00 in New York: no later session yet, but October is not over.
        self.clock = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "2026-10 has not ended"):
            self.register()
        self.assertEqual(self.events(), [])

    def test_calendar_must_be_fetched_for_the_registration(self):
        with self.assertRaisesRegex(ValueError, "no \\^SP500TR series"):
            self.register(calendars={"KR": calendar("KR", NOW)})
        old = {m: calendar(m, NOW - timedelta(days=3)) for m in ("US", "KR")}
        with self.assertRaisesRegex(ValueError, "not retrieved for this registration"):
            self.register(calendars=old)
        wrong = {m: dict(calendar(m, NOW), symbol="SPY") for m in ("US", "KR")}
        with self.assertRaisesRegex(ValueError, "series for the session rules"):
            self.register(calendars=wrong)

    def test_months_strictly_increase(self):
        later = universe("2026-11-30", captured=NOVEMBER)
        as_of = {"US": "2026-11-30", "KR": "2026-11-30"}
        self.clock = datetime(2026, 12, 1, 23, 0, tzinfo=timezone.utc)
        self.register(as_of=as_of, universe=later, rated=rated(later, as_of))
        # October's window is closed anyway; the order rule refuses it on its own too.
        with mock.patch.object(
            registry, "_calendars", return_value=({}, []), create=True
        ), mock.patch.object(registry, "_timing", return_value=[]):
            with self.assertRaisesRegex(ValueError, "Months must increase"):
                self.register()
        self.assertEqual([e["month"] for e in self.events()], ["2026-11"])
        self.clock += timedelta(minutes=1)  # an identical rerun is still idempotent
        self.register(as_of=as_of, universe=later, rated=rated(later, as_of))
        self.assertEqual(len(self.events()), 1)


class UniverseRuleTests(Gated):
    """D5', D6, D11 and D11': per-market universe timing, exclusions, fetch errors and
    pinned references and rules."""

    def refused_universe(self, built, pattern):
        return self.refused(pattern, universe=built, rated=rated(built))

    def test_each_market_is_captured_after_its_own_close(self):
        """D5': the KR part captured on T's evening and the US part once SSGA posted
        T's holdings (the next US business day) register together."""
        content = json.loads(self.register(dry_run=True).read_text())
        self.assertEqual(content["issues"], [])
        timing = content["universe"]["timing"]
        self.assertEqual(timing["US"]["capturedAt"]["last"], CAPTURED["US"])
        self.assertEqual(timing["KR"]["rankingBasis"], "T_close")
        # 14:00 KST on T is before the KRX close.
        early = universe(captured=dict(CAPTURED, KR="2026-10-30T05:00:00+00:00"))
        self.refused_universe(early, "KR: universe captured from .* not after the")
        # 15:30 New York on T: the SPY file cannot hold T's holdings yet.
        early = universe(captured=dict(CAPTURED, US="2026-10-30T19:30:00+00:00"))
        self.refused_universe(early, "US: universe captured from .* not after the")
        late = universe(captured=dict(CAPTURED, US="2026-11-02T12:30:00+00:00"))
        self.refused_universe(late, "US: universe captured at .* after")

    def test_market_facts_must_be_those_of_t(self):
        built = universe()
        built["markets"]["US"]["holdingsAsOf"] = "2026-10-29"
        self.refused_universe(built, "SPY holdings as of 2026-10-29")
        built = universe()
        built["markets"]["KR"]["rankingBasis"] = "naver_current"
        self.refused_universe(built, "KR: members ranked on naver_current, not T_close")
        built = universe()
        built["asOfByMarket"]["KR"] = "2026-10-29"
        self.refused_universe(built, "KR: universe part built for 2026-10-29")

    def test_a_single_unmerged_build_has_no_capture_times(self):
        built = universe()
        for info in built["markets"].values():
            del info["capturedAt"]
        self.refused_universe(built, "US: the universe has no capture times")
        built = {k: v for k, v in universe().items() if k != "mergedAt"}
        self.refused_universe(built, "not a merge of market parts")

    def test_only_financial_rules_exclude_and_fetch_errors_are_capped(self):
        built = universe()
        built["members"][0].update(status="excluded", reason="submissions_unavailable")
        self.refused_universe(built, "non-financial reasons")
        built = universe()  # 1 of 6 non-financial US members is over 5%
        built["members"][0]["issues"] = [registry.FETCH_ERROR]
        self.refused_universe(built, "fetch errors for 1 of 6")
        built = universe(us=20)  # 1 of 20 is 5%: allowed, counted as not computable
        built["members"][0]["issues"] = [registry.FETCH_ERROR]
        content = json.loads(
            self.register(universe=built, rated=rated(built)).read_text()
        )
        labels = content["labels"]["US"]
        self.assertEqual((labels["nonFinancial"], labels["scored"]), (20, 19))
        self.assertAlmostEqual(labels["computableRate"], 19 / 20)
        self.assertEqual(content["universe"]["counts"]["US"]["fetchErrors"], 1)

    def test_kr_candidates_are_left_unranked_only_by_a_halt_or_unknown_symbol(self):
        """M3: a failed or rejected price download never leaves a KR candidate out of
        the ranking (the 201st company would replace it): the universe is refused. N1:
        a chart without a session through T (listed after T) is an accepted reason."""
        kept = [
            dict(code="000770", poolRank=40, reason="no_close_on_as_of", detail="halt"),
            dict(code="000780", poolRank=41, reason="symbol_not_found", detail="404"),
            dict(
                code="000800", poolRank=43, reason="not_listed_on_as_of", detail="IPO"
            ),
        ]
        self.assertEqual(registry.UNRANKED, universes.UNRANKED_REASONS)
        built = universe()
        built["markets"]["KR"]["unranked"] = kept
        content = json.loads(
            self.register(dry_run=True, universe=built, rated=rated(built)).read_text()
        )
        self.assertEqual(content["issues"], [])
        for reason in ("price_unavailable", "listed_shares_unavailable", None):
            with self.subTest(reason=reason):
                built = universe()
                built["markets"]["KR"]["unranked"] = kept + [
                    dict(code="000790", poolRank=42, reason=reason, detail="x")
                ]
                self.refused_universe(
                    built,
                    re.escape(f"KR: candidates left unranked for {{'{reason}': 1}}"),
                )
        us_rows = [r for r in rated(built) if r["market"] == "US"]
        self.register(as_of={"US": "2026-10-30"}, universe=built, rated=us_rows)

    def test_a_part_built_offline_is_never_registered(self):
        """M2: a part replayed offline from stored originals (markets[m].online not
        True) is refused for a registered market; a dry run keeps the issue; a market
        left out of the registration is not checked."""
        for value in (False, None, "true", 1):
            with self.subTest(online=value):
                built = universe()
                built["markets"]["KR"]["online"] = value
                self.refused_universe(
                    built,
                    re.escape(f"KR: universe part not built online (online {value!r})"),
                )
        built = universe()
        del built["markets"]["US"]["online"]  # a merge of parts without the field
        content = self.refused_universe(built, "US: universe part not built online")
        self.assertFalse(any(i.startswith("KR:") for i in content["issues"]))
        built = universe()
        built["markets"]["KR"]["online"] = False
        us_rows = [r for r in rated(built) if r["market"] == "US"]
        self.register(as_of={"US": "2026-10-30"}, universe=built, rated=us_rows)
        self.assertEqual(len(self.events()), 1)

    def test_the_computability_check_universe_is_never_registered(self):
        """H1: a universe merged from <T>-gate/ parts sets the coverage gate only."""
        self.refused_universe(
            universe(gate=True),
            "US: the computability-check universe .*2026-10-30-gate/US.json.* is "
            "never registered",
        )

    def test_pinned_references_rules_and_money(self):
        built = universe()
        built["markets"]["US"]["ff12Hash"] = "f" * 64
        self.refused_universe(built, "FF12 definition differs")
        built = universe()
        next(s for s in built["sources"] if s["key"] == "ksic-ff12")["sha256"] = (
            "e" * 64
        )
        self.refused_universe(built, "KSIC reference differs")
        built = universe()
        built["rules"]["KR"]["top"] = 150
        self.refused_universe(built, "universe rules differ")
        built = universe()
        built["members"][1]["sector"] = "Money"
        self.refused_universe(built, "eligible members in the Money sector")
        with mock.patch.dict(universes.RULES["KR"], top=10):
            with self.assertRaisesRegex(ValueError, "universe.RULES changed"):
                self.register()

    def test_ksic_table_must_match_its_literal_pin(self):
        """D11': the pinned table file itself is checked, not a hash taken at import."""
        self.assertEqual(registry._pin("ksicReferenceSha256"), KSIC)
        with tempfile.TemporaryDirectory() as folder:
            edited = Path(folder) / "ksic-ff12.json"
            edited.write_bytes(sectors.KSIC_REFERENCE.read_bytes() + b"\n")
            with mock.patch.object(sectors, "KSIC_REFERENCE", edited):
                self.refused("ksic-ff12.json does not match the PROTOCOL pin")
                us_rows = [r for r in self.rows if r["market"] == "US"]
                with self.assertRaisesRegex(ValueError, "does not match the PROTOCOL"):
                    self.register(as_of={"US": "2026-10-30"}, rated=us_rows)

    def test_code_files_are_hashed(self):
        content = json.loads(self.register().read_text())
        files = content["codeFiles"]
        root = registry.CODE_ROOT
        self.assertIn("scripts/ratings.py", files)
        self.assertEqual(
            set(files) - {"scripts/ratings.py"},
            {p.relative_to(root).as_posix() for p in (root / "ratings").glob("*.py")},
        )
        self.assertEqual(
            files["ratings/registry.py"],
            digest((root / "ratings/registry.py").read_bytes()),
        )
        self.assertEqual(registry.code_digest(), digest(canonical(files)))
        self.assertEqual(content["settings"]["registrationWindowSessions"], 5)


class MergeTests(unittest.TestCase):
    """D5': per-market parts merge into one universe that keeps each market's times."""

    def parts(self):
        us = part("US", "2026-10-30", [member("US:1", "US")], CAPTURED["US"])
        kr = part("KR", "2026-10-30", [member("KR:000010", "KR")], CAPTURED["KR"])
        return dict(US=us, KR=kr)

    def test_merge_keeps_each_markets_build_and_capture(self):
        parts = self.parts()
        parts["KR"]["sources"].append(
            manifest("dart-company-1", provider="OpenDART", retrievedAt=NOW.isoformat())
        )
        files = {m: dict(file=f"{m}.json", sha256="a" * 64) for m in parts}
        merged = registry.merge_universe(parts, files=files, now="2026-11-02T11:00Z")
        self.assertEqual(merged["asOfByMarket"], AS_OF)
        self.assertEqual([m["id"] for m in merged["members"]], ["US:1", "KR:000010"])
        kr = merged["markets"]["KR"]
        self.assertEqual(kr["builtAt"], CAPTURED["KR"])
        # The Naver ranking and the Yahoo closes fix KR in time, not OpenDART.
        self.assertEqual(kr["capturedAt"]["last"], CAPTURED["KR"])
        self.assertEqual(kr["part"], files["KR"])
        self.assertEqual(merged["builtAt"], CAPTURED["US"])
        self.assertEqual(len(merged["sources"]), 5)

    def test_parts_must_be_successful_single_market_builds_alike(self):
        parts = self.parts()
        parts["US"]["rules"] = dict(parts["US"]["rules"], extra=1)
        with self.assertRaisesRegex(ValueError, "differ in rules"):
            registry.merge_universe(parts)
        parts = self.parts()
        parts["KR"]["markets"]["KR"]["status"] = "error"
        with self.assertRaisesRegex(ValueError, "not a successful build"):
            registry.merge_universe(parts)
        parts = self.parts()
        parts["US"]["members"].append(member("KR:000020", "KR"))
        with self.assertRaisesRegex(ValueError, "holds other markets"):
            registry.merge_universe(parts)
        parts = self.parts()
        parts["KR"] = part("KR", "2026-11-30", [], CAPTURED["KR"])
        with self.assertRaisesRegex(ValueError, "different months"):
            registry.merge_universe(parts)
        with self.assertRaisesRegex(ValueError, "no universe parts"):
            registry.merge_universe({})


class GateTests(Ledgered):
    """D10, D10': a passing coverage gate under this protocol before a market's first
    registration."""

    def test_registration_needs_a_passing_gate(self):
        with self.assertRaisesRegex(ValueError, "US: no coverage gate"):
            self.register()
        self.gates(US="pass", KR="fail")
        with self.assertRaisesRegex(ValueError, "KR: failed its coverage gate"):
            self.register()
        us_rows = [r for r in self.rows if r["market"] == "US"]
        path = self.register(as_of={"US": "2026-10-30"}, rated=us_rows)
        self.assertEqual(set(json.loads(path.read_text())["gates"]), {"US"})
        event, created = registry.record_gate(
            "KR", self.universe, computable=6, collection={}
        )
        self.assertEqual((event["verdict"], created), ("fail", False))  # final

    def test_failed_us_gate_blocks_every_registration(self):
        self.gates(US="fail", KR="pass")
        kr_rows = [r for r in self.rows if r["market"] == "KR"]
        with self.assertRaisesRegex(ValueError, "US failed its coverage gate"):
            self.register(as_of={"KR": "2026-10-30"}, rated=kr_rows)
        self.assertEqual(self.events(), [])

    def test_gate_recorded_after_a_first_registration_does_not_count(self):
        self.gates(US="pass", KR=None)
        ledger.append(  # a Korean registration recorded without a gate (older code)
            registry.LEDGER,
            dict(
                eventId="ratings-v1:2026-09",
                type=registry.EVENT_TYPE,
                asOf={"KR": "2026-09-30"},
                protocolHash=PROTOCOL_HASH,
            ),
        )
        self.gates(US=None, KR="pass")
        with self.assertRaisesRegex(
            ValueError, "recorded after its first registration"
        ):
            self.register()

    def test_gates_must_carry_this_protocol_and_the_pinned_as_of(self):
        self.gates(US="pass", KR=None)
        ledger.append(registry.LEDGER, gate_event("KR", asOf="2026-09-30"))
        self.refused("KR: coverage gate computed at 2026-09-30, not the pinned")

    def test_ledger_events_under_another_protocol_freeze_v1(self):
        """D11': a gate or registration recorded under another protocol hash blocks
        every formal registration; a change needs ratings-v2."""
        self.gates(protocolHash="0" * 64)
        content = self.refused(r"ratings-v1 is frozen")
        self.assertTrue(
            any(
                "coverage gate recorded under protocol 000000000000" in i
                for i in content["issues"]
            )
        )


class RecordGateTests(Ledgered):
    """D10': record_gate checks the date, the universe and the collection itself and
    computes the verdict."""

    CHECKED = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)  # 08:00 NY, 21:00 KST
    # Monday Oct 19's captures: Korea at 19:00 KST, the US at 07:00 New York on Oct 20.
    GATE_CAPTURE = dict(US="2026-10-20T11:00:00+00:00", KR="2026-10-19T10:00:00+00:00")

    def setUp(self):
        super().setUp()
        self.clock = self.CHECKED
        self.built = universe(
            GATE_AS_OF, us=20, kr=6, captured=self.GATE_CAPTURE, gate=True
        )
        # N7: the part files the merges record (part_files: content "<stem>/<market>")
        # and the merged file, in a temp universe folder.
        self.folder = self.root / "universe"
        patcher = mock.patch.object(universes, "UNIVERSE_DIR", self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        for stem in (f"{GATE_AS_OF}-gate", GATE_AS_OF, "2026-10-16-gate"):
            for market in ("US", "KR"):
                path = self.folder / stem / f"{market}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"{stem}/{market}".encode())
        self.merged = self.folder / f"{GATE_AS_OF}-gate.json"
        self.full = dict(
            US=dict(
                eligible=20,
                fetchErrors=0,
                collected=20,
                notCollected=0,
                stale=0,
                errors=0,
            ),
            KR=dict(
                eligible=6,
                fetchErrors=0,
                collected=6,
                notCollected=0,
                stale=0,
                errors=0,
            ),
        )

    def checkpoint(self, market) -> dict:
        """L1: the checkpoint file the gate's counts were read from."""
        return {
            market: dict(
                file=f"data/ratings/work/{GATE_AS_OF}-gate/{market}.jsonl",
                sha256=digest(f"gate-{market}".encode()),
                bytes=1234,
                records=20 if market == "US" else 6,
                unreadableLines=0,
            )
        }

    def record(self, market, computable, built=None, **kwargs):
        """record_gate as coverage calls it: ``built`` read from the merged file."""
        built = built or self.built
        common.write_json(self.merged, built)
        args = dict(
            computable=computable,
            collection=self.full[market],
            checkpoints=self.checkpoint(market),
            calendars={m: calendar(m, self.clock) for m in ("US", "KR")},
            universe_file=self.merged,
            universeFile="data/ratings/universe/2026-10-19-gate.json",
        )
        args.update(kwargs)
        return registry.record_gate(market, built, **args)

    def test_verdict_rate_and_threshold_are_computed_here(self):
        event, created = self.record("US", 18)  # 18 of 20 is exactly the 90% threshold
        self.assertTrue(created)
        self.assertEqual(
            (event["verdict"], event["rate"], event["threshold"]), ("pass", 0.9, 0.9)
        )
        self.assertEqual((event["computable"], event["nonFinancial"]), (18, 20))
        self.assertEqual(
            (event["asOf"], event["checkDate"]), (GATE_AS_OF, "2026-10-20")
        )
        self.assertEqual(event["protocolHash"], PROTOCOL_HASH)
        self.assertEqual(event["universeSha256"], digest(canonical(self.built)))
        self.assertEqual(
            event["universeFile"], "data/ratings/universe/2026-10-19-gate.json"
        )
        # L1: the merge, its part files and the checkpoint file, to re-verify it.
        self.assertEqual(event["mergedAt"], self.built["mergedAt"])
        self.assertEqual(event["universeParts"], part_files(GATE_AS_OF, gate=True))
        self.assertEqual(event["checkpoints"], self.checkpoint("US"))
        kr, _ = self.record("KR", 4)  # 4 of 6 is below 80%
        self.assertEqual((kr["verdict"], kr["threshold"]), ("fail", 0.8))
        again, created = self.record("US", 20)
        self.assertEqual((again["verdict"], created), ("pass", False))  # final
        self.assertEqual(len(self.events(registry.GATE_TYPE)), 2)

    def test_nothing_is_recorded_before_the_check_date_or_incomplete(self):
        self.clock = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)  # Oct 19 in NY
        with self.assertRaisesRegex(ValueError, "on or after 2026-10-20"):
            self.record("US", 20)
        self.clock = self.CHECKED
        for gap in (dict(errors=1), dict(stale=2), dict(notCollected=1)):
            with self.subTest(gap=gap):
                with self.assertRaisesRegex(ValueError, "incomplete collection"):
                    self.record("US", 20, collection=dict(self.full["US"], **gap))
        with self.assertRaisesRegex(ValueError, "computable 21 of 20"):
            self.record("US", 21)
        smoke = dict(self.built, limit=5)
        with self.assertRaisesRegex(ValueError, "limited"):
            self.record("US", 20, built=smoke)
        self.assertEqual(self.events(registry.GATE_TYPE), [])

    def test_universe_must_pass_the_registration_checks(self):
        # Holdings of Oct 20: captured a day too late for T = Oct 19.
        built = universe(GATE_AS_OF, us=20, captured=self.GATE_CAPTURE, gate=True)
        built["markets"]["US"]["holdingsAsOf"] = "2026-10-20"
        with self.assertRaisesRegex(ValueError, "SPY holdings as of 2026-10-20"):
            self.record("US", 20, built=built)
        # Korea ranked on 14:00 KST prices of T: before the close.
        early = dict(self.GATE_CAPTURE, KR="2026-10-19T05:00:00+00:00")
        built = universe(GATE_AS_OF, us=20, captured=early, gate=True)
        with self.assertRaisesRegex(ValueError, "not after the 2026-10-19 close"):
            self.record("KR", 6, built=built)
        # A rehearsal universe of another T is not the pinned check.
        other = universe("2026-10-16", us=20, captured=self.GATE_CAPTURE, gate=True)
        with self.assertRaisesRegex(ValueError, "built for 2026-10-16"):
            self.record("US", 20, built=other)
        self.assertEqual(self.events(registry.GATE_TYPE), [])

    def test_a_gate_universe_built_offline_sets_no_gate(self):
        """M2: the gated market's part must have been built online; the other
        market's part is not the gate's concern."""
        built = universe(GATE_AS_OF, us=20, kr=6, captured=self.GATE_CAPTURE, gate=True)
        built["markets"]["KR"]["online"] = False
        with self.assertRaisesRegex(
            ValueError, re.escape("KR: universe part not built online (online False)")
        ):
            self.record("KR", 6, built=built)
        self.assertEqual(self.events(registry.GATE_TYPE), [])
        event, created = self.record("US", 20, built=built)
        self.assertEqual((created, event["market"]), (True, "US"))

    def test_only_the_gate_universe_and_its_checkpoints_set_a_gate(self):
        """H1, L1: the gate comes from the computability-check universe (parts saved in
        <T>-gate/ with their SHA-256), never the month's, and names its checkpoints."""
        month = universe(GATE_AS_OF, us=20, captured=self.GATE_CAPTURE)
        with self.assertRaisesRegex(
            ValueError, "US: not the computability-check universe"
        ):
            self.record("US", 20, built=month)
        unsigned = universe(GATE_AS_OF, us=20, captured=self.GATE_CAPTURE, gate=True)
        unsigned["markets"]["KR"]["part"] = dict(
            unsigned["markets"]["KR"]["part"], sha256=None
        )
        with self.assertRaisesRegex(ValueError, "KR: not the computability-check"):
            self.record("KR", 6, built=unsigned)
        self.record("US", 20, built=unsigned)  # only the gate market's part counts
        with self.assertRaisesRegex(ValueError, "KR: no checkpoint file SHA-256"):
            self.record("KR", 6, checkpoints={})
        self.assertEqual([e["market"] for e in self.events(registry.GATE_TYPE)], ["US"])

    def test_the_files_are_re_hashed_when_the_gate_is_recorded(self):
        """N7: the merged file must still hold the universe being recorded and every
        part file the merge records must still have its SHA-256 (a part rebuilt with
        --overwrite whose re-merge failed does not); otherwise nothing is recorded."""
        part = self.folder / f"{GATE_AS_OF}-gate/KR.json"
        part.write_bytes(b"rebuilt, not merged")
        for market, computable in (("US", 20), ("KR", 6)):  # any recorded part
            with self.subTest(market=market), self.assertRaisesRegex(
                ValueError,
                f"KR: part data/ratings/universe/{GATE_AS_OF}-gate/KR.json on disk "
                r"\(sha256 [0-9a-f]{16}\) is not the one the merge recorded",
            ):
                self.record(market, computable)
        part.unlink()
        with self.assertRaisesRegex(ValueError, r"unreadable: FileNotFoundError"):
            self.record("US", 20)
        part.write_bytes(f"{GATE_AS_OF}-gate/KR".encode())  # as merged
        # The merge was rewritten after coverage read it (a new mergedAt).
        args = dict(
            computable=20,
            collection=self.full["US"],
            checkpoints=self.checkpoint("US"),
            calendars={m: calendar(m, self.clock) for m in ("US", "KR")},
            universe_file=self.merged,
        )
        remerged = dict(self.built, mergedAt="2026-10-20T11:30:00+00:00")
        common.write_json(self.merged, remerged)
        with self.assertRaisesRegex(
            ValueError, f"{GATE_AS_OF}-gate.json no longer holds the universe"
        ):
            registry.record_gate("US", self.built, **args)
        with self.assertRaisesRegex(ValueError, "no merged universe file given"):
            self.record("US", 20, universe_file=None)
        self.assertEqual(self.events(registry.GATE_TYPE), [])
        event, created = self.record("US", 20)  # the files as merged: recorded
        self.assertTrue(created)
        self.assertEqual(
            event["universeFile"], "data/ratings/universe/2026-10-19-gate.json"
        )
        self.assertEqual(event["universeSha256"], digest(canonical(self.built)))
        # Without a display name the event names the file the gate was checked on.
        args.update(computable=6, collection=self.full["KR"])
        args.update(checkpoints=self.checkpoint("KR"))
        kr, _ = registry.record_gate("KR", self.built, **args)
        self.assertEqual(kr["universeFile"], str(self.merged))

    def test_capture_must_fall_inside_the_window(self):
        # Captured Tue Oct 27 in Seoul: five sessions (Oct 20-26) after Oct 19.
        late = dict(self.GATE_CAPTURE, KR="2026-10-27T10:00:00+00:00")
        built = universe(GATE_AS_OF, us=20, captured=late, gate=True)
        self.clock = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "after the registration window"):
            self.record("KR", 6, built=built)
        with self.assertRaisesRegex(ValueError, "no session calendar"):
            self.record("KR", 6, built=built, calendars={})
        self.assertEqual(self.events(registry.GATE_TYPE), [])

    def test_a_ledger_under_another_protocol_takes_no_gate(self):
        ledger.append(registry.LEDGER, gate_event("US", protocolHash="0" * 64))
        with self.assertRaisesRegex(ValueError, "ratings-v1 is frozen"):
            self.record("KR", 6)


class RealStoreTests(unittest.TestCase):
    def test_module_defaults_point_at_the_ratings_store(self):
        self.assertEqual(registry.REGISTRATIONS, common.ROOT / "data/ratings/v1")
        self.assertEqual(registry.LEDGER, common.ROOT / "data/ratings/ledger.jsonl")
        self.assertEqual(registry.DRY_RUNS, common.ROOT / "data/ratings/dry-run")

    def test_patched_registration_never_touches_the_real_store(self):
        real = [common.REGISTRATIONS, common.LEDGER, common.RATINGS / "dry-run"]

        def state():
            return [
                (p.exists(), p.stat().st_mtime_ns if p.exists() else None) for p in real
            ]

        before = state()
        tests = RegistryTests("test_registration_is_written_once_and_ledgered")
        result = unittest.TestResult()
        tests.run(result)
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
        self.assertEqual(state(), before)


if __name__ == "__main__":
    unittest.main()
