from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

from ratings import common, prices
from ratings.common import FetchError

FIXTURES = Path(__file__).parent / "fixtures/ratings/prices"
MANIFESTS = json.loads((FIXTURES / "manifests.json").read_text())
THROUGH = "2026-10-05"
# M1: Yahoo's answer (HTTP 400, both hosts) to a request for 0126Z0.KS (first session
# 2025-11-25) ending 2025-11-20, as retrieved live on 2026-10-06 21:1x KST.
LIVE_400 = (
    b'{"chart":{"result":null,"error":{"code":"Bad Request","description":"Data '
    b"doesn't exist for startDate = 1748703600, endDate = 1763564400\"}}}"
)


def fixture(symbol: str) -> bytes:
    return (FIXTURES / f"{MANIFESTS[symbol]['key']}.json").read_bytes()


def mutated(symbol: str, change) -> bytes:
    obj = json.loads(fixture(symbol))
    change(obj["chart"]["result"][0])
    return json.dumps(obj).encode()


def chart(
    symbol, zone, stamps, closes, adjusted=None, currency="USD", volumes=None
) -> bytes:
    quote = (
        dict(close=closes) if volumes is None else dict(close=closes, volume=volumes)
    )
    result = dict(
        meta=dict(symbol=symbol, currency=currency, exchangeTimezoneName=zone),
        timestamp=stamps,
        indicators=dict(
            quote=[quote],
            adjclose=[dict(adjclose=closes if adjusted is None else adjusted)],
        ),
    )
    return json.dumps(dict(chart=dict(result=[result], error=None))).encode()


class Kept:
    """An HTTP error response whose body ratings.common.fetch keeps as an original
    when its status is in ``keep_status`` (manifest ``httpStatus``), else raises."""

    def __init__(self, body: bytes, status: int = 400):
        self.body, self.status = body, status


