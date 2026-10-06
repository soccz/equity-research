"""Forward evaluation of registered ratings-v1 labels (docs/ratings-v1.md §6).

Pure functions over registrations and price rows ``[[date, adjclose, close], ...]``;
nothing is fetched or written.

- Entry: the close of the first session after the registration's market-local date,
  taken from the later of its stamp and its ledger record. A member without a close on
  that session sits the period out (no_entry_price); nobody enters late. A member whose
  series starts after its entry session does not cover the period: an error
  (series_not_covering), never no_entry_price. A member whose series ends before its
  entry session (delisted, renamed or truncated before entry) is left out of that
  period (series_ends_before_entry) and counted as an error, so the operator checks it.
- Exit: the next month's entry when that registration came inside its window
  (``registrationWindowSessions`` benchmark sessions after its T, judged on its
  registrationDay, D15). When the next month was missed the period ends at the close
  of the session after that window (missed_next_registration) and the portfolio is
  sold.
- Frozen periods (D12'): a completed period's per-member results are frozen by the
  first official evaluation after it completes (``freeze_record``); later evaluations
  pass them back (``frozen``), keep the frozen numbers and flag revised_after_freeze
  where fresh data differ by more than REVISION_TOLERANCE. Member errors hold a
  completed period back while the evaluation date is at most freezeGraceDays
  (PROTOCOL evaluation, 30) days after its exit date (``freeze_state``); after that it
  is frozen with those members recorded as unresolved (out of the returns, kept in the
  counts) and flagged frozen_with_unresolved. A period held back never holds back
  later periods. A frozen period also keeps each portfolio's turnover and costs (N5),
  so an earlier period resolved after the freeze never moves its net metrics.
- 선호 is reported net of costs (the primary metric), 회피 gross.
- A member without any price series is an error that is counted, never dropped quietly;
  so are registrations under different protocol hashes (mixed_protocol_hashes).

``forward_study_check`` recomputes the frozen 40-company study with the same holding and
portfolio functions and compares the result with ``equitylab.forward_study.evaluate``.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from fractions import Fraction
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from equitylab import forward_study
from equitylab.data import canonical, digest

from .common import MARKETS, PROTOCOL_VERSION, protocol_hash
from .rating import (
    AVOID,
    LABELS,
    PREFER,
    PROTOCOL,
    PROTOCOL_HASH,
    SIGNALS,
    iso_day,
    number,
    percentiles,
    positive,
    ranks,
    rows_through,
)
from .registry import read as read_registration
from .registry import setting

PORTFOLIOS = (PREFER, AVOID)
COSTED = {PREFER: True, AVOID: False}  # 회피 is reported gross (no costs)
MISSED = "missed_next_registration"
REVISED = "revised_after_freeze"
UNRESOLVED = "unresolved"  # a member error frozen after the grace (L3)
WITH_UNRESOLVED = "frozen_with_unresolved"
TOLERANCE = 1e-12  # forward-study comparison
REVISION_TOLERANCE = 1e-9  # D12': a frozen return differing by more is flagged
FREEZE_GRACE_DAYS = 30  # decided default of PROTOCOL evaluation.freezeGraceDays
ENDS_BEFORE_ENTRY = "series_ends_before_entry"
# Reasons that make a member's period an error: counted, never a quiet exclusion.
SERIES_ERRORS = (
    "no_price_series",
    "no_price_symbol",
    "series_not_covering",
    ENDS_BEFORE_ENTRY,
)
HELD = ("entryDate", "exitDate", "entryPrice", "exitPrice", "return")
# N5: what a frozen period keeps of each portfolio besides its members' results.
COST_KEYS = ("bought", "sold", "turnover", "cost", "liquidated")


def _day(row) -> str:
    return row[0]


def mean(values) -> float | None:
    values = list(values)
    return math.fsum(values) / len(values) if values else None


def spearman(xs: list, ys: list) -> float | None:
    """Rank correlation (mean ranks for ties); None below three pairs or without spread."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx = [float(r) for r in ranks(xs)]
    ry = [float(r) for r in ranks(ys)]
    mx, my = mean(rx), mean(ry)
    sxy = math.fsum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = math.fsum((a - mx) ** 2 for a in rx)
    syy = math.fsum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def market_calendar(series: list, after: str, through: str) -> list:
    """Sessions in (after, through] traded by at least half of the series listed by then.

    A series counts from its first session in the window onward, so stray rows and the
    tail of a series fetched later than the rest do not become sessions.
    """
    firsts, counts = [], Counter()
    for rows in series:
        days = {
            row[0]
            for row in rows_through(rows or [], through)
            if row[0] > after and positive(row[1]) is not None
        }
        if days:
            firsts.append(min(days))
            counts.update(days)
    firsts.sort()
    return [
        day for day in sorted(counts) if 2 * counts[day] >= bisect_right(firsts, day)
    ]


