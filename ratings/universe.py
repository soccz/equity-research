"""Monthly ratings-v1 universe: S&P 500 issuers and the 200 largest KOSPI common stocks.

US members come from the SSGA SPY daily holdings, one per SEC CIK; the class with the
largest SPY weight prices the issuer and SIC/fiscal year end come from SEC submissions.
SSGA posts the holdings of T on the next US business day, so the US part is built then
(``holdingsAsOf`` must equal T_US).

KR candidates are the ``candidatePool`` largest KOSPI common stocks by Naver market value
after removing SPACs and REITs by name (``(?<!메)리츠``: 메리츠금융지주 is ranked, then
excluded as a financial holding). Naver prices after the 15:30 KRX close move with
Nextrade after-hours trades, so they never rank members: a candidate's market cap at T's
close is the sum over its listed classes of listed shares (Naver market value / price of
the same row) x the class's Yahoo close on T (ratings.prices); a class without its own
close on T uses the common close (``rankingProxy``). Members are the ``top`` largest by
that cap (``rankingBasis`` "T_close"). The ranking series are requested through the
build's Asia/Seoul date (``request_through``), so a stock listed after T shows its later
sessions. Only a halt (the common's settled series has no session on T), a confirmed
HTTP 404 for the common, or Yahoo answers for the common's symbol in KRW without a
settled session in the whole window through T (sessions after T only: listed after T;
none at all; or HTTP 400 "Data doesn't exist") leaves a candidate ``unranked``
(UNRANKED_REASONS); a failed or rejected download of the common (a symbol or currency
mismatch, an undecodable response, any other HTTP 400), a series retrieved before T's
closes settle or a class without listed shares makes the KR market an error, since a
failed download never removes a candidate. Fewer than ``top`` ranked candidates is a
market error too. OpenDART supplies corp_code, KSIC and the settlement month.
``shareClasses`` lists every listed class with the pricing class first.

Only the financial rules exclude a member (docs/ratings-v1.md section 2). A per-company
profile failure (no CIK in company_tickers, SEC submissions or OpenDART corp_code /
company.json unavailable or mismatched, SIC/KSIC missing or unmapped) keeps the member
eligible with ``issues == ["universe_fetch_error"]`` and ``fetchError`` naming the step,
so it stays in the denominator and is scored insufficient. A failed source, an incomplete
Naver ranking, an OpenDART key or quota status, or universe_fetch_error on more than
FETCH_ERROR_LIMIT of a market's non-financial (eligible) members makes that market an
error: rebuild.

Each market is saved as its own part, data/ratings/universe/<T>/<market>.json (``save``),
and ``merge`` combines a month's parts into data/ratings/universe/<asOf>.json (asOf = the
later market T). ``markets[m]`` carries that market's facts for the registration check
(D5'): builtAt / completedAt (UTC, its own build), online, capturedAt ``{first, last}``
(retrievals of the inputs that fix membership: the SPY holdings file; the Naver ranking
pages and the candidates' price series), rulesHash, US holdingsAsOf, KR rankingBasis
and rankingCapturedAt (= capturedAt). The month file is ``registry.merge_universe`` of
the parts, the same merge ``scripts/ratings.py universe-merge`` writes. The
computability-check (gate) universe keeps its own stem, <T>-gate/ and <asOf>-gate.json
(``gate=True``), as smoke builds keep <T>-limit<N>/, so the gate universe and the
month's universe never merge, replace or remove each other's files.
"""

from __future__ import annotations

import calendar
from collections import Counter
from datetime import date, datetime, timezone
from fractions import Fraction
import io
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
import zipfile
import zlib
from zoneinfo import ZoneInfo

from equitylab.dart import request as dart_request
from equitylab.data import canonical, digest
from ratings import prices, sectors
from ratings.common import (
    MARKETS,
    PROTOCOL_VERSION,
    RATINGS,
    FetchError,
    ensure_dart_key,
    fetch,
    fetch_json,
    latest,
    sec_user_agent,
    store,
    write_json,
)

SPY_URL = (
    "https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/"
    "etfs/us/holdings-daily-us-en-spy.xlsx"
)
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
NAVER_URL = (
    "https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page={page}&pageSize={size}"
)
DART_URL = "https://opendart.fss.or.kr/api/"
UNIVERSE_DIR = RATINGS / "universe"
NAVER_PAGE_SIZE = 100
NAVER_MAX_PAGES = 60
SPY_MIN_WEIGHT = 95.0  # equity rows must cover this percent of SPY net assets
DART_RETRY_PAUSE = 1.0
# company.json statuses: 000 data, 013 no data, 100 bad field value are answers about the
# company (stored); key, IP, quota and maintenance statuses fail the market; any other
# status (900 undefined error, ...) is that member's universe_fetch_error.
DART_ANSWERS = ("000", "013", "100")
DART_SYSTEMIC = ("010", "011", "012", "020", "021", "800", "901")
XLSX_MAX_BYTES = 50_000_000
FETCH_ERROR = "universe_fetch_error"
FETCH_ERROR_LIMIT = (
    0.05  # share of non-financial members; above it the market is an error
)
T_CLOSE, NAVER_VALUE = "T_close", "naver_value"
# The computability-check (gate) universe is saved apart: <T>-gate/, <asOf>-gate.json.
GATE_SUFFIX = "-gate"
# The only reasons a KR candidate is left unranked (M3, N1, M1): a series retrieved
# after T's closes settled has no session on T (a halt), every Yahoo host answers HTTP
# 404 for the symbol, or every host answers, after T's closes settled, with a chart of
# the symbol in KRW without a settled session in the whole window through T (sessions
# after T only, as the request runs through the build's date; or none) or with HTTP 400
# "Data doesn't exist" (or 404). Any other failure to price the common makes the KR
# market an error.
HALTED, NOT_FOUND = "no_close_on_as_of", "symbol_not_found"
NOT_LISTED = "not_listed_on_as_of"
UNRANKED_REASONS = (HALTED, NOT_FOUND, NOT_LISTED)
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
# Malformed source data: bad JSON/numbers, missing fields, unexpected shapes, archives
# (including a damaged or truncated deflate stream), XML.
DATA_ERRORS = (
    ValueError,
    LookupError,
    TypeError,
    AttributeError,
    EOFError,
    zlib.error,
    zipfile.BadZipFile,
    ET.ParseError,
)