class FakeFetch:
    """Stands in for ratings.common.fetch: returns blobs or raises queued errors."""

    def __init__(self, *responses, retrieved="2026-10-06T04:12:00+00:00"):
        self.responses, self.retrieved, self.calls = list(responses), retrieved, []

    def __call__(self, url, key, **kwargs):
        self.calls.append(dict(url=url, key=key, **kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status = None
        if isinstance(response, Kept):
            if response.status not in kwargs.get("keep_status", ()):
                raise FetchError(f"Yahoo Finance: HTTP {response.status} for {key}")
            response, status = response.body, response.status
        manifest = dict(
            key=key,
            url=url,
            sha256="0" * 64,
            file=f"data/ratings/sources/{key}.json",
            bytes=len(response),
            provider=kwargs["provider"],
            retrievedAt=self.retrieved,
        )
        if status is not None:
            manifest["httpStatus"] = status
        return response, manifest


def run(symbol, *responses, through=THROUGH, retrieved=None, **kwargs):
    fake = FakeFetch(
        *(responses or [fixture(symbol)]),
        retrieved=retrieved
        or MANIFESTS.get(symbol, {}).get("retrievedAt", "2026-10-06T04:12:00+00:00"),
    )
    with mock.patch.object(prices, "fetch", fake):
        return prices.series(symbol, through, **kwargs), fake.calls


def synthetic(n, start=date(2024, 1, 1)):
    """n weekday sessions with adj = 100 + i and close = 200 + i."""
    rows, day = [], start
    while len(rows) < n:
        if day.weekday() < 5:
            rows.append([day.isoformat(), 100.0 + len(rows), 200.0 + len(rows)])
        day += timedelta(days=1)
    return rows


class SeriesFixtureTests(unittest.TestCase):
    def assert_clean(self, result):
        self.assertEqual(result["status"], "ok", result["error"])
        dates = [r[0] for r in result["rows"]]
        self.assertEqual(dates, sorted(set(dates)))
        self.assertTrue(all(a > 0 and c > 0 for _, a, c in result["rows"]))
        self.assertLessEqual(dates[-1], result["window"]["through"])
        self.assertGreaterEqual(dates[0], result["window"]["from"])

    def test_us_equity_request_window_and_rows(self):
        result, calls = run("AAPL")
        self.assert_clean(result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["key"], "yahoo-AAPL-2026-10-05")
        self.assertEqual(
            calls[0]["url"],
            "https://query2.finance.yahoo.com/v8/finance/chart/AAPL"
            "?period1=1756512000&period2=1791331200"
            "&interval=1d&events=div,split&includeAdjustedClose=true",
        )
        self.assertEqual(calls[0]["provider"], "Yahoo Finance")
        self.assertEqual(result["window"], {"from": "2025-08-31", "through": THROUGH})
        self.assertEqual(len(result["rows"]), 275)
        self.assertEqual(result["rows"][0][0], "2025-09-02")  # 2025-09-01 Labor Day
        self.assertEqual(result["rows"][-1][0], THROUGH)
        self.assertEqual(
            (result["currency"], result["timezone"]), ("USD", "America/New_York")
        )
        self.assertEqual(result["source"]["key"], "yahoo-AAPL-2026-10-05")
        first = result["rows"][0]
        self.assertLess(first[1], first[2])  # dividend-adjusted below the close

    def test_korean_symbol_null_session_and_holiday(self):
        result, _ = run("005930.KS")
        self.assert_clean(result)
        dates = [r[0] for r in result["rows"]]
        self.assertEqual(len(dates), 264)
        self.assertEqual(result["nullSessions"], ["2025-09-19"])
        self.assertNotIn("2025-09-19", dates)
        self.assertIn("2025-09-19", " ".join(result["notes"]))
        self.assertEqual(dates[-1], "2026-10-02")  # 2026-10-05 KRX holiday
        self.assertEqual(
            (result["currency"], result["timezone"]), ("KRW", "Asia/Seoul")
        )
        self.assertLess(result["rows"][0][1], result["rows"][0][2])

    def test_benchmarks(self):
        sp, calls = run("^SP500TR")
        self.assert_clean(sp)
        self.assertEqual(calls[0]["key"], "yahoo-_5ESP500TR-2026-10-05")
        self.assertIn("/chart/%5ESP500TR?", calls[0]["url"])
        self.assertEqual((len(sp["rows"]), sp["currency"]), (275, "USD"))
        spy, _ = run("SPY")
        self.assert_clean(spy)
        self.assertEqual(len(spy["rows"]), 275)
        kodex, _ = run("069500.KS")
        self.assert_clean(kodex)
        self.assertEqual((len(kodex["rows"]), kodex["nullSessions"]), (265, []))
        self.assertIn("2025-09-19", [r[0] for r in kodex["rows"]])

    def test_split_events_and_split_adjusted_close(self):
        result, _ = run("NFLX")
        self.assert_clean(result)
        self.assertEqual(
            result["splits"],
            [{"date": "2025-11-17", "numerator": 10.0, "denominator": 1.0}],
        )
        before = prices.close_on_or_before(result["rows"], "2025-11-14")
        # Yahoo restates pre-split closes (traded near $1,100) on the post-split basis.
        self.assertEqual(before[0], "2025-11-14")
        self.assertLess(before[1], 200)

    def test_split_events_cover_the_requested_window(self):
        def at(day: str, hour: int = 9, minute: int = 30) -> int:  # New York time
            local = datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}")
            return int(local.replace(tzinfo=ZoneInfo("America/New_York")).timestamp())

        events = {
            "2025-08-29": (2.0, 1.0),  # before the window: not reported
            "2025-08-31": (3.0, 2.0),  # first day of the window (a Sunday stamp)
            "2026-01-12": (1.0, 20.0),  # reverse split 1-for-20
            "2026-03-02": (0.650391, 1.0),  # spin-off shown as a split: kept as given
            THROUGH: (4.0, 1.0),  # through day itself
            "2026-10-06": (5.0, 1.0),  # returned by the widened request, after through
        }

        def add(result):
            splits = result.setdefault("events", {}).setdefault("splits", {})
            for day, (numerator, denominator) in events.items():
                stamp = at(day)
                splits[str(stamp)] = dict(
                    date=stamp,
                    numerator=numerator,
                    denominator=denominator,
                    splitRatio=f"{numerator}:{denominator}",
                )

        blob = mutated("NFLX", add)
        result, _ = run("NFLX", blob)
        self.assert_clean(result)
        self.assertEqual(
            result["splits"],
            [
                {"date": "2025-08-31", "numerator": 3.0, "denominator": 2.0},
                {"date": "2025-11-17", "numerator": 10.0, "denominator": 1.0},
                {"date": "2026-01-12", "numerator": 1.0, "denominator": 20.0},
                {"date": "2026-03-02", "numerator": 0.650391, "denominator": 1.0},
                {"date": THROUGH, "numerator": 4.0, "denominator": 1.0},
            ],
        )
        extended, _ = run("NFLX", blob, start="2025-08-15")  # start widens the window
        self.assertEqual(
            [s["date"] for s in extended["splits"][:2]], ["2025-08-29", "2025-08-31"]
        )
        # A split stamped late in the New York evening still falls on that local day.
        late = mutated(
            "NFLX",
            lambda r: r["events"]["splits"].update(
                x=dict(date=at("2026-10-05", 23), numerator=2.0, denominator=1.0)
            ),
        )
        self.assertIn(
            {"date": THROUGH, "numerator": 2.0, "denominator": 1.0},
            run("NFLX", late)[0]["splits"],
        )

    def test_undated_split_event_rejects_the_original(self):
        blob = mutated(
            "NFLX",
            lambda r: r["events"]["splits"].update(x=dict(numerator=2.0)),
        )
        result, _ = run("NFLX", blob, blob)
        self.assertEqual((result["status"], result["rows"]), ("error", []))
        self.assertIn("rejected original", result["error"])

    def test_momentum_on_live_originals(self):
        expected = {"AAPL": 0.24993292885787888, "005930.KS": 2.451261579000433}
        for symbol, value in expected.items():
            rows = run(symbol)[0]["rows"]
            t = max(i for i, r in enumerate(rows) if r[0] <= "2026-09-30")
            self.assertEqual(rows[t][0], "2026-09-30")
            self.assertAlmostEqual(prices.momentum_12_1(rows, "2026-09-30"), value, 12)
            self.assertAlmostEqual(
                prices.momentum_12_1(rows, "2026-09-30"),
                rows[t - 21][1] / rows[t - 252][1] - 1,
                12,
            )

    def test_unsettled_session_is_dropped_by_retrieval_time(self):
        early, _ = run("AAPL", retrieved="2026-10-05T20:00:00+00:00")  # 16:00 New York
        self.assertEqual(early["status"], "ok")
        self.assertEqual(early["rows"][-1][0], "2026-10-02")
        self.assertIn("unsettled", early["notes"][0])
        late, _ = run("AAPL", retrieved="2026-10-05T22:00:00+00:00")  # 18:00 New York
        self.assertEqual(late["rows"][-1][0], THROUGH)
        self.assertEqual(late["notes"], [])

    def test_fallback_to_query1_uses_same_key(self):
        result, calls = run(
            "AAPL", FetchError("Yahoo Finance: HTTP 503"), fixture("AAPL")
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            [c["url"].split(".")[0] for c in calls],
            ["https://query2", "https://query1"],
        )
        self.assertEqual(calls[0]["key"], calls[1]["key"])
        self.assertTrue(
            result["notes"][0].startswith("fallback to query1 after query2")
        )
        self.assertIn("query1", result["source"]["url"])

    def test_rejected_originals_return_error_without_rows(self):
        cases = {
            "symbol": (fixture("AAPL"), "provider returned symbol 'AAPL'"),
            "currency": (
                mutated("005930.KS", lambda r: r["meta"].update(currency="USD")),
                "expected KRW",
            ),
            "price": (
                mutated(
                    "AAPL",
                    lambda r: r["indicators"]["quote"][0]["close"].__setitem__(5, 0),
                ),
                "invalid close",
            ),
            "provider": (
                b'{"chart":{"result":null,"error":{"code":"Not Found",'
                b'"description":"No data found, symbol may be delisted"}}}',
                "Not Found",
            ),
        }
        for name, (blob, message) in cases.items():
            symbol = {"symbol": "MSFT", "currency": "005930.KS"}.get(name, "AAPL")
            with self.subTest(name):
                result, calls = run(symbol, blob, blob)
                self.assertEqual((result["status"], result["rows"]), ("error", []))
                self.assertEqual(len(calls), 2)
                self.assertIn(message, result["error"])
                self.assertIn("query2", result["error"])
                self.assertIn("query1", result["error"])
                self.assertIsNotNone(
                    result["source"]
                )  # rejected original kept for audit

    def test_network_failure_on_both_hosts(self):
        result, calls = run(
            "AAPL",
            FetchError("Yahoo Finance: HTTP 429 for k"),
            ConnectionResetError("reset"),
        )
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["source"])
        self.assertIn("HTTP 429", result["error"])
        self.assertIn("reset", result["error"])

    def test_offline_replays_one_stored_original(self):
        result, calls = run("AAPL", online=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]["online"])
        missing, calls = run("AAPL", FetchError("No stored original"), online=False)
        self.assertEqual(missing["status"], "error")
        self.assertEqual(len(calls), 1)
        self.assertTrue(missing["error"].startswith("stored: No stored original"))

    def test_invalid_requests_never_fetch(self):
        for symbol, through in (
            ("AAPL", "2026/10/05"),
            ("AAPL", "20261005"),
            ("BAD SYMBOL", THROUGH),
            ("A_B", THROUGH),
            (None, THROUGH),
        ):
            with self.subTest(symbol=symbol, through=through):
                result, calls = run(symbol, b"", through=through)
                self.assertEqual(result["status"], "error")
                self.assertTrue(result["error"].startswith("invalid request"))
                self.assertEqual(calls, [])

    def test_start_extends_window_and_key(self):
        result, calls = run("AAPL", start="2024-01-02")
        self.assertEqual(calls[0]["key"], "yahoo-AAPL-2026-10-05-from-2024-01-02")
        self.assertIn("period1=1704067200&", calls[0]["url"])  # 2024-01-01 UTC
        self.assertEqual(result["window"]["from"], "2024-01-02")
        _, calls = run("AAPL", start="2026-01-02")  # inside default window: no change
        self.assertEqual(calls[0]["key"], "yahoo-AAPL-2026-10-05")
        self.assertEqual(
            prices.source_key("KRW=X", date(2026, 10, 5)), "yahoo-KRW_3DX-2026-10-05"
        )
        self.assertEqual(prices.source_key("BRK-B", THROUGH), "yahoo-BRK-B-2026-10-05")

    def test_timestamps_are_dated_in_exchange_timezone(self):
        # 01-05 00:00 UTC = 09:00 Seoul; 01-05 15:30 UTC = 00:30 Seoul on 01-06.
        blob = chart(
            "000001.KS",
            "Asia/Seoul",
            [1767571200, 1767627000],
            [10.0, 11.0],
            currency="KRW",
        )
        result, _ = run(
            "000001.KS",
            blob,
            through="2026-01-06",
            retrieved="2026-01-07T00:00:00+00:00",
        )
        self.assertEqual([r[0] for r in result["rows"]], ["2026-01-05", "2026-01-06"])
        blob = chart("ABC", "America/New_York", [1767627000], [10.0])  # 10:30 New York
        result, _ = run(
            "ABC", blob, through="2026-01-05", retrieved="2026-01-07T00:00:00+00:00"
        )
        self.assertEqual(result["rows"], [["2026-01-05", 10.0, 10.0]])

    def test_duplicate_sessions(self):
        stamps = [1767627000, 1767650400]  # 10:30 and 17:00 New York, same day
        same = chart("ABC", "America/New_York", stamps, [10.0, 10.0])
        result, _ = run(
            "ABC", same, through="2026-01-05", retrieved="2026-01-07T00:00:00+00:00"
        )
        self.assertEqual(len(result["rows"]), 1)
        self.assertIn("duplicate", result["notes"][0])
        differ = chart("ABC", "America/New_York", stamps, [10.0, 10.5])
        result, _ = run(
            "ABC",
            differ,
            differ,
            through="2026-01-05",
            retrieved="2026-01-07T00:00:00+00:00",
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("duplicate or unordered session 2026-01-05", result["error"])


class NoSessionsTests(unittest.TestCase):
    """N1: an original that names the symbol in its currency but has no settled session
    in the window (listed after it, or nothing traded) is rejected like any original
    without rows, and told apart from the other rejections (NoSessions, ``empty``)."""

    ZONE = "Asia/Seoul"
    SYMBOL = "777770.KS"

    def stamp(self, day: str) -> int:
        return int(
            datetime.fromisoformat(f"{day}T09:00")
            .replace(tzinfo=ZoneInfo(self.ZONE))
            .timestamp()
        )

    def test_an_empty_chart_is_recorded_as_one(self):
        # Listed on Oct 7: the response holds a session after the window only.
        empty = chart(
            self.SYMBOL, self.ZONE, [self.stamp("2026-10-07")], [5000.0], currency="KRW"
        )
        result, calls = run(self.SYMBOL, empty, empty)
        self.assertEqual((result["status"], result["rows"]), ("error", []))
        self.assertEqual(len(calls), 2)  # both hosts are asked
        self.assertEqual(result["empty"]["host"], "query1")
        self.assertEqual(
            result["empty"]["detail"],
            "no settled sessions between 2025-08-31 and 2026-10-05 "
            "(next session 2026-10-07)",
        )
        self.assertIn("query1", result["empty"]["source"]["url"])
        self.assertEqual(
            result["error"],
            "; ".join(
                f"{host}: rejected original (NoSessions: {result['empty']['detail']})"
                for host in prices.HOSTS
            ),
        )
        self.assertTrue(issubclass(prices.NoSessions, ValueError))
        with self.assertRaises(prices.NoSessions):
            prices._parse(
                empty, self.SYMBOL, "2025-08-31", THROUGH, "2026-10-06T04:12:00+00:00"
            )
        # Null closes and unsettled sessions are named; no '; ' splits the failures.
        days = ["2026-10-01", "2026-10-02", "2026-10-05"]
        held = chart(
            self.SYMBOL,
            self.ZONE,
            [self.stamp(d) for d in days],
            [None, None, 5000.0],
            currency="KRW",
        )
        result, _ = run(self.SYMBOL, held, held, retrieved="2026-10-05T07:00:00+00:00")
        self.assertEqual(
            result["empty"]["detail"],
            "no settled sessions between 2025-08-31 and 2026-10-05 (dropped 2 "
            "null-close session(s): 2026-10-01, 2026-10-02, dropped 1 unsettled "
            "session(s): 2026-10-05)",
        )
        self.assertEqual(len(result["error"].split("; ")), 2)

    def test_an_unpublished_last_close_fails_the_series_never_a_halt(self):
        # D17, seen live 2026-10-07 00:30 KST: 005930.KS 2026-10-06 close null, volume
        # 14,340,821. A halted session has no volume (094800.KS 2026-10-06: null, null).
        days = ["2026-10-01", "2026-10-02", "2026-10-05"]
        stamps = [self.stamp(d) for d in days]
        late = "2026-10-05T15:30:00+00:00"  # 00:30 KST the next day: settled

        def blob(closes, volumes):
            return chart(
                self.SYMBOL, self.ZONE, stamps, closes, currency="KRW", volumes=volumes
            )

        pending = blob([5000.0, 5100.0, None], [10, 12, 14_340_821])
        with self.assertRaises(prices.UnpublishedClose) as caught:
            prices._parse(pending, self.SYMBOL, "2025-08-31", THROUGH, late)
        self.assertIn("close of 2026-10-05 not published", str(caught.exception))
        self.assertTrue(issubclass(prices.UnpublishedClose, prices.PARSE_ERRORS))
        result, calls = run(self.SYMBOL, pending, pending, retrieved=late)
        self.assertEqual((result["status"], result["rows"]), ("error", []))
        self.assertIsNone(result["empty"])  # never "no sessions": not a halt
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result["error"].split("; ")), 2)
        self.assertIn("UnpublishedClose", result["error"])
        # The other host's published close wins.
        good = blob([5000.0, 5100.0, 5200.0], [10, 12, 14])
        result, _ = run(self.SYMBOL, pending, good, retrieved=late)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["rows"][-1], ["2026-10-05", 5200.0, 5200.0])
        self.assertIn("fallback to query1", result["notes"][0])
        # A null close without volume (none, zero or no volume list) stays a halt:
        # the session is dropped and the series ends at the last valid row.
        for volumes in ([10, 12, None], [10, 12, 0], None):
            with self.subTest(volumes=volumes):
                held = blob([5000.0, 5100.0, None], volumes)
                result, _ = run(self.SYMBOL, held, retrieved=late)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["rows"][-1][0], "2026-10-02")
                self.assertEqual(result["nullSessions"], ["2026-10-05"])
        # An earlier traded null-close session (a historical hole) is dropped.
        hole = blob([5000.0, None, 5200.0], [10, 12, 14])
        result, _ = run(self.SYMBOL, hole, retrieved=late)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([r[0] for r in result["rows"]], ["2026-10-01", "2026-10-05"])
        self.assertEqual(result["nullSessions"], ["2026-10-02"])
        # Before the closes settle the session is unsettled, not unpublished.
        early = "2026-10-05T07:00:00+00:00"  # 16:00 KST
        result, _ = run(self.SYMBOL, pending, retrieved=early)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["rows"][-1][0], "2026-10-02")

    def test_other_rejections_and_a_working_host_are_not_empty(self):
        cases = {
            "another symbol": chart("777771.KS", self.ZONE, [], [], currency="KRW"),
            "another currency": chart(self.SYMBOL, self.ZONE, [], [], currency="USD"),
            "undecodable": b"<html>busy</html>",
            "provider error": b'{"chart":{"result":null,"error":{"code":"Not Found"}}}',
        }
        for label, blob in cases.items():
            with self.subTest(label):
                result, _ = run(self.SYMBOL, blob, blob)
                self.assertEqual(result["status"], "error")
                self.assertIsNone(result["empty"])
                self.assertNotIn("NoSessions", result["error"])
        # Another host's original with sessions gives the series (empty is None).
        empty = chart("AAPL", "America/New_York", [], [])
        result, _ = run("AAPL", empty, fixture("AAPL"))
        self.assertEqual((result["status"], result["empty"]), ("ok", None))
        self.assertIn("NoSessions", result["notes"][0])
        # A failure that downloads nothing is never empty either.
        result, _ = run(self.SYMBOL, FetchError("HTTP 404"), FetchError("HTTP 404"))
        self.assertIsNone(result["empty"])