def holding(rows, entry: str, exit: str) -> dict:
    """Return from the close on the ``entry`` session to the close on ``exit``, else the
    last close before it (flagged last_price: delistings and halts).

    Without a valid close on the entry session itself the member is out of the period
    (no_entry_price); there is no late entry. A series that starts after the entry
    session does not cover the period (series_not_covering: a reused ticker or a reset
    history), and one that ends before it (series_ends_before_entry: delisted, renamed
    or truncated before entry) leaves the member out of the period; both are errors for
    the caller, never a missing entry price.
    """
    if not rows:
        return dict(reason="no_price_series")
    if rows[0][0] > entry:
        return dict(reason="series_not_covering")
    if rows[-1][0] < entry:
        return dict(reason=ENDS_BEFORE_ENTRY)
    start = bisect_left(rows, entry, key=_day)
    stop = bisect_right(rows, exit, key=_day)
    window = [row for row in rows[start:stop] if positive(row[1]) is not None]
    if not window or window[0][0] != entry or entry >= exit:
        return dict(reason="no_entry_price")
    first, last = window[0], window[-1]
    return {
        "entryDate": first[0],
        "exitDate": last[0],
        "entryPrice": float(first[1]),
        "exitPrice": float(last[1]),
        "return": last[1] / first[1] - 1,
        "flags": ["last_price"] if last[0] != exit else [],
    }


def _aware(stamp: str) -> datetime:
    moment = datetime.fromisoformat(stamp)
    if moment.utcoffset() is None:
        raise ValueError(f"timestamp without a timezone: {stamp}")
    return moment


def registered_day(registration: dict, zone: ZoneInfo) -> str:
    """Market-local date of the later of the stamp and the ledger record: the entry
    follows this day (D2, D12)."""
    stamps = [registration["registeredAt"]]
    recorded = (registration.get("ledger") or {}).get("recordedAt")
    if recorded:
        stamps.append(recorded)
    return max(map(_aware, stamps)).astimezone(zone).date().isoformat()


def registration_day(registration: dict, market: str, zone: ZoneInfo) -> str:
    """D15: the registration's own market-local date (registrationDay, the local date of
    registeredAt), on which the registry and the evaluator judge the window."""
    stored = registration.get("registrationDay")
    if isinstance(stored, dict) and stored.get(market):
        return iso_day(stored[market])
    return _aware(registration["registeredAt"]).astimezone(zone).date().isoformat()


def _next_session(calendar: list, day: str) -> str | None:
    i = bisect_right(calendar, day)
    return calendar[i] if i < len(calendar) else None


def _months_between(earlier: str, later: str) -> int:
    (y1, m1), (y2, m2) = (map(int, s[:7].split("-")) for s in (earlier, later))
    return (y2 * 12 + m2) - (y1 * 12 + m1)


def _month_after(month: str) -> str:
    year, index = int(month[:4]), int(month[5:7])
    return f"{year + index // 12:04d}-{index % 12 + 1:02d}"


def _last_session(sessions: list, month: str) -> str | None:
    """The month's last session, once a later session shows that the month is over."""
    inside = [s for s in sessions if s[:7] == month]
    return inside[-1] if inside and sessions[-1][:7] > month else None


def _exit(registration, following, market, calendar, bench, through) -> tuple:
    """(exit session or None, status, flags) of a period under the window rule (D4);
    ``bench`` are the sessions of the market's session-calendar series."""
    protocol = registration["protocol"]
    zone = ZoneInfo(protocol["registration"]["timezones"][market])
    window = int(setting("registrationWindowSessions", protocol))
    forced = int(setting("missedRegistrationExitSession", protocol)) - 1
    month, flags = _month_after(registration["month"]), []
    last = calendar[-1] if calendar else None
    if following is not None and following["month"] == month:
        t_next = following["asOf"][market]
        day = registration_day(following, market, zone)  # D15: window membership
        if len([s for s in bench if t_next < s < day]) < window:
            entry = _next_session(calendar, registered_day(following, zone))
            return (entry, "complete", flags) if entry else (last, "in_progress", flags)
        flags.append("late_next_registration")
    else:
        t_next = _last_session(bench, month)
    after = [s for s in bench if t_next is not None and s > t_next]
    if len(after) > forced:
        return after[forced], "complete", flags + [MISSED]
    if len(after) >= window and through > after[window - 1]:
        flags.append(MISSED)  # the deadline passed; the forced exit is still ahead
    return last, "in_progress", flags


def _net(out: dict) -> None:
    """The net metrics of a portfolio from its gross ones and its total ``cost``."""
    cost = out.get("cost")
    if cost is None or out.get("gross") is None:
        return
    out.update(
        net=out["gross"] - cost,
        netSectorExcess=out["sectorExcess"] - cost,
        netUniverseExcess=out["universeExcess"] - cost,
    )


def _portfolio(ids, held, excess, universe, before, costs) -> tuple:
    """Equal-weight holding of ``ids``. With ``costs`` the rebalancing from the drifted
    ``before`` weights is charged; without, the portfolio is reported gross only."""
    names = sorted(i for i in set(ids) if i in held)
    weights = {i: 1 / len(names) for i in names}
    keys = set(weights) | set(before)
    bought = math.fsum(max(weights.get(i, 0.0) - before.get(i, 0.0), 0.0) for i in keys)
    sold = math.fsum(max(before.get(i, 0.0) - weights.get(i, 0.0), 0.0) for i in keys)
    cost = None if costs is None else costs["buy"] * bought + costs["sell"] * sold
    out = dict(
        members=len(set(ids)),
        held=len(names),
        bought=bought,
        sold=sold,
        turnover=(bought + sold) / 2,
        costsApplied=costs is not None,
        cost=cost,
        gross=None,
        sectorBenchmark=None,
        sectorExcess=None,
        universeExcess=None,
        net=None,
        netSectorExcess=None,
        netUniverseExcess=None,
    )
    if not names:
        return out, {}
    gross = mean(held[i]["return"] for i in names)
    sector_excess = mean(excess[i] for i in names)
    out.update(
        gross=gross,
        sectorBenchmark=gross - sector_excess,
        sectorExcess=sector_excess,
        universeExcess=gross - universe,
    )
    _net(out)
    growth = 1 + gross
    drifted = (
        {i: weights[i] * (1 + held[i]["return"]) / growth for i in names}
        if growth > 0
        else {}
    )
    return out, drifted


