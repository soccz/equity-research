import copy
from datetime import date, timedelta
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from equitylab import forward_study as study
from equitylab.data import ROOT, canonical, digest

from ratings import evaluate as ev
from ratings.common import protocol_hash
from ratings.rating import AVOID, PREFER, PROTOCOL, PROTOCOL_HASH, WATCH


def business_days(start: str, end: str) -> list:
    day, out = date.fromisoformat(start), []
    while day <= date.fromisoformat(end):
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


DAYS = business_days("2026-10-26", "2027-01-29")
# 12:00 UTC is the same calendar day in New York (07:00) and Seoul (21:00).
OCTOBER_AT = "2026-11-02T12:00:00+00:00"
NOVEMBER_AT = "2026-12-01T12:00:00+00:00"
DECEMBER_AT = "2027-01-04T12:00:00+00:00"
AS_OF = {"2026-10": "2026-10-30", "2026-11": "2026-11-30", "2026-12": "2026-12-31"}
THROUGH = "2026-12-15"

# Adjusted-close steps: period 1 runs Nov 3 -> Dec 2, period 2 Dec 2 -> Dec 15.
STEPS = {
    "A": [("2026-10-26", 100), ("2026-12-02", 110), ("2026-12-15", 121)],
    "B": [("2026-10-26", 100), ("2026-11-30", 95)],
    "C": [("2026-10-26", 50), ("2026-12-02", 45)],
    "D": [("2026-10-26", 200), ("2026-12-02", 260), ("2026-12-15", 247)],
    "E": [("2026-10-26", 100), ("2026-12-02", 105), ("2026-12-15", 110.25)],
    "F": [("2026-10-26", 100), ("2026-12-02", 500)],
    "G": [("2026-10-26", 100)],
    "I": [("2026-10-26", 100)],
    "INDEX": [("2026-10-26", 1000), ("2026-12-02", 1050), ("2026-12-15", 1071)],
}
UNTIL = {"B": "2026-11-30"}  # delisted after Nov 30
SKIP = {"I": {"2026-12-02"}}  # no trade on period 2's entry session


def price_rows(name: str) -> list:
    rows = []
    for day in DAYS:
        if day > UNTIL.get(name, "9999") or day in SKIP.get(name, ()):
            continue
        value = float([v for start, v in STEPS[name] if start <= day][-1])
        rows.append([day, value, value])
    return rows


def symbol(market: str, name: str) -> str:
    if name == "INDEX":
        return PROTOCOL["benchmarks"][market]
    return name * 3 if market == "US" else f"{ord(name):06d}.KS"


def series() -> dict:
    out = {symbol(m, name): price_rows(name) for m in ("US", "KR") for name in STEPS}
    return out


def row(market, name, sector, label, composite=None, z=(None, None, None), reason=None):
    if reason is None:
        reason = "tercile" if label else "insufficient"
    return dict(
        id=f"{market}:{name}",
        market=market,
        sector=sector,
        priceSymbol=symbol(market, name) if name != "H" else "HHH-missing",
        status="excluded" if reason == "excluded" else "eligible",
        reason="financial_sic" if reason == "excluded" else None,
        label=label,
        labelReason=reason,
        composite=composite,
        z=dict(zip(("fcfYield", "cashProfitability", "momentum12_1"), z)),
    )


def october_rows(market: str) -> list:
    return [
        row(market, "A", "S1", PREFER, 1.0, (1.0, None, 5.0)),
        row(market, "B", "S1", WATCH, 0.0, (2.0, None, 4.0)),
        row(market, "C", "S2", AVOID, -1.0, (3.0, None, 3.0)),
        row(market, "D", "S2", PREFER, 0.5, (4.0, None, 2.0)),
        row(market, "E", "S2", WATCH, 0.2, (5.0, None, 1.0)),
        row(market, "G", "S1", None, None, (None, None, 0.0)),
        row(market, "H", "S1", WATCH, 0.1),
        row(market, "F", "Money", None, reason="excluded"),
    ]


def november_rows(market: str) -> list:
    return [
        row(market, "A", "S1", PREFER, 0.9),
        row(market, "B", "S1", WATCH, 0.0),
        row(market, "C", "S2", AVOID, -1.0),
        row(market, "D", "S2", WATCH, 0.3),
        row(market, "E", "S2", PREFER, 0.8),
        row(market, "G", "S1", None),
        row(market, "I", "S2", WATCH, 0.1),
        row(market, "F", "Money", None, reason="excluded"),
    ]


def registration(
    month, at, rows, kind="registration", protocol=None, recorded=None
) -> dict:
    """A registration as registry.registrations() returns it (with its ledger block)."""
    protocol = protocol or PROTOCOL
    markets = sorted({r["market"] for r in rows})
    out = dict(
        version="ratings-v1",
        kind=kind,
        protocol=protocol,
        protocolHash=protocol_hash(protocol),
        month=month,
        asOf={m: AS_OF[month] for m in markets},
        registeredAt=at,
        rows=rows,
    )
    if kind == "registration":
        out["ledger"] = dict(
            eventId=f"ratings-v1:{month}",
            recordedAt=recorded or at,
            hash=digest(month.encode()),
            sequence=0,
        )
    return out


def both(make) -> list:
    return make("US") + make("KR")


def periods(result: dict, market: str) -> list:
    return [p for p in result["periods"] if p["market"] == market]