class NoDataTests(unittest.TestCase):
    """M1: Yahoo answers a request without any session (a symbol listed after its
    end) with HTTP 400 "Data doesn't exist": the body is kept as an original and read
    as a window without sessions (NoSessions, ``empty``); any other HTTP 400 body is a
    rejected original. ``request_through`` extends the request, never the window."""

    SYMBOL = "0126Z0.KS"
    THROUGH = "2025-11-20"
    WINDOW = "no settled sessions between 2024-10-16 and 2025-11-20"

    def test_the_live_no_data_answer_is_a_window_without_sessions(self):
        result, calls = run(
            self.SYMBOL,
            Kept(LIVE_400),
            Kept(LIVE_400),
            through=self.THROUGH,
            retrieved="2026-10-06T12:15:00+00:00",
        )
        self.assertEqual([c["keep_status"] for c in calls], [(400,), (400,)])
        self.assertEqual((result["status"], result["rows"]), ("error", []))
        detail = (
            f"{self.WINDOW} (HTTP 400: Data doesn't exist for startDate = "
            "1748703600, endDate = 1763564400)"
        )
        self.assertEqual(result["empty"]["detail"], detail)
        self.assertEqual(result["empty"]["host"], "query1")
        self.assertEqual(result["empty"]["source"]["httpStatus"], 400)
        self.assertEqual(result["source"]["httpStatus"], 400)
        self.assertEqual(
            result["error"],
            "; ".join(
                f"{host}: rejected original (NoSessions: {detail})"
                for host in prices.HOSTS
            ),
        )
        self.assertEqual(
            result["window"], {"from": "2024-10-16", "through": "2025-11-20"}
        )
        with self.assertRaises(prices.NoSessions):
            prices._kept(LIVE_400, 400, "2024-10-16", self.THROUGH)
        # One host's 400 and the other's sessions: the series (the 400 in the notes).
        result, _ = run("AAPL", Kept(LIVE_400), fixture("AAPL"))
        self.assertEqual((result["status"], result["empty"]), ("ok", None))
        self.assertIn("Data doesn't exist", result["notes"][0])
        # Without keep_status (an older caller) the 400 stays a download failure.
        fake = FakeFetch(Kept(LIVE_400))
        with self.assertRaises(FetchError):
            fake("u", "k", provider=prices.PROVIDER)

    def test_any_other_http_400_body_stays_an_error(self):
        other = (
            b'{"chart":{"result":null,"error":{"code":"Bad Request","description":'
            b'"Invalid input - interval=1x is not supported; try 1d"}}}'
        )
        cases = {
            "another description": (other, "HTTP 400 answer: Invalid input"),
            "no description": (
                b'{"chart":{"result":null,"error":{"code":"Bad Request"}}}',
                "HTTP 400 answer: no chart error description",
            ),
            "not json": (b"<html>Bad Request</html>", "no chart error description"),
            "a description that only mentions it": (
                LIVE_400.replace(b'"Data doesn', b'"Note: Data doesn'),
                "HTTP 400 answer: Note: Data doesn't exist",
            ),
        }
        for label, (body, message) in cases.items():
            with self.subTest(label):
                result, _ = run(self.SYMBOL, Kept(body), Kept(body), through=THROUGH)
                self.assertEqual(result["status"], "error")
                self.assertIsNone(result["empty"])
                self.assertNotIn("NoSessions", result["error"])
                self.assertIn(message, result["error"])
                self.assertIn(
                    "query2: rejected original (ValueError: HTTP 400", result["error"]
                )
                self.assertEqual(len(result["error"].split("; ")), 2)  # ';' escaped
        # The no-data description is an answer only with HTTP 400.
        with self.assertRaisesRegex(ValueError, "HTTP 404 answer") as caught:
            prices._kept(LIVE_400, 404, "2024-10-16", self.THROUGH)
        self.assertNotIsInstance(caught.exception, prices.NoSessions)

    def stamp(self, day: str) -> int:
        moment = datetime.fromisoformat(f"{day}T09:00").replace(
            tzinfo=ZoneInfo("Asia/Seoul")
        )
        return int(moment.timestamp())

    def test_request_through_extends_the_request_not_the_window(self):
        plain, calls = run("AAPL")
        later, extended = run("AAPL", request_through="2026-10-20")
        self.assertEqual(extended[0]["key"], calls[0]["key"])
        query = dict(parse_qsl(urlsplit(extended[0]["url"]).query))
        end = datetime(2026, 10, 22, tzinfo=timezone.utc)  # 2026-10-20 + 2 days
        self.assertEqual(int(query["period2"]), int(end.timestamp()))
        self.assertIn("period2=1791331200&", calls[0]["url"])  # 2026-10-07 UTC
        self.assertEqual(
            {k: later[k] for k in ("rows", "splits", "window", "notes")},
            {k: plain[k] for k in ("rows", "splits", "window", "notes")},
        )
        # An earlier date never shortens the request.
        _, calls = run("AAPL", request_through="2026-01-02")
        self.assertIn("period2=1791331200&", calls[0]["url"])
        # The later sessions a listing after the window shows are named, then dropped.
        listed = chart(
            self.SYMBOL,
            "Asia/Seoul",
            [self.stamp("2025-11-25"), self.stamp("2025-11-26")],
            [60000.0, 61000.0],
            currency="KRW",
        )
        result, calls = run(
            self.SYMBOL,
            listed,
            listed,
            through=self.THROUGH,
            retrieved="2026-10-06T12:15:00+00:00",
            request_through="2026-10-06",
        )
        self.assertEqual(
            result["empty"]["detail"], f"{self.WINDOW} (next session 2025-11-25)"
        )
        self.assertEqual({c["key"] for c in calls}, {"yahoo-0126Z0.KS-2025-11-20"})
        bad, calls = run("AAPL", b"", request_through="2026/10/20")
        self.assertTrue(bad["error"].startswith("invalid request"))
        self.assertEqual(calls, [])