def _liquidate(out: dict, drifted: dict, costs) -> None:
    """Charge the sale of the whole drifted portfolio at a forced exit."""
    sold = math.fsum(drifted.values())
    out["liquidated"] = sold
    if costs is None or out["cost"] is None or out["gross"] is None:
        return
    out["cost"] += costs["sell"] * sold
    _net(out)


def _keep_costs(out: dict, kept: dict) -> dict | None:
    """N5: a frozen period keeps the turnover and costs it was frozen with (COST_KEYS),
    and its net metrics follow them, so an earlier period resolved after the freeze
    (other drifted weights) never moves them. Returns the fresh values when they differ
    by more than REVISION_TOLERANCE (reported as a revision), else None."""
    fresh = {key: out.get(key) for key in COST_KEYS if key in out or key in kept}
    moved = any(
        (kept.get(key) is None) != (value is None)
        or (value is not None and abs(kept[key] - value) > REVISION_TOLERANCE)
        for key, value in fresh.items()
    )
    out.update({key: kept[key] for key in COST_KEYS if key in kept})
    _net(out)
    return fresh if moved else None


def _hit_rate(ids, excess, sign: int) -> tuple:
    values = [excess[i] for i in set(ids) if i in excess]
    return sum(1 for v in values if sign * v > 0), len(values)


def _coverage(rows: list, held: dict, missing: dict) -> dict:
    reasons = Counter(r.get("labelReason") for r in rows)
    labels = Counter(r.get("label") for r in rows if r.get("label") in LABELS)
    excluded = Counter(
        str(r.get("reason")) for r in rows if r.get("labelReason") == "excluded"
    )
    flags = Counter(flag for h in held.values() for flag in h["flags"])
    return dict(
        members=len(rows),
        excluded=reasons["excluded"],
        excludedReasons=dict(sorted(excluded.items())),
        eligible=len(rows) - reasons["excluded"],
        labeled={label: labels[label] for label in LABELS},
        insufficient=reasons["insufficient"],
        held=len(held),
        notHeld=dict(sorted(Counter(missing.values()).items())),
        flags=dict(sorted(flags.items())),
    )


def _differs(frozen: dict, fresh: dict) -> bool:
    """A fresh result that is not the frozen one (D12': dates, reason, or a return more
    than REVISION_TOLERANCE apart; adjusted price levels move with every dividend). An
    unresolved member differs once fresh data no longer show the error it was frozen
    with."""
    if frozen.get("reason") == UNRESOLVED:
        return fresh.get("reason") != frozen.get("error")
    if ("reason" in frozen) or ("reason" in fresh):
        return frozen.get("reason") != fresh.get("reason")
    return (
        frozen["entryDate"] != fresh["entryDate"]
        or frozen["exitDate"] != fresh["exitDate"]
        or abs(frozen["return"] - fresh["return"]) > REVISION_TOLERANCE
    )


def _frozen_problem(record: dict, registration: dict, market: str, eligible) -> str:
    """Why a frozen period record cannot stand for this registration's period."""
    block = registration.get("ledger") or {}
    if record.get("market") != market or record.get("month") != registration["month"]:
        return f"it is {record.get('market')}/{record.get('month')}"
    if (record.get("registration") or {}).get("hash") != block.get("hash"):
        return "its registration ledger hash differs"
    if record.get("protocolHash") != registration.get("protocolHash"):
        return "its protocol hash differs"
    if record.get("status") != "complete" or not (
        isinstance(record.get("entry"), str) and isinstance(record.get("exit"), str)
    ):
        return "it is not a completed period"
    members = record.get("members") or []
    if sorted(str(m.get("id")) for m in members) != sorted(r["id"] for r in eligible):
        return "its members are not the registration's eligible members"
    for m in members:
        dated = isinstance(m.get("entryDate"), str) and isinstance(
            m.get("exitDate"), str
        )
        valued = all(number(m.get(key)) is not None for key in HELD[2:])
        if not (isinstance(m.get("reason"), str) or (dated and valued)):
            return f"member {m.get('id')} has no frozen result"
    costs = record.get("costs", {})  # N5; a record frozen before N5 has none
    if not isinstance(costs, dict) or not all(
        isinstance(kept, dict)
        and all(
            kept[key] is None or number(kept[key]) is not None
            for key in COST_KEYS
            if key in kept
        )
        for kept in costs.values()
    ):
        return "its costs are unreadable"
    return ""


def _fresh(eligible, entry, exit, series, stored, sources, errors) -> tuple:
    """Holdings from the fresh series: (held, missing, series sha by id)."""
    held, missing, shas = {}, {}, {}
    for r in eligible:
        symbol = r.get("priceSymbol")
        h = (
            holding(series.get(symbol), entry, exit)
            if symbol
            else dict(reason="no_price_symbol")
        )
        shas[r["id"]] = sources.get(symbol)
        if h.get("reason") in SERIES_ERRORS:
            errors.append(dict(id=r["id"], symbol=symbol, reason=h["reason"]))
        if "reason" in h:
            missing[r["id"]] = h["reason"]
            continue
        if symbol in stored:
            h["flags"].append("stored_series")
        held[r["id"]] = h
    return held, missing, shas


