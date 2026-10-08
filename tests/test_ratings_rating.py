import copy
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
import random
import unittest
from unittest import mock

try:  # an independent cross-check of the quantiles and spreads (hash-pinned in CI)
    import numpy
except ImportError:  # pragma: no cover - only where numpy is not installed
    numpy = None

from equitylab.data import digest
from ratings import prices as price_data
from ratings import rating, sectors
from ratings import universe as universes
from ratings.common import protocol_hash
from ratings.rating import AVOID, PREFER, PROTOCOL, PROTOCOL_HASH, WATCH, score, signals

AS_OF = "2026-10-30"
RETRIEVED = "2026-11-03"  # price_rows() hold sessions through this retrieval date
PRICE_FIXTURES = Path(__file__).parent / "fixtures/ratings/prices"


def sessions_until(end: str, n: int) -> list:
    day, out = date.fromisoformat(end), []
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day -= timedelta(days=1)
    return out[::-1]


def price_rows(n: int = 300, end: str = AS_OF, scale: float = 2.0) -> list:
    """adjclose 100+i, unadjusted close scale*(100+i); later rows must never be read."""
    rows = [
        [d, 100.0 + i, scale * (100.0 + i)]
        for i, d in enumerate(sessions_until(end, n))
    ]
    return rows + [["2026-11-02", 1e9, 1e9], ["2026-11-03", 1e-9, 1e-9]]


def us_member(**extra) -> dict:
    member = dict(
        id="US:0000000001",
        market="US",
        name="Alpha",
        ticker="AAA",
        priceSymbol="AAA",
        cik="0000000001",
        sic="3571",
        sector="BusEq",
        shareClasses=[dict(ticker="AAA", priceSymbol="AAA")],
        status="eligible",
        reason=None,
    )
    return {**member, **extra}


def us_fundamentals(**extra) -> dict:
    record = dict(
        id="US:0000000001",
        status="ok",
        error=None,
        currency="USD",
        cfoTTM=120.0,
        capexTTM=20.0,
        assets=1000.0,
        shares=10.0,
        sharesBasis="cover",
        sharesAsOf="2026-10-20",
        periodEnd="2026-09-27",
        filedAt="2026-10-29",
        filings=[dict(form="10-K", filedAt="2026-10-29")],
        sources=[],
        notes=[],
    )
    return {**record, **extra}


def kr_member(**extra) -> dict:
    member = dict(
        id="KR:005930",
        market="KR",
        name="Samsung",
        ticker="005930",
        priceSymbol="005930.KS",
        corpCode="00126380",
        ksic="264",
        sector="BusEq",
        shareClasses=[
            dict(ticker="005930", priceSymbol="005930.KS", listedShares=100.0),
            dict(ticker="005935", priceSymbol="005935.KS", listedShares=10.0),
        ],
        status="eligible",
        reason=None,
    )
    return {**member, **extra}


def kr_fundamentals(**extra) -> dict:
    record = dict(
        id="KR:005930",
        status="ok",
        error=None,
        currency="KRW",
        cfoTTM=1000.0,
        capexTTM=300.0,
        assets=10000.0,
        listedShares=None,
        periodEnd="2026-06-30",
        filedAt="2026-08-14",
        filings=[],
        sources=[],
        notes=[],
    )
    return {**record, **extra}


def split(day: str, numerator, denominator) -> dict:
    return {"date": day, "numerator": numerator, "denominator": denominator}


def checked(
    member,
    record,
    prices,
    splits=None,
    as_of=AS_OF,
    retrieved=RETRIEVED,
    windows=None,
    captures=None,
):
    """signals() with split events (none unless given) read through ``retrieved``;
    ``windows`` (price windows by symbol) and ``captures`` (capture dates by market)
    are passed only when given."""
    events = {symbol: [] for symbol in prices}
    events.update(splits or {})
    extra = {} if windows is None else dict(windows_by_symbol=windows)
    if captures is not None:
        extra["capture_dates_by_market"] = captures
    return signals(
        member,
        record,
        prices,
        as_of,
        splits_by_symbol=events,
        retrieved_on=retrieved,
        **extra,
    )


def halted(rows: list, day: str = AS_OF) -> list:
    """The same rows without the session on ``day`` (trading halted that day)."""
    return [row for row in rows if row[0] != day]


def scored_input(key, market="US", sector="S", status="eligible", **values) -> dict:
    return dict(
        id=key,
        market=market,
        sector=sector,
        status=status,
        reason=None if status == "eligible" else "financial",
        asOf=AS_OF,
        signals={s: values.get(s) for s in rating.SIGNALS},
        issues=[],
    )


def ladder(n: int, market: str = "US") -> list:
    """n members in one sector whose composite rises with k (two equal signals)."""
    return [
        scored_input(
            f"{market}{k}", market, fcfYield=float(k), cashProfitability=float(k)
        )
        for k in range(1, n + 1)
    ]


def by_id(rows: list) -> dict:
    return {row["id"]: row for row in rows}