class ReparseTests(unittest.TestCase):
    """D12': a kept series is rebuilt from its original with prices._parse."""

    PARSED = ("rows", "currency", "timezone", "splits", "nullSessions", "notes")

    def test_original_reparses_to_the_series(self):
        for symbol in ("AAPL", "005930.KS", "NFLX", "^SP500TR"):
            with self.subTest(symbol):
                result, _ = run(symbol)
                again = prices._parse(
                    fixture(symbol),
                    symbol,
                    result["window"]["from"],
                    result["window"]["through"],
                    result["source"]["retrievedAt"],
                )
                self.assertEqual(set(again), set(self.PARSED))
                self.assertEqual(again, {key: result[key] for key in self.PARSED})

    def test_dates_and_retrieval_time(self):
        expected, _ = run("AAPL")
        retrieved = MANIFESTS["AAPL"]["retrievedAt"]
        blob = fixture("AAPL")
        as_dates = prices._parse(
            blob, "AAPL", date(2025, 8, 31), datetime(2026, 10, 5, 12), retrieved
        )
        self.assertEqual(as_dates["rows"], expected["rows"])
        # Without a UTC offset the settled sessions would depend on the machine's zone.
        with self.assertRaises(ValueError):
            prices._parse(blob, "AAPL", "2025-08-31", THROUGH, retrieved[:19])
        for bad in ("2025/08/31", None):
            with self.subTest(first=bad), self.assertRaises(prices.PARSE_ERRORS):
                prices._parse(blob, "AAPL", bad, THROUGH, retrieved)
        # A different symbol's original is refused, never relabelled.
        with self.assertRaises(ValueError):
            prices._parse(blob, "MSFT", "2025-08-31", THROUGH, retrieved)

    def test_naive_retrieval_time_rejects_the_original(self):
        naive = MANIFESTS["AAPL"]["retrievedAt"][:19]
        result, calls = run("AAPL", fixture("AAPL"), fixture("AAPL"), retrieved=naive)
        self.assertEqual((result["status"], result["rows"]), ("error", []))
        self.assertIn("no UTC offset", result["error"])
        self.assertEqual(len(calls), 2)