def _reuse(eligible, record, entry, exit, series) -> tuple:
    """Holdings from a frozen period: (held, missing, series sha by id, revisions)."""
    frozen = {m["id"]: m for m in record["members"]}
    held, missing, shas, revised = {}, {}, {}, {}
    for r in eligible:
        kept = frozen[r["id"]]
        symbol = r.get("priceSymbol")
        fresh = (
            holding(series.get(symbol), entry, exit)
            if symbol
            else dict(reason="no_price_symbol")
        )
        shas[r["id"]] = kept.get("seriesSha256")
        if "reason" in kept:
            missing[r["id"]] = kept["reason"]
        else:
            held[r["id"]] = {
                **{key: kept[key] for key in HELD},
                "flags": [f for f in kept.get("flags") or [] if f != REVISED],
            }
        if _differs(kept, fresh):
            revised[r["id"]] = {
                key: fresh.get(key) for key in ("reason", *HELD) if key in fresh
            }
            if r["id"] in held:
                held[r["id"]]["flags"].append(REVISED)
    return held, missing, shas, revised


def _period(market, registration, following, calendar, bench, context) -> tuple:
    series, before, stored, through, sources, frozen = context
    protocol = registration["protocol"]
    zone = ZoneInfo(protocol["registration"]["timezones"][market])
    day = registered_day(registration, zone)
    entry = _next_session(calendar, day)
    exit, status, flags = _exit(
        registration, following, market, calendar, bench, through
    )
    if entry is None or exit is None or exit <= entry:
        status, exit = "pending", None
    rows = [r for r in registration["rows"] if r.get("market") == market]
    eligible = [r for r in rows if r.get("labelReason") != "excluded"]
    block = registration.get("ledger") or {}
    out = dict(
        market=market,
        month=registration["month"],
        asOf=registration["asOf"][market],
        registeredAt=registration["registeredAt"],
        recordedAt=block.get("recordedAt"),
        registrationDay=registration_day(registration, market, zone),
        entryDay=day,
        eventId=block.get("eventId"),
        ledgerHash=block.get("hash"),
        protocolHash=registration["protocolHash"],
        status=status,
        entry=entry,
        exit=exit,
        flags=flags,
        nextMonth=following["month"] if following else None,
        gapMonths=(
            _months_between(registration["month"], following["month"])
            if following
            else None
        ),
        frozen=None,
        freezeGraceDays=grace_days(protocol),
        errors=[],
    )
    record = None
    if registration.get("kind") == "registration":
        record = frozen.get((market, registration["month"]))
    if record is not None:
        problem = _frozen_problem(record, registration, market, eligible)
        if problem:
            out["errors"].append(
                dict(
                    reason="frozen_period_mismatch", detail=f"frozen record: {problem}"
                )
            )
            record = None
    if record is not None:
        fresh = dict(entry=entry, exit=exit, status=status)
        entry, exit, status = record["entry"], record["exit"], record["status"]
        changed = {k: v for k, v in fresh.items() if record.get(k) != v}
        out.update(
            entry=entry,
            exit=exit,
            status=status,
            flags=[f for f in record.get("flags") or [] if f != REVISED],
            frozen=dict(
                frozenAt=record.get("frozenAt"),
                through=record.get("through"),
                unresolved=list(record.get("unresolved") or []),
            ),
        )
        if changed:
            out["flags"].append(REVISED)
            out["revisions"] = dict(period=changed)
        flags = out["flags"]
    if status == "pending":
        out["coverage"] = _coverage(rows, {}, {})
        return out, before
    if record is None:
        held, missing, shas = _fresh(
            eligible, entry, exit, series, stored, sources, out["errors"]
        )
        revised, unresolved = {}, {}
    else:
        held, missing, shas, revised = _reuse(eligible, record, entry, exit, series)
        if revised:
            out["revisions"] = dict(out.get("revisions") or {}, members=revised)
        unresolved = {  # L3: the error each unresolved member was frozen with
            m["id"]: m.get("error")
            for m in record["members"]
            if m.get("reason") == UNRESOLVED
        }
    sector_of = {r["id"]: r.get("sector") for r in eligible}
    by_sector = defaultdict(list)
    for i, h in held.items():
        by_sector[sector_of[i]].append(h["return"])
    sector_mean = {sector: mean(values) for sector, values in by_sector.items()}
    universe = mean(h["return"] for h in held.values())
    excess = {i: h["return"] - sector_mean[sector_of[i]] for i, h in held.items()}
    costs = protocol["costs"][market]
    forced = status == "complete" and MISSED in flags
    after, portfolios, drifts = {}, {}, {}
    # N5: a frozen period's turnover and costs, by portfolio (freeze_record "costs").
    kept_costs = (record or {}).get("costs") or {}
    moved_costs = {}

    def build(key, ids, charged):
        out_, drifts[key] = _portfolio(
            ids, held, excess, universe, before.get(key, {}), costs if charged else None
        )
        if forced:
            _liquidate(out_, drifts[key], costs if charged else None)
        after[key] = {} if forced else drifts[key]
        if isinstance(kept_costs.get(key), dict):
            fresh = _keep_costs(out_, kept_costs[key])
            if fresh is not None:
                moved_costs[key] = fresh
        return out_

    for label in PORTFOLIOS:
        ids = [r["id"] for r in eligible if r.get("label") == label]
        portfolios[label] = build(label, ids, COSTED[label])
    hits = {
        PREFER: _hit_rate(
            [r["id"] for r in eligible if r.get("label") == PREFER], excess, 1
        ),
        AVOID: _hit_rate(
            [r["id"] for r in eligible if r.get("label") == AVOID], excess, -1
        ),
    }
    both = (sum(h for h, _ in hits.values()), sum(n for _, n in hits.values()))
    pairs = [
        (number(r.get("composite")), held[r["id"]]["return"])
        for r in eligible
        if r["id"] in held and number(r.get("composite")) is not None
    ]
    prefer_above = Fraction(protocol["terciles"]["preferAbove"])
    signal_baselines = {}
    for signal in SIGNALS:
        z = {r["id"]: number((r.get("z") or {}).get(signal)) for r in eligible}
        ranked = percentiles({i: v for i, v in z.items() if v is not None})
        top = sorted(i for i, p in ranked.items() if p > prefer_above)
        signal_baselines[signal] = build(f"signal:{signal}", top, True)
    if moved_costs:  # N5: the frozen costs stand; fresh drifted weights differ
        out.setdefault("revisions", {})["costs"] = moved_costs
        if REVISED not in out["flags"]:
            out["flags"].append(REVISED)
    symbol = protocol["benchmarks"][market]
    index = holding(series.get(symbol), entry, exit)
    index_sha = sources.get(symbol)
    if record is not None and isinstance(record.get("benchmark"), dict):
        kept = record["benchmark"]
        if _differs(kept, index):
            out.setdefault("revisions", {})["benchmark"] = {
                key: index.get(key) for key in ("reason", *HELD) if key in index
            }
        index = {k: v for k, v in kept.items() if k not in ("symbol", "seriesSha256")}
        index_sha = kept.get("seriesSha256")
    prefer, avoid = portfolios[PREFER], portfolios[AVOID]
    out.update(
        coverage=_coverage(rows, held, missing),
        portfolios=portfolios,
        spread=(
            prefer["sectorExcess"] - avoid["sectorExcess"]
            if prefer["held"] and avoid["held"]
            else None
        ),
        spreadRaw=(
            prefer["gross"] - avoid["gross"]
            if prefer["held"] and avoid["held"]
            else None
        ),
        ic=spearman([a for a, _ in pairs], [b for _, b in pairs]),
        icPairs=len(pairs),
        hitRate={
            **{label: h / n if n else None for label, (h, n) in hits.items()},
            "combined": both[0] / both[1] if both[1] else None,
        },
        sectors={
            str(sector): dict(members=len(by_sector[sector]), mean=value)
            for sector, value in sorted(sector_mean.items(), key=lambda kv: str(kv[0]))
        },
        baselines=dict(
            signals=signal_baselines,
            equalWeight=dict(held=len(held), gross=universe),
            benchmark=dict(symbol=symbol, seriesSha256=index_sha, **index),
        ),
        members=[
            dict(
                id=r["id"],
                sector=r.get("sector"),
                label=r.get("label"),
                composite=number(r.get("composite")),
                symbol=r.get("priceSymbol"),
                seriesSha256=shas.get(r["id"]),
                **(
                    {**held[r["id"]], "sectorExcess": excess[r["id"]]}
                    if r["id"] in held
                    else {"reason": missing[r["id"]]}
                ),
                **({"error": unresolved[r["id"]]} if r["id"] in unresolved else {}),
                **({REVISED: revised[r["id"]]} if r["id"] in revised else {}),
            )
            for r in eligible
        ],
    )
    return out, after