RULES = dict(
    US=dict(
        source="SSGA SPY daily holdings",
        equityTicker=r"[A-Z]{1,5}(\.[A-Z]{1,2})?",
        issuer="SEC CIK via company_tickers.json (BRK.B -> BRK-B); one member per CIK, "
        "priced by the class with the largest SPY weight",
        holdings="holdingsAsOf (the file's 'As of' date) must equal T_US; SSGA posts "
        "the holdings of T on the next US business day",
        financialSic=list(sectors.FINANCIAL_SIC),
        sectors="Fama-French 12 from Siccodes12; SIC outside every range = Other",
        ff12Outage="when Siccodes12 cannot be fetched (offline: when the latest stored "
        "original cannot be read), a stored original whose parsed definition hashes "
        "to the pin is used (issue ff12_stored_original; ff12Fallback records the "
        "error); without one the US market is an error",
        ff12Changed="when the downloaded Siccodes12 does not parse to the pinned "
        "definition (Ken French published a changed one) or does not parse at all, "
        "the stored original with the pinned definition is used: issue "
        "ff12_definition_changed_pinned_used, ff12Changed records the download; only "
        "without such an original does a changed definition stand (issue "
        "ff12_definition_changed, ff12Hash off the pin, refused by the registry) and "
        "an unparsable download make the US market an error",
        ff12Pinned="the stored original with the pinned definition is the one kept "
        "under its own pointer (ken-french-siccodes12-pinned), else the latest "
        "stored, else any stored ken-french-siccodes12-*.zip whose content matches its "
        "name and whose parsed definition hashes to the pin",
    ),
    KR=dict(
        source="Naver KOSPI market-value ranking (candidates, listed shares); Yahoo "
        "daily closes via ratings.prices (market cap at T's close)",
        top=200,
        candidatePool=260,
        rankingBasis=T_CLOSE,
        commonType="stock",
        commonCode=r"[0-9A-Z]{5}0",
        # Regular expressions searched in the Naver stock name before ranking.
        excludeNamePatterns={"spac": "스팩", "reit": "(?<!메)리츠"},
        candidates="the candidatePool largest commons by Naver market value at the "
        "capture, after the name filters",
        ranking="market cap at T's close = sum over the candidate's listed classes of "
        "listedShares x that class's close on T (prices.series with its window through "
        "T, requested through the build's Asia/Seoul date: request_through, not T+2; "
        "close_on_or_before); a preferred class without its own close on T (no "
        "session on T, or a series that failed for any reason but close_unsettled) "
        "uses the common close (rankingProxy, issue class_price_proxy); members are "
        "the top candidates by that cap, ties by code; fewer than top ranked "
        "candidates is a market error",
        unranked="only unrankedReasons leave a candidate unranked (unranked, issue "
        f"candidate_unranked; never a stale close): {HALTED} (its common's series, "
        "retrieved after T's closes settled, has no session on T: a halt), "
        f"{NOT_FOUND} (every Yahoo host answers HTTP 404 for its common) and "
        f"{NOT_LISTED} (every Yahoo host answers the request for its common's symbol, "
        "retrieved after T's closes settled, with a chart in KRW without a settled "
        f"session from {prices.LOOKBACK_DAYS} days before T through T: sessions after "
        f"T only (listed after T) or none (halted throughout); with HTTP "
        f"{prices.NO_DATA_STATUS} whose chart error description starts with "
        f"{prices.NO_DATA!r} (no session in the request: kept as the original, "
        "prices.NO_DATA); or with HTTP 404, provided at least one host answers "
        "without sessions as above); any other failure to price the common (a "
        "transient download failure, a rejected original: a symbol or currency "
        f"mismatch, an undecodable response, any other HTTP {prices.NO_DATA_STATUS}), "
        "a class without listed shares or a class priced from a series "
        "retrieved before T's closes settled makes the market an error (rebuild): a "
        "failed download never removes a candidate",
        unrankedReasons=list(UNRANKED_REASONS),
        capture="every ranking input (Naver pages, candidates' price series) is "
        "retrieved after T's close (timing.marketClose), else the market is an error; "
        "a price series must also be retrieved after T's closes settle "
        "(prices.SETTLE_HOUR local time), else the market is an error (close_unsettled, "
        f"never {HALTED} or {NOT_LISTED}); no Naver marketStatus requirement",
        naverPages="every page up to totalCount, none empty, totalCount unchanged and "
        "rows == totalCount; otherwise the market is an error",
        preferred="same first five code characters, last character not 0, "
        "name starting with the common name",
        listedShares="marketValueRaw (KRW) / closePriceRaw of the same Naver row",
        smoke="a limited build takes the limit largest commons by Naver market value "
        f"(rankingBasis {NAVER_VALUE}) without prices and is never registered",
        dartStatuses="company.json status 000 is used; 010, 011, 012, 020, 021, 800 and "
        "901 (key, IP, quota, maintenance) make the market an error; any other status "
        "is the member's universe_fetch_error; only 000, 013 and 100 are stored",
        financialKsic=list(sectors.FINANCIAL_KSIC),
        keptKsic=list(sectors.KEPT_KSIC),
        financialHoldingName=sectors.FINANCIAL_HOLDING_MARK,
        sectors="data/ratings/reference/ksic-ff12.json (SHA-256 in sources)",
    ),
    members=dict(
        excludedBy="financial rules only (US financialSic; KR financialKsic and "
        "64992 with financialHoldingName)",
        fetchError=f"{FETCH_ERROR}: a member whose CIK, SEC submissions, OpenDART "
        "corp_code/company.json or SIC/KSIC is unavailable, mismatched or unmapped "
        "stays eligible (fetchError names the step) and is scored insufficient",
        fetchErrorLimit=FETCH_ERROR_LIMIT,
        fetchErrorRule="market error when members with the issue / non-financial "
        "(eligible) members > fetchErrorLimit",
    ),
    timing=dict(
        marketClose={"US": "16:00", "KR": "15:30"},
        timezones={"US": "America/New_York", "KR": "Asia/Seoul"},
        US="holdingsAsOf = SPY 'As of' date; capturedAt = {first, last} = "
        "holdingsRetrievedAt",
        KR="rankingBasis; capturedAt = rankingCapturedAt = {first, last} retrieval of "
        "the ranking inputs (rankingRetrievedAt: Naver pages; closesRetrievedAt: the "
        "candidates' price series); marketStatus and pricedAt are informational",
        build="each market records builtAt (UTC start of its build), completedAt, "
        "online and rulesHash; the registry checks each market's timing from them and "
        "refuses, for a registration or a coverage gate, a market whose part was not "
        "built online (online true; universe --offline replays stored originals)",
        issues="holdings_date (US) against T; ranking_captured_before_close (KR smoke "
        "build; a full KR build fails instead); ff12_stored_original (US, R12); "
        "ff12_definition_changed_pinned_used (US)",
    ),
    files=dict(
        part="data/ratings/universe/<T>/<market>.json, one per market and T, never "
        "silently replaced",
        merged="data/ratings/universe/<asOf>.json = registry.merge_universe of the "
        "month's parts (asOf = the later T; a market without a part at that date uses "
        "its only part of the month), rewritten only when a part changes; an earlier "
        "merge of the month is removed only when every market it holds has the same T "
        "in the new merge",
        gate=f"the computability-check universe: parts in <T>{GATE_SUFFIX}/, merged "
        f"into <asOf>{GATE_SUFFIX}.json; never the month's universe, and neither ever "
        "merges, replaces or removes the other's files",
        smoke="parts in <T>-limit<N>/, merged into <asOf>-limit<N>.json; never the "
        "month's universe",
        saveFailure="parts written but the month not merged: reported as part saved, "
        "month not merged (MonthNotMerged), never as not saved",
    ),
)


def build(
    as_of, online: bool = True, markets=MARKETS, limit: int | None = None
) -> dict:
    """Universe for ``as_of``; ``markets`` limits the build to some markets.

    ``as_of`` is YYYY-MM-DD, or ``{market: YYYY-MM-DD}`` when the markets' last sessions
    of the month differ (each market is checked against its own date; ``asOf`` is the
    later one). Every market records its own builtAt, completedAt, capture times,
    rulesHash and sources (``markets[m]``); ``save`` keeps each market as a part.
    ``limit`` is for smoke runs only: just the ``limit`` largest issuers of each market
    (SPY weight, KOSPI market value) are profiled. The result records ``limit``, is
    saved apart from the month's universe and is never registered.
    """
    if not markets or set(markets) - set(MARKETS):
        raise ValueError(f"markets must be a subset of {MARKETS}")
    days = _days(as_of, markets)
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer")
    rules = json.loads(json.dumps(RULES))
    rules_hash = digest(canonical(rules))
    universe = dict(
        version=PROTOCOL_VERSION,
        asOf=max(days.values()),
        asOfByMarket=days,
        builtAt=_now(),
        completedAt=None,
        online=online,
        status="ok",
        rules=rules,
        rulesHash=rules_hash,
        markets={},
        sources=[],
        members=[],
    )
    if limit is not None:
        universe["limit"] = limit
    for market in days:
        started, sources = _now(), []
        try:
            members, info = (_us if market == "US" else _kr)(
                days[market], online, sources, limit
            )
        except (FetchError, *DATA_ERRORS) as exc:
            members, info = [], dict(
                status="error", error=f"{type(exc).__name__}: {exc}"
            )
        own = _unique(sources)
        info = dict(
            asOf=days[market],
            builtAt=started,
            completedAt=_now(),
            online=online,
            rulesHash=rules_hash,
            **info,
            sources=own,
        )
        if info["status"] != "ok":
            universe["status"] = "error"
        universe["markets"][market] = info
        universe["members"].extend(members)
        universe["sources"] = _unique(universe["sources"] + own)
    universe["completedAt"] = _now()
    return universe


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _local_date(market: str) -> str:
    """The market-local date now (timing.timezones): the build's date in ``market``."""
    zone = ZoneInfo(RULES["timing"]["timezones"][market])
    return datetime.now(timezone.utc).astimezone(zone).date().isoformat()


