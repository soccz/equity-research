"""ratings.universe and ratings.sectors against trimmed real originals, fully offline.

tests/fixtures/ratings/universe was cut from originals retrieved on 2026-10-06: the SSGA
SPY holdings file (as of 2026-10-02; seven equity rows, the cash row and a CVR row kept),
SEC company_tickers and submissions (filings dropped; NVIDIA's taken from the smoke run's
store), Ken French Siccodes12.zip (unchanged), 17 rows of Naver's KOSPI market-value
pages 1-3 repaged six per page (captured 13:11 KST during the session, marketStatus
OPEN), an OpenDART corpCode archive with the fixture issuers plus two unlisted ones, and
unchanged OpenDART company.json responses (SK하이닉스 and 현대차 from the smoke run's
store). Yahoo daily closes: Samsung common (tests/fixtures/ratings/prices) and preferred
(yahoo-005935.KS-2026-10-05.json, provenance.json) are trimmed originals; every other
symbol is served a constructed series (weekday sessions at its Naver price, marked as
such in ``chart``). Failures and other states are injected per test as overrides; a
changed Siccodes12 is constructed from the fixture. A module guard turns any live
request into a test error and sends every store write to a temp folder; the tests of
the real store functions (``RealStoreTests``) serve their downloads through a stubbed
``urlopen`` into a temp ROOT.
"""

import copy
from datetime import date, datetime, timedelta, timezone
import io
import json
import os
import re
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlsplit
import zipfile

from equitylab.data import ROOT, canonical, digest
from ratings import common, prices, sectors, universe
from ratings.common import FetchError

FIXTURES = ROOT / "tests/fixtures/ratings/universe"
PRICE_FIXTURES = ROOT / "tests/fixtures/ratings/prices"
NAMED = {
    "ssga-spy-holdings": "spy-holdings.xlsx",
    "sec-company-tickers": "company_tickers.json",
    "ken-french-siccodes12": "Siccodes12.zip",
    # The original kept under its own pointer (sectors.FF12_PINNED_KEY, L5).
    "ken-french-siccodes12-pinned": "Siccodes12.zip",
    "dart-corpcode": "corpcode.zip",
}
KSIC_DIVISIONS = (
    "01 02 03 05 06 07 08 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 "
    "31 32 33 34 35 36 37 38 39 41 42 45 46 47 49 50 51 52 55 56 58 59 60 61 62 63 64 65 "
    "66 68 70 71 72 73 74 75 76 84 85 86 87 90 91 94 95 96 97 98 99"
).split()
UA = "ratings-test tests@example.com"
RETRIEVED = "2026-10-06T04:11:30+00:00"  # 13:11 KST, during the 2026-10-06 session
AFTER_CLOSE = "2026-10-06T07:00:00+00:00"  # 16:00 KST: after the close, before 18:00
SETTLED = "2026-10-06T10:00:00+00:00"  # 19:00 KST: the day's closes have settled
# Trimmed real Yahoo originals and their retrieval times (13:11 and 13:17 KST, 10-06).
REAL_YAHOO = {
    "005930.KS": (
        PRICE_FIXTURES / "yahoo-005930.KS-2026-10-05.json",
        "2026-10-06T04:11:57.126016+00:00",
    ),
    "005935.KS": (
        FIXTURES / "yahoo-005935.KS-2026-10-05.json",
        "2026-10-06T04:17:46.243875+00:00",
    ),
}
FETCH_ERROR = "universe_fetch_error"  # the issue name other modules match on
# 메리츠금융지주 as Naver listed it in the same 13:11 KST capture (stored original
# naver-kospi-marketvalue-p1-a8da1f658bf448ae.json, rank 35 of the KOSPI commons).
MERITZ_ROW = {
    "stockType": "domestic",
    "stockEndType": "stock",
    "itemCode": "138040",
    "stockName": "메리츠금융지주",
    "closePrice": "129,600",
    "closePriceRaw": "129600",
    "marketValue": "216,882",
    "marketValueRaw": "21688206580800",
    "localTradedAt": "2026-10-06T13:11:20+09:00",
    "marketStatus": "OPEN",
}
MERITZ_CORP = "00860332"  # corpCode.xml of 2026-10-06 maps 138040 to it
# Constructed company.json (not an OpenDART original): the holding-company KSIC and a
# registered name with 금융지주, as OpenDART codes KB금융 and 신한지주.
MERITZ_COMPANY = dict(
    status="000",
    message="정상",
    corp_code=MERITZ_CORP,
    corp_name="메리츠금융지주(주)",
    stock_name="메리츠금융지주",
    stock_code="138040",
    induty_code="64992",
    acc_mt="12",
)
LOTTE_COMPANY = dict(  # constructed: a 64992 holding company outside 금융지주
    status="000",
    message="정상",
    corp_code="00120562",
    corp_name="롯데지주(주)",
    stock_name="롯데지주",
    stock_code="004990",
    induty_code="64992",
    acc_mt="12",
)
# Listed shares (Naver value / price) and real closes behind the expected market caps.
SAMSUNG_CAP = 5_846_278_608 * 276_000.0 + 802_371_203 * 201_000.0
# M1: Yahoo's answer (HTTP 400 on query1 and query2) to a request for 0126Z0.KS (first
# session 2025-11-25) ending 2025-11-20, as retrieved live on 2026-10-06 21:1x KST.
LIVE_400 = (
    b'{"chart":{"result":null,"error":{"code":"Bad Request","description":"Data '
    b"doesn't exist for startDate = 1748703600, endDate = 1763564400\"}}}"
)
# The build's Asia/Seoul date the tests run at (universe._local_date), not the clock.
BUILD_DATE = "2026-10-06"
GUARDS = []


def setUpModule():
    """No live request and no write to the real store from this module."""

    def refuse(*args, **kwargs):
        raise AssertionError("live network request in an offline test")

    folder = tempfile.TemporaryDirectory()
    GUARDS.append(folder)
    for patcher in (
        mock.patch("ratings.common.urlopen", refuse),
        mock.patch("equitylab.dart.urlopen", refuse),
        mock.patch.object(common, "SOURCES", universe.Path(folder.name)),
    ):
        patcher.start()
        GUARDS.append(patcher)


def tearDownModule():
    while GUARDS:
        guard = GUARDS.pop()
        guard.cleanup() if hasattr(guard, "cleanup") else guard.stop()


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def manifest(key: str, blob: bytes, url=None, retrieved=RETRIEVED) -> dict:
    return dict(
        key=key,
        url=url,
        sha256=digest(blob),
        file=f"fixture/{key}",
        bytes=len(blob),
        retrievedAt=retrieved,
    )


def page(number: int) -> dict:
    return json.loads(fixture(f"naver-p{number}.json"))


# Naver prices of the fixture rows: the default close of a constructed series.
NAVER_CLOSE = {
    f"{row['itemCode']}.KS": int(row["closePriceRaw"])
    for number in (1, 2, 3)
    for row in page(number)["stocks"]
    if row["stockEndType"] == "stock"
}
NAVER_CLOSE["138040.KS"] = int(MERITZ_ROW["closePriceRaw"])


def chart(symbol: str, closes: dict) -> dict:
    """A constructed Yahoo chart response (not an original): ``{day: close}`` sessions
    stamped 09:00 KST, adjusted close = close."""
    days = sorted(closes)
    stamps = [
        int(datetime.fromisoformat(f"{d}T09:00:00+09:00").timestamp()) for d in days
    ]
    values = [float(closes[d]) for d in days]
    result = dict(
        meta=dict(symbol=symbol, currency="KRW", exchangeTimezoneName="Asia/Seoul"),
        timestamp=stamps,
        indicators=dict(quote=[dict(close=values)], adjclose=[dict(adjclose=values)]),
    )
    return dict(chart=dict(result=[result], error=None))


def yahoo_key(symbol: str, as_of: str) -> str:
    return prices.source_key(symbol, as_of)


def naver_pages(extra=(), drop=(), status=None, total=None) -> dict:
    """Overrides for Naver pages 1-3: rows appended to page 3 or dropped by code, every
    page and row marked ``status``, totalCount following the rows unless given."""
    pages = {n: page(n) for n in (1, 2, 3)}
    pages[3]["stocks"] += [copy.deepcopy(row) for row in extra]
    for body in pages.values():
        body["stocks"] = [s for s in body["stocks"] if s["itemCode"] not in drop]
    count = sum(len(body["stocks"]) for body in pages.values())
    for body in pages.values():
        body["totalCount"] = count if total is None else total
        if status:
            body["marketStatus"] = status
            for row in body["stocks"]:
                row["marketStatus"] = status
    return {f"naver-kospi-marketvalue-p{n}": body for n, body in pages.items()}


def corpcode_with(*entries) -> bytes:
    """The fixture corpCode archive plus ``(corp_code, name, stock_code)`` entries."""
    text = zipfile.ZipFile(io.BytesIO(fixture("corpcode.zip"))).read("CORPCODE.xml")
    rows = "".join(
        f"<list><corp_code>{corp}</corp_code><corp_name>{name}</corp_name>"
        f"<stock_code>{stock}</stock_code></list>"
        for corp, name, stock in entries
    )
    text = text.decode().replace("</result>", rows + "</result>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", text)
    return buffer.getvalue()


class Sources:
    """Serves fixtures in place of ratings.common fetch/latest/store and the DART request.

    ``failing`` keys fail online (HTTP 503) while ``latest`` still serves the stored
    original; ``downloads`` serves an online download other than the stored original
    (a value or an exception), and ``hosts`` fails a key on some Yahoo hosts only
    (``{key: {"query2": exception}}``). Yahoo series: the real Samsung originals
    (``real_yahoo``), else constructed sessions on the weekdays of the two weeks to the
    requested date at ``closes`` (the Naver price by default), without that date for
    ``halted`` symbols; a symbol without a Naver price is unknown (HTTP 404 for its
    key, as ratings.common.fetch words it). ``times`` sets retrieval times by key, or by
    group "naver" / "yahoo". ``kept`` serves HTTP 400 bodies by key, as
    ratings.common.fetch does for a status in ``keep_status`` (manifest ``httpStatus``;
    else the HTTP 400 is a FetchError), online and as the stored pointer offline.
    ``listed`` answers a symbol's requests as Yahoo does for a stock first traded on
    the given day: weekday sessions from that day through the request's end (period2
    less the two days prices._url adds), or the HTTP 400 "Data doesn't exist" answer
    when the request ends before it."""

    def __init__(
        self,
        *,
        failing=(),
        real_yahoo=True,
        closes=None,
        halted=(),
        times=None,
        downloads=None,
        hosts=None,
        kept=None,
        listed=None,
        **overrides,
    ):
        self.overrides = overrides
        self.failing = set(failing)
        self.real_yahoo = real_yahoo
        self.closes = dict(closes or {})
        self.halted = set(halted)
        self.times = dict(times or {})
        self.downloads = dict(downloads or {})
        self.hosts = dict(hosts or {})
        self.kept = dict(kept or {})
        self.listed = dict(listed or {})
        self.calls = []

    def listing(self, symbol: str, url: str) -> tuple:
        """``(blob, httpStatus)`` of Yahoo's answer for a stock listed on
        ``self.listed[symbol]`` to the request ``url``."""
        query = dict(parse_qsl(urlsplit(url).query))
        period1, period2 = int(query["period1"]), int(query["period2"])
        end = datetime.fromtimestamp(period2, timezone.utc).date() - timedelta(days=2)
        day, sessions = date.fromisoformat(self.listed[symbol]), {}
        while day <= end:
            if day.weekday() < 5:
                sessions[day.isoformat()] = 50_000
            day += timedelta(days=1)
        if sessions:
            return json.dumps(chart(symbol, sessions)).encode(), None
        description = (
            f"Data doesn't exist for startDate = {period1}, endDate = {period2}"
        )
        body = dict(
            chart=dict(
                result=None, error=dict(code="Bad Request", description=description)
            )
        )
        return json.dumps(body).encode(), 400

    def _yahoo(self, key: str):
        match = re.fullmatch(r"yahoo-(.+)-(\d{4}-\d{2}-\d{2})", key)
        symbol, through = match[1], match[2]
        real = self.real_yahoo and symbol in REAL_YAHOO
        real = real and symbol not in self.closes and symbol not in self.halted
        return symbol, through, real

    def blob(self, key: str) -> bytes:
        if key in self.overrides:
            value = self.overrides[key]
            if isinstance(value, Exception):
                raise value
            return value if isinstance(value, bytes) else json.dumps(value).encode()
        if key.startswith("yahoo-"):
            symbol, through, real = self._yahoo(key)
            if real:
                return REAL_YAHOO[symbol][0].read_bytes()
            if symbol not in self.closes and symbol not in NAVER_CLOSE:
                raise FetchError(f"Yahoo Finance: HTTP 404 for {key}")
            end = date.fromisoformat(through)
            days = [end - timedelta(days=n) for n in range(14, -1, -1)]
            sessions = {
                d.isoformat(): self.closes.get(symbol, NAVER_CLOSE.get(symbol))
                for d in days
                if d.weekday() < 5 and not (symbol in self.halted and d == end)
            }
            return json.dumps(chart(symbol, sessions)).encode()
        if key in NAMED:
            name = NAMED[key]
        elif key.startswith("sec-submissions-"):
            name = f"submissions-{key.removeprefix('sec-submissions-')}.json"
        elif key.startswith("naver-kospi-marketvalue-p"):
            name = f"naver-p{key.removeprefix('naver-kospi-marketvalue-p')}.json"
        elif key.startswith("dart-company-"):
            name = f"company-{key.removeprefix('dart-company-')}.json"
        else:
            name = ""
        if not name or not (FIXTURES / name).exists():
            raise FetchError(f"fixture: HTTP 404 for {key}")
        return fixture(name)

    def retrieved(self, key: str) -> str:
        if key in self.times:
            return self.times[key]
        if key.startswith("yahoo-"):
            symbol, _, real = self._yahoo(key)
            return REAL_YAHOO[symbol][1] if real else self.times.get("yahoo", RETRIEVED)
        if key.startswith("naver-"):
            return self.times.get("naver", RETRIEVED)
        return RETRIEVED

    def fetch(self, url, key, *, provider, online=True, headers=None, **kwargs):
        self.calls.append(dict(key=key, online=online, headers=headers, url=url))
        if online and key in self.failing:
            raise FetchError(f"{provider}: HTTP 503 for {key}")
        host = re.match(r"https://([^.]+)\.", url or "")
        failure = self.hosts.get(key, {}).get(host[1] if host else None)
        if online and failure is not None:
            raise failure
        status = None
        symbol = self._yahoo(key)[0] if key.startswith("yahoo-") else None
        if online and key in self.downloads:
            value = self.downloads[key]
            if isinstance(value, Exception):
                raise value
            blob = value if isinstance(value, bytes) else json.dumps(value).encode()
        elif online and symbol in self.listed:
            blob, status = self.listing(symbol, url)
        elif key in self.kept:
            blob, status = self.kept[key], 400
        else:
            blob = self.blob(key)
        record = manifest(key, blob, url, self.retrieved(key))
        if status is not None:
            if online and status not in kwargs.get("keep_status", ()):
                raise FetchError(f"{provider}: HTTP {status} for {key}")
            record["httpStatus"] = status  # offline: the pointer kept it
        return blob, record

    def fetch_json(self, url, key, **kwargs):
        blob, record = self.fetch(url, key, **kwargs)
        return json.loads(blob), record

    def latest(self, key):
        self.calls.append(dict(key=key, online=False, headers=None, url=None))
        blob = self.blob(key)
        # A kept pointer holds the original's own manifest (sectors._keep_pinned).
        original = key.removesuffix("-pinned")
        return blob, manifest(original, blob, retrieved=self.retrieved(original))

    def dart_request(self, endpoint, params):
        corp = params.get("corp_code")
        key = f"dart-company-{corp}" if corp else "dart-corpcode"
        try:
            return self.blob(key)
        except FetchError:
            raise RuntimeError(f"DART {endpoint}: HTTPError; request details withheld")

    def store(self, blob, key, url, provider, suffix):
        self.calls.append(dict(key=key, stored=True, url=url, suffix=suffix))
        return manifest(key, blob, url)

    def keys(self, prefix: str) -> list:
        return [c["key"] for c in self.calls if c["key"].startswith(prefix)]