class MetricTests(unittest.TestCase):
    def test_spearman_on_constructed_examples(self):
        self.assertAlmostEqual(ev.spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]), 0.8)
        self.assertAlmostEqual(ev.spearman([1, 2, 3], [30, 20, 10]), -1.0)
        tied = ev.spearman([5, 2, 1, 4, 3], [4.5, 2, 1, 4.5, 3])
        self.assertAlmostEqual(tied, 9.5 / math.sqrt(10 * 9.5))
        self.assertIsNone(ev.spearman([1, 2], [1, 2]))
        self.assertIsNone(ev.spearman([1, 2, 3], [7, 7, 7]))

    def test_majority_calendar_ignores_stray_rows(self):
        days = business_days("2026-11-02", "2026-11-06")
        full = [[d, 1.0, 1.0] for d in days]
        stray = full + [["2026-11-07", 1.0, 1.0]]
        halted = [r for r in full if r[0] != "2026-11-04"]
        thin = [r for r in full if r[0] not in ("2026-11-04", "2026-11-05")]
        calendar = ev.market_calendar(
            [full, stray, halted, thin], "2026-11-01", "2026-11-30"
        )
        self.assertEqual(calendar, days)
        self.assertEqual(
            ev.market_calendar([full, stray], "2026-11-03", "2026-11-05"),
            ["2026-11-04", "2026-11-05"],
        )

    def test_holding_rules(self):
        rows = [["2026-11-03", 10.0, 10.0], ["2026-11-05", 11.0, 11.0]]
        self.assertEqual(
            ev.holding([], "2026-11-03", "2026-11-06")["reason"], "no_price_series"
        )
        self.assertEqual(
            ev.holding(rows, "2026-11-05", "2026-11-05")["reason"], "no_entry_price"
        )
        # D2: no close on the entry session is no entry at all, not a late one.
        self.assertEqual(
            ev.holding(rows, "2026-11-04", "2026-11-06"), dict(reason="no_entry_price")
        )
        last = ev.holding(rows, "2026-11-03", "2026-11-06")
        self.assertEqual(last["flags"], ["last_price"])
        self.assertAlmostEqual(last["return"], 0.1)
        exact = ev.holding(rows, "2026-11-03", "2026-11-05")
        self.assertEqual(exact["flags"], [])
        self.assertAlmostEqual(exact["return"], 0.1)
        bad = [
            ["2026-11-03", None, 10.0],
            ["2026-11-04", 10.0, 10.0],
            ["2026-11-05", 12.0, 0],
        ]
        self.assertEqual(
            ev.holding(bad, "2026-11-03", "2026-11-05")["reason"], "no_entry_price"
        )
        self.assertEqual(
            ev.holding(bad, "2026-11-04", "2026-11-05")["entryDate"], "2026-11-04"
        )
        # D12': a series that starts after the entry session does not cover the period
        # (a reused ticker, a reset history): not a missing entry price.
        self.assertEqual(
            ev.holding(rows, "2026-11-02", "2026-11-05"),
            dict(reason="series_not_covering"),
        )
        # M4: a series that ends before the entry session (delisted, renamed or
        # truncated before it) leaves the member out of the period, never as a missing
        # entry price: the caller counts it as an error.
        self.assertEqual(
            ev.holding(rows, "2026-11-06", "2026-11-09"),
            dict(reason="series_ends_before_entry"),
        )
        self.assertIn("series_ends_before_entry", ev.SERIES_ERRORS)
        self.assertNotIn("no_entry_price", ev.SERIES_ERRORS)


class EvaluateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registrations = [
            registration("2026-10", OCTOBER_AT, both(october_rows)),
            registration("2026-11", NOVEMBER_AT, both(november_rows)),
        ]
        cls.result = ev.evaluate(list(reversed(cls.registrations)), series(), THROUGH)

    def test_periods_entry_exit_and_status(self):
        for market in ("US", "KR"):
            first, second = periods(self.result, market)
            self.assertEqual(
                (first["status"], first["entry"], first["exit"], first["flags"]),
                ("complete", "2026-11-03", "2026-12-02", []),
            )
            self.assertEqual(first["registrationDay"], "2026-11-02")
            self.assertEqual(first["recordedAt"], OCTOBER_AT)
            self.assertEqual(
                (second["status"], second["entry"], second["exit"]),
                ("in_progress", "2026-12-02", "2026-12-15"),
            )
        self.assertEqual(self.result["issues"], [])
        self.assertEqual(self.result["protocolHash"], PROTOCOL_HASH)

    def test_first_period_returns_excess_and_costs(self):
        p = periods(self.result, "US")[0]
        members = {m["id"]: m for m in p["members"]}
        self.assertAlmostEqual(members["US:A"]["return"], 0.10)
        self.assertAlmostEqual(members["US:B"]["return"], -0.05)
        self.assertEqual(members["US:B"]["flags"], ["last_price"])
        self.assertEqual(members["US:B"]["exitDate"], "2026-11-30")
        self.assertEqual(members["US:H"]["reason"], "no_price_series")
        self.assertNotIn("US:F", members)
        self.assertAlmostEqual(p["sectors"]["S1"]["mean"], (0.10 - 0.05 + 0.0) / 3)
        self.assertAlmostEqual(p["sectors"]["S2"]["mean"], (-0.10 + 0.30 + 0.05) / 3)
        self.assertAlmostEqual(members["US:D"]["sectorExcess"], 0.30 - 0.25 / 3)
        prefer = p["portfolios"][PREFER]
        self.assertEqual((prefer["members"], prefer["held"]), (2, 2))
        self.assertAlmostEqual(prefer["gross"], 0.20)
        self.assertAlmostEqual(prefer["sectorExcess"], 0.15)
        self.assertAlmostEqual(prefer["universeExcess"], 0.20 - 0.05)
        self.assertAlmostEqual(prefer["bought"], 1.0)
        self.assertAlmostEqual(prefer["sold"], 0.0)
        self.assertAlmostEqual(prefer["cost"], 0.0005)
        self.assertAlmostEqual(prefer["netSectorExcess"], 0.15 - 0.0005)
        self.assertAlmostEqual(prefer["netUniverseExcess"], 0.15 - 0.0005)
        avoid = p["portfolios"][AVOID]
        self.assertAlmostEqual(avoid["sectorExcess"], -0.10 - 0.25 / 3)
        # 회피 is reported gross: no costs are charged against it.
        self.assertFalse(avoid["costsApplied"])
        self.assertEqual(
            (avoid["cost"], avoid["net"], avoid["netSectorExcess"]), (None,) * 3
        )
        self.assertAlmostEqual(p["spread"], 0.15 - (-0.10 - 0.25 / 3))
        self.assertAlmostEqual(p["spreadRaw"], 0.30)
        self.assertAlmostEqual(p["ic"], 0.9)
        self.assertEqual(p["icPairs"], 5)
        self.assertEqual(p["hitRate"], {PREFER: 1.0, AVOID: 1.0, "combined": 1.0})
        coverage = p["coverage"]
        self.assertEqual(
            (coverage["members"], coverage["excluded"], coverage["eligible"]), (8, 1, 7)
        )
        self.assertEqual(coverage["labeled"], {PREFER: 2, WATCH: 3, AVOID: 1})
        self.assertEqual(coverage["insufficient"], 1)
        self.assertEqual(coverage["held"], 6)
        self.assertEqual(coverage["notHeld"], {"no_price_series": 1})
        self.assertEqual(coverage["flags"], {"last_price": 1})
        self.assertEqual(coverage["excludedReasons"], {"financial_sic": 1})

    def test_member_without_any_series_is_a_counted_error(self):
        first = periods(self.result, "US")[0]
        self.assertEqual(
            first["errors"],
            [dict(id="US:H", symbol="HHH-missing", reason="no_price_series")],
        )
        # M4: B was delisted on Nov 30, before November's entry on Dec 2: left out of
        # that period and counted as an error (never no_entry_price).
        self.assertEqual(
            periods(self.result, "KR")[1]["errors"],
            [
                dict(
                    id="KR:B",
                    symbol=symbol("KR", "B"),
                    reason="series_ends_before_entry",
                )
            ],
        )
        self.assertEqual(self.result["errors"], 4)  # H in October, B in November
        self.assertEqual(self.result["summary"]["US"]["seriesErrors"], 2)

    def test_baselines(self):
        p = periods(self.result, "US")[0]
        signals = p["baselines"]["signals"]
        self.assertAlmostEqual(signals["fcfYield"]["gross"], (0.30 + 0.05) / 2)
        self.assertEqual(signals["fcfYield"]["held"], 2)
        self.assertAlmostEqual(signals["momentum12_1"]["gross"], (0.10 - 0.05) / 2)
        self.assertEqual(signals["cashProfitability"]["held"], 0)
        self.assertIsNone(signals["cashProfitability"]["gross"])
        self.assertAlmostEqual(p["baselines"]["equalWeight"]["gross"], 0.05)
        self.assertEqual(p["baselines"]["equalWeight"]["held"], 6)
        index = p["baselines"]["benchmark"]
        self.assertEqual(index["symbol"], "^SP500TR")
        self.assertAlmostEqual(index["return"], 0.05)
        kr_index = periods(self.result, "KR")[0]["baselines"]["benchmark"]
        self.assertEqual(kr_index["symbol"], "069500.KS")

    def test_turnover_from_drifted_weights_and_market_costs(self):
        drifted_a, drifted_d = 0.5 * 1.1 / 1.2, 0.5 * 1.3 / 1.2
        traded = (0.5 - drifted_a) + 0.5
        for market, cost in (("US", 0.0005 * traded * 2), ("KR", 0.003 * traded)):
            p = periods(self.result, market)[1]
            prefer = p["portfolios"][PREFER]
            self.assertAlmostEqual(prefer["bought"], traded)
            self.assertAlmostEqual(prefer["sold"], drifted_d)
            self.assertAlmostEqual(prefer["turnover"], traded)
            self.assertAlmostEqual(prefer["cost"], cost)
            self.assertAlmostEqual(prefer["gross"], 0.075)
            self.assertAlmostEqual(prefer["sectorExcess"], 0.05)
            self.assertAlmostEqual(prefer["netSectorExcess"], 0.05 - cost)
            # I has no close on Dec 2 and sits the period out: five members held.
            self.assertAlmostEqual(prefer["universeExcess"], 0.075 - 0.10 / 5)
            avoid = p["portfolios"][AVOID]
            for field in ("bought", "sold"):
                self.assertAlmostEqual(avoid[field], 0.0)
            self.assertIsNone(avoid["cost"])
        self.assertAlmostEqual(
            periods(self.result, "KR")[1]["portfolios"][PREFER]["cost"], 0.001625
        )

    def test_second_period_has_no_late_entry(self):
        p = periods(self.result, "KR")[1]
        members = {m["id"]: m for m in p["members"]}
        self.assertEqual(members["KR:B"]["reason"], "series_ends_before_entry")
        self.assertEqual(members["KR:I"]["reason"], "no_entry_price")
        self.assertNotIn("entryDate", members["KR:I"])
        self.assertEqual(
            p["coverage"]["notHeld"],
            {"no_entry_price": 1, "series_ends_before_entry": 1},
        )
        self.assertEqual(p["coverage"]["held"], 5)
        self.assertAlmostEqual(p["ic"], 0.8)
        self.assertAlmostEqual(p["baselines"]["benchmark"]["return"], 0.02)

    def test_summary_uses_complete_periods(self):
        for market in ("US", "KR"):
            summary = self.result["summary"][market]
            self.assertEqual(
                (summary["complete"], summary["inProgress"], summary["pending"]),
                (1, 1, 0),
            )
            self.assertAlmostEqual(summary["primary"]["mean"], 0.15 - 0.0005)
            self.assertEqual(summary["primary"]["periods"], 1)
            # 회피 gross: the October avoid portfolio's sector excess without costs.
            self.assertAlmostEqual(summary["avoid"]["mean"], -0.10 - 0.25 / 3)
            self.assertEqual(summary["costBasis"], {PREFER: "net", AVOID: "gross"})
            self.assertAlmostEqual(summary["ic"]["mean"], 0.9)

    def test_pending_dry_run_and_protocol_checks(self):
        early = ev.evaluate(self.registrations, series(), "2026-11-03")
        self.assertEqual({p["status"] for p in early["periods"]}, {"pending"})
        dry = [dict(r, kind="dry-run") for r in self.registrations]
        skipped = ev.evaluate(dry, series(), THROUGH)
        self.assertEqual(skipped["periods"], [])
        self.assertEqual(len(skipped["issues"]), 2)
        included = ev.evaluate(dry, series(), THROUGH, include_dry_run=True)
        self.assertTrue(included["dryRunIncluded"])
        self.assertEqual(len(included["periods"]), 4)
        tampered = copy.deepcopy(self.registrations[0])
        tampered["protocol"]["costs"]["US"]["buy"] = 0.0
        result = ev.evaluate([tampered], series(), THROUGH)
        self.assertEqual(result["issues"][0]["issue"], "protocol_hash_mismatch")
        own = copy.deepcopy(PROTOCOL)
        own["costs"]["US"]["buy"] = 0.01
        alternative = registration(
            "2026-10", OCTOBER_AT, october_rows("US"), protocol=own
        )
        result = ev.evaluate([alternative], series(), "2026-12-04")
        self.assertEqual(result["issues"][0]["issue"], "protocol_differs_from_code")
        self.assertAlmostEqual(result["periods"][0]["portfolios"][PREFER]["cost"], 0.01)
        with self.assertRaises(ValueError):
            ev.evaluate(self.registrations[:1] * 2, series(), THROUGH)

    def test_registration_without_its_ledger_record_is_flagged(self):
        bare = {k: v for k, v in self.registrations[0].items() if k != "ledger"}
        result = ev.evaluate([bare], series(), THROUGH)
        self.assertIn(
            dict(registration="2026-10", issue="ledger_unverified"), result["issues"]
        )

    def test_stored_series_are_flagged(self):
        result = ev.evaluate(self.registrations, series(), THROUGH, stored={"AAA"})
        members = {m["id"]: m for m in periods(result, "US")[0]["members"]}
        self.assertEqual(members["US:A"]["flags"], ["stored_series"])
        self.assertEqual(members["US:C"]["flags"], [])