def _iso(value) -> str:
    return date.fromisoformat(str(value)).isoformat()


def _moment(text) -> datetime | None:
    """An ISO timestamp with a UTC offset, else None."""
    try:
        moment = datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return moment if moment.utcoffset() is not None else None


def _span(times: list) -> tuple[str, str]:
    """(first, last) of ISO retrieval timestamps, compared as instants."""
    stamps = []
    for text in times:
        moment = _moment(text)
        if moment is None:
            raise FetchError(f"retrieval time {text!r} unknown; capture not placeable")
        stamps.append((moment, str(text)))
    if not stamps:
        raise FetchError("no retrieval time recorded; capture not placeable")
    return min(stamps)[1], max(stamps)[1]


def market_close(market: str, day) -> datetime:
    """The regular close of ``day`` in ``market`` (RULES timing.marketClose)."""
    clock = RULES["timing"]["marketClose"][market]
    zone = ZoneInfo(RULES["timing"]["timezones"][market])
    return datetime.fromisoformat(f"{_iso(day)}T{clock}").replace(tzinfo=zone)


def _unique(manifests: list) -> list:
    seen, out = set(), []
    for manifest in manifests:
        key = canonical(manifest)
        if key not in seen:
            seen.add(key)
            out.append(manifest)
    return out


def _days(as_of, markets) -> dict:
    """``{market: YYYY-MM-DD}`` in MARKETS order; per-market dates share one month."""
    chosen = [m for m in MARKETS if m in markets]
    if isinstance(as_of, dict):
        missing = [m for m in chosen if not as_of.get(m)]
        if missing:
            raise ValueError(f"as_of lacks a date for {missing}")
        days = {m: _iso(as_of[m]) for m in chosen}
        if len({day[:7] for day in days.values()}) != 1:
            raise ValueError("per-market as_of dates must fall in one month")
        return days
    day = date.fromisoformat(as_of).isoformat()
    return {m: day for m in chosen}


# --- files: one part per market, merged per month ------------------------------------


class MonthNotMerged(ValueError):
    """``save`` wrote the parts but could not merge the month: part saved, month not
    merged. ``parts`` = {market: Path} of the parts written, ``error`` = the merge's
    exception; ``str()`` is the whole message. Rerun the merge (``merge``, CLI
    universe-merge) once the cause is fixed; the parts need no rebuild."""

    def __init__(self, parts: dict, error: Exception):
        self.parts, self.error = dict(parts), error
        names = ", ".join(
            path.relative_to(UNIVERSE_DIR).as_posix() for path in self.parts.values()
        )
        noun = "part" if len(self.parts) == 1 else "parts"
        super().__init__(f"{noun} {names} saved, month not merged: {error}")


def _suffix(limit=None, gate=False) -> str:
    return (GATE_SUFFIX if gate else "") + (f"-limit{int(limit)}" if limit else "")


def _stem(day, limit=None, gate=False) -> str:
    """Folder of a market's part and stem of the merged file: <T>, <T>-gate for the
    computability-check (gate) universe, -limit<N> appended for a smoke build."""
    return _iso(day) + _suffix(limit, gate)


def _of_month(month: str, limit=None, gate=False) -> re.Pattern:
    """Stems of the part folders and merged files of one month and one kind (the month's
    universe, the gate universe or a smoke build; never another kind)."""
    return re.compile(re.escape(month) + r"-\d{2}" + re.escape(_suffix(limit, gate)))


def part_path(market: str, day, limit=None, gate=False) -> Path:
    """data/ratings/universe/<T>/<market>.json; <T>-gate/ for the gate universe and
    <T>-limit<N>/ (<T>-gate-limit<N>/) for a smoke build."""
    if market not in MARKETS:
        raise ValueError(f"Unknown market {market!r}")
    return UNIVERSE_DIR / _stem(day, limit, gate) / f"{market}.json"


def merged_path(as_of, limit=None, gate=False) -> Path:
    """data/ratings/universe/<asOf>.json, the merged month (<asOf>-gate.json for the gate
    universe, -limit<N> appended for a smoke build)."""
    return UNIVERSE_DIR / f"{_stem(as_of, limit, gate)}.json"


def parts(universe: dict) -> dict:
    """``{market: part}``: each market of a build as a build of its own (its asOf,
    builtAt, completedAt, sources and members), as ``scripts/ratings.py universe``
    saves it. A build without per-market fields (older files) gives every part the
    build-wide values and sources."""
    out = {}
    by_market = universe.get("asOfByMarket") or {}
    for market, info in (universe.get("markets") or {}).items():
        day = _iso(info.get("asOf") or by_market.get(market) or universe["asOf"])
        info = dict(info, asOf=day)
        for key in ("builtAt", "completedAt", "rulesHash", "online"):
            if info.get(key) is None and universe.get(key) is not None:
                info[key] = universe[key]
        if "sources" not in info:
            info["sources"] = list(universe.get("sources") or [])
        out[market] = dict(
            universe,
            asOf=day,
            asOfByMarket={market: day},
            builtAt=info.get("builtAt"),
            completedAt=info.get("completedAt"),
            status="ok" if info.get("status", "ok") == "ok" else "error",
            markets={market: info},
            sources=info["sources"],
            members=[
                m for m in universe.get("members") or [] if m.get("market") == market
            ],
        )
    return out


def save(universe: dict, overwrite: bool = False, gate: bool = False) -> Path:
    """Save each market of a build as its part and merge the month (``merge``); returns
    the merged file (``merged_path``). ``gate`` saves the computability-check universe
    under its own stem (parts in <T>-gate/, merged into <asOf>-gate.json), apart from
    the month's universe; a smoke build (``limit``) stays in <T>-limit<N>/. A part is
    never silently replaced: ``overwrite`` replaces only the parts of this build's
    markets, and a differing part is refused before anything is written. When the
    parts are written but the month cannot be merged, MonthNotMerged (a ValueError)
    says so: part saved, month not merged."""
    if universe.get("status") != "ok":
        raise ValueError(
            "Universe has a market error; rebuild or limit markets before saving"
        )
    split, limit = parts(universe), universe.get("limit")
    if not split:
        raise ValueError("Universe has no market to save")
    targets = {m: part_path(m, part["asOf"], limit, gate) for m, part in split.items()}
    for market, path in targets.items():  # refuse before writing anything
        if path.exists() and not overwrite:
            if canonical(json.loads(path.read_text())) != canonical(split[market]):
                name = path.relative_to(UNIVERSE_DIR).as_posix()
                raise FileExistsError(f"{name} exists with different content")
    for market, path in targets.items():
        write_json(path, split[market])
    days = {m: part["asOf"] for m, part in split.items()}
    try:
        return merge(days, limit=limit, gate=gate)
    except Exception as exc:  # the parts are written whatever stopped the merge
        raise MonthNotMerged(targets, exc) from exc