class ProtocolTests(unittest.TestCase):
    def test_constants_and_hash(self):
        self.assertEqual(PROTOCOL["version"], "ratings-v1")
        self.assertEqual(
            (PROTOCOL["winsor"]["lower"], PROTOCOL["winsor"]["upper"]), (0.01, 0.99)
        )
        self.assertEqual(PROTOCOL["minSectorSize"], 5)
        self.assertEqual(PROTOCOL["minSignals"], 2)
        self.assertEqual(PROTOCOL["hysteresis"], 0.5)
        self.assertEqual(PROTOCOL["costs"]["KR"], {"buy": 0.0005, "sell": 0.0025})
        self.assertEqual(PROTOCOL["costs"]["US"], {"buy": 0.0005, "sell": 0.0005})
        self.assertEqual(PROTOCOL["benchmarks"], {"US": "^SP500TR", "KR": "069500.KS"})
        self.assertEqual(PROTOCOL["financialExclusions"]["US"]["sic"], [[6000, 6799]])
        self.assertEqual(PROTOCOL_HASH, protocol_hash(PROTOCOL))
        changed = copy.deepcopy(PROTOCOL)
        changed["hysteresis"] = 0.4
        self.assertNotEqual(protocol_hash(changed), PROTOCOL_HASH)

    def test_registration_and_evaluation_decisions_are_hashed(self):
        self.assertEqual(PROTOCOL["registrationWindowSessions"], 5)  # D3
        self.assertEqual(PROTOCOL["universeFetchErrorMaxShare"], 0.05)  # D6
        self.assertEqual(PROTOCOL["evaluation"]["missedRegistrationExitSession"], 6)
        self.assertEqual(
            PROTOCOL["registration"]["sessionCalendar"],
            {"US": "^SP500TR", "KR": "069500.KS"},
        )
        self.assertEqual(
            PROTOCOL["decisions"]["computabilityCheck"]["thresholds"],
            {"US": 0.90, "KR": 0.80},
        )
        self.assertEqual(
            PROTOCOL["codeFiles"],
            [
                "ratings/*.py",
                "scripts/ratings.py",
                "equitylab/data.py",
                "equitylab/ledger.py",
                "equitylab/dart.py",
                "equitylab/forward_study.py",
            ],
        )
        root = Path(rating.__file__).resolve().parents[1]
        hashed = {
            path.relative_to(root).as_posix()
            for pattern in PROTOCOL["codeFiles"]
            for path in root.glob(pattern)
        }
        self.assertLessEqual(
            {
                "ratings/rating.py",
                "ratings/prices.py",
                "ratings/registry.py",
                "ratings/evaluate.py",
                "scripts/ratings.py",
            },
            hashed,
        )
        self.assertNotIn("late_entry", PROTOCOL["evaluation"]["entry"])  # D2
        # (path, needle) pairs, not a dict: one path may carry several decisions (L2).
        texts = [
            (("evaluation", "missingEntry"), "no_entry_price"),  # D2
            (("registration", "window"), "registrationWindowSessions"),  # D3
            (("registration", "order"), "never registered"),  # D3
            (("evaluation", "exit"), "missed_next_registration"),  # D4
            (("universe", "timing", "KR"), "T_close"),  # D5'
            (("universe", "timing", "US"), "holdingsAsOf"),  # D5'
            (("universe", "parts"), "<T>/<market>.json"),  # D5'
            (("universe", "fetchErrors"), "universe_fetch_error"),  # D6
            (("decisions", "computabilityCheck", "denominator"), "financial"),  # D6
            (("marketCap", "splits", "standard"), "nonstandard_split"),  # D7
            (("marketCap", "splits", "unknown"), "through date"),  # D7'
            (("pointInTime", "freshness"), "lagCheck"),  # D8'
            (("registration", "inputs"), "--refresh"),  # D9
            (("marketCap", "priceOnAsOf"), "no_price_on_as_of"),  # D9'
            (("decisions", "computabilityCheck", "gateEvent"), "coverage-gate"),  # D10
            (("decisions", "computabilityCheck", "gateRecording"), "incomplete"),
            (("registration", "integrity"), "codeFiles"),  # D11
            (("registration", "freeze"), "ratings-v2"),  # D11'
            (("evaluation", "freeze"), "revised_after_freeze"),  # D12'
            (("evaluation", "missingEntry"), "series_not_covering"),  # D12', M4
            (("evaluation", "missingEntry"), "series_ends_before_entry"),  # M4
            (("evaluation", "missingEntry"), "run's errors (exit 1)"),  # M4
            (("registration", "window"), "registrationDay"),  # D15
            (("hysteresisRule",), "its market"),  # D16
            (("evaluation", "freeze"), "freezeGraceDays calendar days"),  # L3
            (("evaluation", "freeze"), "unresolved"),  # L3
            (("evaluation", "freeze"), "frozen_with_unresolved"),  # L3
            (("evaluation", "freeze"), "never blocks the freezing of later"),  # L3
            (("marketCap", "splits", "KRAfterAsOf"), "(sharesCapturedOn, retrievedOn]"),
            (("marketCap", "splits", "KRCaptureAfterRetrieval"), "sharesCapturedOn"),
            (("signals", "fcfYield", "capex"), "capex_tag_understated"),  # D18
            (("signals", "fcfYield", "capex"), "only cfo_missing"),  # D18
            (("signals", "fcfYield", "capex"), "capex_parts_summed"),  # D20
            (("signals", "fcfYield", "capex"), "capex_includes_investment_property"),
            (("signals", "momentum12_1", "definition"), "nullSessions"),  # D19
        ]
        for path, needle in texts:
            with self.subTest(path=path, needle=needle):
                changed = copy.deepcopy(PROTOCOL)
                parent = changed
                for key in path[:-1]:
                    parent = parent[key]
                self.assertIn(needle, parent[path[-1]])
                parent[path[-1]] += " (edited)"
                self.assertNotEqual(protocol_hash(changed), PROTOCOL_HASH)
        for key in ("registrationWindowSessions", "universeFetchErrorMaxShare"):
            changed = copy.deepcopy(PROTOCOL)
            changed[key] = 0
            self.assertNotEqual(protocol_hash(changed), PROTOCOL_HASH)
        self.assertEqual(PROTOCOL["marketClose"], {"US": "16:00", "KR": "15:30"})
        self.assertNotIn("marketClose", PROTOCOL["registration"])  # one source

    def test_round_three_decisions_are_pinned_in_the_protocol(self):
        # L3: member errors hold a completed period's freeze back for 30 calendar days.
        self.assertEqual(PROTOCOL["evaluation"]["freezeGraceDays"], 30)
        self.assertEqual(rating.FREEZE_GRACE_DAYS, 30)
        changed = copy.deepcopy(PROTOCOL)
        changed["evaluation"]["freezeGraceDays"] = 31
        self.assertNotEqual(protocol_hash(changed), PROTOCOL_HASH)
        # M4: a series ending before entry is excluded and counted as an error; one
        # starting after entry is an error; neither is a missing entry price.
        text = PROTOCOL["evaluation"]["missingEntry"]
        self.assertIn("series that covers that session is excluded", text)
        self.assertIn("starts after the entry session (series_not_covering)", text)
        self.assertIn("ends before the entry session is excluded", text)
        self.assertIn(
            "(series_ends_before_entry) and counted in the run's errors", text
        )
        self.assertNotIn("does not cover its period is an error", text)
        # L4: KR splits are compared with the listed shares' capture date, not T.
        kr = PROTOCOL["marketCap"]["splits"]["KRAfterAsOf"]
        self.assertNotIn("(T, retrievedOn]", kr)
        self.assertIn("capturedAt, rankingCapturedAt, rankingRetrievedAt", kr)
        self.assertEqual(
            rating.CAPTURE_FIELDS,
            ("capturedAt", "rankingCapturedAt", "rankingRetrievedAt"),
        )

    def test_round_four_rules_are_described_in_the_hashed_texts(self):
        """N3: the hashed texts describe the implemented rules (they freeze with the
        first coverage-gate event): the universe stems and merges, the KR candidate
        pool and its only unranked reasons, the FF12 pinned original, the official
        evaluation, the per-market freeze date and frozen costs (N2, N5), the gate
        event's L1 fields and the gate's file checks (N7), and the KR capture after
        the price retrieval (N6)."""
        texts = {
            ("universe", "parts"): (
                "data/ratings/universe/<T>/<market>.json",
                "data/ratings/universe/<asOf>.json (asOf: the later T)",
                "mergedAt",
                "only part of the month",
                "rewritten only when a part changes",
                "removed only when every market it holds has the same T",
                "<asOf>-gate/<market>.json",
                "<asOf>-gate.json",
                "<T>-limit<N>/",
                "no kind of universe ever merges, replaces or removes",
            ),
            ("universe", "KR", "tCloseMarketCap"): (
                "candidatePool largest commons by Naver market value",
                "market cap at T's close",
                "retrieved after T's closes settle",
                "class_price_proxy",
                universes.HALTED,
                universes.NOT_FOUND,
                universes.NOT_LISTED,
                "listed after T or halted throughout",
                "(close_unsettled)",
                "transient download failure",
                "symbol or currency mismatch",
                "undecodable response",
                "the KR part is an error and is rebuilt",
            ),
            ("sectors", "US"): (
                "R12",
                "L5",
                "ff12_stored_original",
                "ff12_definition_changed_pinned_used",
                "offline",
                "whose content matches its name",
                "makes the US part an error",
                "(ff12_definition_changed)",
            ),
            ("evaluation", "official"): (
                "full ledger without dry runs",
                "online run",
                "evaluation date not after today",
            ),
            ("evaluation", "freeze"): (
                "not after that market's local date",  # N2
                "turnover and costs",  # N5
                "net metrics included",
            ),
            ("decisions", "computabilityCheck", "gateEvent"): (
                "mergedAt",
                "every universe part file with its sha256",
                "checkpoint file the counts came from with its sha256 and byte length",
                "protocolHash",
            ),
            ("decisions", "computabilityCheck", "gateRecording"): (
                "computability-check universe",
                "<asOf>-gate/",
                # N7 (L3: what is hashed again, what the merged file must hold)
                "every part file the merge recorded with a sha256 is hashed again",
                "must still hold the universe being recorded",
                "incomplete",
                "nothing is recorded",
            ),
            ("marketCap", "splits", "KRCaptureAfterRetrieval"): (
                rating.CAPTURE_AFTER_RETRIEVAL,
                "withheld",
            ),
        }
        for path, needles in texts.items():
            text = PROTOCOL
            for key in path:
                text = text[key]
            for needle in needles:
                with self.subTest(path=path, needle=needle):
                    self.assertIn(needle, text)
        # The superseded wording is gone.
        self.assertNotIn("<asOf>/<market>.json", PROTOCOL["universe"]["parts"])
        unchecked = PROTOCOL["marketCap"]["splits"]["unchecked"]
        self.assertNotIn("captured after it", unchecked)
        self.assertEqual(
            universes.RULES["KR"]["unrankedReasons"],
            ["no_close_on_as_of", "symbol_not_found", "not_listed_on_as_of"],
        )

    def test_round_five_rules_are_described_in_the_hashed_texts(self):
        """M1, M2, L1, L2, L3: the hashed texts (frozen with the first coverage-gate
        event) say that the KR ranking series are requested through the build's
        Asia/Seoul date and that Yahoo's HTTP 400 "Data doesn't exist" is an answer
        without sessions; that a part used by a registration or a gate is built
        online; that capture_after_retrieval is stale; that the error rules are those
        of the common stock; and what the gate hashes again."""
        kr = PROTOCOL["universe"]["KR"]["tCloseMarketCap"]
        rules = universes.RULES["KR"]
        texts = {
            ("universe", "KR", "tCloseMarketCap"): (
                "requested through the build's Asia/Seoul date",
                "sessions after T show; they are never used",
                "every Yahoo host answers the request for its common",
                "sessions after T only or none",
                'with HTTP 400 whose chart error description starts with "Data '
                "doesn't exist\"",
                "or with HTTP 404",
                "for the common stock of a candidate a series read before T's closes "
                "settle (close_unsettled)",
                "or any other HTTP 400",
                "for any of its classes a series read before T's closes settle or no "
                "listed shares",
                "a preferred class without its own close on T (no session on T, every "
                "Yahoo host HTTP 404, or a rejected original) is priced at the common "
                "close (class_price_proxy), but one whose close on T is unsettled, "
                "traded without a published close (D17: close_unpublished) or whose "
                "download failed transiently (moduleRules.prices.transientFailure) "
                "makes the KR part an error (rebuilt)",
            ),
            ("universe", "timing", "builtAt"): (
                "built online (markets[m].online true)",
                "refuses a registered or gated market whose part was not built online",
            ),
            ("decisions", "computabilityCheck", "gateRecording"): (
                "the market's part built online",
                "a part built offline",
                "every part file the merge recorded with a sha256 is hashed again and "
                "must still have that sha256",
                "the merged file is read again and must still hold the universe being "
                "recorded (its canonical sha256, the event's universeSha256",
                "the merge records no hash of the merged file itself",
                "not capture_after_retrieval",
            ),
            ("registration", "inputs"): (
                "no earlier than sharesCapturedOn of the universe",
                "capture_after_retrieval",
            ),
            ("marketCap", "splits", "KRCaptureAfterRetrieval"): (
                "its checkpoint is stale (registration.inputs)",
            ),
            ("moduleRules", "prices", "noData"): (
                'HTTP 400 answer whose chart.error.description starts with "Data '
                "doesn't exist\"",
                "(NoSessions)",
                "any other HTTP 400 is a rejected original",
            ),
            ("moduleRules", "prices", "requestThrough"): (
                "requested through a later date than its window",
                "window, rows, splits and stored key stay those of the window",
            ),
            ("moduleRules", "universe", "KR", "unranked"): (
                "every Yahoo host answers the request for its common's symbol",
                "sessions after T only (listed after T)",
                'with HTTP 400 whose chart error description starts with "Data '
                "doesn't exist\"",
                "any other HTTP 400",
            ),
            ("moduleRules", "universe", "KR", "ranking"): (
                "requested through the build's Asia/Seoul date: request_through, not "
                "T+2",
                "a preferred class without its own close on T",
            ),
            ("moduleRules", "universe", "timing", "build"): (
                "a market whose part was not built online",
            ),
        }
        for path, needles in texts.items():
            text = PROTOCOL
            for key in path:
                text = text[key]
            for needle in needles:
                with self.subTest(path=path, needle=needle):
                    self.assertIn(needle, text)
        # The superseded wording is gone.
        gate = PROTOCOL["decisions"]["computabilityCheck"]["gateRecording"]
        self.assertNotIn("still hash to what the merge recorded", gate)
        self.assertNotIn("a class without its own close on T uses the common", kr)
        self.assertNotIn("(prices.series through T,", rules["ranking"])
        self.assertEqual(
            (price_data.NO_DATA_STATUS, price_data.NO_DATA), (400, "Data doesn't exist")
        )
        # The texts are hashed: changing the no-data rule changes the protocol.
        changed = copy.deepcopy(PROTOCOL)
        changed["moduleRules"]["prices"]["noData"] = "any HTTP 400 is an error"
        self.assertNotEqual(protocol_hash(changed), PROTOCOL_HASH)

    def test_round_two_decisions_are_pinned_in_the_protocol(self):
        # D5': regular closes with their zones, the KR candidate pool and ranking basis
        self.assertEqual(PROTOCOL["marketClose"], {"US": "16:00", "KR": "15:30"})
        self.assertEqual(
            PROTOCOL["registration"]["timezones"],
            {"US": "America/New_York", "KR": "Asia/Seoul"},
        )
        kr = PROTOCOL["universe"]["KR"]
        self.assertEqual((kr["size"], kr["candidatePool"]), (200, 260))
        self.assertEqual(kr["rankingBasis"], "T_close")
        # The universe module's own copies (hashed in moduleRules) must agree.
        rules = universes.RULES["KR"]
        self.assertEqual(rules.get("candidatePool", 260), kr["candidatePool"])
        self.assertEqual(rules.get("top", 200), kr["size"])
        self.assertEqual(rules.get("rankingBasis", "T_close"), kr["rankingBasis"])
        timing = universes.RULES.get("timing") or {}
        self.assertEqual(
            timing.get("marketClose", PROTOCOL["marketClose"]), PROTOCOL["marketClose"]
        )
        self.assertEqual(
            timing.get("timezones", PROTOCOL["registration"]["timezones"]),
            PROTOCOL["registration"]["timezones"],
        )
        # D10': the gate's T is the last session before the check date in both markets
        check = PROTOCOL["decisions"]["computabilityCheck"]
        self.assertEqual((check["asOf"], check["date"]), ("2026-10-19", "2026-10-20"))
        self.assertEqual(date.fromisoformat(check["asOf"]).weekday(), 0)  # a Monday
        for path, value in (
            (("marketClose", "KR"), "15:31"),
            (("universe", "KR", "candidatePool"), 250),
            (("decisions", "computabilityCheck", "asOf"), "2026-10-16"),
            (("moduleRules", "sectorReferences", "ksicReferenceSha256"), "0" * 64),
        ):
            with self.subTest(path=path):
                changed = copy.deepcopy(PROTOCOL)
                parent = changed
                for key in path[:-1]:
                    parent = parent[key]
                parent[path[-1]] = value
                self.assertNotEqual(protocol_hash(changed), PROTOCOL_HASH)

    def test_ksic_reference_is_a_literal_pin(self):
        """D11': the KSIC table hash is written into rating.py, not read at import, and
        the table in the repository is the pinned one."""
        pin = PROTOCOL["moduleRules"]["sectorReferences"]["ksicReferenceSha256"]
        self.assertEqual(pin, rating.KSIC_REFERENCE_SHA256)
        self.assertRegex(pin, r"\A[0-9a-f]{64}\Z")
        source = Path(rating.__file__).read_text(encoding="utf-8")
        self.assertIn(f'"{pin}"', source)
        self.assertNotIn("KSIC_REFERENCE.read_bytes", source)
        self.assertEqual(digest(sectors.KSIC_REFERENCE.read_bytes()), pin)

    def test_constants_used_elsewhere_are_pinned_in_the_protocol(self):
        # registry.setting() falls back to unhashed defaults for a name PROTOCOL lacks
        # (top level or one level down); every such name must be in PROTOCOL itself.
        from ratings import registry

        for name, value in getattr(registry, "DEFAULTS", {}).items():
            with self.subTest(name):
                nested = [v for v in PROTOCOL.values() if isinstance(v, dict)]
                found = [PROTOCOL[name]] if name in PROTOCOL else []
                found += [v[name] for v in nested if name in v]
                self.assertEqual(found[:1], [value])