class EntryAndExitTests(unittest.TestCase):
    """D12 entry date and the D4 window exit."""

    def test_entry_follows_the_later_of_stamp_and_ledger_record(self):
        late = registration(
            "2026-10",
            OCTOBER_AT,
            both(october_rows),
            recorded="2026-11-04T12:00:00+00:00",
        )
        result = ev.evaluate([late], series(), THROUGH)
        for p in result["periods"]:
            self.assertEqual(
                (p["registrationDay"], p["entryDay"], p["entry"]),
                ("2026-11-02", "2026-11-04", "2026-11-05"),
            )

    def test_window_membership_uses_the_registration_day(self):
        """D15: stamped 23:59:59.6 New York on Dec 7 (the fifth session after Nov 30),
        ledgered 0.8 s later on Dec 8: inside the window as the registry judged it, so
        October exits at November's entry (after the later timestamp), not a forced
        exit with a sale."""
        october = registration("2026-10", OCTOBER_AT, october_rows("US"))
        november = registration(
            "2026-11",
            "2026-12-08T04:59:59.600000+00:00",
            november_rows("US"),
            recorded="2026-12-08T05:00:00.400000+00:00",
        )
        first, second = ev.evaluate([october, november], series(), THROUGH)["periods"]
        self.assertEqual(
            (first["status"], first["exit"], first["flags"]),
            ("complete", "2026-12-09", []),
        )
        self.assertNotIn("liquidated", first["portfolios"][PREFER])
        self.assertEqual(
            (second["registrationDay"], second["entryDay"], second["entry"]),
            ("2026-12-07", "2026-12-08", "2026-12-09"),
        )
        # The stored registrationDay is what the registry judged; it wins.
        stored = dict(november, registrationDay={"US": "2026-12-08"})
        first = ev.evaluate([october, stored], series(), THROUGH)["periods"][0]
        self.assertEqual(
            (first["exit"], first["flags"]),
            ("2026-12-08", ["late_next_registration", "missed_next_registration"]),
        )

    def test_missed_month_exits_after_the_window_and_sells(self):
        october = registration("2026-10", OCTOBER_AT, october_rows("US"))
        december = registration("2026-12", DECEMBER_AT, november_rows("US"))
        result = ev.evaluate([october, december], series(), "2027-01-15")
        first, second = result["periods"]
        # November's T is Mon Nov 30; its window ran through Dec 7 (the fifth session)
        # and the forced exit is the sixth session, Dec 8.
        self.assertEqual(
            (first["status"], first["exit"], first["flags"], first["gapMonths"]),
            ("complete", "2026-12-08", ["missed_next_registration"], 2),
        )
        prefer = first["portfolios"][PREFER]
        self.assertAlmostEqual(prefer["liquidated"], 1.0)
        self.assertAlmostEqual(prefer["cost"], 0.0005 + 0.0005)
        self.assertAlmostEqual(
            prefer["netSectorExcess"], prefer["sectorExcess"] - 0.001
        )
        self.assertEqual(
            (second["entry"], second["status"]), ("2027-01-05", "in_progress")
        )
        self.assertAlmostEqual(second["portfolios"][PREFER]["bought"], 1.0)
        self.assertEqual(result["summary"]["US"]["missedRegistrations"], 1)

    def test_registration_after_its_window_counts_as_missed(self):
        october = registration("2026-10", OCTOBER_AT, october_rows("US"))
        late = registration("2026-11", "2026-12-10T12:00:00+00:00", november_rows("US"))
        first = ev.evaluate([october, late], series(), THROUGH)["periods"][0]
        self.assertEqual(
            (first["status"], first["exit"], first["flags"]),
            (
                "complete",
                "2026-12-08",
                ["late_next_registration", "missed_next_registration"],
            ),
        )

    def test_passed_deadline_waits_for_the_forced_exit(self):
        october = registration("2026-10", OCTOBER_AT, october_rows("US"))
        rows = {s: [r for r in v if r[0] < "2026-12-08"] for s, v in series().items()}
        first = ev.evaluate([october], rows, "2026-12-08")["periods"][0]
        self.assertEqual(
            (first["status"], first["exit"], first["flags"]),
            ("in_progress", "2026-12-07", ["missed_next_registration"]),
        )
        open_ = ev.evaluate([october], series(), "2026-12-07")["periods"][0]
        self.assertEqual((open_["status"], open_["flags"]), ("in_progress", []))