def merge(as_of, overwrite: bool = False, limit=None, gate: bool = False) -> Path:
    """Merge the month's parts into data/ratings/universe/<asOf>.json; returns its path.

    ``as_of`` is YYYY-MM-DD or ``{market: YYYY-MM-DD}``. A market named in a dict uses
    its part of that date (FileNotFoundError if absent). Otherwise a market uses its part
    of the given date, else its only part in that month (several are ambiguous); a market
    without a part is left out. ``gate`` merges the gate universe's parts into
    <asOf>-gate.json and ``limit`` a smoke build's; each kind only ever sees its own
    parts and files. The content is ``registry.merge_universe`` (the one merge: each
    market keeps its own build and capture times, ``part`` = the part file and its
    SHA-256). The file is rewritten only when the parts changed; a file that is not a
    merge is replaced only with ``overwrite``. An earlier merge of the same kind and
    month is removed only when every market it holds has the same T in this merge
    (December: 12-30.json, KR of 12-30 alone, goes once 12-31.json holds that KR part
    and the US part of 12-31); a merge holding a market of another T is never removed.
    """
    from ratings import registry  # imports this module; one merge for CLI and save()

    days = _part_days(as_of, limit, gate)
    if not days:
        raise FileNotFoundError(f"No universe part for {as_of}")
    chosen, files = {}, {}
    for market, day in days.items():
        path = part_path(market, day, limit, gate)
        blob = path.read_bytes()
        chosen[market] = json.loads(blob)
        relative = path.relative_to(UNIVERSE_DIR).as_posix()
        files[market] = dict(
            file=f"data/ratings/universe/{relative}", sha256=digest(blob)
        )
    merged = registry.merge_universe(chosen, files=files)
    path = merged_path(merged["asOf"], limit, gate)
    if path.exists():
        existing = json.loads(path.read_text())
        if _merged(existing) and _content(existing) == _content(merged):
            return path  # same parts: keep the file and its mergedAt
        if not overwrite and not _merged(existing):
            raise FileExistsError(
                f"{path.name} exists with different content and is not a merge of parts"
            )
    write_json(path, merged)
    month = _of_month(merged["asOf"][:7], limit, gate)
    for other in sorted(UNIVERSE_DIR.glob(f"{merged['asOf'][:7]}-*.json")):
        if other == path or not month.fullmatch(other.stem):
            continue
        try:
            content = json.loads(other.read_text())
        except ValueError:
            continue
        if _superseded(content, merged):
            other.unlink()  # its parts, each of the same T, are merged into ``path``
    return path


def _merged(content) -> bool:
    """A file written by a merge (registry.merge_universe stamps mergedAt)."""
    return (
        isinstance(content, dict)
        and "mergedAt" in content
        and isinstance(content.get("markets"), dict)
    )


def _merged_days(content: dict) -> dict:
    """``{market: T}`` of a merged file (asOfByMarket, else each market's asOf)."""
    by_market = content.get("asOfByMarket") or {}
    return {
        market: _iso(by_market.get(market) or (info or {}).get("asOf"))
        for market, info in content["markets"].items()
    }


def _superseded(content, merged: dict) -> bool:
    """An earlier merge whose every market has the same T in ``merged``."""
    if not _merged(content):
        return False
    try:
        old, new = _merged_days(content), _merged_days(merged)
    except (AttributeError, TypeError, ValueError):
        return False  # unreadable dates: never remove what cannot be compared
    return bool(old) and all(new.get(market) == day for market, day in old.items())


def _content(merged: dict) -> bytes:
    return canonical({k: v for k, v in merged.items() if k != "mergedAt"})


def _part_days(as_of, limit=None, gate=False) -> dict:
    """``{market: T}`` of the parts to merge (see ``merge``)."""
    if isinstance(as_of, dict):
        if set(as_of) - set(MARKETS):
            raise ValueError(f"as_of keys must be markets of {MARKETS}")
        given = {m: _iso(as_of[m]) for m in MARKETS if as_of.get(m)}
        if not given:
            raise ValueError("as_of names no market")
    else:
        given = {m: _iso(as_of) for m in MARKETS}
    months = {day[:7] for day in given.values()}
    if len(months) != 1:
        raise ValueError("per-market as_of dates must fall in one month")
    month = months.pop()
    folder = _of_month(month, limit, gate)
    kind = f" (<T>{_suffix(limit, gate)}/)" if _suffix(limit, gate) else ""
    days = {}
    for market in MARKETS:
        day = given.get(market)
        if day and part_path(market, day, limit, gate).exists():
            days[market] = day
            continue
        if day and isinstance(as_of, dict):
            raise FileNotFoundError(f"No {market} universe part for {day}{kind}")
        found = sorted(
            path.parent.name[:10]
            for path in UNIVERSE_DIR.glob(f"{month}-*/{market}.json")
            if folder.fullmatch(path.parent.name)
        )
        if len(found) > 1:
            raise ValueError(
                f"Several {market} universe parts in {month}{kind} "
                f"({', '.join(found)}); merge with {{'{market}': <T>}}"
            )
        if found:
            days[market] = found[0]
    return days


# --- membership --------------------------------------------------------------------


def _issue(code: str, detail: str) -> dict:
    return dict(issue=code, detail=detail)


def _exclude(member: dict, reason: str, error=None) -> dict:
    """Financial exclusion (the only rule that removes a member from eligibility)."""
    member.update(
        status="excluded", reason=reason, error=None if error is None else str(error)
    )
    return member


def _fetch_error(member: dict, step: str, error=None) -> dict:
    """A profile step failed: the member stays eligible and is scored insufficient."""
    if FETCH_ERROR not in member["issues"]:
        member["issues"].append(FETCH_ERROR)
    member.update(fetchError=step, error=None if error is None else str(error))
    return member


def _counts(members: list) -> dict:
    """Eligible = non-financial members, the denominator of every rate."""
    excluded = Counter(m["reason"] for m in members if m["status"] == "excluded")
    eligible = [m for m in members if m["status"] == "eligible"]
    failed = Counter(m["fetchError"] for m in eligible if FETCH_ERROR in m["issues"])
    rate = sum(failed.values()) / len(eligible) if eligible else None
    return dict(
        members=len(members),
        eligible=len(eligible),
        excluded=dict(sorted(excluded.items())),
        fetchErrors=dict(sorted(failed.items())),
        fetchErrorRate=None if rate is None else round(rate, 6),
    )


def _market(members: list, info: dict) -> tuple[list, dict]:
    """Counts, the Money check and the fetch-error limit of one market's build."""
    counts = _counts(members)
    info.update(counts=counts, fetchErrorLimit=FETCH_ERROR_LIMIT)
    info["issues"] = info.get("issues", []) + _money_issue(members)
    failed, eligible = sum(counts["fetchErrors"].values()), counts["eligible"]
    # Exact comparison: 10 of 200 is at the limit, 11 of 200 is above it.
    if eligible and Fraction(failed, eligible) > Fraction(str(FETCH_ERROR_LIMIT)):
        info.update(
            status="error",
            error=f"{failed} of {eligible} non-financial members have {FETCH_ERROR} "
            f"({failed / eligible:.1%} > {FETCH_ERROR_LIMIT:.0%}); rebuild",
        )
    return members, info


def _money_issue(members: list) -> list:
    money = [
        m["id"] for m in members if m["status"] == "eligible" and m["sector"] == "Money"
    ]
    return [_issue("money_not_empty", ", ".join(money))] if money else []


# --- United States ------------------------------------------------------------------


def _column(ref: str) -> int:
    index = 0
    for char in re.match(r"[A-Z]+", ref)[0]:
        index = index * 26 + ord(char) - 64
    return index - 1


def xlsx_rows(blob: bytes) -> list[list]:
    """Cell text of the first worksheet as dense rows (shared and inline strings resolved)."""
    with zipfile.ZipFile(io.BytesIO(blob)) as book:
        if sum(e.file_size for e in book.infolist()) > XLSX_MAX_BYTES:
            raise ValueError("xlsx expands beyond the size limit")
        names = book.namelist()
        strings = []
        if "xl/sharedStrings.xml" in names:
            table = ET.fromstring(book.read("xl/sharedStrings.xml"))
            strings = [
                "".join(
                    t.text or ""
                    for t in si.findall(f"{NS}t") + si.findall(f"{NS}r/{NS}t")
                )
                for si in table.findall(f"{NS}si")
            ]
        sheets = sorted(
            n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)
        )
        if not sheets:
            raise ValueError("xlsx has no worksheet")
        first = "xl/worksheets/sheet1.xml"
        sheet = ET.fromstring(book.read(first if first in sheets else sheets[0]))
    rows = []
    for row in sheet.iter(f"{NS}row"):
        cells, position = {}, -1
        for cell in row.findall(f"{NS}c"):
            position = _column(cell.get("r")) if cell.get("r") else position + 1
            kind, value = cell.get("t"), cell.find(f"{NS}v")
            if kind == "inlineStr":
                cells[position] = "".join(t.text or "" for t in cell.iter(f"{NS}t"))
            elif value is not None:
                cells[position] = (
                    strings[int(value.text)] if kind == "s" else value.text
                )
        rows.append([cells.get(i) for i in range(max(cells, default=-1) + 1)])
    return rows


