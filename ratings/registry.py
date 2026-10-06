"""Immutable monthly ratings-v1 registrations, coverage gates and their hash-chained ledger.

docs/ratings-v1.md §5 and §7. A formal registration is accepted only when

- each market's asOf T is the last session of its month in that market's benchmark
  series, the month has ended in the market's local date, and the registration comes
  within ``registrationWindowSessions`` benchmark sessions after T, for a month later
  than every month already registered (a missed month can never be registered);
- it carries the current time: a file left without its ledger event by an interrupted
  run is completed only within the clock tolerance of its stamp, never backdated;
- the universe is the merge of per-market parts (``merge_universe``), each built online
  (M2: never replayed offline from stored originals) for its market's T and captured
  after T's close inside the registration window (US: SPY holdings as of T; KR:
  members ranked on T's closes, a candidate left unranked only by a halt on T, an
  unknown symbol or no session through T), excludes members only by
  the financial rules, has at most ``universeFetchErrorMaxShare`` profile failures,
  matches the pinned sector references (the KSIC table file too) and rules, has no
  eligible Money member and is not the computability-check universe (parts in
  <T>-gate/);
- no row comes from a stale checkpoint (collection.stale) and the SHA-256 of every
  market's checkpoint file is recorded;
- each market passed its coverage gate, recorded under this protocol for the pinned
  check date before that market's first registration (a failed US gate blocks every
  registration), and no ledger event carries another protocol hash: ratings-v1 is
  frozen, a rule change needs ratings-v2.

Files are created exclusively and never rewritten: an identical re-run returns the stored
file, anything else is refused. Each registration records the SHA-256 of the code that
made it. Dry runs are written apart, never reach the ledger and keep every failed check
in ``issues``. Registrations are read back from the ledger: every event needs its
unaltered file and every file its event.

The coverage gate (``record_gate``) is recorded once per market, on or after the check
date, from the computability-check universe (its parts in <asOf>-gate/) for the pinned
asOf that passes the same universe checks, and only after a complete, current
collection; when it is recorded each part file the merge recorded is hashed again and
must still have the SHA-256 the merge recorded, and the merged file must still hold the
universe being recorded (L3: the merge records no hash of the merged file itself). The
registry computes its verdict. The event keeps what re-verifies it: the SHA-256 (and
byte length) of the checkpoint file the counts came from, the merged file, each universe
part file's SHA-256 and the merge's mergedAt.
"""

from __future__ import annotations

from calendar import monthrange
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from zoneinfo import ZoneInfo

from equitylab import ledger
from equitylab.data import ROOT, canonical, digest

from . import fundamentals, sectors
from . import universe as universes
from .common import (
    LEDGER,
    MARKETS,
    PROTOCOL_VERSION,
    RATINGS,
    REGISTRATIONS,
    protocol_hash,
    safe_key,
    write_json,
)
from .prices import PROVIDER as YAHOO
from .prices import SETTLE_HOUR
from .rating import LABELS, MONEY, PROTOCOL, PROTOCOL_HASH, REASONS, iso_day, positive

DRY_RUNS = RATINGS / "dry-run"
EVENT_TYPE = "rating-registration"
GATE_TYPE = "coverage-gate"
CLOCK_TOLERANCE = timedelta(minutes=10)
# Facts of the registration act itself; an identical re-run may differ only in these.
VOLATILE = ("registeredAt", "registrationDay", "calendar")
SHA256 = re.compile(r"[0-9a-f]{64}")
FETCH_ERROR = "universe_fetch_error"
FINANCIAL = "financial"  # exclusion reasons financial_sic / financial_ksic / _holding
CODE_ROOT = Path(__file__).resolve().parents[1]
# Decided values (docs/ratings-v1.md) used where PROTOCOL does not carry them itself;
# the effective values are recorded with each registration (``settings``).
DEFAULTS = dict(
    registrationWindowSessions=5,
    missedRegistrationExitSession=6,
    universeFetchErrorMaxShare=0.05,
    sessionCalendar={"US": "^SP500TR", "KR": "069500.KS"},
    marketClose={"US": "16:00", "KR": "15:30"},  # regular closes, local time
    codeFiles=[
        "ratings/*.py",
        "scripts/ratings.py",
        "equitylab/data.py",
        "equitylab/ledger.py",
        "equitylab/dart.py",
        "equitylab/forward_study.py",
    ],
)
TIMEZONES = {"US": "America/New_York", "KR": "Asia/Seoul"}
# docs/ratings-v1.md §7 (PROTOCOL decisions.computabilityCheck when it carries them).
GATE_DEFAULTS = dict(
    date="2026-10-20", asOf="2026-10-19", thresholds={"US": 0.90, "KR": 0.80}
)
RANKING_BASIS = "T_close"  # D5': KR members ranked on market caps at T's close
# M3, N1, M1: the only reasons a KR candidate may be left unranked (a halt on T, a
# symbol every Yahoo host answers 404 for, Yahoo answers without a settled session
# through T: a chart with none, or only later ones, or HTTP 400 "Data doesn't exist");
# any other failure to price it needs a rebuild.
UNRANKED = universes.UNRANKED_REASONS
GATE_SUFFIX = universes.GATE_SUFFIX  # H1: the computability-check universe's stem
GATE_PART = re.compile(r"\d{4}-\d{2}-\d{2}" + re.escape(GATE_SUFFIX) + r"(-limit\d+)?")
# D5': the originals whose retrieval times fix each market part in time (the SPY
# holdings; the Naver ranking and the Yahoo closes of T). Profile sources (SEC, OpenDART,
# Ken French, the KSIC table) may be older.
CAPTURE_PROVIDERS = {"US": ("SSGA",), "KR": ("Naver Finance", YAHOO)}
# The builder's own capture records in markets[m] (universe.build) count as well.
CAPTURE_FIELDS = (
    "capturedAt",
    "rankingCapturedAt",
    "holdingsRetrievedAt",
    "rankingRetrievedAt",
    "closesRetrievedAt",
    "pricesRetrievedAt",
)


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def setting(name: str, protocol: dict | None = None):
    """A decided constant from the protocol (top level or one level down), else the
    documented default in DEFAULTS."""
    protocol = PROTOCOL if protocol is None else protocol
    if name in protocol:
        return protocol[name]
    for value in protocol.values():
        if isinstance(value, dict) and name in value:
            return value[name]
    return DEFAULTS[name]