class MomentumSessionTests(unittest.TestCase):
    """D19: sessions a series lists without a close count as sessions, never priced."""

    def setUp(self):
        self.rows = price_rows()[:300]  # adjclose 100+i; index 299 is T
        self.clean = rating.momentum_12_1(self.rows, AS_OF)

    def without(self, *indices):
        rows = [r for i, r in enumerate(self.rows) if i not in indices]
        return rows, [self.rows[i][0] for i in indices]

    def test_a_clean_series_is_unchanged(self):
        self.assertEqual(
            self.clean, (378 / 147 - 1, [], [self.rows[47][0], self.rows[278][0]], [])
        )

    def test_a_blank_session_inside_the_window_keeps_the_window(self):
        rows, blank = self.without(100)
        value, issues, window, gaps = rating.momentum_12_1(rows, AS_OF, blank)
        self.assertEqual((value, window), self.clean[:1] + self.clean[2:3])
        self.assertEqual((issues, gaps), (["momentum_session_gap"], blank))
        # Counting own rows only moves the start one session earlier.
        self.assertEqual(rating.momentum_12_1(rows, AS_OF)[0], 378 / 146 - 1)

    def test_a_blank_endpoint_uses_the_last_own_close_before_it(self):
        flags = ["momentum_endpoint_stale", "momentum_session_gap"]
        rows, blank = self.without(47)
        value, issues, window, _ = rating.momentum_12_1(rows, AS_OF, blank)
        self.assertEqual((value, issues), (378 / 146 - 1, flags))
        self.assertEqual(window, [self.rows[46][0], self.rows[278][0]])
        rows, blank = self.without(278)
        value, issues, window, _ = rating.momentum_12_1(rows, AS_OF, blank)
        self.assertEqual((value, issues), (377 / 147 - 1, flags))
        self.assertEqual(window, [self.rows[47][0], self.rows[277][0]])

    def test_blanks_outside_the_window_change_nothing(self):
        for index in (10, 290):  # before T-252; inside the skipped month
            rows, blank = self.without(index)
            self.assertEqual(rating.momentum_12_1(rows, AS_OF, blank), self.clean)
        after = ["2026-11-02"]
        self.assertEqual(rating.momentum_12_1(self.rows, AS_OF, after), self.clean)

    def test_t_itself_still_needs_an_own_close(self):
        rows, blank = self.without(299)
        self.assertEqual(
            rating.momentum_12_1(rows, AS_OF, blank),
            (None, ["no_price_on_as_of"], None, []),
        )

    def test_history_counts_blank_sessions_but_needs_an_own_start(self):
        rows = self.rows[47:]  # exactly 253 own sessions through T
        self.assertEqual(rating.momentum_12_1(rows, AS_OF)[0], 378 / 147 - 1)
        short, blank = rows[1:], [rows[0][0]]  # the start is a blank session
        self.assertEqual(
            rating.momentum_12_1(short, AS_OF, blank),
            (None, ["momentum_history_short"], None, []),
        )

    def test_signals_pass_the_series_blank_sessions(self):
        rows, blank = self.without(100)
        row = signals(
            us_member(),
            us_fundamentals(),
            {"AAA": rows},
            AS_OF,
            null_sessions_by_symbol={"AAA": blank},
        )
        self.assertAlmostEqual(row["signals"]["momentum12_1"], 378 / 147 - 1)
        self.assertIn("momentum_session_gap", row["issues"])
        self.assertEqual(row["inputs"]["momentumGaps"], blank)