def run(
    sources=None,
    markets=("US", "KR"),
    online=True,
    as_of="2026-10-02",
    env=UA,
    limit=None,
    top=10,
    pool=13,
    built_on=BUILD_DATE,
):
    """universe.build on ``sources``; ``built_on`` is the build's Asia/Seoul date (the
    KR ranking series are requested through it, M1)."""
    sources = sources or Sources()
    key_loader = mock.Mock()
    patches = mock.patch.multiple(
        universe,
        fetch=sources.fetch,
        fetch_json=sources.fetch_json,
        latest=sources.latest,
        store=sources.store,
        dart_request=sources.dart_request,
        ensure_dart_key=key_loader,
        SPY_MIN_WEIGHT=1.0,
        DART_RETRY_PAUSE=0,
        _local_date=lambda market: built_on,
    )
    with patches, mock.patch.multiple(
        sectors, fetch=sources.fetch, latest=sources.latest
    ), mock.patch.object(prices, "fetch", sources.fetch), mock.patch.dict(
        universe.RULES["KR"], top=top, candidatePool=pool
    ), mock.patch.dict(
        os.environ, {"SEC_USER_AGENT": env or ""}
    ):
        result = universe.build(as_of, online=online, markets=markets, limit=limit)
    return result, sources, key_loader


def by_id(result: dict) -> dict:
    return {m["id"]: m for m in result["members"]}


def issues(info: dict) -> list:
    return [i["issue"] for i in info["issues"]]


def relabel(result: dict, day: str) -> dict:
    """A copy of a build with every market relabelled to another T (file-layout tests
    only)."""
    copied = copy.deepcopy(result)
    copied.update(asOf=day, asOfByMarket={market: day for market in copied["markets"]})
    for info in copied["markets"].values():
        info["asOf"] = day
    return copied