def _zone(market: str, protocol: dict | None = None) -> str:
    protocol = PROTOCOL if protocol is None else protocol
    zones = (protocol.get("registration") or {}).get("timezones") or {}
    return zones.get(market) or TIMEZONES[market]


def market_close(market: str, day: str, protocol: dict | None = None) -> datetime:
    """The regular close of ``day`` in ``market`` as an aware datetime.

    PROTOCOL marketClose gives 'HH:MM' in the market's registration timezone; 'HH:MM
    Area/City' or ``{"time", "timezone"}`` name the zone themselves.
    """
    protocol = PROTOCOL if protocol is None else protocol
    value, zone = setting("marketClose", protocol)[market], _zone(market, protocol)
    if isinstance(value, dict):
        zone = value.get("timezone") or value.get("zone") or zone
        value = value.get("time") or value.get("close")
    clock, *named = str(value).split()
    hour, minute = (int(part) for part in clock.split(":"))
    zone = ZoneInfo(named[0] if named else zone)
    return datetime.combine(date.fromisoformat(iso_day(day)), time(hour, minute), zone)


def gate_rule(protocol: dict | None = None) -> dict:
    """§7 computability check: ``{date, asOf, thresholds}`` (D10': both markets are
    checked at the pinned asOf, the last session before the check date)."""
    protocol = PROTOCOL if protocol is None else protocol
    check = (protocol.get("decisions") or {}).get("computabilityCheck") or {}
    thresholds = check.get("thresholds") or GATE_DEFAULTS["thresholds"]
    return dict(
        date=iso_day(check.get("date") or GATE_DEFAULTS["date"]),
        asOf=iso_day(check.get("asOf") or GATE_DEFAULTS["asOf"]),
        thresholds={market: float(value) for market, value in thresholds.items()},
    )