def _number(text) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def spy_holdings(blob: bytes) -> dict:
    """``{asOf, equities, skipped, equityWeight}``; rows without an equity ticker are skipped."""
    rows = xlsx_rows(blob)
    held_at, columns, start = None, None, None
    for index, row in enumerate(rows):
        cells = ["" if c is None else str(c).strip() for c in row]
        dated = re.search(r"As of (\d{1,2})-([A-Za-z]{3})-(\d{4})", " ".join(cells))
        if dated and held_at is None and dated[2].title() in MONTHS:
            month = MONTHS.index(dated[2].title()) + 1
            held_at = date(int(dated[3]), month, int(dated[1])).isoformat()
        if {"Name", "Ticker", "Weight"} <= set(cells):
            columns = {name: cells.index(name) for name in cells if name}
            start = index + 1
            break
    if columns is None:
        raise ValueError("SPY holdings header row (Name/Ticker/Weight) not found")
    if held_at is None:
        raise ValueError("SPY holdings date ('As of DD-Mon-YYYY') not found")

    def cell(row, name):
        at = columns.get(name)
        value = row[at] if at is not None and at < len(row) else None
        return "" if value is None else str(value).strip()

    equity = re.compile(RULES["US"]["equityTicker"])
    equities, skipped = [], []
    for row in rows[start:]:
        name, weight = cell(row, "Name"), _number(cell(row, "Weight"))
        if not name or weight is None:
            continue
        ticker = cell(row, "Ticker")
        identifier = cell(row, "Identifier") or None
        item = dict(name=name, ticker=ticker, identifier=identifier, weight=weight)
        (equities if equity.fullmatch(ticker) else skipped).append(item)
    total = round(sum(h["weight"] for h in equities), 6)
    if total < SPY_MIN_WEIGHT:
        raise ValueError(
            f"SPY equity rows cover {total}% (expected percent units near 100)"
        )
    if len({h["ticker"] for h in equities}) != len(equities):
        raise ValueError("SPY holdings repeat a ticker")
    return dict(asOf=held_at, equities=equities, skipped=skipped, equityWeight=total)


def _us_member(cik: str | None, name: str, holdings: list) -> dict:
    holdings = sorted(holdings, key=lambda h: (-h["weight"], h["ticker"]))
    symbol = holdings[0]["ticker"].replace(".", "-")
    return dict(
        id=f"US:{cik or symbol}",
        market="US",
        name=name,
        ticker=holdings[0]["ticker"],
        priceSymbol=symbol,
        cik=cik,
        sic=None,
        sicDescription=None,
        sector=None,
        fiscalYearEnd=None,
        shareClasses=[
            dict(
                ticker=h["ticker"],
                priceSymbol=h["ticker"].replace(".", "-"),
                kind="common",
                weight=h["weight"],
            )
            for h in holdings
        ],
        weight=round(sum(h["weight"] for h in holdings), 6),
        rank=None,
        status="eligible",
        reason=None,
        issues=[],
        fetchError=None,
        error=None,
    )


def _sec_profile(member, industries, online, headers, sources) -> dict:
    cik = member["cik"]
    try:
        profile, manifest = fetch_json(
            SEC_SUBMISSIONS_URL.format(cik=cik),
            f"sec-submissions-{cik}",
            provider="SEC",
            online=online,
            headers=headers,
        )
    except (FetchError, ValueError) as exc:
        return _fetch_error(member, "submissions_unavailable", exc)
    sources.append(manifest)
    if not isinstance(profile, dict):
        return _fetch_error(member, "submissions_unavailable", "not a JSON object")
    if str(profile.get("cik", "")).lstrip("0") != cik.lstrip("0"):
        detail = f"CIK {profile.get('cik')!r}"
        return _fetch_error(member, "submissions_mismatch", detail)
    member.update(
        name=profile.get("name") or member["name"],
        fiscalYearEnd=profile.get("fiscalYearEnd") or None,
    )
    sic = str(profile.get("sic") or "").strip()
    if not re.fullmatch(r"\d{3,4}", sic):
        return _fetch_error(member, "missing_sic", f"SIC {sic!r}" if sic else None)
    member.update(
        sic=sic.zfill(4),
        sicDescription=profile.get("sicDescription") or None,
        sector=sectors.sic_sector(int(sic), industries),
    )
    if sectors.financial_sic(int(sic)):
        return _exclude(member, "financial_sic")
    return member


def _us(as_of: str, online: bool, sources: list, limit=None) -> tuple[list, dict]:
    blob, manifest = fetch(
        SPY_URL, "ssga-spy-holdings", provider="SSGA", online=online, suffix=".xlsx"
    )
    sources.append(manifest)
    holdings_retrieved = manifest.get("retrievedAt")
    spy = spy_holdings(blob)
    headers = {"User-Agent": sec_user_agent()} if online else None
    tickers, manifest = fetch_json(
        SEC_TICKERS_URL,
        "sec-company-tickers",
        provider="SEC",
        online=online,
        headers=headers,
    )
    sources.append(manifest)
    by_ticker = {str(row["ticker"]).upper(): row for row in tickers.values()}
    industries, manifest = sectors.load_ff12(online)
    sources.append(manifest)
    issues = []
    if spy["asOf"] != as_of:
        issues.append(_issue("holdings_date", f"SPY holdings as of {spy['asOf']}"))
    if sectors.ff12_hash(industries) != sectors.FF12_DEFINITION_SHA256:
        detail = "Siccodes12 differs from the pin; no stored original has the pin"
        issues.append(_issue("ff12_definition_changed", detail))
    changed = manifest.get("changed")
    # The pinned original by its retrieval, or by its file when found without a
    # pointer (sectors._stored_pinned: N4).
    kept = manifest.get("retrievedAt") or manifest.get("file")
    if changed:  # L5: Ken French changed the file; the pinned definition is kept
        found = changed.get("definitionSha256") or changed.get("error")
        read = "downloaded" if online else "stored"  # L7: offline reads the latest
        detail = (
            f"{read} Siccodes12 {str(changed.get('sha256'))[:16]} (retrieved "
            f"{changed.get('retrievedAt')}) gives {found}; the stored original of "
            f"{kept} with the pinned definition is used"
        )
        issues.append(_issue("ff12_definition_changed_pinned_used", detail))
    if manifest.get("fallback"):
        detail = f"pinned original of {kept} after: "
        issues.append(_issue("ff12_stored_original", detail + manifest["fallback"]))
    issuers = {}  # one group per CIK; a ticker without a CIK is its own issuer
    for holding in spy["equities"]:
        hit = by_ticker.get(holding["ticker"].replace(".", "-"))
        key = f"{int(hit['cik_str']):010d}" if hit else None
        title = hit["title"] if hit else holding["name"]
        group = issuers.setdefault(key or holding["ticker"], dict(cik=key, title=title))
        group.setdefault("rows", []).append(holding)
    members = [_us_member(g["cik"], g["title"], g["rows"]) for g in issuers.values()]
    members.sort(key=lambda m: (-m["weight"], m["id"]))
    if limit is not None:  # smoke runs profile only the largest issuers
        del members[limit:]
    for member in members:
        if member["cik"] is None:
            detail = f"{member['ticker']} is not in SEC company_tickers"
            _fetch_error(member, "missing_cik", detail)
        else:
            _sec_profile(member, industries, online, headers, sources)
    for rank, member in enumerate(members, 1):
        member["rank"] = rank
    info = dict(
        status="ok",
        error=None,
        holdingsAsOf=spy["asOf"],
        holdingsRetrievedAt=holdings_retrieved,
        capturedAt=dict(first=holdings_retrieved, last=holdings_retrieved),
        equityRows=len(spy["equities"]),
        equityWeight=spy["equityWeight"],
        skipped=spy["skipped"],
        ff12Hash=sectors.ff12_hash(industries),
        ff12Fallback=manifest.get("fallback"),
        ff12Changed=changed,
        issues=issues,
    )
    return _market(members, info)