def without_h(market: str) -> list:
    return [r for r in october_rows(market) if not r["id"].endswith(":H")]


class FreezeTests(unittest.TestCase):
    """D12': completed periods are frozen and kept; fresh data that differ are flagged."""

    SHA = {s: digest(s.encode()) for s in series()}

    def setUp(self):
        self.registrations = [
            registration("2026-10", OCTOBER_AT, both(without_h)),
            registration("2026-11", NOVEMBER_AT, both(november_rows)),
        ]
        self.first = ev.evaluate(
            self.registrations, series(), THROUGH, sources=self.SHA
        )
        self.records = {
            (p["market"], p["month"]): ev.freeze_record(p, THROUGH, "2026-12-16T00:00Z")
            for p in self.first["periods"]
            if p["status"] == "complete"
        }

    def test_freeze_record_holds_the_member_results(self):
        record = self.records[("US", "2026-10")]
        self.assertEqual(
            (record["kind"], record["entry"], record["exit"], record["through"]),
            ("frozen-period", "2026-11-03", "2026-12-02", THROUGH),
        )
        self.assertEqual(record["registration"]["hash"], digest(b"2026-10"))
        members = {m["id"]: m for m in record["members"]}
        self.assertEqual(
            members["US:A"],
            dict(
                id="US:A",
                symbol="AAA",
                sector="S1",
                label=PREFER,
                composite=1.0,
                seriesSha256=self.SHA["AAA"],
                entryDate="2026-11-03",
                exitDate="2026-12-02",
                entryPrice=100.0,
                exitPrice=110.0,
                **{"return": 0.10000000000000009},
                flags=[],
            ),
        )
        self.assertEqual(record["benchmark"]["seriesSha256"], self.SHA["^SP500TR"])
        november = next(p for p in self.first["periods"] if p["month"] == "2026-11")
        with self.assertRaisesRegex(ValueError, "completed period"):
            ev.freeze_record(november, THROUGH, "2026-12-16T00:00Z")

    def test_frozen_results_are_kept_and_revisions_flagged(self):
        changed = series()
        changed["AAA"] = [  # Yahoo revises A's Dec 2 close
            [d, 120.0 if d == "2026-12-02" else v, c] for d, v, c in changed["AAA"]
        ]
        changed["CCC"] = [r for r in changed["CCC"] if r[0] >= "2026-11-20"]  # reset
        result = ev.evaluate(self.registrations, changed, THROUGH, frozen=self.records)
        october = next(
            p
            for p in result["periods"]
            if (p["market"], p["month"]) == ("US", "2026-10")
        )
        before = next(
            p
            for p in self.first["periods"]
            if (p["market"], p["month"]) == ("US", "2026-10")
        )
        self.assertEqual(october["frozen"]["through"], THROUGH)
        self.assertEqual(october["errors"], [])  # frozen numbers need no fresh series
        members = {m["id"]: m for m in october["members"]}
        self.assertAlmostEqual(members["US:A"]["return"], 0.10)  # frozen, not 0.20
        self.assertIn(ev.REVISED, members["US:A"]["flags"])
        self.assertAlmostEqual(members["US:A"][ev.REVISED]["return"], 0.20)
        self.assertAlmostEqual(members["US:C"]["return"], -0.10)
        self.assertEqual(
            members["US:C"][ev.REVISED], dict(reason="series_not_covering")
        )
        self.assertNotIn(ev.REVISED, members["US:B"]["flags"])
        self.assertEqual(members["US:A"]["seriesSha256"], self.SHA["AAA"])
        for key in ("portfolios", "spread", "ic", "sectors", "baselines"):
            self.assertEqual(october[key], before[key], key)
        self.assertEqual(result["summary"]["US"]["frozen"], 1)
        self.assertEqual(result["summary"]["US"]["revisedAfterFreeze"], 1)
        # The open November period uses fresh data, where C's reset history still
        # covers its Dec 2 entry.
        november = next(
            p
            for p in result["periods"]
            if (p["market"], p["month"]) == ("US", "2026-11")
        )
        self.assertIsNone(november["frozen"])
        self.assertEqual(  # only B, delisted before November's entry (M4)
            november["errors"],
            [dict(id="US:B", symbol="BBB", reason="series_ends_before_entry")],
        )

    def test_a_frozen_record_must_be_this_registrations_period(self):
        record = dict(
            self.records[("US", "2026-10")],
            registration=dict(hash="f" * 64),
        )
        result = ev.evaluate(
            self.registrations, series(), THROUGH, frozen={("US", "2026-10"): record}
        )
        october = result["periods"][0]
        self.assertIsNone(october["frozen"])
        self.assertEqual(october["errors"][0]["reason"], "frozen_period_mismatch")
        self.assertGreaterEqual(result["errors"], 1)
        dry = [dict(r, kind="dry-run") for r in self.registrations]
        result = ev.evaluate(
            dry, series(), THROUGH, include_dry_run=True, frozen=self.records
        )
        self.assertEqual({p["frozen"] for p in result["periods"]}, {None})

    def test_member_errors_hold_a_period_back_until_its_grace_has_passed(self):
        """L3: a completed period with member errors waits while the evaluation date is
        at most freezeGraceDays (30) after its exit date, then is frozen with those
        members unresolved: out of the returns, kept in the counts, no longer errors."""
        registrations = [
            registration("2026-10", OCTOBER_AT, both(october_rows)),  # H: no series
            registration("2026-11", NOVEMBER_AT, both(november_rows)),
        ]
        waiting = ev.evaluate(registrations, series(), THROUGH)
        october = periods(waiting, "US")[0]
        self.assertEqual(
            (october["status"], october["exit"], october["freezeGraceDays"]),
            ("complete", "2026-12-02", 30),
        )
        self.assertEqual(ev.unresolved_from(october), "2027-01-02")
        state, detail = ev.freeze_state(october, "2027-01-01")  # 30 days after exit
        self.assertEqual(state, "wait")
        self.assertIn("2027-01-02", detail)
        with self.assertRaisesRegex(ValueError, "member errors"):
            ev.freeze_record(october, THROUGH, "2026-12-16T00:00Z")
        mismatch = dict(october, errors=[dict(reason="frozen_period_mismatch")])
        self.assertEqual(ev.freeze_state(mismatch, "2027-02-01")[0], "blocked")
        later = ev.evaluate(registrations, series(), "2027-01-04")
        october = periods(later, "US")[0]
        self.assertEqual(ev.freeze_state(october, "2027-01-04"), ("freeze", ""))
        record = ev.freeze_record(october, "2027-01-04", "2027-01-05T00:00Z")
        members = {m["id"]: m for m in record["members"]}
        self.assertEqual(
            members["US:H"],
            dict(
                id="US:H",
                symbol="HHH-missing",
                sector="S1",
                label=WATCH,
                composite=0.1,
                seriesSha256=None,
                reason="unresolved",
                error="no_price_series",
            ),
        )
        self.assertEqual(record["unresolved"], ["US:H"])
        self.assertEqual(record["flags"], ["frozen_with_unresolved"])
        frozen = {("US", "2026-10"): record}
        kept = ev.evaluate(registrations, series(), "2027-01-04", frozen=frozen)
        october = periods(kept, "US")[0]
        self.assertEqual(october["errors"], [])
        self.assertEqual(october["frozen"]["unresolved"], ["US:H"])
        self.assertEqual(october["flags"], ["frozen_with_unresolved"])
        member = next(m for m in october["members"] if m["id"] == "US:H")
        self.assertEqual(
            (member["reason"], member["error"]), ("unresolved", "no_price_series")
        )
        self.assertNotIn(ev.REVISED, member)  # still without a series: no revision
        self.assertEqual(
            (october["coverage"]["held"], october["coverage"]["notHeld"]),
            (6, {"unresolved": 1}),
        )
        for key in ("portfolios", "spread", "ic", "sectors"):
            self.assertEqual(october[key], periods(later, "US")[0][key], key)
        summary = kept["summary"]["US"]
        self.assertEqual(
            (summary["frozenWithUnresolved"], summary["unresolvedMembers"]), (1, 1)
        )
        self.assertEqual(summary["seriesErrors"], 1)  # B in the open November period
        # A series found later revises nothing: it is flagged on the frozen member.
        found = series()
        found["HHH-missing"] = price_rows("A")
        revised = ev.evaluate(registrations, found, "2027-01-04", frozen=frozen)
        october = periods(revised, "US")[0]
        member = next(m for m in october["members"] if m["id"] == "US:H")
        self.assertEqual(member["reason"], "unresolved")
        self.assertAlmostEqual(member[ev.REVISED]["return"], 0.10)
        self.assertEqual(october["coverage"]["held"], 6)

    def test_a_frozen_period_keeps_its_costs_when_an_earlier_one_resolves(self):
        """N5: November is frozen while October waits out its grace (H, a 선호 member,
        has no series). H's series turns up later: October's drifted weights change and
        so would November's rebalancing cost, but November keeps the turnover, costs
        and net metrics it was frozen with; the fresh costs are a revision."""
        own = json.loads(canonical(PROTOCOL))
        own["evaluation"]["freezeGraceDays"] = 60
        october = [
            row("US", "H", "S1", PREFER, 0.6) if r["id"] == "US:H" else r
            for r in october_rows("US")
        ]
        november = [r for r in november_rows("US") if r["id"] != "US:B"]
        registrations = [
            registration("2026-10", OCTOBER_AT, october, protocol=own),
            registration("2026-11", NOVEMBER_AT, november, protocol=own),
            registration("2026-12", DECEMBER_AT, november, protocol=own),
        ]
        through = "2027-01-15"
        first = ev.evaluate(registrations, series(), through)
        waiting, frozen_now = periods(first, "US")[:2]
        self.assertEqual(ev.freeze_state(waiting, through)[0], "wait")
        self.assertEqual(ev.freeze_state(frozen_now, through), ("freeze", ""))
        record = ev.freeze_record(frozen_now, through, "2027-01-16T00:00Z")
        prefer = frozen_now["portfolios"][PREFER]
        self.assertEqual(
            record["costs"][PREFER],
            {key: prefer[key] for key in ("bought", "sold", "turnover", "cost")},
        )
        self.assertEqual(
            set(record["costs"]),
            {
                PREFER,
                AVOID,
                *(
                    f"signal:{s}"
                    for s in ("fcfYield", "cashProfitability", "momentum12_1")
                ),
            },
        )
        found = series()  # H's series turns up: October now holds it
        rises = {d: 150.0 if d >= "2026-12-02" else 100.0 for d in DAYS}
        found["HHH-missing"] = [[d, v, v] for d, v in rises.items()]
        fresh = periods(ev.evaluate(registrations, found, through), "US")[1]
        self.assertGreater(
            abs(fresh["portfolios"][PREFER]["cost"] - prefer["cost"]), 1e-9
        )  # recomputed from October's new drifted weights, the cost moves
        kept = ev.evaluate(
            registrations, found, through, frozen={("US", "2026-11"): record}
        )
        resolved, again = periods(kept, "US")[:2]
        self.assertEqual(resolved["errors"], [])
        self.assertTrue(again["frozen"])
        self.assertEqual(again["portfolios"][PREFER], prefer)  # net metrics included
        self.assertEqual(again["portfolios"][AVOID], frozen_now["portfolios"][AVOID])
        self.assertEqual(
            again["baselines"]["signals"], frozen_now["baselines"]["signals"]
        )
        self.assertEqual(
            again["revisions"]["costs"][PREFER]["cost"],
            fresh["portfolios"][PREFER]["cost"],
        )
        self.assertIn(ev.REVISED, again["flags"])
        self.assertEqual(kept["summary"]["US"]["revisedAfterFreeze"], 1)
        # A record frozen before N5 (no costs) is valued as before; unreadable costs
        # are a mismatch the operator has to look at.
        older = {k: v for k, v in record.items() if k != "costs"}
        legacy = periods(
            ev.evaluate(
                registrations, found, through, frozen={("US", "2026-11"): older}
            ),
            "US",
        )[1]
        self.assertEqual(
            legacy["portfolios"][PREFER]["cost"], fresh["portfolios"][PREFER]["cost"]
        )
        broken = dict(record, costs={PREFER: dict(cost="0.001")})
        mismatch = periods(
            ev.evaluate(
                registrations, found, through, frozen={("US", "2026-11"): broken}
            ),
            "US",
        )[1]
        self.assertEqual(
            mismatch["errors"],
            [
                dict(
                    reason="frozen_period_mismatch",
                    detail="frozen record: its costs are unreadable",
                )
            ],
        )

    def test_open_period_member_whose_series_lost_its_entry_is_an_error(self):
        """D12': a held member whose fresh series no longer covers its in-progress
        period is an error, never no_entry_price."""
        changed = series()
        changed["DDD"] = [r for r in changed["DDD"] if r[0] >= "2026-12-07"]
        result = ev.evaluate(self.registrations, changed, THROUGH, frozen=self.records)
        november = next(
            p
            for p in result["periods"]
            if (p["market"], p["month"]) == ("US", "2026-11")
        )
        self.assertEqual(
            november["errors"],
            [
                dict(id="US:B", symbol="BBB", reason="series_ends_before_entry"),
                dict(id="US:D", symbol="DDD", reason="series_not_covering"),
            ],
        )
        self.assertEqual(result["errors"], 3)  # and KR:B

    def test_mixed_protocol_hashes_are_an_error_and_valuation_date_is_reported(self):
        own = copy.deepcopy(PROTOCOL)
        own["costs"]["US"]["buy"] = 0.01
        november = registration(
            "2026-11", NOVEMBER_AT, november_rows("US"), protocol=own
        )
        october = registration("2026-10", OCTOBER_AT, without_h("US"))
        result = ev.evaluate([october, november], series(), THROUGH)
        mixed = [i for i in result["issues"] if i["issue"] == "mixed_protocol_hashes"]
        self.assertEqual(len(mixed), 1)
        self.assertEqual(result["errors"], 2)  # and B, delisted before November (M4)
        self.assertEqual(self.first["valuedThrough"], {"US": THROUGH, "KR": THROUGH})
        early = ev.evaluate(self.registrations, series(), "2026-12-13")  # a Sunday
        self.assertEqual(early["valuedThrough"]["US"], "2026-12-11")


