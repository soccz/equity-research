#!/usr/bin/env python3
"""Deadman check of the unattended ratings-v1 operation.

    python scripts/ratings_deadman.py [--now 2026-10-21T07:00:00+00:00]

Exits 1 and lists each expected result still missing after its deadline (and, from
December of the KRX table's last year, that the table needs the next year). The failed
run makes GitHub notify the owner even when no operation run happened at all: a failed
operation run notifies by itself, a run that never starts does not. Read-only: it reads
the checkout's ledger, registration files and universe parts.

Deadlines (UTC) follow the operation (scripts/ratings_ops.py) and count business days
(NYSE holidays by rule, KRX holidays from the table below): G is the gate's asOf, and
T_US / T_KR are a month's last business day in each market.
- KR gate part: G 15:00 (00:00 KST; built on G's evening and collected before the KST
  day rolls over, D17).
- US gate part: the next NYSE business day after G, 16:00 (SSGA posts G's holdings
  about 10:30-11:30 UTC that day; the PC timer tries hourly until 14:41).
- KR gate event: the second KRX business day after G, 06:00 (15:00 KST).
- US gate event: the third NYSE business day after G, 16:00 (members without a close
  on G are collected again until two sessions after G).
- KR month part: 15:00 on the first day of the next month (00:00 KST on the 2nd): a
  month's part is built once the month is over in Seoul, after 20:15 KST on weekdays.
- US month part: the next NYSE business day after T_US, 16:00.
- The month's registration: the third business day after T in each market in v1,
  15:00, the later of the two (markets register together unless one is late), but
  never after SLACK past a market's own last call: LAST_CALL local time on its last
  window day, the fifth business day after T, from which the operation registers a
  market it held for the other (its window closes at the end of that day). While the
  KR gate's part is captured but the gate unrecorded, the operation holds the US until
  its last call, so the US is then due SLACK after it. A US gate whose part is
  captured but unrecorded holds every registration, so KR stays due as usual (without
  the part the US leaves v1 and KR registers alone, due as usual too).
Each is alerted for ALERT_DAYS after its deadline, then left to the operation's own
reports. A month expects only markets whose gate passed; a failed US gate publishes
nothing (§7). A ledger or registration file that does not verify is always alerted.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ratings import rating, registry, universe  # noqa: E402
from ratings.common import MARKETS  # noqa: E402

ALERT_DAYS = 3
CHECK = registry.gate_rule()
FIRST_MONTH = CHECK["date"][:7]
WINDOW = int(registry.setting("registrationWindowSessions"))
# The operation's last call (scripts/ratings_ops.py LAST_CALL, pinned by a test) and
# the two hourly PC timer runs after it.
LAST_CALL = {"US": time(8, 0), "KR": time(15, 0)}
SLACK = timedelta(hours=2)
# KRX closures on weekdays, 2026-2028 (lunar and substitute holidays, election days, the
# year-end closing on the year's last weekday). Past 2028 only weekends would count:
# from 2028-12-01 the check fails until 2029 is added (table_ends).
KRX_HOLIDAYS = frozenset(
    {
        "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02",
        "2026-05-01", "2026-05-05", "2026-05-25", "2026-06-03", "2026-07-17",
        "2026-08-17", "2026-09-24", "2026-09-25", "2026-10-05", "2026-10-09",
        "2026-12-25", "2026-12-31",
        "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-01", "2027-05-03",
        "2027-05-05",
        "2027-05-13", "2027-07-19", "2027-08-16", "2027-09-14", "2027-09-15",
        "2027-09-16", "2027-10-04", "2027-10-11", "2027-12-27", "2027-12-31",
        "2028-01-25", "2028-01-26", "2028-01-27", "2028-03-01", "2028-04-12",
        "2028-05-01", "2028-05-02", "2028-05-05", "2028-06-06", "2028-07-17",
        "2028-08-15", "2028-10-02", "2028-10-03", "2028-10-04", "2028-10-05",
        "2028-10-09", "2028-12-25", "2028-12-29",
    }
)  # fmt: skip


def easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th ``weekday`` (0 Monday) of the month; n = -1 is the last one."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    """A Saturday holiday is observed on Friday, a Sunday one on Monday."""
    return day + timedelta(days={5: -1, 6: 1}.get(day.weekday(), 0))


@lru_cache(maxsize=None)
def nyse_holidays(year: int) -> frozenset:
    """NYSE full-day closures by rule (New Year's Day on a Saturday is not observed)."""
    new_year = date(year, 1, 1)
    days = {
        _nth(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth(year, 2, 0, 3),  # Washington's Birthday
        easter(year) - timedelta(days=2),  # Good Friday
        _nth(year, 5, 0, -1),  # Memorial Day
        _observed(date(year, 6, 19)),  # Juneteenth
        _observed(date(year, 7, 4)),  # Independence Day
        _nth(year, 9, 0, 1),  # Labor Day
        _nth(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),  # Christmas
    }
    if new_year.weekday() != 5:
        days.add(_observed(new_year))
    return frozenset(days)


def business(day: date, market: str) -> bool:
    if day.weekday() >= 5:
        return False
    if market == "US":
        return day not in nyse_holidays(day.year)
    return day.isoformat() not in KRX_HOLIDAYS


def business_after(day: date, n: int, market: str) -> date:
    while n:
        day += timedelta(days=1)
        n -= business(day, market)
    return day


def last_business(month: date, market: str) -> date:
    day = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    day -= timedelta(days=1)
    while not business(day, market):
        day -= timedelta(days=1)
    return day


def next_month(month: date) -> date:
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


def at(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=timezone.utc)


def last_call(month: date, market: str) -> datetime:
    """SLACK after the market's last call on its last window day for ``month``."""
    day = business_after(last_business(month, market), WINDOW, market)
    where = ZoneInfo(rating.PROTOCOL["registration"]["timezones"][market])
    local = datetime.combine(day, LAST_CALL[market], tzinfo=where)
    return local.astimezone(timezone.utc) + SLACK


def month_part(market: str, month: str) -> bool:
    """A universe part of ``market`` whose T falls in ``month`` (<T>/, not -gate/)."""
    return any(
        len(path.parent.name) == 10
        for path in universe.UNIVERSE_DIR.glob(f"{month}-*/{market}.json")
    )


def expected(now: datetime) -> list:
    """[(deadline, what, present)] of every expected result due by ``now``."""
    gate_day = date.fromisoformat(CHECK["asOf"])
    gates = {m: registry.gate(m) for m in MARKETS}
    out = []
    for market, deadline in (
        ("KR", at(gate_day, 15)),
        ("US", at(business_after(gate_day, 1, "US"), 16)),
    ):
        part = universe.part_path(market, CHECK["asOf"], gate=True).exists()
        what = f"{market} gate part (asOf {CHECK['asOf']})"
        out.append((deadline, what, part or gates[market] is not None))
    for market, deadline in (
        ("KR", at(business_after(gate_day, 2, "KR"), 6)),
        ("US", at(business_after(gate_day, 3, "US"), 16)),
    ):
        what = f"{market} coverage gate in the ledger"
        out.append((deadline, what, gates[market] is not None))
    if (gates["US"] or {}).get("verdict") == "fail":
        return [item for item in out if item[0] <= now]
    in_v1 = [m for m in MARKETS if (gates[m] or {}).get("verdict") == "pass"]
    held = (  # the US waits for a KR gate that may still be recorded
        "US" in in_v1
        and gates["KR"] is None
        and universe.part_path("KR", CHECK["asOf"], gate=True).exists()
    )
    registered = {}
    for content in registry.registrations(strict=False):
        for market in content.get("asOf") or {}:
            registered.setdefault(content["month"], set()).add(market)
    month = date.fromisoformat(FIRST_MONTH + "-01")
    while in_v1 and at(next_month(month), 15) <= now:
        name, parts, due = month.strftime("%Y-%m"), {}, []
        if "KR" in in_v1:
            parts["KR"] = at(next_month(month), 15)
        if "US" in in_v1:
            last = last_business(month, "US")
            parts["US"] = at(business_after(last, 1, "US"), 16)
        for market in in_v1:
            last = last_business(month, market)
            due.append(at(business_after(last, 3, market), 15))
        for market in in_v1:
            done = market in registered.get(name, set())
            what = f"{market} universe part for {name}"
            out.append((parts[market], what, done or month_part(market, name)))
            final = last_call(month, market)
            deadline = final if held else min(max(due), final)
            out.append((deadline, f"{market} registration of {name}", done))
        month = next_month(month)
    return [item for item in out if item[0] <= now]


def table_ends(now: datetime) -> list:
    """From December of the KRX table's last year until the next year is added."""
    year = max(int(day[:4]) for day in KRX_HOLIDAYS)
    if now < at(date(year, 12, 1), 0):
        return []
    return [f"KRX_HOLIDAYS ends with {year}: add {year + 1}'s KRX closures"]


def overdue(now: datetime) -> list:
    try:
        items = expected(now)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return table_ends(now) + [f"the ledger or a registration did not verify: {exc}"]
    return table_ends(now) + [
        f"{what}: due {deadline:%Y-%m-%d %H:%M} UTC"
        for deadline, what, present in sorted(items)
        if not present and now - deadline <= timedelta(days=ALERT_DAYS)
    ]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--now", help="aware ISO time (default: now)")
    args = p.parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        p.error("--now needs a time zone")
    missing = overdue(now)
    for line in missing:
        print(f"OVERDUE {line}")
    if not missing:
        print(f"ok {now:%Y-%m-%d %H:%M} UTC: nothing overdue")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
