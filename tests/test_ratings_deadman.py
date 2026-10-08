"""The deadman check of the unattended operation (scripts/ratings_deadman.py)."""

from datetime import date, datetime, timezone
import importlib.util
from unittest import mock
import unittest

from equitylab.data import ROOT
from ratings import registry, universe

import test_ratings_registry as fixtures

spec = importlib.util.spec_from_file_location(
    "ratings_deadman", ROOT / "scripts/ratings_deadman.py"
)
deadman = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deadman)

G = deadman.CHECK["asOf"]  # 2026-10-19, a Monday


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


class Deadman(fixtures.Ledgered):
    """A temp ledger and registration folder (fixtures.Ledgered) and universe folder."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(universe, "UNIVERSE_DIR", self.root / "universe")
        patcher.start()
        self.addCleanup(patcher.stop)

    def part(self, market, day, gate=False):
        path = universe.part_path(market, day, gate=gate)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")

    def overdue(self, when: str) -> list:
        return deadman.overdue(utc(when))


class GateDeadlines(Deadman):
    def test_nothing_is_due_before_the_gate(self):
        self.assertEqual(self.overdue("2026-10-19T14:59:00"), [])

    def test_the_kr_part_is_due_at_midnight_kst_on_the_gate_day(self):
        self.assertEqual(
            self.overdue("2026-10-19T15:01:00"),
            [f"KR gate part (asOf {G}): due 2026-10-19 15:00 UTC"],
        )
        self.part("KR", G, gate=True)
        self.assertEqual(self.overdue("2026-10-19T15:01:00"), [])

    def test_the_us_part_follows_ssga_and_each_gate_event_its_retries(self):
        self.part("KR", G, gate=True)
        self.assertEqual(self.overdue("2026-10-20T15:59:00"), [])
        self.assertEqual(
            self.overdue("2026-10-20T16:01:00"),
            [f"US gate part (asOf {G}): due 2026-10-20 16:00 UTC"],
        )
        self.part("US", G, gate=True)
        self.assertEqual(
            self.overdue("2026-10-21T06:01:00"),
            ["KR coverage gate in the ledger: due 2026-10-21 06:00 UTC"],
        )
        # US members without a close on G are collected again for two sessions.
        self.assertEqual(
            self.overdue("2026-10-22T16:01:00"),
            [
                "KR coverage gate in the ledger: due 2026-10-21 06:00 UTC",
                "US coverage gate in the ledger: due 2026-10-22 16:00 UTC",
            ],
        )
        self.gates()
        self.assertEqual(self.overdue("2026-10-22T16:01:00"), [])

    def test_an_alert_lasts_three_days(self):
        self.assertEqual(len(self.overdue("2026-10-22T14:59:00")), 3)
        # The KR part (due 10-19 15:00) is no longer listed three days on.
        self.assertEqual(len(self.overdue("2026-10-22T16:01:00")), 3)
        self.assertEqual(self.overdue("2026-10-25T16:01:00"), [])


class MonthDeadlines(Deadman):
    def setUp(self):
        super().setUp()
        self.gates()
        self.part("KR", G, gate=True)
        self.part("US", G, gate=True)

    def test_each_part_once_its_month_is_over_then_the_registration(self):
        # Parts are built only once the month is over: nothing is due on T itself.
        self.assertEqual(self.overdue("2026-10-31T12:00:00"), [])
        self.assertEqual(
            self.overdue("2026-11-01T15:01:00"),
            ["KR universe part for 2026-10: due 2026-11-01 15:00 UTC"],
        )
        self.part("KR", "2026-10-30")
        self.assertEqual(
            self.overdue("2026-11-02T16:01:00"),
            ["US universe part for 2026-10: due 2026-11-02 16:00 UTC"],
        )
        self.part("US", "2026-10-30")
        self.assertEqual(self.overdue("2026-11-04T14:59:00"), [])
        self.assertEqual(
            self.overdue("2026-11-04T15:01:00"),
            [
                "KR registration of 2026-10: due 2026-11-04 15:00 UTC",
                "US registration of 2026-10: due 2026-11-04 15:00 UTC",
            ],
        )
        self.register()  # both markets, at the fixture's clock (Nov 2)
        self.assertEqual(self.overdue("2026-11-04T15:01:00"), [])

    def test_month_start_holidays_move_the_deadlines(self):
        # December 2026: KRX closes 12-31 and 01-01, NYSE 01-01. SSGA posts 12-31's
        # holdings on Mon 01-04; both registrations are due on the third business day.
        self.assertIn(
            "KR universe part for 2026-12: due 2027-01-01 15:00 UTC",
            self.overdue("2027-01-02T00:00:00"),
        )
        us_part = "US universe part for 2026-12: due 2027-01-04 16:00 UTC"
        self.assertNotIn(us_part, self.overdue("2027-01-04T15:59:00"))
        self.assertIn(us_part, self.overdue("2027-01-04T16:01:00"))
        self.assertIn(
            "US registration of 2026-12: due 2027-01-06 15:00 UTC",
            self.overdue("2027-01-06T15:01:00"),
        )

    def test_a_registration_is_never_due_after_a_window_closes(self):
        # April 2028: KRX closes 05-01, 05-02 and 05-05, so KR's third business day is
        # 05-08, after the US window (NYSE 05-01..05-05): the US item is due two hours
        # after the US last call (05-05 08:00 EDT), inside its window.
        us = "US registration of 2028-04: due 2028-05-05 14:00 UTC"
        self.assertNotIn(us, self.overdue("2028-05-05T13:59:00"))
        self.assertIn(us, self.overdue("2028-05-05T14:01:00"))

    def test_a_market_held_for_the_other_is_due_only_after_its_last_call(self):
        # April 2027: KRX closes 05-03 and 05-05. A KR member with errors holds the US
        # until KR's second session after T (05-06) or the US last call (05-07 08:00
        # EDT), so the US is not overdue after its own fourth business day.
        us = "US registration of 2027-04: due 2027-05-07 14:00 UTC"
        self.assertNotIn(us, self.overdue("2027-05-06T16:01:00"))
        self.assertNotIn(us, self.overdue("2027-05-07T13:59:00"))
        self.assertIn(us, self.overdue("2027-05-07T14:01:00"))
        self.assertIn(
            "KR registration of 2027-04: due 2027-05-07 15:00 UTC",
            self.overdue("2027-05-07T15:01:00"),
        )

    def test_a_kr_gate_that_may_still_be_recorded_holds_the_us_to_its_last_call(self):
        self.part("KR", "2026-10-30")
        self.part("US", "2026-10-30")
        with mock.patch.object(
            deadman.registry,
            "gate",
            lambda m: None if m == "KR" else {"verdict": "pass"},
        ):
            self.assertEqual(self.overdue("2026-11-04T15:01:00"), [])
            # The US last call: 11-06 08:00 EST (13:00 UTC), plus two hours.
            self.assertEqual(self.overdue("2026-11-06T14:59:00"), [])
            self.assertEqual(
                self.overdue("2026-11-06T15:01:00"),
                ["US registration of 2026-10: due 2026-11-06 15:00 UTC"],
            )

    def test_an_unrecorded_us_gate_leaves_kr_due_as_usual(self):
        # The operation registers nothing while the US gate is pending: KR's month is
        # lost unless someone acts before KR's window closes, so it is due as usual.
        self.part("KR", "2026-10-30")
        self.part("US", "2026-10-30")
        with mock.patch.object(
            deadman.registry,
            "gate",
            lambda m: None if m == "US" else {"verdict": "pass"},
        ):
            self.assertEqual(
                self.overdue("2026-11-04T15:01:00"),
                ["KR registration of 2026-10: due 2026-11-04 15:00 UTC"],
            )

    def test_gate_parts_and_smoke_builds_are_not_month_parts(self):
        self.part("KR", "2026-10-30", gate=True)
        path = universe.UNIVERSE_DIR / "2026-10-30-limit24/KR.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        self.assertIn(
            "KR universe part for 2026-10: due 2026-11-01 15:00 UTC",
            self.overdue("2026-11-01T15:01:00"),
        )


class GateOutcomes(Deadman):
    def test_a_failed_us_gate_expects_no_month(self):
        self.gates(US="fail")
        self.assertEqual(self.overdue("2026-11-04T15:01:00"), [])

    def test_a_market_without_a_passing_gate_is_not_expected(self):
        self.gates(US=None)  # the US gate never recorded: KR goes on alone
        self.assertEqual(
            self.overdue("2026-11-02T15:01:00"),
            ["KR universe part for 2026-10: due 2026-11-01 15:00 UTC"],
        )
        self.assertEqual(
            self.overdue("2026-11-04T15:01:00"),
            ["KR registration of 2026-10: due 2026-11-04 15:00 UTC"],
        )

    def test_a_failed_kr_gate_leaves_the_us_expected(self):
        self.gates(KR="fail")
        self.assertEqual(
            self.overdue("2026-11-04T15:01:00"),
            [
                "US universe part for 2026-10: due 2026-11-02 16:00 UTC",
                "US registration of 2026-10: due 2026-11-04 15:00 UTC",
            ],
        )

    def test_a_ledger_that_does_not_verify_is_always_alerted(self):
        self.gates()
        lines = registry.LEDGER.read_text().splitlines()
        lines[0] = lines[0].replace('"pass"', '"fail"')
        registry.LEDGER.write_text("\n".join(lines) + "\n")
        (only,) = self.overdue("2027-06-01T00:00:00")
        self.assertIn("did not verify", only)


class Calendars(unittest.TestCase):
    def test_nyse_holidays_by_rule(self):
        self.assertEqual(
            sorted(d.isoformat() for d in deadman.nyse_holidays(2027)),
            [
                "2027-01-01",
                "2027-01-18",
                "2027-02-15",
                "2027-03-26",  # Good Friday
                "2027-05-31",
                "2027-06-18",  # Juneteenth on a Saturday, observed Friday
                "2027-07-05",  # Independence Day on a Sunday, observed Monday
                "2027-09-06",
                "2027-11-25",
                "2027-12-24",
            ],
        )
        # New Year's Day 2028 is a Saturday: NYSE stays open on Friday 2027-12-31.
        self.assertNotIn(date(2027, 12, 31), deadman.nyse_holidays(2027))
        self.assertNotIn(date(2027, 12, 31), deadman.nyse_holidays(2028))
        self.assertEqual(deadman.easter(2026), date(2026, 4, 5))
        self.assertEqual(deadman.easter(2028), date(2028, 4, 16))

    def test_business_days(self):
        self.assertEqual(
            deadman.business_after(date(2026, 12, 31), 1, "US"), date(2027, 1, 4)
        )
        self.assertEqual(
            deadman.last_business(date(2026, 12, 1), "KR"), date(2026, 12, 30)
        )
        self.assertEqual(
            deadman.business_after(date(2026, 10, 19), 2, "KR"), date(2026, 10, 21)
        )
        self.assertFalse(deadman.business(date(2026, 10, 9), "KR"))  # Hangul Day
        self.assertFalse(deadman.business(date(2027, 5, 3), "KR"))  # Labor Day sub.
        self.assertTrue(deadman.business(date(2026, 10, 9), "US"))

    def test_the_krx_table_covers_v1(self):
        years = {day[:4] for day in deadman.KRX_HOLIDAYS}
        self.assertEqual(years, {"2026", "2027", "2028"})
        for day in deadman.KRX_HOLIDAYS:
            self.assertLess(date.fromisoformat(day).weekday(), 5, day)

    def test_the_last_call_is_the_operations(self):
        spec = importlib.util.spec_from_file_location(
            "ratings_ops_for_deadman", ROOT / "scripts/ratings_ops.py"
        )
        ops = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ops)
        self.assertEqual(deadman.LAST_CALL, ops.LAST_CALL)
        self.assertEqual(deadman.WINDOW, ops.WINDOW)


class TableEnd(Deadman):
    def test_the_end_of_the_krx_table_is_alerted_from_december(self):
        self.assertEqual(self.overdue("2028-11-30T23:59:00"), [])
        line = "KRX_HOLIDAYS ends with 2028: add 2029's KRX closures"
        self.assertEqual(self.overdue("2028-12-01T00:00:00"), [line])
        self.assertEqual(self.overdue("2029-03-01T00:00:00"), [line])


class Command(Deadman):
    def test_exit_status(self):
        with mock.patch("sys.stdout"):
            self.assertEqual(deadman.main(["--now", "2026-10-19T14:00:00+00:00"]), 0)
            self.assertEqual(deadman.main(["--now", "2026-10-19T16:00:00+00:00"]), 1)
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            deadman.main(["--now", "2026-10-19T16:00:00"])