# --- Korea --------------------------------------------------------------------------


def _naver_row(item: dict) -> dict:
    row = dict(
        code=str(item["itemCode"]).strip().upper(),
        name=str(item["stockName"]).strip(),
        type=item.get("stockEndType"),
    )
    if row["type"] == "stock":
        try:
            close, value = int(item["closePriceRaw"]), int(item["marketValueRaw"])
            shown = int(str(item["marketValue"]).replace(",", ""))
        except (KeyError, TypeError, ValueError):
            raise FetchError(
                f"Naver row {row['code']} lacks a numeric price or value"
            ) from None
        # marketValue is displayed in 억원 (1e8 KRW); the raw value must be in KRW.
        if abs(value / 1e8 - shown) > 1:
            raise FetchError(f"Naver marketValueRaw of {row['code']} is not in KRW")
        row.update(
            close=close,
            marketValue=value,
            tradedAt=item.get("localTradedAt"),
            status=item.get("marketStatus"),
        )
    return row


def naver_ranking(online: bool, sources: list, max_pages: int | None = None) -> dict:
    """Every row of the KOSPI market-value ranking.

    A repeated code means the ranking moved during paging; an empty page, a changed
    totalCount or a row count other than totalCount means the ranking is incomplete
    (later pages hold most preferred classes). Both raise FetchError: the KR market
    becomes an error instead of silently losing members or share classes. ``max_pages``
    reads a deliberately partial ranking (no completeness check). ``times`` are the
    pages' retrieval timestamps.
    """
    rows, seen, fetched, times = [], set(), 0, []
    page, pages, total, statuses = 1, 1, None, Counter()
    while page <= pages:
        payload, manifest = fetch_json(
            NAVER_URL.format(page=page, size=NAVER_PAGE_SIZE),
            f"naver-kospi-marketvalue-p{page}",
            provider="Naver Finance",
            online=online,
        )
        sources.append(manifest)
        times.append(manifest.get("retrievedAt"))
        fetched += 1
        if page == 1:
            total = int(payload["totalCount"])
            pages = math.ceil(total / int(payload["pageSize"]))
            if pages > NAVER_MAX_PAGES:
                raise FetchError(
                    f"Naver ranking spans {pages} pages (limit {NAVER_MAX_PAGES})"
                )
            pages = min(pages, max_pages or pages)
        if int(payload["page"]) != page:
            raise FetchError(f"Naver returned page {payload['page']} for page {page}")
        if int(payload["totalCount"]) != total:
            raise FetchError(
                f"Naver totalCount changed during paging ({total} -> "
                f"{payload['totalCount']} on page {page})"
            )
        statuses[payload.get("marketStatus")] += 1
        if not payload["stocks"]:
            if max_pages is None:
                raise FetchError(
                    f"Naver ranking incomplete: page {page} of {pages} is empty "
                    f"after {len(rows)} of {total} rows"
                )
            break
        for item in payload["stocks"]:
            row = _naver_row(item)
            if row["code"] in seen:
                raise FetchError(
                    f"Naver ranking moved during paging ({row['code']} repeated)"
                )
            seen.add(row["code"])
            rows.append(row)
        page += 1
    if max_pages is None and len(rows) != total:
        raise FetchError(
            f"Naver ranking incomplete: {len(rows)} rows for totalCount {total}"
        )
    stocks = Counter(r["status"] for r in rows if r["type"] == "stock")
    shared = set(statuses) | set(stocks)
    return dict(
        rows=rows,
        totalCount=total,
        pages=fetched,
        marketStatus=shared.pop() if len(shared) == 1 else "MIXED",
        marketStatuses=dict(pages=_tally(statuses), stocks=_tally(stocks)),
        times=times,
    )


def _tally(counter: Counter) -> dict:
    return {str(k): n for k, n in sorted(counter.items(), key=lambda i: str(i[0]))}


def _naver_facts(ranking: dict) -> dict:
    """What Naver reported (informational): its status and the latest stock-row trade
    time (KST); ``rankingRetrievedAt`` = first / last retrieval of its pages."""
    traded = [r["tradedAt"] for r in ranking["rows"] if r.get("tradedAt")]
    priced = max(traded, default=None)
    first, last = _span(ranking["times"])
    return dict(
        marketStatus=ranking["marketStatus"],
        marketStatuses=ranking["marketStatuses"],
        pricedAt=priced,
        pricedDate=priced[:10] if priced else None,
        tradedDates=_tally(Counter(t[:10] for t in traded)),
        rankingRetrievedAt=dict(first=first, last=last),
    )


def kospi_commons(rows: list, name_excluded: list | None = None):
    """``(common rows, other stock classes by 5-character code prefix, filter counts)``.

    Rows removed by a name pattern (SPAC, REIT) are appended to ``name_excluded``.
    """
    rules = RULES["KR"]
    patterns = [
        (reason, re.compile(p)) for reason, p in rules["excludeNamePatterns"].items()
    ]
    commons, others, filtered = [], {}, Counter()
    for row in rows:
        if row["type"] != rules["commonType"]:
            filtered[row["type"] or "unknown"] += 1
        elif not re.fullmatch(r"[0-9A-Z]{6}", row["code"]):
            filtered["invalid_code"] += 1
        elif not re.fullmatch(rules["commonCode"], row["code"]):
            others.setdefault(row["code"][:5], []).append(row)
            filtered["other_class"] += 1
        elif reason := next((r for r, p in patterns if p.search(row["name"])), None):
            filtered[reason] += 1
            if name_excluded is not None:
                name_excluded.append(
                    dict(
                        code=row["code"],
                        name=row["name"],
                        rule=reason,
                        marketValue=row["marketValue"],
                    )
                )
        else:
            commons.append(row)
    return commons, others, dict(sorted(filtered.items()))


def _listed_shares(row: dict, issues: list) -> int | None:
    if row["close"] <= 0:
        issues.append(
            _issue("listed_shares_unavailable", f"{row['code']} price {row['close']}")
        )
        return None
    shares, remainder = divmod(row["marketValue"], row["close"])
    if remainder:
        issues.append(
            _issue("listed_shares_inexact", f"{row['code']} value/price not whole")
        )
        shares += 2 * remainder >= row["close"]
    return shares


def _kr_class(row: dict, kind: str, issues: list) -> dict:
    return dict(
        ticker=row["code"],
        priceSymbol=f"{row['code']}.KS",
        kind=kind,
        listedShares=_listed_shares(row, issues),
    )


def _candidate(pool_rank: int, row: dict, others: dict) -> dict:
    """A common row, its listed classes (common first) and the issues met building them."""
    issues, preferred = [], []
    for other in sorted(others.get(row["code"][:5], []), key=lambda r: r["code"]):
        if other["name"].startswith(row["name"]):
            preferred.append(other)
        else:
            detail = f"{other['code']} {other['name']} vs {row['code']} {row['name']}"
            issues.append(_issue("class_name_mismatch", detail))
    classes = [
        _kr_class(row, "common", issues),
        *(_kr_class(other, "preferred", issues) for other in preferred),
    ]
    return dict(row=row, poolRank=pool_rank, classes=classes, issues=issues, cap=None)


def _settled(day: str) -> datetime:
    """When the Korean closes of ``day`` settle (prices.SETTLE_HOUR, Seoul time)."""
    zone = ZoneInfo(RULES["timing"]["timezones"]["KR"])
    clock = f"{_iso(day)}T{prices.SETTLE_HOUR:02d}:00"
    return datetime.fromisoformat(clock).replace(tzinfo=zone)


