"""ratings-v1 monthly pipeline: universe -> collect -> score, plus evaluation and checks.

    universe       --as-of D [--gate] [--offline] [--markets US KR] [--limit N]
                   [--overwrite]
    universe-merge --as-of D [--as-of-us D] [--as-of-kr D] [--gate] [--limit N]
                   [--overwrite]
    collect        --month M | --as-of D [--gate] [--markets US KR] [--limit N]
                   [--offline] [--skip-failed] [--refresh]
    score          --as-of-us D --as-of-kr D [--dry-run] [--allow-errors] [--offline]
    evaluate       --through D [--offline] [--files F ...] [--out F]
    forward-check  --through D [--offline]
    coverage       --as-of D --gate [--markets US KR] [--offline]

Everything is read from and written to data/ratings (docs/ratings-v1.md §9).

- universe builds each market apart and saves its part as data/ratings/universe/
  <T>/<market>.json (D5': Korea after T's close, the US once SSGA posts T's holdings,
  normally the next US business day), then re-merges the month's parts into
  data/ratings/universe/<asOf>.json with each market's own build and capture times;
  universe-merge rewrites that file from the parts. A market whose last session
  differs (December) is built under its own T; the merge finds its only part of the
  month (--as-of-us / --as-of-kr pick one when there are several). When the part is
  saved but the month cannot be merged, it says so (part saved, month not merged;
  exit 2): fix the cause and run universe-merge.
- --gate selects the computability-check (coverage gate) universe, kept apart from
  the month's universe (H1): parts in <T>-gate/, merged into <asOf>-gate.json, its
  checkpoints in data/ratings/work/<asOf>-gate/. coverage runs on it only.
- collect appends one JSON line per member attempt to data/ratings/work/<T>/
  <market>.jsonl, recording the protocol hash and the code digest. Each market is
  collected at its own T from the month's universe (asOfByMarket; --month finds it);
  --as-of, for months whose markets share T, is refused unless it is the T of every
  market collected (N8). Price series run from LOOKBACK_DAYS before T through the
  retrieval date, so splits after T reach the market cap. A rerun skips members whose
  checkpoint is current (collected online after T's close under this protocol and
  code, own series with a close on T, KR series retrieved no earlier than the
  universe's share capture: N6) and re-collects the rest; --refresh re-collects all.
  --month takes the month's merge without a -limit<N> suffix when there is one.
  A company failure is recorded, never fatal; a Korean preferred class whose series
  fails is priced at the common close (class_price_proxy, classFailures), never a
  checkpoint error; members the universe could not profile are not collected
  (insufficient).
- score turns current checkpoints into a registration (stale ones only into a dry run)
  and records the SHA-256 of each checkpoint file. It fetches each market's benchmark
  through today so the registry can check that T is the month's last session and the
  registration is inside its window. A market whose coverage gate failed is left out
  (Korea) or blocks registration (US). --allow-errors accepts recorded collection
  errors and members without a close on T (they get no price-based signal); it never
  accepts a stale checkpoint (offline, before T's close, other protocol or code, or a
  KR series retrieved before the universe's share capture).
- coverage applies the §7 gate over every non-financial member of the
  computability-check universe and, at the pinned asOf on or after the check date,
  asks the registry to record each market's verdict once: only from a merged gate
  universe that passes the registration checks and a complete collection (online,
  after the close, current, no errors), with the SHA-256 of the checkpoint file it
  read; otherwise it only reports.
- evaluate reads the registrations from the ledger. An official run (the whole ledger,
  no dry runs, online, benchmark and session-calendar series freshly fetched, one
  protocol, an evaluation date not after today) writes data/ratings/evaluation/
  <through>.json, merges every downloaded original into data/ratings/series (never
  shrinking it) and freezes each newly completed period in data/ratings/periods/
  <market>/<YYYY-MM>.json; later runs keep the frozen results. A period with member
  errors (counted: exit 1) is frozen only once the evaluation date is more than
  freezeGraceDays past its exit, with those members unresolved (L3); while it waits,
  later periods are still frozen. A market's periods are frozen only when the
  evaluation date is not after that market's local date (N2), and a frozen period
  keeps its turnover and costs (N5). A failed download falls back, flagged, to a kept
  original re-parsed after its hash is verified.

Online runs need SEC_USER_AGENT (US) and the OpenDART key (KR, via --dart-env or
EQUITY_DART_ENV); the key stays in this process and is never printed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from equitylab.data import canonical, digest  # noqa: E402
from ratings import (  # noqa: E402
    common,
    evaluate,
    fundamentals,
    prices,
    rating,
    registry,
    universe,
)

WORK = common.RATINGS / "work"
EVALUATIONS = common.RATINGS / "evaluation"
SERIES = common.RATINGS / "series"
PERIODS = common.RATINGS / "periods"
FORWARD_CHECKS = common.RATINGS / "forward-check"
FORWARD_STUDY = ROOT / "data/forward-study.json"
CHECKPOINT = "ratings-v1-collect-1"
# docs/ratings-v1.md §7: the check date, the pinned asOf and the share of non-financial
# members with >= minSignals signals required per market (rating.PROTOCOL).
CHECK = registry.gate_rule()
GATE = CHECK["thresholds"]
# A smoke build's stem (universe._stem): <T>-limit<N>, <T>-gate-limit<N>.
SMOKE = re.compile(r"-limit\d+$")


class CliError(Exception):
    """A request the command cannot carry out: bad input, missing data or a refusal."""


def day(text: str) -> str:
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {text!r}") from None


def calendar_month(text: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", text):
        raise argparse.ArgumentTypeError(f"not a YYYY-MM month: {text!r}")
    return text


def count(text: str) -> int:
    if not re.fullmatch(r"[1-9]\d*", text):
        raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}")
    return int(text)


def clock() -> datetime:
    return datetime.now(timezone.utc)


def now() -> str:
    return clock().isoformat()


def zone(market: str) -> ZoneInfo:
    return ZoneInfo(rating.PROTOCOL["registration"]["timezones"][market])


def today(market: str) -> str:
    """The market-local date now: signal and benchmark series run through it."""
    return clock().astimezone(zone(market)).date().isoformat()


def window_start(as_of: str) -> str:
    """First day of a signal series: LOOKBACK_DAYS before T, however late it is fetched."""
    return (
        date.fromisoformat(as_of) - timedelta(days=prices.LOOKBACK_DAYS)
    ).isoformat()


def rel(path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def inside(path, folder: Path) -> bool:
    return Path(path).resolve().is_relative_to(folder.resolve())


def credentials(markets, dart_env=None) -> None:
    """Fail before any download when a market's credential is missing (never shown)."""
    try:
        if "US" in markets:
            common.sec_user_agent()
        if "KR" in markets:
            common.ensure_dart_key(dart_env)
    except (common.FetchError, ValueError, OSError) as exc:
        raise CliError(f"credentials: {exc}") from None


def downloads(manifests, since: str) -> dict:
    """Originals retrieved during this run, by provider (stored pointers are older)."""
    seen = {
        (m.get("file"), m.get("retrievedAt")): m.get("provider") or "unknown"
        for m in manifests
        if isinstance(m, dict) and (m.get("retrievedAt") or "") >= since
    }
    return dict(sorted(Counter(seen.values()).items()))


def timing(values: list) -> dict:
    if not values:
        return dict(n=0)
    return dict(
        n=len(values),
        mean=round(statistics.fmean(values), 3),
        median=round(statistics.median(values), 3),
        max=round(max(values), 3),
        total=round(math.fsum(values), 1),
    )


def reason(text) -> str:
    """Error text grouped across companies: identifiers and symbols are masked."""
    text = re.sub(r"^(prices) \S+:", r"\1:", str(text))
    text = re.sub(r"\b(sec-facts|dart-acnt|yahoo)-\S+", r"\1-*", text)
    text = re.sub(r"\d{5,}", "#", text)
    return text[:120]