def grace_days(protocol: dict | None = None) -> int:
    """L3: PROTOCOL evaluation.freezeGraceDays of the registration's protocol, else of
    the code's, else the decided FREEZE_GRACE_DAYS."""
    for source in (protocol, PROTOCOL):
        value = ((source or {}).get("evaluation") or {}).get("freezeGraceDays")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return FREEZE_GRACE_DAYS


def unresolved_from(period: dict) -> str | None:
    """L3: the first evaluation date on which a completed period with member errors is
    frozen with those members unresolved: member errors hold it back while the
    evaluation date is at most freezeGraceDays calendar days after its exit date."""
    exit_ = period.get("exit")
    if not isinstance(exit_, str):
        return None
    days = period.get("freezeGraceDays")
    days = FREEZE_GRACE_DAYS if days is None else int(days)
    return (date.fromisoformat(iso_day(exit_)) + timedelta(days=days + 1)).isoformat()


def freeze_state(period: dict, through) -> tuple[str, str]:
    """``(state, detail)`` of a period for freezing by an evaluation through
    ``through``: "freeze"; "wait" while member errors hold a completed period back
    (unresolved_from; a period waiting never holds back later periods); "frozen"
    already; "blocked" when it is not complete or has an error that is not a member's
    (a frozen record that does not match: the operator has to look)."""
    if period.get("frozen"):
        return "frozen", "frozen already"
    if period.get("status") != "complete":
        return "blocked", f"the period is {period.get('status')}"
    errors = period.get("errors") or []
    other = [e for e in errors if not e.get("id")]
    if other:
        return "blocked", "; ".join(str(e.get("reason")) for e in other)
    start = unresolved_from(period)
    if errors and (start is None or iso_day(through) < start):
        return "wait", (
            f"{len(errors)} member error(s): frozen with them unresolved by an "
            f"evaluation through {start} or later, unless resolved before"
        )
    return "freeze", ""