class SignalTests(unittest.TestCase):
    def test_us_signals_use_only_data_known_at_as_of(self):
        rows = price_rows()
        row = checked(us_member(), us_fundamentals(), {"AAA": rows})
        close = 2.0 * (100.0 + 299)
        self.assertEqual(row["status"], "eligible")
        self.assertEqual(row["marketCap"], 10.0 * close)
        self.assertAlmostEqual(row["signals"]["fcfYield"], 100.0 / (10.0 * close))
        self.assertAlmostEqual(row["signals"]["cashProfitability"], 0.12)
        self.assertAlmostEqual(
            row["signals"]["momentum12_1"], (100.0 + 278) / (100.0 + 47) - 1
        )
        self.assertEqual(row["inputs"]["momentumWindow"], [rows[47][0], rows[278][0]])
        self.assertEqual(row["inputs"]["closeDate"], AS_OF)
        self.assertEqual(
            (row["inputs"]["splitFactor"], row["inputs"]["retrievedOn"]),
            (1.0, RETRIEVED),
        )
        self.assertEqual(row["issues"], [])
        proxy = checked(
            us_member(shareClasses=[dict(priceSymbol="AAA"), dict(priceSymbol="AAB")]),
            us_fundamentals(sharesBasis="diluted_wavg_proxy"),
            {"AAA": rows},
        )
        self.assertEqual(proxy["marketCap"], row["marketCap"])
        both = {"US": AS_OF, "KR": "2026-10-29"}
        same = checked(us_member(), us_fundamentals(), {"AAA": rows}, as_of=both)
        self.assertEqual((same["asOf"], same["signals"]), (AS_OF, row["signals"]))
        self.assertEqual(proxy["issues"], ["shares_proxy", "multi_class_single_price"])
        # A caller without split events keeps the old product, flagged as unchecked.
        legacy = signals(us_member(), us_fundamentals(), {"AAA": rows}, AS_OF)
        self.assertEqual(legacy["marketCap"], row["marketCap"])
        self.assertEqual(legacy["issues"], ["splits_unchecked"])

    def test_filing_on_or_after_as_of_is_not_used(self):
        for record in (
            us_fundamentals(filedAt=AS_OF),
            us_fundamentals(filings=[dict(filedAt="2026-10-01"), dict(filedAt=AS_OF)]),
        ):
            row = signals(us_member(), record, {"AAA": price_rows()}, AS_OF)
            self.assertIn("filed_on_or_after_as_of", row["issues"])
            self.assertIsNone(row["signals"]["fcfYield"])
            self.assertIsNone(row["signals"]["cashProfitability"])
            self.assertIsNotNone(row["signals"]["momentum12_1"])
        row = signals(
            us_member(), us_fundamentals(filedAt=None), {"AAA": price_rows()}, AS_OF
        )
        self.assertIn("filed_at_missing", row["issues"])
        self.assertIsNone(row["signals"]["cashProfitability"])

    def test_kr_market_cap_sums_share_classes(self):
        prices = {
            "005930.KS": price_rows(),
            "005935.KS": price_rows(scale=600.0 / 399.0),
        }
        row = signals(kr_member(), kr_fundamentals(), prices, AS_OF)
        self.assertAlmostEqual(row["marketCap"], 100 * 798.0 + 10 * 600.0)
        self.assertAlmostEqual(row["signals"]["fcfYield"], 700.0 / 85800.0)
        self.assertNotIn("class_price_proxy", row["issues"])
        proxy = signals(
            kr_member(), kr_fundamentals(), {"005930.KS": price_rows()}, AS_OF
        )
        self.assertAlmostEqual(proxy["marketCap"], 110 * 798.0)
        self.assertIn("class_price_proxy", proxy["issues"])
        self.assertTrue(proxy["inputs"]["shareClasses"][1]["priceProxy"])

    def test_missing_or_negative_market_cap_gives_no_fcf_yield(self):
        member = kr_member(
            shareClasses=[
                dict(ticker="005930", priceSymbol="005930.KS", listedShares=-5)
            ]
        )
        row = signals(member, kr_fundamentals(), {"005930.KS": price_rows()}, AS_OF)
        self.assertLess(row["marketCap"], 0)
        self.assertIsNone(row["signals"]["fcfYield"])
        self.assertIn("market_cap_nonpositive", row["issues"])
        self.assertAlmostEqual(row["signals"]["cashProfitability"], 0.1)
        unknown = kr_member(
            shareClasses=[dict(ticker="005930", priceSymbol="005930.KS")]
        )
        row = signals(unknown, kr_fundamentals(), {"005930.KS": price_rows()}, AS_OF)
        self.assertIsNone(row["marketCap"])
        self.assertIn("listed_shares_missing", row["issues"])
        self.assertIn("market_cap_missing", row["issues"])
        fallback = signals(
            unknown,
            kr_fundamentals(listedShares=100.0),
            {"005930.KS": price_rows()},
            AS_OF,
        )
        self.assertAlmostEqual(fallback["marketCap"], 100 * 798.0)
        row = signals(
            us_member(), us_fundamentals(shares=None), {"AAA": price_rows()}, AS_OF
        )
        self.assertIn("shares_missing", row["issues"])
        self.assertIsNone(row["signals"]["fcfYield"])
        self.assertIsNotNone(row["signals"]["cashProfitability"])

    def test_capex_currency_and_assets_rules(self):
        cases = [
            (dict(capexTTM=-20.0), "capex_negative", "fcfYield"),
            (dict(capexTTM=None), "capex_missing", "fcfYield"),
            (dict(currency="EUR"), "currency_mismatch", "fcfYield"),
            (dict(assets=0.0), "assets_nonpositive", "cashProfitability"),
        ]
        for change, issue, missing in cases:
            row = signals(
                us_member(), us_fundamentals(**change), {"AAA": price_rows()}, AS_OF
            )
            self.assertIn(issue, row["issues"])
            self.assertIsNone(row["signals"][missing])
        row = signals(
            us_member(), us_fundamentals(currency="EUR"), {"AAA": price_rows()}, AS_OF
        )
        self.assertAlmostEqual(row["signals"]["cashProfitability"], 0.12)

    def test_without_cfo_only_cfo_missing_is_reported(self):
        # D18: a US capex trailing year forms only over the CFO one; a KR record's
        # error still names its own capex failure.
        for member, records, prices in (
            (us_member(), us_fundamentals, {"AAA": price_rows()}),
            (kr_member(), kr_fundamentals, {"005930.KS": price_rows()}),
        ):
            with self.subTest(market=member["market"]):
                row = signals(
                    member, records(cfoTTM=None, capexTTM=None), prices, AS_OF
                )
                self.assertIn("cfo_missing", row["issues"])
                self.assertNotIn("capex_missing", row["issues"])
                self.assertIsNone(row["signals"]["fcfYield"])
                self.assertIsNone(row["signals"]["cashProfitability"])

    def test_price_edge_cases(self):
        short = signals(
            us_member(), us_fundamentals(), {"AAA": price_rows(n=200)}, AS_OF
        )
        self.assertIsNone(short["signals"]["momentum12_1"])
        self.assertIn("momentum_history_short", short["issues"])
        ended = signals(
            us_member(), us_fundamentals(), {"AAA": price_rows(end="2026-10-23")}, AS_OF
        )
        self.assertIn("no_price_on_as_of", ended["issues"])
        self.assertNotIn("stale_price", ended["issues"])
        self.assertEqual(
            (ended["marketCap"], ended["inputs"]["closeDate"]), (None, None)
        )
        none = signals(us_member(), us_fundamentals(), {}, AS_OF)
        self.assertIn("price_series_missing", none["issues"])
        self.assertIn("no_price_on_as_of", none["issues"])
        self.assertIsNone(none["marketCap"])
        both = signals(us_member(), us_fundamentals(shares=None), {}, AS_OF)
        self.assertLessEqual(
            {"shares_missing", "no_price_on_as_of"}, set(both["issues"])
        )

    def test_halt_on_as_of_gives_no_price_based_signals(self):
        """D9': a member without its own session on T has no market cap, FCF yield or
        momentum; an earlier close is never used, with or without split checks."""
        rows = halted(price_rows())  # traded before and after T, not on T
        for name, row in (
            ("checked", checked(us_member(), us_fundamentals(), {"AAA": rows})),
            ("plain", signals(us_member(), us_fundamentals(), {"AAA": rows}, AS_OF)),
        ):
            with self.subTest(name):
                self.assertEqual(
                    row["signals"],
                    dict(fcfYield=None, cashProfitability=0.12, momentum12_1=None),
                )
                self.assertIsNone(row["marketCap"])
                self.assertIn("no_price_on_as_of", row["issues"])
                self.assertNotIn("stale_price", row["issues"])
                self.assertEqual(
                    (row["inputs"]["close"], row["inputs"]["closeDate"]), (None, None)
                )
                self.assertIsNone(row["inputs"]["momentumWindow"])
        self.assertEqual(
            rating.momentum_12_1(rows, AS_OF), (None, ["no_price_on_as_of"], None, [])
        )
        self.assertIsNone(rating.close_on(rows, AS_OF))
        # KR: the common halted on T has no cap even though the preferred traded.
        preferred = price_rows(scale=600.0 / 399.0)
        prices = {"005930.KS": rows, "005935.KS": preferred}
        row = checked(kr_member(), kr_fundamentals(), prices)
        self.assertEqual((row["marketCap"], row["signals"]["fcfYield"]), (None, None))
        self.assertIsNone(row["signals"]["momentum12_1"])
        self.assertIn("no_price_on_as_of", row["issues"])
        self.assertAlmostEqual(row["signals"]["cashProfitability"], 0.1)
        # KR: a preferred halted on T takes the common close on T, not its own
        # earlier close (as the universe's T-close market cap does).
        prices = {"005930.KS": price_rows(), "005935.KS": halted(preferred)}
        row = checked(kr_member(), kr_fundamentals(), prices)
        self.assertAlmostEqual(row["marketCap"], 110 * 798.0)
        self.assertIn("class_price_proxy", row["issues"])
        self.assertNotIn("no_price_on_as_of", row["issues"])
        self.assertNotIn("stale_price", row["issues"])
        part = row["inputs"]["shareClasses"][1]
        self.assertEqual((part["priceProxy"], part["closeDate"]), (True, AS_OF))
        self.assertIsNotNone(row["signals"]["momentum12_1"])

    def test_fundamentals_issues_and_lag_check_reach_the_row(self):
        """D8': the record's issues and lagCheck are kept in the signal and rated rows."""
        lag = dict(
            status="lag",
            source="sec-submissions-CIK0000000001",
            sha256="1" * 64,
            retrievedAt="2026-10-31T00:00:00+00:00",
            detail="10-Q for 2026-09-27 filed before asOf; facts end 2026-06-28",
        )
        record = us_fundamentals(
            status="insufficient",
            error="companyfacts_lag: newer 10-Q",
            cfoTTM=None,
            capexTTM=None,
            assets=None,
            issues=["companyfacts_lag"],
            lagCheck=lag,
            withheld=dict(cfoTTM=120.0, periodEnd="2026-06-28"),
        )
        row = checked(us_member(), record, {"AAA": price_rows()})
        self.assertLessEqual(
            {"fundamentals_insufficient", "companyfacts_lag"}, set(row["issues"])
        )
        self.assertEqual(row["inputs"]["lagCheck"], lag)
        self.assertEqual(row["inputs"]["fundamentalsIssues"], ["companyfacts_lag"])
        self.assertIsNone(row["signals"]["cashProfitability"])
        rated = score([row])[0]
        self.assertIn("companyfacts_lag", rated["issues"])
        self.assertEqual(rated["inputs"]["lagCheck"], lag)
        # An unavailable check leaves the record usable but visible.
        unavailable = dict(status="unavailable", detail="offline without an original")
        record = us_fundamentals(issues=["lag_check_unavailable"], lagCheck=unavailable)
        row = checked(us_member(), record, {"AAA": price_rows()})
        self.assertIn("lag_check_unavailable", row["issues"])
        self.assertEqual(row["inputs"]["lagCheck"], unavailable)
        self.assertAlmostEqual(row["signals"]["cashProfitability"], 0.12)
        kr = kr_fundamentals(
            status="insufficient",
            cfoTTM=None,
            capexTTM=None,
            assets=None,
            issues=["dart_api_lag"],
            lagCheck=dict(status="lag", latestReport="20261114000123"),
        )
        row = signals(kr_member(), kr, {"005930.KS": price_rows()}, AS_OF)
        self.assertIn("dart_api_lag", row["issues"])
        self.assertEqual(row["inputs"]["lagCheck"]["latestReport"], "20261114000123")
        # A clean record adds nothing; another member's record lends no findings.
        clean = checked(us_member(), us_fundamentals(), {"AAA": price_rows()})
        self.assertEqual(
            (clean["inputs"]["fundamentalsIssues"], clean["inputs"]["lagCheck"]),
            ([], None),
        )
        other = us_fundamentals(
            id="US:0000000002", issues=["companyfacts_lag"], lagCheck=lag
        )
        row = checked(us_member(), other, {"AAA": price_rows()})
        self.assertIn("fundamentals_id_mismatch", row["issues"])
        self.assertNotIn("companyfacts_lag", row["issues"])
        self.assertIsNone(row["inputs"]["lagCheck"])

    def test_excluded_and_failing_members_never_raise(self):
        excluded = signals(
            us_member(status="excluded", reason="SIC 6022"), None, {}, AS_OF
        )
        self.assertEqual(excluded["status"], "excluded")
        self.assertEqual(excluded["reason"], "SIC 6022")
        self.assertEqual(excluded["signals"], dict.fromkeys(rating.SIGNALS))
        broken = signals(us_member(), us_fundamentals(), {"AAA": [[AS_OF]]}, AS_OF)
        self.assertEqual(broken["status"], "eligible")
        self.assertIn("signal_error", broken["issues"])
        self.assertIn("IndexError", broken["error"])
        error = signals(
            us_member(), us_fundamentals(status="error", error="HTTP 404"), {}, AS_OF
        )
        self.assertIn("fundamentals_error", error["issues"])
        self.assertEqual(error["inputs"]["fundamentalsError"], "HTTP 404")
        mismatch = signals(us_member(), us_fundamentals(id="US:0000000002"), {}, AS_OF)
        self.assertIn("fundamentals_id_mismatch", mismatch["issues"])
        garbage = signals({}, None, None, AS_OF)
        self.assertEqual(garbage["status"], "excluded")
        self.assertIn("unknown_status", garbage["issues"])