def _not_found(series: dict, symbol: str, day: str) -> bool:
    """A confirmed HTTP 404 (M3): every Yahoo host answered 404 for the symbol's series
    (prices.series joins the hosts' failures with '; '). A timeout, 429, 5xx, a rejected
    original, a 404 from one host only or an offline replay is not one."""
    try:
        key = re.escape(prices.source_key(symbol, day))
    except ValueError:
        return False
    failures = str(series.get("error") or "").split("; ")
    return len(failures) == len(prices.HOSTS) and all(
        re.fullmatch(rf"{re.escape(host)}: [^;]*\bHTTP 404 for {key}", failure)
        for host, failure in zip(prices.HOSTS, failures)
    )


def _not_listed(series: dict, symbol: str, day: str, online: bool) -> bool:
    """N1, M1: the hosts confirm that nothing traded through ``day``: a host's answer
    has no settled session in the window (prices.NoSessions, the series' ``empty``: a
    chart naming the symbol in the expected currency with sessions after ``day`` only,
    the request running through the build's date, or none; or Yahoo's HTTP 400
    prices.NO_DATA answer) and every host answered so or with HTTP 404 for the symbol
    (offline: the stored original answered so). A timeout, 429, 5xx or any other
    rejected original (a symbol or currency mismatch, an undecodable response, any
    other HTTP 400) is no such answer: the market is rebuilt."""
    if not isinstance(series.get("empty"), dict):
        return False
    try:
        key = re.escape(prices.source_key(symbol, day))
    except ValueError:
        return False
    hosts = prices.HOSTS if online else ("stored",)
    empty = rf"rejected original \({prices.NoSessions.__name__}: [^;]*\)"
    failures = str(series.get("error") or "").split("; ")
    return len(failures) == len(hosts) and all(
        re.fullmatch(
            rf"{re.escape(host)}: ({empty}|[^;]*\bHTTP 404 for {key})", failure
        )
        for host, failure in zip(hosts, failures)
    )


def _close_on(
    symbol: str, day: str, online: bool, sources: list, through: str | None = None
) -> dict:
    """``{close, reason, detail, at}``: the symbol's close on ``day`` from its price
    series through ``day``, requested through ``through`` (M1: the build's local date,
    so that sessions after ``day`` show; ``at`` = the series' retrieval time). Without
    one, ``reason`` says why: HALTED (a series retrieved after the closes of ``day``
    settled has no session that day), NOT_FOUND (every Yahoo host answered HTTP 404),
    NOT_LISTED (``_not_listed``: no settled session in the whole window, in an answer
    retrieved after the closes of ``day`` settled), ``close_unsettled`` (the series, or
    that answer, was retrieved before the closes settled) or ``price_unavailable`` (any
    other download failure, or a rejected original)."""
    series = prices.series(symbol, day, online=online, request_through=through)
    empty = None
    if series.get("status") != "ok":
        if not _not_listed(series, symbol, day, online):
            failed = (
                NOT_FOUND if _not_found(series, symbol, day) else "price_unavailable"
            )
            return dict(close=None, reason=failed, detail=series.get("error"), at=None)
        empty = series["empty"]
    manifest = (empty or series).get("source") or {}
    sources.append(manifest)
    at = manifest.get("retrievedAt")
    hit = None if empty else prices.close_on_or_before(series.get("rows") or [], day)
    if hit is not None and hit[0] == day:
        return dict(close=hit[1], reason=None, detail=None, at=at)
    retrieved, settles = _moment(at), _settled(day)
    if retrieved is None or retrieved < settles:  # prices dropped the day unsettled
        detail = f"retrieved {at}, before the closes settle at {settles.isoformat()}"
        return dict(close=None, reason="close_unsettled", detail=detail, at=at)
    if empty:  # N1: listed after T, or no session in the whole window
        return dict(close=None, reason=NOT_LISTED, detail=series.get("error"), at=at)
    detail = f"last session {hit[0] if hit else None}"
    return dict(close=None, reason=HALTED, detail=detail, at=at)


def _unpriced(candidate: str, share_class: dict, result: dict) -> str:
    """The market error for a class that could not be priced at T's close."""
    late = result["reason"] == "close_unsettled"
    return (
        f"{candidate}: {share_class['priceSymbol']} {result['reason']} "
        f"({result['detail']}); a failed price download never removes a candidate "
        f"(only {', '.join(UNRANKED_REASONS)} leave one unranked): rebuild"
        + (" after the closes settle" if late else "")
    )


def _rank_at_close(
    pool: list, others: dict, day: str, online: bool, sources: list, through=None
):
    """``(ranked, unranked, retrieval times)``: candidates by market cap at the close of
    ``day`` (descending, ties by code) and those left unranked for UNRANKED_REASONS.
    Every series is requested through ``through`` (M1: the build's local date).

    Anything else that keeps a candidate from being ranked raises FetchError, so the KR
    market is an error and is rebuilt (M3): a class without listed shares, a common that
    cannot be priced (a transient download failure, a rejected original other than a
    confirmed empty answer) and any class priced from a series retrieved before the
    closes settled. A preferred class that cannot be priced otherwise is ranked at the
    common close (class_price_proxy)."""
    ranked, unranked, times = [], [], []
    for pool_rank, row in enumerate(pool, 1):
        candidate = _candidate(pool_rank, row, others)
        classes = candidate["classes"]
        name = f"KR candidate {row['code']} {row['name']} (pool rank {pool_rank})"
        missing = [c["ticker"] for c in classes if c["listedShares"] is None]
        if missing:
            raise FetchError(
                f"{name}: no listed shares for {', '.join(missing)} (Naver price "
                "<= 0); rebuild"
            )
        common = _close_on(classes[0]["priceSymbol"], day, online, sources, through)
        times += [common["at"]] if common["at"] else []
        if common["close"] is None:
            if common["reason"] not in UNRANKED_REASONS:
                raise FetchError(_unpriced(name, classes[0], common))
            unranked.append(
                dict(
                    code=row["code"],
                    name=row["name"],
                    poolRank=pool_rank,
                    poolMarketValue=row["marketValue"],
                    reason=common["reason"],
                    detail=common["detail"],
                )
            )
            continue
        cap = 0.0
        for share_class in classes:
            own = common
            if share_class is not classes[0]:
                own = _close_on(
                    share_class["priceSymbol"], day, online, sources, through
                )
                times += [own["at"]] if own["at"] else []
                if own["reason"] == "close_unsettled":
                    raise FetchError(_unpriced(name, share_class, own))
            proxy = own["close"] is None
            close = common["close"] if proxy else own["close"]
            share_class.update(rankingClose=close, rankingProxy=proxy)
            if proxy:
                detail = (
                    f"{share_class['ticker']} ranked at the {classes[0]['ticker']} "
                    f"close ({own['reason']}: {own['detail']})"
                )
                candidate["issues"].append(_issue("class_price_proxy", detail))
            cap += share_class["listedShares"] * close
        candidate["cap"] = cap
        ranked.append(candidate)
    ranked.sort(key=lambda c: (-c["cap"], c["row"]["code"]))
    return ranked, unranked, times


def _kr_member(rank: int, candidate: dict) -> dict:
    row = candidate["row"]
    return dict(
        id=f"KR:{row['code']}",
        market="KR",
        name=row["name"],
        ticker=row["code"],
        priceSymbol=f"{row['code']}.KS",
        corpCode=None,
        ksic=None,
        sector=None,
        fiscalYearEnd=None,
        rankMarketCap=candidate["cap"],
        poolRank=candidate["poolRank"],
        poolMarketValue=row["marketValue"],
        shareClasses=candidate["classes"],
        rank=rank,
        status="eligible",
        reason=None,
        issues=[],
        fetchError=None,
        error=None,
    )


def _dart_code(blob: bytes) -> str | None:
    match = re.search(rb'<status>(\d+)</status>|"status"\s*:\s*"(\d+)"', blob[:4000])
    return (match[1] or match[2]).decode() if match else None


def _dart_status(blob: bytes) -> str:
    code = _dart_code(blob)
    return f"status {code}" if code else "unrecognised response"


def _company_answer(blob: bytes) -> bool:
    return _dart_code(blob) in DART_ANSWERS


def _archive(blob: bytes) -> bool:
    return blob.startswith(b"PK")