class SectorTests(unittest.TestCase):
    def test_ff12_definition_matches_pin_and_french_ranges(self):
        industries = sectors.parse_ff12(fixture("Siccodes12.zip"))
        self.assertEqual(sectors.ff12_hash(industries), sectors.FF12_DEFINITION_SHA256)
        self.assertEqual([i["code"] for i in industries], list(sectors.FF12))
        expected = {
            3571: "BusEq",
            7370: "BusEq",
            2080: "NoDur",
            100: "NoDur",
            3714: "Durbl",
            3559: "Manuf",
            2911: "Enrgy",
            2821: "Chems",
            2836: "Hlth",
            3693: "Hlth",
            4813: "Telcm",
            4911: "Utils",
            5331: "Shops",
            6021: "Money",
            6331: "Money",
            4011: "Other",
            1040: "Other",
            9995: "Other",
        }
        for sic, code in expected.items():
            self.assertEqual(sectors.sic_sector(sic, industries), code, sic)

    def test_ff12_parser_rejects_changed_layouts(self):
        text = zipfile.ZipFile(io.BytesIO(fixture("Siccodes12.zip"))).read(
            "Siccodes12.txt"
        )
        for broken in (
            text.replace(b"2000-2399", b"2000-2399 ;; 2350-2360\n          2350-2360"),
            text.replace(b"12 Other", b"12 Misc"),
            text.replace(b"0100-0999", b"0999-0100"),
            text + b"\nunexpected trailer\n",
        ):
            with self.assertRaises(ValueError):
                sectors.parse_ff12(siccodes(broken))

    def test_ken_french_outage_uses_a_stored_original_with_the_pinned_hash(self):
        # R12: the definition is pinned by hash, so the stored original is the same one.
        sources = Sources(failing={"ken-french-siccodes12"})
        with mock.patch.multiple(sectors, fetch=sources.fetch, latest=sources.latest):
            industries, record = sectors.load_ff12(online=True)
        self.assertEqual(sectors.ff12_hash(industries), sectors.FF12_DEFINITION_SHA256)
        self.assertIn("HTTP 503 for ken-french-siccodes12", record["fallback"])
        self.assertEqual(record["sha256"], digest(fixture("Siccodes12.zip")))
        self.assertNotIn("changed", record)
        self.assertEqual(
            [(c["key"], c["online"]) for c in sources.calls],
            [
                ("ken-french-siccodes12-pinned", False),  # kept before the download
                ("ken-french-siccodes12", True),
                ("ken-french-siccodes12-pinned", False),
            ],
        )
        # A download that works is used as fetched, without a fallback mark.
        sources = Sources()
        with mock.patch.multiple(sectors, fetch=sources.fetch, latest=sources.latest):
            _, record = sectors.load_ff12(online=True)
        self.assertNotIn("fallback", record)
        self.assertNotIn("changed", record)
        self.assertEqual(
            [c["key"] for c in sources.calls if c["online"]], ["ken-french-siccodes12"]
        )

    def test_outage_without_a_pinned_stored_original_stays_an_error(self):
        text = zipfile.ZipFile(io.BytesIO(fixture("Siccodes12.zip"))).read(
            "Siccodes12.txt"
        )
        changed = siccodes(text.replace(b"5000-5999", b"5000-5998"))
        unkept = {"ken-french-siccodes12-pinned": FetchError("No stored original")}
        cases = {
            "differs from the pinned definition": Sources(
                failing={"ken-french-siccodes12"},
                **{"ken-french-siccodes12": changed},
                **unkept,
            ),
            "no usable stored Siccodes12": Sources(
                failing={"ken-french-siccodes12"},
                **{"ken-french-siccodes12": b"<html>maintenance</html>"},
                **unkept,
            ),
        }
        for message, sources in cases.items():
            with mock.patch.multiple(
                sectors, fetch=sources.fetch, latest=sources.latest
            ), self.assertRaisesRegex(FetchError, message):
                sectors.load_ff12(online=True)
        # N4: offline, a latest original that cannot be read falls back to the kept
        # pinned one (like an outage) instead of raising; without one it still raises.
        for latest in (
            FetchError("No stored original"),
            FileNotFoundError("ken-french-siccodes12-0123456789abcdef.zip"),
            ValueError("Source hash mismatch"),
        ):
            with self.subTest(latest=type(latest).__name__):
                missing = Sources(**{"ken-french-siccodes12": latest})
                with mock.patch.multiple(
                    sectors, fetch=missing.fetch, latest=missing.latest
                ):
                    industries, record = sectors.load_ff12(online=False)
                self.assertEqual(
                    sectors.ff12_hash(industries), sectors.FF12_DEFINITION_SHA256
                )
                self.assertEqual(record["fallback"], str(latest))
                self.assertTrue(all(c["online"] is False for c in missing.calls))
        neither = Sources(
            **{"ken-french-siccodes12": FetchError("No stored original")}, **unkept
        )
        with mock.patch.multiple(
            sectors, fetch=neither.fetch, latest=neither.latest
        ), self.assertRaisesRegex(FetchError, "no usable stored Siccodes12"):
            sectors.load_ff12(online=False)

    def test_a_corrupt_download_is_a_us_market_error(self):
        """N4: with no pinned original to fall back on, a download whose deflate stream
        is damaged (zlib.error) or cut short (EOFError) makes the US market an error,
        never a traceback out of the build."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Siccodes12.txt", b"1 NoDur Consumer\n" * 50)
        blob = bytearray(buffer.getvalue())
        blob[30 + len("Siccodes12.txt")] = 0xFF  # a reserved deflate block type
        corrupt = bytes(blob)
        with self.assertRaises(sectors.zlib.error):
            sectors.parse_ff12(corrupt)
        self.assertIn(sectors.zlib.error, universe.DATA_ERRORS)
        self.assertIn(EOFError, universe.DATA_ERRORS)
        unkept = {"ken-french-siccodes12-pinned": FetchError("No stored original")}
        sources = Sources(**{"ken-french-siccodes12": corrupt}, **unkept)
        result, _, _ = run(sources, markets=("US",))
        info = result["markets"]["US"]
        self.assertEqual((result["status"], info["status"]), ("error", "error"))
        self.assertTrue(
            info["error"].startswith("error: Error -3 while decompressing"),
            info["error"],
        )
        self.assertEqual(result["members"], [])
        with mock.patch.object(
            sectors, "load_ff12", side_effect=EOFError("compressed file ended early")
        ):
            result, _, _ = run(markets=("US",))
        self.assertEqual(
            result["markets"]["US"]["error"], "EOFError: compressed file ended early"
        )

    def test_changed_definition_uses_the_pinned_stored_original(self):
        # L5: Ken French publishes a changed Siccodes12; the pinned stored original is
        # the definition PROTOCOL pins, so it is used and the download is recorded.
        text = zipfile.ZipFile(io.BytesIO(fixture("Siccodes12.zip"))).read(
            "Siccodes12.txt"
        )
        changed = siccodes(text.replace(b"5000-5999", b"5000-5998"))
        pinned = digest(fixture("Siccodes12.zip"))
        for download, found in (
            (changed, sectors.ff12_hash(sectors.parse_ff12(changed))),
            (b"<html>moved</html>", None),  # a file that no longer parses at all
        ):
            sources = Sources(downloads={"ken-french-siccodes12": download})
            with mock.patch.multiple(
                sectors, fetch=sources.fetch, latest=sources.latest
            ):
                industries, record = sectors.load_ff12(online=True)
            self.assertEqual(
                sectors.ff12_hash(industries), sectors.FF12_DEFINITION_SHA256
            )
            self.assertEqual(record["sha256"], pinned)
            self.assertNotIn("fallback", record)
            self.assertEqual(
                (record["changed"]["sha256"], record["changed"]["definitionSha256"]),
                (digest(download), found),
            )
            self.assertEqual(record["changed"]["retrievedAt"], RETRIEVED)
            if found is None:
                self.assertIn("BadZipFile", record["changed"]["error"])
            else:
                self.assertNotEqual(found, sectors.FF12_DEFINITION_SHA256)
                self.assertIsNone(record["changed"]["error"])
        # Offline, a changed latest original also falls back to the kept pinned one.
        sources = Sources(**{"ken-french-siccodes12": changed})
        with mock.patch.multiple(sectors, fetch=sources.fetch, latest=sources.latest):
            industries, record = sectors.load_ff12(online=False)
        self.assertEqual(sectors.ff12_hash(industries), sectors.FF12_DEFINITION_SHA256)
        self.assertEqual(record["changed"]["sha256"], digest(changed))
        self.assertTrue(all(c["online"] is False for c in sources.calls))
        # Without a pinned original the changed definition stands (the universe
        # reports it and registrations refuse the US); an unparsable one is an error.
        unkept = {"ken-french-siccodes12-pinned": FetchError("No stored original")}
        sources = Sources(**{"ken-french-siccodes12": changed}, **unkept)
        with mock.patch.multiple(sectors, fetch=sources.fetch, latest=sources.latest):
            industries, record = sectors.load_ff12(online=True)
        self.assertNotEqual(
            sectors.ff12_hash(industries), sectors.FF12_DEFINITION_SHA256
        )
        self.assertNotIn("changed", record)
        sources = Sources(**{"ken-french-siccodes12": b"<html>moved</html>"}, **unkept)
        with mock.patch.multiple(
            sectors, fetch=sources.fetch, latest=sources.latest
        ), self.assertRaises(zipfile.BadZipFile):
            sectors.load_ff12(online=True)

    def test_financial_sic_bounds(self):
        self.assertEqual(
            [sectors.financial_sic(s) for s in (5999, 6000, 6331, 6799, 6800)],
            [False, True, True, True, False],
        )

    def test_ksic_reference_is_complete_hashed_and_money_only_where_excluded(self):
        table, record = sectors.load_ksic()
        self.assertEqual(sorted(c for c in table if len(c) == 2), KSIC_DIVISIONS)
        self.assertEqual(record["file"], "data/ratings/reference/ksic-ff12.json")
        self.assertEqual(record["sha256"], digest(sectors.KSIC_REFERENCE.read_bytes()))
        for code, sector in table.items():
            self.assertIn(sector, sectors.FF12)
            self.assertEqual(sector == "Money", sectors.financial_ksic(code), code)

    def test_ksic_longest_prefix(self):
        table, _ = sectors.load_ksic()
        expected = {
            "264": "BusEq",
            "261": "BusEq",
            "2612": "BusEq",
            "2411": "Manuf",
            "265": "Durbl",
            "28202": "BusEq",
            "58211": "BusEq",
            "58113": "NoDur",
            "64992": "Other",
            "64201": "Money",
            "70113": "Hlth",
            "70121": "Other",
            "35300": "Other",
            "35110": "Utils",
            "30121": "Durbl",
            "30201": "Manuf",
        }
        for code, sector in expected.items():
            self.assertEqual(sectors.ksic_sector(code, table), sector, code)
        for code in ("", "5", "ab", "123456", "04", "4"):
            self.assertIsNone(sectors.ksic_sector(code, table), code)

    def test_korean_financial_exclusion(self):
        self.assertFalse(sectors.financial_ksic("64992"))
        for code in ("64", "6499", "64201", "65110", "66", "68112"):
            self.assertTrue(sectors.financial_ksic(code), code)
        for code in ("264", "70113", "63"):
            self.assertFalse(sectors.financial_ksic(code), code)
        # Holding companies (64992) stay unless the registered name marks 금융지주.
        self.assertTrue(sectors.financial_holding("64992", "(주)KB금융지주"))
        self.assertTrue(sectors.financial_holding("64992", "(주)신한금융지주회사"))
        self.assertTrue(sectors.financial_holding("64992", "메리츠금융지주(주)"))
        self.assertFalse(sectors.financial_holding("64992", "SK(주)"))
        self.assertFalse(sectors.financial_holding("64992", None))
        self.assertFalse(sectors.financial_holding("2411", "포스코금융지주"))


def siccodes(text: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Siccodes12.txt", text)
    return buffer.getvalue()


class RealStoreTests(unittest.TestCase):
    """sectors.load_ff12 on the real ratings.common fetch/latest/store in a temp ROOT;
    each download is served by a stubbed urlopen (never the network). A download moves
    the latest pointer to what it fetched, as on the real store."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = universe.Path(folder.name).resolve()
        self.store = root / "data/ratings/sources"
        self.served = []
        for target, name, value in (
            (common, "ROOT", root),
            (common, "SOURCES", self.store),
            (common, "urlopen", self.urlopen),
            (common, "time", mock.Mock(sleep=lambda seconds: None)),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        text = zipfile.ZipFile(io.BytesIO(fixture("Siccodes12.zip"))).read(
            "Siccodes12.txt"
        )
        self.pinned = fixture("Siccodes12.zip")
        self.changed = siccodes(text.replace(b"5000-5999", b"5000-5998"))

    def urlopen(self, request, timeout=None):
        self.assertEqual(request.full_url, sectors.FF12_URL)
        served = self.served.pop(0)
        if isinstance(served, Exception):
            raise served
        return io.BytesIO(served)

    def pointer(self, key: str) -> dict:
        return json.loads((self.store / f"{key}.manifest.json").read_text())

    def load(self, served=None, online=True):
        self.served = [] if served is None else [served]
        industries, record = sectors.load_ff12(online=online)
        self.assertEqual(self.served, [])
        return sectors.ff12_hash(industries), record

    def test_a_changed_definition_never_displaces_the_pinned_original(self):
        pin = sectors.FF12_DEFINITION_SHA256
        definition, first = self.load(self.pinned)  # the store's first download
        self.assertEqual((definition, first["sha256"]), (pin, digest(self.pinned)))
        self.assertNotIn("changed", first)
        # Ken French publishes a changed file: the download moves the latest pointer,
        # but the pinned original was kept under its own pointer before it, so the
        # universe keeps the pinned definition (L5) and records the download.
        definition, record = self.load(self.changed)
        self.assertEqual(definition, pin)
        self.assertEqual(record["sha256"], digest(self.pinned))
        self.assertEqual(record["retrievedAt"], first["retrievedAt"])
        self.assertEqual(record["changed"]["sha256"], digest(self.changed))
        self.assertNotEqual(record["changed"]["definitionSha256"], pin)
        self.assertEqual(
            self.pointer("ken-french-siccodes12")["sha256"], digest(self.changed)
        )
        self.assertEqual(self.pointer("ken-french-siccodes12-pinned"), first)
        # Every later month, online and offline, and through an outage (R12).
        for served, online in ((self.changed, True), (None, False)):
            before = sorted(p.name for p in self.store.iterdir())
            definition, record = self.load(served, online=online)
            self.assertEqual((definition, record["sha256"]), (pin, first["sha256"]))
            self.assertEqual(record["changed"]["sha256"], digest(self.changed))
            if not online:  # offline never writes
                self.assertEqual(sorted(p.name for p in self.store.iterdir()), before)
        outage = HTTPError(sectors.FF12_URL, 404, "Not Found", {}, None)
        definition, record = self.load(outage)
        self.assertEqual((definition, record["sha256"]), (pin, first["sha256"]))
        self.assertIn("HTTP 404", record["fallback"])
        self.assertEqual(self.pointer("ken-french-siccodes12-pinned"), first)

    def test_a_pinned_original_no_pointer_leads_to_is_found_in_the_store(self):
        """N4: the pinned original is still among the stored Siccodes12 originals, but
        no pointer leads to it (a download moved the latest pointer before the pinned
        one was kept): it is found by its content and used online, offline and
        through an outage, never the changed definition."""
        pin = sectors.FF12_DEFINITION_SHA256
        self.load(self.pinned)  # stored; no pinned pointer yet (nothing to keep before)
        common.store(
            self.changed, sectors.FF12_KEY, sectors.FF12_URL, "Ken French", ".zip"
        )
        self.assertFalse(
            (self.store / "ken-french-siccodes12-pinned.manifest.json").exists()
        )
        name = f"ken-french-siccodes12-{digest(self.pinned)[:16]}.zip"
        outage = HTTPError(sectors.FF12_URL, 404, "Not Found", {}, None)
        for served, online in ((self.changed, True), (outage, True), (None, False)):
            with self.subTest(served=type(served).__name__, online=online):
                definition, record = self.load(served, online=online)
                self.assertEqual(definition, pin)
                self.assertEqual(
                    (record["sha256"], record["file"], record["retrievedAt"]),
                    (digest(self.pinned), f"data/ratings/sources/{name}", None),
                )
                self.assertIn("without a pointer", record["located"])
                if served is outage:
                    self.assertIn("HTTP 404", record["fallback"])
                else:
                    self.assertEqual(record["changed"]["sha256"], digest(self.changed))
        # Offline without any latest pointer: the stored original still serves.
        (self.store / "ken-french-siccodes12.manifest.json").unlink()
        definition, record = self.load(online=False)
        self.assertEqual((definition, record["sha256"]), (pin, digest(self.pinned)))
        self.assertIn("No stored original", record["fallback"])
        # A file whose bytes do not match the hash in its name is never used.
        (self.store / name).rename(
            self.store / "ken-french-siccodes12-0123456789abcdef.zip"
        )
        with self.assertRaisesRegex(FetchError, "no usable stored Siccodes12"):
            self.load(online=False)
        definition, record = self.load(self.changed)  # the change stands (refused)
        self.assertNotEqual(definition, pin)
        self.assertNotIn("changed", record)

    def test_without_a_pinned_original_the_change_stands(self):
        definition, record = self.load(self.changed)  # nothing pinned was ever stored
        self.assertNotEqual(definition, sectors.FF12_DEFINITION_SHA256)
        self.assertEqual(record["sha256"], digest(self.changed))
        self.assertFalse(
            (self.store / "ken-french-siccodes12-pinned.manifest.json").exists()
        )


class HoldingsFileTests(unittest.TestCase):
    @mock.patch.object(
        universe, "SPY_MIN_WEIGHT", 1.0
    )  # the fixture keeps 7 of 504 rows
    def test_spy_holdings_keep_equities_and_record_skipped_rows(self):
        spy = universe.spy_holdings(fixture("spy-holdings.xlsx"))
        self.assertEqual(spy["asOf"], "2026-10-02")
        self.assertEqual(
            [h["ticker"] for h in spy["equities"]],
            ["NVDA", "AAPL", "GOOGL", "GOOG", "BRK.B", "JPM", "BF.B"],
        )
        self.assertEqual([h["ticker"] for h in spy["skipped"]], ["-", "2602335D"])
        self.assertEqual(spy["skipped"][0]["name"], "US DOLLAR")
        self.assertEqual(spy["equities"][0]["weight"], 8.504512)

    def test_weight_guard_rejects_partial_or_fractional_files(self):
        with self.assertRaisesRegex(ValueError, "cover"):
            universe.spy_holdings(fixture("spy-holdings.xlsx"))  # real 95% floor

    def test_xlsx_reader_handles_inline_and_sparse_cells(self):
        main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        sheet = (
            f'<worksheet xmlns="{main}"><sheetData>'
            '<row r="1"><c r="A1" t="inlineStr"><is><t>Name</t></is></c>'
            '<c r="C1" t="s"><v>0</v></c></row>'
            '<row r="2"><c t="s"><v>1</v></c><c><v>2.5</v></c></row>'
            "</sheetData></worksheet>"
        )
        strings = (
            f'<sst xmlns="{main}"><si><t>Weight</t></si>'
            "<si><r><t>Rich </t></r><r><t>text</t></r></si></sst>"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as book:
            book.writestr("xl/worksheets/sheet1.xml", sheet)
            book.writestr("xl/sharedStrings.xml", strings)
        rows = universe.xlsx_rows(buffer.getvalue())
        self.assertEqual(rows, [["Name", None, "Weight"], ["Rich text", "2.5"]])

    def test_header_and_date_are_required(self):
        buffer = io.BytesIO()
        main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        with zipfile.ZipFile(buffer, "w") as book:
            book.writestr(
                "xl/worksheets/sheet1.xml",
                f'<worksheet xmlns="{main}"><sheetData><row r="1">'
                '<c r="A1" t="inlineStr"><is><t>Holdings</t></is></c>'
                "</row></sheetData></worksheet>",
            )
        with self.assertRaisesRegex(ValueError, "header"):
            universe.spy_holdings(buffer.getvalue())


class UsUniverseTests(unittest.TestCase):
    def test_one_member_per_issuer_with_reasons(self):
        result, sources, _ = run(markets=("US",))
        self.assertEqual(result["status"], "ok")
        members = by_id(result)
        alphabet = members["US:0001652044"]
        self.assertEqual(
            (alphabet["ticker"], alphabet["priceSymbol"], alphabet["cik"]),
            ("GOOGL", "GOOGL", "0001652044"),
        )
        # Every listed class, the pricing class first (rating.market_cap reads them all).
        self.assertEqual(
            alphabet["shareClasses"],
            [
                dict(
                    ticker="GOOGL", priceSymbol="GOOGL", kind="common", weight=3.027691
                ),
                dict(ticker="GOOG", priceSymbol="GOOG", kind="common", weight=2.430157),
            ],
        )
        self.assertEqual(alphabet["weight"], 5.457848)
        self.assertEqual((alphabet["sic"], alphabet["sector"]), ("7370", "BusEq"))
        self.assertEqual((alphabet["status"], alphabet["reason"]), ("eligible", None))
        self.assertEqual((alphabet["issues"], alphabet["fetchError"]), ([], None))
        self.assertEqual(alphabet["name"], "Alphabet Inc.")
        berkshire = members["US:0001067983"]
        self.assertEqual(
            (berkshire["ticker"], berkshire["priceSymbol"]), ("BRK.B", "BRK-B")
        )
        self.assertEqual(
            (berkshire["sector"], berkshire["reason"]), ("Money", "financial_sic")
        )
        self.assertEqual(members["US:0000019617"]["reason"], "financial_sic")
        brown = members["US:0000014693"]
        self.assertEqual((brown["priceSymbol"], brown["sector"]), ("BF-B", "NoDur"))
        self.assertEqual(
            (brown["fiscalYearEnd"], brown["status"]), ("0430", "eligible")
        )
        apple = members["US:0000320193"]
        self.assertEqual(
            (apple["fiscalYearEnd"], len(apple["shareClasses"])), ("0926", 1)
        )
        nvidia = members["US:0001045810"]
        self.assertEqual(
            (nvidia["sic"], nvidia["sector"], nvidia["status"]),
            ("3674", "BusEq", "eligible"),
        )
        self.assertEqual(
            [m["id"] for m in result["members"]],
            [
                "US:0001045810",
                "US:0000320193",
                "US:0001652044",
                "US:0001067983",
                "US:0000019617",
                "US:0000014693",
            ],
        )
        self.assertEqual([m["rank"] for m in result["members"]], [1, 2, 3, 4, 5, 6])
        info = result["markets"]["US"]
        self.assertEqual((info["holdingsAsOf"], info["equityRows"]), ("2026-10-02", 7))
        self.assertEqual([s["ticker"] for s in info["skipped"]], ["-", "2602335D"])
        self.assertEqual(
            info["counts"],
            dict(
                members=6,
                eligible=4,
                excluded=dict(financial_sic=2),
                fetchErrors={},
                fetchErrorRate=0.0,
            ),
        )
        self.assertEqual(info["issues"], [])
        self.assertIsNone(info["ff12Fallback"])
        self.assertIsNone(info["ff12Changed"])
        sec = [c for c in sources.calls if c["key"].startswith("sec-")]
        self.assertTrue(sec and all(c["headers"] == {"User-Agent": UA} for c in sec))
        keys = {s["key"] for s in result["sources"]}
        self.assertIn("sec-submissions-0000014693", keys)
        self.assertIn("sec-submissions-0001045810", keys)
        self.assertEqual(info["sources"], result["sources"])  # one market built
        self.assertEqual(sources.keys("yahoo-"), [])  # US membership needs no prices

    def test_holdings_date_and_capture_are_recorded_against_as_of(self):
        result, _, _ = run(markets=("US",), as_of="2026-09-30")
        info = result["markets"]["US"]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            (info["asOf"], info["holdingsAsOf"], info["holdingsRetrievedAt"]),
            ("2026-09-30", "2026-10-02", RETRIEVED),
        )
        # D5: the US part is captured once SSGA posts T's holdings (the next business day).
        self.assertEqual(info["capturedAt"], dict(first=RETRIEVED, last=RETRIEVED))
        self.assertIs(info["online"], True)
        self.assertEqual(issues(info), ["holdings_date"])
        self.assertEqual(issues(run(markets=("US",))[0]["markets"]["US"]), [])

    def test_ken_french_outage_keeps_the_market_on_the_pinned_definition(self):
        sources = Sources(failing={"ken-french-siccodes12"})
        result, _, _ = run(sources, markets=("US",))
        info = result["markets"]["US"]
        self.assertEqual((result["status"], info["status"]), ("ok", "ok"))
        self.assertEqual(info["ff12Hash"], sectors.FF12_DEFINITION_SHA256)
        self.assertIn("HTTP 503", info["ff12Fallback"])
        self.assertIsNone(info["ff12Changed"])
        self.assertEqual(issues(info), ["ff12_stored_original"])
        french = [s for s in result["sources"] if s["key"] == "ken-french-siccodes12"]
        self.assertEqual(
            [s["sha256"] for s in french], [digest(fixture("Siccodes12.zip"))]
        )
        self.assertEqual(by_id(result)["US:0001652044"]["sector"], "BusEq")

    def test_changed_ken_french_definition_keeps_the_market_on_the_pin(self):
        # L5: a changed Siccodes12 never leaves the US off the pinned definition while
        # a pinned original is stored; only without one does the change stand.
        text = zipfile.ZipFile(io.BytesIO(fixture("Siccodes12.zip"))).read(
            "Siccodes12.txt"
        )
        changed = siccodes(text.replace(b"5000-5999", b"5000-5998"))
        sources = Sources(downloads={"ken-french-siccodes12": changed})
        result, _, _ = run(sources, markets=("US",))
        info = result["markets"]["US"]
        self.assertEqual((result["status"], info["status"]), ("ok", "ok"))
        self.assertEqual(info["ff12Hash"], sectors.FF12_DEFINITION_SHA256)
        self.assertEqual(issues(info), ["ff12_definition_changed_pinned_used"])
        self.assertIn(digest(changed)[:16], info["issues"][0]["detail"])
        self.assertEqual(info["ff12Changed"]["sha256"], digest(changed))
        self.assertIsNone(info["ff12Fallback"])
        french = [s for s in result["sources"] if s["key"] == "ken-french-siccodes12"]
        self.assertEqual(
            [s["sha256"] for s in french], [digest(fixture("Siccodes12.zip"))]
        )
        unkept = Sources(
            **{"ken-french-siccodes12": changed},
            **{"ken-french-siccodes12-pinned": FetchError("No stored original")},
        )
        result, _, _ = run(unkept, markets=("US",))
        info = result["markets"]["US"]
        self.assertNotEqual(info["ff12Hash"], sectors.FF12_DEFINITION_SHA256)
        self.assertEqual(issues(info), ["ff12_definition_changed"])
        self.assertIsNone(info["ff12Changed"])

    def test_an_offline_build_names_the_changed_definition_stored(self):
        """L7: offline the changed Siccodes12 is the latest stored original, never a
        download: the issue detail says so."""
        text = zipfile.ZipFile(io.BytesIO(fixture("Siccodes12.zip"))).read(
            "Siccodes12.txt"
        )
        changed = siccodes(text.replace(b"5000-5999", b"5000-5998"))
        online, _, _ = run(
            Sources(downloads={"ken-french-siccodes12": changed}), markets=("US",)
        )
        offline, _, _ = run(
            Sources(**{"ken-french-siccodes12": changed}),
            markets=("US",),
            online=False,
            env="",
        )
        for result, word in ((online, "downloaded"), (offline, "stored")):
            with self.subTest(word=word):
                info = result["markets"]["US"]
                self.assertEqual(issues(info), ["ff12_definition_changed_pinned_used"])
                self.assertEqual(info["ff12Hash"], sectors.FF12_DEFINITION_SHA256)
                self.assertTrue(
                    info["issues"][0]["detail"].startswith(
                        f"{word} Siccodes12 {digest(changed)[:16]} (retrieved "
                    ),
                    info["issues"][0]["detail"],
                )

    def test_profile_failures_keep_issuers_eligible_and_fail_the_market(self):
        apple = json.loads(fixture("submissions-0000320193.json"))
        overrides = {
            "sec-submissions-0000320193": dict(apple, cik="0001652044"),
            "sec-submissions-0000014693": dict(
                json.loads(fixture("submissions-0000014693.json")), sic=""
            ),
            "sec-submissions-0001045810": FetchError(
                "SEC: HTTP 404 for sec-submissions-0001045810"
            ),
        }
        result, _, _ = run(Sources(**overrides), markets=("US",))
        members = by_id(result)
        expected = {
            "US:0000320193": "submissions_mismatch",
            "US:0000014693": "missing_sic",
            "US:0001045810": "submissions_unavailable",
        }
        for member_id, step in expected.items():
            member = members[member_id]
            self.assertEqual(
                (member["status"], member["reason"], member["fetchError"]),
                ("eligible", None, step),
                member_id,
            )
            self.assertEqual(member["issues"], [FETCH_ERROR])
        self.assertIsNone(members["US:0000014693"]["sector"])
        self.assertIn("HTTP 404", members["US:0001045810"]["error"])
        self.assertEqual(members["US:0000019617"]["reason"], "financial_sic")
        info = result["markets"]["US"]
        self.assertEqual(
            info["counts"],
            dict(
                members=6,
                eligible=4,
                excluded=dict(financial_sic=2),
                fetchErrors=dict(
                    missing_sic=1, submissions_mismatch=1, submissions_unavailable=1
                ),
                fetchErrorRate=0.75,
            ),
        )
        # Three of four non-financial issuers unprofiled: a retry, not a universe.
        self.assertEqual((info["status"], result["status"]), ("error", "error"))
        self.assertIn("3 of 4 non-financial members", info["error"])
        with self.assertRaisesRegex(ValueError, "market error"):
            universe.save(result)

    def test_fetch_error_limit_is_a_share_of_non_financial_members(self):
        tickers = json.loads(fixture("company_tickers.json"))
        tickers = {k: v for k, v in tickers.items() if v["ticker"] != "AAPL"}
        sources = Sources(**{"sec-company-tickers": tickers})
        with mock.patch.object(universe, "FETCH_ERROR_LIMIT", 0.25):
            result, _, _ = run(sources, markets=("US",))
        apple = by_id(result)["US:AAPL"]
        self.assertEqual(
            (apple["cik"], apple["status"], apple["fetchError"], apple["rank"]),
            (None, "eligible", "missing_cik", 2),
        )
        self.assertIn("not in SEC company_tickers", apple["error"])
        info = result["markets"]["US"]
        self.assertEqual(info["counts"]["fetchErrorRate"], 0.25)
        self.assertEqual(info["status"], "ok")  # 1 of 4 is at the limit, not above
        with mock.patch.object(universe, "FETCH_ERROR_LIMIT", 0.24):
            result, _, _ = run(Sources(**{"sec-company-tickers": tickers}), ("US",))
        self.assertEqual(result["markets"]["US"]["status"], "error")
        self.assertEqual(universe.FETCH_ERROR_LIMIT, 0.05)

    def test_limit_counts_issuers_without_cik_by_weight(self):
        tickers = json.loads(fixture("company_tickers.json"))
        tickers = {k: v for k, v in tickers.items() if v["ticker"] != "NVDA"}
        result, sources, _ = run(
            Sources(**{"sec-company-tickers": tickers}), markets=("US",), limit=2
        )
        self.assertEqual(
            [m["id"] for m in result["members"]], ["US:NVDA", "US:0000320193"]
        )
        profiled = [c["key"] for c in sources.calls if "submissions" in c["key"]]
        self.assertEqual(profiled, ["sec-submissions-0000320193"])

    def test_source_failure_marks_the_market_and_blocks_saving(self):
        failure = FetchError("SSGA: HTTP 503 for ssga-spy-holdings")
        result, _, _ = run(Sources(**{"ssga-spy-holdings": failure}), markets=("US",))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["markets"]["US"]["status"], "error")
        self.assertIn("HTTP 503", result["markets"]["US"]["error"])
        self.assertEqual(result["members"], [])
        with self.assertRaisesRegex(ValueError, "market error"):
            universe.save(result)

    def test_non_spreadsheet_response_is_a_market_error(self):
        blocked = b"<html><body>Request blocked</body></html>"
        result, _, _ = run(Sources(**{"ssga-spy-holdings": blocked}), markets=("US",))
        self.assertIn("BadZipFile", result["markets"]["US"]["error"])
        garbled = dict(page(1), stocks="unexpected")
        result, _, _ = run(
            Sources(**{"naver-kospi-marketvalue-p1": garbled}), markets=("KR",)
        )
        self.assertEqual(result["markets"]["KR"]["status"], "error")

    def test_online_sec_requests_need_a_declared_contact(self):
        result, _, _ = run(markets=("US",), env="")
        self.assertIn("SEC_USER_AGENT", result["markets"]["US"]["error"])
        result, sources, _ = run(markets=("US",), env="", online=False)
        self.assertEqual(result["markets"]["US"]["status"], "ok")
        self.assertTrue(all(c["headers"] is None for c in sources.calls))