class SplitTests(unittest.TestCase):
    """D7: US cap = shares x Yahoo close(T) x integer splits in (sharesAsOf, retrieval]."""

    CLOSE = 2.0 * (100.0 + 299)  # price_rows() close at AS_OF, on the restated basis

    def test_nvda_like_split_between_share_count_and_as_of(self):
        # NVIDIA: 2.46B cover shares as of 2024-05-22 (10-Q filed 05-29), 10-for-1
        # split ex 2024-06-10, close 123.54 at T = 2024-06-28.
        as_of = "2024-06-28"
        rows = [
            [d, 100.0 + i, 123.54] for i, d in enumerate(sessions_until(as_of, 300))
        ]
        record = us_fundamentals(
            cfoTTM=4.0e10,
            capexTTM=1.0e9,
            shares=2.46e9,
            sharesAsOf="2024-05-22",
            periodEnd="2024-04-28",
            filedAt="2024-05-29",
            filings=[dict(form="10-Q", filedAt="2024-05-29")],
        )
        events = {"AAA": [split("2024-06-10", 10.0, 1.0)]}
        row = checked(us_member(), record, {"AAA": rows}, events, as_of, "2024-07-01")
        self.assertAlmostEqual(row["marketCap"] / 1e12, 2.46e10 * 123.54 / 1e12)
        self.assertGreater(row["marketCap"], 3e12)
        self.assertAlmostEqual(
            row["signals"]["fcfYield"], 3.9e10 / (2.46e10 * 123.54), places=15
        )
        self.assertIn("shares_split_adjusted", row["issues"])
        self.assertEqual(row["inputs"]["splitFactor"], 10.0)
        self.assertEqual(row["inputs"]["splitsSinceShares"], events["AAA"])
        unadjusted = signals(us_member(), record, {"AAA": rows}, as_of)
        self.assertAlmostEqual(
            unadjusted["marketCap"] * 10 / 1e12, row["marketCap"] / 1e12
        )
        self.assertIn("splits_unchecked", unadjusted["issues"])

    def test_split_between_as_of_and_retrieval(self):
        rows = price_rows()
        record = us_fundamentals()  # cover shares as of 2026-10-20, filed 2026-10-29
        events = [
            split("2026-09-01", 3.0, 1.0),  # before the count: already in it
            split("2026-10-20", 7.0, 1.0),  # on sharesAsOf: already in it
            split("2026-11-02", 10.0, 1.0),  # after T: the T close was restated
            split("2026-11-04", 2.0, 1.0),  # after retrieval: not in the close
        ]
        row = checked(us_member(), record, {"AAA": rows}, {"AAA": events})
        self.assertEqual(row["marketCap"], 10.0 * self.CLOSE * 10)
        self.assertEqual(row["inputs"]["splitsSinceShares"], [events[2]])
        self.assertIn("shares_split_adjusted", row["issues"])
        edge = checked(
            us_member(), record, {"AAA": rows}, {"AAA": [split(RETRIEVED, 5, 1)]}
        )
        self.assertEqual(
            edge["marketCap"], 10.0 * self.CLOSE * 5
        )  # retrieval day counts

    def test_reverse_split(self):
        events = {"AAA": [split("2026-10-26", 1.0, 20.0)]}
        row = checked(us_member(), us_fundamentals(), {"AAA": price_rows()}, events)
        self.assertEqual(row["marketCap"], 10.0 * self.CLOSE / 20)
        self.assertEqual(row["inputs"]["splitFactor"], 0.05)
        self.assertAlmostEqual(row["signals"]["fcfYield"], 100.0 / (self.CLOSE / 2))
        repeated = {"AAA": events["AAA"] * 2}  # a provider duplicate counts once
        row = checked(us_member(), us_fundamentals(), {"AAA": price_rows()}, repeated)
        self.assertEqual(row["marketCap"], 10.0 * self.CLOSE / 20)
        both = [split("2026-10-22", 3, 2), split("2026-10-26", 1, 3)]
        row = checked(
            us_member(), us_fundamentals(), {"AAA": price_rows()}, {"AAA": both}
        )
        self.assertEqual(row["marketCap"], 10.0 * self.CLOSE / 2)  # exact 3/2 x 1/3

    def test_nonstandard_split_withholds_the_market_cap(self):
        for numerator, denominator in (
            (0.650391, 1.0),  # 207940.KS spin-off shown as a split
            (1.05, 1.0),  # 068270.KS bonus issue shown as a split
            (0, 1),
            (10, None),
            (True, 1),
        ):
            with self.subTest(ratio=(numerator, denominator)):
                events = {"AAA": [split("2026-10-26", numerator, denominator)]}
                row = checked(
                    us_member(), us_fundamentals(), {"AAA": price_rows()}, events
                )
                self.assertIsNone(row["marketCap"])
                self.assertIn("nonstandard_split", row["issues"])
                self.assertIn("market_cap_missing", row["issues"])
                self.assertIsNone(row["signals"]["fcfYield"])
                self.assertAlmostEqual(row["signals"]["cashProfitability"], 0.12)
                self.assertIsNotNone(row["signals"]["momentum12_1"])
        outside = {"AAA": [split("2026-03-02", 0.650391, 1.0)]}  # before the count
        row = checked(us_member(), us_fundamentals(), {"AAA": price_rows()}, outside)
        self.assertEqual(row["marketCap"], 10.0 * self.CLOSE)
        self.assertNotIn("nonstandard_split", row["issues"])
        self.assertEqual(rating.split_ratio(3.0, 2.0), Fraction(3, 2))

    def test_unknown_split_information_withholds_the_us_market_cap(self):
        rows = price_rows()
        cases = {
            "symbol without events": dict(splits_by_symbol={"AAB": []}),
            "no events": dict(splits_by_symbol=None),
            "no retrieval date": dict(splits_by_symbol={"AAA": []}, retrieved_on=None),
            "sessions after retrieval": dict(retrieved_on="2026-11-02"),
            "undated event": dict(splits_by_symbol={"AAA": [dict(numerator=2)]}),
            "conflicting events on one day": dict(
                splits_by_symbol={
                    "AAA": [split("2026-10-26", 2, 1), split("2026-10-26", 3, 1)]
                }
            ),
        }
        for name, change in cases.items():
            with self.subTest(name):
                kwargs = dict(splits_by_symbol={"AAA": []}, retrieved_on=RETRIEVED)
                kwargs.update(change)
                row = signals(
                    us_member(), us_fundamentals(), {"AAA": rows}, AS_OF, **kwargs
                )
                self.assertIsNone(row["marketCap"])
                self.assertIn("splits_unknown", row["issues"])
                self.assertIsNone(row["signals"]["fcfYield"])
        for shares_as_of in (None, "2025-01-02"):  # missing, or before the price series
            with self.subTest(sharesAsOf=shares_as_of):
                record = us_fundamentals(sharesAsOf=shares_as_of)
                row = checked(us_member(), record, {"AAA": rows})
                self.assertIsNone(row["marketCap"])
                self.assertIn("splits_unknown", row["issues"])

    def test_window_ending_before_retrieval_leaves_splits_unknown(self):
        """D7': a split after the price window's through date was never read, so a
        window ending before the retrieval date withholds the US market cap."""
        rows = price_rows()
        known = 10.0 * self.CLOSE

        def window(through):
            return {"from": "2025-09-26", "through": through}

        cases = {
            "rolled over": ({"AAA": window("2026-11-02")}, None),  # through < retrieval
            "through the retrieval date": ({"AAA": window(RETRIEVED)}, known),
            "past the retrieval date": ({"AAA": window("2026-11-04")}, known),
            "window not given": ({"AAB": window(RETRIEVED)}, None),
            "window without a date": ({"AAA": {"from": "2025-09-26"}}, None),
            "not a window": ({"AAA": RETRIEVED}, None),
        }
        for name, (windows, cap) in cases.items():
            with self.subTest(name):
                row = checked(
                    us_member(), us_fundamentals(), {"AAA": rows}, windows=windows
                )
                self.assertEqual(row["marketCap"], cap)
                if cap is None:
                    self.assertIn("splits_unknown", row["issues"])
                    self.assertIn("market_cap_missing", row["issues"])
                    self.assertIsNone(row["signals"]["fcfYield"])
                    self.assertAlmostEqual(row["signals"]["cashProfitability"], 0.12)
                    self.assertIsNotNone(row["signals"]["momentum12_1"])
                else:
                    self.assertEqual(row["issues"], [])
        row = checked(
            us_member(),
            us_fundamentals(),
            {"AAA": rows},
            windows={"AAA": window("2026-11-02")},
        )
        self.assertEqual(row["inputs"]["windowThrough"], "2026-11-02")
        # Without windows (an older caller) the window is not checked.
        legacy = checked(us_member(), us_fundamentals(), {"AAA": rows})
        self.assertEqual(
            (legacy["marketCap"], legacy["inputs"]["windowThrough"]), (known, None)
        )
        # KR keeps its cap and flags the class whose split events are incomplete.
        prices = {
            "005930.KS": price_rows(),
            "005935.KS": price_rows(scale=600.0 / 399.0),
        }
        windows = {
            "005930.KS": window(RETRIEVED),
            "005935.KS": window("2026-11-02"),
        }
        row = checked(kr_member(), kr_fundamentals(), prices, windows=windows)
        self.assertAlmostEqual(row["marketCap"], 100 * 798.0 + 10 * 600.0)
        self.assertIn("splits_unchecked", row["issues"])
        parts = row["inputs"]["shareClasses"]
        self.assertEqual([p["windowThrough"] for p in parts], [RETRIEVED, "2026-11-02"])
        windows["005935.KS"] = window(RETRIEVED)
        row = checked(kr_member(), kr_fundamentals(), prices, windows=windows)
        self.assertNotIn("splits_unchecked", row["issues"])

    def test_restated_proxy_count_is_withheld_around_its_filing(self):
        rows = price_rows()
        # A diluted weighted-average count dated at its period end is restated for
        # splits made before its filing (ASC 260); a cover count is dated and is not.
        proxy = us_fundamentals(
            sharesBasis="diluted_wavg_proxy", sharesAsOf="2026-09-27"
        )
        between = {"AAA": [split("2026-10-12", 20.0, 1.0)]}
        row = checked(us_member(), proxy, {"AAA": rows}, between)
        self.assertIsNone(row["marketCap"])
        self.assertIn("split_restatement_ambiguous", row["issues"])
        later = {"AAA": [split("2026-11-02", 20.0, 1.0)]}  # after the filing
        row = checked(us_member(), proxy, {"AAA": rows}, later)
        self.assertEqual(row["marketCap"], 10.0 * self.CLOSE * 20)
        cover = us_fundamentals(sharesAsOf="2026-09-27")
        row = checked(us_member(), cover, {"AAA": rows}, between)
        self.assertEqual(row["marketCap"], 10.0 * self.CLOSE * 20)

    def test_kr_market_cap_is_not_split_adjusted(self):
        prices = {
            "005930.KS": price_rows(),
            "005935.KS": price_rows(scale=600.0 / 399.0),
        }
        events = {
            "005930.KS": [
                split("2026-05-04", 50.0, 1.0),
                split("2026-08-03", 0.650391, 1.0),
                split(AS_OF, 2.0, 1.0),
            ],
            "005935.KS": [split("2026-05-04", 50.0, 1.0)],
        }
        row = checked(kr_member(), kr_fundamentals(), prices, events)
        self.assertAlmostEqual(row["marketCap"], 100 * 798.0 + 10 * 600.0)
        for issue in (
            "shares_split_adjusted",
            "nonstandard_split",
            "splits_unknown",
            "splits_unchecked",
            "split_after_as_of",
        ):
            self.assertNotIn(issue, row["issues"])
        legacy = signals(kr_member(), kr_fundamentals(), prices, AS_OF)
        self.assertEqual(legacy["marketCap"], row["marketCap"])
        self.assertIn("splits_unchecked", legacy["issues"])

    def test_kr_split_after_as_of_withholds_the_market_cap(self):
        # Without a capture date T stands in for it: Yahoo restates the T close for a
        # split before retrieval, so the close and the shares no longer share a basis.
        prices = {
            "005930.KS": price_rows(),
            "005935.KS": price_rows(scale=600.0 / 399.0),
        }
        later = [split("2026-11-02", 50.0, 1.0)]
        row = checked(kr_member(), kr_fundamentals(), prices, {"005935.KS": later})
        self.assertIsNone(row["marketCap"])
        self.assertIn("split_after_as_of", row["issues"])
        self.assertEqual(row["inputs"]["shareClasses"][1]["splitsAfterCapture"], later)
        self.assertEqual(row["inputs"]["shareClasses"][0]["splitsAfterCapture"], [])
        self.assertIsNone(row["inputs"]["sharesCapturedOn"])
        proxy = checked(
            kr_member(),
            kr_fundamentals(),
            {"005930.KS": price_rows()},
            {"005930.KS": later},
        )
        self.assertIsNone(proxy["marketCap"])
        self.assertIn("class_price_proxy", proxy["issues"])
        self.assertIn("split_after_as_of", proxy["issues"])

    def test_kr_split_up_to_the_capture_date_keeps_the_market_cap(self):
        """L4: listed shares are captured with the universe after T, so a split with
        ex-date in (T, capture date] is in both the shares and the restated close;
        only one in (capture date, retrieval date] withholds the KR cap."""
        prices = {
            "005930.KS": price_rows(),
            "005935.KS": price_rows(scale=600.0 / 399.0),
        }
        known = 100 * 798.0 + 10 * 600.0
        monday = [split("2026-11-02", 50.0, 1.0)]  # T = Friday 10-30, retrieved 11-03
        tuesday = [split(RETRIEVED, 50.0, 1.0)]
        friday = [split(AS_OF, 50.0, 1.0)]  # the close on T is already post-split
        cases = {
            # name: (captures, preferred-class splits, cap, withheld split)
            "captured on the ex-date": ({"KR": "2026-11-02"}, monday, known, None),
            "captured after it": ({"KR": RETRIEVED}, monday, known, None),
            "split after the capture": ({"KR": "2026-11-02"}, tuesday, None, tuesday),
            "captured on T": ({"KR": AS_OF}, monday, None, monday),
            "after the KR close": (
                {"KR": "2026-11-02T09:00:00+00:00"},  # 18:00 KST
                monday,
                known,
                None,
            ),
            "before the KR close": (
                {"KR": "2026-11-02T05:00:00+00:00"},  # 14:00 KST: the day before
                monday,
                None,
                monday,
            ),
            "split on T, captured after its close": (
                {"KR": "2026-10-30T09:00:00+00:00"},
                friday,
                known,
                None,
            ),
            "split on T, captured before its close": (
                {"KR": "2026-10-30T05:00:00+00:00"},  # the shares may predate it
                friday,
                None,
                friday,
            ),
            "no capture date (T)": ({}, monday, None, monday),
            "unreadable capture date (T)": ({"KR": "soon"}, monday, None, monday),
            "US capture only (T)": ({"US": "2026-11-02"}, monday, None, monday),
        }
        for name, (captures, events, cap, withheld) in cases.items():
            with self.subTest(name):
                row = checked(
                    kr_member(),
                    kr_fundamentals(),
                    prices,
                    {"005935.KS": events},
                    captures=captures,
                )
                parts = row["inputs"]["shareClasses"]
                self.assertEqual(row["marketCap"], cap)
                self.assertEqual(parts[1]["splitsAfterCapture"], withheld or [])
                self.assertEqual(parts[0]["splitsAfterCapture"], [])
                self.assertNotIn("splits_unchecked", row["issues"])
                if cap is None:
                    self.assertIn("split_after_as_of", row["issues"])
                    self.assertIn("market_cap_missing", row["issues"])
                    self.assertIsNone(row["signals"]["fcfYield"])
                else:
                    self.assertEqual(row["issues"], [])
                    self.assertAlmostEqual(row["signals"]["fcfYield"], 700.0 / known)
        row = checked(
            kr_member(),
            kr_fundamentals(),
            prices,
            {"005935.KS": monday},
            captures={"KR": "2026-11-02T05:00:00+00:00"},
        )
        self.assertEqual(row["inputs"]["sharesCapturedOn"], "2026-11-01")
        # N6: a capture after the retrieval date (a universe rebuilt after collection)
        # may count a split the closes do not show yet: the cap is withheld, never
        # kept with a flag, until the member is collected again.
        for events in (monday, None):  # with a split after T, and with none
            with self.subTest(split=bool(events)):
                row = checked(
                    kr_member(),
                    kr_fundamentals(),
                    prices,
                    None if events is None else {"005935.KS": events},
                    captures={"KR": "2026-11-04"},
                )
                self.assertIsNone(row["marketCap"])
                self.assertIn("capture_after_retrieval", row["issues"])
                self.assertIn("market_cap_missing", row["issues"])
                self.assertIsNone(row["signals"]["fcfYield"])
                self.assertNotIn("splits_unchecked", row["issues"])
                self.assertNotIn("split_after_as_of", row["issues"])
                self.assertEqual(
                    (
                        row["inputs"]["sharesCapturedOn"],
                        row["inputs"]["retrievedOn"],
                    ),
                    ("2026-11-04", RETRIEVED),
                )
        # Captured on the retrieval date itself: the closes show every split.
        row = checked(
            kr_member(),
            kr_fundamentals(),
            prices,
            {"005935.KS": []},
            captures={"KR": RETRIEVED},
        )
        self.assertEqual((row["marketCap"], row["issues"]), (known, []))
        # The proxy class is priced, and checked, with the common's close and splits.
        common = {"005930.KS": price_rows()}
        for captured, cap in (("2026-11-02", 110 * 798.0), (AS_OF, None)):
            with self.subTest(proxy=captured):
                row = checked(
                    kr_member(),
                    kr_fundamentals(),
                    common,
                    {"005930.KS": monday},
                    captures={"KR": captured},
                )
                self.assertEqual(row["marketCap"], cap)
                self.assertIn("class_price_proxy", row["issues"])
        # A common count taken from the fundamentals record was not captured with the
        # universe, so T still bounds its splits.
        member = kr_member()
        member["shareClasses"][0].pop("listedShares")
        fallback = dict(prices=prices, captures={"KR": "2026-11-02"})
        row = checked(member, kr_fundamentals(listedShares=100.0), **fallback)
        self.assertEqual(row["marketCap"], known)
        row = checked(
            member,
            kr_fundamentals(listedShares=100.0),
            splits={"005930.KS": monday},
            **fallback,
        )
        self.assertIsNone(row["marketCap"])
        self.assertIn("split_after_as_of", row["issues"])
        # The US cap uses the filed share count: capture dates do not touch it.
        us = {"AAA": price_rows()}
        plain = checked(us_member(), us_fundamentals(), us)
        dated = checked(us_member(), us_fundamentals(), us, captures={"US": AS_OF})
        self.assertEqual(plain, dated)

    def test_capture_date_is_the_last_kr_close_before_the_capture(self):
        cases = {
            "2026-10-30T09:00:00+00:00": "2026-10-30",  # 18:00 KST
            "2026-10-30T06:30:01+00:00": "2026-10-30",  # just after the 15:30 close
            "2026-10-30T06:30:00+00:00": "2026-10-29",  # at the close: not after it
            "2026-10-30T02:00:00+00:00": "2026-10-29",  # 11:00 KST, in the session
            "2026-10-30T22:00:00+00:00": "2026-10-30",  # 07:00 KST on 10-31
            "2026-11-02T16:00:00+09:00": "2026-11-02",
            datetime(2026, 10, 30, 9, tzinfo=timezone.utc): "2026-10-30",
            "2026-10-30T18:00:00": None,  # no UTC offset
            "2026-10-30": None,  # a date is not a capture time
            "soon": None,
            None: None,
        }
        for value, day in cases.items():
            with self.subTest(value=value):
                self.assertEqual(rating.capture_date("KR", value), day)

    def test_capture_dates_read_the_earliest_kr_capture_of_the_universe(self):
        def universe(**kr):
            us = dict(capturedAt=dict(first="2026-11-02T22:00:00+00:00"))
            return dict(markets=dict(US=us, KR=kr), members=[])

        span = dict(first="2026-11-02T09:40:00+00:00", last="2026-11-02T10:05:00+00:00")
        cases = {
            "merged span": (
                universe(capturedAt=dict(span, stamps=12), rankingCapturedAt=span),
                {"KR": "2026-11-02"},
            ),
            "span over midnight KST": (
                universe(
                    capturedAt=dict(
                        first="2026-11-02T14:50:00+00:00",  # 23:50 KST
                        last="2026-11-02T15:20:00+00:00",  # 00:20 KST on 11-03
                    )
                ),
                {"KR": "2026-11-02"},
            ),
            "earliest field": (
                universe(
                    capturedAt=dict(first="2026-11-03T09:00:00+00:00"),
                    rankingRetrievedAt=dict(first="2026-11-02T09:00:00+00:00"),
                ),
                {"KR": "2026-11-02"},
            ),
            "one timestamp": (
                universe(rankingCapturedAt="2026-11-02T09:00:00+00:00"),
                {"KR": "2026-11-02"},
            ),
            "before the close": (
                universe(capturedAt=dict(first="2026-11-02T05:00:00+00:00")),
                {"KR": "2026-11-01"},
            ),
            "no capture time": (universe(capturedAt=dict(first=None)), {}),
            "naive capture time": (
                universe(capturedAt=dict(first="2026-11-02T18:00:00")),
                {},
            ),
            "no KR market": (dict(markets=dict(US={}), members=[]), {}),
            "no markets": (dict(members=[]), {}),
            "no universe": (None, {}),
        }
        for name, (built, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(rating.capture_dates(built), expected)
        # The CLI passes capture_dates(universe) to signals().
        prices = {
            "005930.KS": price_rows(),
            "005935.KS": price_rows(scale=600.0 / 399.0),
        }
        row = signals(
            kr_member(),
            kr_fundamentals(),
            prices,
            AS_OF,
            splits_by_symbol={
                "005930.KS": [],
                "005935.KS": [split("2026-11-02", 50.0, 1.0)],
            },
            retrieved_on=RETRIEVED,
            capture_dates_by_market=rating.capture_dates(
                universe(capturedAt=dict(span, stamps=12))
            ),
        )
        self.assertEqual(row["marketCap"], 100 * 798.0 + 10 * 600.0)
        self.assertEqual(row["inputs"]["sharesCapturedOn"], "2026-11-02")

    def test_nflx_fixture_split_after_the_cover_date(self):
        # Review reproduction: 425M pre-split cover shares x NFLX's restated close at
        # 2025-11-28 gave 4.57e10; the 10-for-1 split of 2025-11-17 restores ~4.57e11.
        manifest = dict(retrievedAt="2026-10-06T04:12:00.875820+00:00")
        blob = (PRICE_FIXTURES / "yahoo-NFLX-2026-10-05.json").read_bytes()
        with mock.patch.object(
            price_data, "fetch", lambda url, key, **kwargs: (blob, manifest)
        ):
            series = price_data.series("NFLX", "2026-10-05")
        self.assertEqual(series["status"], "ok", series["error"])
        as_of = "2025-11-28"
        member = us_member(
            ticker="NFLX",
            priceSymbol="NFLX",
            shareClasses=[dict(ticker="NFLX", priceSymbol="NFLX")],
        )
        record = us_fundamentals(
            shares=4.25e8,
            sharesAsOf="2025-10-17",
            periodEnd="2025-09-30",
            filedAt="2025-10-22",
            filings=[dict(form="10-Q", filedAt="2025-10-22")],
        )
        row = checked(
            member,
            record,
            {"NFLX": series["rows"]},
            {"NFLX": series["splits"]},
            as_of,
            "2026-10-06",  # New York date of the retrieval
        )
        close = rating.close_on(series["rows"], as_of)
        self.assertEqual(close[0], as_of)
        self.assertEqual(row["marketCap"], 4.25e8 * close[1] * 10)
        self.assertTrue(4.0e11 < row["marketCap"] < 5.0e11)
        self.assertIn("shares_split_adjusted", row["issues"])
        # D7': this original was retrieved at 00:12 New York on 10-06 for a window
        # through 10-05, so a split going ex on 10-06 would be missing from it.
        late = checked(
            member,
            record,
            {"NFLX": series["rows"]},
            {"NFLX": series["splits"]},
            as_of,
            "2026-10-06",
            windows={"NFLX": series["window"]},
        )
        self.assertEqual(series["window"]["through"], "2026-10-05")
        self.assertIsNone(late["marketCap"])
        self.assertIn("splits_unknown", late["issues"])
        # Fetched through the retrieval date, the same original settles the splits.
        with mock.patch.object(
            price_data, "fetch", lambda url, key, **kwargs: (blob, manifest)
        ):
            current = price_data.series("NFLX", "2026-10-06")
        self.assertEqual(current["rows"], series["rows"])
        row = checked(
            member,
            record,
            {"NFLX": current["rows"]},
            {"NFLX": current["splits"]},
            as_of,
            "2026-10-06",
            windows={"NFLX": current["window"]},
        )
        self.assertEqual(row["marketCap"], 4.25e8 * close[1] * 10)


class ScoreTests(unittest.TestCase):
    @unittest.skipIf(numpy is None, "numpy cross-check not installed")
    def test_winsorizes_at_market_quantiles(self):
        values = [float(v) for v in range(50)] + [1000.0]
        rows = [
            scored_input(f"U{i}", sector=f"S{i % 3}", fcfYield=v, cashProfitability=v)
            for i, v in enumerate(values)
        ]
        out = by_id(score(rows))
        high, low = numpy.quantile(values, 0.99), numpy.quantile(values, 0.01)
        self.assertAlmostEqual(high, 524.5)
        self.assertAlmostEqual(out["U50"]["winsorized"]["fcfYield"], high)
        self.assertAlmostEqual(out["U0"]["winsorized"]["fcfYield"], low)
        self.assertEqual(out["U25"]["winsorized"]["fcfYield"], 25.0)
        self.assertEqual(out["U50"]["signals"]["fcfYield"], 1000.0)
        clipped = [out[f"U{i}"]["winsorized"]["fcfYield"] for i in range(51)]
        center = sum(clipped) / 51
        scale = numpy.std(clipped)
        sector = [clipped[i] for i in range(51) if i % 3 == 2]
        self.assertAlmostEqual(
            out["U26"]["z"]["fcfYield"], (26.0 - sum(sector) / len(sector)) / scale
        )
        self.assertNotAlmostEqual(sum(sector) / len(sector), center)
        self.assertNotAlmostEqual(out["U26"]["z"]["fcfYield"], 0.0)

    @unittest.skipIf(numpy is None, "numpy cross-check not installed")
    def test_small_sector_falls_back_to_market_mean(self):
        rows = [
            scored_input(f"A{k}", sector="A", fcfYield=float(k), momentum12_1=0.1 * k)
            for k in range(1, 6)
        ] + [
            scored_input(f"B{k}", sector="B", fcfYield=10.0 * k, momentum12_1=0.1)
            for k in range(1, 5)
        ]
        out = by_id(score(rows))
        clipped = {k: r["winsorized"]["fcfYield"] for k, r in out.items()}
        center = sum(clipped.values()) / len(clipped)
        scale = numpy.std(list(clipped.values()))
        a_mean = sum(clipped[f"A{k}"] for k in range(1, 6)) / 5
        self.assertEqual(out["A2"]["zBasis"]["fcfYield"], "sector")
        self.assertAlmostEqual(
            out["A2"]["z"]["fcfYield"], (clipped["A2"] - a_mean) / scale
        )
        self.assertEqual(out["B2"]["zBasis"]["fcfYield"], "market")
        self.assertAlmostEqual(
            out["B2"]["z"]["fcfYield"], (clipped["B2"] - center) / scale
        )
        self.assertIn("sector_fallback", out["B2"]["issues"])
        self.assertNotIn("sector_fallback", out["A2"]["issues"])

    def test_terciles_and_insufficient_and_excluded(self):
        rows = ladder(9) + [
            scored_input("ONE", fcfYield=5.0),
            scored_input("FIN", status="excluded", fcfYield=1e6, cashProfitability=1e6),
        ]
        out = by_id(score(rows))
        labels = [out[f"US{k}"]["label"] for k in range(1, 10)]
        self.assertEqual(labels, [AVOID] * 3 + [WATCH] * 3 + [PREFER] * 3)
        self.assertEqual(
            [out[f"US{k}"]["percentile"] for k in range(1, 10)],
            [float(Fraction(k, 9)) for k in range(1, 10)],
        )
        self.assertEqual(
            {out[f"US{k}"]["labelReason"] for k in range(1, 10)}, {"tercile"}
        )
        self.assertIsNone(out["ONE"]["label"])
        self.assertEqual(out["ONE"]["labelReason"], "insufficient")
        self.assertIsNone(out["ONE"]["composite"])
        self.assertIsNone(out["FIN"]["label"])
        self.assertEqual(out["FIN"]["labelReason"], "excluded")
        self.assertIsNone(out["FIN"]["z"]["fcfYield"])
        without = by_id(score(rows[:-1]))
        for key, row in without.items():
            self.assertEqual(row["z"], out[key]["z"])
            self.assertEqual(row["label"], out[key]["label"])

    def test_hysteresis_keeps_labels_until_the_median(self):
        def labels(previous):
            out = by_id(score(ladder(10), previous))
            return {k: (out[k]["label"], out[k]["labelReason"]) for k in out}

        plain = labels(None)
        self.assertEqual(plain["US5"], (WATCH, "tercile"))
        self.assertEqual(plain["US7"], (PREFER, "tercile"))
        self.assertEqual(plain["US3"], (AVOID, "tercile"))
        kept = labels({"US5": PREFER, "US4": PREFER, "US8": AVOID, "US2": PREFER})
        self.assertEqual(kept["US5"], (PREFER, "hysteresis"))
        self.assertEqual(kept["US4"], (WATCH, "tercile"))
        self.assertEqual(kept["US8"], (PREFER, "tercile"))
        self.assertEqual(kept["US2"], (AVOID, "tercile"))
        avoid = labels([dict(id="US5", label=AVOID), dict(id="US6", label=AVOID)])
        self.assertEqual(avoid["US5"], (AVOID, "hysteresis"))
        self.assertEqual(avoid["US6"], (WATCH, "tercile"))

    def test_ties_share_mean_rank(self):
        rows = ladder(6)
        rows.append(scored_input("TWIN", fcfYield=3.0, cashProfitability=3.0))
        out = by_id(score(rows))
        self.assertEqual(out["TWIN"]["percentile"], out["US3"]["percentile"])
        self.assertEqual(out["US3"]["percentile"], float(Fraction(7, 2) / 7))

    def test_markets_are_scored_separately_and_order_free(self):
        us = ladder(9)
        kr = ladder(9, "KR")
        kr[0]["signals"]["fcfYield"] = -1e9
        together = by_id(score(us + kr))
        alone = by_id(score(copy.deepcopy(us)))
        for key in alone:
            self.assertEqual(together[key]["z"], alone[key]["z"])
            self.assertEqual(together[key]["label"], alone[key]["label"])
        shuffled = us + kr
        random.Random(7).shuffle(shuffled)
        again = by_id(score(shuffled))
        for key, row in together.items():
            for field in ("z", "composite", "percentile", "label"):
                self.assertEqual(again[key][field], row[field])

    def test_rejects_duplicates_and_unknown_markets(self):
        with self.assertRaises(ValueError):
            score(ladder(3) + ladder(1))
        with self.assertRaises(ValueError):
            score([scored_input("X", market="JP")])

    def test_signals_feed_score(self):
        member, record = us_member(), us_fundamentals()
        rows = [signals(member, record, {"AAA": price_rows()}, AS_OF)]
        out = score(rows)
        self.assertEqual(out[0]["labelReason"], "insufficient")
        self.assertIn("fcfYield_z_undefined", out[0]["issues"])


if __name__ == "__main__":
    unittest.main()