class HelperTests(unittest.TestCase):
    def test_momentum_needs_index_252(self):
        rows = synthetic(300)
        self.assertIsNone(prices.momentum_12_1(rows, rows[251][0]))
        self.assertAlmostEqual(prices.momentum_12_1(rows, rows[252][0]), 331 / 100 - 1)
        self.assertAlmostEqual(prices.momentum_12_1(rows, rows[299][0]), 378 / 147 - 1)
        saturday = (date.fromisoformat(rows[254][0]) + timedelta(days=1)).isoformat()
        self.assertEqual(date.fromisoformat(rows[254][0]).weekday(), 4)
        self.assertAlmostEqual(prices.momentum_12_1(rows, saturday), 333 / 102 - 1)
        self.assertIsNone(prices.momentum_12_1(rows, "2023-12-31"))
        self.assertIsNone(prices.momentum_12_1([], "2026-09-30"))
        self.assertAlmostEqual(
            prices.momentum_12_1(rows, rows[20][0], skip=5, lookback=20), 115 / 100 - 1
        )

    def test_close_on_or_before(self):
        rows = synthetic(10)  # 2024-01-01 (Mon) .. 2024-01-12 (Fri)
        self.assertEqual(
            prices.close_on_or_before(rows, "2024-01-03"), ("2024-01-03", 202.0, 102.0)
        )
        self.assertEqual(prices.close_on_or_before(rows, "2024-01-07")[0], "2024-01-05")
        self.assertEqual(
            prices.close_on_or_before(rows, date(2024, 2, 1))[0], "2024-01-12"
        )
        self.assertIsNone(prices.close_on_or_before(rows, "2023-12-31"))
        self.assertIsNone(prices.close_on_or_before([], "2024-01-03"))

    def test_next_session_after(self):
        rows = synthetic(10)
        self.assertEqual(prices.next_session_after(rows, "2024-01-05"), "2024-01-08")
        self.assertEqual(prices.next_session_after(rows, "2024-01-06"), "2024-01-08")
        self.assertEqual(prices.next_session_after(rows, "2023-06-01"), "2024-01-01")
        self.assertIsNone(prices.next_session_after(rows, "2024-01-12"))

    def test_last_session_of_month(self):
        rows = synthetic(60)  # 2024-01-01 .. 2024-03-22
        self.assertEqual(prices.last_session_of_month(rows, 2024, 1), "2024-01-31")
        self.assertEqual(prices.last_session_of_month(rows, 2024, 2), "2024-02-29")
        self.assertEqual(prices.last_session_of_month(rows, 2024, 3), "2024-03-22")
        self.assertIsNone(prices.last_session_of_month(rows, 2023, 12))
        self.assertIsNone(prices.last_session_of_month(rows, 2024, 4))
        dec = [["2024-12-31", 1.0, 1.0], ["2025-01-02", 1.0, 1.0]]
        self.assertEqual(prices.last_session_of_month(dec, 2024, 12), "2024-12-31")
        with self.assertRaises(ValueError):
            prices.last_session_of_month(rows, 2024, 13)

    def test_returns_between(self):
        rows = synthetic(10)  # adj 100..109 on 2024-01-01 .. 2024-01-12
        ok = prices.returns_between(rows, "2024-01-02", "2024-01-09")
        self.assertEqual(ok["status"], "ok")
        self.assertAlmostEqual(ok["return"], 106 / 101 - 1)
        self.assertEqual(
            (ok["entry"], ok["exit"], ok["exitFallback"]),
            ("2024-01-02", "2024-01-09", False),
        )
        weekend = prices.returns_between(rows, "2024-01-02", "2024-01-07")
        self.assertEqual(
            (weekend["exit"], weekend["exitFallback"], weekend["exitReason"]),
            ("2024-01-05", True, "no-session"),
        )
        self.assertAlmostEqual(weekend["return"], 104 / 101 - 1)
        ended = prices.returns_between(rows, "2024-01-02", "2024-02-01")
        self.assertEqual(
            (ended["exit"], ended["exitReason"]), ("2024-01-12", "series-ended")
        )
        same = prices.returns_between(rows, "2024-01-02", "2024-01-02")
        self.assertEqual((same["status"], same["return"]), ("ok", 0.0))
        for entry in ("2024-01-06", "2023-12-29", "2024-02-01"):
            missing = prices.returns_between(rows, entry, "2024-02-02")
            self.assertEqual(
                (missing["status"], missing["return"]), ("missing-entry", None)
            )
            self.assertIn("2024-01-01..2024-01-12", missing["error"])
        backwards = prices.returns_between(rows, "2024-01-09", "2024-01-02")
        self.assertEqual(backwards["status"], "error")

    def test_malformed_days_raise(self):
        rows = synthetic(5)
        for bad in ("2024/01/02", "20240102", "2024-1-2", None):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    prices.close_on_or_before(rows, bad)