def freeze_record(period: dict, through, frozen_at: str) -> dict:
    """D12': the record that freezes a completed period: its dates and flags, each
    eligible member's result (entry and exit dates and closes, return, flags, or the
    reason it was not held) with sector, label, composite and the SHA-256 of the series
    original, the benchmark's result and (N5) each portfolio's turnover and costs
    (``costs``: COST_KEYS by portfolio, 선호, 회피 and signal:<signal>), which later
    evaluations keep with the net metrics that follow from them.

    L3: member errors hold the period back while ``through`` (the evaluation date) is
    at most freezeGraceDays after its exit date (freeze_state); after that those
    members are frozen as unresolved (``error``: the reason) and the period is flagged
    frozen_with_unresolved. A period error that is not a member's is never frozen."""
    through = iso_day(through)
    state, detail = freeze_state(period, through)
    if state == "frozen":
        raise ValueError("the period is frozen already")
    if state != "freeze":
        raise ValueError(
            "only a completed period is frozen, one with member errors once past its "
            f"grace ({state}: {detail})"
        )
    failed = {e["id"]: e.get("reason") for e in period.get("errors") or []}
    members = []
    for m in period["members"]:
        item = {
            key: m.get(key)
            for key in ("id", "symbol", "sector", "label", "composite", "seriesSha256")
        }
        if m.get("id") in failed:
            item.update(reason=UNRESOLVED, error=failed[m["id"]] or m.get("reason"))
        elif "reason" in m:
            item["reason"] = m["reason"]
        else:
            item.update({key: m[key] for key in HELD})
            item["flags"] = [f for f in m.get("flags") or [] if f != REVISED]
        members.append(item)
    flags = [f for f in period["flags"] if f not in (REVISED, WITH_UNRESOLVED)]
    if failed:
        flags.append(WITH_UNRESOLVED)
    benchmark = period["baselines"]["benchmark"]
    built = dict(period["portfolios"])  # N5: keyed as _period builds them
    built.update(
        {f"signal:{name}": p for name, p in period["baselines"]["signals"].items()}
    )
    return dict(
        version=PROTOCOL_VERSION,
        kind="frozen-period",
        market=period["market"],
        month=period["month"],
        asOf=period["asOf"],
        protocolHash=period["protocolHash"],
        registration=dict(
            eventId=period.get("eventId"),
            hash=period.get("ledgerHash"),
            recordedAt=period.get("recordedAt"),
            registrationDay=period.get("registrationDay"),
        ),
        frozenAt=frozen_at,
        through=through,
        status=period["status"],
        entry=period["entry"],
        exit=period["exit"],
        flags=flags,
        unresolved=sorted(str(i) for i in failed),
        members=members,
        costs={key: {k: p[k] for k in COST_KEYS if k in p} for key, p in built.items()},
        benchmark={
            key: value
            for key, value in benchmark.items()
            if key in ("symbol", "seriesSha256", "reason", "flags", *HELD)
        },
    )


def _summary(periods: list, calendar: list) -> dict:
    complete = [p for p in periods if p["status"] == "complete"]

    def average(values) -> dict:
        values = [v for v in values if v is not None]
        return dict(mean=mean(values), periods=len(values))

    return dict(
        complete=len(complete),
        inProgress=sum(p["status"] == "in_progress" for p in periods),
        pending=sum(p["status"] == "pending" for p in periods),
        frozen=sum(bool(p.get("frozen")) for p in periods),
        frozenWithUnresolved=sum(WITH_UNRESOLVED in p["flags"] for p in periods),
        unresolvedMembers=sum(
            m.get("reason") == UNRESOLVED
            for p in periods
            for m in p.get("members") or []
        ),
        revisedAfterFreeze=sum(
            REVISED in p["flags"] or "revisions" in p for p in periods
        ),
        valuedThrough=calendar[-1] if calendar else None,
        missedRegistrations=sum(MISSED in p["flags"] for p in periods),
        seriesErrors=sum(len(p["errors"]) for p in periods),
        costBasis={PREFER: "net", AVOID: "gross"},
        primary=average(p["portfolios"][PREFER]["netSectorExcess"] for p in complete),
        primaryNonNeutral=average(
            p["portfolios"][PREFER]["netUniverseExcess"] for p in complete
        ),
        avoid=average(p["portfolios"][AVOID]["sectorExcess"] for p in complete),
        avoidNonNeutral=average(
            p["portfolios"][AVOID]["universeExcess"] for p in complete
        ),
        spread=average(p["spread"] for p in complete),
        ic=average(p["ic"] for p in complete),
    )


def _load(item):
    return read_registration(item) if isinstance(item, (str, Path)) else item


def _usable(registrations, include_dry_run: bool) -> tuple:
    usable, issues = [], []
    for item in registrations:
        registration = _load(item)
        tag = registration.get("month") or str(item)
        kinds = ("registration", "dry-run") if include_dry_run else ("registration",)
        problem = None
        if registration.get("version") != PROTOCOL_VERSION:
            problem = "version_mismatch"
        elif protocol_hash(registration.get("protocol") or {}) != registration.get(
            "protocolHash"
        ):
            problem = "protocol_hash_mismatch"
        elif registration.get("kind") not in kinds:
            problem = f"kind_{registration.get('kind')}_not_evaluated"
        if problem:
            issues.append(dict(registration=tag, issue=problem))
            continue
        if registration["protocolHash"] != PROTOCOL_HASH:
            issues.append(dict(registration=tag, issue="protocol_differs_from_code"))
        if registration["kind"] == "registration" and not (
            registration.get("ledger") or {}
        ).get("recordedAt"):
            issues.append(dict(registration=tag, issue="ledger_unverified"))
        usable.append(registration)
    hashes = sorted({r["protocolHash"] for r in usable})
    if len(hashes) > 1:  # D11': one protocol across every evaluated registration
        issues.append(dict(issue="mixed_protocol_hashes", hashes=hashes))
    return usable, issues