class ForwardStudyCheckTests(unittest.TestCase):
    def snapshot(self, contract, prices, through) -> dict:
        companies = []
        for market, spec in contract["markets"].items():
            for company in [spec["calendarCompany"], *spec["members"]]:
                key = f"{company}.KS" if market == "KR" else company
                companies.append(
                    dict(
                        id=company,
                        prices=[
                            dict(date=d, adjustedClose=adj)
                            for d, adj, _ in prices.get(key, [])
                        ],
                        sources=[],
                    )
                )
        unique = {c["id"]: c for c in companies}
        return dict(asOf=through, contentHash="test", companies=list(unique.values()))

    def assertSameAsStudy(self, mine: dict, theirs: dict):
        self.assertEqual(mine["status"], "ok")
        self.assertEqual((mine["matches"], mine["differences"]), (True, []))
        self.assertEqual(mine["reference"], "equitylab.forward_study.evaluate")
        self.assertEqual(len(mine["results"]), len(theirs["results"]))
        for a, b in zip(mine["results"], theirs["results"]):
            for key in ("market", "horizon", "status", "observedSessions", "missing"):
                self.assertEqual(a.get(key), b.get(key), key)
            self.assertEqual(
                (a.get("entry"), a.get("end")), (b.get("entry"), b.get("end"))
            )
            self.assertEqual(set(a.get("policies", {})), set(b.get("policies", {})))
            for name, policy in a.get("policies", {}).items():
                other = b["policies"][name]
                self.assertEqual(policy["selected"], other["selected"])
                for field in ("gross", "net", "differenceFromBaseline"):
                    self.assertAlmostEqual(policy[field], other[field], places=12)
            for company, value in a.get("companyReturns", {}).items():
                self.assertAlmostEqual(value, b["companyReturns"][company], places=12)

    def write(self, folder: Path, contract: dict) -> Path:
        contract = dict(contract)
        contract["protocolHash"] = digest(canonical(contract))
        path = folder / "forward.json"
        path.write_bytes(canonical(contract))
        return path

    def contract(self) -> dict:
        return dict(
            version="forward-coverage-v1",
            registeredAt="2026-09-30T10:00:00+00:00",
            markets={
                "US": dict(
                    registrationDay="2026-09-30",
                    calendarCompany="A",
                    members=["A", "B"],
                    selection=dict(
                        equal_weight=["A", "B"],
                        cash_conditions=["A"],
                        without_growth=[],
                        momentum63_top5=["B"],
                    ),
                )
            },
            horizons=[2],
            oneWayCost=0.001,
        )

    def prices(self) -> dict:
        dates = ["2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05"]
        return {
            name: [[d, float(v), float(v)] for d, v in zip(dates, values)]
            for name, values in (("A", [1, 100, 105, 110]), ("B", [1, 200, 200, 190]))
        }

    def test_matches_the_original_evaluator_on_a_synthetic_contract(self):
        prices = self.prices()
        with tempfile.TemporaryDirectory() as folder:
            path = self.write(Path(folder), self.contract())
            signed = json.loads(path.read_bytes())
            mine = ev.forward_study_check(path, prices, "2026-10-05")
            theirs = study.evaluate(signed, self.snapshot(signed, prices, "2026-10-05"))
            self.assertSameAsStudy(mine, theirs)
            observed = mine["results"][0]
            self.assertAlmostEqual(observed["policies"]["equal_weight"]["net"], 0.023)
            self.assertEqual(
                observed["policies"]["oracle_upper_bound"]["selected"], ["A"]
            )
            prices["B"].pop()
            gap = ev.forward_study_check(path, prices, "2026-10-05")
            self.assertEqual(
                (gap["results"][0]["status"], gap["results"][0]["missing"]),
                ("unresolved", ["B"]),
            )
            self.assertTrue(gap["matches"])
            path.write_bytes(path.read_bytes().replace(b"0.001", b"0.002"))
            self.assertEqual(
                ev.forward_study_check(path, prices, "2026-10-05")["status"], "invalid"
            )

    def test_uses_the_ratings_functions_and_reports_differences(self):
        """D13: returns come from evaluate.holding and policies from evaluate._portfolio;
        a disagreement with equitylab.forward_study.evaluate is reported, not hidden."""
        prices = self.prices()
        with tempfile.TemporaryDirectory() as folder:
            path = self.write(Path(folder), self.contract())
            original = ev.holding

            def shifted(rows, entry, exit):
                out = original(rows, entry, exit)
                if "return" in out:
                    out["return"] += 0.01
                return out

            with mock.patch.object(ev, "holding", side_effect=shifted) as spy:
                result = ev.forward_study_check(path, prices, "2026-10-05")
            self.assertEqual(spy.call_count, 2)
            self.assertFalse(result["matches"])
            fields = {d["field"] for d in result["differences"]}
            self.assertIn("companyReturns.A", fields)
            self.assertIn("equal_weight.gross", fields)
            with mock.patch.object(ev, "_portfolio", side_effect=ev._portfolio) as spy:
                self.assertTrue(
                    ev.forward_study_check(path, prices, "2026-10-05")["matches"]
                )
            self.assertGreater(spy.call_count, 0)

    def test_real_frozen_study_is_read_only_and_matches_the_original(self):
        path = ROOT / "data/forward-study.json"
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        contract = json.loads(before[0])
        empty = ev.forward_study_check(path, {}, "2026-10-06")
        self.assertEqual(empty["status"], "ok")
        self.assertEqual(
            empty["protocolHash"],
            "14e3d1c9bb52979ddb7e4cd048a9742c040df5a7727042a402e2e582ca981f30",
        )
        self.assertEqual({r["status"] for r in empty["results"]}, {"unresolved"})
        self.assertEqual(len(empty["results"]), 4)
        self.assertTrue(empty["matches"])
        days = business_days("2026-09-28", "2027-01-15")
        prices = {}
        for market, spec in contract["markets"].items():
            for k, company in enumerate(spec["members"]):
                key = f"{company}.KS" if market == "KR" else company
                growth = 1 + 0.0005 * (k - 9)
                prices[key] = [
                    [d, 100.0 * growth**t, 100.0] for t, d in enumerate(days)
                ]
        through = days[-1]
        mine = ev.forward_study_check(path, prices, through)
        theirs = study.evaluate(contract, self.snapshot(contract, prices, through))
        self.assertEqual({r["status"] for r in mine["results"]}, {"observed"})
        self.assertSameAsStudy(mine, theirs)
        self.assertEqual(mine["results"][0]["symbols"]["000660"], "000660.KS")
        self.assertFalse(mine["independentAlphaValidation"])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)


if __name__ == "__main__":
    unittest.main()