# --- universe -----------------------------------------------------------------------


def gate_flag(gate: bool) -> str:
    return " --gate" if gate else ""


def universe_file(as_of: str, explicit=None, gate=False) -> Path:
    """The month's universe: an explicit file, <asOf>.json, or the month's only file.
    ``as_of`` is a T or, to take the month's file (N8: collect --month), YYYY-MM: then
    the month's single merge without a -limit<N> suffix is preferred over smoke builds
    (L4), else its only file. ``gate``: the computability-check universe instead
    (<asOf>-gate.json, else the month's only gate file, again preferring the one
    without -limit<N>); neither lookup ever returns the other kind (H1)."""
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise CliError(f"No universe file {path}")
        return path
    folder = universe.UNIVERSE_DIR
    exact = universe.merged_path(as_of, gate=gate) if len(as_of) > 7 else None
    if exact is not None and exact.exists():
        return exact
    month = sorted(
        path
        for path in folder.glob(f"{as_of[:7]}-*.json")
        if bool(registry.GATE_PART.fullmatch(path.stem)) == bool(gate)
    )
    if len(as_of) == 7:  # L4: --month takes the month's full merge over smoke builds
        full = [path for path in month if not SMOKE.search(path.stem)]
        if len(full) == 1:
            return full[0]
    if len(month) == 1:
        return month[0]
    kind = "computability-check universe" if gate else "universe"
    if not month:
        raise CliError(
            f"No {kind} for {as_of[:7]} in {rel(folder)}; build each market's part "
            f"with 'universe{gate_flag(gate)}' and merge them with "
            f"'universe-merge{gate_flag(gate)}' first"
        )
    names = ", ".join(p.name for p in month)
    raise CliError(f"Several {kind}s for {as_of[:7]} ({names}); pass --universe")


def load_universe(as_of, explicit=None, gate=False) -> tuple[Path, dict]:
    """The universe file and its content; ``as_of`` (a T or YYYY-MM; None only with
    ``explicit``) must name its month."""
    path = universe_file(as_of, explicit, gate)
    built = json.loads(path.read_text())
    if as_of and str(built.get("asOf") or "")[:7] != as_of[:7]:
        raise CliError(f"{path.name} is the universe of {built.get('asOf')}")
    return path, built


def market_ok(built: dict, market: str) -> bool:
    return ((built.get("markets") or {}).get(market) or {}).get("status") == "ok"


def market_summary(built: dict, market: str) -> dict:
    info = (built.get("markets") or {}).get(market) or {}
    return dict(
        status=info.get("status", built.get("status")),
        error=info.get("error"),
        counts=info.get("counts"),
        builtAt=info.get("builtAt") or built.get("builtAt"),
        # The capture the registry checks against T's close and the window (D5').
        capturedAt=registry.capture_times(built, market),
        holdingsAsOf=info.get("holdingsAsOf"),
        rankingBasis=info.get("rankingBasis"),
        issues=[
            f"{i.get('issue')}: {str(i.get('detail'))[:100]}"
            for i in info.get("issues") or []
        ],
    )


def cmd_universe(args) -> tuple[dict, bool]:
    """D5': build each requested market apart and save it as its part
    (data/ratings/universe/<T>/<market>.json); universe.save re-merges the month's
    parts into data/ratings/universe/<asOf>.json, as universe-merge does. ``--gate``
    saves the computability-check universe apart (<T>-gate/, <asOf>-gate.json; H1).
    A part saved whose month could not be merged is reported as exactly that."""
    markets = tuple(m for m in common.MARKETS if m in args.markets)
    targets = {
        m: universe.part_path(m, args.as_of, args.limit, gate=args.gate)
        for m in markets
    }
    existing = [rel(path) for path in targets.values() if path.exists()]
    if existing and not args.overwrite:
        raise CliError(f"{existing} exist; pass --overwrite to build them again")
    online = not args.offline
    if online:
        credentials(markets, args.dart_env)
    since, started = now(), time.monotonic()
    summary = dict(
        command="universe",
        asOf=args.as_of,
        gate=args.gate,
        limit=args.limit,
        online=online,
        markets={},
        parts={},
        file=None,
    )
    sources, ok = [], True
    for market in markets:  # apart: one market's failure never blocks the other
        built = universe.build(
            args.as_of, online=online, markets=(market,), limit=args.limit
        )
        sources += built.get("sources") or []
        summary["markets"][market] = market_summary(built, market)
        if built.get("status") != "ok":  # a failed build is never saved
            ok = False
            continue
        try:
            month = universe.save(built, overwrite=args.overwrite, gate=args.gate)
        except universe.MonthNotMerged as exc:  # the part is written: say so
            saved = ", ".join(rel(p) for p in exc.parts.values())
            raise CliError(
                f"{market} part saved ({saved}), month not merged: {exc.error}; fix "
                f"that and run 'universe-merge{gate_flag(args.gate)}' (the part "
                "needs no rebuild)"
            ) from None
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            raise CliError(f"{market} part not saved: {exc}") from None
        summary["parts"][market] = rel(targets[market])
        summary["file"] = rel(month)
    summary.update(
        status="ok" if ok else "error",
        elapsedSeconds=round(time.monotonic() - started, 1),
        downloads=downloads(sources, since),
    )
    return summary, ok