def _dart(endpoint, params, key, online, sources, suffix=".json", answer=None):
    """An OpenDART original through equitylab.dart.request; the key never reaches a URL here.

    Online, a response for which ``answer(blob)`` is false (a key, quota or other error
    status) is returned without being stored, so no offline rebuild replays it as the
    company's original."""
    if not online:
        blob, manifest = latest(key)
    else:
        for attempt in (1, 2):
            try:
                blob = dart_request(endpoint, params)
                break
            except RuntimeError as exc:  # message already withholds request details
                if attempt == 2:
                    raise FetchError(str(exc)) from None
                time.sleep(DART_RETRY_PAUSE)
            except ValueError as exc:
                raise FetchError(f"DART {endpoint}: {exc}") from None
        if answer is not None and not answer(blob):
            return blob
        url = DART_URL + endpoint + ("?" + urlencode(params) if params else "")
        manifest = store(blob, key, url, "OpenDART", suffix)
    sources.append(manifest)
    return blob


def dart_corp_codes(blob: bytes) -> dict[str, list[str]]:
    """``{stock_code: [corp_code, ...]}`` from the OpenDART corpCode.xml archive."""
    if not _archive(blob):
        raise FetchError(
            f"OpenDART corpCode.xml returned no archive ({_dart_status(blob)})"
        )
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        entry = next(
            (e for e in archive.infolist() if e.filename.lower() == "corpcode.xml"),
            None,
        )
        if entry is None or entry.file_size > 200_000_000:
            raise ValueError("corpCode archive lacks a bounded CORPCODE.xml")
        root = ET.fromstring(archive.read(entry))
    codes = {}
    for row in root.iter("list"):
        stock = (row.findtext("stock_code") or "").strip().upper()
        if stock:
            codes.setdefault(stock, []).append(
                (row.findtext("corp_code") or "").strip()
            )
    return codes


def _month_end(month) -> str | None:
    text = str(month or "").strip()
    if not re.fullmatch(r"\d{1,2}", text) or not 1 <= int(text) <= 12:
        return None
    return f"{int(text):02d}{calendar.monthrange(2001, int(text))[1]:02d}"


def _dart_profile(member, corp_codes, table, online, sources) -> dict:
    codes = corp_codes.get(member["ticker"], [])
    if len(codes) != 1:
        step = "missing_corp_code" if not codes else "ambiguous_corp_code"
        return _fetch_error(member, step, ", ".join(codes) or None)
    member["corpCode"] = corp = codes[0]
    try:
        key = f"dart-company-{corp}"
        company = json.loads(
            _dart(
                "company.json",
                {"corp_code": corp},
                key,
                online,
                sources,
                answer=_company_answer,
            )
        )
    except (FetchError, ValueError) as exc:
        return _fetch_error(member, "company_unavailable", exc)
    if not isinstance(company, dict):
        return _fetch_error(member, "company_unavailable", "not a JSON object")
    status = str(company.get("status"))
    if status in DART_SYSTEMIC:  # key, IP, quota, maintenance: no member can be read
        raise FetchError(
            f"OpenDART company.json status {status}: {company.get('message')}"
        )
    if status != "000":
        return _fetch_error(member, "company_unavailable", f"OpenDART status {status}")
    if str(company.get("stock_code") or "").strip().upper() != member["ticker"]:
        detail = f"company.json stock_code {company.get('stock_code')!r}"
        return _fetch_error(member, "dart_identity_mismatch", detail)
    member["fiscalYearEnd"] = _month_end(company.get("acc_mt"))
    ksic = str(company.get("induty_code") or "").strip()
    if not ksic:
        return _fetch_error(member, "missing_ksic")
    member.update(ksic=ksic, sector=sectors.ksic_sector(ksic, table))
    if sectors.financial_ksic(ksic):
        return _exclude(member, "financial_ksic")
    if sectors.financial_holding(ksic, company.get("corp_name")):
        member["sector"] = "Money"
        return _exclude(member, "financial_holding")
    if member["sector"] is None:
        return _fetch_error(member, "unmapped_ksic", f"KSIC {ksic!r}")
    return member


def _kr(as_of: str, online: bool, sources: list, limit=None) -> tuple[list, dict]:
    rules = RULES["KR"]
    ranking = naver_ranking(online, sources)
    name_excluded = []
    commons, others, filtered = kospi_commons(ranking["rows"], name_excluded)
    by_value = sorted(commons, key=lambda r: (-r["marketValue"], r["code"]))
    if len(by_value) < rules["top"]:
        raise FetchError(f"Naver ranking yields {len(by_value)} common stocks")
    close = market_close("KR", as_of)
    facts = _naver_facts(ranking)
    issues = []
    if _moment(facts["rankingRetrievedAt"]["first"]) <= close:
        early = (
            f"Naver ranking retrieved from {facts['rankingRetrievedAt']['first']}, "
            f"not after the {as_of} close ({close.isoformat()})"
        )
        if limit is None:
            raise FetchError(f"{early}; rebuild after the close")
        issues.append(_issue("ranking_captured_before_close", early))
    if online:
        ensure_dart_key()
    corp_codes = dart_corp_codes(
        _dart(
            "corpCode.xml",
            {},
            "dart-corpcode",
            online,
            sources,
            suffix=".zip",
            answer=_archive,
        )
    )
    table, record = sectors.load_ksic()
    sources.append(record)
    if limit is None:
        pool = by_value[: rules["candidatePool"]]
        # M1: requested through the build's Seoul date, not T+2, so that a stock
        # listed after T shows its later sessions (NoSessions "next session ...");
        # offline replays the stored originals as they were requested.
        through = max(as_of, _local_date("KR")) if online else None
        ranked, unranked, times = _rank_at_close(
            pool, others, as_of, online, sources, through
        )
        first, last = _span(ranking["times"] + times)
        if _moment(first) <= close:
            raise FetchError(
                f"KR ranking input retrieved at {first}, not after the {as_of} close "
                f"({close.isoformat()}); rebuild after the close"
            )
        if len(ranked) < rules["top"]:
            why = _tally(Counter(u["reason"] for u in unranked))
            raise FetchError(
                f"only {len(ranked)} of {len(pool)} candidates have a close on "
                f"{as_of}, {rules['top']} needed (unranked {why}); rebuild later"
            )
        chosen, basis = ranked[: rules["top"]], T_CLOSE
        outside = [
            dict(
                code=c["row"]["code"],
                name=c["row"]["name"],
                rank=rank,
                rankMarketCap=c["cap"],
            )
            for rank, c in enumerate(ranked[rules["top"] :], rules["top"] + 1)
        ]
        issues += [
            _issue("candidate_unranked", f"{u['code']} {u['reason']}: {u['detail']}")
            for u in unranked
        ]
        closes_first, closes_last = _span(times)
        ranking_facts = dict(
            closesRetrievedAt=dict(first=closes_first, last=closes_last),
            closesRequestedThrough=through,
            candidatePool=rules["candidatePool"],
            candidates=len(pool),
            ranked=len(ranked),
            unranked=unranked,
            outside=outside,
        )
    else:  # smoke run: Naver market value, no prices
        top = min(limit, rules["top"])
        chosen = [_candidate(n, row, others) for n, row in enumerate(by_value[:top], 1)]
        first, last = _span(ranking["times"])
        basis, ranking_facts = NAVER_VALUE, {}
    members = []
    for rank, candidate in enumerate(chosen, 1):
        issues += candidate["issues"]
        member = _kr_member(rank, candidate)
        members.append(_dart_profile(member, corp_codes, table, online, sources))
    info = dict(
        status="ok",
        error=None,
        rankingBasis=basis,
        capturedAt=dict(first=first, last=last),
        rankingCapturedAt=dict(first=first, last=last),
        totalCount=ranking["totalCount"],
        rows=len(ranking["rows"]),
        pages=ranking["pages"],
        **facts,
        filtered=filtered,
        nameExcluded=name_excluded,
        commons=len(commons),
        **ranking_facts,
        issues=issues,
    )
    return _market(members, info)
