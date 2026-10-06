"""ratings-v1 signals, cross-sectional scores and labels (docs/ratings-v1.md §3-4).

Pure functions: members, fundamentals records, price rows ``[[date, adjclose, close],
...]`` and split events in, rated rows out. Every constant that can move a label lives in
PROTOCOL; its canonical hash is recorded with each registration, so a rule change needs a
new protocol version, never an edit of this one.

Yahoo restates ``close`` for every split up to the retrieval date, while a US share count
is dated (sharesAsOf). The US market cap therefore multiplies the count by the integer
split ratios with ex-date in (sharesAsOf, retrieval date] and is withheld when that
product is unknown, including when the price window ended before the retrieval date
(D7'); see PROTOCOL["marketCap"]. KR listed shares are captured with the universe after
T, so only a split with ex-date in (that capture date, retrieval date] withholds the KR
market cap (``capture_dates``; T stands in when no capture date is given), and so does a
capture later than the retrieval date (capture_after_retrieval, N6).

Price-based signals (market cap, FCF yield, momentum) need the member's own session on
T; a member halted on T gets none of them (no_price_on_as_of), never an earlier close
(D9'). A row keeps its fundamentals record's issues and lag check (D8').
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from fractions import Fraction
import json
import math
from numbers import Real
from zoneinfo import ZoneInfo

from . import fundamentals, prices, sectors, universe
from .common import MARKETS, PROTOCOL_VERSION, protocol_hash

PREFER, WATCH, AVOID = "선호", "관찰", "회피"
LABELS = (PREFER, WATCH, AVOID)
REASONS = ("tercile", "hysteresis", "insufficient", "excluded")
SIGNALS = ("fcfYield", "cashProfitability", "momentum12_1")
MONEY = ("Money", 11, "11")
REGISTRATION_WINDOW_SESSIONS = 5
# L3: calendar days after a period's exit date during which member errors hold its
# freeze back; after them it is frozen with those members unresolved.
FREEZE_GRACE_DAYS = 30
# Regular closes in market-local time (registration.timezones: 16:00 America/New_York,
# 15:30 Asia/Seoul); "after the close of T" means after this instant (D5', D9, D10').
MARKET_CLOSE = {"US": "16:00", "KR": "15:30"}
# D11': SHA-256 of data/ratings/reference/ksic-ff12.json, pinned as a literal like
# sectors.FF12_DEFINITION_SHA256 (never read from the file at import). A registration
# refuses a table that no longer matches; a new table needs ratings-v2.
KSIC_REFERENCE_SHA256 = (
    "4f1bb7c24ade63a458333f125dea2894b732feb8ab3d4b6698749ba9fc1a3095"
)
NO_PRICE = "no_price_on_as_of"  # D9': the member's own series has no session on T
# N6: KR listed shares captured after the closes were retrieved: no market cap.
CAPTURE_AFTER_RETRIEVAL = "capture_after_retrieval"

PROTOCOL = {
    "version": PROTOCOL_VERSION,
    "document": "docs/ratings-v1.md",
    "markets": list(MARKETS),
    "currencies": {"US": "USD", "KR": "KRW"},
    "asOf": "each market's last trading day of the month",
    # D5', D9, D10': each market's regular close in its local time (registration
    # timezones); "after the close of T" means after this instant.
    "marketClose": dict(MARKET_CLOSE),
    "universe": {
        "US": {
            "rule": "S&P 500 constituents in the SSGA SPY daily holdings file, one row "
            "per issuer (CIK); an issuer with several share classes is priced with the "
            "ticker of largest SPY weight",
            "sources": [
                "SSGA SPY holdings xlsx",
                "SEC company_tickers.json",
                "SEC submissions (SIC)",
            ],
        },
        "KR": {
            "rule": "KOSPI common stocks (code ending in 0) without SPACs and REITs: "
            "the candidatePool largest by Naver current market value are the "
            "candidates and the size largest of them by market cap at T's close "
            "(rankingBasis) are the members; a rule, not the official KOSPI 200",
            "size": 200,
            "candidatePool": 260,
            # D5': Naver prices after the 15:30 close are Nextrade after-hours prices,
            # so members are ranked on Yahoo closes of T, never on the Naver price.
            "rankingBasis": "T_close",
            # M3, N1, M1, L2: the candidate pool, the ranking and the only unranked
            # reasons; the error rules are those of the common stock.
            "tCloseMarketCap": "the candidatePool largest commons by Naver market "
            "value at the capture, after the SPAC and REIT name filters, are ranked by "
            "market cap at T's close = sum over the candidate's listed classes of "
            "listedShares (Naver market value / Naver price of the same row at the "
            "capture) x the class's Yahoo close on T, read from a series retrieved "
            "after T's closes settle (moduleRules.prices.settleHour, market-local) "
            "whose window ends at T and which is requested through the build's "
            "Asia/Seoul date (so that sessions after T show; they are never used); a "
            "preferred class without its own close on T (no session on T, every Yahoo "
            "host HTTP 404, or a rejected original) is priced at the common close "
            "(class_price_proxy), but one whose close on T is unsettled, traded "
            "without a published close (D17: close_unpublished) or whose download "
            "failed transiently (moduleRules.prices.transientFailure) makes the KR "
            "part an error (rebuilt); a symbol whose close on T is unpublished or whose "
            "download failed transiently is fetched again up to twice within the build "
            "(at most six re-fetches per build) before that; the size largest ranked "
            "candidates are the members (ties by code); a candidate is left unranked "
            "only for no_close_on_as_of (its common's settled series has no session on "
            "T: a halt; a session traded on T without a published close is not one, "
            "D17), symbol_not_found (every Yahoo host answers HTTP 404 for its "
            "common) or not_listed_on_as_of (every Yahoo host answers the request for "
            "its common, retrieved after T's closes settle, with a chart for that "
            "symbol in KRW without a settled session in the lookback window through T "
            "(sessions after T only or none: listed after T or halted throughout), "
            f"with HTTP {prices.NO_DATA_STATUS} whose chart error description "
            f"starts with {prices.NO_DATA!r} (moduleRules.prices.noData), or with "
            "HTTP 404, provided at least one host answers without sessions); for "
            "the common stock of a candidate a series read before T's "
            "closes settle (close_unsettled), a close on T not published "
            "(close_unpublished), a transient download failure, a symbol "
            "or currency mismatch, an undecodable response or any other HTTP "
            f"{prices.NO_DATA_STATUS}, and for any of its classes a series read before "
            "T's closes settle or no listed shares, never leaves a candidate out: the "
            "KR part is an error and is rebuilt, as it is when fewer than size "
            "candidates are ranked",
            "sources": [
                "Naver Finance KOSPI market-cap API (candidates, listed shares)",
                "Yahoo Finance daily closes (market cap at T's close)",
                "OpenDART corpCode and company.json",
            ],
        },
        "fixedAt": "asOf",
        # D5': the markets are captured apart, each once its facts for T exist; H1:
        # the computability-check universe and smoke builds keep their own stems.
        "parts": "each market is built apart and saved as its part "
        "data/ratings/universe/<T>/<market>.json (T: that market's asOf; a part is "
        "never silently replaced); a merge (registry.merge_universe) writes "
        "data/ratings/universe/<asOf>.json (asOf: the later T) with each market's own "
        "metadata (asOf, builtAt, completedAt, capturedAt, holdingsAsOf, "
        "rankingBasis, rulesHash, part file and sha256) and mergedAt; a market "
        "without a part of T = asOf uses its only part of the month, except in a merge "
        "of exactly the named markets (universe-merge --only), which the unattended "
        "operation always uses; the merged file "
        "is rewritten only when a part changes, and an earlier merge of the month is "
        "removed only when every market it holds has the same T in the new merge; a "
        "part saved whose month cannot be merged is reported as saved, not merged; "
        "the computability-check universe keeps its own stem (its parts in "
        "data/ratings/universe/<asOf>-gate/<market>.json, merged into "
        "<asOf>-gate.json) as smoke builds keep <T>-limit<N>/, so no kind of universe "
        "ever merges, replaces or removes another kind's files; registrations take "
        "the month's universe only",
        # D5': a formal registration refuses a universe that breaks these; a dry run
        # records the violations as issues.
        "timing": {
            "US": "SPY holdingsAsOf equals T_US; SSGA posts T's holdings on the next "
            "US business day, so the US part is captured after that",
            "KR": "rankingBasis T_close, captured after T's close (marketClose KR) and "
            "within the registration window; members are ranked on closes of T, so "
            "the capture time only selects the candidates, and no Naver marketStatus "
            "is required",
            # M2: a part replayed offline from stored originals is never used.
            "builtAt": "each market's part is built online (markets[m].online true) "
            "after the close of T in that market (marketClose); the registry checks "
            "each market on its own metadata and refuses a registered or gated market "
            "whose part was not built online",
            "violations": "refuse a formal registration; recorded as issues in a dry run",
        },
        # D6: a member is excluded only by the financial rules.
        "fetchErrors": "a member whose SEC submissions, company.json, corp code, SIC or "
        "KSIC is unavailable or mismatched stays eligible with issue "
        "universe_fetch_error (scored insufficient); a market where more than "
        "universeFetchErrorMaxShare of the non-financial members have "
        "universe_fetch_error gets status error (retry required); an OpenDART "
        "company.json status other than 000 is that member's universe_fetch_error, "
        "except key or quota statuses (010, 011, 012, 020, 021, 800, 901), which make "
        "the KR market an error",
    },
    "universeFetchErrorMaxShare": 0.05,
    "financialExclusions": {
        "US": {"sic": [[6000, 6799]]},
        "KR": {
            "ksicDivisions": ["64", "65", "66", "68"],
            "keep": ["64992"],
            "holdingName": f"64992 whose registered name contains "
            f"{sectors.FINANCIAL_HOLDING_MARK} is excluded (financial_holding)",
        },
        "treatment": "only these rules exclude; excluded members keep a row with the "
        "reason and no label and stay in the universe counts (the computability "
        "denominator is decisions.computabilityCheck.denominator)",
    },
    "sectors": {
        "scheme": "Fama-French 12",
        # R12, L5, N4
        "US": "SIC via Ken French's official definition file, pinned by "
        "moduleRules.sectorReferences.ff12DefinitionSha256; when the file cannot be "
        "fetched (R12: an outage; offline: the latest stored original cannot be read) "
        "or the file read (downloaded; offline the latest stored) does not parse to "
        "the pinned definition (L5: a changed or unreadable file), a stored original "
        "whose parsed definition hashes to the pin is used and the outage "
        "(ff12_stored_original) or the changed file "
        "(ff12_definition_changed_pinned_used) is recorded: the original kept under "
        "its own pointer, else the latest stored, else any stored Siccodes12 original "
        "whose content matches its name; without one an outage or an unreadable file "
        "makes the US part an error and a changed definition stands "
        "(ff12_definition_changed), which registrations refuse",
        "KR": "KSIC via data/ratings/reference/ksic-ff12.json, pinned by "
        "moduleRules.sectorReferences.ksicReferenceSha256",
        "mustBeEmpty": "Money",
    },
    "pointInTime": {
        "filings": "filed strictly before asOf (US companyfacts filed date, or the "
        "SEC submissions filingDate of a report or amendment read from its own XBRL "
        "instance; KR receipt-number date); a record without filedAt is not used",
        "prices": "sessions on or before asOf, the last of them the member's own "
        "session on asOf (marketCap.priceOnAsOf)",
        # D8, D8'
        "fundamentalsSource": "US: SEC companyfacts first; a newer periodic report "
        "(10-K/10-Q) filed before asOf that companyfacts lacks, with every 10-K/A or "
        "10-Q/A for its period filed before asOf, is read from its own XBRL instance "
        "in the EDGAR archives, the latest filing winning per period "
        "(moduleRules.fundamentals.us.filingXbrl, issue filing_xbrl_supplement); if "
        "that read fails the member is insufficient (companyfacts_lag), while an "
        "online retrieval failure makes the record an error that is collected again. "
        "KR: OpenDART fnlttSinglAcntAll",
        "freshness": "a record whose statement API lags the latest periodic report "
        "filed before asOf (US: after the filing XBRL supplement) is insufficient "
        "(moduleRules.fundamentals.lag); each row carries its record's issues "
        "(companyfacts_lag, dart_api_lag, lag_check_unavailable, "
        "filing_xbrl_supplement, ...) and the record's lagCheck in its inputs",
    },
    "signals": {
        "fcfYield": {
            "definition": "(cfoTTM - capexTTM) / marketCap",
            "capex": "acquisition of property, plant and equipment as a non-negative "
            "payment; negative or missing gives no value",
            "marketCap": "missing or non-positive gives no value",
            "currency": "filing currency must equal the market currency",
        },
        "cashProfitability": {
            "definition": "cfoTTM / assets",
            "assets": "latest total assets, positive",
        },
        "momentum12_1": {
            "definition": "adjclose[T-21] / adjclose[T-252] - 1 over the member's own "
            "sessions on or before T, the last of which is T itself (no_price_on_as_of "
            "otherwise)",
            "skipSessions": 21,
            "lookbackSessions": 252,
        },
        "trailingTwelveMonths": "annual value, else current cumulative + prior annual "
        "- prior-year same-period cumulative",
        "direction": "higher is better for every signal",
    },
    "marketCap": {
        "US": "shares (cover-page shares, else the latest quarterly diluted "
        "weighted-average shares as a flagged proxy) x Yahoo close on T x the product "
        "of numerator/denominator of every split with ex-date in (sharesAsOf, "
        "retrievedOn]; Yahoo restates closes for splits up to the retrieval date, so "
        "the split events come from a series fetched through that date",
        "KR": "sum over listed share classes of listedShares x that class's Yahoo close "
        "on T, without split adjustment; listedShares = Naver market value / Naver "
        "price at the universe capture; a class without its own close on T uses the "
        "common close on T (class_price_proxy), except a class whose download failed "
        "transiently or that traded on T without a published close: the member is "
        "collected again (D17); a registration that records such a member as a "
        "failure (--allow-errors, after the retries) prices that class at the common "
        "close too (class_price_proxy)",
        "splits": {
            "standard": "numerator and denominator are positive integers; a split in "
            "the product that is not (a spin-off or rights issue shown as a split, e.g. "
            "0.650391:1) withholds the market cap (nonstandard_split)",
            # D7, D7'
            "unknown": "US: no split events for the priced symbol, no retrieval date, "
            "no sharesAsOf, an undated event, two different events on one date, a "
            "series starting after sharesAsOf or holding sessions after the retrieval "
            "date, or a price window whose through date is earlier than the retrieval "
            "date (later splits were not read; when windows are given, a symbol "
            "without one counts as such) withholds the market cap (splits_unknown); a "
            "repeated identical event counts once",
            "restated": "US: a count other than the cover-page count is restated for "
            "splits up to its filing, so a split with ex-date in (sharesAsOf, filedAt] "
            "withholds the market cap (split_restatement_ambiguous)",
            # L4
            "KRAfterAsOf": "KR: listedShares are captured with the universe after T "
            "and Yahoo restates the close on T for every split up to the retrieval "
            "date, so a split with ex-date on or before sharesCapturedOn is in both; a "
            "split with ex-date in (sharesCapturedOn, retrievedOn] on the class whose "
            "close is used withholds the market cap (split_after_as_of); "
            "sharesCapturedOn is the KR-local date of the earliest capture time in the "
            "universe's markets.KR (capturedAt, rankingCapturedAt, rankingRetrievedAt), "
            "or the day before when that time is not after the KR close (marketClose) "
            "of its date; T stands in for it without a capture date and for a count "
            "that did not come from the universe",
            "unchecked": "a call without split events and retrieval date keeps the "
            "unadjusted cap and is flagged splits_unchecked; so is a KR class whose "
            "split events are unknown (none given, or a window ending before the "
            "retrieval date)",
            # N6
            "KRCaptureAfterRetrieval": "KR: listedShares captured after the closes "
            "were retrieved (sharesCapturedOn later than retrievedOn, e.g. a universe "
            "rebuilt after its members were collected) may count a split that the "
            "close does not show, so the market cap is withheld "
            "(capture_after_retrieval), never kept with a flag; an online collect "
            "gathers such a member again, which clears it, and until then its "
            "checkpoint is stale (registration.inputs): no registration or coverage "
            "gate uses it",
            "adjusted": "a US product other than 1 is flagged shares_split_adjusted",
        },
        # D9'
        "priceOnAsOf": "a member whose own price series (priceSymbol) has no session "
        "on T gets no price-based signal: no market cap, no FCF yield and no momentum "
        "(no_price_on_as_of); an earlier close is never used, in dry runs and "
        "registrations alike. A KR member was ranked at its common's close on T, so a "
        "KR collection without that close (or with it unpublished, D17) is a "
        "collection error, collected again; a registration that records it as a "
        "failure gives it no price-based signal (no_price_on_as_of)",
    },
    "winsor": {
        "lower": 0.01,
        "upper": 0.99,
        "quantile": "linear interpolation (Hyndman-Fan type 7)",
        "scope": "per market and signal over eligible members with a value",
    },
    "zScore": {
        "center": "sector mean of winsorized values",
        "scale": "market population standard deviation of winsorized values",
        "fallback": "market mean when the sector has fewer than minSectorSize values",
    },
    "minSectorSize": 5,
    "minSignals": 2,
    "composite": "mean of available z; fewer than minSignals gives no label",
    "percentile": "mean rank / n of the composite within the market, ascending, "
    "in (0, 1]",
    "terciles": {"avoidAtOrBelow": "1/3", "preferAbove": "2/3"},
    "hysteresis": 0.5,
    # D16: the previous label is read per market.
    "hysteresisRule": "a previous 선호 stays 선호 at percentile >= hysteresis; a "
    "previous 회피 stays 회피 at percentile <= hysteresis; a member's previous label "
    "comes from the latest registration that contains its market",
    "labels": {"prefer": PREFER, "watch": WATCH, "avoid": AVOID},
    "costs": {
        "US": {"buy": 0.0005, "sell": 0.0005},
        "KR": {"buy": 0.0005, "sell": 0.0025},
    },
    "benchmarks": {"US": "^SP500TR", "KR": "069500.KS"},
    "registrationWindowSessions": REGISTRATION_WINDOW_SESSIONS,
    "registration": {
        # Each market's zone; the top-level marketClose is local time in it.
        "timezones": {"US": "America/New_York", "KR": "Asia/Seoul"},
        "rule": "market-local registration date strictly after asOf; a file is never "
        "overwritten; dry runs stay out of the ledger and the evaluation",
        # D3, D15
        "window": "a formal registration of month M is made within "
        "registrationWindowSessions sessions after T in each registered market: its "
        "market-local date is after T and not after the registrationWindowSessions-th "
        "session after T, sessions counted on the market's sessionCalendar series; "
        "that date is the registrationDay recorded per market (the local date of "
        "registeredAt), on which the registry and the evaluator both judge the window",
        "sessionCalendar": {"US": "^SP500TR", "KR": "069500.KS"},
        "order": "months strictly increase: a month at or before the latest registered "
        "month is refused, and a month whose window has passed is never registered",
        # D8', D9, D9', D11'
        "inputs": "every checkpoint used by a formal registration was collected online "
        "after the close of T in its market (marketClose) under the current "
        "protocolHash and code digest (sha256 over codeFiles) and, in KR, its own "
        "series was retrieved (KR date) no earlier than sharesCapturedOn of the "
        "universe (else capture_after_retrieval); any other checkpoint is stale and "
        "is collected again (--refresh forces it); stale checkpoints back dry runs "
        "only, and the registry refuses formal rows whose collection.stale is not "
        "empty; a registration records the sha256 of each checkpoint file",
        # D11, D11'
        "integrity": "a registration records the sha256 of every codeFiles file "
        "(codeFiles) and is refused unless the universe FF12 definition hash, the KSIC "
        "reference sha256 and the module rules equal moduleRules, "
        "data/ratings/reference/ksic-ff12.json matches the pinned "
        "ksicReferenceSha256, and no eligible member has sector Money",
        # D11'
        "freeze": "a formal registration is refused while any ledger event "
        "(rating-registration or coverage-gate) carries a protocolHash other than this "
        "protocol's: changing any rule needs ratings-v2",
    },
    # D11: repository-relative glob patterns of the code whose sha256 each registration
    # records (the hashes cannot live here: this file is one of them).
    "codeFiles": [
        "ratings/*.py",
        "scripts/ratings.py",
        "equitylab/data.py",
        "equitylab/ledger.py",
        "equitylab/dart.py",
        "equitylab/forward_study.py",
    ],
    "evaluation": {
        "calendar": "dates traded by at least half of the market's price series that "
        "had started by then",
        # D2 (registration date per D12)
        "entry": "close of the first market session after the market-local date of "
        "the registration (the later of registeredAt and the ledger recordedAt)",
        # D2, D12, M4
        "missingEntry": "a member without a close on the entry session of a series "
        "that covers that session is excluded from that period (no_entry_price) and "
        "kept in the counts; there is no late entry; a held member without a price "
        "series, or whose series starts after the entry session (series_not_covering), "
        "is an error; a member whose series ends before the entry session is excluded "
        "from that period (series_ends_before_entry) and counted in the run's errors "
        "(exit 1) so that the operator checks it; none of these is ever no_entry_price",
        # D4, D15
        "exit": "the next registration's entry session when that registration was "
        "made inside its window (judged on its registrationDay); when the next month "
        "was missed, the close of the missedRegistrationExitSession-th session after "
        "the next month's T (forced exit, flagged missed_next_registration); an open "
        "period is valued on the last session on or before the evaluation date; a "
        "member without a close on its exit session uses its last close before it "
        "(last_price); completed periods are frozen (freeze)",
        "missedRegistrationExitSession": REGISTRATION_WINDOW_SESSIONS + 1,
        # D12', L3, N2, N5
        "freeze": "the per-member results of a completed period (entry and exit dates "
        "and closes, returns, sector, label, series source sha256) and each "
        "portfolio's turnover and costs (bought, sold, turnover, cost, liquidated) "
        "are frozen in data/ratings/periods/<market>/<YYYY-MM>.json by the first "
        "official evaluation after it completes whose evaluation date is not after "
        "that market's local date; member errors hold the freeze back while the "
        "evaluation date is at most freezeGraceDays calendar days after the period's "
        "exit date, and the first official evaluation after that freezes the period "
        "with those members recorded as unresolved (excluded from the returns, kept "
        "in the counts) and the period flagged frozen_with_unresolved; a period held "
        "back never blocks the freezing of later periods; later evaluations keep the "
        "frozen values, net metrics included (the frozen costs, never costs "
        "recomputed from an earlier period's drifted weights), and flag "
        "revised_after_freeze where fresh data differ by more than 1e-9",
        "freezeGraceDays": FREEZE_GRACE_DAYS,
        "series": "kept series (data/ratings/series) are merged, never shrunk, and "
        "written only by official runs; a kept series is re-parsed from its "
        "hash-verified original (rows and splits), never read from its saved rows; "
        "it stands in for a failed download only when the failure is not transient "
        "(moduleRules.prices.transientFailure: the source is gone or answers "
        "otherwise), never for a series whose latest session traded without a "
        "published close (D17)",
        # D12', L3, N2
        "official": "official output needs the full ledger without dry runs, one "
        "protocolHash across the registrations (mixed hashes are an error), an "
        "online run with freshly fetched benchmark and session-calendar series and an "
        "evaluation date not after today (the later of the markets' local dates); it "
        "records that it was online and the date it is valued through, and only "
        "official output writes kept series and frozen periods",
        "return": "adjusted close ratio",
        "primary": "선호 equal-weight return - mean same-sector equal-weight return of "
        "eligible members, minus costs",
        "costs": "buy rate x weight bought + sell rate x weight sold when rebalancing "
        "from the previous portfolio's drifted weights; the first period buys all",
        "secondary": [
            "회피 excess",
            "선호 - 회피 spread",
            "Spearman IC of composite and return",
            "hit rate",
        ],
        "baselines": [
            "single-signal top tercile by z",
            "equal-weight eligible members",
            "benchmark index",
        ],
        "baselineUse": "reported only, never used for decisions",
    },
    "decisions": {  # docs/ratings-v1.md §7, fixed before any result
        "computabilityCheck": {
            "date": "2026-10-20",
            # D10': both markets are checked at this T, the last session before date.
            "asOf": "2026-10-19",
            "rule": "eligible members with at least minSignals signals / eligible "
            "members; no company-specific exception codes",
            "thresholds": {"US": 0.90, "KR": 0.80},
            "belowUS": "ratings are not published",
            "belowKR": "Korea leaves the v1 ratings; deep reports only",
            # D6
            "denominator": "every member not excluded by a financial rule; a "
            "universe_fetch_error member counts as not computable",
            # D10, D10', L1
            "gateEvent": "coverage appends one ledger event of type coverage-gate per "
            "market with asOf, checkDate, rate, threshold, verdict, the computable and "
            "nonFinancial counts, the collection counts, the universe sha256, the "
            "merged universe file and its mergedAt, every universe part file with its "
            "sha256, the checkpoint file the counts came from with its sha256 and byte "
            "length (the append-only file's first bytes keep that hash) and "
            "protocolHash; record_gate computes the verdict from the rate and "
            "thresholds",
            # D10', H1, L1, N7, M2, L3
            "gateRecording": "only on or after date in the market's local date, for "
            "asOf, from the merged computability-check universe (the market's part "
            "built online and saved in <asOf>-gate/ with its sha256; never the month's "
            "universe, a smoke build or a part built offline) that passes the timing, "
            "membership and integrity checks of a formal registration; when the gate "
            "is recorded every part file the merge recorded with a sha256 is hashed "
            "again and must still have that sha256, and the merged file is read again "
            "and must still hold the universe being recorded (its canonical sha256, "
            "the event's universeSha256; the merge records no hash of the merged file "
            "itself); and only when every eligible member's checkpoint is online, "
            "collected after the close, current under this protocol and code (in KR "
            "also not capture_after_retrieval) and not in error; a collection error, "
            "gap or stale checkpoint makes the verdict incomplete, and then, as on any "
            "refused check, nothing is recorded (retry)",
            "gateRule": "a formal registration of a market needs a passing "
            "coverage-gate event for that market, carrying this protocolHash, recorded "
            "before the market's first registration; a failed gate leaves KR out of the "
            "registrations and blocks US registration",
        },
        "review": {
            "date": "2028-11-30",
            "rule": "a market whose 24-month mean primary metric <= 0 or mean IC <= 0 "
            "has its labels downgraded to '관찰 신호'; applied without a review",
        },
    },
    # Rules kept next to the code that applies them; copied (not aliased) so that the
    # hash covers them and a later edit of those modules changes protocolHash.
    "moduleRules": json.loads(
        json.dumps(
            {
                "universe": universe.RULES,
                "sectorReferences": {
                    "ff12DefinitionSha256": sectors.FF12_DEFINITION_SHA256,
                    "ksicReferenceSha256": KSIC_REFERENCE_SHA256,
                },
                "fundamentals": fundamentals.RULES,
                "prices": {
                    "provider": prices.PROVIDER,
                    "lookbackDays": prices.LOOKBACK_DAYS,
                    "settleHour": prices.SETTLE_HOUR,
                    "rows": "[date, adjclose, close], exchange-local dates",
                    "splits": "{date, numerator, denominator} for every split with "
                    "an exchange-local ex-date in the requested window",
                    # M1: Yahoo's answer to a request without any session.
                    "noData": f"an HTTP {prices.NO_DATA_STATUS} answer whose "
                    f"chart.error.description starts with {prices.NO_DATA!r} is kept "
                    f"as an original (httpStatus {prices.NO_DATA_STATUS}) and read as "
                    "a window without settled sessions (NoSessions); any other HTTP "
                    f"{prices.NO_DATA_STATUS} is a rejected original",
                    "requestThrough": "a series may be requested through a later "
                    "date than its window (sessions after the window then show as "
                    "'next session' and are dropped); its window, rows, splits and "
                    "stored key stay those of the window",
                    # D17: Yahoo nulled KRX closes of the latest session around
                    # midnight KST (2026-10-07) while keeping their volume.
                    "unpublishedClose": "a null-close session with traded volume "
                    "(volume > 0) is a close the provider has not published (yet): "
                    "it is dropped from the rows like any null-close session and "
                    "listed in unpublishedSessions (an original with such sessions "
                    "and no row is rejected: UnpublishedClose). A caller needing that "
                    "day's close retries and never reads a halt: a collection with T "
                    "unpublished in any of the member's series is an error (collected "
                    "again; a registration that records it as a failure after the "
                    "retries gives it no price-based signal, or prices such a class at "
                    "the common close), a KR ranking with T unpublished is a market "
                    "error "
                    "(close_unpublished, rebuild), and an evaluation series whose "
                    "latest session is unpublished is left out of that run (an "
                    "error), never replaced by a kept series. A halt is no session on "
                    "T, or a null close without volume",
                    "transientFailure": "a failed series some host failed to "
                    "download (timeout, connection error, an HTTP status other than "
                    "404) or rejected as UnpublishedClose; a later download may fix "
                    "it, so collection retries it for every class (no "
                    "class_price_proxy until a registration records the member as a "
                    "failure), the KR ranking rebuilds and evaluation never replaces "
                    "it by a kept series",
                },
            }
        )
    ),
}
PROTOCOL_HASH = protocol_hash(PROTOCOL)


def iso_day(value) -> str:
    """'YYYY-MM-DD' from a date, datetime or ISO text."""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)[:10]).isoformat()


def number(value) -> float | None:
    """A finite float, else None (bools and text are not numbers here)."""
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def positive(value) -> float | None:
    value = number(value)
    return value if value is not None and value > 0 else None


def rows_through(rows, day: str) -> list:
    """Price rows dated on or before ``day`` (rows ascend by ISO date)."""
    return rows[: bisect_right(rows, day, key=lambda row: row[0])]


def session_on(rows, day: str):
    """The row dated ``day`` (rows ascend by ISO date), else None."""
    rows = rows or []
    i = bisect_left(rows, day, key=lambda row: row[0])
    return rows[i] if i < len(rows) and rows[i][0] == day else None


def close_on(rows, day: str, column: int = 2) -> tuple | None:
    """(day, value) when the row dated ``day`` has a positive value there, else None.

    D9': price-based signals use the session on T itself, never an earlier close.
    """
    row = session_on(rows, day)
    value = None if row is None else positive(row[column])
    return None if value is None else (day, value)


def momentum_12_1(rows, as_of: str) -> tuple:
    """(value, issue, [start date, end date]) on the member's own sessions.

    The last of those sessions must be T itself: a member halted on T has no momentum
    (no_price_on_as_of), never one measured from earlier sessions (D9').
    """
    spec = PROTOCOL["signals"]["momentum12_1"]
    if not rows:
        return None, "price_series_missing", None
    past = rows_through(rows, as_of)
    if not past or past[-1][0] != as_of:
        return None, NO_PRICE, None
    last = len(past) - 1
    if last < spec["lookbackSessions"]:
        return None, "momentum_history_short", None
    start = past[last - spec["lookbackSessions"]]
    end = past[last - spec["skipSessions"]]
    if positive(start[1]) is None or positive(end[1]) is None:
        return None, "momentum_price_missing", [start[0], end[0]]
    return end[1] / start[1] - 1, None, [start[0], end[0]]


def ranks(values: list) -> list:
    """1-based ascending ranks as exact fractions; ties share their mean rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [None] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = Fraction(i + j + 2, 2)
        i = j + 1
    return out


def percentiles(values: dict) -> dict:
    """{key: mean rank / n} in (0, 1] as exact fractions."""
    keys = list(values)
    return {
        key: rank / len(keys)
        for key, rank in zip(keys, ranks([values[k] for k in keys]))
    }


def quantile(ordered: list, q: float) -> float:
    """Linear-interpolation quantile of sorted values (numpy's default method)."""
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _day_or_none(value) -> str | None:
    try:
        return None if value is None else iso_day(value)
    except (TypeError, ValueError):
        return None


def split_ratio(numerator, denominator) -> Fraction | None:
    """Share-count multiplier of a split, or None unless both terms are positive integers.

    Yahoo shows spin-offs and rights issues as fractional 'splits' (0.650391:1); those
    are not share-count changes this rule can apply.
    """
    n, d = number(numerator), number(denominator)
    if n is None or d is None or n <= 0 or d <= 0:
        return None
    if not (n.is_integer() and d.is_integer()):
        return None
    return Fraction(int(n), int(d))


def _window_through(windows_by_symbol, symbol) -> str | None:
    """The through date of ``symbol``'s price window, or None when not given."""
    window = (windows_by_symbol or {}).get(symbol)
    return _day_or_none(window.get("through")) if isinstance(window, dict) else None


# L4: the universe's markets[m] fields holding the capture of a market's listed shares
# (a {first, last, ...} span or one timestamp); the earliest of them is used.
CAPTURE_FIELDS = ("capturedAt", "rankingCapturedAt", "rankingRetrievedAt")


def _moment(value) -> datetime | None:
    """A timestamp with a UTC offset (datetime or ISO text), else None."""
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    return value if value.utcoffset() is not None else None


def capture_date(market: str, captured_at) -> str | None:
    """L4: the market-local date whose listed shares a capture at ``captured_at`` (a
    timestamp with a UTC offset) shows, else None.

    It is the capture's local date when taken after that date's close (marketClose,
    registration.timezones), otherwise the day before: a capture before the close may
    predate a split that takes effect that day.
    """
    moment = _moment(captured_at)
    if moment is None:
        return None
    zone = ZoneInfo(PROTOCOL["registration"]["timezones"][market])
    local = moment.astimezone(zone)
    day = local.date()
    if local.time() <= time.fromisoformat(PROTOCOL["marketClose"][market]):
        day -= timedelta(days=1)
    return day.isoformat()


def capture_dates(universe: dict) -> dict:
    """L4: ``{"KR": 'YYYY-MM-DD'}``, the sharesCapturedOn of the universe's KR listed
    shares, for ``signals(..., capture_dates_by_market=...)``.

    The earliest time in ``universe["markets"]["KR"]``'s CAPTURE_FIELDS goes through
    capture_date(). A universe without a usable KR capture time gives {} (T then
    stands in). US market caps use the filed share count, never the capture.
    """
    info = ((universe or {}).get("markets") or {}).get("KR")
    if not isinstance(info, dict):
        return {}
    stamps = []
    for field in CAPTURE_FIELDS:
        value = info.get(field)
        values = list(value.values()) if isinstance(value, dict) else [value]
        stamps += [m for m in map(_moment, values) if m is not None]
    return {"KR": capture_date("KR", min(stamps))} if stamps else {}


def _capture_day(market: str, value) -> str | None:
    """sharesCapturedOn from a 'YYYY-MM-DD' date (used as given) or a capture timestamp
    with a UTC offset (capture_date); None otherwise."""
    if isinstance(value, datetime) or (isinstance(value, str) and len(value) > 10):
        return capture_date(market, value)
    return _day_or_none(value) if isinstance(value, (str, date)) else None


def _split_events(
    splits_by_symbol, symbol, rows, retrieved_on, windows_by_symbol=None
) -> list | None:
    """[(ex-date, numerator, denominator)] of ``symbol`` by date, or None when unknown.

    Unknown: no events or no retrieval date supplied, an event without a date, two
    different events on one date, price rows after the retrieval date (so the events
    were not read through that date) or, when windows are supplied, a window missing or
    ending before the retrieval date (D7': a split after the window's end may have
    restated the closes unseen). A repeated identical event counts once.
    """
    if splits_by_symbol is None or retrieved_on is None:
        return None
    events = splits_by_symbol.get(symbol)
    if not isinstance(events, (list, tuple)):
        return None
    if rows and rows[-1][0] > retrieved_on:
        return None
    if windows_by_symbol is not None:
        through = _window_through(windows_by_symbol, symbol)
        if through is None or through < retrieved_on:
            return None
    out = []
    for event in events:
        day = _day_or_none(event.get("date")) if isinstance(event, dict) else None
        if day is None:
            return None
        event = (day, event.get("numerator"), event.get("denominator"))
        if event in out:
            continue
        if any(other[0] == day for other in out):
            return None
        out.append(event)
    return sorted(out, key=lambda event: event[0])


def _shown(event: tuple) -> dict:
    """A split event as recorded in inputs (non-finite or non-numeric terms as None)."""
    day, numerator, denominator = event
    return dict(date=day, numerator=number(numerator), denominator=number(denominator))


def _us_split_factor(record: dict, rows: list, events, retrieved_on) -> tuple:
    """(product or None, splits in (sharesAsOf, retrievedOn], issues)."""
    after = _day_or_none(record.get("sharesAsOf"))
    if events is None or after is None or after < rows[0][0]:
        return None, [], ["splits_unknown"]
    applied = [event for event in events if after < event[0] <= retrieved_on]
    shown = [_shown(event) for event in applied]
    ratios = [split_ratio(n, m) for _, n, m in applied]
    issues = []
    if None in ratios:
        issues.append("nonstandard_split")
    filed = _day_or_none(record.get("filedAt"))
    if record.get("sharesBasis") != "cover" and any(
        filed is None or event[0] <= filed for event in applied
    ):
        issues.append("split_restatement_ambiguous")
    if issues:
        return None, shown, issues
    return math.prod(ratios, start=Fraction(1)), shown, []


def market_cap(
    member: dict,
    fundamentals: dict,
    prices: dict,
    as_of: str,
    *,
    splits_by_symbol=None,
    retrieved_on=None,
    windows_by_symbol=None,
    capture_dates_by_market=None,
) -> tuple:
    """(value or None, detail, issues) at T from Yahoo closes on T and split events.

    ``splits_by_symbol`` maps a priceSymbol to its split events ``[{date, numerator,
    denominator}]`` and ``retrieved_on`` is the date the closes were retrieved (Yahoo
    restates them for every split up to it). Without both, the cap is not checked
    against splits. ``windows_by_symbol`` maps a priceSymbol to its series window
    ``{from, through}``; no split after ``through`` was read, so a window ending before
    ``retrieved_on`` leaves the splits unknown (D7'). A member without its own close on
    T has no cap (D9': no_price_on_as_of); no earlier close is used.

    ``capture_dates_by_market`` (``capture_dates(universe)``) gives the KR
    sharesCapturedOn: only a split with ex-date in (sharesCapturedOn, retrieved_on]
    withholds a KR cap (split_after_as_of, L4); without it T stands in. Listed shares
    captured after ``retrieved_on`` withhold it too (capture_after_retrieval, N6).
    """
    issues = []
    unchecked = splits_by_symbol is None and retrieved_on is None
    retrieved_on = None if retrieved_on is None else iso_day(retrieved_on)
    symbol = member.get("priceSymbol")
    common = close_on(prices.get(symbol), as_of)
    if member["market"] == "US":
        shares = number(fundamentals.get("shares"))
        detail = dict(
            shares=shares,
            sharesBasis=fundamentals.get("sharesBasis"),
            sharesAsOf=fundamentals.get("sharesAsOf"),
            close=common[1] if common else None,
            closeDate=common[0] if common else None,
            retrievedOn=retrieved_on,
            windowThrough=_window_through(windows_by_symbol, symbol),
            splitFactor=None,
            splitsSinceShares=[],
        )
        if fundamentals.get("sharesBasis") not in (None, "cover"):
            issues.append("shares_proxy")
        if len(member.get("shareClasses") or []) > 1:
            issues.append("multi_class_single_price")
        missing = ["shares_missing"] if shares is None else []
        if common is None:
            missing.append(NO_PRICE)
        if missing:
            return None, detail, issues + missing
        if unchecked:
            return shares * common[1], detail, issues + ["splits_unchecked"]
        rows = prices[symbol]
        events = _split_events(
            splits_by_symbol, symbol, rows, retrieved_on, windows_by_symbol
        )
        factor, since, problems = _us_split_factor(
            fundamentals, rows, events, retrieved_on
        )
        detail.update(
            splitFactor=None if factor is None else float(factor),
            splitsSinceShares=since,
        )
        if problems:
            return None, detail, issues + problems
        if factor != 1:
            issues.append("shares_split_adjusted")
        return (
            shares * common[1] * factor.numerator / factor.denominator,
            detail,
            issues,
        )
    classes = member.get("shareClasses") or [dict(priceSymbol=symbol)]
    parts, total = [], 0.0
    if common is None:  # D9': halted on T, whatever its other classes did
        issues.append(NO_PRICE)
        total = None
    # L4: splits up to the capture are in both the listed shares and the restated close.
    captured = _capture_day("KR", (capture_dates_by_market or {}).get("KR"))
    for share_class in classes:
        class_symbol = share_class.get("priceSymbol")
        shares = number(share_class.get("listedShares"))
        since, captured_count = captured or as_of, True  # the universe's count
        if shares is None and class_symbol == symbol:
            shares = number(fundamentals.get("listedShares"))
            since, captured_count = as_of, False  # not the universe's: no capture date
        quote = close_on(prices.get(class_symbol), as_of)
        proxy = quote is None and common is not None and class_symbol != symbol
        if proxy:  # the common close on T, never the class's own earlier close
            quote = common
            issues.append("class_price_proxy")
        later = []  # splits after the capture restate the close but not the shares
        priced = symbol if proxy else class_symbol
        # N6: shares captured after the closes were retrieved may count a split the
        # close does not show yet: no cap until the member is collected again.
        late = (
            captured_count
            and None not in (captured, retrieved_on)
            and retrieved_on < captured
        )
        if quote is not None and not late:
            events = _split_events(
                splits_by_symbol,
                priced,
                prices.get(priced),
                retrieved_on,
                windows_by_symbol,
            )
            if events is None or retrieved_on < since:  # later splits were not read
                issues.append("splits_unchecked")
            else:
                later = [
                    _shown(event)
                    for event in events
                    if since < event[0] <= retrieved_on
                ]
        parts.append(
            dict(
                priceSymbol=class_symbol,
                listedShares=shares,
                close=quote[1] if quote else None,
                closeDate=quote[0] if quote else None,
                priceProxy=proxy,
                windowThrough=_window_through(windows_by_symbol, priced),
                splitsAfterCapture=later,
            )
        )
        if shares is None:
            issues.append("listed_shares_missing")
            total = None
        elif quote is None:  # the member is halted on T (no_price_on_as_of above)
            total = None
        elif late:
            issues.append(CAPTURE_AFTER_RETRIEVAL)
            total = None
        elif later:
            issues.append("split_after_as_of")
            total = None
        elif total is not None:
            total += shares * quote[1]
    detail = dict(
        shareClasses=parts, retrievedOn=retrieved_on, sharesCapturedOn=captured
    )
    return total, detail, list(dict.fromkeys(issues))


def _usable_fundamentals(member_id, record, as_of: str, issues: list) -> dict:
    """The record if it may be used at T, else {} with the reason recorded."""
    if not record:
        issues.append("fundamentals_missing")
        return {}
    if record.get("id") != member_id:
        issues.append("fundamentals_id_mismatch")
        return {}
    if record.get("status") == "error":
        issues.append("fundamentals_error")
        return {}
    if record.get("status") not in ("ok", "insufficient"):
        issues.append("fundamentals_status_unknown")
        return {}
    if not record.get("filedAt"):
        issues.append("filed_at_missing")
        return {}
    filed = [record["filedAt"]] + [
        f["filedAt"]
        for f in record.get("filings") or []
        if isinstance(f, dict) and f.get("filedAt")
    ]
    if any(iso_day(day) >= as_of for day in filed):
        issues.append("filed_on_or_after_as_of")
        return {}
    if record["status"] == "insufficient":
        issues.append("fundamentals_insufficient")
    return record


def _record_issues(record: dict) -> list:
    """The fundamentals record's own issue codes (e.g. companyfacts_lag)."""
    issues = record.get("issues")
    if not isinstance(issues, list):
        return []
    return [issue for issue in issues if isinstance(issue, str) and issue]


def _compute(
    row: dict, member: dict, record, prices: dict, as_of: str, splits: dict
) -> None:
    issues = row["issues"]
    market = row["market"]
    if market not in MARKETS:
        raise ValueError(f"unknown market {market!r}")
    if member.get("sector") in MONEY:
        issues.append("financial_sector_eligible")
    used = _usable_fundamentals(row["id"], record, as_of, issues)
    source = record if isinstance(record, dict) else {}
    # D8': the record's findings (statement-API lag, unavailable lag check) stay in the
    # row; a record of another member lends it none.
    own = bool(source) and source.get("id") == row["id"]
    carried = _record_issues(source) if own else []
    issues.extend(carried)
    cap, detail, cap_issues = market_cap(member, used, prices, as_of, **splits)
    issues.extend(cap_issues)
    cfo, capex, assets = (number(used.get(k)) for k in ("cfoTTM", "capexTTM", "assets"))
    fcf = None
    if used:
        if cfo is None:
            issues.append("cfo_missing")
        if capex is None:
            issues.append("capex_missing")
        elif capex < 0:
            issues.append("capex_negative")
        elif cfo is not None:
            fcf = cfo - capex
        if assets is None:
            issues.append("assets_missing")
        elif assets <= 0:
            issues.append("assets_nonpositive")
        currency = used.get("currency")
        if currency != PROTOCOL["currencies"][market]:
            issues.append(
                "currency_missing" if currency is None else "currency_mismatch"
            )
            fcf = None
    if cap is None:
        issues.append("market_cap_missing")
    elif cap <= 0:
        issues.append("market_cap_nonpositive")
    fcf_yield = fcf / cap if fcf is not None and cap is not None and cap > 0 else None
    profitability = (
        cfo / assets if cfo is not None and assets is not None and assets > 0 else None
    )
    momentum, issue, window = momentum_12_1(
        prices.get(member.get("priceSymbol")), as_of
    )
    if issue:
        issues.append(issue)
    row["signals"] = dict(
        fcfYield=number(fcf_yield),
        cashProfitability=number(profitability),
        momentum12_1=number(momentum),
    )
    row["marketCap"] = cap
    row["inputs"] = dict(
        fundamentalsStatus=source.get("status"),
        fundamentalsError=source.get("error"),
        fundamentalsIssues=carried,
        lagCheck=source.get("lagCheck") if own else None,
        currency=source.get("currency"),
        periodEnd=source.get("periodEnd"),
        filedAt=source.get("filedAt"),
        cfoTTM=cfo,
        capexTTM=capex,
        assets=assets,
        momentumWindow=window,
        **detail,
    )


def signals(
    member: dict,
    fundamentals,
    prices_by_symbol,
    as_of,
    *,
    splits_by_symbol=None,
    retrieved_on=None,
    windows_by_symbol=None,
    capture_dates_by_market=None,
) -> dict:
    """Raw signals of one member at T; per-company failures become issues, not raises.

    ``as_of`` is the member market's T (or the ``{market: T}`` dict); prices_by_symbol
    maps every class's priceSymbol to rows ``[[date, adjclose, close], ...]``.
    ``splits_by_symbol`` maps the same symbols to ``prices.series(...)["splits"]``
    (``[{date, numerator, denominator}]``) of series fetched through ``retrieved_on``
    ('YYYY-MM-DD', the exchange-local retrieval date of those closes). The US market
    cap needs both (else withheld as splits_unknown); a call passing neither keeps the
    unadjusted cap flagged splits_unchecked. ``windows_by_symbol`` maps the symbols to
    ``prices.series(...)["window"]`` (``{from, through}``): a window ending before
    ``retrieved_on`` left later splits unread, so the US cap is withheld as
    splits_unknown and a KR class flagged splits_unchecked (D7'). A registration
    passes it; without it the windows are not checked.

    ``capture_dates_by_market`` is ``capture_dates(universe)``, ``{"KR":
    'YYYY-MM-DD'}``: KR listed shares are captured with the universe after T, so only
    a split with ex-date in (that date, ``retrieved_on``] withholds the KR market cap
    (split_after_as_of, L4); a capture after ``retrieved_on`` withholds it as well
    (capture_after_retrieval, N6: collect again). A capture timestamp with a UTC offset
    is converted by capture_date(). Without it T stands in for the capture date. A KR
    row records the capture date as ``inputs.sharesCapturedOn`` (None when none was
    given).

    A member whose own series has no session on T gets no market cap, FCF yield or
    momentum (D9': no_price_on_as_of). The fundamentals record's issues and lagCheck are
    kept in the row (``issues``, ``inputs.fundamentalsIssues``, ``inputs.lagCheck``).
    """
    status = member.get("status")
    row = dict(
        id=member.get("id"),
        market=member.get("market"),
        name=member.get("name"),
        ticker=member.get("ticker"),
        priceSymbol=member.get("priceSymbol"),
        sector=member.get("sector"),
        status="eligible" if status == "eligible" else "excluded",
        reason=member.get("reason"),
        asOf=None,
        signals=dict.fromkeys(SIGNALS),
        marketCap=None,
        inputs={},
        issues=[],
        error=None,
    )
    for key in ("cik", "corpCode", "sic", "ksic"):
        if member.get(key) is not None:
            row[key] = member[key]
    if status not in ("eligible", "excluded"):
        row["issues"].append("unknown_status")
        row["reason"] = row["reason"] or f"status {status!r}"
    try:
        if isinstance(as_of, dict):  # {market: T} as passed to register()
            as_of = as_of.get(row["market"])
        row["asOf"] = iso_day(as_of)
        if row["status"] == "eligible":
            splits = dict(
                splits_by_symbol=splits_by_symbol,
                retrieved_on=retrieved_on,
                windows_by_symbol=windows_by_symbol,
                capture_dates_by_market=capture_dates_by_market,
            )
            _compute(
                row, member, fundamentals, prices_by_symbol or {}, row["asOf"], splits
            )
    except Exception as exc:  # company boundary: record the failure, never raise
        row.update(signals=dict.fromkeys(SIGNALS), marketCap=None)
        row["issues"].append("signal_error")
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["issues"] = list(dict.fromkeys(row["issues"]))
    return row


def _standardize(eligible: list, signal: str) -> None:
    present = [r for r in eligible if r["signals"][signal] is not None]
    if not present:
        return
    ordered = sorted(r["signals"][signal] for r in present)
    low = quantile(ordered, PROTOCOL["winsor"]["lower"])
    high = quantile(ordered, PROTOCOL["winsor"]["upper"])
    for r in present:
        r["winsorized"][signal] = min(max(r["signals"][signal], low), high)
    values = [r["winsorized"][signal] for r in present]
    center = math.fsum(values) / len(values)
    scale = math.sqrt(math.fsum((v - center) ** 2 for v in values) / len(values))
    if not scale > 0:
        for r in present:
            r["issues"].append(f"{signal}_z_undefined")
        return
    by_sector = defaultdict(list)
    for r in present:
        by_sector[r.get("sector")].append(r["winsorized"][signal])
    centers = {
        sector: math.fsum(v) / len(v)
        for sector, v in by_sector.items()
        if sector is not None and len(v) >= PROTOCOL["minSectorSize"]
    }
    for r in present:
        basis = "sector" if r.get("sector") in centers else "market"
        mean = centers[r["sector"]] if basis == "sector" else center
        r["z"][signal] = (r["winsorized"][signal] - mean) / scale
        r["zBasis"][signal] = basis
        if basis == "market":
            r["issues"].append("sector_fallback")


def _label(eligible: list, previous: dict) -> None:
    low = Fraction(PROTOCOL["terciles"]["avoidAtOrBelow"])
    high = Fraction(PROTOCOL["terciles"]["preferAbove"])
    keep = Fraction(str(PROTOCOL["hysteresis"]))
    scored = []
    for r in eligible:
        available = [r["z"][s] for s in SIGNALS if r["z"][s] is not None]
        if len(available) >= PROTOCOL["minSignals"]:
            r["composite"] = math.fsum(available) / len(available)
            scored.append(r)
        else:
            r["labelReason"] = "insufficient"
    ranked = percentiles({r["id"]: r["composite"] for r in scored})
    for r in scored:
        p = ranked[r["id"]]
        label = AVOID if p <= low else PREFER if p > high else WATCH
        reason = "tercile"
        before = previous.get(r["id"])
        if before == PREFER and label != PREFER and p >= keep:
            label, reason = PREFER, "hysteresis"
        elif before == AVOID and label != AVOID and p <= keep:
            label, reason = AVOID, "hysteresis"
        r.update(percentile=float(p), label=label, labelReason=reason)


def _previous(previous) -> dict:
    if not previous:
        return {}
    if isinstance(previous, dict):
        items = previous.items()
    else:
        items = ((row.get("id"), row.get("label")) for row in previous)
    return {key: label for key, label in items if label in LABELS}


def score(rows: list, previous=None) -> list:
    """Winsorize, sector-neutral z, composite, percentile and labels within each market.

    ``previous`` is ``{id: label}`` of the prior registration (or its rows) for the
    hysteresis rule. Excluded and insufficient members stay in the output unlabeled.
    """
    previous = _previous(previous)
    out = []
    for row in rows:
        r = dict(row)
        r["issues"] = list(row.get("issues") or [])
        raw = row.get("signals") or {}
        r["signals"] = {s: number(raw.get(s)) for s in SIGNALS}
        for s in SIGNALS:
            if raw.get(s) is not None and r["signals"][s] is None:
                r["issues"].append(f"{s}_invalid")
        r.update(
            winsorized=dict.fromkeys(SIGNALS),
            z=dict.fromkeys(SIGNALS),
            zBasis=dict.fromkeys(SIGNALS),
            composite=None,
            percentile=None,
            label=None,
            labelReason="excluded",
            previousLabel=previous.get(r.get("id")),
        )
        out.append(r)
    counts = Counter(r.get("id") for r in out)
    duplicates = sorted(str(key) for key, n in counts.items() if n > 1)
    if duplicates:
        raise ValueError(f"Duplicate ids in rows: {duplicates[:5]}")
    unknown = sorted({str(r.get("market")) for r in out} - set(MARKETS))
    if unknown:
        raise ValueError(f"Unknown markets in rows: {unknown}")
    for market in MARKETS:
        eligible = [
            r for r in out if r["market"] == market and r.get("status") == "eligible"
        ]
        for signal in SIGNALS:
            _standardize(eligible, signal)
        _label(eligible, previous)
    for r in out:
        r["issues"] = list(dict.fromkeys(r["issues"]))
    return out