class StoreIntegrationTests(unittest.TestCase):
    def test_online_store_then_offline_replay(self):
        blob = fixture("AAPL")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.multiple(
            common, ROOT=Path(tmp), SOURCES=Path(tmp) / "sources"
        ), mock.patch.object(common.time, "sleep"), mock.patch.object(
            common, "urlopen", side_effect=lambda *a, **k: io.BytesIO(blob)
        ) as opened:
            online = prices.series("AAPL", THROUGH)
            offline = prices.series("AAPL", THROUGH, online=False)
            self.assertEqual(opened.call_count, 1)
            request = opened.call_args[0][0]
            self.assertTrue(
                request.full_url.startswith("https://query2.finance.yahoo.com/")
            )
            self.assertEqual(online["status"], "ok", online["error"])
            self.assertEqual(online["rows"], offline["rows"])
            self.assertEqual(online["source"]["sha256"], offline["source"]["sha256"])
            stored = Path(tmp) / online["source"]["file"]
            self.assertTrue(stored.name.startswith("yahoo-AAPL-2026-10-05-"))
            self.assertEqual(stored.read_bytes(), blob)
            self.assertEqual(len(online["rows"]), 275)
            # D12': the kept original, hash-verified, re-parses to the same series.
            window, source = online["window"], online["source"]
            again = prices._parse(
                common.load(source),
                "AAPL",
                window["from"],
                window["through"],
                source["retrievedAt"],
            )
            self.assertEqual(
                (again["rows"], again["splits"]), (online["rows"], online["splits"])
            )
            stored.write_bytes(blob.replace(b'"close"', b'"close" ', 1))
            with self.assertRaises(ValueError):  # an edited original is refused
                common.load(source)

    def test_the_no_data_400_is_stored_and_replayed_offline(self):
        """M1: ratings.common.fetch keeps Yahoo's HTTP 400 body (keep_status) as an
        original with httpStatus 400; online and offline it is the same answer."""

        def answer(request, timeout=None):
            raise HTTPError(
                request.full_url, 400, "Bad Request", {}, io.BytesIO(LIVE_400)
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.multiple(
            common, ROOT=Path(tmp), SOURCES=Path(tmp) / "sources"
        ), mock.patch.object(common.time, "sleep"), mock.patch.object(
            common, "urlopen", side_effect=answer
        ) as opened:
            online = prices.series(
                "0126Z0.KS", "2025-11-20", request_through="2026-10-06"
            )
            offline = prices.series("0126Z0.KS", "2025-11-20", online=False)
            self.assertEqual(opened.call_count, 2)  # both hosts, no retry of a 400
            self.assertIn("period2=1791417600&", opened.call_args[0][0].full_url)
            self.assertEqual(online["status"], "error")
            self.assertEqual(online["empty"]["source"]["httpStatus"], 400)
            self.assertIn("Data doesn't exist", online["empty"]["detail"])
            pointer = Path(tmp) / "sources/yahoo-0126Z0.KS-2025-11-20.manifest.json"
            self.assertEqual(json.loads(pointer.read_text())["httpStatus"], 400)
            stored = Path(tmp) / online["source"]["file"]
            self.assertEqual(stored.read_bytes(), LIVE_400)
            self.assertEqual(offline["empty"]["host"], "stored")
            self.assertEqual(offline["empty"]["detail"], online["empty"]["detail"])
            self.assertEqual(
                offline["error"],
                f"stored: rejected original (NoSessions: {online['empty']['detail']})",
            )


if __name__ == "__main__":
    unittest.main()