ERROR_ISSUES = ("benchmark_series_missing", "mixed_protocol_hashes")


def evaluate(
    registrations,
    series_by_symbol: dict,
    through,
    *,
    include_dry_run=False,
    stored=(),
    sources=None,
    frozen=None,
) -> dict:
    """Period and market metrics for the registrations, up to ``through``.

    ``registrations`` are registration dicts (as registry.registrations() returns them,
    with their ledger block) or paths (ledger-verified when read); ``series_by_symbol``
    maps price symbols (members and benchmarks) to price rows; ``stored`` names the
    symbols whose rows came from storage after a failed fetch (flagged stored_series);
    ``sources`` maps symbols to the SHA-256 of the original their rows were parsed from
    (recorded per member). ``frozen`` maps ``(market, month)`` to a freeze_record() of a
    real registration's completed period, whose results are kept (D12'). Dry runs are
    skipped unless ``include_dry_run`` (development only, never reported). ``errors``
    counts members without a usable series (none, or one starting after or ending
    before the entry session), frozen records that do not match, missing benchmarks
    and mixed protocol hashes.
    """
    through = iso_day(through)
    usable, issues = _usable(registrations, include_dry_run)
    stored = set(stored)
    sources = {
        symbol: value.get("sha256") if isinstance(value, dict) else value
        for symbol, value in (sources or {}).items()
    }
    frozen = dict(frozen or {})
    periods, summary = [], {}
    for market in MARKETS:
        mine = sorted(
            (r for r in usable if market in (r.get("asOf") or {})),
            key=lambda r: r["asOf"][market],
        )
        if not mine:
            continue
        months = Counter(r["asOf"][market][:7] for r in mine)
        repeated = sorted(month for month, n in months.items() if n > 1)
        if repeated:
            raise ValueError(f"{market}: several registrations for {repeated}")
        first = min(
            registered_day(
                r, ZoneInfo(r["protocol"]["registration"]["timezones"][market])
            )
            for r in mine
        )
        symbols = {
            r.get("priceSymbol")
            for registration in mine
            for r in registration["rows"]
            if r.get("market") == market and r.get("labelReason") != "excluded"
        }
        benchmarks = {r["protocol"]["benchmarks"][market] for r in mine} | {
            setting("sessionCalendar", r["protocol"])[market] for r in mine
        }
        symbols |= benchmarks
        calendar = market_calendar(
            [series_by_symbol.get(s) for s in sorted(symbols - {None})], first, through
        )
        for symbol in sorted(benchmarks):
            if not series_by_symbol.get(symbol):
                issues.append(
                    dict(market=market, issue="benchmark_series_missing", symbol=symbol)
                )
        before, results = {}, []
        for k, registration in enumerate(mine):
            following = mine[k + 1] if k + 1 < len(mine) else None
            symbol = setting("sessionCalendar", registration["protocol"])[market]
            bench = sorted(
                row[0]
                for row in rows_through(series_by_symbol.get(symbol) or [], through)
                if positive(row[1]) is not None
            )
            period, before = _period(
                market,
                registration,
                following,
                calendar,
                bench,
                (series_by_symbol, before, stored, through, sources, frozen),
            )
            results.append(period)
        periods.extend(results)
        summary[market] = _summary(results, calendar)
    errors = sum(len(p["errors"]) for p in periods) + sum(
        i.get("issue") in ERROR_ISSUES for i in issues
    )
    return dict(
        version=PROTOCOL_VERSION,
        protocolHash=PROTOCOL_HASH,
        through=through,
        valuedThrough={m: s["valuedThrough"] for m, s in summary.items()},
        dryRunIncluded=include_dry_run,
        periods=periods,
        summary=summary,
        issues=issues,
        errors=errors,
    )


# --- 40-company forward study (evaluator integrity check, §8) ---------------------


def _forward_symbol(company: str, market: str, series: dict) -> str | None:
    candidates = [company] + (
        [f"{company}.KS", f"{company}.KQ"] if market == "KR" else []
    )
    return next((c for c in candidates if c in series), None)


def _round_trip(selected, held, cost) -> tuple:
    """(gross, net) of buying ``selected`` equally and selling it all at the end, with
    this module's portfolio function on both legs."""
    if not selected:
        return 0, 0
    legs, flat = dict(buy=cost, sell=cost), {c: 0.0 for c in held}
    bought, drifted = _portfolio(selected, held, flat, 0.0, {}, legs)
    sold, _ = _portfolio([], held, flat, 0.0, drifted, legs)
    return bought["gross"], bought["gross"] - bought["cost"] - sold["cost"]


def _forward_window(spec, entry, end, symbols, series, through, cost) -> dict:
    held, missing = {}, []
    for company in spec["members"]:
        rows = rows_through(series.get(symbols[company]) or [], through)
        h = holding(rows, entry, end)
        if "reason" in h or h["exitDate"] != end:  # the study needs both exact closes
            missing.append(company)
            continue
        held[company] = h
    out = dict(entry=entry, end=end)
    if missing:
        return dict(
            out,
            status="unresolved",
            missing=missing,
            reason="공통 진입·종료 가격 미확인; 대상 제외 또는 날짜 변경 없음",
        )
    policies = {}
    for name, selected in spec["selection"].items():
        gross, net = _round_trip(selected, held, cost)
        policies[name] = dict(selected=selected, gross=gross, net=net)
    returns = {c: h["return"] for c, h in held.items()}
    winner = max(returns, key=lambda c: (returns[c], c))
    chosen = [winner] if returns[winner] > 2 * cost else []
    gross, net = _round_trip(chosen, held, cost)
    policies["oracle_upper_bound"] = dict(selected=chosen, gross=gross, net=net)
    baseline = policies["equal_weight"]["net"]
    for policy in policies.values():
        policy["differenceFromBaseline"] = policy["net"] - baseline
    return dict(out, status="observed", policies=policies, companyReturns=returns)