def moment(value) -> datetime | None:
    """An ISO timestamp with a UTC offset, else None."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def financial(member: dict) -> bool:
    """Excluded by a financial rule: the only exclusion that leaves the denominator."""
    return member.get("status") == "excluded" and str(
        member.get("reason") or ""
    ).startswith(FINANCIAL)


def fetch_error(member: dict) -> bool:
    """The universe could not profile this member: eligible, never rated (D6)."""
    marks = [member.get("reason"), *(member.get("issues") or [])]
    return any(
        (mark.get("issue") if isinstance(mark, dict) else mark) == FETCH_ERROR
        for mark in marks
    )


def code_files() -> dict:
    """SHA-256 of the code a registration was made with (PROTOCOL codeFiles patterns,
    relative to the repository: ratings/*.py, scripts/ratings.py and the equitylab
    modules ratings imports)."""
    files = {
        path
        for pattern in setting("codeFiles")
        for path in CODE_ROOT.glob(pattern)
        if path.is_file()
    }
    return {
        path.relative_to(CODE_ROOT).as_posix(): digest(path.read_bytes())
        for path in sorted(files)
    }


def code_digest() -> str:
    """One SHA-256 over code_files(): the code a checkpoint was collected with (D11')."""
    return digest(canonical(code_files()))


def register(
    as_of,
    universe,
    rated,
    inputs,
    now=None,
    dry_run=False,
    run=None,
    *,
    calendars=None,
    checkpoints=None,
) -> Path:
    """Record one month's rated rows; refuse early, late, backdated, unsupported or
    revised ones.

    ``as_of`` is ``{"US": date, "KR": date}`` (a subset when a market is left out of
    v1); ``rated`` are score() rows covering exactly the universe members of those
    markets; ``inputs`` are the manifests of every original used (a list, or lists by
    group). ``calendars`` maps each market to its benchmark series, a prices.series()
    result fetched through the registration date, for the session rules.
    ``checkpoints`` maps each market to its checkpoint file ``{file, sha256, ...}``
    (D8': recorded; required for a formal registration). ``run`` (dry runs only) is
    stored as the file's ``run`` field; its ``tag`` names the file
    ``<asOf>-<tag>.json``, so a smoke run never replaces a full dry run. A failed check
    refuses a registration and is kept in a dry run's ``issues``.
    """
    if run is not None and not dry_run:
        raise ValueError("run metadata is recorded for dry runs only")
    if universe.get("limit") is not None and not dry_run:
        raise ValueError("A limited (smoke) universe cannot be registered")
    days = _days(as_of)
    when = _stamp(now, dry_run)
    local = {market: _local(when, market) for market in days}
    early = {m: [days[m], local[m]] for m in days if local[m] <= days[m]}
    if early:
        raise ValueError(
            f"Registration date must be after asOf in each market's local date: {early}"
        )
    if protocol_hash(PROTOCOL) != PROTOCOL_HASH:
        raise ValueError("PROTOCOL was modified after import; refusing to register")
    month = next(iter(days.values()))[:7]
    _check_universe(universe, days, month)
    rows = _rows(rated, universe, days)
    manifests = _manifests(inputs)
    calendar, issues = _calendars(days, local, when, calendars or {})
    events = ledger.read(LEDGER)
    gates, refused = _gates(days, events)
    files, unrecorded = _checkpoints(checkpoints, days)
    issues += (
        refused
        + _frozen(events)
        + universe_issues(universe, days, when, _sessions(calendars or {}, days))
        + _gate_parts(universe, days, gate=False)
        + _stale(rows)
        + unrecorded
    )
    if issues and not dry_run:
        raise ValueError("Registration refused: " + "; ".join(issues))
    content = dict(
        version=PROTOCOL_VERSION,
        kind="dry-run" if dry_run else "registration",
        protocol=PROTOCOL,
        protocolHash=PROTOCOL_HASH,
        month=month,
        asOf=days,
        registeredAt=when.isoformat(),
        registrationDay=local,
        calendar=calendar,
        gates=gates,
        settings={name: setting(name) for name in DEFAULTS},
        codeFiles=code_files(),
        checkpoints=files,
        universe=_universe(universe, days),
        inputs=manifests,
        rows=rows,
        labels=_label_counts(rows, days),
    )
    if dry_run:
        content["issues"] = issues
    if run is not None:
        content["run"] = run
    content = json.loads(canonical(content))  # refuses NaN, infinities and non-JSON
    if dry_run:
        tag = (run or {}).get("tag")
        stem = max(days.values()) + (f"-{tag}" if tag else "")
        path = DRY_RUNS / f"{safe_key(stem)}.json"
        write_json(path, content)
        return path
    return _commit(content, when)


def universe_issues(universe: dict, days: dict, when=None, sessions=None) -> list:
    """The universe checks of a formal registration and of a coverage gate: timing
    (D5'), membership (D6, M3) and integrity (D11, D11'). ``sessions`` ({market: session
    dates}) enables the capture-window check; None skips it (a preview)."""
    return (
        _timing(universe, days, when, sessions)
        + _membership(universe, days)
        + _unranked(universe, days)
        + _integrity(universe, days)
    )


def capture_times(part: dict, market: str) -> dict | None:
    """``{first, last, stamps}``: retrieval times of the originals that fix a market part
    in time (CAPTURE_PROVIDERS sources and the part's own capture fields, the widest
    span of them), else None."""
    stamps = [
        source.get("retrievedAt")
        for source in part.get("sources") or []
        if isinstance(source, dict)
        and source.get("provider") in CAPTURE_PROVIDERS[market]
    ]
    info = (part.get("markets") or {}).get(market) or {}
    for field in CAPTURE_FIELDS:
        value = info.get(field)
        stamps += list(value.values()) if isinstance(value, dict) else [value]
    found = sorted(m for m in (moment(s) for s in stamps if s) if m is not None)
    if not found:
        return None
    return dict(
        first=found[0].isoformat(), last=found[-1].isoformat(), stamps=len(found)
    )


def merge_universe(parts: dict, files: dict | None = None, now=None) -> dict:
    """D5': one month's universe from per-market parts built at different times.

    ``parts`` maps each market to its own successful build (``universe.build`` for that
    market alone); ``files`` optionally maps each market to the part's ``{file, sha256}``.
    The parts must share version, rules and limit and fall in one month. Each market
    keeps its own metadata in ``markets[market]``: the asOf it was built for, builtAt and
    completedAt of its build, ``capturedAt`` (capture_times), its rules hash and part
    file; the registry checks every market on its own metadata.
    """
    if not isinstance(parts, dict) or not parts:
        raise ValueError("no universe parts to merge")
    unknown = sorted(set(parts) - set(MARKETS))
    if unknown:
        raise ValueError(f"unknown markets {unknown}")
    chosen = [market for market in MARKETS if market in parts]
    first = parts[chosen[0]]
    days = {}
    for market in chosen:
        part = parts[market]
        info = (part.get("markets") or {}).get(market)
        if (
            part.get("status") != "ok"
            or not isinstance(info, dict)
            or info.get("status", "ok") != "ok"
        ):
            raise ValueError(f"{market}: the part is not a successful build")
        if set(part.get("markets") or {}) != {market} or any(
            member.get("market") != market for member in part.get("members") or []
        ):
            raise ValueError(f"{market}: the part holds other markets")
        for key in ("version", "rulesHash", "rules", "limit"):
            if canonical(part.get(key)) != canonical(first.get(key)):
                raise ValueError(f"the parts differ in {key}")
        day = (part.get("asOfByMarket") or {}).get(market) or info.get("asOf")
        days[market] = iso_day(day or part.get("asOf"))
    if len({day[:7] for day in days.values()}) != 1:
        raise ValueError(f"the parts fall in different months: {days}")
    markets, sources, seen, members = {}, [], set(), []
    for market in chosen:
        part = parts[market]
        info = part["markets"][market]
        markets[market] = dict(
            info,
            asOf=days[market],
            builtAt=part.get("builtAt") or info.get("builtAt"),
            completedAt=part.get("completedAt") or info.get("completedAt"),
            capturedAt=capture_times(part, market),
            rulesHash=part.get("rulesHash"),
            part=(files or {}).get(market),
        )
        for source in part.get("sources") or []:
            key = canonical(source)
            if key not in seen:
                seen.add(key)
                sources.append(source)
        members += part.get("members") or []
    stamps = {
        key: [moment(parts[m].get(key)) for m in chosen]
        for key in ("builtAt", "completedAt")
    }
    merged = dict(
        version=first.get("version"),
        asOf=max(days.values()),
        asOfByMarket=days,
        builtAt=_latest(stamps["builtAt"]),
        completedAt=_latest(stamps["completedAt"]),
        mergedAt=now if isinstance(now, str) else (now or _clock()).isoformat(),
        status="ok",
        rules=first.get("rules"),
        rulesHash=first.get("rulesHash"),
        markets=markets,
        sources=sources,
        members=members,
    )
    if first.get("limit") is not None:
        merged["limit"] = first["limit"]
    return merged


def _latest(stamps: list) -> str | None:
    known = [stamp for stamp in stamps if stamp is not None]
    return max(known).isoformat() if known and len(known) == len(stamps) else None


def read(path) -> dict:
    """Load a registration or a dry run.

    A file in the registration folder, or of kind 'registration' anywhere, must be a
    registration matching its ledger event; it is returned with ``ledger`` (eventId,
    recordedAt, hash, sequence of that event) added.
    """
    path = Path(path)
    blob = path.read_bytes()
    content = _verified_protocol(path, json.loads(blob))
    inside = path.resolve().parent == REGISTRATIONS.resolve()
    if inside or content.get("kind") == "registration":
        if content.get("kind") != "registration":
            raise ValueError(
                f"{path.name}: kind {content.get('kind')!r} is not allowed"
            )
        found = _registration_event(content.get("month"))
        if found is None or found[1].get("fileSha256") != digest(blob):
            raise ValueError(f"{path.name}: does not match its ledger event")
        content["ledger"] = _ledger_block(*found)
    return content


def registrations(strict: bool = True) -> list:
    """Every real registration in ledger order, each with its ``ledger`` block.

    Raises when a ledgered file is missing, altered or not a registration and, when
    ``strict``, when a file in the registration folder has no ledger event (an
    interrupted registration not completed in time must be removed: it was never
    registered).
    """
    out, seen = [], set()
    for sequence, event in enumerate(ledger.read(LEDGER)):
        if event.get("type") != EVENT_TYPE:
            continue
        month = _month_of(event)
        path = REGISTRATIONS / f"{month}.json"
        if not path.exists():
            raise ValueError(f"{event['eventId']}: {path.name} is missing")
        blob = path.read_bytes()
        if digest(blob) != event.get("fileSha256"):
            raise ValueError(f"{path.name}: does not match its ledger event")
        content = _verified_protocol(path, json.loads(blob))
        if content.get("kind") != "registration" or content.get("month") != month:
            raise ValueError(f"{path.name}: not the registration of {month}")
        content["ledger"] = _ledger_block(sequence, event)
        out.append(content)
        seen.add(path.name)
    unledgered = sorted(
        p.name for p in REGISTRATIONS.glob("*.json") if p.name not in seen
    )
    if strict and unledgered:
        raise ValueError(f"Registration files without a ledger event: {unledgered}")
    return out


def previous_labels(month: str) -> dict:
    """{id: label} for the hysteresis rule: each market's rows from the latest real
    registration before ``month`` that contains that market (D16), so a month that left
    a market out does not erase that market's previous labels.

    Only ledgered registrations count, so an interrupted registration of ``month``
    itself can still be completed by re-running it.
    """
    earlier = sorted(
        (r for r in registrations(strict=False) if r["month"] < month),
        key=lambda r: r["month"],
    )
    labels = {}
    for market in MARKETS:
        latest = next(
            (r for r in reversed(earlier) if market in (r.get("asOf") or {})), None
        )
        if latest is not None:
            labels.update(
                {
                    row["id"]: row["label"]
                    for row in latest["rows"]
                    if row.get("market") == market
                }
            )
    return labels


def ledger_head() -> dict:
    """Hash of the newest ledger row and the counts (provenance of an evaluation)."""
    rows = ledger.read(LEDGER)
    return dict(
        head=rows[-1]["hash"] if rows else None,
        events=len(rows),
        registrations=sum(row.get("type") == EVENT_TYPE for row in rows),
    )


def gate(market: str) -> dict | None:
    """The market's coverage gate: its first recorded verdict, which is final (§7)."""
    return next(
        (
            event
            for event in ledger.read(LEDGER)
            if event.get("type") == GATE_TYPE and event.get("market") == market
        ),
        None,
    )


def record_gate(
    market,
    universe,
    *,
    computable,
    collection,
    checkpoints=None,
    calendars=None,
    universe_file=None,
    now=None,
    **detail,
) -> tuple[dict, bool]:
    """Record the market's §7 coverage gate once (D10'): ``(event, created)``.

    A market keeps its first verdict; a later call returns that event unchanged.
    Otherwise the gate is recorded only on or after the check date (market-local), for
    the pinned asOf, from the merged computability-check ``universe`` (H1: the market's
    part saved in <asOf>-gate/, M2: built online) that passes the universe checks of a
    formal registration (``calendars``: the session-calendar series for the capture
    window), and when ``collection`` (the market's collection counts) shows every
    eligible member collected online after the close under this protocol and code (in
    KR not before the universe's share capture: capture_after_retrieval is stale),
    none in error. ``computable`` is the number of non-financial members with at least
    minSignals signals; the denominator (every non-financial member), the rate, the
    threshold and the verdict are computed here. ``checkpoints`` maps the market to the
    checkpoint file its counts came from (L1: ``file`` and ``sha256`` required; the CLI
    adds ``bytes``, the length that hash covers in the append-only file); the event
    records it with every universe part file ``{file, sha256}`` and the merge's
    mergedAt, so the gate can be re-verified. N7: ``universe_file`` is the merged file
    ``universe`` was read from; when the gate is recorded that file must still hold
    ``universe`` and every part file the merge records with a SHA-256 must still have
    it (``_unchanged``). The event's ``universeFile`` is ``detail``'s, else that path.
    Anything else raises ValueError and records nothing.
    """
    if market not in MARKETS:
        raise ValueError(f"A gate needs a market: {market!r}")
    existing = gate(market)
    if existing is not None:
        return existing, False
    check = gate_rule()
    when = _stamp(now, dry_run=False)
    local = _local(when, market)
    if local < check["date"]:
        raise ValueError(
            f"{market}: the coverage gate is recorded on or after {check['date']} "
            f"(it is {local})"
        )
    days = {market: check["asOf"]}
    _check_universe(universe, days, check["asOf"][:7])
    if universe.get("limit") is not None:
        raise ValueError("A limited (smoke) universe cannot set the coverage gate")
    events = ledger.read(LEDGER)
    files, unrecorded = _checkpoints(checkpoints, days)
    issues = (
        _frozen(events)
        + universe_issues(universe, days, when, _sessions(calendars or {}, days))
        + _gate_parts(universe, days, gate=True)
        + _unchanged(universe, universe_file)
        + _complete(collection, universe, market)
        + unrecorded
    )
    base = [
        m
        for m in universe.get("members") or []
        if m.get("market") == market and not financial(m)
    ]
    if (
        isinstance(computable, bool)
        or not isinstance(computable, int)
        or not 0 <= computable <= len(base)
    ):
        issues.append(f"{market}: computable {computable!r} of {len(base)} members")
    if not base:
        issues.append(f"{market}: no non-financial members")
    if issues:
        raise ValueError("Coverage gate not recorded: " + "; ".join(issues))
    threshold = check["thresholds"][market]
    share = Fraction(computable, len(base))
    detail.setdefault("universeFile", _relative(Path(universe_file)))
    event = dict(
        detail,
        eventId=f"{PROTOCOL_VERSION}:{GATE_TYPE}:{market}",
        type=GATE_TYPE,
        market=market,
        asOf=check["asOf"],
        checkDate=check["date"],
        rate=float(share),
        threshold=threshold,
        verdict="pass" if share >= Fraction(str(threshold)) else "fail",
        computable=computable,
        nonFinancial=len(base),
        universeSha256=digest(canonical(universe)),
        # L1: what re-verifies the gate (the merge, its parts, the checkpoints read).
        mergedAt=universe.get("mergedAt"),
        universeParts={
            m: (info or {}).get("part")
            for m, info in (universe.get("markets") or {}).items()
        },
        checkpoints=files,
        protocolHash=PROTOCOL_HASH,
        collection={
            key: collection.get(key)
            for key in ("eligible", "fetchErrors", "collected", "errors", "stale")
        },
    )
    return ledger.append(LEDGER, json.loads(canonical(event))), True


def write_once(path: Path, content: dict) -> None:
    """Write a complete JSON file and link it into place; an existing file is never
    replaced (FileExistsError)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    handle, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)


def _verified_protocol(path: Path, content: dict) -> dict:
    if protocol_hash(content.get("protocol") or {}) != content.get("protocolHash"):
        raise ValueError(f"{path.name}: protocol hash mismatch")
    return content


def _month_of(event: dict) -> str:
    return str(event.get("month") or event["eventId"].split(":", 1)[1])


def _registration_event(month) -> tuple[int, dict] | None:
    event_id = f"{PROTOCOL_VERSION}:{month}"
    return next(
        (
            (sequence, event)
            for sequence, event in enumerate(ledger.read(LEDGER))
            if event["eventId"] == event_id and event.get("type") == EVENT_TYPE
        ),
        None,
    )


def _ledger_block(sequence: int, event: dict) -> dict:
    return dict(
        eventId=event["eventId"],
        recordedAt=event.get("recordedAt"),
        hash=event.get("hash"),
        sequence=sequence,
    )


def _days(as_of) -> dict:
    if not isinstance(as_of, dict) or not as_of:
        raise ValueError("as_of must be {market: date}")
    unknown = sorted(set(as_of) - set(MARKETS))
    if unknown:
        raise ValueError(f"Unknown markets in as_of: {unknown}")
    days = {market: iso_day(as_of[market]) for market in MARKETS if market in as_of}
    if len({day[:7] for day in days.values()}) != 1:
        raise ValueError(f"asOf dates must share one month: {days}")
    return days


def _local(when: datetime, market: str) -> str:
    return when.astimezone(ZoneInfo(_zone(market))).date().isoformat()


def _stamp(now, dry_run: bool) -> datetime:
    clock = _clock()
    when = clock if now is None else now
    if not isinstance(when, datetime) or when.utcoffset() is None:
        raise ValueError("Registration time must be a timezone-aware datetime")
    if not dry_run and abs(when - clock) > CLOCK_TOLERANCE:
        raise ValueError("A registration carries the current time; backdating refused")
    return when.astimezone(timezone.utc)


def _check_universe(universe: dict, days: dict, month: str) -> None:
    """A registered market needs a successful universe build for the same month."""
    if str(universe.get("asOf") or month)[:7] != month:
        raise ValueError(f"Universe asOf {universe.get('asOf')} is not in {month}")
    markets = universe.get("markets") or {}
    failed = {
        m: (markets.get(m) or {}).get("error")
        for m in days
        if (markets.get(m) or {}).get("status", "ok") != "ok"
    }
    if failed:
        raise ValueError(f"Universe build failed for registered markets: {failed}")


def _sessions(calendars: dict, markets) -> dict:
    """{market: sorted session dates} of each usable session-calendar series."""
    out = {}
    for market in markets:
        series = calendars.get(market)
        if (
            isinstance(series, dict)
            and series.get("status") == "ok"
            and series.get("symbol") == setting("sessionCalendar")[market]
        ):
            out[market] = sorted(
                {row[0] for row in series.get("rows") or [] if positive(row[1])}
            )
    return out


def _calendars(days: dict, local: dict, when: datetime, calendars: dict) -> tuple:
    """D3: in each market's benchmark series T is the last session of its month, the
    month is over and fewer than the window's sessions passed before the registration
    date. The series must be retrieved for this registration (all earlier sessions)."""
    window = int(setting("registrationWindowSessions"))
    record, issues = {}, []
    sessions_by_market = _sessions(calendars, days)
    for market, day in days.items():
        symbol = setting("sessionCalendar")[market]
        series = calendars.get(market)
        if market not in sessions_by_market:
            issues.append(f"{market}: no {symbol} series for the session rules")
            record[market] = dict(symbol=symbol, available=False)
            continue
        zone = ZoneInfo(_zone(market))
        sessions = sessions_by_market[market]
        source = series.get("source") or {}
        retrieved = moment(source.get("retrievedAt"))
        before = date.fromisoformat(local[market]) - timedelta(days=1)
        through = str((series.get("window") or {}).get("through") or "")
        if (
            retrieved is None
            or retrieved < datetime.combine(before, time(SETTLE_HOUR), zone)
            or retrieved > when + CLOCK_TOLERANCE
            or through < before.isoformat()
        ):
            issues.append(
                f"{market}: {symbol} series not retrieved for this registration "
                f"(retrieved {source.get('retrievedAt')}, through {through or None})"
            )
        end = f"{day[:7]}-{monthrange(int(day[:4]), int(day[5:7]))[1]:02d}"
        later = [s for s in sessions if day < s <= end]
        elapsed = [s for s in sessions if day < s < local[market]]
        if day not in sessions:
            issues.append(f"{market}: asOf {day} is not a {symbol} session")
        if later:
            issues.append(f"{market}: asOf {day} is not the last session of its month")
        if local[market] <= end:
            issues.append(f"{market}: {day[:7]} has not ended on {local[market]}")
        if len(elapsed) >= window:
            issues.append(
                f"{market}: the registration window closed on {elapsed[window - 1]} "
                f"({window} sessions after {day}); a missed month is never registered"
            )
        record[market] = dict(
            symbol=symbol,
            available=True,
            source=source,
            through=through,
            sessionsAfterAsOf=elapsed,
            windowSessions=window,
        )
    return record, issues


def _gates(days: dict, events: list) -> tuple[dict, list]:
    """D10, D10': each registered market passed its coverage gate, recorded under this
    protocol for the pinned asOf, before its first registration; a failed US gate
    blocks every registration."""
    check = gate_rule()
    first = {}
    for sequence, event in enumerate(events):
        if event.get("type") == GATE_TYPE:
            first.setdefault(("gate", event.get("market")), (sequence, event))
        elif event.get("type") == EVENT_TYPE:
            for market in event.get("asOf") or {}:
                first.setdefault(("registration", market), (sequence, event))
    record, issues = {}, []
    us = first.get(("gate", "US"))
    if us is not None and us[1].get("verdict") != "pass":
        issues.append("US failed its coverage gate: no ratings are published (§7)")
    for market in days:
        found = first.get(("gate", market))
        if found is None:
            issues.append(f"{market}: no coverage gate in the ledger (run coverage)")
            continue
        sequence, event = found
        record[market] = {
            key: event.get(key)
            for key in (
                "eventId",
                "hash",
                "asOf",
                "rate",
                "threshold",
                "verdict",
                "protocolHash",
            )
        }
        if event.get("protocolHash") != PROTOCOL_HASH:
            issues.append(
                f"{market}: coverage gate recorded under protocol "
                f"{str(event.get('protocolHash'))[:12]}, not {PROTOCOL_HASH[:12]}"
            )
        if event.get("asOf") != check["asOf"]:
            issues.append(
                f"{market}: coverage gate computed at {event.get('asOf')}, not the "
                f"pinned {check['asOf']}"
            )
        if market != "US" and event.get("verdict") != "pass":
            issues.append(
                f"{market}: failed its coverage gate, so it is left out of v1 (§7)"
            )
        earlier = first.get(("registration", market))
        if earlier is not None and earlier[0] < sequence:
            issues.append(
                f"{market}: coverage gate recorded after its first registration "
                f"{earlier[1].get('eventId')}"
            )
    return record, issues


def _frozen(events: list) -> list:
    """D11': every registration and gate in the ledger carries this protocol's hash."""
    other = [
        str(event.get("eventId"))
        for event in events
        if event.get("type") in (EVENT_TYPE, GATE_TYPE)
        and event.get("protocolHash") != PROTOCOL_HASH
    ]
    if not other:
        return []
    return [
        f"ledger events under another protocol hash {other[:5]}: ratings-v1 is "
        "frozen, a protocol change needs ratings-v2"
    ]


def _timing(universe: dict, days: dict, when=None, sessions=None) -> list:
    """D5': each market's part was built online (M2: ``markets[m].online`` is True;
    an offline build replays whatever the stored originals hold) for that market's T
    and captured after T's close (marketClose), not after the registration and, with
    ``sessions``, inside the registration window; US holdings are as of T, KR members
    are ranked on T's closes.
    """
    markets = universe.get("markets") or {}
    by_market = universe.get("asOfByMarket") or {}
    window = int(setting("registrationWindowSessions"))
    basis = ((PROTOCOL.get("universe") or {}).get("KR") or {}).get("rankingBasis")
    basis = basis or RANKING_BASIS
    issues = []
    if not universe.get("mergedAt"):
        issues.append(
            "the universe is not a merge of market parts (save each market's part with "
            "'universe' and merge them with 'universe-merge')"
        )
    for market, day in days.items():
        info = markets.get(market) or {}
        built_for = by_market.get(market) or info.get("asOf") or universe.get("asOf")
        if str(built_for) != day:
            issues.append(f"{market}: universe part built for {built_for}, not {day}")
        if info.get("online") is not True:  # M2
            issues.append(
                f"{market}: universe part not built online (online "
                f"{info.get('online')!r}): build it again without --offline "
                f"('universe --markets {market}', with --gate for the "
                "computability-check universe) and merge it"
            )
        close = market_close(market, day)
        captured = info.get("capturedAt") or {}
        first, last = moment(captured.get("first")), moment(captured.get("last"))
        if first is None or last is None:
            issues.append(
                f"{market}: the universe has no capture times for this market (build "
                f"its part with 'universe --markets {market}' and run universe-merge)"
            )
        else:
            if first <= close:
                issues.append(
                    f"{market}: universe captured from {captured['first']}, not after "
                    f"the {day} close"
                )
            if when is not None and last > when + CLOCK_TOLERANCE:
                issues.append(
                    f"{market}: universe captured at {captured['last']}, after "
                    f"{when.isoformat()}"
                )
            if sessions is not None:
                on = last.astimezone(close.tzinfo).date().isoformat()
                if market not in sessions:
                    issues.append(
                        f"{market}: no session calendar to check the capture window"
                    )
                elif len([s for s in sessions[market] if day < s < on]) >= window:
                    issues.append(
                        f"{market}: universe captured on {on}, after the registration "
                        f"window ({window} sessions after {day})"
                    )
        if market == "US" and info.get("holdingsAsOf") != day:
            issues.append(
                f"US: SPY holdings as of {info.get('holdingsAsOf')}, not {day}"
            )
        if market == "KR" and info.get("rankingBasis") != basis:
            issues.append(
                f"KR: members ranked on {info.get('rankingBasis')}, not {basis} "
                f"(market caps at the {day} close)"
            )
    return issues


def _membership(universe: dict, days: dict) -> list:
    """D6 and §2: only the financial rules exclude; profile failures stay eligible and
    may not exceed universeFetchErrorMaxShare of the non-financial members; the Money
    sector holds no eligible member."""
    limit = float(setting("universeFetchErrorMaxShare"))
    issues = []
    for market in days:
        members = [
            m for m in universe.get("members") or [] if m.get("market") == market
        ]
        base = [m for m in members if not financial(m)]
        wrong = Counter(
            str(m.get("reason")) for m in base if m.get("status") != "eligible"
        )
        if wrong:
            issues.append(
                f"{market}: members excluded by non-financial reasons {dict(wrong)}; "
                "only the financial rules exclude"
            )
        failed = [m for m in base if fetch_error(m)]
        if base and len(failed) > limit * len(base):
            issues.append(
                f"{market}: universe fetch errors for {len(failed)} of {len(base)} "
                f"non-financial members (over {limit:.0%}); rebuild the universe"
            )
        money = [
            m.get("id")
            for m in members
            if m.get("status") == "eligible" and m.get("sector") in MONEY
        ]
        if money:
            issues.append(f"{market}: eligible members in the Money sector {money[:5]}")
    return issues


def _unranked(universe: dict, days: dict) -> list:
    """M3, N1, M1: a KR candidate is left unranked only by a halt on T
    (no_close_on_as_of), a symbol unknown to Yahoo (a confirmed 404, symbol_not_found)
    or Yahoo answers without a settled session through T (not_listed_on_as_of: listed
    after T, or halted throughout; a chart or HTTP 400 "Data doesn't exist"); any other
    reason (a failed or rejected price download) would quietly swap a large company for
    a smaller one."""
    if "KR" not in days:
        return []
    info = (universe.get("markets") or {}).get("KR") or {}
    unranked = info.get("unranked") or []
    if not isinstance(unranked, list):
        return [f"KR: unranked candidates unreadable ({type(unranked).__name__})"]
    other = Counter(
        str(item.get("reason") if isinstance(item, dict) else item)
        for item in unranked
        if not (isinstance(item, dict) and item.get("reason") in UNRANKED)
    )
    if not other:
        return []
    return [
        f"KR: candidates left unranked for {dict(sorted(other.items()))}, not only "
        f"{list(UNRANKED)}: a failed price download is never an exclusion; rebuild "
        "the KR part"
    ]


def _gate_parts(universe: dict, days: dict, gate: bool) -> list:
    """H1: the computability-check universe is saved apart (its parts in <T>-gate/).
    ``gate``: each market's part is a gate part of its T, recorded with its SHA-256;
    otherwise none of them is (the gate universe is never registered)."""
    markets = universe.get("markets") or {}
    issues = []
    for market, day in days.items():
        part = (markets.get(market) or {}).get("part") or {}
        folder = PurePosixPath(str(part.get("file") or "")).parent.name
        if gate and (
            folder != f"{day}{GATE_SUFFIX}"
            or not SHA256.fullmatch(str(part.get("sha256")))
        ):
            issues.append(
                f"{market}: not the computability-check universe (part "
                f"{part.get('file')!r}, expected one saved in {day}{GATE_SUFFIX}/ with "
                "its SHA-256): build it with 'universe --gate' and merge it with "
                "'universe-merge --gate'"
            )
        elif not gate and GATE_PART.fullmatch(folder):
            issues.append(
                f"{market}: the computability-check universe ({part.get('file')}) is "
                "never registered"
            )
    return issues


def _part_path(file: str) -> Path:
    """A part file as universe.merge records it (data/ratings/universe/<stem>/<market>
    .json) in the folder the universe module writes to (universe.UNIVERSE_DIR)."""
    path = PurePosixPath(str(file))
    try:
        return universes.UNIVERSE_DIR / path.relative_to("data/ratings/universe")
    except ValueError:
        return ROOT / path


def _unchanged(universe: dict, universe_file) -> list:
    """N7: what a gate records still matches the files: the merged file
    ``universe_file`` still holds ``universe`` (its canonical SHA-256 is the event's
    universeSha256) and every part file the merge records with a SHA-256 still has it
    (a part rebuilt with --overwrite whose re-merge failed does not)."""
    if universe_file is None:
        return ["no merged universe file given to verify the gate against (N7)"]
    path, issues = Path(universe_file), []
    try:
        on_disk = digest(canonical(json.loads(path.read_bytes())))
    except (OSError, ValueError) as exc:
        return [f"merged universe {path.name} unreadable: {exc}"]
    if on_disk != digest(canonical(universe)):
        issues.append(
            f"{path.name} no longer holds the universe being recorded (sha256 "
            f"{on_disk[:12]}, recording {digest(canonical(universe))[:12]}): run "
            "coverage again on the current merge"
        )
    for market, info in sorted((universe.get("markets") or {}).items()):
        part = info.get("part") if isinstance(info, dict) else None
        if not isinstance(part, dict) or not SHA256.fullmatch(str(part.get("sha256"))):
            continue  # nothing recorded to compare (_gate_parts requires the gate's)
        try:
            found = digest(_part_path(part.get("file")).read_bytes())
            shown = f"sha256 {found[:16]}"
        except OSError as exc:
            found, shown = None, f"unreadable: {type(exc).__name__}"
        if found != part["sha256"]:
            recorded = part["sha256"][:16]
            issues.append(
                f"{market}: part {part.get('file')} on disk ({shown}) is not the one "
                f"the merge recorded (sha256 {recorded}): run universe-merge --gate "
                "(or rebuild the part) and coverage again"
            )
    return issues


def _find(value, name: str) -> list:
    """Every value stored under key ``name`` anywhere in a nested dict/list."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            found += [item] if key == name else _find(item, name)
    elif isinstance(value, list):
        for item in value:
            found += _find(item, name)
    return found


def _pin(name: str) -> str | None:
    """The PROTOCOL pin ``name`` when PROTOCOL holds it once (or consistently)."""
    pins = {str(value) for value in _find(PROTOCOL, name)}
    return pins.pop() if len(pins) == 1 else None


def _integrity(universe: dict, days: dict) -> list:
    """D11, D11': the universe used the pinned FF12 definition, KSIC reference and rules,
    the KSIC table file still matches its PROTOCOL pin, and the modules still hold the
    rules PROTOCOL hashed at import."""
    pins = PROTOCOL.get("moduleRules") or {}
    markets = universe.get("markets") or {}
    issues = []
    ff12 = _pin("ff12DefinitionSha256")
    if "US" in days and ff12 and (markets.get("US") or {}).get("ff12Hash") != ff12:
        issues.append("US: the universe FF12 definition differs from the pinned hash")
    ksic = _pin("ksicReferenceSha256")
    if ksic is None:
        issues.append("PROTOCOL does not pin one KSIC reference SHA-256")
    else:
        try:
            table = digest(sectors.KSIC_REFERENCE.read_bytes())
        except OSError:
            table = None
        if table != ksic:
            issues.append(
                f"{_relative(sectors.KSIC_REFERENCE)} does not match the PROTOCOL pin "
                "ksicReferenceSha256 (a new table needs ratings-v2)"
            )
        used = {
            source.get("sha256")
            for source in universe.get("sources") or []
            if isinstance(source, dict) and source.get("key") == "ksic-ff12"
        }
        if "KR" in days and used != {ksic}:
            issues.append(
                "KR: the universe KSIC reference differs from the pinned SHA-256"
            )
    rules = pins.get("universe")
    if rules is not None and (
        canonical(universe.get("rules")) != canonical(rules)
        or universe.get("rulesHash") != digest(canonical(rules))
    ):
        issues.append("the universe rules differ from PROTOCOL moduleRules.universe")
    for name, module in (("universe", universes), ("fundamentals", fundamentals)):
        live = json.loads(json.dumps(module.RULES))
        if name in pins and canonical(live) != canonical(pins[name]):
            issues.append(f"ratings.{name}.RULES changed after PROTOCOL was hashed")
    return issues


def _stale(rows: list) -> list:
    """D9': a formal row never comes from a stale checkpoint (collection.stale)."""
    stale = sorted(
        str(row.get("id"))
        for row in rows
        if isinstance(row.get("collection"), dict) and row["collection"].get("stale")
    )
    if not stale:
        return []
    return [
        f"{len(stale)} rows come from stale checkpoints (collection.stale) "
        f"{stale[:5]}: collect them again online after the close"
    ]


def _checkpoints(checkpoints, days: dict) -> tuple[dict, list]:
    """D8': the checkpoint file of every registered market, recorded by SHA-256."""
    record, issues = {}, []
    for market in days:
        item = (checkpoints or {}).get(market)
        if not (
            isinstance(item, dict)
            and SHA256.fullmatch(str(item.get("sha256")))
            and item.get("file")
        ):
            issues.append(f"{market}: no checkpoint file SHA-256 recorded")
            continue
        record[market] = dict(item)
    return record, issues


def _complete(collection, universe: dict, market: str) -> list:
    """D10': every eligible member collected (or left unprofiled by the universe) and
    no checkpoint stale (offline, before the close, other protocol or code, or a KR
    series retrieved before the universe's share capture) or in error."""
    stats = collection if isinstance(collection, dict) else {}
    eligible = sum(
        1
        for m in universe.get("members") or []
        if m.get("market") == market and m.get("status") == "eligible"
    )
    problems = [
        f"{key} {stats.get(key)!r}"
        for key in ("notCollected", "stale", "errors")
        if stats.get(key) != 0
    ]
    if (
        stats.get("eligible") != eligible
        or (stats.get("collected") or 0) + (stats.get("fetchErrors") or 0) != eligible
    ):
        problems.append(
            f"collected {stats.get('collected')!r} + fetchErrors "
            f"{stats.get('fetchErrors')!r} of {eligible} eligible"
        )
    if not problems:
        return []
    return [
        f"{market}: incomplete collection ({', '.join(problems)}); retry once every "
        "eligible member is collected online after the close, current and not in error"
    ]


def _rows(rated, universe: dict, days: dict) -> list:
    rows = [dict(row) for row in rated]
    counts = Counter(row.get("id") for row in rows)
    duplicates = sorted(str(key) for key, n in counts.items() if n > 1)
    if duplicates:
        raise ValueError(f"Duplicate rated ids: {duplicates[:5]}")
    for row in rows:
        name, market = row.get("id"), row.get("market")
        if market not in days:
            raise ValueError(f"{name}: market {market!r} is not being registered")
        if row.get("asOf") is None or iso_day(row["asOf"]) != days[market]:
            raise ValueError(
                f"{name}: computed for asOf {row.get('asOf')}, registering {days[market]}"
            )
        label, reason = row.get("label"), row.get("labelReason")
        if label not in (*LABELS, None) or reason not in REASONS:
            raise ValueError(f"{name}: not a scored row (label {label!r}, {reason!r})")
        if (label is None) != (reason in ("insufficient", "excluded")):
            raise ValueError(f"{name}: label {label!r} contradicts reason {reason!r}")
    members = {
        m.get("id") for m in universe.get("members") or [] if m.get("market") in days
    }
    missing, extra = sorted(members - set(counts)), sorted(set(counts) - members)
    if missing or extra:
        raise ValueError(
            "Rated rows must cover the universe exactly: "
            f"missing {missing[:5]} ({len(missing)}), extra {extra[:5]} ({len(extra)})"
        )
    return rows


TIMING_KEYS = (
    "asOf",
    "builtAt",
    "completedAt",
    "capturedAt",
    "holdingsAsOf",
    "rankingBasis",
    "rulesHash",
    "part",
    "ff12Hash",
)


def _universe(universe: dict, days: dict) -> dict:
    members = universe.get("members") or []
    markets = universe.get("markets") or {}
    counts, timing = {}, {}
    for market in days:
        mine = [m for m in members if m.get("market") == market]
        status = Counter(m.get("status") for m in mine)
        counts[market] = dict(
            members=len(mine),
            eligible=status["eligible"],
            excluded=len(mine) - status["eligible"],
            financialExcluded=sum(financial(m) for m in mine),
            fetchErrors=sum(fetch_error(m) for m in mine),
        )
        info = markets.get(market) or {}
        timing[market] = {key: info.get(key) for key in TIMING_KEYS if key in info}
    return dict(
        sha256=digest(canonical(universe)),
        version=universe.get("version"),
        asOf=universe.get("asOf"),
        builtAt=universe.get("builtAt"),
        mergedAt=universe.get("mergedAt"),
        rulesHash=universe.get("rulesHash"),
        timing=timing,
        counts=counts,
        sources=_manifests(universe.get("sources") or [], "universe.sources"),
    )


def _manifests(inputs, where: str = "inputs"):
    if isinstance(inputs, dict):
        return {
            str(group): _manifests(items, f"{where}.{group}")
            for group, items in inputs.items()
        }
    unique = {}
    for item in inputs or []:
        if (
            not isinstance(item, dict)
            or not SHA256.fullmatch(str(item.get("sha256")))
            or not item.get("file")
        ):
            raise ValueError(f"{where}: every original needs a manifest (sha256, file)")
        unique[(str(item["file"]), item["sha256"])] = item
    return [unique[key] for key in sorted(unique)]


def _label_counts(rows: list, days: dict) -> dict:
    """Label counts; the computable rate's denominator is every non-financial member."""
    out = {}
    for market in days:
        mine = [r for r in rows if r["market"] == market]
        reasons = Counter(r["labelReason"] for r in mine)
        labels = Counter(r["label"] for r in mine if r["label"] is not None)
        base = sum(not financial(r) for r in mine)
        scored = sum(labels.values())
        out[market] = {
            **{label: labels[label] for label in LABELS},
            "insufficient": reasons["insufficient"],
            "excluded": reasons["excluded"],
            "eligible": len(mine) - reasons["excluded"],
            "nonFinancial": base,
            "scored": scored,
            "computableRate": scored / base if base else None,
        }
    return out


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _substance(content: dict) -> dict:
    return {key: value for key, value in content.items() if key not in VOLATILE}


def _commit(content: dict, when: datetime) -> Path:
    month = content["month"]
    path = REGISTRATIONS / f"{month}.json"
    event_id = f"{PROTOCOL_VERSION}:{month}"
    events = [e for e in ledger.read(LEDGER) if e.get("type") == EVENT_TYPE]
    mine = next((e for e in events if e["eventId"] == event_id), None)
    later = sorted(_month_of(e) for e in events if _month_of(e) > month)
    if mine is None and later:
        raise ValueError(
            f"Months must increase: {later[-1]} is registered, so {month} never can be"
        )
    if not path.exists():
        if mine is not None:
            raise ValueError(f"Ledger already records {event_id} but {path} is missing")
        try:
            write_once(path, content)
        except FileExistsError:
            pass  # a concurrent registration won the race; compare with it below
    blob = path.read_bytes()
    stored = json.loads(blob)
    if _substance(stored) != _substance(content):
        raise ValueError(f"{path.name} is already registered with different content")
    if mine is None:
        # A file without its event is an interrupted registration. It is completed only
        # by a re-run close to the stamp it carries, so it can never be backdated.
        stamp = moment(stored.get("registeredAt"))
        if stamp is None or abs(stamp - when) > CLOCK_TOLERANCE:
            raise ValueError(
                f"{path.name} has no ledger event and is stamped "
                f"{stored.get('registeredAt')}: an interrupted registration is "
                f"completed only within {CLOCK_TOLERANCE} of its stamp; remove the "
                "unledgered file (it was never registered) and register again"
            )
    ledger.append(
        LEDGER,
        dict(
            eventId=event_id,
            type=EVENT_TYPE,
            month=month,
            file=_relative(path),
            fileSha256=digest(blob),
            protocolHash=stored["protocolHash"],
            universeSha256=stored["universe"]["sha256"],
            asOf=stored["asOf"],
            registeredAt=stored["registeredAt"],
        ),
    )
    return path
