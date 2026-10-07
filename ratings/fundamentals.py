"""Point-in-time trailing-year cash flow, total assets and share counts for ratings-v1.

US facts come from SEC companyfacts (10-K/10-Q and amendments), KR facts from OpenDART
fnlttSinglAcntAll. Only filings dated before ``as_of`` are read (``FILED_BEFORE_AS_OF``;
AGENTS.md: 신호일 전날까지). A trailing year that cannot be formed for the latest
reported period is ``insufficient`` with its reason; it is never filled from an older
period. The latest periodic report filed before ``as_of`` is also looked up apart from
the statement API (US: the stored SEC submissions original; KR: OpenDART list.json); when
it covers a later period than the facts did, the API lags the filings. In the US that
report, and every 10-K/A or 10-Q/A for its period filed before ``as_of``, is then read
from its own XBRL instance in the EDGAR archives (``RULES['us']['filingXbrl']``, issue
``filing_xbrl_supplement``): the facts join companyfacts under each filing's accession,
form and filing date, so per period the latest filing wins, and periods the report does
not state still come from companyfacts. When that read fails, or in Korea, the record is
``insufficient`` (issue ``companyfacts_lag`` / ``dart_api_lag``) with the period values
moved to ``withheld``; when its online retrieval fails the record is an ``error`` (a
transient failure is collected again, never rated). ``RULES`` lists every constant used
here so the rating protocol can hash it.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
import io
import json
import math
import re
import time
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from equitylab.dart import request as dart_request

from .common import FetchError, ensure_dart_key, fetch, latest, sec_user_agent, store

SEC_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/"
DART_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")
LAG_FORMS = ("10-K", "10-Q")  # the original periodic reports in SEC submissions
AMENDMENT_FORMS = ("10-K/A", "10-Q/A")  # read with the report they amend (filingXbrl)
LAG_PERIOD_DAYS = 20  # a report period this much later than periodEnd is a newer period
LAG_WITHHELD = ("cfoTTM", "capexTTM", "assets")
US_ZONE = "America/New_York"
KR_LIST_DAYS = 400
KR_LIST_MAX_PAGES = 5
KR_PERIODIC = r"(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)"
UNIVERSE_FETCH_ERROR = "universe_fetch_error"  # set by ratings.universe on the member
US_CFO = (
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
)
US_CAPEX = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsToAcquireOtherPropertyPlantAndEquipment",
)
# Read only when a trailing-year period has no US_CAPEX tag (RULES us.capexTag).
US_CAPEX_MORE = (
    "PaymentsForCapitalImprovements",
    "PaymentsToAcquireMachineryAndEquipment",
    "PaymentsForConstructionInProcess",
    "PaymentsToExploreAndDevelopOilAndGasProperties",
)
# Capex-category tags a capex trailing year not taken wholly from US_CAPEX[0] is checked
# against (RULES us.capexUnderstated).
US_CAPEX_COMPARE = (
    US_CAPEX + US_CAPEX_MORE + ("PaymentsToAcquireOilAndGasPropertyAndEquipment",)
)
CAPEX_UNDERSTATED = "capex_tag_understated"
COVER = ("dei", "EntityCommonStockSharesOutstanding")
DILUTED = ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding")
BALANCE_SHARES = ("us-gaap", "CommonStockSharesOutstanding")
# Filing XBRL supplement (RULES us.filingXbrl): the report that companyfacts lacks is read
# from its own XBRL instance in the EDGAR archives.
SUPPLEMENT_ISSUE = "filing_xbrl_supplement"
SUPPLEMENT_FAILED = "filing_xbrl_unavailable"
XBRLI = "http://www.xbrl.org/2003/instance"
XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
CIK_SCHEME = "http://www.sec.gov/CIK"
FILING_TAXONOMIES = {
    "us-gaap": r"http://fasb\.org/us-gaap/\d{4}(?:-\d{2}-\d{2})?",
    "dei": r"http://xbrl\.sec\.gov/dei/\d{4}(?:-\d{2}-\d{2})?",
}
FILING_UNITS = {
    "USD": ("http://www.xbrl.org/2003/iso4217", "USD"),
    "shares": (XBRLI, "shares"),
}
FILING_CONCEPTS = tuple(
    [("us-gaap", tag, "USD") for tag in US_CFO + US_CAPEX_COMPARE + ("Assets",)]
    + [(*COVER, "shares"), (*DILUTED, "shares"), (*BALANCE_SHARES, "shares")]
)
FILING_INSTANCE = r"[A-Za-z0-9][A-Za-z0-9._-]*\.xml"
FILING_LINKBASE = r".*_(?:cal|def|lab|pre)\.xml"
FILING_SUMMARY = "FilingSummary.xml"
DECIMALS_LIMIT = 100  # duplicate ranges use at most this many places either way
ANNUAL_DAYS = (330, 400)
YTD_MIN_DAYS = 60
QUARTER_DAYS = (80, 100)
SAME_LENGTH_DAYS = 10
SHARES_AGREE = (0.5, 2.0)
SHARES_MAX_AGE_DAYS = 400
CONFLICT_NOTE_DAYS = 800
FILED_BEFORE_AS_OF = True  # AGENTS.md: 신호일 전날까지 공개된 항목만; rating.py agrees
KR_REPORTS = {
    "11013": ("Q1", 3),
    "11012": ("H1", 6),
    "11014": ("Q3", 9),
    "11011": ("FY", 12),
}
KR_NEWEST_FIRST = ("11011", "11014", "11012", "11013")
KR_FS = ("CFS", "OFS")
KR_WALK = 5
KR_WALK_OTHER_FYE = 9
KR_CURRENT = ("thstrm_add_amount", "thstrm_amount")
KR_PREVIOUS_SAME = ("frmtrm_add_amount", "frmtrm_q_amount", "frmtrm_amount")
KR_CFO = dict(
    ids=("ifrs-full_CashFlowsFromUsedInOperatingActivities",),
    names=(
        "영업활동현금흐름",
        "영업활동으로인한현금흐름",
        "영업활동순현금흐름",
        "영업활동으로인한순현금흐름",
    ),
)
KR_CAPEX = dict(
    ids=(
        "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "ifrs-full_PurchaseOfPropertyPlantAndEquipment",
    ),
    prefix="ifrs-full_PurchaseOfPropertyPlantAndEquipment",
    contains="유형자산의취득",
)
KR_ASSETS = dict(ids=("ifrs-full_Assets",), names=("자산총계",))
KR_OPENING_CASH = dict(
    ids=(
        "dart_CashAndCashEquivalentsAtBeginningOfPeriodCf",
        "ifrs-full_CashAndCashEquivalentsAtBeginningOfPeriod",
    ),
    starts=("기초현금", "기초의현금"),
)
KR_CASH = dict(ids=("ifrs-full_CashAndCashEquivalents",), names=("현금및현금성자산",))
REQUIRED = {
    "US": ("cfoTTM", "capexTTM", "assets", "shares"),
    "KR": ("cfoTTM", "capexTTM", "assets"),
}

RULES = dict(
    version="ratings-v1-fundamentals-4",
    status="ok only when every REQUIRED field is present; otherwise insufficient "
    "with the available fields kept and the reasons in error",
    required={k: list(v) for k, v in REQUIRED.items()},
    filedBeforeAsOf=FILED_BEFORE_AS_OF,
    filedRule=f"usable filing date <= asOf{' - 1 day' if FILED_BEFORE_AS_OF else ''} "
    "(US companyfacts filed, or the SEC submissions filingDate of a report or "
    "amendment read by the filing XBRL supplement; KR first 8 digits of rcept_no)",
    us=dict(
        source="SEC companyfacts first; a later periodic report filed before asOf "
        "that companyfacts lacks (lag.us) is read from its own XBRL instance in the "
        "EDGAR archives, with every amendment of it filed before asOf (filingXbrl); "
        "if that read fails the record is insufficient (companyfacts_lag), and if its "
        "online retrieval fails the record is an error (collected again)",
        forms=list(FORMS),
        pointInTime="per (start, end) the latest usable filing",
        periodEnd="latest end among CFO durations and Assets instants; CFO and "
        "assets must both be reported at it",
        cfo=[f"us-gaap:{t}" for t in US_CFO],
        cfoTag="the first cfo tag whose own periods form the trailing year (ttm); "
        "else, when more than one cfo tag reports durations, the trailing year formed "
        "(ttm) from the periods any cfo tag reports, taken by tagChain over cfo (base "
        "list cfo)",
        capex=[f"us-gaap:{t}" for t in US_CAPEX],
        capexMore=[f"us-gaap:{t}" for t in US_CAPEX_MORE],
        capexTag="the first capex tag reporting every period of the CFO trailing "
        "year; else tagChain over capex; else, when a period has no capex tag, the "
        "first capexMore tag reporting every period, or else tagChain over capex then "
        "capexMore; the base list is capex",
        tagChain="each period of the trailing year from the first tag in list order "
        "reporting it, the previous same-length YTD from the current YTD's tag when "
        "that tag reports it; a trailing year taken this way, or from a capexMore "
        "tag, is withheld when a tag of its base list or a tag it takes a period from "
        "reports one of its periods with another value or with conflicting values in "
        "one filing",
        capexUnderstated="a capex trailing year not taken wholly from "
        f"us-gaap:{US_CAPEX[0]} that passes tagChain and capexCheck is withheld "
        f"(issue {CAPEX_UNDERSTATED}) when a capexCompare tag it takes no period from "
        "reports every one of its periods with a larger trailing-year total (same "
        "signs)",
        capexCompare=[f"us-gaap:{t}" for t in US_CAPEX_COMPARE],
        assets="us-gaap:Assets",
        ttm="annual at periodEnd; else YTD + previous annual - previous same-length "
        "YTD; else four contiguous reported quarters",
        annualDays=list(ANNUAL_DAYS),
        ytdMinDays=YTD_MIN_DAYS,
        quarterDays=list(QUARTER_DAYS),
        sameLengthDays=SAME_LENGTH_DAYS,
        capexCheck="previous same-length YTD above previous annual withholds capex",
        shares=":".join(COVER),
        sharesProxy=":".join(DILUTED) + " latest quarter",
        sharesChecks=[":".join(DILUTED), ":".join(BALANCE_SHARES)],
        sharesAgreement=list(SHARES_AGREE),
        sharesMaxAgeDays=SHARES_MAX_AGE_DAYS,
        sharesRule="cover if it agrees with a check count (or none exists); diluted "
        "if cover is absent or both checks agree against it; otherwise withheld",
        multiValueCover="sum (distinct classes) or largest (reported total) only "
        "when it agrees with a check count; otherwise not used",
        filingXbrl=dict(
            when="the lag check (lag.us) finds its latestReport later than the "
            "companyfacts periodEnd",
            report="that latestReport: an original 10-K/10-Q with filingDate <= asOf "
            "- 1 day in the SEC submissions original; a report filed on or after asOf "
            "is never read, nor one that submissions mark isXBRL 0",
            amendments="every amendmentForms filing in that submissions original "
            "with the report's reportDate, filed on or after the report's filingDate "
            "and on or before asOf - 1 day, is read after the report, oldest first, "
            "by the same rules (index to duplicates) and listed in "
            "lagCheck.supplement.amendments with status read, skipped, unreadable or "
            "unread; one that submissions mark isXBRL 0 is skipped (not read); one "
            "without these concepts (e.g. a Part III 10-K/A) adds nothing; one that "
            "cannot be read, or is not stored offline, fails the supplement "
            "('amended_by <accession> unreadable: <reason>'), and any not reached "
            "after a failure stays unread",
            amendmentForms=list(AMENDMENT_FORMS),
            index="https://www.sec.gov/Archives/edgar/data/<cik>/<accession without "
            "dashes>/index.json, stored as sec-filing-index-<accession>",
            instance="the one listed file ending in _htm.xml (inline XBRL), else the "
            f"one .xml that is not *_cal/_def/_lab/_pre.xml or {FILING_SUMMARY}; its "
            f"name must match {FILING_INSTANCE}; stored as sec-filing-xbrl-<accession>",
            retrieval="ratings.common.fetch with the SEC User-Agent; offline the "
            "latest stored originals",
            contexts="every context's entity identifier is the member's CIK (scheme "
            f"{CIK_SCHEME}); facts only from contexts without segment or scenario (no "
            "dimensions) whose period is startDate/endDate or instant as YYYY-MM-DD; "
            "nil facts are skipped",
            concepts=[f"{t}:{c} ({u})" for t, c, u in FILING_CONCEPTS],
            taxonomies=dict(FILING_TAXONOMIES),
            units={k: "{%s}%s" % v for k, v in FILING_UNITS.items()},
            values="an xs:decimal without exponent that a float can hold; any other "
            "value makes the instance unreadable",
            duplicates="per concept, unit and period: equal values count once; "
            "different values keep the most precise when every one states decimals, "
            "the most precise agree and every range (value +/- half a unit in the "
            "place decimals names, at most decimalsLimit places either way; INF exact) "
            "shares a point; otherwise, including different values where one lacks "
            "decimals, every value stays and the period conflicts (not used)",
            decimalsLimit=DECIMALS_LIMIT,
            facts="added to companyfacts with each filing's own accession, form and "
            "filingDate from SEC submissions, so per (start, end) the latest usable "
            "filing picks them (pointInTime); periods the report does not state still "
            "come from companyfacts and the trailing-year, capex-tag and share rules "
            "are unchanged",
            required="the report (not an amendment): a CFO duration (cfo tags) and "
            "us-gaap:Assets at the instance's latest CFO end, which is at most "
            "lag.periodDays before the report period",
            issue=f"{SUPPLEMENT_ISSUE}; lagCheck.supplement records the accession, "
            "instance, each amendment and the companyfacts periodEnd, and the lag "
            "check passes",
            failure="no unique instance, an unreadable instance or one naming another "
            "issuer, missing required facts, an amendment that cannot be read, an "
            "original not stored (offline), or a periodEnd that still lags leave the "
            "record insufficient with companyfacts_lag (lag.rule) and "
            f"'{SUPPLEMENT_FAILED}: <reason>' in the lag detail and lagCheck.supplement",
            onlineFailure="online, a failed retrieval of a filing index or instance "
            "(ratings.common.fetch FetchError: an HTTP error such as SEC's 403 rate "
            "limit or a 5xx after its retries, or a network failure) makes the record "
            "an error, collected again; never companyfacts_lag",
        ),
    ),
    kr=dict(
        source="OpenDART fnlttSinglAcntAll",
        reports={code: name for code, (name, _) in KR_REPORTS.items()},
        fsDiv=list(KR_FS),
        fsRule="per report CFS then OFS; one fs_div for every report of the "
        "trailing year, OFS when the CFS previous annual is missing and the OFS "
        "latest report was also filed before asOf",
        walkRule="newest report first; a period ending on or after asOf is not "
        "probed; a report filed on or after asOf is skipped",
        walk=KR_WALK,
        walkOtherFiscalYearEnd=KR_WALK_OTHER_FYE,
        ttm="annual thstrm; else cumulative thstrm + previous annual thstrm - "
        "previous same cumulative period",
        currentFields=list(KR_CURRENT),
        previousSameFields=list(KR_PREVIOUS_SAME),
        cfo=dict(ids=list(KR_CFO["ids"]), names=list(KR_CFO["names"])),
        capex=dict(
            ids=list(KR_CAPEX["ids"]),
            prefix=KR_CAPEX["prefix"],
            nameContains=KR_CAPEX["contains"],
            absolute=True,
        ),
        assets=dict(ids=list(KR_ASSETS["ids"]), names=list(KR_ASSETS["names"])),
        capexCheck="previous same cumulative period above previous annual "
        "withholds capex",
        currency="KRW only",
    ),
    lag=dict(
        rule="a periodic report filed before asOf for a later period than the facts "
        "(US: companyfacts with the filing XBRL supplement, us.filingXbrl) makes the "
        "record insufficient: cfoTTM, capexTTM and assets move to 'withheld'; share "
        "counts are kept",
        withheld=list(LAG_WITHHELD),
        us="latest non-amended report (forms usForms, filingDate <= asOf - 1) in "
        "the stored SEC submissions original sec-submissions-<cik> retrieved on or "
        "after asOf (New York); reportDate later than periodEnd + periodDays -> "
        "that report and its amendments are read by the filing XBRL supplement "
        "(us.filingXbrl) and the periodEnd they give is compared again; "
        "companyfacts_lag when it fails (us.filingXbrl.onlineFailure: an error when "
        "its online retrieval fails). Online, a missing or older original is fetched "
        "again",
        usForms=list(LAG_FORMS),
        periodDays=LAG_PERIOD_DAYS,
        kr="OpenDART list.json pblntf_ty A, last_reprt_at N, bgn_de asOf - listDays, "
        "end_de asOf - 1; the latest period (YYYY.MM of reportName) among periodic "
        "reports with rcept_dt <= asOf - 1 later than the used report's period (its "
        "list entry by rcept_no, else its periodEnd, else any original report filed "
        "after it) -> dart_api_lag",
        krListDays=KR_LIST_DAYS,
        krListMaxPages=KR_LIST_MAX_PAGES,
        krReportName=KR_PERIODIC,
        unavailable="offline without a stored original: issue lag_check_unavailable "
        "and status unchanged; an online retrieval failure makes the record an error",
    ),
    universeFetchError=f"a member with issue {UNIVERSE_FETCH_ERROR} (incomplete "
    "universe profile) is insufficient without any retrieval",
)


def collect(member: dict, as_of, online: bool = True) -> dict:
    """Fundamentals record for one universe member; failures stay inside the record."""
    market = member.get("market") or ("US" if member.get("cik") else "KR")
    if isinstance(as_of, dict):
        as_of = as_of.get(market)
    sources: list = []
    out = _record(member, market, str(as_of), sources)
    try:
        as_of = date.fromisoformat(str(as_of)[:10]).isoformat()
        out["asOf"] = as_of
        if market in REQUIRED and UNIVERSE_FETCH_ERROR in (member.get("issues") or []):
            out["issues"].append(UNIVERSE_FETCH_ERROR)
            step = member.get("fetchError") or "incomplete member profile"
            return _finish(out, [f"{UNIVERSE_FETCH_ERROR}: {step}"])
        if market == "US":
            if not member.get("cik"):
                raise ValueError("US member lacks cik")
            cik = int(str(member["cik"]))
            headers = None
            if online:
                headers = {"User-Agent": sec_user_agent(), "Accept": "application/json"}
            blob, manifest = fetch(
                SEC_URL.format(cik=cik),
                f"sec-facts-CIK{cik:010d}",
                provider="SEC",
                online=online,
                headers=headers,
            )
            sources.append(manifest)
            body = json.loads(blob)
            if int(body.get("cik", -1)) != cik:
                raise ValueError("SEC companyfacts CIK does not match the member")
            result = _us(member, body, as_of, sources)
            check, amendments = _us_lag(
                cik, as_of, result["periodEnd"], online, headers, sources
            )
            if check["status"] == "lag":
                result, check = _us_supplement(
                    member, body, as_of, result, check, online, headers, amendments
                )
            return _apply_lag(result, check, "companyfacts_lag")
        if market == "KR":
            corp = str(member.get("corpCode") or "")
            if not re.fullmatch(r"\d{8}", corp):
                raise ValueError("KR member lacks an 8-digit corpCode")
            if online:
                ensure_dart_key()
            result = _kr(member, as_of, _dart_reports(corp, online), sources)
            filings, manifests = _dart_list(corp, as_of, online)
            sources.extend(manifests)
            check = _kr_lag(result, filings, corp, as_of)
            return _apply_lag(result, check, "dart_api_lag")
        raise ValueError(f"Unsupported market {market!r}")
    except Exception as exc:  # the company boundary: record, never raise
        out.update(
            status="error",
            error=str(exc) or type(exc).__name__,
            missing=list(REQUIRED.get(market, ())),
        )
        return out


def _record(member: dict, market: str, as_of: str, sources: list) -> dict:
    return dict(
        id=member.get("id"),
        market=market,
        asOf=as_of,
        status="error",
        error=None,
        missing=[],
        currency="KRW" if market == "KR" else "USD",
        cfoTTM=None,
        capexTTM=None,
        assets=None,
        shares=None,
        sharesBasis=None,
        sharesAsOf=None,
        listedShares=None,
        periodEnd=None,
        filedAt=None,
        method=None,
        fsDiv=None,
        tags={},
        components=[],
        filings=[],
        sources=sources,
        notes=[],
        issues=[],
        lagCheck=None,
        withheld=None,
    )


def _finish(out: dict, reasons: list) -> dict:
    out["missing"] = [k for k in REQUIRED[out["market"]] if out[k] is None]
    out["status"] = "insufficient" if out["missing"] else "ok"
    out["error"] = "; ".join(reasons or out["missing"]) if out["missing"] else None
    return out


def _retrieved_since(manifest: dict | None, as_of: str, zone: str) -> bool:
    """Whether an original was retrieved on or after the start of ``as_of`` in ``zone``."""
    try:
        when = datetime.fromisoformat(str((manifest or {}).get("retrievedAt")))
    except ValueError:
        return False
    if when.utcoffset() is None:
        return False
    day = _day(as_of)
    return when >= datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(zone))


def _apply_lag(out: dict, check: dict, issue: str) -> dict:
    """Record the lag check; a lagging statement API withholds the period values."""
    out["lagCheck"] = check
    if check["status"] == "unavailable":
        out["issues"].append("lag_check_unavailable")
        out["notes"].append(f"lag check unavailable: {check['detail']}")
        return out
    if check["status"] != "lag":
        return out
    out["issues"].append(issue)
    held = {k: out[k] for k in LAG_WITHHELD if out[k] is not None}
    out["withheld"] = dict(held, periodEnd=out["periodEnd"]) if held else None
    for key in LAG_WITHHELD:
        out[key] = None
    reasons = [f"{issue}: {check['detail']}"] + ([out["error"]] if out["error"] else [])
    return _finish(out, reasons)


# --- United States: SEC companyfacts ------------------------------------------------


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _shift(day: str, days: int) -> str:
    return (_day(day) + timedelta(days=days)).isoformat()


def _through(as_of: str) -> str:
    """Last filing date usable for signals at ``as_of``."""
    return _shift(as_of, -1) if FILED_BEFORE_AS_OF else as_of


def _span(period: tuple) -> int:
    return (_day(period[1]) - _day(period[0])).days + 1


def _latest_filing(
    facts: dict, taxonomy: str, tag: str, unit: str, through: str
) -> dict:
    """{(start, end): facts from the latest filing dated <= ``through`` reporting it}."""
    groups: dict = {}
    for f in facts.get(taxonomy, {}).get(tag, {}).get("units", {}).get(unit, []):
        value = f.get("val")
        if (
            f.get("form") not in FORMS
            or not f.get("end")
            or not f.get("filed")
            or f["filed"] > through
            or f["end"] > through
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            continue
        groups.setdefault((f.get("start"), f["end"]), []).append(f)
    out = {}
    for period, rows in groups.items():
        top = max((f["filed"], f["accn"]) for f in rows)
        out[period] = [f for f in rows if (f["filed"], f["accn"]) == top]
    return out


def _view(facts: dict, taxonomy: str, tag: str, unit: str, through: str):
    """One value per period; a period whose latest filing gives two values is dropped."""
    view, conflicts = {}, []
    for period, rows in _latest_filing(facts, taxonomy, tag, unit, through).items():
        if len({f["val"] for f in rows}) == 1:
            view[period] = rows[0]
        else:
            conflicts.append(period)
    return view, conflicts


def _plan(view: dict, end: str):
    """([(sign, period)], method) summing to the trailing year ending at ``end``."""
    spans = sorted((p for p in view if p[0] and p[1] == end), key=_span, reverse=True)
    for p in spans:
        if ANNUAL_DAYS[0] <= _span(p) <= ANNUAL_DAYS[1]:
            return [(1, p)], "annual"
    for p in spans:
        length = _span(p)
        if not YTD_MIN_DAYS <= length < ANNUAL_DAYS[0]:
            continue
        before = _shift(p[0], -1)
        annuals = [
            a
            for a in view
            if a[0] and a[1] == before and ANNUAL_DAYS[0] <= _span(a) <= ANNUAL_DAYS[1]
        ]
        if not annuals:
            continue
        a = min(annuals, key=lambda a: abs(_span(a) - 365))
        same = [
            q
            for q in view
            if q[0] == a[0]
            and q[1] < a[1]
            and abs(_span(q) - length) <= SAME_LENGTH_DAYS
        ]
        if same:
            q = min(same, key=lambda q: abs(_span(q) - length))
            return [(1, p), (1, a), (-1, q)], "ytd"
    quarters, cursor = [], end
    while len(quarters) < 4:
        found = [
            q
            for q in view
            if q[0]
            and q[1] == cursor
            and QUARTER_DAYS[0] <= _span(q) <= QUARTER_DAYS[1]
        ]
        if not found:
            break
        quarters.append(found[0])
        cursor = _shift(found[0][0], -1)
    total = sum(map(_span, quarters))
    if len(quarters) == 4 and ANNUAL_DAYS[0] <= total <= ANNUAL_DAYS[1]:
        return [(1, q) for q in quarters], "quarters"
    return None, f"no annual, year-to-date or four-quarter trailing year ends {end}"


def _parts(metric: str, views: dict, plan: list) -> list:
    """Components of a trailing year given as [(sign, period, tag)]."""
    return [
        dict(
            metric=metric,
            tag=f"us-gaap:{tag}",
            sign=sign,
            start=period[0],
            end=period[1],
            days=_span(period),
            value=views[tag][0][period]["val"],
            accession=views[tag][0][period]["accn"],
            form=views[tag][0][period]["form"],
            filedAt=views[tag][0][period]["filed"],
        )
        for sign, period, tag in plan
    ]


def _tag_names(plan: list) -> str:
    return ", ".join(dict.fromkeys(f"us-gaap:{tag}" for _, _, tag in plan))


def _chain(views: dict, tags, plan: list, method: str) -> list | None:
    """``plan`` [(sign, period)] as [(sign, period, tag)] by the tag chain ``tags``
    (RULES us.tagChain): each period from the first tag reporting it, the previous
    same-length YTD from the current YTD's tag when that tag reports it; None when a
    period has no tag."""
    out = []
    for sign, period in plan:
        tag = next((t for t in tags if period in views[t][0]), None)
        if tag is None:
            return None
        out.append((sign, period, tag))
    if method == "ytd" and out[2][1] in views[out[0][2]][0]:
        out[2] = (out[2][0], out[2][1], out[0][2])
    return out


def _disagreement(views: dict, base, plan: list) -> str | None:
    """Why a chained trailing year is withheld (RULES us.tagChain): a tag of the base
    list, or one it takes a period from, reports a period with another value or with
    conflicting values in one filing; None when none does."""
    used = [tag for _, _, tag in plan]
    for _, period, tag in plan:
        value = views[tag][0][period]["val"]
        for other in dict.fromkeys(list(base) + used):
            view, conflicts = views[other]
            if period in conflicts or (period in view and view[period]["val"] != value):
                return (
                    f"us-gaap:{other} reports {period[0]}..{period[1]} otherwise "
                    f"than us-gaap:{tag} (tag chain withheld)"
                )
    return None


def _capex_plan(views: dict, plan: list, method: str) -> tuple:
    """([(sign, period, tag)] or None, reason or None) of the capex trailing year over
    the CFO ``plan`` [(sign, period)] (RULES us.capexTag); a plan with a reason is
    withheld (tagChain)."""
    tag = next((t for t in US_CAPEX if all(p in views[t][0] for _, p in plan)), None)
    if tag:
        return [(sign, period, tag) for sign, period in plan], None
    found = _chain(views, US_CAPEX, plan, method)
    if found is None:
        more = next(
            (t for t in US_CAPEX_MORE if all(p in views[t][0] for _, p in plan)), None
        )
        if more:
            found = [(sign, period, more) for sign, period in plan]
        else:
            found = _chain(views, US_CAPEX + US_CAPEX_MORE, plan, method)
    if found is None:
        return None, "no capex tag reports every trailing period"
    return found, _disagreement(views, US_CAPEX, found)


def _understated(views: dict, plan: list, total) -> str | None:
    """Why a capex trailing year not taken wholly from US_CAPEX[0] is withheld (RULES
    us.capexUnderstated): a capexCompare tag it takes no period from reports every one
    of its periods with a larger total; None otherwise."""
    used = {tag for _, _, tag in plan}
    if used == {US_CAPEX[0]}:
        return None
    for other in US_CAPEX_COMPARE:
        view = views[other][0]
        if other in used or not all(period in view for _, period, _ in plan):
            continue
        larger = sum(sign * view[period]["val"] for sign, period, _ in plan)
        if larger > total:
            return (
                f"us-gaap:{other} reports every trailing period with a larger total "
                f"({larger} > {total}; {CAPEX_UNDERSTATED})"
            )
    return None


def _agree(a: float, b: float) -> bool:
    return SHARES_AGREE[0] <= a / b <= SHARES_AGREE[1]


def _newest(facts: list):
    return max(facts, key=lambda f: (f["end"], f["filed"], f["accn"]), default=None)


def _us_shares(facts: dict, through: str) -> dict:
    """Cover shares, else the latest quarterly diluted count, each checked by counts."""
    floor = _shift(through, -SHARES_MAX_AGE_DAYS)
    covers = {
        p[1]: rows
        for p, rows in _latest_filing(facts, *COVER, "shares", through).items()
        if p[0] is None and p[1] >= floor
    }
    diluted_view = _view(facts, *DILUTED, "shares", through)[0]
    diluted = _newest(
        [
            f
            for p, f in diluted_view.items()
            if p[0]
            and QUARTER_DAYS[0] <= _span(p) <= QUARTER_DAYS[1]
            and p[1] >= floor
            and f["val"] > 0
        ]
    )
    balance_view = _view(facts, *BALANCE_SHARES, "shares", through)[0]
    balance = _newest(
        [
            f
            for p, f in balance_view.items()
            if p[0] is None and p[1] >= floor and f["val"] > 0
        ]
    )
    checks = [f["val"] for f in (diluted, balance) if f]
    out = dict(value=None, basis=None, asOf=None, facts=[], notes=[], reason=None)
    cover, rows, end = None, [], None
    if covers:
        end = max(covers)
        rows = [f for f in covers[end] if f["val"] > 0]
        values = sorted({f["val"] for f in rows})
        if len(values) == 1:
            cover = values[0]
        elif values:  # companyfacts drops class dimensions: classes or total + parts
            total = sum(values)
            options = [total]
            if math.isclose(values[-1], total - values[-1], rel_tol=0.005):
                options.append(values[-1])
            agreeing = [v for v in options if any(_agree(v, c) for c in checks)]
            cover = min(
                agreeing,
                key=lambda v: min(abs(math.log(v / c)) for c in checks),
                default=None,
            )
            verdict = (
                "not used (no agreeing count)"
                if cover is None
                else "summed as classes" if cover == total else "largest is the total"
            )
            out["notes"].append(
                f"cover reports {len(values)} values at {end}: {verdict}"
            )
    proxy = dict(
        value=diluted and diluted["val"],
        basis="diluted_wavg_proxy",
        asOf=diluted and diluted["end"],
        facts=[diluted],
    )
    if cover is not None:
        if not checks:
            out["notes"].append("cover shares not cross-checked (no other count)")
        if not checks or any(_agree(cover, c) for c in checks):
            return dict(out, value=cover, basis="cover", asOf=end, facts=rows)
        if diluted and balance and _agree(diluted["val"], balance["val"]):
            out["notes"].append(
                f"cover {cover} disagrees with diluted {diluted['val']} and "
                f"balance-sheet {balance['val']}; diluted proxy used"
            )
            return dict(out, **proxy)
        return dict(out, reason=f"cover {cover} disagrees with counts {checks}")
    if diluted is None:
        return dict(out, reason="no cover or quarterly diluted share count")
    if balance and not _agree(diluted["val"], balance["val"]):
        return dict(
            out,
            reason=f"diluted {diluted['val']} disagrees with balance-sheet "
            f"{balance['val']}",
        )
    return dict(out, **proxy)


def _us(member: dict, body: dict, as_of: str, sources: list) -> dict:
    out = _record(member, "US", as_of, sources)
    facts = body.get("facts", {})
    through = _through(as_of)
    reasons, used = [], []
    views = {
        tag: _view(facts, "us-gaap", tag, "USD", through)
        for tag in US_CFO + US_CAPEX_COMPARE
    }
    assets, assets_conflicts = _view(facts, "us-gaap", "Assets", "USD", through)
    ends = [p[1] for tag in US_CFO for p in views[tag][0] if p[0]]
    ends += [p[1] for p in assets if p[0] is None]
    if not ends:
        reasons.append("no CFO or total assets filed before as_of")
    else:
        end = out["periodEnd"] = max(ends)
        plan, failures, chained = None, [], False
        for tag in US_CFO:
            view = views[tag][0]
            if not any(p[0] and p[1] == end for p in view):
                continue
            found, how = _plan(view, end)
            if found:
                plan = [(sign, period, tag) for sign, period in found]
                break
            failures.append(f"{how} (us-gaap:{tag})")
        if plan is None and failures and sum(bool(views[t][0]) for t in US_CFO) > 1:
            joined = {}  # RULES us.cfoTag: the periods any cfo tag reports
            for tag in US_CFO:
                for period, row in views[tag][0].items():
                    joined.setdefault(period, row)
            found, how = _plan(joined, end)
            if found is None:
                failures.append(f"{how} (tag chain)")
            else:
                found = _chain(views, US_CFO, found, how)
                why = _disagreement(views, US_CFO, found)
                if why:
                    failures.append(why)
                else:
                    plan, chained = found, True
        if plan is None:
            failures = failures or [f"no standard CFO tag reported at {end}"]
            reasons.append("cfoTTM: " + "; ".join(failures))
            reasons.append("capexTTM: no CFO trailing year to align with")
        else:
            cfo = _parts("cfo", views, plan)
            out["cfoTTM"] = sum(c["sign"] * c["value"] for c in cfo)
            out["method"] = how
            out["tags"]["cfo"] = _tag_names(plan)
            out["components"] += cfo
            used += [views[tag][0][period] for _, period, tag in plan]
            if chained:
                out["notes"].append(f"CFO from the tag chain {_tag_names(plan)}")
            elif plan[0][2] != US_CFO[0]:
                out["notes"].append(f"CFO from fallback tag us-gaap:{plan[0][2]}")
            spans = [(sign, period) for sign, period, _ in plan]
            taken, why = _capex_plan(views, spans, how)
            if taken is None:
                reasons.append(f"capexTTM: {why}")
            else:
                capex = _parts("capex", views, taken)
                out["tags"]["capex"] = _tag_names(taken)
                out["components"] += capex
                used += [views[tag][0][period] for _, period, tag in taken]
                if len({tag for _, _, tag in taken}) > 1:
                    out["notes"].append(
                        f"capex from the tag chain {_tag_names(taken)} (scope not "
                        "reconciled)"
                    )
                elif taken[0][2] != US_CAPEX[0]:
                    out["notes"].append(
                        f"capex from fallback tag us-gaap:{taken[0][2]} (scope not "
                        "reconciled)"
                    )
                total = sum(c["sign"] * c["value"] for c in capex)
                larger = None if why else _understated(views, taken, total)
                if why:
                    reasons.append(f"capexTTM: {why}")
                elif out["method"] == "ytd" and capex[2]["value"] > capex[1]["value"]:
                    reasons.append(
                        "capexTTM: previous same-length YTD exceeds previous annual "
                        "(reclassification or restatement)"
                    )
                elif larger:
                    out["issues"].append(CAPEX_UNDERSTATED)
                    reasons.append(f"capexTTM: {larger}")
                else:
                    out["capexTTM"] = total
                    if out["capexTTM"] < 0:
                        out["notes"].append("trailing-year capex is negative")
        fact = assets.get((None, end))
        if fact:
            out["assets"] = fact["val"]
            out["tags"]["assets"] = "us-gaap:Assets"
            used.append(fact)
        else:
            reasons.append(f"assets: no us-gaap:Assets at {end}")
    shares = _us_shares(facts, through)
    out.update(shares=shares["value"], sharesBasis=shares["basis"])
    out["sharesAsOf"] = shares["asOf"]
    out["notes"] += shares["notes"]
    if shares["reason"]:
        reasons.append(f"shares: {shares['reason']}")
    else:
        out["tags"]["shares"] = ":".join(
            COVER if shares["basis"] == "cover" else DILUTED
        )
        used += shares["facts"]
    conflicts = [p for tag in US_CFO + US_CAPEX for p in views[tag][1]]
    floor = _shift(as_of, -CONFLICT_NOTE_DAYS)
    recent = sorted(
        {f"{s or ''}..{e}" for s, e in conflicts + assets_conflicts if e >= floor}
    )
    if recent:
        out["notes"].append("values conflict within one filing: " + ", ".join(recent))
    cik = int(body.get("cik", 0))
    filings = {
        f["accn"]: dict(
            accession=f["accn"],
            form=f["form"],
            filedAt=f["filed"],
            url=f"https://www.sec.gov/Archives/edgar/data/{cik}/"
            f"{f['accn'].replace('-', '')}/{f['accn']}-index.html",
        )
        for f in used
    }
    out["filings"] = sorted(
        filings.values(), key=lambda f: (f["filedAt"], f["accession"])
    )
    out["filedAt"] = max((f["filed"] for f in used), default=None)
    return _finish(out, reasons)


def _us_filings(profile, cik: int) -> list:
    """SEC submissions recent filings as rows (form, accession, filedAt, periodEnd,
    isXBRL); a body for another CIK or with ragged columns raises ValueError."""
    found = profile.get("cik", "") if isinstance(profile, dict) else None
    if str(found).lstrip("0") != str(cik):
        raise ValueError("SEC submissions CIK does not match the member")
    recent = (profile.get("filings") or {}).get("recent") or {}
    names = ("accessionNumber", "filingDate", "reportDate", "form")
    columns = [recent.get(name) or [] for name in names]
    if len({len(column) for column in columns}) != 1:
        raise ValueError("SEC submissions filing columns differ in length")
    xbrl = recent.get("isXBRL") or [None] * len(columns[0])
    return [
        dict(
            form=form, accession=accession, filedAt=filed, periodEnd=period, isXBRL=flag
        )
        for accession, filed, period, form, flag in zip(*columns, xbrl)
    ]


def _us_latest_report(profile, cik: int, through: str) -> dict | None:
    """Latest original 10-K/10-Q filed on or before ``through`` in SEC submissions."""
    best = None
    for row in _us_filings(profile, cik):
        if (
            row["form"] not in LAG_FORMS
            or not row["filedAt"]
            or not row["periodEnd"]
            or row["filedAt"] > through
        ):
            continue
        order = (row["periodEnd"], row["filedAt"], row["accession"])
        if best is None or order > (
            best["periodEnd"],
            best["filedAt"],
            best["accession"],
        ):
            best = row
    return best


def _us_amendments(profile, cik: int, report, through: str) -> list:
    """10-K/A and 10-Q/A for ``report``'s period filed on or after it and on or
    before ``through`` in SEC submissions, oldest first (RULES us.filingXbrl)."""
    if not report:
        return []
    rows = [
        row
        for row in _us_filings(profile, cik)
        if row["form"] in AMENDMENT_FORMS
        and row["periodEnd"] == report["periodEnd"]
        and row["filedAt"]
        and report["filedAt"] <= row["filedAt"] <= through
    ]
    return sorted(rows, key=lambda row: (row["filedAt"], str(row["accession"])))


def _us_lag(cik: int, as_of: str, period_end, online: bool, headers, sources):
    """(check, amendments): companyfacts' periodEnd against the stored SEC submissions.

    The universe build stores ``sec-submissions-<cik>`` after T; an original retrieved
    before T may miss filings, so online it is fetched again, offline the check is
    unavailable. Online retrieval failures raise (the record becomes an error).
    ``amendments`` are the latest report's amendments filed before T, for the filing
    XBRL supplement (``_us_amendments``).
    """
    key = f"sec-submissions-{cik:010d}"
    check = dict(status="unavailable", source=key, sha256=None, retrievedAt=None)
    check.update(periodEnd=period_end, latestReport=None, detail=None, supplement=None)
    missing = f"no stored {key}"
    try:
        blob, manifest = latest(key)
    except FetchError:
        blob, manifest = None, None
    if manifest is not None and not _retrieved_since(manifest, as_of, US_ZONE):
        missing = f"stored {key} predates asOf ({manifest.get('retrievedAt')})"
        blob, manifest = None, None
    if manifest is None and online:
        url = SEC_SUBMISSIONS_URL.format(cik=cik)
        blob, manifest = fetch(url, key, provider="SEC", online=True, headers=headers)
    if manifest is None:
        return dict(check, detail=missing), []
    sources.append(manifest)
    profile, through = json.loads(blob), _through(as_of)
    report = _us_latest_report(profile, cik, through)
    check.update(
        sha256=manifest.get("sha256"),
        retrievedAt=manifest.get("retrievedAt"),
        latestReport=report,
    )
    amendments = _us_amendments(profile, cik, report, through)
    return _us_verdict(check, period_end), amendments


def _us_verdict(check: dict, period_end) -> dict:
    """The lag verdict of a check whose latestReport is known, for ``period_end``."""
    report = check["latestReport"]
    check = dict(check, periodEnd=period_end, detail=None)
    if report is None:
        return dict(check, status="ok", detail="no 10-K/10-Q filed before asOf")
    later = period_end is None or report["periodEnd"] > _shift(
        period_end, LAG_PERIOD_DAYS
    )
    if not later:
        return dict(check, status="ok")
    detail = (
        f"{report['form']} for {report['periodEnd']} filed {report['filedAt']} "
        f"({report['accession']}); companyfacts latest period {period_end}"
    )
    return dict(check, status="lag", detail=detail)


def _us_supplement(
    member: dict,
    body: dict,
    as_of: str,
    result: dict,
    check: dict,
    online,
    headers,
    amendments=(),
) -> tuple:
    """(record, lag check) once the lagging report was read from its own XBRL instance.

    The report's facts, then each amendment's (``_us_amendments``), join companyfacts
    under that filing's accession, form and filing date, and the record is formed again
    by the companyfacts rules, so per period the latest filing wins; when a filing
    cannot be read, or the period still lags, the companyfacts record and its lag stand
    with the reason (``filing_xbrl_unavailable``) in the check. Online, a retrieval
    failure raises (``_us_filing``).
    """
    cik = int(body["cik"])
    sources = result["sources"]
    added, info = _us_filing(
        cik, as_of, check["latestReport"], online, headers, sources, amendments
    )
    info["companyfactsPeriodEnd"] = result["periodEnd"]
    if added is not None:
        merged = body.get("facts", {})
        for facts in added:
            merged = _merged(merged, facts)
        fresh = _us(member, dict(body, facts=merged), as_of, sources)
        verdict = _us_verdict(check, fresh["periodEnd"])
        if verdict["status"] == "ok":
            fresh["issues"].append(SUPPLEMENT_ISSUE)
            amended = "".join(
                (
                    f"; amended by {a['form']} {a['accession']} filed {a['filedAt']} "
                    f"({a['instance']}, {a['facts']} facts)"
                    if a["status"] == "read"
                    else f"; {a['form']} {a['accession']} filed {a['filedAt']} not "
                    f"read ({a['reason']})"
                )
                for a in info["amendments"]
            )
            fresh["notes"].append(
                f"{SUPPLEMENT_ISSUE}: {info['form']} {info['accession']} for "
                f"{info['periodEnd']} filed {info['filedAt']} read from its XBRL "
                f"instance {info['instance']} ({info['facts']} facts){amended}; "
                f"companyfacts latest period {result['periodEnd']}"
            )
            return fresh, dict(verdict, supplement=info)
        info = dict(
            info,
            status="unavailable",
            reason=f"periodEnd {fresh['periodEnd']} still lags the report",
        )
    detail = f"{check['detail']}; {SUPPLEMENT_FAILED}: {info['reason']}"
    return result, dict(check, detail=detail, supplement=info)


def _merged(facts: dict, added: dict) -> dict:
    """companyfacts ``facts`` with the ``added`` facts appended; neither is changed."""
    out = {taxonomy: dict(tags) for taxonomy, tags in facts.items()}
    for taxonomy, tags in added.items():
        for tag, entry in tags.items():
            old = out.setdefault(taxonomy, {}).get(tag) or {}
            units = dict(old.get("units") or {})
            for unit, rows in entry["units"].items():
                units[unit] = list(units.get(unit) or []) + rows
            out[taxonomy][tag] = dict(old, units=units)
    return out


def _us_filing(
    cik: int, as_of: str, report, online, headers, sources, amendments=()
) -> tuple:
    """([facts, ...] or None, supplement record) of ``report`` and its ``amendments``.

    ``report`` is the lag check's latestReport and ``amendments`` its 10-K/A and 10-Q/A
    filed before asOf, oldest first (SEC submissions). Each filing's EDGAR index.json
    and XBRL instance are fetched and stored like any original (offline: the latest
    stored); its facts come back shaped like companyfacts ``facts`` under its own
    accession, form and filing date, the report's first. A filing that cannot be read,
    or that is not stored offline, gives None with the reason in the record (an
    amendment as ``amended_by <accession> unreadable: <reason>``); online a retrieval
    failure raises FetchError so the record becomes an error and is collected again.
    Every amendment is listed with its status: read, skipped (isXBRL 0), unreadable,
    or unread (not reached after a failure).
    """
    report = report or {}
    info = dict(
        status="unavailable",
        accession=report.get("accession"),
        form=report.get("form"),
        filedAt=report.get("filedAt"),
        periodEnd=report.get("periodEnd"),
        instance=None,
        instancePeriodEnd=None,
        facts=0,
        reason=None,
        amendments=[
            dict(
                accession=row.get("accession"),
                form=row.get("form"),
                filedAt=row.get("filedAt"),
                status="unread",
                instance=None,
                facts=0,
                reason=None,
            )
            for row in amendments
        ],
    )
    through = _through(as_of)
    facts = None
    if report.get("form") not in LAG_FORMS or not report.get("periodEnd"):
        reason = f"not an original periodic report: {report.get('form')}"
    elif report.get("isXBRL") in (0, False):
        reason = "SEC submissions mark the report isXBRL 0"
    else:
        facts, reason = _filing_read(
            cik, through, report, online, headers, sources, info
        )
    if facts is not None:
        try:
            info["instancePeriodEnd"] = _supplement_end(facts, report)
        except ValueError as exc:
            facts, reason = None, str(exc)
    if facts is None:
        return None, dict(info, reason=reason)
    info["facts"] = _count(facts)
    read = [facts]
    for row, entry in zip(amendments, info["amendments"]):
        if row.get("isXBRL") in (0, False):
            entry.update(status="skipped", reason="SEC submissions mark it isXBRL 0")
            continue
        found, why = _filing_read(cik, through, row, online, headers, sources, entry)
        if found is None:
            entry.update(status="unreadable", reason=why)
            why = f"amended_by {entry['accession']} unreadable: {why}"
            return None, dict(info, reason=why)
        entry.update(status="read", facts=_count(found))
        read.append(found)
    return read, dict(info, status="used")


def _count(facts: dict) -> int:
    return sum(
        len(rows)
        for tags in facts.values()
        for entry in tags.values()
        for rows in entry["units"].values()
    )


def _filing_read(cik, through: str, row: dict, online, headers, sources, record):
    """(facts, None) of one filing (``row`` from SEC submissions) read from its XBRL
    instance, or (None, reason) when it cannot be read or, offline, is not stored.

    The instance name goes into ``record`` once the index names it. Online a retrieval
    failure (FetchError) is not a reason: it raises, and the record becomes an error.
    """
    accession = str(row.get("accession") or "")
    try:
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            raise ValueError(f"malformed accession {accession!r}")
        if not row.get("filedAt") or row["filedAt"] > through:
            raise ValueError(f"filed {row.get('filedAt')}, not before asOf")
        base = SEC_ARCHIVE_URL.format(cik=cik, folder=accession.replace("-", ""))
        blob, manifest = fetch(
            base + "index.json",
            f"sec-filing-index-{accession}",
            provider="SEC",
            online=online,
            headers=headers,
        )
        sources.append(manifest)
        try:
            index = json.loads(blob)
        except ValueError:
            raise ValueError("filing index is not JSON") from None
        name = record["instance"] = _instance_name(index, cik, accession)
        blob, manifest = fetch(
            base + name,
            f"sec-filing-xbrl-{accession}",
            provider="SEC",
            online=online,
            headers=dict(headers, Accept="application/xml") if headers else None,
            suffix=".xml",
        )
        sources.append(manifest)
        return _instance_facts(blob, cik, row), None
    except FetchError as exc:
        if online:
            raise  # the record becomes an error, collected again (onlineFailure)
        return None, str(exc) or type(exc).__name__  # offline: not stored
    except (ValueError, ArithmeticError, ET.ParseError) as exc:
        return None, str(exc) or type(exc).__name__


def _instance_name(index, cik: int, accession: str) -> str:
    """The one XBRL instance an EDGAR filing index.json lists (ValueError otherwise)."""
    directory = index.get("directory") if isinstance(index, dict) else None
    items = directory.get("item") if isinstance(directory, dict) else None
    if not isinstance(items, list):
        raise ValueError("filing index lists no directory")
    folder = f"/Archives/edgar/data/{cik}/{accession.replace('-', '')}"
    if str(directory.get("name") or folder).rstrip("/") != folder:
        raise ValueError(f"filing index is for {directory.get('name')}")
    names = [str(i.get("name") or "") for i in items if isinstance(i, dict)]
    inline = [n for n in names if n.endswith("_htm.xml")]
    plain = [
        n
        for n in names
        if n.lower().endswith(".xml")
        and n != FILING_SUMMARY
        and not re.fullmatch(FILING_LINKBASE, n, re.IGNORECASE)
    ]
    found = inline or plain
    if len(found) != 1:
        raise ValueError(
            f"{len(found)} XBRL instances listed: {', '.join(found)}"
            if found
            else "no XBRL instance listed"
        )
    if not re.fullmatch(FILING_INSTANCE, found[0]):
        raise ValueError(f"unexpected instance name {found[0]!r}")
    return found[0]


def _iso_date(text) -> str | None:
    text = (text or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _xbrl_number(text):
    """An xs:decimal lexical value as int (integral) or float; None otherwise, also
    when a float cannot hold it (RULES us.filingXbrl.values)."""
    text = (text or "").strip()
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        return None
    value = Decimal(text)
    if not math.isfinite(float(value)):
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def _instance_facts(blob: bytes, cik: int, report: dict) -> dict:
    """FILING_CONCEPTS facts of one XBRL instance shaped like companyfacts ``facts``.

    Only contexts without segment or scenario (no dimensions) count, every context
    must name the member's CIK, and a unit's measure is resolved through the namespace
    bindings in scope at it (root, unit, measure). Duplicates of one concept, unit and
    period keep one value when they are equal or consistent (``_consistent``);
    otherwise every value stays (the period then conflicts).
    """
    if b"<!DOCTYPE" in blob or b"<!ENTITY" in blob:
        raise ValueError("XBRL instance declares a DTD")
    declared, pending = {}, {}  # element -> the namespace bindings it declares
    parser = ET.iterparse(io.BytesIO(blob), events=("start-ns", "start"))
    for event, item in parser:
        if event == "start-ns":
            pending[item[0]] = item[1]
        elif pending:
            declared[item], pending = pending, {}
    root = parser.root
    x = "{%s}" % XBRLI
    if root.tag != x + "xbrl":
        raise ValueError("not an XBRL instance")
    units = {}
    for unit in root.findall(x + "unit"):
        kids = list(unit)
        if len(kids) != 1 or kids[0].tag != x + "measure":
            continue
        scope = {**declared.get(root, {}), **declared.get(unit, {})}
        scope.update(declared.get(kids[0], {}))
        prefix, _, local = (kids[0].text or "").strip().rpartition(":")
        for name, measure in FILING_UNITS.items():
            if (scope.get(prefix), local) == measure:
                units[unit.get("id")] = name
    contexts = {}
    for context in root.findall(x + "context"):
        ident = context.find(f"{x}entity/{x}identifier")
        if (
            ident is None
            or ident.get("scheme") != CIK_SCHEME
            or (ident.text or "").strip().lstrip("0") != str(cik)
        ):
            raise ValueError("XBRL instance names another issuer")
        if context.find(f".//{x}segment") is not None:
            continue
        if context.find(f".//{x}scenario") is not None:
            continue
        period = context.find(x + "period")
        if period is None:
            continue
        instant = _iso_date(period.findtext(x + "instant"))
        start = _iso_date(period.findtext(x + "startDate"))
        end = _iso_date(period.findtext(x + "endDate"))
        if instant:
            contexts[context.get("id")] = (None, instant)
        elif start and end and start <= end:
            contexts[context.get("id")] = (start, end)
    wanted = {(t, c): u for t, c, u in FILING_CONCEPTS}
    groups: dict = {}
    for element in root:
        ref = element.get("contextRef")
        if ref is None or not element.tag.startswith("{"):
            continue
        uri, _, local = element.tag[1:].partition("}")
        taxonomy = next(
            (t for t, p in FILING_TAXONOMIES.items() if re.fullmatch(p, uri)), None
        )
        unit = wanted.get((taxonomy, local))
        if unit is None or ref not in contexts:
            continue
        if units.get(element.get("unitRef")) != unit:
            continue
        if element.get(XSI_NIL) in ("true", "1"):
            continue
        value = _xbrl_number(element.text)
        if value is None:
            raise ValueError(f"unreadable value for {taxonomy}:{local} in {ref}")
        decimals = element.get("decimals")
        if decimals == "INF":
            precision = math.inf
        elif decimals and re.fullmatch(r"-?\d+", decimals):
            precision = int(decimals)
        else:
            precision = None
        key = (taxonomy, local, unit) + contexts[ref]
        groups.setdefault(key, []).append((value, precision))
    facts: dict = {}
    for (taxonomy, tag, unit, start, end), rows in groups.items():
        for value in _consistent(rows):
            fact = dict(
                end=end,
                val=value,
                accn=report["accession"],
                form=report["form"],
                filed=report["filedAt"],
            )
            if start:
                fact["start"] = start
            entry = facts.setdefault(taxonomy, {}).setdefault(tag, {"units": {}})
            entry["units"].setdefault(unit, []).append(fact)
    return facts


def _consistent(rows: list) -> list:
    """The values of one duplicate group of (value, decimals) (XBRL duplicates).

    Equal values count once. Different values are consistent duplicates, kept as the
    most precise value, when the most precise facts agree and every range (value plus
    or minus half a unit in the place ``decimals`` names, at most DECIMALS_LIMIT places
    either way; INF: the value itself) shares a point; otherwise, or when a precision
    is unknown, every value stays and the period conflicts.
    """
    values = sorted({value for value, _ in rows})
    precisions = [p for _, p in rows]
    if len(values) == 1 or None in precisions:
        return values

    def half(p) -> Decimal:
        if p == math.inf:
            return Decimal(0)
        places = max(-DECIMALS_LIMIT, min(DECIMALS_LIMIT, p))  # no decimal overflow
        return Decimal(5).scaleb(-places - 1)

    best = max(precisions)
    top = sorted({v for v, p in rows if p == best})
    low = max(Decimal(str(v)) - half(p) for v, p in rows)
    high = min(Decimal(str(v)) + half(p) for v, p in rows)
    return top if len(top) == 1 and low <= high else values


def _supplement_end(facts: dict, report: dict) -> str:
    """The instance period: its latest CFO end, with total assets reported at it."""
    ends = [
        f["end"]
        for tag in US_CFO
        for f in facts.get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", [])
        if f.get("start")
    ]
    if not ends:
        raise ValueError(
            "required facts missing: no CFO duration ("
            + ", ".join(f"us-gaap:{t}" for t in US_CFO)
            + ")"
        )
    end = max(ends)
    assets = facts.get("us-gaap", {}).get("Assets", {}).get("units", {}).get("USD", [])
    if not any(f["end"] == end and not f.get("start") for f in assets):
        raise ValueError(f"required facts missing: no us-gaap:Assets at {end}")
    if report["periodEnd"] > _shift(end, LAG_PERIOD_DAYS):
        raise ValueError(
            f"instance period {end} is earlier than the report period "
            f"{report['periodEnd']}"
        )
    return end


# --- Korea: OpenDART fnlttSinglAcntAll ----------------------------------------------


def _dart_get(params: dict, endpoint: str = "fnlttSinglAcntAll.json") -> bytes:
    delay = 1.0
    for attempt in range(3):
        try:
            return dart_request(endpoint, params)
        except RuntimeError as exc:  # transport failure; equitylab withholds the URL
            if attempt == 2:
                raise FetchError(f"OpenDART: {exc}") from None
            time.sleep(delay)
            delay *= 2
    raise FetchError("OpenDART: retries exhausted")


def _dart_list(corp: str, as_of: str, online: bool):
    """(filings or None, manifests): OpenDART list.json periodic reports before as_of.

    Offline without a stored original the filings are None (check unavailable).
    """
    end = _through(as_of).replace("-", "")
    begin = (_day(as_of) - timedelta(days=KR_LIST_DAYS)).strftime("%Y%m%d")
    filings, manifests, page, pages = [], [], 1, 1
    while page <= pages:
        params = dict(
            corp_code=corp,
            bgn_de=begin,
            end_de=end,
            pblntf_ty="A",
            last_reprt_at="N",
            page_no=page,
            page_count=100,
            sort="date",
            sort_mth="desc",
        )
        key = f"dart-list-{corp}-{end}" + (f"-p{page}" if page > 1 else "")
        if online:
            blob, manifest = _dart_get(params, "list.json"), None
        else:
            try:
                blob, manifest = latest(key)
            except FetchError:
                return None, manifests
        try:
            body = json.loads(blob)
        except ValueError:
            raise FetchError(f"OpenDART returned non-JSON for {key}") from None
        status = body.get("status") if isinstance(body, dict) else None
        if status not in ("000", "013"):  # 013: no filing in the range
            raise FetchError(f"OpenDART status {status} for {key}")
        if online:  # no credential in the stored URL
            url = f"{DART_LIST_URL}?{urlencode(params)}"
            manifest = store(blob, key, url, "OpenDART", ".json")
        manifests.append(manifest)
        if status == "013":
            break
        filings += body.get("list") or []
        pages = int(body.get("total_page") or 1)
        if pages > KR_LIST_MAX_PAGES:
            raise FetchError(f"OpenDART list.json spans {pages} pages for {key}")
        page += 1
    return filings, manifests


def _kr_periodic(filings: list, corp: str, cutoff: str) -> list:
    """Periodic reports (사업/반기/분기보고서) received on or before ``cutoff``."""
    out = []
    for filing in filings:
        if not isinstance(filing, dict) or str(filing.get("corp_code")) != corp:
            raise ValueError("OpenDART list.json lists another company")
        received = str(filing.get("rcept_dt") or "")
        name = str(filing.get("report_nm") or "")
        match = re.search(KR_PERIODIC, name)
        if not match or not re.fullmatch(r"\d{8}", received) or received > cutoff:
            continue
        out.append(
            dict(
                period=f"{match[2]}-{match[3]}",
                report=name,
                rceptNo=str(filing.get("rcept_no")),
                filedAt=f"{received[:4]}-{received[4:6]}-{received[6:]}",
                original=not name.lstrip().startswith("["),
            )
        )
    return out


def _kr_lag(out: dict, filings, corp: str, as_of: str) -> dict:
    """Compare the report the facts came from with the latest periodic filing."""
    check = dict(status="unavailable", latestReport=None, usedReport=None, detail=None)
    if filings is None:
        return dict(check, detail="no stored OpenDART list.json for asOf")
    periodic = _kr_periodic(filings, corp, _through(as_of).replace("-", ""))
    newest = max(
        periodic, key=lambda f: (f["period"], f["filedAt"], f["rceptNo"]), default=None
    )
    used = next((f for f in out["filings"] if f.get("role") == "latest"), None)
    check.update(latestReport=newest, usedReport=used and used["rceptNo"])
    if newest is None:
        return dict(check, status="ok", detail="no periodic report before asOf")
    if used is None:
        detail = f"{newest['report']} filed {newest['filedAt']}; no statements used"
        return dict(check, status="lag", detail=detail)
    entry = next((f for f in periodic if f["rceptNo"] == used["rceptNo"]), None)
    period = entry["period"] if entry else (used.get("periodEnd") or "")[:7] or None
    if period is not None:
        later = newest["period"] > period
    else:  # originals are filed in period order
        later = any(f["original"] and f["filedAt"] > used["filedAt"] for f in periodic)
    if not later:
        return dict(check, status="ok", usedPeriod=period)
    detail = (
        f"{newest['report']} filed {newest['filedAt']} ({newest['rceptNo']}); "
        f"statements from {used['report']} {used['rceptNo']}"
    )
    return dict(check, status="lag", usedPeriod=period, detail=detail)


def _dart_reports(corp: str, online: bool):
    """report(year, code, fs) -> (rows | None, manifest); None is status 013 (no data)."""

    def report(year: int, code: str, fs: str):
        params = dict(corp_code=corp, bsns_year=str(year), reprt_code=code, fs_div=fs)
        key = f"dart-acnt-{corp}-{year}-{code}-{fs}"
        blob, manifest = (_dart_get(params), None) if online else latest(key)
        try:
            body = json.loads(blob)
        except ValueError:
            raise FetchError(f"OpenDART returned non-JSON for {key}") from None
        if online:
            if body.get("status") not in ("000", "013"):  # never stored as an answer
                raise FetchError(f"OpenDART status {body.get('status')} for {key}")
            url = f"{DART_URL}?{urlencode(params)}"  # no credential in the manifest
            manifest = store(blob, key, url, "OpenDART", ".json")
        if body.get("status") == "013":
            return None, manifest
        if body.get("status") != "000":
            raise FetchError(f"OpenDART status {body.get('status')} for {key}")
        return body.get("list") or [], manifest

    return report


def _fye_month(member: dict) -> int:
    digits = re.sub(r"\D", "", str(member.get("fiscalYearEnd") or "12"))
    month = {1: digits, 2: digits, 4: digits[:2], 8: digits[4:6]}.get(len(digits), "")
    return int(month) if month.isdigit() and 1 <= int(month) <= 12 else 12


def _kr_walk(as_of: str, fye: int) -> list:
    """(bsns_year, reprt_code, period end or None) candidates, newest first."""
    day = _day(as_of)
    if fye != 12:  # bsns_year labelling is not assumed; probe one extra year instead
        years = range(day.year + 1, day.year - 3, -1)
        return [(y, c, None) for y in years for c in KR_NEWEST_FIRST][
            :KR_WALK_OTHER_FYE
        ]
    out = []
    for year in range(day.year, day.year - 3, -1):
        for code in KR_NEWEST_FIRST:
            month = KR_REPORTS[code][1]
            end = date(year, month, calendar.monthrange(year, month)[1])
            if end < day:  # a report cannot be filed by the end of its own period
                out.append((year, code, end.isoformat()))
    return out[:KR_WALK]


def _amount(text):
    if text is None:
        return None
    s = str(text).strip().replace(",", "")
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    if s in ("", "-"):
        return None
    try:
        value = int(s)
    except ValueError:
        try:
            value = float(s)
        except ValueError:
            return None
        if not math.isfinite(value):
            return None
    return -value if negative else value


def _first(row: dict, fields: tuple):
    for field in fields:
        value = _amount(row.get(field))
        if value is not None:
            return field, value
    return None, None


def _norm(name) -> str:
    text = re.sub(r"\s+", "", str(name or ""))
    return re.sub(
        r"^(?:[IVXⅠ-Ⅻ]+\.|\d+\.|\(\d+\)|\d+\)|[가-하]\.|\([가-하]\))", "", text
    )


def _kr_find(
    rows: list, sj: str, ids=(), prefix=None, names=(), contains=None, starts=()
):
    """(row, how) for one account: XBRL ids in order, then id prefix, then label."""
    pool = [r for r in rows if r.get("sj_div") == sj]
    tiers = [(f"id:{i}", [r for r in pool if r.get("account_id") == i]) for i in ids]
    if prefix:
        hits = [r for r in pool if str(r.get("account_id", "")).startswith(prefix)]
        tiers.append(("id-prefix", hits))
    labels = [
        r
        for r in pool
        if _norm(r.get("account_nm")) in names
        or (contains and contains in _norm(r.get("account_nm")))
        or any(_norm(r.get("account_nm")).startswith(s) for s in starts)
    ]
    tiers.append(("name", labels))
    for how, hits in tiers:
        if not hits:
            continue
        amounts = {
            tuple(_amount(v) for k, v in sorted(r.items()) if k.endswith("_amount"))
            for r in hits
        }
        if len(amounts) > 1:
            return None, f"{len(hits)} conflicting rows ({how})"
        row = hits[0]
        if not how.startswith("id:"):
            how = f"{how}:{row.get('account_id')}|{row.get('account_nm')}"
        return row, how
    return None, "not reported"


def _receipt(rows: list, corp: str, year: int, code: str) -> str:
    receipts = {str(r.get("rcept_no", "")) for r in rows}
    receipt = receipts.pop() if len(receipts) == 1 else ""
    if not re.fullmatch(r"\d{14}", receipt):
        raise ValueError(f"OpenDART {year} {code}: missing or mixed rcept_no")
    if any(
        str(r.get("corp_code")) != corp
        or str(r.get("bsns_year")) != str(year)
        or str(r.get("reprt_code")) != code
        for r in rows
    ):
        raise ValueError(f"OpenDART {year} {code}: response does not match request")
    return receipt


def _kr_opening_check(rows: list) -> str:
    """A cumulative CF column opens at the previous fiscal year-end balance-sheet cash."""
    opening = _kr_find(rows, "CF", **KR_OPENING_CASH)[0]
    cash = _kr_find(rows, "BS", **KR_CASH)[0]
    a = _first(opening, KR_CURRENT)[1] if opening else None
    b = _amount(cash.get("frmtrm_amount")) if cash else None
    if a is None or b is None:
        return "unavailable"
    return "ok" if a == b else "mismatch"


def _kr_latest(report, corp: str, as_of: str, fye: int, out: dict):
    """Newest periodic report filed before as_of, walking back period by period."""
    cutoff = _through(as_of).replace("-", "")
    walk = _kr_walk(as_of, fye)
    for year, code, end in walk:
        for fs in KR_FS:
            rows, manifest = report(year, code, fs)
            out["sources"].append(manifest)
            if rows is None:
                continue
            receipt = _receipt(rows, corp, year, code)
            if receipt[:8] <= cutoff:
                return dict(
                    year=year, code=code, end=end, fs=fs, rows=rows, receipt=receipt
                )
            out["notes"].append(
                f"{year} {KR_REPORTS[code][0]} filed {receipt[:8]}, not before as_of; skipped"
            )
            break
    return f"no periodic report filed before as_of in {len(walk)} periods"


def _kr_previous(report, corp: str, hit: dict, as_of: str, out: dict):
    """Previous annual in the same fs_div; OFS for every report if CFS lacks it.

    The OFS latest report is used only when it, too, was received before as_of.
    """
    cutoff = _through(as_of).replace("-", "")
    year = hit["year"] - 1
    rows, manifest = report(year, "11011", hit["fs"])
    out["sources"].append(manifest)
    if rows is None and hit["fs"] == "CFS":
        alt, manifest = report(hit["year"], hit["code"], "OFS")
        out["sources"].append(manifest)
        if alt is not None:
            name = f"{hit['year']} {KR_REPORTS[hit['code']][0]}"
            receipt = _receipt(alt, corp, hit["year"], hit["code"])
            if receipt[:8] > cutoff:
                out["notes"].append(
                    f"OFS {name} filed {receipt[:8]}, not before as_of; not used"
                )
                return (
                    f"previous annual report {year} unavailable (CFS) and OFS "
                    f"{name} filed {receipt[:8]}, not before as_of"
                )
            rows, manifest = report(year, "11011", "OFS")
            out["sources"].append(manifest)
            if rows is not None:
                if receipt != hit["receipt"]:
                    out["notes"].append(
                        f"OFS {name} receipt {receipt} differs from CFS "
                        f"{hit['receipt']}"
                    )
                hit.update(fs="OFS", rows=alt, receipt=receipt)
                out["notes"].append(
                    "previous annual lacks CFS; OFS used for every report"
                )
    if rows is None:
        return f"previous annual report {year} unavailable ({hit['fs']})"
    receipt = _receipt(rows, corp, year, "11011")
    if receipt[:8] > cutoff:
        return f"previous annual report {year} filed {receipt[:8]}, not before as_of"
    end = f"{year}-12-31" if hit["end"] else None
    return dict(
        year=year, code="11011", end=end, fs=hit["fs"], rows=rows, receipt=receipt
    )


def _kr_metric(metric: str, spec: dict, hit: dict, prior: dict | None) -> tuple:
    """(components, reason) for CFO or capex over the trailing year."""
    row, how = _kr_find(hit["rows"], "CF", **spec)
    if row is None:
        return [], f"{how} in {hit['year']} {KR_REPORTS[hit['code']][0]}"
    parts = [("current", 1, hit, row, how, KR_CURRENT)]
    if hit["code"] != "11011":
        prow, phow = _kr_find(prior["rows"], "CF", **spec)
        if prow is None:
            return [], f"{phow} in previous annual {prior['year']}"
        parts += [
            ("previousAnnual", 1, prior, prow, phow, ("thstrm_amount",)),
            ("previousSamePeriod", -1, hit, row, how, KR_PREVIOUS_SAME),
        ]
    components = []
    for role, sign, rep, r, account, fields in parts:
        field, value = _first(r, fields)
        if value is None:
            return [], f"no amount for {role}"
        components.append(
            dict(
                metric=metric,
                role=role,
                sign=sign,
                account=account,
                field=field,
                value=abs(value) if metric == "capex" else value,
                rceptNo=rep["receipt"],
                bsnsYear=rep["year"],
                reprtCode=rep["code"],
                fsDiv=rep["fs"],
            )
        )
    return components, None


def _kr(member: dict, as_of: str, report, sources: list) -> dict:
    out = _record(member, "KR", as_of, sources)
    corp = str(member["corpCode"])
    fye = _fye_month(member)
    if fye != 12:
        out["notes"].append(f"fiscal year ends in month {fye}; periodEnd not derived")
    hit = _kr_latest(report, corp, as_of, fye, out)
    if isinstance(hit, str):
        return _finish(out, [hit])
    prior, why = None, None
    if hit["code"] != "11011":
        prior = _kr_previous(report, corp, hit, as_of, out)
        if isinstance(prior, str):
            prior, why = None, prior
    out.update(periodEnd=hit["end"], fsDiv=hit["fs"])
    out["method"] = "annual" if hit["code"] == "11011" else "ytd"
    reports = [("latest", hit)] + ([("previousAnnual", prior)] if prior else [])
    for role, rep in reports:
        receipt = rep["receipt"]
        out["filings"].append(
            dict(
                role=role,
                rceptNo=receipt,
                filedAt=f"{receipt[:4]}-{receipt[4:6]}-{receipt[6:8]}",
                bsnsYear=rep["year"],
                reprtCode=rep["code"],
                report=KR_REPORTS[rep["code"]][0],
                fsDiv=rep["fs"],
                periodEnd=rep["end"],
                cumulativeCheck=_kr_opening_check(rep["rows"]),
                url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
            )
        )
        if out["filings"][-1]["cumulativeCheck"] == "mismatch":
            out["notes"].append(
                f"{role} CF opening cash differs from prior year-end cash"
            )
    out["filedAt"] = max(f["filedAt"] for f in out["filings"])
    currencies = {r.get("currency") for _, rep in reports for r in rep["rows"]}
    currencies.discard(None)
    if currencies - {"KRW"}:
        out["currency"] = ",".join(sorted(currencies))
        return _finish(out, [f"statements in {out['currency']}; ratings-v1 needs KRW"])
    reasons = []
    for metric, spec in (("cfo", KR_CFO), ("capex", KR_CAPEX)):
        if why:
            reasons.append(f"{metric}TTM: {why}")
            continue
        components, reason = _kr_metric(metric, spec, hit, prior)
        if reason:
            reasons.append(f"{metric}TTM: {reason}")
            continue
        out["tags"][metric] = components[0]["account"]
        out["components"] += components
        if metric == "capex" and len(components) == 3:
            if components[2]["value"] > components[1]["value"]:
                reasons.append(
                    "capexTTM: previous same cumulative period exceeds previous "
                    "annual (reclassification or restatement)"
                )
                continue
        if any(c["account"] != components[0]["account"] for c in components):
            out["notes"].append(f"{metric} matched differently across reports")
        out[f"{metric}TTM"] = sum(c["sign"] * c["value"] for c in components)
    row, how = _kr_find(hit["rows"], "BS", **KR_ASSETS)
    value = _amount(row.get("thstrm_amount")) if row else None
    if value is None:
        reasons.append(f"assets: {how if row is None else 'no amount'}")
    else:
        out["assets"] = value
        out["tags"]["assets"] = how
    return _finish(out, reasons)