def _close(a, b) -> bool:
    if a == b:
        return True
    a, b = number(a), number(b)
    return a is not None and b is not None and abs(a - b) <= TOLERANCE


def _differences(mine: list, theirs: list) -> list:
    """Every field on which the recomputation and the study's own evaluator disagree."""
    found = []
    if len(mine) != len(theirs):
        found.append(dict(field="results", ratings=len(mine), study=len(theirs)))
    for a, b in zip(mine, theirs):
        at = f"{a.get('market')}/{a.get('horizon')}"
        keys = ("market", "horizon", "status", "observedSessions", "requiredSessions")
        for key in (*keys, "entry", "end", "missing"):
            if a.get(key) != b.get(key):
                found.append(
                    dict(at=at, field=key, ratings=a.get(key), study=b.get(key))
                )
        ours, study = a.get("policies") or {}, b.get("policies") or {}
        if set(ours) != set(study):
            found.append(
                dict(at=at, field="policies", ratings=sorted(ours), study=sorted(study))
            )
        for name in sorted(set(ours) & set(study)):
            if ours[name]["selected"] != study[name]["selected"]:
                found.append(
                    dict(
                        at=at,
                        field=f"{name}.selected",
                        ratings=ours[name]["selected"],
                        study=study[name]["selected"],
                    )
                )
            for field in ("gross", "net", "differenceFromBaseline"):
                if not _close(ours[name].get(field), study[name].get(field)):
                    found.append(
                        dict(
                            at=at,
                            field=f"{name}.{field}",
                            ratings=ours[name].get(field),
                            study=study[name].get(field),
                        )
                    )
        ours, study = a.get("companyReturns") or {}, b.get("companyReturns") or {}
        for company in sorted(set(ours) | set(study)):
            if not _close(ours.get(company), study.get(company)):
                found.append(
                    dict(
                        at=at,
                        field=f"companyReturns.{company}",
                        ratings=ours.get(company),
                        study=study.get(company),
                    )
                )
    return found


def forward_study_check(path, series_by_symbol: dict, through) -> dict:
    """Recompute data/forward-study.json (read-only) with this module's holding and
    portfolio functions and compare it with ``equitylab.forward_study.evaluate``.

    The study's own contract applies, not ratings-v1's: entry on the calendar company's
    first session after the registration day, exits after 21/63 of its sessions, identical
    dates for every member (a whole market-horizon is unresolved when any price is
    missing), selections against its equal-weight baseline and the perfect-foresight
    bound, and a round trip (buying and selling the whole portfolio) at the one-way cost
    per leg. ``matches`` is False when anything differs; ``differences`` lists it.
    """
    path = Path(path)
    blob = path.read_bytes()
    through = iso_day(through)
    out = dict(
        path=str(path),
        fileSha256=digest(blob),
        through=through,
        independentAlphaValidation=False,
    )
    try:
        contract = json.loads(blob)
        unsigned = {k: v for k, v in contract.items() if k != "protocolHash"}
        intact = digest(canonical(unsigned)) == contract["protocolHash"]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return dict(out, status="invalid", error=f"{type(exc).__name__}: {exc}")
    if not intact:
        return dict(out, status="invalid", error="protocolHash does not match contract")
    out.update(
        status="ok",
        version=contract.get("version"),
        protocolHash=contract["protocolHash"],
        registeredAt=contract.get("registeredAt"),
    )
    cost = contract["oneWayCost"]
    results, companies = [], {}
    for market, spec in contract["markets"].items():
        names = [spec["calendarCompany"], *spec["members"]]
        symbols = {c: _forward_symbol(c, market, series_by_symbol) for c in names}
        for company in names:
            rows = series_by_symbol.get(symbols[company]) or []
            companies[company] = dict(
                id=company,
                prices=[dict(date=row[0], adjustedClose=row[1]) for row in rows],
                sources=[],
            )
        anchor = series_by_symbol.get(symbols[spec["calendarCompany"]]) or []
        calendar = sorted(
            row[0] for row in anchor if spec["registrationDay"] < row[0] <= through
        )
        for horizon in contract["horizons"]:
            row = dict(
                market=market,
                horizon=horizon,
                status="pending",
                observedSessions=len(calendar),
                requiredSessions=horizon + 1,
                symbols=symbols,
            )
            if not anchor:
                row.update(
                    status="unresolved",
                    missing=[spec["calendarCompany"]],
                    reason="지정한 달력 종목의 가격 자료 미확인; 다른 달력으로 대체하지 않음",
                )
            elif len(calendar) > horizon:
                row.update(
                    _forward_window(
                        spec,
                        calendar[0],
                        calendar[horizon],
                        symbols,
                        series_by_symbol,
                        through,
                        cost,
                    )
                )
            results.append(row)
    snapshot = dict(
        asOf=through,
        contentHash="ratings-forward-check",
        companies=list(companies.values()),
    )
    reference = forward_study.evaluate(contract, snapshot)["results"]
    differences = _differences(results, reference)
    out.update(
        results=results,
        reference="equitylab.forward_study.evaluate",
        matches=not differences,
        differences=differences,
    )
    return out