def cmd_universe_merge(args) -> tuple[dict, bool]:
    """D5': (re)write the month's universe from its market parts, each keeping its own
    build and capture times (registry.merge_universe via universe.merge)."""
    pinned = {m: d for m, d in (("US", args.as_of_us), ("KR", args.as_of_kr)) if d}
    if not (args.as_of or pinned):
        raise CliError("give --as-of, or --as-of-us / --as-of-kr")
    if pinned and args.as_of:
        pinned = {m: pinned.get(m, args.as_of) for m in common.MARKETS}
    try:
        if args.only and (args.as_of or not pinned):
            raise ValueError("--only merges exactly --as-of-us/--as-of-kr")
        path = universe.merge(
            pinned or args.as_of,
            args.overwrite,
            args.limit,
            gate=args.gate,
            only=args.only,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise CliError(f"cannot merge the universe parts: {exc}") from None
    merged = json.loads(path.read_text())
    keys = ("asOf", "part", "builtAt", "capturedAt", "holdingsAsOf", "rankingBasis")
    return (
        dict(
            command="universe-merge",
            gate=args.gate,
            asOf=merged["asOf"],
            asOfByMarket=merged.get("asOfByMarket"),
            file=rel(path),
            mergedAt=merged.get("mergedAt"),
            sha256=digest(canonical(merged)),
            markets={
                market: {key: info.get(key) for key in (*keys, "counts")}
                for market, info in merged["markets"].items()
            },
            # Checks a registration repeats with its session calendar (window) and
            # clock; shown here so a bad capture is caught before collecting.
            checks=registry.universe_issues(merged, merged["asOfByMarket"]),
        ),
        True,
    )


# --- collect ------------------------------------------------------------------------


def symbols(member: dict) -> list:
    """Price symbols a member needs: its own and, in Korea, every listed class."""
    out = [member.get("priceSymbol")]
    if member.get("market") == "KR":
        out += [c.get("priceSymbol") for c in member.get("shareClasses") or []]
    return [s for s in dict.fromkeys(out) if s]


def identity(member: dict) -> dict:
    """What a checkpoint was collected for; a rebuilt universe that differs voids it."""
    return dict(
        id=member.get("id"),
        cik=member.get("cik"),
        corpCode=member.get("corpCode"),
        fiscalYearEnd=member.get("fiscalYearEnd"),
        symbols=symbols(member),
    )


def work_dir(as_of: str, gate=False) -> Path:
    """data/ratings/work/<asOf>/ (<asOf>-gate/ for the computability-check universe)."""
    return WORK / (as_of + (universe.GATE_SUFFIX if gate else ""))


def work_file(as_of: str, market: str, gate=False) -> Path:
    return work_dir(as_of, gate) / f"{market}.jsonl"


def parse_checkpoints(blob: bytes) -> tuple[dict, int]:
    """Latest record per member id and the number of unreadable (torn) lines."""
    records, bad = {}, 0
    for line in blob.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            records[record["id"]] = record
        except (ValueError, KeyError, TypeError):
            bad += 1
    return records, bad


def read_checkpoints(path: Path) -> tuple[dict, int]:
    return parse_checkpoints(path.read_bytes()) if path.exists() else ({}, 0)


def usable(record, member: dict, as_of: str) -> bool:
    return (
        isinstance(record, dict)
        and record.get("version") == CHECKPOINT
        and record.get("asOf") == as_of
        and record.get("identity") == identity(member)
    )


def staleness(record: dict, member: dict, as_of: str, code: str, captured=None) -> list:
    """Why a usable checkpoint cannot back a registration or a coverage gate (D9, D11'):
    collected offline, collected before T's close, under another protocol hash or code
    digest (``code``: registry.code_digest() now) or, in Korea, with its own series
    retrieved before the universe captured the listed shares (``captured``:
    rating.capture_dates of the universe; capture_after_retrieval, L1: its market cap
    is withheld until it is collected again). Stale checkpoints are collected again;
    the registry refuses rows whose collection.stale is not empty."""
    problems = []
    if record.get("online") is not True:
        problems.append("offline")
    collected = registry.moment(record.get("collectedAt"))
    if collected is None or collected <= registry.market_close(member["market"], as_of):
        problems.append("collected_before_close")
    if record.get("protocolHash") != rating.PROTOCOL_HASH:
        problems.append("protocol_changed")
    if record.get("codeDigest") != code:
        problems.append("code_changed")
    if captured_after(record, member, captured or {}):
        problems.append(rating.CAPTURE_AFTER_RETRIEVAL)
    return problems


def close_on_as_of(record: dict, member: dict, as_of: str) -> bool:
    """The member's own series has a row for T (D9': else no price-based signal)."""
    own = (record.get("prices") or {}).get(member.get("priceSymbol")) or {}
    rows = (own.get("rows") or []) if own.get("status") == "ok" else []
    return any(row[0] == as_of for row in rows)


def append_checkpoint(path: Path, record: dict) -> None:
    try:
        text = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:  # keep the attempt even if a value is bad
        keep = {k: record.get(k) for k in ("version", "id", "market", "asOf")}
        keep.update(
            identity=record.get("identity"),
            collectedAt=record.get("collectedAt"),
            status="error",
            errors=[f"checkpoint not serialisable: {exc}"],
        )
        text = json.dumps(keep, ensure_ascii=False, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell():
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":  # a torn line from an interrupted run
                handle.write(b"\n")
        handle.write(text.encode("utf-8") + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def collect_member(member: dict, as_of: str, online: bool, code: str) -> dict:
    """Fundamentals and price series of one member; every failure stays in the record.

    Series run through the retrieval date (D7: Yahoo closes are split-adjusted to it).
    The record carries the protocol hash and the code digest it was collected under.
    A failed series of the member's own symbol (Korea: the common) makes the record an
    error (collected again); a Korean preferred class whose series is not ok (HTTP
    404 on every host, no sessions, a rejected original) does not (L5): the rating
    prices that class at the common close (class_price_proxy), and ``classFailures``
    keeps the class's failure. D17: any symbol whose download failed transiently
    (prices.transient_failure) or whose series traded on T without a published close
    (prices.unpublished) makes the record an error, collected again: a later download
    may fix it, so it is never a halt or a proxy. A KR member was ranked at its close on
    T, so a KR series without that close is an error too, never a halt.
    """
    started = time.monotonic()
    record = dict(
        version=CHECKPOINT,
        id=member.get("id"),
        market=member.get("market"),
        asOf=as_of,
        rank=member.get("rank"),
        identity=identity(member),
        online=online,
        protocolHash=rating.PROTOCOL_HASH,
        codeDigest=code,
        collectedAt=now(),
        pricesThrough=None,
        status="error",
        errors=[],
        classFailures={},
        fundamentals=None,
        prices={},
        elapsedSeconds=None,
    )
    errors = record["errors"]
    try:
        through = max(today(member["market"]), as_of)
        record["pricesThrough"] = through
        facts = fundamentals.collect(member, as_of, online=online)
        record["fundamentals"] = facts
        if facts.get("status") == "error":
            errors.append(f"fundamentals: {facts.get('error')}")
        for symbol in symbols(member):
            series = prices.series(
                symbol, through, online=online, start=window_start(as_of)
            )
            record["prices"][symbol] = series
            if series.get("status") == "ok":
                if prices.unpublished(series, as_of):  # D17: collect again
                    errors.append(
                        f"prices {symbol}: {as_of} traded without a published close"
                    )
                continue
            if symbol == member.get("priceSymbol") or prices.transient_failure(series):
                errors.append(f"prices {symbol}: {series.get('error')}")  # again
            else:  # L5: a preferred class is priced at the common close
                record["classFailures"][symbol] = series.get("error")
        own = record["prices"].get(member.get("priceSymbol")) or {}
        if (
            member.get("market") == "KR"
            and own.get("status") == "ok"
            and not prices.unpublished(own, as_of)
            and as_of not in {row[0] for row in own.get("rows") or []}
        ):  # ranked at that very close: its absence is the source's (D17), not a halt
            errors.append(
                f"prices {member.get('priceSymbol')}: no close on {as_of}, at which "
                "the member was ranked"
            )
    except Exception as exc:  # company boundary: the modules should not raise
        errors.append(f"unexpected {type(exc).__name__}: {exc}")
    record["status"] = "error" if errors else "ok"
    record["elapsedSeconds"] = round(time.monotonic() - started, 3)
    return record


def eligible_members(built: dict, market: str) -> list:
    """Eligible members to collect; those the universe could not profile are rated
    insufficient without collection (D6)."""
    members = [
        m
        for m in built.get("members") or []
        if m.get("market") == market
        and m.get("status") == "eligible"
        and not registry.fetch_error(m)
    ]
    return sorted(members, key=lambda m: (m.get("rank") or math.inf, str(m.get("id"))))


def collect_summary(file, chosen, eligible, attempted, skipped, as_of) -> dict:
    records, bad = read_checkpoints(file)
    state = Counter(
        (
            records[m["id"]].get("status", "error")
            if usable(records.get(m["id"]), m, as_of)
            else "missing"
        )
        for m in chosen
    )
    facts = [r.get("fundamentals") or {} for r in attempted]
    return dict(
        eligible=len(eligible),
        selected=len(chosen),
        attempted=len(attempted),
        skipped=dict(skipped),
        state=dict(sorted(state.items())),
        errors=dict(
            Counter(reason(e) for r in attempted for e in r["errors"]).most_common(12)
        ),
        # L5: preferred classes left to the common close (not errors), by reason.
        classFailures=dict(
            Counter(
                reason(e)
                for r in attempted
                for e in (r.get("classFailures") or {}).values()
            ).most_common(12)
        ),
        fundamentals=dict(Counter(f.get("status") for f in facts)),
        methods=dict(Counter(f.get("method") for f in facts if f.get("method"))),
        missingFields=dict(Counter(k for f in facts for k in f.get("missing") or [])),
        elapsedSeconds=timing([r["elapsedSeconds"] for r in attempted]),
        checkpoint=rel(file),
        unreadableLines=bad,
    )


def universe_days(built: dict) -> dict:
    """{market: T} of the universe's markets: asOfByMarket, else each market's asOf,
    else the universe's asOf (a single-T file)."""
    by_market, markets = built.get("asOfByMarket") or {}, built.get("markets") or {}
    return {
        market: str(
            by_market.get(market) or markets[market].get("asOf") or built.get("asOf")
        )
        for market in common.MARKETS
        if isinstance(markets.get(market), dict)
    }


def collect_days(args, path: Path, built: dict, markets: list) -> dict:
    """N8: each market is collected at its own T from the universe (asOfByMarket);
    --as-of, kept for months whose markets share one T, must be the T of every market
    collected, else the run is refused (December: KR's T precedes the US's)."""
    every = universe_days(built)
    days = {m: d for m, d in every.items() if m in markets}
    wrong = {m: d for m, d in days.items() if args.as_of and d != args.as_of}
    if wrong:
        alone = " or ".join(f"--as-of {d} --markets {m}" for m, d in wrong.items())
        # L4: with --universe the file is already chosen: only --as-of is in the way.
        instead = (
            f"leave out --as-of (--universe {args.universe} alone collects every "
            "market at its T)"
            if args.universe
            else f"give --month {args.as_of[:7]} instead of --as-of to collect every "
            "market at its T"
        )
        raise CliError(
            f"--as-of {args.as_of} is not the T of "
            f"{', '.join(f'{m} ({d})' for m, d in wrong.items())} in {rel(path)} "
            f"(asOfByMarket {every}): each market is collected at its own T; "
            f"{instead}, or collect one market at a time ({alone})"
        )
    return days


def captured_after(record: dict, member: dict, captured: dict) -> bool:
    """N6: the member's own series was retrieved (exchange-local date) before the
    universe captured its listed shares (rating.capture_dates): its market cap is
    withheld (capture_after_retrieval) until the member is collected again."""
    day = captured.get(member.get("market"))
    own = (record.get("prices") or {}).get(member.get("priceSymbol")) or {}
    on = retrieved_on(own, member["market"]) if own.get("status") == "ok" else None
    return day is not None and on is not None and on < day


def cmd_collect(args) -> tuple[dict, bool]:
    """Collect every eligible member of the selected markets, each market at its own T
    (N8: asOfByMarket of the month's universe, found by --as-of, --month or
    --universe)."""
    online = not args.offline
    if not (args.as_of or args.month or args.universe):
        raise CliError("give --month YYYY-MM (or --as-of T, or --universe FILE)")
    if args.as_of and args.month and args.as_of[:7] != args.month:
        raise CliError(f"--as-of {args.as_of} is not in --month {args.month}")
    path, built = load_universe(args.as_of or args.month, args.universe, args.gate)
    markets = [m for m in common.MARKETS if m in args.markets]
    days = collect_days(args, path, built, markets)
    if online:
        credentials(markets, args.dart_env)
    since = now()
    summary = dict(
        command="collect",
        asOf=args.as_of,
        asOfByMarket=days,
        gate=args.gate,
        universe=rel(path),
        universeLimit=built.get("limit"),
        limit=args.limit,
        online=online,
        refresh=args.refresh,
        markets={},
    )
    manifests, code = [], registry.code_digest()
    captured = rating.capture_dates(built)  # L4, N6: when the KR shares were captured
    for market in markets:
        if not market_ok(built, market) or market not in days:
            summary["markets"][market] = dict(status="skipped", reason="no universe")
            continue
        as_of = days[market]
        eligible = eligible_members(built, market)
        chosen = eligible[: args.limit] if args.limit else eligible
        file = work_file(as_of, market, args.gate)
        done, _ = read_checkpoints(file)
        attempted, skipped, recollected = [], Counter(), Counter()
        for n, member in enumerate(chosen, 1):
            previous = done.get(member.get("id"))
            if usable(previous, member, as_of) and not args.refresh:
                ok, why = previous.get("status") == "ok", None
                if online and ok:
                    stale = staleness(previous, member, as_of, code, captured)
                    if not close_on_as_of(previous, member, as_of):
                        stale.append("no_close_on_as_of")
                    if stale == [rating.CAPTURE_AFTER_RETRIEVAL]:
                        why = rating.CAPTURE_AFTER_RETRIEVAL  # N6 alone
                    elif stale:
                        why = "stale"  # D9, D11': offline, early, other code, no T
                if ok and why is None:
                    skipped["collected"] += 1
                    continue
                if not ok and args.skip_failed:
                    skipped["failed"] += 1
                    continue
                if why:
                    recollected[why] += 1
            record = collect_member(member, as_of, online, code)
            append_checkpoint(file, record)
            attempted.append(record)
            manifests += (record.get("fundamentals") or {}).get("sources") or []
            manifests += [s.get("source") for s in record["prices"].values()]
            first = record["errors"][0][:100] if record["errors"] else ""
            print(
                f"{market} {n}/{len(chosen)} {member.get('id')} {member.get('ticker')} "
                f"{record['status']} {record['elapsedSeconds']}s {first}",
                file=sys.stderr,
                flush=True,
            )
        summary["markets"][market] = collect_summary(
            file, chosen, eligible, attempted, skipped, as_of
        )
        summary["markets"][market].update(
            asOf=as_of,
            recollected=dict(recollected),
            fetchErrors=sum(
                registry.fetch_error(m)
                for m in built.get("members") or []
                if m.get("market") == market and m.get("status") == "eligible"
            ),
        )
    summary["downloads"] = downloads(manifests, since)
    return summary, True


# --- score and coverage -------------------------------------------------------------


def retrieved_on(series: dict, market: str) -> str | None:
    """Exchange-local date a series was retrieved: Yahoo restates closes for every
    split up to that date."""
    stamp = registry.moment((series.get("source") or {}).get("retrievedAt"))
    if stamp is None:
        return None
    where = ZoneInfo(series["timezone"]) if series.get("timezone") else zone(market)
    return stamp.astimezone(where).date().isoformat()


COLLECTION_STATS = (
    "eligible",
    "fetchErrors",
    "collected",
    "notCollected",
    "stale",
    "errors",
    "noCloseOnAsOf",
    "failures",
    "excluded",
    "withPrices",
    "closeOnAsOf",
)


def assemble(built: dict, days: dict, gate=False) -> tuple[list, dict, dict]:
    """signals() rows for every member of the markets in ``days`` from the checkpoints
    (``gate``: those of the computability-check universe).

    An eligible member without a usable checkpoint keeps an empty row marked
    not_collected (or stale_checkpoint), and one the universe could not profile an empty
    row marked universe_fetch_error (and not_collected; L6: never the halt or price
    codes of an empty row), so that both stay in the denominator. Collected rows get
    the split events, retrieval date and window of every series (D7') and the KR
    capture date of the listed shares (L4). Each collected row records why its
    checkpoint could not back a registration (collection.stale) and whether its own
    series has a close on T; each market records the SHA-256 and byte length of the
    checkpoint file the rows were read from (D8', L1).
    """
    rows, inputs, collection = [], dict(fundamentals=[], prices=[]), {}
    code = registry.code_digest()
    captured = rating.capture_dates(built)  # L4: {"KR": date of the share capture}
    for market, as_of in days.items():
        file = work_file(as_of, market, gate)
        blob = file.read_bytes() if file.exists() else None
        records, bad = parse_checkpoints(blob or b"")
        stats = Counter()
        for member in built.get("members") or []:
            if member.get("market") != market:
                continue
            if member.get("status") != "eligible":
                rows.append(rating.signals(member, None, {}, as_of))
                stats["excluded"] += 1
                continue
            stats["eligible"] += 1
            record = records.get(member.get("id"))
            if registry.fetch_error(member):
                row = rating.signals(member, None, {}, as_of)
                found = usable(record, member, as_of)
                row.update(
                    inputs={},
                    issues=[registry.FETCH_ERROR]
                    + ([] if found else ["not_collected"]),
                )
                rows.append(row)
                stats["fetchErrors"] += 1
                continue
            if not usable(record, member, as_of):
                row = rating.signals(member, None, {}, as_of)
                row.update(
                    inputs={},
                    issues=["stale_checkpoint" if record else "not_collected"],
                )
                rows.append(row)
                stats["notCollected"] += 1
                continue
            ok = {
                symbol: s
                for symbol, s in (record.get("prices") or {}).items()
                if isinstance(s, dict) and s.get("status") == "ok"
            }
            own = ok.get(member.get("priceSymbol")) or {}
            row = rating.signals(
                member,
                record.get("fundamentals"),
                {symbol: s["rows"] for symbol, s in ok.items()},
                as_of,
                splits_by_symbol={s: v.get("splits") or [] for s, v in ok.items()},
                retrieved_on=retrieved_on(own, market),
                windows_by_symbol={s: v.get("window") for s, v in ok.items()},
                capture_dates_by_market=captured,
            )
            stale = staleness(record, member, as_of, code, captured)
            close = close_on_as_of(record, member, as_of)
            row["collection"] = dict(
                status=record.get("status"),
                collectedAt=record.get("collectedAt"),
                online=record.get("online"),
                protocolHash=record.get("protocolHash"),
                codeDigest=record.get("codeDigest"),
                errors=record.get("errors") or [],
                # L5: preferred classes priced at the common close, and why.
                classFailures=record.get("classFailures") or {},
                stale=stale,
                closeOnAsOf=close,
            )
            rows.append(row)
            stats["collected"] += 1
            stats["errors"] += record.get("status") != "ok"
            stats["stale"] += bool(stale)
            stats["noCloseOnAsOf"] += not close
            stats["failures"] += record.get("status") != "ok" or not close
            facts = record.get("fundamentals") or {}
            inputs["fundamentals"] += [
                m for m in facts.get("sources") or [] if isinstance(m, dict)
            ]
            inputs["prices"] += [s["source"] for s in ok.values() if s.get("source")]
            stats["withPrices"] += bool(own.get("rows"))
            stats["closeOnAsOf"] += close
        collection[market] = dict(
            asOf=as_of,
            workFile=rel(file),
            workFileSha256=digest(blob) if blob is not None else None,
            workFileBytes=len(blob) if blob is not None else None,
            records=len(records),
            unreadableLines=bad,
            **{key: stats[key] for key in COLLECTION_STATS},
        )
    return rows, inputs, collection


def checkpoint_files(collection: dict) -> dict:
    """D8', L1: each market's checkpoint file, its SHA-256 and byte length (the file is
    append-only: the first ``bytes`` keep that hash), for a registration or a gate."""
    return {
        market: dict(
            file=c["workFile"],
            sha256=c["workFileSha256"],
            bytes=c.get("workFileBytes"),
            records=c["records"],
            unreadableLines=c["unreadableLines"],
        )
        for market, c in collection.items()
        if c.get("workFileSha256")
    }


def market_issues(rows: list, market: str, limit: int = 15) -> dict:
    issues = Counter(
        issue
        for r in rows
        if r.get("market") == market and r.get("status") == "eligible"
        for issue in r.get("issues") or []
    )
    return dict(issues.most_common(limit))


def gate_brief(event) -> dict | None:
    if not event:
        return None
    keys = ("eventId", "asOf", "rate", "threshold", "verdict", "recordedAt", "hash")
    return {key: event.get(key) for key in keys}


def benchmark_calendars(days: dict, online: bool) -> dict:
    """Each market's session-calendar series (its benchmark) through today, for the
    registry's session rules (D3)."""
    calendar = registry.setting("sessionCalendar")
    return {
        market: prices.series(calendar[market], today(market), online=online)
        for market in days
    }


def cmd_score(args) -> tuple[dict, bool]:
    days = {m: d for m, d in (("US", args.as_of_us), ("KR", args.as_of_kr)) if d}
    if not days:
        raise CliError("give --as-of-us and/or --as-of-kr")
    if len({d[:7] for d in days.values()}) != 1:
        raise CliError(f"as-of dates must share one month: {days}")
    if args.offline and not args.dry_run:
        raise CliError("a registration checks T against the benchmark online")
    month = next(iter(days.values()))[:7]
    gates = {m: registry.gate(m) for m in common.MARKETS}
    left_out = {}
    if not args.dry_run:
        if gates["US"] is not None and gates["US"].get("verdict") != "pass":
            raise CliError(
                "the US coverage gate failed: ratings are not published (§7)"
            )
        for market in [m for m in days if m != "US"]:
            if gates[market] is not None and gates[market].get("verdict") != "pass":
                left_out[market] = "failed coverage gate (§7): left out of v1"
                del days[market]
        if not days:
            raise CliError(f"no market left to register: {left_out}")
    path, built = load_universe(max(days.values()), args.universe)
    failed = [m for m in days if not market_ok(built, m)]
    if failed:
        raise CliError(f"{path.name} has no successful build for {failed}")
    rows, inputs, collection = assemble(built, days)
    try:
        rated = rating.score(rows, registry.previous_labels(month))
    except ValueError as exc:
        raise CliError(f"cannot score {month}: {exc}") from None
    partial = built.get("limit") is not None or any(
        c["notCollected"] for c in collection.values()
    )
    if not args.dry_run:
        if partial:
            raise CliError(
                "a registration needs the full universe with every eligible member "
                "collected; collect the rest or use --dry-run"
            )
        stale = {m: c["stale"] for m, c in collection.items() if c["stale"]}
        if stale:  # D9': --allow-errors never accepts a stale checkpoint
            raise CliError(
                f"checkpoints collected offline or before T's close, retrieved (KR) "
                f"before the universe's share capture, or under another protocol or "
                f"code {stale}: rerun collect online (it re-collects them) or use "
                "--dry-run"
            )
        failures = {m: c["failures"] for m, c in collection.items() if c["failures"]}
        if failures and not args.allow_errors:
            raise CliError(
                f"collection errors or no close on asOf {failures}: rerun collect, or "
                "pass --allow-errors to register them as recorded failures (a member "
                "without a close on T gets no price-based signal)"
            )
    calendars = benchmark_calendars(days, online=not args.offline)
    run = None
    if args.dry_run:
        run = dict(
            tag="smoke" if partial else None,
            smoke=partial,
            note=(
                "smoke test of the pipeline on a partial universe or collection; "
                "not a rating, never evaluated or reported"
                if partial
                else "dry run; never evaluated or reported"
            ),
            universeFile=rel(path),
            universeLimit=built.get("limit"),
            collection=collection,
            gates={m: gate_brief(g) for m, g in gates.items()},
            createdBy="scripts/ratings.py score",
        )
    try:
        out = registry.register(
            days,
            built,
            rated,
            inputs,
            dry_run=args.dry_run,
            run=run,
            calendars=calendars,
            checkpoints=checkpoint_files(collection),
        )
    except (ValueError, OSError) as exc:
        raise CliError(f"registration refused: {exc}") from None
    content = json.loads(out.read_text())
    summary = dict(
        command="score",
        kind=content["kind"],
        smoke=partial,
        file=rel(out),
        month=month,
        asOf=days,
        leftOut=left_out,
        protocolHash=content["protocolHash"],
        labels=content["labels"],
        collection=collection,
        checks=content.get("issues", []),
        calendar={
            m: dict(
                symbol=c.get("symbol"),
                available=c.get("available"),
                sessionsAfterAsOf=c.get("sessionsAfterAsOf"),
            )
            for m, c in (content.get("calendar") or {}).items()
        },
        issues={m: market_issues(rated, m) for m in days},
    )
    scored = [r for r in rated if r.get("label")]
    if len(scored) <= 40:
        summary["scored"] = [
            dict(
                id=r["id"],
                name=r.get("name"),
                sector=r.get("sector"),
                label=r["label"],
                percentile=round(r["percentile"], 4),
                signals={k: v and round(v, 4) for k, v in r["signals"].items()},
            )
            for r in sorted(scored, key=lambda r: (r["market"], -r["percentile"]))
        ]
    return summary, True


def try_gate(market, as_of, entry, built, path, stats, online) -> dict:
    """D10': record the market's gate once, from the first run that may: on or after
    the check date, at the pinned asOf, online and with a complete collection; the
    registry repeats the universe checks (parts built online), hashes again the part
    files the merge recorded, checks that the merged file ``path`` still holds
    ``built`` (N7) and computes the verdict, and the event keeps the checkpoint file's
    SHA-256 (L1). Other runs report."""
    existing = registry.gate(market)
    out = dict(recorded=False, event=gate_brief(existing))
    if existing is not None:
        return dict(out, reason="the market's gate was already recorded; it is final")
    if as_of != CHECK["asOf"]:
        return dict(out, reason=f"rehearsal: the gate is computed at {CHECK['asOf']}")
    if today(market) < CHECK["date"]:
        return dict(out, reason=f"rehearsal before the {CHECK['date']} check date")
    if entry["verdict"] not in ("pass", "fail"):
        return dict(out, reason="incomplete collection: nothing recorded, retry")
    if not online:
        return dict(out, reason="offline: a gate is recorded online")
    calendars = benchmark_calendars({market: as_of}, online=True)
    try:
        event, created = registry.record_gate(
            market,
            built,
            computable=entry["withTwoSignals"],
            collection=stats,
            checkpoints=checkpoint_files({market: stats}),
            calendars=calendars,
            universe_file=path,  # N7: re-hashed with its parts when recorded
            universeFile=rel(path),
        )
    except ValueError as exc:
        return dict(out, refused=True, reason=str(exc))
    if not created:
        return dict(out, reason="the market's gate was already recorded; it is final")
    return dict(recorded=True, event=gate_brief(event))


def cmd_coverage(args) -> tuple[dict, bool]:
    """§7 on the computability-check universe only (H1: --gate is required)."""
    if not args.gate:
        raise CliError(
            "coverage runs on the computability-check universe only: build it with "
            "'universe --gate', collect it with 'collect --gate' and pass --gate"
        )
    as_of, online = args.as_of, not args.offline
    path, built = load_universe(as_of, args.universe, gate=True)
    days = {
        m: as_of for m in common.MARKETS if m in args.markets and market_ok(built, m)
    }
    rows, _, collection = assemble(built, days, gate=True)
    labelled = Counter(r["market"] for r in rating.score(rows) if r.get("label"))
    need = rating.PROTOCOL["minSignals"]
    result = dict(
        command="coverage",
        asOf=as_of,
        universe=rel(path),
        universeLimit=built.get("limit"),
        gate=GATE,
        checkDate=CHECK["date"],
        checkAsOf=CHECK["asOf"],
        rule=f"members with >= {need} signals / every non-financial member "
        "(docs/ratings-v1.md §7); members not collected or left unprofiled by the "
        "universe count as not computable; a verdict needs the full universe "
        "collected online after the close under this protocol and code (KR: not "
        "before the universe's share capture), without collection errors",
        markets={},
    )
    refused = False
    for market in days:
        mine = [r for r in rows if r["market"] == market]
        base = [r for r in mine if not registry.financial(r)]
        collected = [r for r in base if "collection" in r]
        two = [
            r
            for r in collected
            if sum(v is not None for v in r["signals"].values()) >= need
        ]
        stats = collection[market]
        rate = len(two) / len(base) if base else None
        complete = (
            not stats["notCollected"]
            and not stats["stale"]
            and not stats["errors"]
            and built.get("limit") is None
        )
        verdict = "incomplete"
        if complete and rate is not None:
            verdict = "pass" if rate >= GATE[market] else "fail"
        entry = dict(
            nonFinancial=len(base),
            eligible=stats["eligible"],
            excludedNonFinancial=len(base) - stats["eligible"],
            fetchErrors=stats["fetchErrors"],
            collected=len(collected),
            notCollected=stats["notCollected"],
            stale=stats["stale"],
            collectionErrors=stats["errors"],
            noCloseOnAsOf=stats["noCloseOnAsOf"],
            withTwoSignals=len(two),
            labelled=labelled[market],
            rate=rate,
            rateCollected=len(two) / len(collected) if collected else None,
            threshold=GATE[market],
            verdict=verdict,
            signalsAvailable={
                s: sum(r["signals"][s] is not None for r in collected)
                for s in rating.SIGNALS
            },
            issues=market_issues(base, market),
        )
        entry["gate"] = try_gate(market, as_of, entry, built, path, stats, online)
        refused |= bool(entry["gate"].get("refused"))
        result["markets"][market] = entry
    out = work_dir(as_of, gate=True) / "coverage.json"
    common.write_json(out, result)
    result["file"] = rel(out)
    return result, not refused


# --- evaluation ---------------------------------------------------------------------


def brief(series: dict) -> dict:
    rows = series.get("rows") or []
    return dict(
        status=series.get("status"),
        error=series.get("error"),
        sessions=len(rows),
        first=rows[0][0] if rows else None,
        last=rows[-1][0] if rows else None,
        source=series.get("source"),
        notes=series.get("notes") or [],
    )


def series_file(symbol: str) -> Path:
    name = re.sub(r"[^A-Za-z0-9.-]", lambda m: f"_{ord(m.group()):02X}", symbol)
    return SERIES / f"{common.safe_key(f'yahoo-{name}')}.json"


def kept_originals(symbol: str) -> list:
    """The originals kept for ``symbol`` ({source, window, first, last, sessions});
    a file of the earlier layout (one source and saved rows) gives its source only."""
    path = series_file(symbol)
    if not path.exists():
        return []
    saved = json.loads(path.read_text())
    if saved.get("symbol") != symbol:
        raise ValueError(f"{path.name} keeps {saved.get('symbol')!r}")
    if "originals" in saved:
        return [o for o in saved["originals"] if isinstance(o, dict)]
    return [dict(source=saved["source"], window=saved.get("window"))]


def keep_series(symbol: str, result: dict) -> str | None:
    """D12': add a downloaded original to the symbol's kept series (official runs only).

    Kept originals are merged, never dropped, so a later download that covers less
    (a reused ticker, a reset history) never shrinks what is kept. Returns a note when
    the result cannot be kept.
    """
    try:
        originals = kept_originals(symbol)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return f"{symbol}: kept series unreadable ({exc}); left unchanged"
    source, window = result.get("source") or {}, result.get("window") or {}
    rows = result.get("rows") or []
    if not (
        rows and source.get("sha256") and window.get("from") and window.get("through")
    ):
        return f"{symbol}: no original and window to keep"
    if source["sha256"] not in {
        (o.get("source") or {}).get("sha256") for o in originals
    }:
        originals.append(
            dict(
                source=source,
                window=window,
                first=rows[0][0],
                last=rows[-1][0],
                sessions=len(rows),
            )
        )
    originals.sort(key=lambda o: str((o.get("source") or {}).get("retrievedAt")))
    common.write_json(
        series_file(symbol), dict(symbol=symbol, updatedAt=now(), originals=originals)
    )
    return None


def stored_series(symbol: str, through: str, start: str) -> dict | None:
    """The best kept original of ``symbol``, re-parsed (rows and splits) by
    prices._parse after its SHA-256 is verified; saved rows are never trusted (D12').

    Preferred: an original reaching back to ``start``, then the latest last session,
    then the latest retrieval.
    """
    try:
        originals = kept_originals(symbol)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    found = []
    for original in originals:
        source, window = original.get("source") or {}, original.get("window") or {}
        try:
            blob = common.load(source)  # the exact original, hash verified
            parsed = prices._parse(
                blob, symbol, window["from"], window["through"], source["retrievedAt"]
            )
        except (OSError, *prices.PARSE_ERRORS):
            continue
        rows = rating.rows_through(parsed["rows"], through)
        if rows:
            covers = start is None or rows[0][0] <= start
            rank = (covers, rows[-1][0], str(source.get("retrievedAt")))
            found.append((rank, dict(original, rows=rows, splits=parsed["splits"])))
    return max(found, key=lambda item: item[0])[1] if found else None


def fetch_series(symbols_, through: str, online: bool, start: str) -> dict:
    """Rows by symbol, with each symbol's report, the symbols served from storage, the
    SHA-256 of the original behind each symbol's rows and the fresh downloads.

    A failed download falls back to the kept original that serves the evaluation best
    (stored_series), so a delisted or renamed member keeps the closes it had; a
    download that failed transiently (prices.transient_failure) or whose latest session
    traded without a published close (D17) does not: the symbol has no series in this
    run (an error, never a stale close frozen as an exit) and a later run fetches it.
    """
    out = dict(series={}, fetched={}, stored=set(), sources={}, downloaded={})
    for symbol in symbols_:
        result = prices.series(symbol, through, online=online, start=start)
        out["fetched"][symbol] = brief(result)
        rows = result.get("rows") or []
        pending = [
            day
            for day in result.get("unpublishedSessions") or []
            if not rows or day > rows[-1][0]
        ]
        if result["status"] == "ok" and pending:  # D17: not settled yet
            out["fetched"][symbol]["unpublished"] = max(pending)
            continue
        if result["status"] != "ok" and prices.transient_failure(result):
            continue  # D17: retried by a later run, never served from storage
        if result["status"] == "ok":
            out["series"][symbol] = result["rows"]
            out["sources"][symbol] = (result.get("source") or {}).get("sha256")
            out["downloaded"][symbol] = result
            continue
        saved = stored_series(symbol, through, start)
        if saved:
            out["series"][symbol] = saved["rows"]
            out["stored"].add(symbol)
            out["sources"][symbol] = saved["source"].get("sha256")
            out["fetched"][symbol]["stored"] = dict(
                file=rel(series_file(symbol)),
                window=saved.get("window"),
                source=saved["source"],
                first=saved["rows"][0][0],
                last=saved["rows"][-1][0],
            )
    return out


def same_registrations(found: list, ledgered: list) -> bool:
    def key(items):
        return sorted(
            (r.get("month"), (r.get("ledger") or {}).get("hash")) for r in items
        )

    return key(found) == key(ledgered)


def load_frozen() -> dict:
    """Frozen periods by (market, month) from data/ratings/periods (D12')."""
    found = {}
    for path in sorted(PERIODS.glob("*/*.json")):
        try:
            found[(path.parent.name, path.stem)] = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise CliError(f"{rel(path)} unreadable: {exc}") from None
    return found


AFTER_LOCAL_DATE = "after_local_date"  # N2: held back, not frozen by this run


def freeze_periods(result: dict) -> tuple[list, list]:
    """D12', L3: freeze each period completed since the last official run, market by
    market in order; returns (files written, periods held back).

    A period whose members have errors waits until the evaluation date is more than
    freezeGraceDays after its exit date (evaluate.freeze_state), then is frozen with
    those members unresolved; a waiting period never holds back later periods. A
    period error that is not a member's (a frozen record that does not match) stops
    freezing in that market until the operator resolves it. N2: a market's periods
    are frozen only when the evaluation date is not after that market's local date
    (an official run may be dated by the later market); otherwise they wait for a
    later official run (state AFTER_LOCAL_DATE)."""
    written, held = [], []
    for market in common.MARKETS:
        local = today(market)
        for period in (p for p in result["periods"] if p["market"] == market):
            state, detail = evaluate.freeze_state(period, result["through"])
            if state == "frozen":
                continue
            if state == "freeze" and result["through"] > local:  # N2
                state, detail = AFTER_LOCAL_DATE, (
                    f"evaluation date {result['through']} is after {market}'s local "
                    f"date {local}: frozen by a later official run"
                )
            if state != "freeze":
                if period["status"] == "complete":
                    held.append(
                        dict(
                            market=market,
                            month=period["month"],
                            state=state,
                            reason=detail,
                        )
                    )
                if state in ("wait", AFTER_LOCAL_DATE):
                    continue
                break
            path = PERIODS / market / f"{period['month']}.json"
            record = evaluate.freeze_record(period, result["through"], now())
            try:
                registry.write_once(path, record)
            except FileExistsError:
                raise CliError(f"{rel(path)} exists but was not used") from None
            written.append(rel(path))
    return written, held


def official_blockers(dry, whole, online, markers, downloaded, result) -> list:
    """Why an evaluation is not official (D12'); none means official. An evaluation
    date later than today (in every market) is never official: it would freeze periods
    whose grace has not passed (L3)."""
    blockers = []
    if dry:
        blockers.append("dry runs are never official")
    elif not whole:
        blockers.append("not the whole ledger")
    if not online:
        blockers.append("offline run")
    latest = max(today(market) for market in common.MARKETS)
    if result["through"] > latest:
        blockers.append(f"evaluation date {result['through']} is after {latest}")
    missing = sorted(symbol for symbol in markers if symbol not in downloaded)
    if missing:
        blockers.append(f"benchmark or session-calendar series not fetched: {missing}")
    if any(i.get("issue") == "mixed_protocol_hashes" for i in result["issues"]):
        blockers.append("registrations under different protocol hashes")
    return blockers


def cmd_evaluate(args) -> tuple[dict, bool]:
    through, online = args.through, not args.offline
    try:
        ledgered = registry.registrations()
        found = [registry.read(Path(f)) for f in args.files] if args.files else ledgered
    except (ValueError, OSError) as exc:
        raise CliError(f"registrations do not match the ledger: {exc}") from None
    kinds = sorted({str(r.get("kind")) for r in found})
    if len(kinds) > 1:
        raise CliError(f"--files mixes {kinds}: dry runs are never evaluated with real")
    dry = kinds == ["dry-run"]
    whole = bool(found) and not dry and same_registrations(found, ledgered)
    out = Path(args.out) if args.out else None
    if out is not None and inside(out, EVALUATIONS) and not (whole and online):
        raise CliError(
            f"{rel(EVALUATIONS)} holds official evaluations of the whole ledger only "
            "(online, no dry runs, no subsets); write elsewhere with --out"
        )
    summary = dict(
        command="evaluate",
        through=through,
        online=online,
        registrations=[dict(month=r.get("month"), kind=r.get("kind")) for r in found],
    )
    if not found:
        summary["status"] = "no_registrations"
        return summary, True
    wanted, markers, first = set(), set(), None
    for r in found:
        for market, as_of in (r.get("asOf") or {}).items():
            first = min(first or as_of, as_of)
            markers.add(r["protocol"]["benchmarks"][market])
            markers.add(registry.setting("sessionCalendar", r["protocol"])[market])
        wanted |= {
            row["priceSymbol"]
            for row in r["rows"]
            if row.get("labelReason") != "excluded" and row.get("priceSymbol")
        }
    since = now()
    got = fetch_series(sorted(wanted | markers), through, online, first)
    try:
        result = evaluate.evaluate(
            found,
            got["series"],
            through,
            include_dry_run=dry,
            stored=got["stored"],
            sources=got["sources"],
            frozen=None if dry else load_frozen(),
        )
    except ValueError as exc:
        raise CliError(f"cannot evaluate: {exc}") from None
    blockers = official_blockers(dry, whole, online, markers, got["downloaded"], result)
    official = not blockers
    notes, frozen_now, held = [], [], []
    if official:
        notes = [
            keep_series(s, got["downloaded"][s]) for s in sorted(got["downloaded"])
        ]
        frozen_now, held = freeze_periods(result)
        out = out or EVALUATIONS / f"{through}.json"
    elif out is not None and inside(out, EVALUATIONS):
        raise CliError(f"not official ({'; '.join(blockers)}): nothing written")
    result.update(
        series=got["fetched"],
        online=online,
        official=official,
        officialBlockers=blockers,
        frozenNow=frozen_now,
        frozenHeld=held,
        ledger=registry.ledger_head(),
        files=[rel(f) for f in args.files] if args.files else None,
    )
    if out is not None:
        common.write_json(out, result)
    summary.update(
        status="ok" if not result["errors"] else "errors",
        dryRunIncluded=dry,
        official=official,
        officialBlockers=blockers,
        valuedThrough=result["valuedThrough"],
        ledger=result["ledger"],
        file=rel(out) if out else None,
        errors=result["errors"],
        summary=result["summary"],
        periods=[
            dict(
                market=p["market"],
                month=p["month"],
                status=p["status"],
                entry=p["entry"],
                exit=p["exit"],
                flags=p["flags"],
                frozen=bool(p.get("frozen")),
                errors=p["errors"],
            )
            for p in result["periods"]
        ],
        frozenNow=frozen_now,
        frozenHeld=held,
        keptSeries=dict(
            written=len(notes) - sum(n is not None for n in notes),
            notes=[n for n in notes if n],
        ),
        issues=result["issues"],
        storedSeries=sorted(got["stored"]),
        seriesErrors={s: f["error"] for s, f in got["fetched"].items() if f["error"]},
        downloads=downloads([f["source"] for f in got["fetched"].values()], since),
    )
    return summary, not result["errors"]


def cmd_forward_check(args) -> tuple[dict, bool]:
    through, online = args.through, not args.offline
    path = FORWARD_STUDY
    before = digest(path.read_bytes())
    precheck = evaluate.forward_study_check(path, {}, through)  # hash before downloads
    if precheck["status"] != "ok":
        return dict(precheck, command="forward-check"), False
    try:
        companies = {
            market: list(dict.fromkeys([spec["calendarCompany"], *spec["members"]]))
            for market, spec in json.loads(path.read_bytes())["markets"].items()
        }
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise CliError(f"{rel(path)} unreadable: {type(exc).__name__}: {exc}") from None
    since = now()
    series, fetched = {}, {}
    for market, names in companies.items():
        for company in names:
            candidates = (
                [f"{company}.KS", f"{company}.KQ"] if market == "KR" else [company]
            )
            for symbol in candidates:  # .KQ only when the KOSPI symbol fails
                result = prices.series(symbol, through, online=online)
                fetched[symbol] = brief(result)
                if result["status"] == "ok":
                    series[symbol] = result["rows"]
                    break
    result = evaluate.forward_study_check(path, series, through)
    if digest(path.read_bytes()) != before:
        raise CliError(f"{rel(path)} changed during the check")
    result["series"] = fetched
    out = FORWARD_CHECKS / f"{through}.json"
    common.write_json(out, result)
    summary = dict(
        command="forward-check",
        through=through,
        status=result["status"],
        study=rel(path),
        studySha256=before,
        unchanged=True,
        file=rel(out),
        reference=result.get("reference"),
        matches=result.get("matches"),
        differences=(result.get("differences") or [])[:20],
        results=[
            {
                k: r.get(k)
                for k in (
                    "market",
                    "horizon",
                    "status",
                    "observedSessions",
                    "requiredSessions",
                    "entry",
                    "end",
                    "missing",
                )
                if r.get(k) is not None
            }
            for r in result.get("results") or []
        ],
        seriesErrors={s: f["error"] for s, f in fetched.items() if f["error"]},
        downloads=downloads([f["source"] for f in fetched.values()], since),
    )
    if result["status"] != "ok":
        summary["error"] = result.get("error")
    return summary, result["status"] == "ok" and bool(result.get("matches"))


# --- command line -------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ratings.py", description="ratings-v1 pipeline (docs/ratings-v1.md)"
    )
    sub = p.add_subparsers(dest="command", required=True)

    def markets(command):
        command.add_argument(
            "--markets", nargs="+", choices=common.MARKETS, default=list(common.MARKETS)
        )

    def gate(command, text="the computability-check (coverage gate) universe"):
        command.add_argument("--gate", action="store_true", help=text)

    def source(command, network=True):
        command.add_argument("--universe", help="universe file (default: the month's)")
        if network:
            command.add_argument("--offline", action="store_true")
            command.add_argument(
                "--dart-env", help="env file with DART_API_KEY (or EQUITY_DART_ENV)"
            )

    c = sub.add_parser("universe", help="build and save each market's universe part")
    c.add_argument("--as-of", type=day, required=True)
    c.add_argument("--offline", action="store_true")
    c.add_argument("--dart-env", help="env file with DART_API_KEY (or EQUITY_DART_ENV)")
    c.add_argument(
        "--limit", type=count, help="smoke runs only: profile the N largest per market"
    )
    c.add_argument("--overwrite", action="store_true")
    gate(c, "save the computability-check universe apart (<T>-gate/)")
    markets(c)

    c = sub.add_parser(
        "universe-merge", help="write the month's universe from its market parts"
    )
    c.add_argument(
        "--as-of",
        type=day,
        help="T: each market's part of T, else its only part of the month",
    )
    c.add_argument("--as-of-us", type=day, help="the US part's T (several in a month)")
    c.add_argument("--as-of-kr", type=day, help="the KR part's T (several in a month)")
    c.add_argument("--limit", type=count, help="merge the smoke parts of --limit N")
    c.add_argument(
        "--overwrite", action="store_true", help="replace a month file not merged"
    )
    c.add_argument(
        "--only",
        action="store_true",
        help="exactly the markets of --as-of-us/--as-of-kr (no other part of the month)",
    )
    gate(c, "merge the computability-check universe (<asOf>-gate.json)")

    c = sub.add_parser("collect", help="fundamentals and prices per eligible member")
    c.add_argument(
        "--as-of",
        type=day,
        help="T of every market collected (a month whose markets share T)",
    )
    c.add_argument(
        "--month",
        type=calendar_month,
        help="the month's universe: each market is collected at its own T",
    )
    c.add_argument("--limit", type=count, help="first N eligible members per market")
    c.add_argument(
        "--skip-failed", action="store_true", help="do not retry recorded failures"
    )
    c.add_argument(
        "--refresh", action="store_true", help="re-collect current checkpoints too"
    )
    gate(c)
    source(c)
    markets(c)

    c = sub.add_parser(
        "score", help="signals, scores and the registration (or dry run)"
    )
    c.add_argument("--as-of-us", type=day)
    c.add_argument("--as-of-kr", type=day)
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--allow-errors", action="store_true")
    c.add_argument(
        "--offline", action="store_true", help="dry runs only: stored benchmark series"
    )
    source(c, network=False)

    c = sub.add_parser("evaluate", help="forward evaluation of registrations")
    c.add_argument("--through", type=day, required=True)
    c.add_argument("--offline", action="store_true")
    c.add_argument("--files", nargs="+", help="registration or dry-run files instead")
    c.add_argument("--out", help="output file (default data/ratings/evaluation)")

    c = sub.add_parser("forward-check", help="re-evaluate data/forward-study.json")
    c.add_argument("--through", type=day, required=True)
    c.add_argument("--offline", action="store_true")

    c = sub.add_parser("coverage", help="share of non-financial members with 2 signals")
    c.add_argument("--as-of", type=day, required=True)
    c.add_argument(
        "--offline", action="store_true", help="report only: never record the gate"
    )
    gate(c, "required: coverage runs on the computability-check universe only")
    source(c, network=False)
    markets(c)
    return p


COMMANDS = {
    "universe": cmd_universe,
    "universe-merge": cmd_universe_merge,
    "collect": cmd_collect,
    "score": cmd_score,
    "evaluate": cmd_evaluate,
    "forward-check": cmd_forward_check,
    "coverage": cmd_coverage,
}


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        summary, ok = COMMANDS[args.command](args)
    except CliError as exc:
        print(f"ratings {args.command}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
