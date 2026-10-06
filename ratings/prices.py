"""Daily price series for ratings-v1 (Yahoo Finance chart API).

rows are ``[date, adjclose, close]`` in ascending exchange-local dates, limited to the
requested window and to sessions that had settled when the original was retrieved.

- ``adjclose`` is split- and dividend-adjusted as of the retrieval vintage. Ratios
  inside one series are total returns; levels are not comparable across fetches.
- ``close`` is Yahoo's close: dividend-unadjusted but split-adjusted as of retrieval, so
  it equals the traded close only when no split occurred between that day and retrieval.
- ``splits`` lists every split event whose exchange-local ex-date lies in the requested
  window, as ``{"date", "numerator", "denominator"}`` with the provider's numbers (a
  10-for-1 split is 10:1, a 1-for-20 reverse split 1:20). Fetch through the retrieval
  date to see every split that restated ``close`` (rating.market_cap reconciles them);
  a split after ``window.through`` is never listed, so a window ending before the
  exchange-local retrieval date leaves later splits unknown (D7').

A failed or rejected download is returned as an error; older stored data is never
substituted. Offline mode replays the stored original for the same (symbol, window).
A kept series is rebuilt from its hash-verified original with ``_parse`` (see there),
never from rows saved beside it. An original for the requested symbol and currency
without a settled session in the window (NoSessions: listed after it, or no trading
throughout) is rejected like any other, and ``series`` records the last such answer
as ``empty`` so that a caller can tell it from a failed download. Yahoo answers a
request without any session in it (a symbol listed after the request's end) with HTTP
400 and a chart error "Data doesn't exist ..." (NO_DATA): that body is stored as an
original (``httpStatus`` 400 in its manifest) and read as such an answer (NoSessions);
any other HTTP 400 body stays an error. ``request_through`` asks Yahoo for sessions
after the window as well (a listing after it then shows as "next session ...") without
changing the window, the rows or the stored key.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date, datetime, time, timedelta, timezone
from http.client import HTTPException
import json
import math
from operator import itemgetter
import re
from urllib.parse import quote
from zoneinfo import ZoneInfo

from ratings.common import FetchError, fetch, safe_key

PROVIDER = "Yahoo Finance"
HOSTS = ("query2", "query1")
LOOKBACK_DAYS = 400
# A close is final once retrieval is at or after this exchange-local hour that day.
SETTLE_HOUR = 18
MOMENTUM_SKIP = 21
MOMENTUM_LOOKBACK = 252
# M1: Yahoo's HTTP 400 for a request without any session (live 2026-10-06, 0126Z0.KS
# through 2025-11-20 on both hosts): {"chart":{"result":null,"error":{"code":"Bad
# Request","description":"Data doesn't exist for startDate = ..., endDate = ..."}}}.
NO_DATA_STATUS = 400
NO_DATA = "Data doesn't exist"
SYMBOL = re.compile(r"\^?[A-Za-z0-9][A-Za-z0-9.=&-]{0,40}")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
PARSE_ERRORS = (
    ValueError,
    KeyError,
    TypeError,
    IndexError,
    AttributeError,
    OverflowError,
)
_date = itemgetter(0)


class NoSessions(ValueError):
    """An original naming the requested symbol, in the expected currency, without a
    settled session in the requested window, or Yahoo's HTTP 400 NO_DATA answer for
    the symbol's request (``_kept``). A rejected original (a PARSE_ERRORS ValueError)
    whose answer is "nothing traded": the symbol listed after the window, or traded on
    no day of it."""


class UnpublishedClose(ValueError):
    """An original whose last session in the window has traded volume but no close:
    the provider has not published that close yet (seen live for KRX symbols around
    midnight KST, 2026-10-07, flapping by symbol). A rejected original, so the series
    fails and is fetched again; never read as a halt (a halted session has no volume).
    """


def _iso(value) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and DAY.fullmatch(value):
        return date.fromisoformat(value).isoformat()
    raise ValueError(f"Expected a YYYY-MM-DD day, got {value!r}")


def _window(through, start=None) -> tuple[date, date]:
    end = date.fromisoformat(_iso(through))
    first = end - timedelta(days=LOOKBACK_DAYS)
    if start is not None:
        first = min(first, date.fromisoformat(_iso(start)))
    return first, end


def source_key(symbol: str, through, start=None) -> str:
    """Stable original key per (symbol, window); others hex-escaped (^ -> _5E)."""
    if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
        raise ValueError(f"Unsupported symbol {symbol!r}")
    first, end = _window(through, start)
    escaped = re.sub(r"[^A-Za-z0-9.-]", lambda m: f"_{ord(m.group()):02X}", symbol)
    key = f"yahoo-{escaped}-{end}"
    if first != end - timedelta(days=LOOKBACK_DAYS):
        key += f"-from-{first}"
    return safe_key(key)


def _epoch(day: date) -> int:
    return int(datetime.combine(day, time(0), timezone.utc).timestamp())


def _url(host: str, symbol: str, first: date, end: date) -> str:
    # UTC bounds widened (first-1, end+2) so boundary sessions in any exchange timezone
    # are returned; rows are then trimmed to the window in exchange-local dates (``end``
    # is the window's end, or the later request_through of series()).
    period1, period2 = _epoch(first - timedelta(days=1)), _epoch(
        end + timedelta(days=2)
    )
    return (
        f"https://{host}.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
        f"?period1={period1}&period2={period2}"
        "&interval=1d&events=div,split&includeAdjustedClose=true"
    )


def _expected_currency(symbol: str) -> str | None:
    if symbol.endswith((".KS", ".KQ")):
        return "KRW"
    if re.fullmatch(r"[A-Z][A-Z0-9-]*", symbol):
        return "USD"
    return None  # indices and other venues: recorded, not asserted


def _price(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def _brief(days: list, limit: int = 8) -> str:
    more = f" (+{len(days) - limit} more)" if len(days) > limit else ""
    return ", ".join(days[:limit]) + more


def _parse(blob: bytes, symbol: str, first, end, retrieved_at: str) -> dict:
    """Rows, splits and metadata of one Yahoo chart original: pure and deterministic.

    ``series()`` returns exactly this plus symbol, status, source and window, so a kept
    series is rebuilt from its original with the values recorded beside it::

        blob = common.load(series["source"])  # hash-verified original bytes
        _parse(blob, series["symbol"], series["window"]["from"],
               series["window"]["through"], series["source"]["retrievedAt"])

    - ``blob``: the original bytes as fetched.
    - ``symbol``: the requested symbol; the original must name the same one.
    - ``first``, ``end``: the inclusive window in exchange-local dates ('YYYY-MM-DD',
      a date or a datetime); rows and split events outside it are dropped.
    - ``retrieved_at``: ISO timestamp with a UTC offset (the manifest's retrievedAt);
      a session is kept only if it was retrieved at or after SETTLE_HOUR local time
      on its day. A timestamp without an offset is refused, since the settled
      sessions would then depend on the machine's time zone.

    Returns ``{rows, currency, timezone, splits, nullSessions, notes}``. A rejected
    original raises one of PARSE_ERRORS; one that names ``symbol`` in the expected
    currency, with only valid rows but no settled session in the window, raises
    NoSessions (a ValueError). A null-close session with traded volume after the last
    valid row raises UnpublishedClose (a ValueError): its close is not out yet. Such a
    session before a valid row is dropped like any null-close session.
    """
    first, end = _iso(first), _iso(end)
    chart = json.loads(blob)["chart"]
    if chart.get("error"):
        error = chart["error"]
        raise ValueError(
            f"provider error {error.get('code')}: {error.get('description')}"
        )
    results = chart.get("result") or []
    if len(results) != 1:
        raise ValueError(f"expected one chart result, got {len(results)}")
    result = results[0]
    meta = result["meta"]
    if meta.get("symbol") != symbol:
        raise ValueError(f"provider returned symbol {meta.get('symbol')!r}")
    zone = meta["exchangeTimezoneName"]
    tz = ZoneInfo(zone)
    currency, expected = meta.get("currency"), _expected_currency(symbol)
    if expected and currency != expected:
        raise ValueError(f"currency {currency!r}, expected {expected}")
    stamps = result.get("timestamp") or []
    closes = adjusted = volumes = []
    if stamps:
        closes = result["indicators"]["quote"][0]["close"]
        adjusted = result["indicators"]["adjclose"][0]["adjclose"]
        if not len(stamps) == len(closes) == len(adjusted):
            raise ValueError("timestamp, close and adjclose lengths differ")
        # Volume only tells an unpublished close from a halt; without a usable
        # volume list every null close is read as before (dropped).
        volumes = result["indicators"]["quote"][0].get("volume")
        if not isinstance(volumes, list) or len(volumes) != len(stamps):
            volumes = [None] * len(stamps)
    retrieved = datetime.fromisoformat(retrieved_at)
    if retrieved.utcoffset() is None:
        raise ValueError(f"retrieval time {retrieved_at!r} has no UTC offset")
    retrieved = retrieved.astimezone(tz)
    rows, nulls, duplicates, unsettled, later, traded = [], [], 0, [], [], []
    for stamp, adj, close, volume in zip(stamps, adjusted, closes, volumes):
        day = datetime.fromtimestamp(stamp, tz).date()
        iso = day.isoformat()
        if iso < first or iso > end:
            later += [iso] if iso > end else []
            continue
        if retrieved < datetime.combine(day, time(SETTLE_HOUR), tz):
            unsettled.append(iso)
            continue
        if close is None or adj is None:
            nulls.append(iso)
            if isinstance(volume, (int, float)) and volume > 0:
                traded.append(iso)
            continue
        if not (_price(close) and _price(adj)):
            raise ValueError(f"invalid close on {iso}")
        if rows and iso <= rows[-1][0]:
            if iso == rows[-1][0] and rows[-1][1:] == [float(adj), float(close)]:
                duplicates += 1
                continue
            raise ValueError(f"duplicate or unordered session {iso}")
        rows.append([iso, float(adj), float(close)])
    pending = [iso for iso in traded if not rows or iso > rows[-1][0]]
    if pending:  # never '; ' in the text (series() joins the hosts' failures with it)
        raise UnpublishedClose(
            f"close of {max(pending)} not published (traded volume, no close, after "
            f"the last valid row {rows[-1][0] if rows else None})"
        )
    if not rows:  # never '; ' in the text: series() joins the hosts' failures with it
        seen = [
            f"dropped {len(found)} {kind} session(s): {_brief(found)}"
            for kind, found in (("null-close", nulls), ("unsettled", unsettled))
            if found
        ]
        seen += [f"next session {min(later)}"] if later else []
        raise NoSessions(
            f"no settled sessions between {first} and {end}"
            + (f" ({', '.join(seen)})" if seen else "")
        )
    splits = []
    for event in ((result.get("events") or {}).get("splits") or {}).values():
        # An undatable split rejects the original: it could not be placed against the
        # date of a share count. Ratios are kept as provided (rating checks them).
        iso = datetime.fromtimestamp(event["date"], tz).date().isoformat()
        if first <= iso <= end:
            splits.append(
                dict(
                    date=iso,
                    numerator=event.get("numerator"),
                    denominator=event.get("denominator"),
                )
            )
    notes = []
    if nulls:
        notes.append(f"dropped {len(nulls)} null-close session(s): {_brief(nulls)}")
    if duplicates:
        notes.append(f"merged {duplicates} identical duplicate row(s)")
    if unsettled:
        notes.append(
            f"dropped {len(unsettled)} unsettled session(s) (before {SETTLE_HOUR}:00"
            f" local): {_brief(unsettled)} (retrieved {retrieved_at})"
        )
    return dict(
        rows=rows,
        currency=currency,
        timezone=zone,
        splits=sorted(splits, key=itemgetter("date")),
        nullSessions=nulls,
        notes=notes,
    )


def _kept(blob: bytes, status, first, end) -> None:
    """An HTTP error body kept as an original (``fetch(keep_status=...)``; its
    manifest's ``httpStatus``) is never a series: Yahoo's HTTP 400 whose
    chart.error.description starts with NO_DATA is the answer "no session in the
    request" (raises NoSessions); any other kept body is rejected (ValueError)."""
    try:
        description = json.loads(blob)["chart"]["error"]["description"]
    except PARSE_ERRORS:
        description = None
    # never '; ' in the text: series() joins the hosts' failures with it
    shown = "no chart error description" if description is None else description
    shown = str(shown)[:200].replace(";", ",")
    if (
        status == NO_DATA_STATUS
        and isinstance(description, str)
        and description.startswith(NO_DATA)
    ):
        raise NoSessions(
            f"no settled sessions between {_iso(first)} and {_iso(end)} "
            f"(HTTP {status}: {shown})"
        )
    raise ValueError(f"HTTP {status} answer: {shown}")


def series(
    symbol: str, through, online: bool = True, *, start=None, request_through=None
) -> dict:
    """Closes from LOOKBACK_DAYS (or more) before ``through`` to ``through`` inclusive.

    ``start`` only extends the window backwards (e.g. evaluation over many months) and
    becomes part of the stored key. ``request_through`` (a later date, e.g. the date of
    the request) only extends the request: Yahoo returns the sessions after the window
    too, which ``_parse`` names ("next session ...") and drops; the window, the rows,
    the splits and the key stay those of ``through``. Failures return status "error";
    nothing is raised. Yahoo fetches keep an HTTP 400 body as an original
    (``keep_status``): a NO_DATA answer counts as a window without sessions
    (NoSessions), any other is a rejected original. ``empty`` is None unless the series
    failed and a host's original named the symbol in the expected currency without a
    settled session in the window, or was that NO_DATA answer (NoSessions): then it is
    ``{host, source, detail}`` of the last such original. Another host's original with
    sessions still makes the series ok (``empty`` None).
    """
    out = dict(
        symbol=symbol,
        status="error",
        error=None,
        rows=[],
        source=None,
        currency=None,
        timezone=None,
        window=None,
        splits=[],
        nullSessions=[],
        notes=[],
        empty=None,
    )
    try:
        first, end = _window(through, start)
        key = source_key(symbol, end, first)
        asked = end
        if request_through is not None:
            asked = max(end, date.fromisoformat(_iso(request_through)))
    except (ValueError, TypeError) as exc:
        out["error"] = f"invalid request: {exc}"
        return out
    out["window"] = {"from": first.isoformat(), "through": end.isoformat()}
    failures = []
    for host in HOSTS if online else HOSTS[:1]:
        label = host if online else "stored"
        try:
            blob, manifest = fetch(
                _url(host, symbol, first, asked),
                key,
                provider=PROVIDER,
                online=online,
                headers={"Accept": "application/json"},
                keep_status=(NO_DATA_STATUS,),
            )
        except (FetchError, OSError, HTTPException) as exc:
            failures.append(f"{label}: {exc}")
            continue
        out["source"] = manifest
        try:
            if manifest.get("httpStatus") is not None:  # a kept HTTP error body
                _kept(blob, manifest["httpStatus"], first, end)
            parsed = _parse(
                blob,
                symbol,
                first.isoformat(),
                end.isoformat(),
                manifest["retrievedAt"],
            )
        except PARSE_ERRORS as exc:
            failures.append(f"{label}: rejected original ({type(exc).__name__}: {exc})")
            if isinstance(exc, NoSessions):
                out["empty"] = dict(host=label, source=manifest, detail=str(exc))
            continue
        out.update(parsed, status="ok", empty=None)
        if failures:
            out["notes"].insert(0, f"fallback to {host} after {'; '.join(failures)}")
        return out
    out["error"] = "; ".join(failures)
    return out


def momentum_12_1(
    rows: list, as_of, *, skip: int = MOMENTUM_SKIP, lookback: int = MOMENTUM_LOOKBACK
) -> float | None:
    """adj[t-skip] / adj[t-lookback] - 1 for t = last session <= as_of, else None.

    The rating signal (rating.momentum_12_1) also requires t == as_of (D9').
    """
    t = bisect_right(rows, _iso(as_of), key=_date) - 1
    if t < lookback:
        return None
    recent, base = rows[t - skip][1], rows[t - lookback][1]
    if not (_price(recent) and _price(base)):
        return None
    return recent / base - 1


def close_on_or_before(rows: list, day) -> tuple[str, float, float] | None:
    """(date, close, adjclose) of the last session <= day."""
    i = bisect_right(rows, _iso(day), key=_date) - 1
    if i < 0:
        return None
    session, adj, close = rows[i]
    return session, close, adj


def next_session_after(rows: list, day) -> str | None:
    i = bisect_right(rows, _iso(day), key=_date)
    return rows[i][0] if i < len(rows) else None


def last_session_of_month(rows: list, year: int, month: int) -> str | None:
    """Last session in that month; final only if the series runs past month end."""
    if not (isinstance(year, int) and isinstance(month, int) and 1 <= month <= 12):
        raise ValueError(f"Invalid month {year!r}-{month!r}")
    prefix = f"{year:04d}-{month:02d}-"
    i = bisect_right(rows, prefix + "99", key=_date) - 1
    return rows[i][0] if i >= 0 and rows[i][0].startswith(prefix) else None


def returns_between(rows: list, entry_day, exit_day) -> dict:
    """Adjusted-close return from entry_day's close to exit_day's close.

    Entry requires a session on entry_day (status "missing-entry" otherwise). A missing
    exit uses the last session <= exit_day and sets exitFallback with exitReason
    "no-session" (later sessions exist) or "series-ended" (none after it: delisting or a
    series that stops before exit_day).
    """
    entry_day, exit_day = _iso(entry_day), _iso(exit_day)
    out = {
        "status": "error",
        "error": None,
        "return": None,
        "entry": None,
        "exit": None,
        "entryAdj": None,
        "exitAdj": None,
        "exitFallback": False,
        "exitReason": None,
    }
    if exit_day < entry_day:
        out["error"] = f"exit day {exit_day} precedes entry day {entry_day}"
        return out
    i = bisect_left(rows, entry_day, key=_date)
    if i == len(rows) or rows[i][0] != entry_day:
        span = f"{rows[0][0]}..{rows[-1][0]}" if rows else "empty"
        out.update(
            status="missing-entry", error=f"no session on {entry_day} (series {span})"
        )
        return out
    j = bisect_right(rows, exit_day, key=_date) - 1
    entry, exit = rows[i][1], rows[j][1]
    if not (_price(entry) and _price(exit)):
        out["error"] = "non-positive adjusted close"
        return out
    out.update(
        status="ok",
        entry=entry_day,
        exit=rows[j][0],
        entryAdj=entry,
        exitAdj=exit,
    )
    out["return"] = exit / entry - 1
    if rows[j][0] != exit_day:
        out["exitFallback"] = True
        out["exitReason"] = "series-ended" if j == len(rows) - 1 else "no-session"
    return out