class KrUniverseTests(unittest.TestCase):
    def test_top_commons_by_market_cap_at_the_close_of_t(self):
        result, sources, key_loader = run(markets=("KR",))
        self.assertEqual(result["status"], "ok")
        key_loader.assert_called_once_with()
        members = by_id(result)
        self.assertEqual([m["rank"] for m in result["members"]], list(range(1, 11)))
        self.assertNotIn("KR:004990", members)  # rank 11 when the top is 10
        samsung = members["KR:005930"]
        # Listed shares = KRW market value / price of the Naver row (~5.85e9 commons);
        # each class priced at its own Yahoo close of T (real originals, 2026-10-02).
        self.assertEqual(
            samsung["shareClasses"],
            [
                dict(
                    ticker="005930",
                    priceSymbol="005930.KS",
                    kind="common",
                    listedShares=5_846_278_608,
                    rankingClose=276_000.0,
                    rankingProxy=False,
                ),
                dict(
                    ticker="005935",
                    priceSymbol="005935.KS",
                    kind="preferred",
                    listedShares=802_371_203,
                    rankingClose=201_000.0,
                    rankingProxy=False,
                ),
            ],
        )
        self.assertEqual(samsung["rankMarketCap"], SAMSUNG_CAP)
        self.assertEqual(
            (samsung["poolRank"], samsung["poolMarketValue"]),
            (1, 1_585_803_072_420_000),
        )
        self.assertNotIn("listedShares", samsung)
        self.assertEqual(
            (samsung["corpCode"], samsung["ksic"], samsung["sector"]),
            ("00126380", "264", "BusEq"),
        )
        self.assertEqual(
            (samsung["fiscalYearEnd"], samsung["status"]), ("1231", "eligible")
        )
        self.assertEqual((samsung["issues"], samsung["fetchError"]), ([], None))
        self.assertEqual(samsung["priceSymbol"], "005930.KS")
        hyundai = members["KR:005380"]
        self.assertEqual(
            [(c["ticker"], c["listedShares"]) for c in hyundai["shareClasses"]],
            [("005380", 203_466_492), ("005385", 22_839_037), ("005387", 34_257_047)],
        )
        self.assertEqual(
            hyundai["rankMarketCap"],
            203_466_492 * 347_250.0 + 22_839_037 * 178_600.0 + 34_257_047 * 178_800.0,
        )
        self.assertEqual(
            (hyundai["ksic"], hyundai["sector"], hyundai["status"]),
            ("30121", "Durbl", "eligible"),
        )
        hynix = members["KR:000660"]
        self.assertEqual((hynix["ksic"], hynix["sector"]), ("2612", "BusEq"))
        for code in ("105560", "055550"):
            member = members[f"KR:{code}"]
            self.assertEqual(
                (member["ksic"], member["sector"], member["reason"]),
                ("64992", "Money", "financial_holding"),
            )
        for code in ("034730", "003550", "0126Z0"):
            member = members[f"KR:{code}"]
            self.assertEqual(
                (member["sector"], member["status"]), ("Other", "eligible")
            )
        self.assertEqual(members["KR:0126Z0"]["priceSymbol"], "0126Z0.KS")
        self.assertEqual(members["KR:005490"]["sector"], "Manuf")
        self.assertEqual(
            (members["KR:088980"]["sector"], members["KR:088980"]["reason"]),
            ("Money", "financial_ksic"),
        )
        info = result["markets"]["KR"]
        self.assertEqual(info["rankingBasis"], "T_close")
        self.assertEqual(
            (info["candidatePool"], info["candidates"], info["ranked"]), (13, 11, 11)
        )
        self.assertEqual(info["unranked"], [])
        self.assertEqual(
            info["outside"],
            [
                dict(
                    code="004990",
                    name="롯데지주",
                    rank=11,
                    rankMarketCap=2327149169600.0,
                )
            ],
        )
        self.assertEqual(info["filtered"], dict(etf=1, etn=1, other_class=3, reit=1))
        self.assertEqual(
            info["nameExcluded"],
            [
                dict(
                    code="395400", name="SK리츠", rule="reit", marketValue=1592383209800
                )
            ],
        )
        self.assertEqual((info["totalCount"], info["rows"], info["pages"]), (17, 17, 3))
        self.assertEqual(info["commons"], 11)
        self.assertEqual(
            info["counts"],
            dict(
                members=10,
                eligible=7,
                excluded=dict(financial_holding=2, financial_ksic=1),
                fetchErrors={},
                fetchErrorRate=0.0,
            ),
        )
        # Naver reported OPEN (after-hours trading); that no longer matters (D5').
        self.assertEqual((info["marketStatus"], info["issues"]), ("OPEN", []))
        # Captured from the first Naver page to the last price series (Samsung's pref).
        self.assertEqual(
            info["capturedAt"],
            dict(first=RETRIEVED, last=REAL_YAHOO["005935.KS"][1]),
        )
        self.assertEqual(info["rankingCapturedAt"], info["capturedAt"])
        # Every candidate's classes were priced through T, the classes of all 11.
        self.assertEqual(
            sorted(sources.keys("yahoo-")),
            sorted(
                yahoo_key(f"{code}.KS", "2026-10-02")
                for code in (
                    "005930 005935 000660 005380 005385 005387 105560 055550 034730 "
                    "005490 003550 0126Z0 088980 004990"
                ).split()
            ),
        )
        stored = [c for c in sources.calls if c.get("stored")]
        self.assertEqual(stored[0]["key"], "dart-corpcode")
        self.assertEqual(stored[0]["suffix"], ".zip")
        self.assertTrue(all("crtfc_key" not in c["url"] for c in stored))
        self.assertIn(
            "https://opendart.fss.or.kr/api/company.json?corp_code=00126380",
            [c["url"] for c in stored],
        )
        reference = next(s for s in result["sources"] if s["key"] == "ksic-ff12")
        self.assertEqual(
            reference["sha256"], digest(sectors.KSIC_REFERENCE.read_bytes())
        )
        series = [s for s in info["sources"] if s["key"].startswith("yahoo-")]
        self.assertEqual(len(series), 14)

    def test_membership_follows_the_close_of_t_not_the_naver_price(self):
        # At five times its Naver price on T, 롯데지주 (11th by Naver value) passes
        # 삼성에피스홀딩스 and 맥쿼리인프라; the 10th by Naver value leaves the top 10.
        closes = {"004990.KS": 23_350 * 5}
        # Constructed company.json for 롯데지주 (no OpenDART original in the fixtures).
        lotte = {"dart-company-00120562": LOTTE_COMPANY}
        result, _, _ = run(Sources(closes=closes, **lotte), markets=("KR",))
        self.assertEqual(result["status"], "ok")
        ranked = [(m["ticker"], m["rank"], m["poolRank"]) for m in result["members"]]
        self.assertEqual(
            ranked[7:],
            [("003550", 8, 8), ("004990", 9, 11), ("0126Z0", 10, 9)],
        )
        member = by_id(result)["KR:004990"]
        self.assertEqual(member["rankMarketCap"], 99_663_776 * 116_750.0)
        self.assertEqual((member["sector"], member["status"]), ("Other", "eligible"))
        self.assertEqual(
            [o["code"] for o in result["markets"]["KR"]["outside"]], ["088980"]
        )
        # A company outside the candidate pool is never priced or ranked.
        result, sources, _ = run(
            Sources(closes=closes, **lotte), markets=("KR",), pool=10
        )
        self.assertNotIn("KR:004990", by_id(result))
        self.assertIn("KR:088980", by_id(result))
        self.assertEqual(result["markets"]["KR"]["candidates"], 10)
        self.assertNotIn(yahoo_key("004990.KS", "2026-10-02"), sources.keys("yahoo-"))

    def test_candidates_without_a_close_on_t_are_left_unranked(self):
        # M3: only a halt (a settled series without T) and a confirmed HTTP 404 (every
        # Yahoo host) leave a candidate unranked.
        lg = yahoo_key("003550.KS", "2026-10-02")
        unknown = FetchError(f"Yahoo Finance: HTTP 404 for {lg}")
        sources = Sources(halted={"005490.KS"}, **{lg: unknown})
        result, _, _ = run(sources, markets=("KR",), top=8)
        info = result["markets"]["KR"]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            [(u["code"], u["poolRank"], u["reason"]) for u in info["unranked"]],
            [
                ("005490", 7, "no_close_on_as_of"),
                ("003550", 8, "symbol_not_found"),
            ],
        )
        self.assertIn("last session 2026-10-01", info["unranked"][0]["detail"])
        self.assertEqual(
            info["unranked"][1]["detail"],
            f"query2: {unknown}; query1: {unknown}",
        )
        self.assertEqual(
            universe.UNRANKED_REASONS,
            ("no_close_on_as_of", "symbol_not_found", "not_listed_on_as_of"),
        )
        self.assertEqual(
            issues(info), ["candidate_unranked", "candidate_unranked"]
        )  # never a stale close, never silent
        self.assertEqual(
            [m["ticker"] for m in result["members"]],
            "005930 000660 005380 105560 055550 034730 0126Z0 088980".split(),
        )
        self.assertEqual(info["ranked"], 9)
        # Fewer ranked candidates than the top: the market is an error (rebuild).
        sources = Sources(halted={"005490.KS"}, **{lg: unknown})
        result, _, _ = run(sources, markets=("KR",), top=10)
        info = result["markets"]["KR"]
        self.assertEqual((result["status"], info["status"]), ("error", "error"))
        self.assertIn(
            "only 9 of 11 candidates have a close on 2026-10-02", info["error"]
        )

    def test_a_failed_download_never_removes_a_candidate(self):
        # M3 (D6): LG's common cannot be priced for any other reason, so the KR market
        # is an error to rebuild; the 201st company never takes its place.
        lg = yahoo_key("003550.KS", "2026-10-02")
        not_found = FetchError(f"Yahoo Finance: HTTP 404 for {lg}")
        unavailable = FetchError(f"Yahoo Finance: HTTP 503 for {lg}")
        refused = dict(chart=dict(result=None, error=dict(code="Too Many Requests")))
        cases = {
            "HTTP 503 on both hosts": Sources(failing={lg}),
            "HTTP 404 on one host only": Sources(
                hosts={lg: dict(query2=not_found, query1=unavailable)}
            ),
            "timeout": Sources(
                **{lg: FetchError(f"Yahoo Finance: TimeoutError for {lg}")}
            ),
            "rejected original": Sources(**{lg: refused}),
            "a 404 worded otherwise": Sources(**{lg: FetchError("HTTP 404 (LG)")}),
        }
        for label, sources in cases.items():
            result, _, _ = run(sources, markets=("KR",), top=8)
            info = result["markets"]["KR"]
            self.assertEqual(
                (result["status"], info["status"]), ("error", "error"), label
            )
            self.assertIn(
                "KR candidate 003550 LG (pool rank 8): 003550.KS price_unavailable",
                info["error"],
                label,
            )
            self.assertIn("never removes a candidate", info["error"], label)
            self.assertTrue(info["error"].endswith("rebuild"), label)
            self.assertEqual(result["members"], [], label)
        # An offline replay without the stored original is no confirmed 404 either.
        missing = Sources(**{lg: FetchError(f"No stored original for {lg}")})
        result, _, _ = run(missing, markets=("KR",), top=8, online=False, env="")
        self.assertIn("003550.KS price_unavailable", result["markets"]["KR"]["error"])

    def test_a_chart_without_a_session_through_t_leaves_the_candidate_unranked(self):
        """N1: a Yahoo chart of the right symbol in KRW, read after T's closes settled,
        without a settled session in the whole window through T (listed after T, or
        halted for the whole window) is not a failed download: the candidate is left
        unranked as not_listed_on_as_of, so the KR part can still be built."""
        posco = yahoo_key("005490.KS", "2026-10-02")
        meta = dict(
            symbol="005490.KS", currency="KRW", exchangeTimezoneName="Asia/Seoul"
        )
        weekdays = [
            d.isoformat()
            for d in (date(2026, 9, 21) + timedelta(days=n) for n in range(12))
            if d.weekday() < 5
        ]
        nulls = dict(  # Yahoo's halted sessions: stamps without closes
            meta=meta,
            timestamp=[
                int(datetime.fromisoformat(f"{d}T09:00:00+09:00").timestamp())
                for d in weekdays
            ],
            indicators=dict(
                quote=[dict(close=[None] * len(weekdays))],
                adjclose=[dict(adjclose=[None] * len(weekdays))],
            ),
        )
        cases = {
            # listed on Mon Oct 5: the chart's only session is after T (Fri Oct 2)
            "listed after T": (
                chart("005490.KS", {"2026-10-05": 300_000}),
                "no settled sessions between 2025-08-28 and 2026-10-02 (next session "
                "2026-10-05)",
            ),
            "no stamp in the window": (
                dict(chart=dict(result=[dict(meta=meta)], error=None)),
                "no settled sessions between 2025-08-28 and 2026-10-02",
            ),
            "only null closes": (
                dict(chart=dict(result=[nulls], error=None)),
                "dropped 10 null-close session(s)",
            ),
        }
        for label, (blob, detail) in cases.items():
            with self.subTest(label):
                result, _, _ = run(Sources(**{posco: blob}), markets=("KR",), top=8)
                info = result["markets"]["KR"]
                self.assertEqual((result["status"], info["status"]), ("ok", "ok"))
                self.assertEqual(
                    [(u["code"], u["poolRank"], u["reason"]) for u in info["unranked"]],
                    [("005490", 7, "not_listed_on_as_of")],
                )
                self.assertIn(detail, info["unranked"][0]["detail"])
                self.assertIn(
                    "query2: rejected original (NoSessions",
                    info["unranked"][0]["detail"],
                )
                self.assertIn(
                    "query1: rejected original (NoSessions",
                    info["unranked"][0]["detail"],
                )
                self.assertEqual(issues(info), ["candidate_unranked"])
                self.assertNotIn("KR:005490", by_id(result))
                self.assertEqual(info["ranked"], 10)
                # The original that answered is kept with the capture.
                self.assertIn(
                    digest(json.dumps(blob).encode()),
                    [s["sha256"] for s in info["sources"]],
                )
        self.assertIn("not_listed_on_as_of", universe.UNRANKED_REASONS)
        # Both hosts must answer so (or with HTTP 404); offline the stored one does.
        empty = cases["listed after T"][0]
        not_found = FetchError(f"Yahoo Finance: HTTP 404 for {posco}")
        sources = Sources(**{posco: empty}, hosts={posco: dict(query1=not_found)})
        result, _, _ = run(sources, markets=("KR",), top=8)
        self.assertEqual(
            [u["reason"] for u in result["markets"]["KR"]["unranked"]],
            ["not_listed_on_as_of"],
        )
        result, _, _ = run(
            Sources(**{posco: empty}), markets=("KR",), top=8, online=False, env=""
        )
        self.assertEqual(
            [u["reason"] for u in result["markets"]["KR"]["unranked"]],
            ["not_listed_on_as_of"],
        )

    def test_an_empty_chart_is_no_answer_when_anything_else_fails(self):
        """N1: a symbol or currency mismatch, an undecodable response, a transient
        failure on the other host or a chart read before T's closes settled is never
        "not listed": the KR part is an error and is rebuilt."""
        posco = yahoo_key("005490.KS", "2026-10-02")
        empty = chart("005490.KS", {"2026-10-05": 300_000})
        other = copy.deepcopy(empty)
        other["chart"]["result"][0]["meta"]["symbol"] = "005491.KS"
        dollars = copy.deepcopy(empty)
        dollars["chart"]["result"][0]["meta"]["currency"] = "USD"
        timeout = FetchError(f"Yahoo Finance: TimeoutError for {posco}")
        cases = {
            "another symbol": Sources(**{posco: other}),
            "another currency": Sources(**{posco: dollars}),
            "undecodable": Sources(**{posco: b"<html>busy</html>"}),
            "a timeout on query1": Sources(
                **{posco: empty}, hosts={posco: dict(query1=timeout)}
            ),
            "HTTP 503 on query1": Sources(
                **{posco: empty},
                hosts={
                    posco: dict(
                        query1=FetchError(f"Yahoo Finance: HTTP 503 for {posco}")
                    )
                },
            ),
        }
        for label, sources in cases.items():
            with self.subTest(label):
                result, _, _ = run(sources, markets=("KR",), top=8)
                info = result["markets"]["KR"]
                self.assertEqual((result["status"], info["status"]), ("error", "error"))
                self.assertIn(
                    "KR candidate 005490 POSCO홀딩스 (pool rank 7): 005490.KS "
                    "price_unavailable",
                    info["error"],
                )
                self.assertTrue(info["error"].endswith("rebuild"))
        # Read after the close but before the closes settle (18:00 KST): a capture
        # error to rebuild, never "not listed".
        late = yahoo_key("005490.KS", "2026-10-06")
        times = dict(naver=AFTER_CLOSE, yahoo=SETTLED, **{late: AFTER_CLOSE})
        sources = Sources(
            real_yahoo=False,
            times=times,
            **{late: chart("005490.KS", {"2026-10-07": 300_000})},
        )
        result, _, _ = run(sources, markets=("KR",), as_of="2026-10-06", top=8)
        info = result["markets"]["KR"]
        self.assertEqual((result["status"], info["status"]), ("error", "error"))
        self.assertIn(
            "005490.KS close_unsettled (retrieved 2026-10-06T07:00", info["error"]
        )
        self.assertTrue(info["error"].endswith("rebuild after the closes settle"))

    def test_a_listing_after_t_is_read_through_the_build_date(self):
        """M1: the KR ranking series are requested through the build's Asia/Seoul
        date, not T+2. POSCO, here first traded on Mon Oct 5, shows that session after
        T (Fri Oct 2) when built on Oct 6; built on T's evening Yahoo answers HTTP 400
        "Data doesn't exist" on both hosts. Either way it is not_listed_on_as_of, never
        a failed download that fails the KR part."""
        for built_on, detail in (
            ("2026-10-06", "2026-10-02 (next session 2026-10-05))"),
            ("2026-10-02", "2026-10-02 (HTTP 400: Data doesn't exist for startDate = "),
        ):
            with self.subTest(built_on=built_on):
                sources = Sources(listed={"005490.KS": "2026-10-05"})
                result, _, _ = run(sources, markets=("KR",), top=8, built_on=built_on)
                info = result["markets"]["KR"]
                self.assertEqual((result["status"], info["status"]), ("ok", "ok"))
                self.assertEqual(
                    [(u["code"], u["poolRank"], u["reason"]) for u in info["unranked"]],
                    [("005490", 7, "not_listed_on_as_of")],
                )
                for host in ("query2", "query1"):
                    self.assertIn(
                        f"{host}: rejected original (NoSessions: no settled sessions "
                        f"between 2025-08-28 and {detail}",
                        info["unranked"][0]["detail"],
                    )
                self.assertEqual(info["closesRequestedThrough"], built_on)
                self.assertEqual(info["ranked"], 10)
                # Every ranking series keeps its window and key of T; only the
                # request runs through the build's date (+2 days, prices._url).
                end = date.fromisoformat(built_on) + timedelta(days=2)
                end = int(
                    datetime(
                        end.year, end.month, end.day, tzinfo=timezone.utc
                    ).timestamp()
                )
                calls = [c for c in sources.calls if c["key"].startswith("yahoo-")]
                posco = [
                    urlsplit(c["url"]).netloc.split(".")[0]
                    for c in calls
                    if c["key"] == yahoo_key("005490.KS", "2026-10-02")
                ]
                self.assertEqual(posco, ["query2", "query1"])  # every host answers
                self.assertGreaterEqual(len(calls), 13)  # the candidate pool
                for call in calls:
                    self.assertTrue(call["key"].endswith("-2026-10-02"), call["key"])
                    query = dict(parse_qsl(urlsplit(call["url"]).query))
                    self.assertEqual(int(query["period2"]), end, call["url"])
        # Offline the stored originals are replayed as they were requested.
        result, _, _ = run(online=False, env="", markets=("KR",), top=8)
        self.assertIsNone(result["markets"]["KR"]["closesRequestedThrough"])

    def test_the_live_no_data_answer_of_every_host_leaves_the_candidate_unranked(self):
        """M1: Yahoo's HTTP 400 "Data doesn't exist" body (the exact live answer, kept
        as an original) on every host is an answer without sessions, alone or with
        HTTP 404 from the other host; with a transient failure on the other host, as
        another HTTP 400 body or read before T's closes settle it fails the KR part."""
        posco = yahoo_key("005490.KS", "2026-10-02")
        not_found = FetchError(f"Yahoo Finance: HTTP 404 for {posco}")
        cases = {
            "both hosts": Sources(kept={posco: LIVE_400}),
            "HTTP 404 on query1": Sources(
                kept={posco: LIVE_400}, hosts={posco: dict(query1=not_found)}
            ),
        }
        for label, sources in cases.items():
            with self.subTest(label):
                result, _, _ = run(sources, markets=("KR",), top=8)
                info = result["markets"]["KR"]
                self.assertEqual((result["status"], info["status"]), ("ok", "ok"))
                self.assertEqual(
                    [(u["code"], u["poolRank"], u["reason"]) for u in info["unranked"]],
                    [("005490", 7, "not_listed_on_as_of")],
                )
                self.assertIn(
                    "query2: rejected original (NoSessions: no settled sessions between "
                    "2025-08-28 and 2026-10-02 (HTTP 400: Data doesn't exist for "
                    "startDate = 1748703600, endDate = 1763564400))",
                    info["unranked"][0]["detail"],
                )
                self.assertEqual(issues(info), ["candidate_unranked"])
                kept = [s for s in info["sources"] if s["sha256"] == digest(LIVE_400)]
                self.assertEqual([s.get("httpStatus") for s in kept], [400])
        # Offline: the stored answer (its pointer keeps httpStatus 400) answers so.
        result, _, _ = run(
            Sources(kept={posco: LIVE_400}),
            markets=("KR",),
            top=8,
            online=False,
            env="",
        )
        self.assertEqual(
            [u["reason"] for u in result["markets"]["KR"]["unranked"]],
            ["not_listed_on_as_of"],
        )
        other = LIVE_400.replace(b"Data doesn't exist", b"Invalid input")
        failing = {
            "HTTP 503 on query1": Sources(
                kept={posco: LIVE_400},
                hosts={
                    posco: dict(
                        query1=FetchError(f"Yahoo Finance: HTTP 503 for {posco}")
                    )
                },
            ),
            "another HTTP 400 body": Sources(kept={posco: other}),
        }
        for label, sources in failing.items():
            with self.subTest(label):
                result, _, _ = run(sources, markets=("KR",), top=8)
                info = result["markets"]["KR"]
                self.assertEqual((result["status"], info["status"]), ("error", "error"))
                self.assertIn("005490.KS price_unavailable", info["error"])
                self.assertTrue(info["error"].endswith("rebuild"))
        # Read after the close but before the closes settle: rebuild, never "not listed".
        late = yahoo_key("005490.KS", "2026-10-06")
        sources = Sources(
            real_yahoo=False,
            times=dict(naver=AFTER_CLOSE, yahoo=SETTLED, **{late: AFTER_CLOSE}),
            kept={late: LIVE_400},
        )
        result, _, _ = run(sources, markets=("KR",), as_of="2026-10-06", top=8)
        info = result["markets"]["KR"]
        self.assertEqual((result["status"], info["status"]), ("error", "error"))
        self.assertIn(
            "005490.KS close_unsettled (retrieved 2026-10-06T07:00", info["error"]
        )

    def test_the_build_date_is_seoul_local(self):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):  # 00:30 KST on Oct 3, 11:30 New York on Oct 2
                moment = datetime(2026, 10, 2, 15, 30, tzinfo=timezone.utc)
                return moment if tz is None else moment.astimezone(tz)

        with mock.patch.object(universe, "datetime", Clock):
            self.assertEqual(universe._local_date("KR"), "2026-10-03")
            self.assertEqual(universe._local_date("US"), "2026-10-02")

    def test_a_series_read_before_the_closes_settle_is_never_a_halt(self):
        # After the 15:30 close but before 18:00 KST a series drops T as unsettled: a
        # capture error to rebuild later, not a halt that leaves the candidate out.
        settled = dict(naver=AFTER_CLOSE, yahoo=SETTLED)
        early = {yahoo_key("005490.KS", "2026-10-06"): AFTER_CLOSE}
        sources = Sources(real_yahoo=False, times=dict(settled, **early))
        result, _, _ = run(sources, markets=("KR",), as_of="2026-10-06", top=8)
        info = result["markets"]["KR"]
        self.assertEqual((result["status"], info["status"]), ("error", "error"))
        self.assertIn(
            "005490.KS close_unsettled (retrieved 2026-10-06T07:00:00+00:00, before "
            "the closes settle at 2026-10-06T18:00:00+09:00)",
            info["error"],
        )
        self.assertTrue(info["error"].endswith("rebuild after the closes settle"))
        # A preferred class read too early is no proxy at the common close either.
        early = {yahoo_key("005385.KS", "2026-10-06"): AFTER_CLOSE}
        sources = Sources(real_yahoo=False, times=dict(settled, **early))
        result, _, _ = run(sources, markets=("KR",), as_of="2026-10-06", top=8)
        self.assertIn("005385.KS close_unsettled", result["markets"]["KR"]["error"])
        # A settled series without T is a halt: left unranked.
        sources = Sources(real_yahoo=False, times=settled, halted={"005490.KS"})
        result, _, _ = run(sources, markets=("KR",), as_of="2026-10-06", top=8)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            [u["reason"] for u in result["markets"]["KR"]["unranked"]],
            ["no_close_on_as_of"],
        )

    def test_a_class_without_listed_shares_is_a_market_error(self):
        pages = naver_pages()
        for body in pages.values():
            for row in body["stocks"]:
                if row["itemCode"] == "005385":  # 현대차우: Naver price 0
                    row.update(closePrice="0", closePriceRaw="0")
        result, _, _ = run(Sources(**pages), markets=("KR",), top=8)
        info = result["markets"]["KR"]
        self.assertEqual((result["status"], info["status"]), ("error", "error"))
        self.assertIn(
            "KR candidate 005380 현대차 (pool rank 3): no listed shares for 005385",
            info["error"],
        )

    def test_class_without_its_own_close_is_ranked_at_the_common_close(self):
        sources = Sources(
            halted={"005387.KS"},
            **{yahoo_key("005385.KS", "2026-10-02"): FetchError("HTTP 404 (pref)")},
        )
        result, _, _ = run(sources, markets=("KR",))
        hyundai = by_id(result)["KR:005380"]
        self.assertEqual(
            [
                (c["ticker"], c["rankingClose"], c["rankingProxy"])
                for c in hyundai["shareClasses"]
            ],
            [
                ("005380", 347_250.0, False),
                ("005385", 347_250.0, True),
                ("005387", 347_250.0, True),
            ],
        )
        self.assertEqual(
            hyundai["rankMarketCap"],
            (203_466_492 + 22_839_037 + 34_257_047) * 347_250.0,
        )
        proxies = [
            i["detail"]
            for i in result["markets"]["KR"]["issues"]
            if i["issue"] == "class_price_proxy"
        ]
        self.assertEqual(len(proxies), 2)
        self.assertIn(
            "005385 ranked at the 005380 close (price_unavailable", proxies[0]
        )
        self.assertIn(
            "005387 ranked at the 005380 close (no_close_on_as_of", proxies[1]
        )

    def test_capture_must_follow_the_close_of_t(self):
        # Naver read during T's session: the market fails before any price is fetched.
        result, sources, _ = run(markets=("KR",), as_of="2026-10-06")
        info = result["markets"]["KR"]
        self.assertEqual((result["status"], info["status"]), ("error", "error"))
        self.assertIn("not after the 2026-10-06 close", info["error"])
        self.assertEqual(sources.keys("yahoo-"), [])
        # Naver after the close, but a price series read during the session.
        late_naver = Sources(times=dict(naver=AFTER_CLOSE, yahoo=SETTLED))
        result, _, _ = run(late_naver, markets=("KR",), as_of="2026-10-06")
        error = result["markets"]["KR"]["error"]
        self.assertIn(
            "005930.KS close_unsettled (retrieved 2026-10-06T04:11:57.126016+00:00",
            error,
        )
        # After the close but before the closes settle (18:00 KST): nothing is ranked.
        early = Sources(
            real_yahoo=False, times=dict(naver=AFTER_CLOSE, yahoo=AFTER_CLOSE)
        )
        result, _, _ = run(early, markets=("KR",), as_of="2026-10-06")
        error = result["markets"]["KR"]["error"]
        self.assertIn("005930.KS close_unsettled (retrieved 2026-10-06T07:00:00", error)
        self.assertIn("settle at 2026-10-06T18:00:00+09:00", error)
        # Settled closes: the ranking is T's, and the capture times are recorded.
        settled = Sources(
            real_yahoo=False, times=dict(naver=AFTER_CLOSE, yahoo=SETTLED)
        )
        result, _, _ = run(settled, markets=("KR",), as_of="2026-10-06")
        info = result["markets"]["KR"]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(info["capturedAt"], dict(first=AFTER_CLOSE, last=SETTLED))
        self.assertEqual(info["rankingCapturedAt"], info["capturedAt"])
        self.assertEqual(
            (info["rankingRetrievedAt"], info["closesRetrievedAt"]),
            (
                dict(first=AFTER_CLOSE, last=AFTER_CLOSE),
                dict(first=SETTLED, last=SETTLED),
            ),
        )
        self.assertEqual(
            (info["marketStatus"], info["pricedAt"], info["issues"]),
            ("OPEN", "2026-10-06T13:11:22+09:00", []),
        )
        self.assertEqual(
            universe.market_close("KR", "2026-10-06").isoformat(),
            "2026-10-06T15:30:00+09:00",
        )

    def test_smoke_build_ranks_by_naver_value_without_prices(self):
        result, sources, _ = run(markets=("KR",), as_of="2026-10-06", limit=3)
        info = result["markets"]["KR"]
        self.assertEqual(
            (result["status"], info["rankingBasis"]), ("ok", "naver_value")
        )
        self.assertEqual(
            [(m["ticker"], m["rank"], m["rankMarketCap"]) for m in result["members"]],
            [("005930", 1, None), ("000660", 2, None), ("005380", 3, None)],
        )
        self.assertEqual(sources.keys("yahoo-"), [])
        self.assertNotIn("rankingClose", result["members"][0]["shareClasses"][0])
        self.assertEqual(issues(info), ["ranking_captured_before_close"])
        self.assertNotIn("unranked", info)

    def test_common_filter_rules(self):
        rows = [
            dict(
                code="123450", name="가나스팩1호", type="stock", close=1, marketValue=1
            ),
            dict(code="234560", name="다라리츠", type="stock", close=1, marketValue=2),
            dict(
                code="088260", name="이리츠코크렙", type="stock", close=1, marketValue=3
            ),
            dict(
                code="138040",
                name="메리츠금융지주",
                type="stock",
                close=1,
                marketValue=4,
            ),
            dict(code="0011A0", name="새상장", type="stock", close=1, marketValue=1),
            dict(code="00011K", name="새상장우", type="stock", close=1, marketValue=1),
            dict(code="12345", name="짧은코드", type="stock", close=1, marketValue=1),
            dict(code="069500", name="KODEX 200", type="etf"),
        ]
        excluded = []
        commons, others, filtered = universe.kospi_commons(rows, excluded)
        self.assertEqual([r["code"] for r in commons], ["138040", "0011A0"])
        self.assertEqual(list(others), ["00011"])
        self.assertEqual(
            filtered, dict(etf=1, invalid_code=1, other_class=1, reit=2, spac=1)
        )
        self.assertEqual(
            [(r["code"], r["rule"]) for r in excluded],
            [("123450", "spac"), ("234560", "reit"), ("088260", "reit")],
        )
        self.assertEqual(universe.kospi_commons(rows)[2], filtered)

    def test_meritz_is_ranked_then_excluded_as_a_financial_holding(self):
        # Regression: the substring rule '리츠' dropped 메리츠금융지주 before ranking, so
        # the next company took its top-200 place and it vanished from the exclusions.
        overrides = naver_pages(extra=[MERITZ_ROW])
        overrides["dart-corpcode"] = corpcode_with(
            (MERITZ_CORP, "메리츠금융지주", "138040")
        )
        overrides[f"dart-company-{MERITZ_CORP}"] = MERITZ_COMPANY
        result, _, _ = run(Sources(**overrides), markets=("KR",))
        self.assertEqual(result["status"], "ok")
        members = by_id(result)
        meritz = members["KR:138040"]
        self.assertEqual(
            (meritz["rank"], meritz["status"], meritz["reason"]),
            (8, "excluded", "financial_holding"),
        )
        self.assertEqual(
            (meritz["corpCode"], meritz["ksic"], meritz["sector"]),
            (MERITZ_CORP, "64992", "Money"),
        )
        self.assertEqual(meritz["shareClasses"][0]["listedShares"], 167_347_273)
        self.assertNotIn("KR:088980", members)  # now 11th of the commons
        info = result["markets"]["KR"]
        self.assertEqual([r["code"] for r in info["nameExcluded"]], ["395400"])
        self.assertEqual(info["counts"]["excluded"], dict(financial_holding=3))
        self.assertEqual(info["counts"]["eligible"], 7)

    def test_incomplete_ranking_fails_the_market(self):
        # Page 3 holds 현대차우 (005385): a short or empty last page used to drop that
        # class from 현대차's market value with only a ranking_count note. With the top
        # at 8 every case still yields enough commons, so only completeness catches it.
        cases = {
            "page 3 of 3 is empty": {
                "naver-kospi-marketvalue-p3": dict(page(3), stocks=[])
            },
            "16 rows for totalCount 17": naver_pages(drop=["005385"], total=17),
            "totalCount changed": {
                "naver-kospi-marketvalue-p3": dict(page(3), totalCount=18)
            },
        }
        for message, overrides in cases.items():
            result, _, _ = run(Sources(**overrides), markets=("KR",), top=8)
            info = result["markets"]["KR"]
            self.assertEqual(
                (result["status"], info["status"]), ("error", "error"), message
            )
            self.assertIn(message, info["error"])
            self.assertEqual(result["members"], [])
        result, _, _ = run(markets=("KR",), top=8)  # the complete ranking passes
        self.assertEqual(result["status"], "ok")
        hyundai = by_id(result)["KR:005380"]
        self.assertIn("005385", [c["ticker"] for c in hyundai["shareClasses"]])

    def test_ranking_that_moves_between_pages_fails_the_market(self):
        moved = page(2)
        moved["stocks"][0] = copy.deepcopy(page(1)["stocks"][0])
        result, _, _ = run(
            Sources(**{"naver-kospi-marketvalue-p2": moved}), markets=("KR",)
        )
        self.assertEqual(result["markets"]["KR"]["status"], "error")
        self.assertIn("repeated", result["markets"]["KR"]["error"])

    def test_market_value_unit_is_checked_against_the_display_value(self):
        scaled = page(1)
        row = scaled["stocks"][0]
        row["marketValueRaw"] = str(int(row["marketValueRaw"]) // 10**8)
        result, _, _ = run(
            Sources(**{"naver-kospi-marketvalue-p1": scaled}), markets=("KR",)
        )
        self.assertIn("not in KRW", result["markets"]["KR"]["error"])

    def test_company_profile_failures_keep_members_eligible(self):
        posco = json.loads(fixture("company-00155319.json"))
        lg = json.loads(fixture("company-00120021.json"))
        overrides = {
            "dart-company-00164742": FetchError("fixture: HTTP 404"),
            "dart-company-00155319": dict(posco, induty_code=""),
            "dart-company-00120021": dict(lg, induty_code="9"),
            "dart-company-01965324": {"status": "013", "message": "no data"},
        }
        with mock.patch.object(universe, "FETCH_ERROR_LIMIT", 1.0):
            result, _, _ = run(Sources(**overrides), markets=("KR",))
        members = by_id(result)
        expected = {
            "KR:005380": "company_unavailable",
            "KR:005490": "missing_ksic",
            "KR:003550": "unmapped_ksic",
            "KR:0126Z0": "company_unavailable",
        }
        for member_id, step in expected.items():
            member = members[member_id]
            self.assertEqual(
                (member["status"], member["reason"], member["fetchError"]),
                ("eligible", None, step),
                member_id,
            )
            self.assertEqual(member["issues"], [FETCH_ERROR])
        self.assertIn("withheld", members["KR:005380"]["error"])
        self.assertEqual(members["KR:0126Z0"]["error"], "OpenDART status 013")
        self.assertIsNone(members["KR:003550"]["sector"])
        self.assertEqual(members["KR:105560"]["reason"], "financial_holding")
        counts = result["markets"]["KR"]["counts"]
        self.assertEqual(
            (counts["eligible"], counts["excluded"], counts["fetchErrorRate"]),
            (7, dict(financial_holding=2, financial_ksic=1), round(4 / 7, 6)),
        )
        # A financial KSIC is excluded even where the reference lacks the full code.
        result, _, _ = run(
            Sources(**{"dart-company-00120021": dict(lg, induty_code="649")}),
            markets=("KR",),
        )
        self.assertEqual(by_id(result)["KR:003550"]["reason"], "financial_ksic")
        # With the real limit one failure in seven non-financial members is a retry.
        result, _, _ = run(
            Sources(**{"dart-company-00164742": FetchError("x")}), markets=("KR",)
        )
        info = result["markets"]["KR"]
        self.assertEqual((info["status"], result["status"]), ("error", "error"))
        self.assertIn("1 of 7 non-financial members", info["error"])

    def test_dart_statuses_split_company_and_systemic_failures(self):
        # R13: a company-level status is that member's fetch error; key, IP, quota and
        # maintenance statuses make the whole market an error.
        for status in ("013", "100", "014", "101", "900", None):
            body = {"status": status, "message": "x"} if status else {"message": "x"}
            with mock.patch.object(universe, "FETCH_ERROR_LIMIT", 1.0):
                result, _, _ = run(
                    Sources(**{"dart-company-00126380": body}), markets=("KR",)
                )
            samsung = by_id(result)["KR:005930"]
            self.assertEqual(result["status"], "ok", status)
            self.assertEqual(
                (samsung["status"], samsung["fetchError"], samsung["error"]),
                ("eligible", "company_unavailable", f"OpenDART status {status}"),
            )
        for status in ("010", "011", "012", "020", "021", "800", "901"):
            body = {"status": status, "message": "요청 제한을 초과하였습니다."}
            result, _, _ = run(
                Sources(**{"dart-company-00126380": body}), markets=("KR",)
            )
            self.assertEqual(result["status"], "error", status)
            self.assertIn(f"status {status}", result["markets"]["KR"]["error"])
        body = (
            b"<result><status>010</status><message>unregistered key</message></result>"
        )
        result, _, _ = run(Sources(**{"dart-corpcode": body}), markets=("KR",))
        self.assertIn("status 010", result["markets"]["KR"]["error"])

    def test_only_company_answers_are_stored(self):
        # An error status is not an answer about the company: storing it would make an
        # offline rebuild replay it.
        overrides = {
            "dart-company-00126380": {"status": "900", "message": "undefined"},
            "dart-company-00164779": {"status": "013", "message": "no data"},
        }
        with mock.patch.object(universe, "FETCH_ERROR_LIMIT", 1.0):
            result, sources, _ = run(Sources(**overrides), markets=("KR",))
        stored = {c["key"] for c in sources.calls if c.get("stored")}
        self.assertNotIn("dart-company-00126380", stored)
        self.assertIn("dart-company-00164779", stored)
        self.assertIn("dart-company-00164742", stored)
        quota = {"status": "020", "message": "요청 제한을 초과하였습니다."}
        result, sources, _ = run(
            Sources(**{"dart-company-00126380": quota}), markets=("KR",)
        )
        self.assertEqual(result["status"], "error")
        stored = {c["key"] for c in sources.calls if c.get("stored")}
        self.assertNotIn("dart-company-00126380", stored)
        result, sources, _ = run(
            Sources(**{"dart-corpcode": b"<result><status>020</status></result>"}),
            markets=("KR",),
        )
        self.assertNotIn(
            "dart-corpcode", {c["key"] for c in sources.calls if c.get("stored")}
        )

    def test_dart_identity_must_match_the_listing(self):
        company = json.loads(fixture("company-00181712.json"))
        company["stock_code"] = "999990"
        result, _, _ = run(
            Sources(**{"dart-company-00181712": company}), markets=("KR",)
        )
        sk = by_id(result)["KR:034730"]
        self.assertEqual(
            (sk["status"], sk["fetchError"], sk["sector"]),
            ("eligible", "dart_identity_mismatch", None),
        )

    def test_settlement_month_becomes_fiscal_year_end(self):
        cases = {
            "12": "1231",
            "3": "0331",
            "02": "0228",
            "06": "0630",
            "13": None,
            "": None,
        }
        for month, expected in cases.items():
            self.assertEqual(universe._month_end(month), expected, month)


class BuildTests(unittest.TestCase):
    def test_offline_build_reads_stored_originals_without_credentials(self):
        result, sources, key_loader = run(online=False, env="")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(list(result["markets"]), ["US", "KR"])
        key_loader.assert_not_called()
        self.assertFalse(any(c.get("stored") for c in sources.calls))
        self.assertTrue(all(c["online"] is False for c in sources.calls))
        self.assertTrue(sources.keys("yahoo-"))
        self.assertEqual(len(result["members"]), 16)
        self.assertEqual(result["rulesHash"], digest(canonical(result["rules"])))
        self.assertEqual(result["asOfByMarket"], dict(US="2026-10-02", KR="2026-10-02"))
        keys = [(s["key"], s["sha256"]) for s in result["sources"]]
        self.assertEqual(len(keys), len(set(keys)))
        # Each market keeps its own build facts for the registration check (D5').
        for market, info in result["markets"].items():
            self.assertEqual(info["rulesHash"], result["rulesHash"], market)
            self.assertLessEqual(result["builtAt"], info["builtAt"])
            self.assertLessEqual(info["builtAt"], info["completedAt"])
            self.assertLessEqual(info["completedAt"], result["completedAt"])
            self.assertTrue(info["capturedAt"]["first"], market)
            self.assertLessEqual(
                info["capturedAt"]["first"], info["capturedAt"]["last"]
            )
            self.assertIs(info["online"], False)
        self.assertEqual(
            result["sources"],
            universe._unique(
                result["markets"]["US"]["sources"] + result["markets"]["KR"]["sources"]
            ),
        )

    def test_markets_can_be_checked_against_their_own_last_session(self):
        result, _, _ = run(as_of={"US": "2026-10-02", "KR": "2026-10-01"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            (result["asOf"], result["asOfByMarket"]),
            ("2026-10-02", dict(US="2026-10-02", KR="2026-10-01")),
        )
        us, kr = result["markets"]["US"], result["markets"]["KR"]
        self.assertEqual((us["asOf"], issues(us)), ("2026-10-02", []))
        self.assertEqual((kr["asOf"], issues(kr)), ("2026-10-01", []))
        closes = by_id(result)["KR:005930"]["shareClasses"]
        self.assertEqual([c["rankingClose"] for c in closes], [276_000.0, 204_500.0])

    def test_market_selection_is_validated(self):
        with self.assertRaises(ValueError):
            universe.build("2026-10-02", markets=("JP",))
        with self.assertRaises(ValueError):
            universe.build("2026-13-01")
        with self.assertRaises(ValueError):
            universe.build({"US": "2026-10-02"})  # KR lacks a date
        with self.assertRaises(ValueError):
            universe.build({"US": "2026-09-30", "KR": "2026-10-02"})

    def test_close_times_and_candidate_pool_match_the_protocol(self):
        from ratings import rating, registry

        self.assertEqual(
            (universe.RULES["KR"]["top"], universe.RULES["KR"]["candidatePool"]),
            (200, 260),
        )
        for market in ("US", "KR"):
            self.assertEqual(
                universe.market_close(market, "2026-10-30"),
                registry.market_close(market, "2026-10-30"),
            )

        def pools(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "candidatePool":
                        yield item
                    yield from pools(item)

        for pool in pools(rating.PROTOCOL):
            self.assertEqual(pool, 260)
        self.assertEqual(
            universe.RULES["KR"]["unrankedReasons"], list(universe.UNRANKED_REASONS)
        )
        self.assertEqual(
            rating.PROTOCOL["moduleRules"]["universe"],
            json.loads(json.dumps(universe.RULES)),
        )


class FileTests(unittest.TestCase):
    """D5': one part per market (data/ratings/universe/<T>/<market>.json) and the merged
    month (data/ratings/universe/<asOf>.json): registry.merge_universe of the parts,
    the same merge the CLI's universe-merge writes."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = universe.Path(folder.name)
        patcher = mock.patch.object(universe, "UNIVERSE_DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, name: str) -> dict:
        return json.loads((self.root / name).read_text())

    def files(self) -> list:
        return sorted(
            p.relative_to(self.root).as_posix() for p in self.root.rglob("*.json")
        )

    def test_save_writes_a_part_per_market_and_the_merged_month(self):
        from ratings import registry

        result, _, _ = run(online=False, env="")
        path = universe.save(result)
        self.assertEqual(path, self.root / "2026-10-02.json")
        self.assertEqual(
            self.files(),
            ["2026-10-02.json", "2026-10-02/KR.json", "2026-10-02/US.json"],
        )
        split = universe.parts(result)
        files = {}
        for market in ("US", "KR"):
            blob = (self.root / f"2026-10-02/{market}.json").read_bytes()
            part = json.loads(blob)
            self.assertEqual(canonical(part), canonical(split[market]))
            self.assertEqual(list(part["markets"]), [market])
            self.assertEqual(part["sources"], result["markets"][market]["sources"])
            self.assertEqual(part["builtAt"], result["markets"][market]["builtAt"])
            files[market] = dict(
                file=f"data/ratings/universe/2026-10-02/{market}.json",
                sha256=digest(blob),
            )
        merged = self.read("2026-10-02.json")
        expected = registry.merge_universe(split, files=files)
        self.assertEqual(universe._content(merged), universe._content(expected))
        self.assertEqual(merged["members"], result["members"])
        self.assertEqual(merged["sources"], result["sources"])
        # The names the registry reads, per market, from each market's own build.
        for market in ("US", "KR"):
            info, built = merged["markets"][market], result["markets"][market]
            self.assertEqual(info["part"], files[market])
            self.assertEqual(
                (info["builtAt"], info["rulesHash"], info["asOf"]),
                (built["builtAt"], merged["rulesHash"], "2026-10-02"),
            )
            self.assertEqual(
                {k: info["capturedAt"][k] for k in ("first", "last")},
                built["capturedAt"],
            )
        self.assertEqual(merged["markets"]["US"]["holdingsAsOf"], "2026-10-02")
        self.assertEqual(merged["markets"]["KR"]["rankingBasis"], "T_close")
        stamp = merged["mergedAt"]
        self.assertEqual(universe.save(result), path)  # the same build changes nothing
        self.assertEqual(self.read("2026-10-02.json")["mergedAt"], stamp)
        changed = copy.deepcopy(result)
        changed["markets"]["KR"]["builtAt"] = "2026-10-31T00:00:00+00:00"
        before = self.files(), self.read("2026-10-02.json")
        with self.assertRaisesRegex(FileExistsError, "2026-10-02/KR.json"):
            universe.save(changed)
        self.assertEqual((self.files(), self.read("2026-10-02.json")), before)
        universe.save(changed, overwrite=True)
        self.assertEqual(
            self.read("2026-10-02.json")["markets"]["KR"]["builtAt"],
            "2026-10-31T00:00:00+00:00",
        )

    def test_markets_saved_apart_merge_into_one_month(self):
        kr, _, _ = run(markets=("KR",), online=False, env="")
        path = universe.save(kr)
        self.assertEqual(list(self.read(path.name)["markets"]), ["KR"])
        us, _, _ = run(markets=("US",), online=False, env="")
        self.assertEqual(universe.save(us), path)
        merged = self.read(path.name)
        self.assertEqual(sorted(merged["markets"]), ["KR", "US"])
        self.assertEqual(merged["asOfByMarket"], dict(US="2026-10-02", KR="2026-10-02"))
        self.assertEqual(
            merged["markets"]["KR"]["part"]["sha256"],
            digest((self.root / "2026-10-02/KR.json").read_bytes()),
        )
        self.assertEqual(
            [m["market"] for m in merged["members"]], ["US"] * 6 + ["KR"] * 10
        )
        # A rebuilt US part needs overwrite and leaves the KR part as it was.
        rebuilt = copy.deepcopy(us)
        rebuilt["markets"]["US"]["builtAt"] = "2026-10-05T14:00:00+00:00"
        kr_part = (self.root / "2026-10-02/KR.json").read_bytes()
        with self.assertRaises(FileExistsError):
            universe.save(rebuilt)
        universe.save(rebuilt, overwrite=True)
        self.assertEqual((self.root / "2026-10-02/KR.json").read_bytes(), kr_part)
        self.assertEqual(
            self.read(path.name)["markets"]["US"]["builtAt"],
            "2026-10-05T14:00:00+00:00",
        )
        self.assertEqual(universe.merge("2026-10-02"), path)  # nothing changed

    def test_markets_with_different_last_sessions_share_the_month_file(self):
        # December: KRX is closed on the 31st, so T_KR (12-30) precedes T_US (12-31).
        kr, _, _ = run(markets=("KR",), online=False, env="")
        us, _, _ = run(markets=("US",), online=False, env="")
        universe.save(relabel(kr, "2026-12-30"))
        self.assertEqual(self.files(), ["2026-12-30.json", "2026-12-30/KR.json"])
        path = universe.save(relabel(us, "2026-12-31"))
        self.assertEqual(path.name, "2026-12-31.json")
        self.assertEqual(
            self.files(),
            ["2026-12-30/KR.json", "2026-12-31.json", "2026-12-31/US.json"],
        )  # the KR-only merge is superseded
        merged = self.read("2026-12-31.json")
        self.assertEqual(
            (merged["asOf"], merged["asOfByMarket"]),
            ("2026-12-31", dict(US="2026-12-31", KR="2026-12-30")),
        )
        self.assertEqual(universe.merge("2026-12-31"), path)
        self.assertEqual(self.read("2026-12-31.json"), merged)
        # A second KR part of the month makes a date-only merge ambiguous.
        universe.save(relabel(kr, "2026-12-29"))
        with self.assertRaisesRegex(ValueError, "Several KR universe parts"):
            universe.merge("2026-12-31")
        universe.merge({"US": "2026-12-31", "KR": "2026-12-30"})
        self.assertEqual(
            universe._content(self.read("2026-12-31.json")), universe._content(merged)
        )
        with self.assertRaises(FileNotFoundError):
            universe.merge({"KR": "2026-12-28"})
        with self.assertRaises(ValueError):
            universe.merge({"US": "2026-12-31", "KR": "2027-01-04"})

    def test_parts_that_cannot_share_a_universe_are_not_merged(self):
        kr, _, _ = run(markets=("KR",), online=False, env="")
        us, _, _ = run(markets=("US",), online=False, env="")
        universe.save(kr)
        other = copy.deepcopy(universe.parts(us)["US"])
        other["rules"]["US"]["source"] = "another holdings file"
        other["rulesHash"] = digest(canonical(other["rules"]))
        common.write_json(self.root / "2026-10-02/US.json", other)
        with self.assertRaisesRegex(ValueError, "rules"):
            universe.merge("2026-10-02")
        failed = copy.deepcopy(universe.parts(us)["US"])
        failed["status"] = "error"
        common.write_json(self.root / "2026-10-02/US.json", failed)
        with self.assertRaises(ValueError):
            universe.merge("2026-10-02")
        self.assertEqual(list(self.read("2026-10-02.json")["markets"]), ["KR"])

    def test_builds_without_per_market_fields_split_with_build_values(self):
        result, _, _ = run(online=False, env="")
        older = copy.deepcopy(result)
        for info in older["markets"].values():
            for key in ("builtAt", "completedAt", "sources", "online"):
                info.pop(key)
        split = universe.parts(older)
        for market, part in split.items():
            info = part["markets"][market]
            self.assertEqual(
                (part["builtAt"], info["builtAt"], info["online"]),
                (older["builtAt"], older["builtAt"], False),
            )
            self.assertEqual(part["sources"], older["sources"])
        self.assertEqual(universe.save(older), self.root / "2026-10-02.json")

    def test_month_file_that_is_not_a_merge_is_never_silently_replaced(self):
        result, _, _ = run(online=False, env="")
        legacy = dict(result, builtAt="2026-10-03T00:00:00+00:00")
        (self.root / "2026-10-02.json").write_text(json.dumps(legacy))
        with self.assertRaisesRegex(
            universe.MonthNotMerged,
            "parts 2026-10-02/US.json, 2026-10-02/KR.json saved, month not merged: "
            "2026-10-02.json exists with different content and is not a merge of parts",
        ) as caught:
            universe.save(result)
        self.assertIsInstance(caught.exception.error, FileExistsError)
        self.assertTrue((self.root / "2026-10-02/KR.json").exists())  # parts kept
        universe.merge("2026-10-02", overwrite=True)
        self.assertIn("mergedAt", self.read("2026-10-02.json"))

    def test_gate_universe_keeps_its_own_stem(self):
        # H1: the computability-check universe (T 10-19) and October's universe (T
        # 10-30) never merge, replace or remove each other's files.
        kr, _, _ = run(markets=("KR",), online=False, env="")
        us, _, _ = run(markets=("US",), online=False, env="")
        both, _, _ = run(online=False, env="")
        path = universe.save(relabel(both, "2026-10-19"), gate=True)
        self.assertEqual(path, self.root / "2026-10-19-gate.json")
        self.assertEqual(path, universe.merged_path("2026-10-19", gate=True))
        gate_files = [
            "2026-10-19-gate.json",
            "2026-10-19-gate/KR.json",
            "2026-10-19-gate/US.json",
        ]
        self.assertEqual(self.files(), gate_files)
        self.assertEqual(
            self.read(path.name)["markets"]["KR"]["part"]["file"],
            "data/ratings/universe/2026-10-19-gate/KR.json",
        )
        kept = {name: (self.root / name).read_bytes() for name in gate_files}
        # Month end: KR is built on T's evening, the US once SSGA posts T.
        month = universe.save(relabel(kr, "2026-10-30"))
        self.assertEqual(month, self.root / "2026-10-30.json")
        self.assertEqual(list(self.read(month.name)["markets"]), ["KR"])  # no gate US
        self.assertEqual(universe.save(relabel(us, "2026-10-30")), month)
        merged = self.read(month.name)
        self.assertEqual(merged["asOfByMarket"], dict(US="2026-10-30", KR="2026-10-30"))
        # Retrying the gate merge changes nothing and removes nothing.
        self.assertEqual(universe.merge("2026-10-19", gate=True), path)
        self.assertEqual(universe.merge({"KR": "2026-10-19"}, gate=True), path)
        self.assertEqual(
            {name: (self.root / name).read_bytes() for name in gate_files}, kept
        )
        self.assertEqual(self.read(month.name), merged)
        self.assertEqual(
            self.files(),
            gate_files
            + ["2026-10-30.json", "2026-10-30/KR.json", "2026-10-30/US.json"],
        )
        with self.assertRaisesRegex(FileNotFoundError, r"2026-10-30 \(<T>-gate/\)"):
            universe.merge({"KR": "2026-10-30"}, gate=True)
        # Paths of each kind; a smoke build of the gate stays apart from both.
        self.assertEqual(
            universe.part_path("US", "2026-10-19", gate=True),
            self.root / "2026-10-19-gate/US.json",
        )
        self.assertEqual(
            universe.part_path("US", "2026-10-19", 24, True),
            self.root / "2026-10-19-gate-limit24/US.json",
        )
        self.assertEqual(
            universe.merged_path("2026-10-30"), self.root / "2026-10-30.json"
        )
        smoke, _, _ = run(online=False, env="", limit=2)
        self.assertEqual(
            universe.save(relabel(smoke, "2026-10-19"), gate=True).name,
            "2026-10-19-gate-limit2.json",
        )
        self.assertEqual(self.read(path.name), json.loads(kept[gate_files[0]]))

    def test_an_earlier_merge_goes_only_when_each_market_keeps_its_t(self):
        # H1: 10-30.json holding KR of 10-30 and the US part of 10-19 (the month's only
        # US part) supersedes nothing: 10-19.json's KR part is another T.
        kr, _, _ = run(markets=("KR",), online=False, env="")
        us, _, _ = run(markets=("US",), online=False, env="")
        universe.save(relabel(kr, "2026-10-19"))
        universe.save(relabel(us, "2026-10-19"))
        october = self.read("2026-10-19.json")
        later = universe.save(relabel(kr, "2026-10-30"))
        self.assertEqual(
            self.read(later.name)["asOfByMarket"],
            dict(US="2026-10-19", KR="2026-10-30"),
        )
        self.assertEqual(self.read("2026-10-19.json"), october)  # kept
        # Rewriting 10-19.json (overwritten KR part) never removes 10-30.json either.
        rebuilt = relabel(kr, "2026-10-19")
        rebuilt["markets"]["KR"]["builtAt"] = "2026-10-20T10:00:00+00:00"
        universe.save(rebuilt, overwrite=True)
        self.assertTrue((self.root / "2026-10-30.json").exists())
        self.assertEqual(
            sorted(p.name for p in self.root.glob("*.json")),
            ["2026-10-19.json", "2026-10-30.json"],
        )

    def test_a_failed_month_merge_reports_the_part_saved(self):
        # H1: two KR parts in the month make the US part's merge ambiguous; the US part
        # is written, so the error says so instead of "not saved".
        kr, _, _ = run(markets=("KR",), online=False, env="")
        us, _, _ = run(markets=("US",), online=False, env="")
        universe.save(relabel(kr, "2026-10-29"))
        universe.save(relabel(kr, "2026-10-30"))
        part = relabel(us, "2026-10-30")
        with self.assertRaisesRegex(ValueError, "saved, month not merged") as caught:
            universe.save(part)
        error = caught.exception
        self.assertIsInstance(error, universe.MonthNotMerged)
        self.assertEqual(
            str(error),
            "part 2026-10-30/US.json saved, month not merged: Several KR universe parts "
            "in 2026-10 (2026-10-29, 2026-10-30); merge with {'KR': <T>}",
        )
        self.assertEqual(error.parts, {"US": self.root / "2026-10-30/US.json"})
        self.assertIsInstance(error.error, ValueError)
        self.assertEqual(
            canonical(self.read("2026-10-30/US.json")),
            canonical(universe.parts(part)["US"]),
        )
        self.assertEqual(list(self.read("2026-10-30.json")["markets"]), ["KR"])
        # The parts need no rebuild: merging with the KR date pinned completes it.
        universe.merge({"US": "2026-10-30", "KR": "2026-10-30"})
        self.assertEqual(sorted(self.read("2026-10-30.json")["markets"]), ["KR", "US"])
        # A part that differs is still refused before anything is written.
        changed = relabel(us, "2026-10-30")
        changed["markets"]["US"]["builtAt"] = "2026-10-31T00:00:00+00:00"
        with self.assertRaisesRegex(FileExistsError, "2026-10-30/US.json exists"):
            universe.save(changed)

    def test_smoke_builds_stay_apart_from_the_month(self):
        result, _, _ = run(online=False, env="", limit=2)
        path = universe.save(result)
        self.assertEqual(path, self.root / "2026-10-02-limit2.json")
        self.assertEqual(
            self.files(),
            [
                "2026-10-02-limit2.json",
                "2026-10-02-limit2/KR.json",
                "2026-10-02-limit2/US.json",
            ],
        )
        self.assertEqual(self.read(path.name)["limit"], 2)
        self.assertEqual(universe.save(result), path)
        changed = copy.deepcopy(result)
        changed["markets"]["US"]["builtAt"] = "2026-10-31T00:00:00+00:00"
        with self.assertRaises(FileExistsError):
            universe.save(changed)
        with self.assertRaises(FileNotFoundError):
            universe.merge("2026-10-02")  # no part of the month's universe
        self.assertEqual(universe.merge("2026-10-02", limit=2), path)


if __name__ == "__main__":
    unittest.main()
