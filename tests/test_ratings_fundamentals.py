"""ratings.fundamentals on trimmed real originals (see fixtures provenance.json), offline.

SEC companyfacts, submissions, filing indexes and XBRL instances and OpenDART statements
and filing lists are served from tests/fixtures/ratings/fundamentals; no test reads
data/ratings/sources or the network.
"""

import copy
from datetime import date
import json
import math
import os
from pathlib import Path
import re
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

from ratings import common
from ratings import fundamentals as fx
from ratings import rating
from ratings.common import FetchError, protocol_hash

FIXTURES = Path(__file__).parent / "fixtures/ratings/fundamentals"
AAPL = dict(id="US:0000320193", market="US", ticker="AAPL", cik=320193)
GOOGL = dict(id="US:0001652044", market="US", ticker="GOOGL", cik="0001652044")
NVDA = dict(id="US:0001045810", market="US", ticker="NVDA", cik=1045810)
KO = dict(id="US:0000021344", market="US", ticker="KO", cik="0000021344")
SAMSUNG = dict(id="KR:005930", market="KR", ticker="005930", corpCode="00126380")
SYNTH = dict(id="US:0000000001", market="US", ticker="SYN", cik=1)
SUBMISSIONS_RETRIEVED = "2026-10-06T06:35:17+00:00"  # the smoke run's universe build
LISTING = json.loads((FIXTURES / "dart-list-00126380-20260929.json").read_text())
ISSUE = "universe_fetch_error"  # set on the member by ratings.universe


def manifest(key, retrieved=None):
    out = dict(key=key, sha256="0" * 64, file=f"fixture/{key}", url="fixture")
    if retrieved:
        out["retrievedAt"] = retrieved
    return out


def sec_fetch(url, key, **kwargs):
    """Fixture originals by key (.json, else .xml); a missing one fails as fetch would:
    offline not stored, online a 404."""
    for suffix in (".json", ".xml"):
        if (FIXTURES / f"{key}{suffix}").exists():
            return (FIXTURES / f"{key}{suffix}").read_bytes(), manifest(key)
    if not kwargs.get("online", True):
        raise FetchError(f"No stored original for {key}")
    raise FetchError(f"SEC: HTTP 404 for {key}")


def serve(overrides=None, calls=None):
    """sec_fetch with chosen originals replaced: bytes, or an exception to raise."""

    def fetch(url, key, **kwargs):
        if calls is not None:
            calls.append((url, key, kwargs))
        value = (overrides or {}).get(key)
        if isinstance(value, Exception):
            raise value
        if value is not None:
            return value, manifest(key)
        return sec_fetch(url, key, **kwargs)

    return fetch


def stored(retrieved=SUBMISSIONS_RETRIEVED, missing=()):
    """Stand-in for ratings.common.latest: the SEC submissions fixtures as stored."""

    def latest(key):
        path = FIXTURES / f"{key}.json"
        if (
            key in missing
            or not key.startswith("sec-submissions-")
            or not path.exists()
        ):
            raise FetchError(f"No stored original for {key}")
        return path.read_bytes(), manifest(key, retrieved)

    return latest


def us(member, as_of, facts=None, latest=None, fetch=None):
    """One US member offline; ``facts`` replaces its companyfacts original only."""
    if fetch is None:
        key = f"sec-facts-CIK{int(member['cik']):010d}"
        fetch = serve({key: facts} if facts is not None else None)
    with mock.patch.object(fx, "fetch", side_effect=fetch), mock.patch.object(
        fx, "latest", side_effect=latest or stored()
    ):
        return fx.collect(member, as_of, online=False)


def dart_rows(year, code, fs="CFS"):
    path = FIXTURES / f"dart-acnt-00126380-{year}-{code}-{fs}.json"
    if not path.exists():
        return None
    body = json.loads(path.read_text())
    return body["list"] if body["status"] == "000" else None


def reports(overrides=None, calls=None):
    """Samsung fixtures as an OpenDART reader; absent reports answer status 013."""

    def report(year, code, fs):
        if calls is not None:
            calls.append((year, code, fs))
        key = (year, code, fs)
        rows = overrides[key] if overrides and key in overrides else dart_rows(*key)
        return copy.deepcopy(rows), manifest(f"dart-acnt-00126380-{year}-{code}-{fs}")

    return report


def kr(as_of, overrides=None, member=SAMSUNG, calls=None, listing=LISTING):
    """Samsung offline: statements from the fixtures, the filing list as given."""
    reader = reports(overrides, calls)
    found = None if listing is None else copy.deepcopy(listing["list"])
    lists = [manifest("dart-list-00126380")] if listing is not None else []
    with mock.patch.object(fx, "_dart_reports", return_value=reader), mock.patch.object(
        fx, "_dart_list", return_value=(found, lists)
    ):
        return fx.collect(member, as_of, online=False)


def scaled(rows, factor):
    out = copy.deepcopy(rows)
    for r in out:
        for k, v in r.items():
            if k.endswith("_amount") and v not in (None, ""):
                r[k] = str(int(v) // factor)
    return out


def fact(start, end, val, filed, accn, form="10-Q"):
    f = dict(end=end, val=val, accn=accn, form=form, filed=filed)
    if start:
        f["start"] = start
    return f


def synthetic(**extra):
    """Calendar-year filer: 10-K 2026-02-10 (A), Q1 10-Q 2026-05-01 (Q), H1 10-Q 2026-08-01 (B)."""
    a, q, b = "0000000001-26-000001", "0000000001-26-000002", "0000000001-26-000003"
    cfo = [
        fact("2025-01-01", "2025-12-31", 1000, "2026-02-10", a, "10-K"),
        fact("2026-01-01", "2026-03-31", 280, "2026-05-01", q),
        fact("2025-01-01", "2025-03-31", 200, "2026-05-01", q),
        fact("2026-01-01", "2026-06-30", 600, "2026-08-01", b),
        fact("2025-01-01", "2025-06-30", 450, "2026-08-01", b),
    ]
    capex = [
        fact("2025-01-01", "2025-12-31", 300, "2026-02-10", a, "10-K"),
        fact("2026-01-01", "2026-03-31", 90, "2026-05-01", q),
        fact("2025-01-01", "2025-03-31", 60, "2026-05-01", q),
        fact("2026-01-01", "2026-06-30", 170, "2026-08-01", b),
        fact("2025-01-01", "2025-06-30", 140, "2026-08-01", b),
    ]
    tags = {
        "us-gaap:NetCashProvidedByUsedInOperatingActivities": cfo,
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment": capex,
        "us-gaap:Assets": [
            fact(None, "2025-12-31", 5000, "2026-02-10", a, "10-K"),
            fact(None, "2026-03-31", 5100, "2026-05-01", q),
            fact(None, "2026-06-30", 5200, "2026-08-01", b),
        ],
        "dei:EntityCommonStockSharesOutstanding": [
            fact(None, "2026-04-25", 1_000_000, "2026-05-01", q),
            fact(None, "2026-07-25", 990_000, "2026-08-01", b),
        ],
        "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding": [
            fact("2026-04-01", "2026-06-30", 1_005_000, "2026-08-01", b),
        ],
    }
    for name, rows in extra.items():
        tags[name.replace("__", ":")] = rows
    facts = {}
    for name, rows in tags.items():
        taxonomy, tag = name.split(":")
        unit = "shares" if "Shares" in tag else "USD"
        facts.setdefault(taxonomy, {})[tag] = {"units": {unit: rows}}
    return dict(cik=1, entityName="Synthetic", facts=facts)


def synth(as_of, body):
    return fx._us(SYNTH, body, as_of, [])


class UnitedStatesFixtureTests(unittest.TestCase):
    def test_apple_nine_month_ytd_trailing_year(self):
        r = us(AAPL, "2026-09-30")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["method"], "ytd")
        self.assertEqual(r["cfoTTM"], 116996000000 + 111482000000 - 81754000000)
        self.assertEqual(r["capexTTM"], 6799000000 + 12715000000 - 9473000000)
        self.assertEqual(r["assets"], 383266000000)
        self.assertEqual((r["shares"], r["sharesBasis"]), (14594180000, "cover"))
        self.assertEqual(r["sharesAsOf"], "2026-07-17")
        self.assertEqual((r["periodEnd"], r["filedAt"]), ("2026-06-27", "2026-07-31"))
        self.assertEqual(
            [f["accession"] for f in r["filings"]],
            ["0000320193-25-000079", "0000320193-26-000020"],
        )
        self.assertEqual(r["sources"][0]["key"], "sec-facts-CIK0000320193")
        self.assertIsNone(r["listedShares"])
        # The stored SEC submissions agree: the latest 10-Q is the one used.
        self.assertEqual(r["sources"][1]["key"], "sec-submissions-0000320193")
        self.assertEqual((r["lagCheck"]["status"], r["issues"]), ("ok", []))
        self.assertEqual(
            r["lagCheck"]["latestReport"]["accession"], "0000320193-26-000020"
        )

    def test_filings_on_or_after_as_of_are_invisible(self):
        for as_of in ("2026-07-30", "2026-07-31"):  # third-quarter 10-Q filed 07-31
            r = us(AAPL, as_of)
            self.assertEqual(r["periodEnd"], "2026-03-28")
            self.assertEqual(r["cfoTTM"], 82627000000 + 111482000000 - 53887000000)
            self.assertEqual(r["capexTTM"], 4344000000 + 12715000000 - 6011000000)
            self.assertEqual(r["sharesAsOf"], "2026-04-17")
            self.assertLess(r["filedAt"], as_of)
        self.assertEqual(us(AAPL, "2026-08-01")["periodEnd"], "2026-06-27")

    def test_annual_report_is_used_directly(self):
        r = us(AAPL, "2025-12-31")
        self.assertEqual(r["method"], "annual")
        self.assertEqual((r["cfoTTM"], r["capexTTM"]), (111482000000, 12715000000))
        self.assertEqual(r["periodEnd"], "2025-09-27")

    def test_capex_falls_back_to_the_tag_covering_every_period(self):
        r = us(NVDA, "2026-09-30")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(
            r["tags"]["capex"], "us-gaap:PaymentsToAcquireProductiveAssets"
        )
        self.assertEqual(r["capexTTM"], 4434000000 + 6042000000 - 3122000000)
        self.assertEqual(r["cfoTTM"], 74421000000 + 102718000000 - 42779000000)
        self.assertTrue(any("fallback tag" in n for n in r["notes"]))

    def test_multi_class_issuer_without_cover_uses_diluted_proxy(self):
        r = us(GOOGL, "2026-09-30")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(
            (r["shares"], r["sharesBasis"]), (12309000000, "diluted_wavg_proxy")
        )
        self.assertEqual(r["sharesAsOf"], "2026-06-30")
        self.assertEqual(r["cfoTTM"], 84859000000 + 164713000000 - 63897000000)
        self.assertEqual(r["capexTTM"], 80598000000 + 91447000000 - 39643000000)


class UnitedStatesRuleTests(unittest.TestCase):
    def test_half_year_and_first_quarter_point_in_time(self):
        body = synthetic()
        r = synth("2026-09-30", body)
        self.assertEqual((r["status"], r["cfoTTM"], r["capexTTM"]), ("ok", 1150, 330))
        self.assertEqual((r["assets"], r["shares"]), (5200, 990_000))
        r = synth("2026-07-31", body)
        self.assertEqual(
            (r["periodEnd"], r["cfoTTM"], r["capexTTM"]), ("2026-03-31", 1080, 330)
        )

    def test_restatement_counts_only_once_filed(self):
        late = fact(
            "2025-01-01",
            "2025-12-31",
            1100,
            "2026-09-15",
            "0000000001-26-000009",
            "10-K/A",
        )
        body = synthetic()
        body["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]["units"][
            "USD"
        ].append(late)
        self.assertEqual(synth("2026-09-14", body)["cfoTTM"], 1150)
        self.assertEqual(synth("2026-09-30", body)["cfoTTM"], 1250)

    def test_other_forms_are_ignored(self):
        body = synthetic()
        stray = fact(
            "2026-01-01",
            "2026-09-30",
            9999,
            "2026-09-20",
            "0000000001-26-000010",
            "8-K",
        )
        body["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]["units"][
            "USD"
        ].append(stray)
        r = synth("2026-09-30", body)
        self.assertEqual((r["periodEnd"], r["cfoTTM"]), ("2026-06-30", 1150))

    def test_conflicting_values_in_one_filing_are_not_chosen_silently(self):
        body = synthetic()
        twin = fact(
            "2026-01-01", "2026-06-30", 601, "2026-08-01", "0000000001-26-000003"
        )
        body["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]["units"][
            "USD"
        ].append(twin)
        r = synth("2026-09-30", body)
        self.assertEqual(r["status"], "insufficient")
        self.assertIsNone(r["cfoTTM"])
        self.assertIn("cfoTTM", r["error"])
        self.assertTrue(any("conflict" in n for n in r["notes"]))

    def test_capex_reclassification_withholds_capex_only(self):
        body = synthetic()
        rows = body["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]
        rows["units"]["USD"][4]["val"] = 320  # prior-year H1 above the prior annual 300
        r = synth("2026-09-30", body)
        self.assertEqual(r["status"], "insufficient")
        self.assertEqual(r["missing"], ["capexTTM"])
        self.assertEqual(r["cfoTTM"], 1150)
        self.assertIn("reclassification", r["error"])

    def test_latest_balance_sheet_without_cfo_is_not_backfilled(self):
        body = synthetic(
            **{
                "us-gaap__Assets": synthetic()["facts"]["us-gaap"]["Assets"]["units"][
                    "USD"
                ]
                + [fact(None, "2026-09-30", 5300, "2026-11-01", "0000000001-26-000011")]
            }
        )
        r = synth("2026-12-31", body)
        self.assertEqual(r["periodEnd"], "2026-09-30")
        self.assertIsNone(r["cfoTTM"])
        self.assertEqual(r["assets"], 5300)
        self.assertIn("no standard CFO tag reported at 2026-09-30", r["error"])

    def test_continuing_operations_tag_is_a_fallback(self):
        body = synthetic()
        cfo = body["facts"]["us-gaap"].pop("NetCashProvidedByUsedInOperatingActivities")
        body["facts"]["us-gaap"][fx.US_CFO[1]] = cfo
        r = synth("2026-09-30", body)
        self.assertEqual((r["status"], r["cfoTTM"]), ("ok", 1150))
        self.assertEqual(r["tags"]["cfo"], f"us-gaap:{fx.US_CFO[1]}")

    def test_four_discrete_quarters_and_insufficient_history(self):
        q = [
            ("2025-07-01", "2025-09-30", 10),
            ("2025-10-01", "2025-12-31", 20),
            ("2026-01-01", "2026-03-31", 30),
            ("2026-04-01", "2026-06-30", 40),
        ]
        view = {(s, e): dict(val=v) for s, e, v in q}
        plan, how = fx._plan(view, "2026-06-30")
        self.assertEqual(how, "quarters")
        self.assertEqual(sum(view[p]["val"] for _, p in plan), 100)
        del view[("2025-10-01", "2025-12-31")]
        plan, how = fx._plan(view, "2026-06-30")
        self.assertIsNone(plan)
        self.assertIn("no annual", how)

    def test_shares_cross_checks(self):
        b = "0000000001-26-000003"
        cover = fact(None, "2026-07-25", 250_000, "2026-08-01", b)  # pre-split count
        diluted = fact("2026-04-01", "2026-06-30", 1_005_000, "2026-08-01", b)
        balance = fact(None, "2026-06-30", 1_000_000, "2026-08-01", b)

        def shares(covers=(), dil=(), bal=()):
            facts = {
                "dei": {COVER: {"units": {"shares": list(covers)}}},
                "us-gaap": {
                    DIL: {"units": {"shares": list(dil)}},
                    BAL: {"units": {"shares": list(bal)}},
                },
            }
            return fx._us_shares(facts, "2026-09-30")

        COVER, DIL, BAL = fx.COVER[1], fx.DILUTED[1], fx.BALANCE_SHARES[1]
        r = shares([cover], [diluted], [balance])
        self.assertEqual((r["value"], r["basis"]), (1_005_000, "diluted_wavg_proxy"))
        r = shares([cover], [diluted])
        self.assertIsNone(r["value"])
        self.assertIn("disagrees", r["reason"])
        r = shares([cover])
        self.assertEqual((r["value"], r["basis"]), (250_000, "cover"))
        self.assertTrue(any("not cross-checked" in n for n in r["notes"]))
        classes = [dict(cover, val=700_000), dict(cover, val=300_000)]
        r = shares(classes, [diluted])
        self.assertEqual(r["value"], 1_000_000)
        self.assertTrue(any("summed as classes" in n for n in r["notes"]))
        with_total = classes + [dict(cover, val=1_000_000)]
        r = shares(with_total, [diluted])
        self.assertEqual(r["value"], 1_000_000)
        self.assertTrue(any("largest is the total" in n for n in r["notes"]))
        twins = [dict(cover, val=500_000), dict(cover, val=502_000)]
        r = shares(twins, [dict(diluted, val=1_000_000)])
        self.assertEqual(r["value"], 1_002_000)  # both readings agree; nearest wins
        self.assertEqual(
            shares(classes)["reason"], "no cover or quarterly diluted share count"
        )
        r = shares([], [diluted], [dict(balance, val=100_000)])
        self.assertIsNone(r["value"])


class KoreaTests(unittest.TestCase):
    def test_samsung_half_year_cumulative_trailing_year(self):
        calls = []
        r = kr("2026-09-30", calls=calls)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["cfoTTM"], 145355192000000 + 85315148000000 - 33941002000000)
        self.assertEqual(
            r["capexTTM"], 31234818000000 + 47522179000000 - 26831217000000
        )
        self.assertEqual(r["assets"], 759480516000000)
        self.assertEqual(
            (r["currency"], r["fsDiv"], r["method"]), ("KRW", "CFS", "ytd")
        )
        self.assertEqual((r["periodEnd"], r["filedAt"]), ("2026-06-30", "2026-08-14"))
        self.assertEqual(calls, [(2026, "11012", "CFS"), (2025, "11011", "CFS")])
        self.assertEqual(
            [f["rceptNo"] for f in r["filings"]], ["20260814003699", "20260310002820"]
        )
        self.assertEqual((r["lagCheck"]["status"], r["issues"]), ("ok", []))
        self.assertEqual(r["lagCheck"]["usedPeriod"], "2026-06")
        self.assertEqual({f["cumulativeCheck"] for f in r["filings"]}, {"ok"})
        prior = [c for c in r["components"] if c["role"] == "previousSamePeriod"]
        self.assertEqual({c["field"] for c in prior}, {"frmtrm_q_amount"})
        self.assertIsNone(r["shares"])

    def test_unfiled_quarter_walks_back_through_status_013(self):
        calls = []
        r = kr("2026-10-30", calls=calls)
        self.assertEqual(
            calls[:3],
            [(2026, "11014", "CFS"), (2026, "11014", "OFS"), (2026, "11012", "CFS")],
        )
        self.assertEqual(r["periodEnd"], "2026-06-30")
        keys = [s["key"] for s in r["sources"]]
        self.assertEqual(len([k for k in keys if k.startswith("dart-acnt-")]), 4)
        self.assertEqual(keys[-1], "dart-list-00126380")
        self.assertEqual(r["lagCheck"]["status"], "ok")  # Q3 is not filed yet

    def test_report_filed_on_or_after_as_of_is_skipped(self):
        self.assertEqual(kr("2026-08-15")["periodEnd"], "2026-06-30")
        r = kr("2026-08-14")  # the half-year report was received 2026-08-14
        self.assertEqual(r["periodEnd"], "2026-03-31")
        self.assertEqual(r["cfoTTM"], 40274106000000 + 85315148000000 - 16580866000000)
        self.assertEqual(
            r["capexTTM"], 17127003000000 + 47522179000000 - 12127934000000
        )
        self.assertEqual(r["assets"], 633339604000000)
        self.assertTrue(any("20260814, not before as_of" in n for n in r["notes"]))

    def test_annual_report_is_used_directly(self):
        r = kr("2026-04-30")
        self.assertEqual((r["method"], r["periodEnd"]), ("annual", "2025-12-31"))
        self.assertEqual((r["cfoTTM"], r["capexTTM"]), (85315148000000, 47522179000000))
        self.assertEqual(len(r["filings"]), 1)

    def test_separate_statements_replace_every_component_when_cfs_annual_missing(self):
        overrides = {
            (2025, "11011", "CFS"): None,
            (2026, "11012", "OFS"): scaled(dart_rows(2026, "11012"), 2),
            (2025, "11011", "OFS"): scaled(dart_rows(2025, "11011"), 2),
        }
        r = kr("2026-09-30", overrides)
        self.assertEqual((r["status"], r["fsDiv"]), ("ok", "OFS"))
        self.assertEqual(
            r["cfoTTM"],
            145355192000000 // 2 + 85315148000000 // 2 - 33941002000000 // 2,
        )
        self.assertEqual({c["fsDiv"] for c in r["components"]}, {"OFS"})
        self.assertTrue(any("OFS used for every report" in n for n in r["notes"]))

    def test_company_without_consolidated_statements(self):
        overrides = {(y, c, "CFS"): None for y, c in [(2026, "11012"), (2025, "11011")]}
        overrides[(2026, "11012", "OFS")] = dart_rows(2026, "11012")
        overrides[(2025, "11011", "OFS")] = dart_rows(2025, "11011")
        r = kr("2026-09-30", overrides)
        self.assertEqual((r["status"], r["fsDiv"]), ("ok", "OFS"))
        self.assertEqual(r["filings"][1]["fsDiv"], "OFS")

    def test_label_fallback_commas_and_parentheses(self):
        def relabel(rows):
            out = copy.deepcopy(rows)
            for r in out:
                r["account_id"] = "-표준계정코드 미사용-"
                if r["account_nm"] == "영업활동현금흐름":
                    r["account_nm"] = "Ⅰ. 영업활동으로 인한 현금흐름"
                for k, v in r.items():
                    if k.endswith("_amount") and v:
                        r[k] = f"{int(v):,}"
                if r["account_nm"] == "유형자산의 취득":
                    r["thstrm_amount"] = f"({r['thstrm_amount']})"
            return out

        overrides = {
            (2026, "11012", "CFS"): relabel(dart_rows(2026, "11012")),
            (2025, "11011", "CFS"): relabel(dart_rows(2025, "11011")),
        }
        r = kr("2026-09-30", overrides)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["cfoTTM"], 196729338000000)
        self.assertEqual(r["capexTTM"], 51925780000000)
        self.assertEqual(r["assets"], 759480516000000)
        self.assertTrue(r["tags"]["cfo"].startswith("name:"))

    def test_ambiguous_capex_rows_and_reclassified_capex_are_withheld(self):
        rows = dart_rows(2026, "11012")
        capex = next(r for r in rows if r["account_nm"] == "유형자산의 취득")
        rows.append(dict(capex, thstrm_amount="1"))
        r = kr("2026-09-30", {(2026, "11012", "CFS"): rows})
        self.assertEqual((r["status"], r["missing"]), ("insufficient", ["capexTTM"]))
        self.assertIn("conflicting rows", r["error"])
        rows = dart_rows(2026, "11012")
        capex = next(r for r in rows if r["account_nm"] == "유형자산의 취득")
        capex["frmtrm_q_amount"] = "50000000000000"  # above the previous annual
        r = kr("2026-09-30", {(2026, "11012", "CFS"): rows})
        self.assertEqual(r["missing"], ["capexTTM"])
        self.assertIn("reclassification", r["error"])
        self.assertIsNotNone(r["cfoTTM"])

    def test_non_krw_statements_are_not_used(self):
        rows = [dict(r, currency="USD") for r in dart_rows(2026, "11012")]
        r = kr("2026-09-30", {(2026, "11012", "CFS"): rows})
        self.assertEqual((r["status"], r["currency"]), ("insufficient", "KRW,USD"))
        self.assertEqual((r["cfoTTM"], r["capexTTM"], r["assets"]), (None, None, None))
        self.assertIn("needs KRW", r["error"])

    def test_missing_reports_and_late_previous_annual(self):
        r = kr(
            "2026-09-30",
            {
                (2026, "11012", "CFS"): None,
                (2026, "11013", "CFS"): None,
                (2025, "11011", "CFS"): None,
            },
        )
        self.assertEqual(r["status"], "insufficient")
        self.assertIn("no periodic report", r["error"])
        late = [dict(x, rcept_no="20261001000001") for x in dart_rows(2025, "11011")]
        r = kr("2026-09-30", {(2025, "11011", "CFS"): late})
        self.assertEqual(r["missing"], ["cfoTTM", "capexTTM"])
        self.assertIn("not before as_of", r["error"])
        self.assertEqual(r["assets"], 759480516000000)

    def test_mixed_receipts_become_an_error_record(self):
        rows = dart_rows(2026, "11012")
        rows[0]["rcept_no"] = "20260815000000"
        r = kr("2026-09-30", {(2026, "11012", "CFS"): rows})
        self.assertEqual(r["status"], "error")
        self.assertEqual(r["missing"], ["cfoTTM", "capexTTM", "assets"])
        self.assertEqual(len(r["sources"]), 1)

    def test_walk_and_fiscal_year_parsing(self):
        self.assertEqual(
            fx._kr_walk("2026-09-30", 12),
            [
                (2026, "11012", "2026-06-30"),
                (2026, "11013", "2026-03-31"),
                (2025, "11011", "2025-12-31"),
                (2025, "11014", "2025-09-30"),
                (2025, "11012", "2025-06-30"),
            ],
        )
        other = fx._kr_walk("2026-09-30", 3)
        self.assertEqual(
            (other[0], len(other)), ((2027, "11011", None), fx.KR_WALK_OTHER_FYE)
        )
        for value, month in [
            ("12", 12),
            ("1231", 12),
            ("--03-31", 3),
            ("0630", 6),
            (None, 12),
            ("x", 12),
        ]:
            self.assertEqual(fx._fye_month(dict(fiscalYearEnd=value)), month)
        self.assertEqual(
            [fx._amount(x) for x in ["1,234", "-5", "(7)", "", "-", None, "n/a"]],
            [1234, -5, -7, None, None, None, None],
        )


class RetrievalTests(unittest.TestCase):
    def test_dart_reader_stores_only_answers_and_never_the_key(self):
        stored = []

        def store(blob, key, url, provider, suffix):
            stored.append((key, url))
            return manifest(key)

        ok = (FIXTURES / "dart-acnt-00126380-2026-11012-CFS.json").read_bytes()
        empty = (FIXTURES / "dart-acnt-00126380-2026-11014-CFS.json").read_bytes()
        limit = json.dumps(dict(status="020", message="limit")).encode()
        with mock.patch.object(fx, "store", side_effect=store), mock.patch.object(
            fx, "dart_request", side_effect=[ok, empty, limit]
        ) as request:
            report = fx._dart_reports("00126380", online=True)
            rows, _ = report(2026, "11012", "CFS")
            self.assertEqual(len(rows), 10)
            self.assertIsNone(report(2026, "11014", "CFS")[0])
            with self.assertRaisesRegex(FetchError, "status 020"):
                report(2026, "11013", "CFS")
        self.assertEqual(
            [k for k, _ in stored],
            ["dart-acnt-00126380-2026-11012-CFS", "dart-acnt-00126380-2026-11014-CFS"],
        )
        self.assertTrue(
            all("crtfc" not in url and "fs_div=CFS" in url for _, url in stored)
        )
        self.assertEqual(request.call_args_list[0].args[1]["reprt_code"], "11012")
        with mock.patch.object(fx, "store") as store, mock.patch.object(
            fx, "dart_request", return_value=b"<html>maintenance</html>"
        ):
            with self.assertRaisesRegex(FetchError, "non-JSON"):
                fx._dart_reports("00126380", online=True)(2026, "11012", "CFS")
        store.assert_not_called()

    def test_dart_transport_failures_retry_then_fail(self):
        with mock.patch.object(
            fx,
            "dart_request",
            side_effect=RuntimeError("DART x: URLError; request details withheld"),
        ), mock.patch.object(fx.time, "sleep") as sleep:
            with self.assertRaisesRegex(FetchError, "request details withheld"):
                fx._dart_get({})
        self.assertEqual(sleep.call_count, 2)

    def test_dart_offline_reads_latest_stored_original(self):
        blob = (FIXTURES / "dart-acnt-00126380-2026-11014-CFS.json").read_bytes()
        with mock.patch.object(
            fx, "latest", return_value=(blob, manifest("k"))
        ) as latest, mock.patch.object(fx, "dart_request") as request:
            self.assertIsNone(
                fx._dart_reports("00126380", online=False)(2026, "11014", "OFS")[0]
            )
        latest.assert_called_once_with("dart-acnt-00126380-2026-11014-OFS")
        request.assert_not_called()

    def test_collect_online_paths(self):
        with mock.patch.dict(
            os.environ, {"SEC_USER_AGENT": "test test@example.com"}
        ), mock.patch.object(
            fx, "fetch", side_effect=sec_fetch
        ) as fetch, mock.patch.object(
            fx, "latest", side_effect=stored()
        ):
            r = fx.collect(AAPL, date(2026, 9, 30))
        self.assertEqual(r["status"], "ok")
        self.assertEqual(fetch.call_count, 1)  # the stored submissions suffice
        self.assertEqual(
            fetch.call_args.kwargs["headers"]["User-Agent"], "test test@example.com"
        )
        self.assertEqual(
            fetch.call_args.args[0],
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        )
        listing = (copy.deepcopy(LISTING["list"]), [manifest("dart-list")])
        with mock.patch.object(fx, "ensure_dart_key") as key, mock.patch.object(
            fx, "_dart_reports", return_value=reports()
        ) as readers, mock.patch.object(
            fx, "_dart_list", return_value=listing
        ) as lists:
            r = fx.collect(SAMSUNG, {"US": "2026-09-30", "KR": "2026-09-30"})
        key.assert_called_once_with()
        readers.assert_called_once_with("00126380", True)
        lists.assert_called_once_with("00126380", "2026-09-30", True)
        self.assertEqual((r["status"], r["asOf"]), ("ok", "2026-09-30"))

    def test_collect_never_raises_past_the_company(self):
        with mock.patch.object(
            fx, "fetch", side_effect=FetchError("SEC: HTTP 404 for k")
        ):
            r = fx.collect(AAPL, "2026-09-30", online=False)
        self.assertEqual((r["status"], r["error"]), ("error", "SEC: HTTP 404 for k"))
        self.assertEqual(r["missing"], ["cfoTTM", "capexTTM", "assets", "shares"])
        other = (FIXTURES / "sec-facts-CIK0001652044.json").read_bytes()
        with mock.patch.object(fx, "fetch", return_value=(other, manifest("k"))):
            r = fx.collect(AAPL, "2026-09-30", online=False)
        self.assertEqual(r["status"], "error")
        self.assertIn("CIK", r["error"])
        self.assertEqual(len(r["sources"]), 1)
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": ""}):
            self.assertEqual(fx.collect(AAPL, "2026-09-30")["status"], "error")
        self.assertIn(
            "corpCode",
            fx.collect(dict(SAMSUNG, corpCode="126380"), "2026-09-30")["error"],
        )
        self.assertEqual(
            fx.collect(dict(id="x", market="US"), "2026-09-30")["status"], "error"
        )
        self.assertEqual(
            fx.collect(AAPL, "not a date", online=False)["status"], "error"
        )

    def test_rules_are_hashable_for_the_protocol(self):
        self.assertRegex(protocol_hash(fx.RULES), r"^[0-9a-f]{64}$")


def without_filing(path: Path, accession: str) -> bytes:
    """A companyfacts original as if the API had not yet taken in one filing."""
    body = json.loads(path.read_text())
    for tags in body["facts"].values():
        for tag in tags.values():
            for unit, rows in tag["units"].items():
                tag["units"][unit] = [r for r in rows if r["accn"] != accession]
    return json.dumps(body).encode()


def submissions(*rows, cik="0000000001"):
    """A SEC submissions body whose recent filings are (accession, filed, period, form)
    and optionally isXBRL (else 1)."""
    names = ("accessionNumber", "filingDate", "reportDate", "form")
    recent = {name: [row[i] for row in rows] for i, name in enumerate(names)}
    recent["isXBRL"] = [row[4] if len(row) > 4 else 1 for row in rows]
    return dict(cik=cik, filings=dict(recent=recent, files=[]))


class LagTests(unittest.TestCase):
    """The statement API must not trail the periodic filings it is read for."""

    APPLE_Q3 = "0000320193-26-000020"  # 10-Q for 2026-06-27, filed 2026-07-31

    def test_companyfacts_lag_withholds_the_stale_trailing_year(self):
        # Visa 2026-09-30: companyfacts lacked the June 10-Q that submissions listed.
        facts = without_filing(FIXTURES / "sec-facts-CIK0000320193.json", self.APPLE_Q3)
        r = us(AAPL, "2026-09-30", facts=facts)
        self.assertEqual(
            (r["status"], r["issues"]), ("insufficient", ["companyfacts_lag"])
        )
        self.assertEqual((r["cfoTTM"], r["capexTTM"], r["assets"]), (None, None, None))
        self.assertEqual(r["missing"], ["cfoTTM", "capexTTM", "assets"])
        self.assertEqual(
            r["withheld"],
            dict(
                cfoTTM=82627000000 + 111482000000 - 53887000000,
                capexTTM=4344000000 + 12715000000 - 6011000000,
                assets=371082000000,
                periodEnd="2026-03-28",
            ),
        )
        # A share count is not a period value: the cover count stays, as reported.
        self.assertEqual((r["sharesBasis"], r["sharesAsOf"]), ("cover", "2026-04-17"))
        self.assertGreater(r["shares"], 0)
        self.assertTrue(
            r["error"].startswith(
                "companyfacts_lag: 10-Q for 2026-06-27 filed 2026-07-31"
            )
        )
        check = r["lagCheck"]
        self.assertEqual(
            (check["status"], check["latestReport"]["accession"], check["periodEnd"]),
            ("lag", self.APPLE_Q3, "2026-03-28"),
        )
        self.assertEqual(check["retrievedAt"], SUBMISSIONS_RETRIEVED)
        self.assertIn("sec-submissions-0000320193", [m["key"] for m in r["sources"]])
        # The report's own XBRL instance was tried first; offline its index is not
        # stored, which leaves the lag (online a failed retrieval is an error).
        reason = f"No stored original for sec-filing-index-{self.APPLE_Q3}"
        self.assertEqual(
            (check["supplement"]["status"], check["supplement"]["reason"]),
            ("unavailable", reason),
        )
        self.assertIn(f"filing_xbrl_unavailable: {reason}", r["error"])
        # Before the 10-Q was filed the same facts are current.
        r = us(AAPL, "2026-07-31", facts=facts)
        self.assertEqual((r["status"], r["lagCheck"]["status"]), ("ok", "ok"))

    def test_only_original_reports_filed_before_as_of_count(self):
        body = submissions(
            ("0000000001-26-000001", "2026-05-01", "2026-03-31", "10-Q"),
            ("0000000001-26-000002", "2026-08-01", "2026-06-30", "10-Q"),
            ("0000000001-26-000003", "2026-08-20", "2026-09-30", "10-Q/A"),
            ("0000000001-26-000004", "2026-09-29", "2026-09-28", "8-K"),
            ("0000000001-26-000005", "2026-09-30", "2026-09-30", "10-Q"),
            ("0000000001-26-000006", "2026-09-01", "", "10-K"),
        )
        latest = fx._us_latest_report(body, 1, "2026-09-29")
        self.assertEqual(latest["accession"], "0000000001-26-000002")
        self.assertEqual(
            fx._us_latest_report(body, 1, "2026-07-31")["periodEnd"], "2026-03-31"
        )
        self.assertIsNone(fx._us_latest_report(body, 1, "2026-04-30"))
        with self.assertRaisesRegex(ValueError, "CIK"):
            fx._us_latest_report(dict(body, cik="0000000002"), 1, "2026-09-29")
        broken = copy.deepcopy(body)
        broken["filings"]["recent"]["form"].pop()
        with self.assertRaisesRegex(ValueError, "length"):
            fx._us_latest_report(broken, 1, "2026-09-29")

        # Synthetic issuer (H1 10-Q filed 2026-08-01): a date a few days off is no lag.
        def check(period_end, through_as_of="2026-09-30"):
            blob = json.dumps(body).encode()
            with mock.patch.object(
                fx, "latest", return_value=(blob, manifest("s", SUBMISSIONS_RETRIEVED))
            ):
                found, amendments = fx._us_lag(
                    1, through_as_of, period_end, False, None, []
                )
            self.assertEqual(amendments, [])  # the 10-Q/A is for another period
            return found

        self.assertEqual(check("2026-06-30")["status"], "ok")
        self.assertEqual(check("2026-06-27")["status"], "ok")
        self.assertEqual(check("2026-03-31")["status"], "lag")
        self.assertEqual(check(None)["status"], "lag")

    def test_lag_check_needs_a_submissions_original_taken_after_as_of(self):
        r = us(
            AAPL, "2026-09-30", latest=stored(missing={"sec-submissions-0000320193"})
        )
        self.assertEqual((r["status"], r["issues"]), ("ok", ["lag_check_unavailable"]))
        self.assertEqual(r["lagCheck"]["status"], "unavailable")
        self.assertTrue(any("lag check unavailable" in n for n in r["notes"]))
        early = stored(retrieved="2026-09-30T03:59:59+00:00")  # 23:59 New York, T-1
        r = us(AAPL, "2026-09-30", latest=early)
        self.assertEqual(r["issues"], ["lag_check_unavailable"])
        self.assertIn("predates asOf", r["lagCheck"]["detail"])
        r = us(AAPL, "2026-09-30", latest=stored(retrieved="2026-09-30T04:00:00+00:00"))
        self.assertEqual(r["lagCheck"]["status"], "ok")
        # Online, a missing or early original is fetched again; failures are errors.
        with mock.patch.dict(
            os.environ, {"SEC_USER_AGENT": "test test@example.com"}
        ), mock.patch.object(
            fx, "fetch", side_effect=sec_fetch
        ) as fetch, mock.patch.object(
            fx, "latest", side_effect=early
        ):
            r = fx.collect(AAPL, "2026-09-30")
        self.assertEqual((r["status"], r["lagCheck"]["status"]), ("ok", "ok"))
        self.assertEqual(
            fetch.call_args.args[:2],
            (
                "https://data.sec.gov/submissions/CIK0000320193.json",
                "sec-submissions-0000320193",
            ),
        )

        def refuse(url, key, **kwargs):
            if key.startswith("sec-submissions-"):
                raise FetchError(f"SEC: HTTP 503 for {key}")
            return sec_fetch(url, key)

        with mock.patch.dict(
            os.environ, {"SEC_USER_AGENT": "test test@example.com"}
        ), mock.patch.object(fx, "fetch", side_effect=refuse), mock.patch.object(
            fx, "latest", side_effect=stored(missing={"sec-submissions-0000320193"})
        ):
            r = fx.collect(AAPL, "2026-09-30")
        self.assertEqual(
            (r["status"], r["error"]),
            ("error", "SEC: HTTP 503 for sec-submissions-0000320193"),
        )

    def test_dart_api_lag_withholds_the_older_report(self):
        # The half-year report is on the filing list but the statement API answers 013.
        lagging = {(2026, "11012", "CFS"): None, (2026, "11012", "OFS"): None}
        r = kr("2026-09-30", lagging)
        self.assertEqual((r["status"], r["issues"]), ("insufficient", ["dart_api_lag"]))
        self.assertEqual((r["cfoTTM"], r["capexTTM"], r["assets"]), (None, None, None))
        self.assertEqual(
            r["withheld"],
            dict(
                cfoTTM=40274106000000 + 85315148000000 - 16580866000000,
                capexTTM=17127003000000 + 47522179000000 - 12127934000000,
                assets=633339604000000,
                periodEnd="2026-03-31",
            ),
        )
        self.assertTrue(
            r["error"].startswith(
                "dart_api_lag: 반기보고서 (2026.06) filed 2026-08-14 (20260814003699)"
            )
        )
        self.assertEqual(r["lagCheck"]["usedPeriod"], "2026-03")
        # Without the list (offline, nothing stored) the check is reported, not passed.
        r = kr("2026-09-30", lagging, listing=None)
        self.assertEqual((r["status"], r["issues"]), ("ok", ["lag_check_unavailable"]))

    def test_dart_lag_check_matches_the_used_report(self):
        def out(receipt, filed, end=None):
            used = dict(role="latest", rceptNo=receipt, filedAt=filed, report="H1")
            return dict(filings=[dict(used, periodEnd=end)])

        def entry(name, receipt):
            return dict(
                corp_code="00000001",
                report_nm=name,
                rcept_no=receipt,
                rcept_dt=receipt[:8],
            )

        filings = [
            entry("반기보고서 (2026.03)", "20260514000001"),  # a March year end
            entry("[기재정정]반기보고서 (2026.03)", "20260916000001"),
            entry("분기보고서 (2026.06)", "20260814000001"),
            entry("주요사항보고서(자기주식취득결정)", "20260901000001"),
            entry("분기보고서 (2026.09)", "20260930000001"),  # filed on asOf
        ]
        lag = lambda o: fx._kr_lag(o, filings, "00000001", "2026-09-30")  # noqa: E731
        # Statements from the corrected half-year: matched by receipt, a newer quarter.
        check = lag(out("20260916000001", "2026-09-16"))
        self.assertEqual((check["status"], check["usedPeriod"]), ("lag", "2026-03"))
        self.assertEqual(check["latestReport"]["rceptNo"], "20260814000001")
        self.assertEqual(lag(out("20260814000001", "2026-08-14"))["status"], "ok")
        # Unknown period (receipt not listed, non-December year end): any original
        # report filed after the one used is newer.
        self.assertEqual(lag(out("20260101000001", "2026-01-01"))["status"], "lag")
        self.assertEqual(lag(out("20260815000001", "2026-08-15"))["status"], "ok")
        self.assertEqual(lag(dict(filings=[]))["status"], "lag")
        self.assertEqual(
            fx._kr_lag(out("x", "2026-01-01"), [], "00000001", "2026-09-30")["status"],
            "ok",
        )
        with self.assertRaisesRegex(ValueError, "another company"):
            fx._kr_lag(out("x", "2026-01-01"), filings, "00000002", "2026-09-30")

    def test_dart_list_is_paged_stored_without_the_key_and_read_offline(self):
        def page(number, pages, rows):
            return json.dumps(
                dict(status="000", page_no=number, total_page=pages, list=rows)
            ).encode()

        stored_keys = []

        def store(blob, key, url, provider, suffix):
            stored_keys.append((key, url))
            return manifest(key)

        rows = LISTING["list"]
        answers = [page(1, 2, rows[:4]), page(2, 2, rows[4:])]
        with mock.patch.object(fx, "store", side_effect=store), mock.patch.object(
            fx, "dart_request", side_effect=answers
        ) as request:
            filings, manifests = fx._dart_list("00126380", "2026-09-30", True)
        self.assertEqual(filings, rows)
        self.assertEqual(len(manifests), 2)
        params = request.call_args_list[0].args[1]
        self.assertEqual(request.call_args_list[0].args[0], "list.json")
        self.assertEqual(
            (
                params["bgn_de"],
                params["end_de"],
                params["pblntf_ty"],
                params["last_reprt_at"],
            ),
            ("20250826", "20260929", "A", "N"),
        )
        self.assertEqual(
            [k for k, _ in stored_keys],
            ["dart-list-00126380-20260929", "dart-list-00126380-20260929-p2"],
        )
        self.assertTrue(all("crtfc" not in url for _, url in stored_keys))
        none = json.dumps(dict(status="013", message="no data")).encode()
        with mock.patch.object(fx, "store", side_effect=store), mock.patch.object(
            fx, "dart_request", return_value=none
        ):
            self.assertEqual(fx._dart_list("00126380", "2026-09-30", True)[0], [])
        limit = json.dumps(dict(status="020", message="limit")).encode()
        with mock.patch.object(fx, "store") as never, mock.patch.object(
            fx, "dart_request", return_value=limit
        ):
            with self.assertRaisesRegex(FetchError, "status 020"):
                fx._dart_list("00126380", "2026-09-30", True)
        never.assert_not_called()
        with mock.patch.object(
            fx, "latest", side_effect=FetchError("No stored original")
        ) as latest:
            self.assertEqual(fx._dart_list("00126380", "2026-09-30", False), (None, []))
        latest.assert_called_once_with("dart-list-00126380-20260929")

    def test_universe_fetch_error_members_are_insufficient_without_retrieval(self):
        failing = dict(AAPL, issues=[ISSUE], fetchError="submissions_unavailable")
        with mock.patch.object(fx, "fetch") as fetch:
            r = fx.collect(failing, "2026-09-30", online=False)
        fetch.assert_not_called()
        self.assertEqual(
            (r["status"], r["error"], r["issues"]),
            ("insufficient", f"{ISSUE}: submissions_unavailable", [ISSUE]),
        )
        self.assertEqual(r["missing"], ["cfoTTM", "capexTTM", "assets", "shares"])
        korean = dict(
            SAMSUNG, corpCode=None, issues=[ISSUE], fetchError="missing_corp_code"
        )
        with mock.patch.object(fx, "_dart_reports") as readers:
            r = fx.collect(korean, "2026-09-30", online=False)
        readers.assert_not_called()
        self.assertEqual(
            (r["status"], r["missing"]),
            ("insufficient", ["cfoTTM", "capexTTM", "assets"]),
        )


KO_Q2 = "0001628280-26-050503"  # 10-Q for 2026-07-03 filed 2026-07-29, not in facts
KO_Q1 = "0001628280-26-028802"  # 10-Q for 2026-04-03 filed 2026-04-30
KO_10K = "0001628280-26-010047"  # 10-K for 2025 filed 2026-02-20
KO_INDEX = f"sec-filing-index-{KO_Q2}"
KO_XBRL = f"sec-filing-xbrl-{KO_Q2}"
KO_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/21344/000162828026050503/"
# The 2026-10-05 gate checkpoint: companyfacts still ended with the April 10-Q.
KO_WITHHELD = dict(
    cfoTTM=14631000000, capexTTM=2069000000, assets=104217000000, periodEnd="2026-04-03"
)
BE = dict(id="US:0001664703", market="US", ticker="BE", cik="0001664703")
BE_Q2 = "0001628280-26-050247"  # 10-Q for 2026-06-30 filed 2026-07-28, not in facts
BE_Q2A = "0001628280-26-050325"  # its full inline-XBRL 10-Q/A, filed 2026-07-29
BE_10K = "0001628280-26-006516"  # 10-K for 2025 filed 2026-02-09
SYN_A, SYN_Q, SYN_B = (f"0000000001-26-00000{n}" for n in (1, 2, 3))
SYN_B2 = "0000000001-26-000004"  # a 10-Q/A for B's period (2026-06-30)
SYN_A2 = "0000000001-26-000005"  # a Part III 10-K/A for A's period (2025-12-31)
SYN_REPORT = dict(
    accession=SYN_B, form="10-Q", filedAt="2026-08-01", periodEnd="2026-06-30"
)
SYN_CONTEXTS = dict(
    h1=("2026-01-01", "2026-06-30"),
    h1p=("2025-01-01", "2025-06-30"),
    q2=("2026-04-01", "2026-06-30"),
    fy=("2025-01-01", "2025-12-31"),
    jun=("2026-06-30",),
    junp=("2025-06-30",),
    dec=("2025-12-31",),
    cover=("2026-07-25",),
    feb=("2026-02-01",),
)
CFO, CAPEX = (f"us-gaap:{fx.US_CFO[0]}", f"us-gaap:{fx.US_CAPEX[0]}")
COVER, DILUTED = ":".join(fx.COVER), ":".join(fx.DILUTED)
# Synthetic issuer's H1 10-Q (B) as its instance would report it (see synthetic()).
SYN_FACTS = (
    (CFO, "h1", "usd", "0", 600),
    (CFO, "h1p", "usd", "0", 450),
    (CAPEX, "h1", "usd", "0", 170),
    (CAPEX, "h1p", "usd", "0", 140),
    ("us-gaap:Assets", "jun", "usd", "0", 5200),
    ("us-gaap:Assets", "dec", "usd", "0", 5000),
    (COVER, "cover", "shares", "INF", 990_000),
    (DILUTED, "q2", "shares", "0", 1_005_000),
)
# A full 10-Q/A of B (SYN_B2) restating the half-year CFO, capex and total assets.
SYN_RESTATED = (
    (CFO, "h1", "usd", "0", 610),
    (CFO, "h1p", "usd", "0", 450),
    (CAPEX, "h1", "usd", "0", 175),
    (CAPEX, "h1p", "usd", "0", 140),
    ("us-gaap:Assets", "jun", "usd", "0", 5210),
    ("us-gaap:Assets", "dec", "usd", "0", 5000),
    (COVER, "cover", "shares", "INF", 990_000),
    (DILUTED, "q2", "shares", "0", 1_005_000),
)
# The synthetic 10-K (A) as its instance would report it, and a Part III 10-K/A
# (SYN_A2) whose instance tags only its cover (document type, amendment flag).
SYN_ANNUAL = (
    (CFO, "fy", "usd", "0", 1000),
    (CAPEX, "fy", "usd", "0", 300),
    ("us-gaap:Assets", "dec", "usd", "0", 5000),
    (COVER, "feb", "shares", "INF", 1_000_000),
)
SYN_PART_III = (
    '<dei:DocumentType contextRef="fy">10-K/A</dei:DocumentType>'
    '<dei:AmendmentFlag contextRef="fy">true</dei:AmendmentFlag>'
)


def syn_filing(accession, filed, form, rows):
    """companyfacts rows of one synthetic filing from (concept, context, unit,
    decimals, value) instance facts: {concept: [fact, ...]}."""
    out = {}
    for concept, context, unit, decimals, value in rows:
        period = SYN_CONTEXTS[context]
        start, end = period if len(period) == 2 else (None, period[0])
        row = fact(start, end, value, filed, accession, form)
        out.setdefault(concept, []).append(row)
    return out


def with_filings(body, *filings):
    """A companyfacts body with the rows of ``filings`` (syn_filing) appended."""
    body = copy.deepcopy(body)
    for rows in filings:
        for concept, found in rows.items():
            taxonomy, tag = concept.split(":")
            unit = "shares" if "Shares" in tag else "USD"
            entry = body["facts"].setdefault(taxonomy, {}).setdefault(tag, {})
            entry.setdefault("units", {}).setdefault(unit, []).extend(found)
    return body


def ko_index(drop=(), add=(), name=None):
    """The KO filing index.json with listed files removed or added."""
    body = json.loads((FIXTURES / f"{KO_INDEX}.json").read_text())
    items = [i for i in body["directory"]["item"] if i["name"] not in drop]
    body["directory"]["item"] = items + [dict(name=n, type="text.gif") for n in add]
    if name:
        body["directory"]["name"] = name
    return json.dumps(body).encode()


def ko_instance(drop=(), replace=()):
    """The KO instance without the facts ``drop`` lists as (concept, contextRef|None)."""
    text = (FIXTURES / f"{KO_XBRL}.xml").read_text()
    for concept, context in drop:
        only = f'(?=[^>]*contextRef="{context}")' if context else ""
        text, n = re.subn(rf"\s*<{concept}\b{only}[^>]*>[^<]*</{concept}>", "", text)
        assert n, (concept, context)
    for old, new in replace:
        assert old in text, old
        text = text.replace(old, new)
    return text.encode()


def ko_submissions(**changes):
    """A stand-in for latest() serving KO's submissions with the July 10-Q row changed."""
    body = json.loads((FIXTURES / "sec-submissions-0000021344.json").read_text())
    recent = body["filings"]["recent"]
    row = recent["accessionNumber"].index(KO_Q2)
    for column, value in changes.items():
        recent[column][row] = value
    blob = json.dumps(body).encode()
    return lambda key: (blob, manifest(key, SUBMISSIONS_RETRIEVED))


def syn_instance(*facts, cik="0000000001", extra=""):
    """A small instance in the SEC extracted layout: (concept, context, unit, decimals,
    value) facts, a value of None being nil; contexts seg and scn carry a dimension
    (segment, scenario), fvr is forever and dtm has a time of day."""
    ident = (
        f'<xbrli:identifier scheme="http://www.sec.gov/CIK">{cik}</xbrli:identifier>'
    )
    member = (
        '<xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">'
        "syn:AMember</xbrldi:explicitMember>"
    )
    jun = "<xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period>"
    parts = []
    for cid, period in SYN_CONTEXTS.items():
        when = (
            "<xbrli:startDate>{}</xbrli:startDate><xbrli:endDate>{}</xbrli:endDate>"
            if len(period) == 2
            else "<xbrli:instant>{}</xbrli:instant>"
        ).format(*period)
        parts.append(
            f'<xbrli:context id="{cid}"><xbrli:entity>{ident}</xbrli:entity>'
            f"<xbrli:period>{when}</xbrli:period></xbrli:context>"
        )
    parts += [
        f'<xbrli:context id="seg"><xbrli:entity>{ident}<xbrli:segment>{member}'
        f"</xbrli:segment></xbrli:entity>{jun}</xbrli:context>",
        f'<xbrli:context id="scn"><xbrli:entity>{ident}</xbrli:entity>{jun}'
        f"<xbrli:scenario>{member}</xbrli:scenario></xbrli:context>",
        f'<xbrli:context id="fvr"><xbrli:entity>{ident}</xbrli:entity>'
        "<xbrli:period><xbrli:forever/></xbrli:period></xbrli:context>",
        f'<xbrli:context id="dtm"><xbrli:entity>{ident}</xbrli:entity><xbrli:period>'
        "<xbrli:instant>2026-06-30T00:00:00</xbrli:instant></xbrli:period>"
        "</xbrli:context>",
        '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>',
        '<xbrli:unit id="eur"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>',
        '<xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure>'
        "</xbrli:unit>",
    ]
    for concept, context, unit, decimals, value in facts:
        attrs = f'contextRef="{context}" unitRef="{unit}"'
        if value is None:
            parts.append(f'<{concept} {attrs} xsi:nil="true"/>')
        else:
            parts.append(
                f'<{concept} {attrs} decimals="{decimals}">{value}</{concept}>'
            )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<xbrli:xbrl '
        'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
        'xmlns:iso4217="http://www.xbrl.org/2003/iso4217" '
        'xmlns:us-gaap="http://fasb.org/us-gaap/2026" '
        'xmlns:dei="http://xbrl.sec.gov/dei/2026" '
        'xmlns:syn="http://www.example.com/20260630" '
        'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        + extra
        + "".join(parts)
        + "</xbrli:xbrl>\n"
    ).encode()


def syn_index(*names, folder="000000000126000003"):
    items = [dict(name=n, type="text.gif") for n in names]
    directory = dict(item=items, name=f"/Archives/edgar/data/1/{folder}")
    return json.dumps(dict(directory=directory)).encode()


def syn_collect(
    instance,
    as_of="2026-09-30",
    index=None,
    calls=None,
    filings=(),
    originals=None,
    lacking=(SYN_B,),
    online=False,
):
    """The synthetic issuer with companyfacts lacking B (the H1 10-Q), offline.

    ``filings`` are further SEC submissions rows, ``originals`` further served keys,
    ``lacking`` the accessions companyfacts lacks; online uses the stored submissions
    (retrieved after asOf) and fetches only through the patched fetch.
    """
    body = synthetic()
    for tags in body["facts"].values():
        for tag in tags.values():
            for unit, rows in tag["units"].items():
                tag["units"][unit] = [r for r in rows if r["accn"] not in lacking]
    listed = submissions(
        (SYN_A, "2026-02-10", "2025-12-31", "10-K"),
        (SYN_Q, "2026-05-01", "2026-03-31", "10-Q"),
        (SYN_B, "2026-08-01", "2026-06-30", "10-Q"),
        *filings,
    )
    blob = json.dumps(listed).encode()
    served = {
        "sec-facts-CIK0000000001": json.dumps(body).encode(),
        f"sec-filing-index-{SYN_B}": index or syn_index("syn-20260630_htm.xml"),
        f"sec-filing-xbrl-{SYN_B}": instance,
        **(originals or {}),
    }
    agent = {"SEC_USER_AGENT": "test test@example.com"} if online else {}
    with mock.patch.dict(os.environ, agent), mock.patch.object(
        fx, "fetch", side_effect=serve(served, calls)
    ), mock.patch.object(
        fx,
        "latest",
        side_effect=lambda key: (blob, manifest(key, SUBMISSIONS_RETRIEVED)),
    ):
        return fx.collect(SYNTH, as_of, online=online)


def syn_amendment(accession, instance, index=None):
    """Served originals of a synthetic amendment: its index and XBRL instance."""
    folder = accession.replace("-", "")
    return {
        f"sec-filing-index-{accession}": index
        or syn_index("syn-20260630_htm.xml", folder=folder),
        f"sec-filing-xbrl-{accession}": instance,
    }


class FilingXbrlSupplementTests(unittest.TestCase):
    """A report companyfacts lacks is read from its own XBRL instance (us.filingXbrl)."""

    def assertLagStands(self, r, reason):
        """The companyfacts record and its lag, as without the supplement."""
        self.assertEqual(
            (r["status"], r["issues"]), ("insufficient", ["companyfacts_lag"])
        )
        self.assertEqual(r["withheld"], KO_WITHHELD)
        self.assertEqual((r["cfoTTM"], r["capexTTM"], r["assets"]), (None, None, None))
        self.assertEqual((r["shares"], r["sharesAsOf"]), (4302482418, "2026-04-28"))
        check = r["lagCheck"]
        self.assertEqual((check["status"], check["periodEnd"]), ("lag", "2026-04-03"))
        self.assertEqual(
            (check["supplement"]["status"], check["supplement"]["reason"]),
            ("unavailable", reason),
        )
        self.assertEqual(check["supplement"]["accession"], KO_Q2)
        self.assertEqual(
            r["error"],
            f"companyfacts_lag: 10-Q for 2026-07-03 filed 2026-07-29 ({KO_Q2}); "
            f"companyfacts latest period 2026-04-03; filing_xbrl_unavailable: {reason}",
        )
        self.assertNotIn(fx.SUPPLEMENT_ISSUE, r["issues"])

    def test_lagging_companyfacts_is_supplemented_from_the_filing_instance(self):
        # Coca-Cola, gate 2026-10-05: companyfacts ended with the April 10-Q while the
        # July 10-Q and its extracted instance ko-20260703_htm.xml were on EDGAR.
        calls = []
        r = us(KO, "2026-10-05", fetch=serve(calls=calls))
        self.assertEqual((r["status"], r["issues"]), ("ok", [fx.SUPPLEMENT_ISSUE]))
        self.assertEqual((r["periodEnd"], r["method"]), ("2026-07-03", "ytd"))
        # YTD and prior-year YTD from the 10-Q's instance, the annual from companyfacts.
        self.assertEqual(r["cfoTTM"], 7543000000 + 7408000000 - -1391000000)
        self.assertEqual(r["capexTTM"], 684000000 + 2112000000 - 751000000)
        self.assertEqual(r["assets"], 107922000000)
        q2, k = (KO_Q2, "10-Q", "2026-07-29"), (KO_10K, "10-K", "2026-02-20")
        self.assertEqual(
            [
                (c["metric"], c["sign"], c["start"], c["end"], c["value"])
                + (c["accession"], c["form"], c["filedAt"])
                for c in r["components"]
            ],
            [
                ("cfo", 1, "2026-01-01", "2026-07-03", 7543000000) + q2,
                ("cfo", 1, "2025-01-01", "2025-12-31", 7408000000) + k,
                ("cfo", -1, "2025-01-01", "2025-06-27", -1391000000) + q2,
                ("capex", 1, "2026-01-01", "2026-07-03", 684000000) + q2,
                ("capex", 1, "2025-01-01", "2025-12-31", 2112000000) + k,
                ("capex", -1, "2025-01-01", "2025-06-27", 751000000) + q2,
            ],
        )
        self.assertEqual(
            (r["shares"], r["sharesBasis"], r["sharesAsOf"]),
            (4302549243, "cover", "2026-07-27"),
        )
        self.assertEqual([f["accession"] for f in r["filings"]], [KO_10K, KO_Q2])
        self.assertEqual(r["filedAt"], "2026-07-29")
        check = r["lagCheck"]
        self.assertEqual(
            (check["status"], check["periodEnd"], check["detail"]),
            ("ok", "2026-07-03", None),
        )
        self.assertEqual(
            check["supplement"],
            dict(
                status="used",
                accession=KO_Q2,
                form="10-Q",
                filedAt="2026-07-29",
                periodEnd="2026-07-03",
                instance="ko-20260703_htm.xml",
                instancePeriodEnd="2026-07-03",
                facts=13,  # 8 dimensional CommonStockSharesOutstanding left out
                reason=None,
                amendments=[],  # no 10-Q/A for 2026-07-03 before asOf
                companyfactsPeriodEnd="2026-04-03",
            ),
        )
        self.assertEqual(
            [m["key"] for m in r["sources"]],
            [
                "sec-facts-CIK0000021344",
                "sec-submissions-0000021344",
                KO_INDEX,
                KO_XBRL,
            ],
        )
        self.assertEqual(
            [(url, key) for url, key, _ in calls[1:]],
            [
                (KO_ARCHIVE + "index.json", KO_INDEX),
                (KO_ARCHIVE + "ko-20260703_htm.xml", KO_XBRL),
            ],
        )
        self.assertEqual(
            (calls[1][2].get("suffix", ".json"), calls[2][2]["suffix"]),
            (".json", ".xml"),
        )
        self.assertEqual(
            r["notes"],
            [
                f"filing_xbrl_supplement: 10-Q {KO_Q2} for 2026-07-03 filed "
                "2026-07-29 read from its XBRL instance ko-20260703_htm.xml (13 "
                "facts); companyfacts latest period 2026-04-03"
            ],
        )

    def test_online_supplement_is_fetched_with_the_sec_user_agent(self):
        calls = []
        with mock.patch.dict(
            os.environ, {"SEC_USER_AGENT": "test test@example.com"}
        ), mock.patch.object(
            fx, "fetch", side_effect=serve(calls=calls)
        ), mock.patch.object(
            fx, "latest", side_effect=stored()
        ):
            r = fx.collect(KO, "2026-10-05")
        self.assertEqual((r["status"], r["issues"]), ("ok", [fx.SUPPLEMENT_ISSUE]))
        self.assertEqual([key for _, key, _ in calls][1:], [KO_INDEX, KO_XBRL])
        for _, _, kwargs in calls:
            self.assertEqual((kwargs["online"], kwargs["provider"]), (True, "SEC"))
            self.assertEqual(kwargs["headers"]["User-Agent"], "test test@example.com")
        self.assertEqual(calls[2][2]["headers"]["Accept"], "application/xml")

    def test_the_trailing_year_uses_the_supplemented_ytd_period(self):
        # The same numbers as companyfacts holding B: 600 + 1000 - 450 and 170 + 300 -
        # 140 (annual A from companyfacts), assets 5200 and the July cover count.
        full = synth("2026-09-30", synthetic())
        r = syn_collect(syn_instance(*SYN_FACTS))
        self.assertEqual((r["status"], r["issues"]), ("ok", [fx.SUPPLEMENT_ISSUE]))
        fields = ("cfoTTM", "capexTTM", "assets", "shares", "sharesAsOf", "periodEnd")
        self.assertEqual({f: r[f] for f in fields}, {f: full[f] for f in fields})
        self.assertEqual((r["cfoTTM"], r["capexTTM"], r["method"]), (1150, 330, "ytd"))
        self.assertEqual(
            [(c["metric"], c["accession"]) for c in r["components"]],
            [("cfo", SYN_B), ("cfo", SYN_A), ("cfo", SYN_B)]
            + [("capex", SYN_B), ("capex", SYN_A), ("capex", SYN_B)],
        )
        self.assertEqual(r["components"], full["components"])
        self.assertEqual(r["filings"], full["filings"])
        self.assertEqual(
            r["lagCheck"]["supplement"]["companyfactsPeriodEnd"], "2026-03-31"
        )
        # Before B was filed (asOf = its filing date) Q is current and nothing is read.
        calls = []
        r = syn_collect(syn_instance(*SYN_FACTS), as_of="2026-08-01", calls=calls)
        self.assertEqual(
            (r["periodEnd"], r["cfoTTM"], r["issues"]), ("2026-03-31", 1080, [])
        )
        self.assertEqual([key for _, key, _ in calls], ["sec-facts-CIK0000000001"])

    def test_instance_parser_reads_plain_contexts_usd_and_shares_only(self):
        noise = (
            ("us-gaap:Assets", "seg", "usd", "0", 1),  # segment (dimension)
            ("us-gaap:Assets", "scn", "usd", "0", 2),  # scenario
            ("us-gaap:Assets", "fvr", "usd", "0", 3),  # forever
            ("us-gaap:Assets", "dtm", "usd", "0", 4),  # not a plain date
            (CFO, "h1", "eur", "0", 5),  # another currency
            ("us-gaap:PaymentsToAcquireProductiveAssets", "h1", "usd", "0", None),
            ("syn:PaymentsToAcquirePropertyPlantAndEquipment", "h1", "usd", "0", 6),
            ("us-gaap:Revenues", "h1", "usd", "0", 7),  # not a ratings concept
            (CFO, "h1", "usd", "-2", 600),  # an equal duplicate
            (DILUTED, "q2", "shares", "-4", 1_010_000),  # consistent (rounded up)
        )
        facts = fx._instance_facts(syn_instance(*SYN_FACTS, *noise), 1, SYN_REPORT)
        found = sorted(
            (t, c, u, f.get("start", ""), f["end"], f["val"])
            for t, tags in facts.items()
            for c, entry in tags.items()
            for u, rows in entry["units"].items()
            for f in rows
        )

        def expected(concept, context, unit, decimals, value):
            period = SYN_CONTEXTS[context]
            start, end = period if len(period) == 2 else ("", period[0])
            unit = "USD" if unit == "usd" else unit
            return (*concept.split(":"), unit, start, end, value)

        self.assertEqual(found, sorted(expected(*f) for f in SYN_FACTS))
        row = facts["us-gaap"]["Assets"]["units"]["USD"][0]
        self.assertEqual(
            row,
            dict(
                end="2026-06-30", val=5200, accn=SYN_B, form="10-Q", filed="2026-08-01"
            ),
        )
        self.assertIsInstance(row["val"], int)
        for blob, message in (
            (syn_instance(*SYN_FACTS, cik="0000000002"), "another issuer"),
            (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>', "DTD"),
            (b"<html><body>Not Found</body></html>", "not an XBRL instance"),
            (syn_instance((CFO, "h1", "usd", "0", "n/a")), "unreadable value"),
        ):
            with self.assertRaisesRegex(ValueError, message):
                fx._instance_facts(blob, 1, SYN_REPORT)
        # Namespaces bound on nested elements: a footnote's XHTML default namespace
        # and an extension element reusing the us-gaap prefix change nothing; the
        # names of facts and measures resolve through the bindings in scope.
        nested = (
            '<link:footnoteLink xmlns:link="http://www.xbrl.org/2003/linkbase">'
            '<link:footnote><p xmlns="http://www.w3.org/1999/xhtml">note</p>'
            "</link:footnote></link:footnoteLink>"
            '<us-gaap:Assets xmlns:us-gaap="http://example.com/x" contextRef="jun" '
            'unitRef="usd" decimals="0">1</us-gaap:Assets>'
        )
        self.assertEqual(
            fx._instance_facts(syn_instance(*SYN_FACTS, extra=nested), 1, SYN_REPORT),
            fx._instance_facts(syn_instance(*SYN_FACTS), 1, SYN_REPORT),
        )
        other = syn_instance(*SYN_FACTS).replace(
            b'<xbrli:unit id="usd"><xbrli:measure>',
            b'<xbrli:unit id="usd" xmlns:iso4217="http://example.com/iso"><xbrli:measure>',
        )
        found = fx._instance_facts(other, 1, SYN_REPORT)
        units = {
            u for tags in found.values() for e in tags.values() for u in e["units"]
        }
        self.assertEqual(units, {"shares"})  # that "USD" is not ISO 4217's

    def test_consistent_duplicates(self):
        self.assertEqual(
            fx._consistent([(600000000, -6), (600123000, -3)]), [600123000]
        )
        self.assertEqual(fx._consistent([(1005000, 0), (1010000, -4)]), [1005000])
        self.assertEqual(fx._consistent([(1005000, 0), (1000000, -4)]), [1005000])
        self.assertEqual(fx._consistent([(7, math.inf), (7.4, 0)]), [7])
        self.assertEqual(fx._consistent([(3, 0), (3, -6)]), [3])
        self.assertEqual(fx._consistent([(6, -6), (6, None)]), [6])
        for rows in (
            [(600000000, -6), (601000000, -6)],
            [(600, 0), (601, 0)],  # ranges touch at 600.5, the same precision differs
            [(600, 0), (601, 0), (600, -3)],
            [(7, math.inf), (8, math.inf)],
            [(1005000, 0), (1020000, -4)],  # no common point
            [(5, None), (6, 0)],
        ):
            self.assertEqual(fx._consistent(rows), sorted({v for v, _ in rows}))

    def test_inconsistent_duplicates_are_a_conflict_not_a_choice(self):
        twin = (CFO, "h1", "usd", "0", 601)
        r = syn_collect(syn_instance(*SYN_FACTS, twin))
        self.assertEqual(
            (r["status"], r["issues"]), ("insufficient", [fx.SUPPLEMENT_ISSUE])
        )
        self.assertEqual(
            (r["periodEnd"], r["cfoTTM"], r["assets"]), ("2026-06-30", None, 5200)
        )
        self.assertIn("no standard CFO tag reported at 2026-06-30", r["error"])
        self.assertIn(
            "values conflict within one filing: 2026-01-01..2026-06-30", r["notes"]
        )

    def test_instance_listing(self):
        name = lambda *n: fx._instance_name(  # noqa: E731
            json.loads(syn_index(*n)), 1, SYN_B
        )
        linkbases = [f"syn-20100630_{x}.xml" for x in ("cal", "def", "lab", "PRE")]
        self.assertEqual(
            name("syn-20260630.htm", "syn-20260630_htm.xml", "FilingSummary.xml"),
            "syn-20260630_htm.xml",
        )
        plain = name("syn-20100630.xml", "FilingSummary.xml", "syn.xsd", *linkbases)
        self.assertEqual(plain, "syn-20100630.xml")  # before inline XBRL
        for names, message in (
            (("FilingSummary.xml", "syn.xsd", *linkbases), "no XBRL instance listed"),
            (("a_htm.xml", "b_htm.xml"), "2 XBRL instances listed"),
            (("a.xml", "b.xml"), "2 XBRL instances listed"),
            (("../x_htm.xml",), "unexpected instance name"),
        ):
            with self.assertRaisesRegex(ValueError, message):
                name(*names)
        with self.assertRaisesRegex(ValueError, "is for /Archives/edgar/data/1/0"):
            fx._instance_name(json.loads(syn_index("a_htm.xml", folder="0")), 1, SYN_B)
        for index in ({}, [], dict(directory=dict(item=None))):
            with self.assertRaisesRegex(ValueError, "lists no directory"):
                fx._instance_name(index, 1, SYN_B)

    def test_unreadable_filings_leave_companyfacts_lag(self):
        # Offline only originals not stored and content failures occur; both leave
        # the lag (online retrieval failures: test_online_retrieval_failures_...).
        cases = [
            (
                {KO_INDEX: FetchError(f"No stored original for {KO_INDEX}")},
                f"No stored original for {KO_INDEX}",  # offline, nothing stored
                [KO_INDEX],
            ),
            (
                {KO_XBRL: FetchError(f"No stored original for {KO_XBRL}")},
                f"No stored original for {KO_XBRL}",
                [KO_INDEX, KO_XBRL],
            ),
            ({KO_INDEX: b"<html>busy</html>"}, "filing index is not JSON", [KO_INDEX]),
            (
                {KO_INDEX: ko_index(drop=("ko-20260703_htm.xml",))},
                "no XBRL instance listed",
                [KO_INDEX],
            ),
            (
                {KO_INDEX: ko_index(add=("ko-20260703-2_htm.xml",))},
                "2 XBRL instances listed: ko-20260703_htm.xml, ko-20260703-2_htm.xml",
                [KO_INDEX],
            ),
            (
                {KO_INDEX: ko_index(name="/Archives/edgar/data/21344/x")},
                "filing index is for /Archives/edgar/data/21344/x",
                [KO_INDEX],
            ),
            (
                {
                    KO_XBRL: ko_instance(
                        replace=[
                            (">0000021344</identifier>", ">0000021345</identifier>")
                        ]
                    )
                },
                "XBRL instance names another issuer",
                [KO_INDEX, KO_XBRL],
            ),
            (
                {KO_XBRL: ko_instance(drop=[(CFO, None)])},
                "required facts missing: no CFO duration (us-gaap:"
                + ", us-gaap:".join(fx.US_CFO)
                + ")",
                [KO_INDEX, KO_XBRL],
            ),
            (
                {KO_XBRL: ko_instance(drop=[("us-gaap:Assets", "c-25")])},
                "required facts missing: no us-gaap:Assets at 2026-07-03",
                [KO_INDEX, KO_XBRL],
            ),
        ]
        for originals, reason, fetched in cases:
            with self.subTest(reason=reason):
                calls = []
                r = us(KO, "2026-10-05", fetch=serve(originals, calls))
                self.assertLagStands(r, reason)
                self.assertEqual([key for _, key, _ in calls][1:], fetched)
                # Every original read is kept as evidence of the reason.
                failed = {k for k, v in originals.items() if isinstance(v, Exception)}
                self.assertEqual(
                    [m["key"] for m in r["sources"]][2:],
                    [k for k in fetched if k not in failed],
                )
        # SEC submissions mark the report without XBRL: nothing is fetched.
        calls = []
        r = us(
            KO, "2026-10-05", latest=ko_submissions(isXBRL=0), fetch=serve(calls=calls)
        )
        self.assertLagStands(r, "SEC submissions mark the report isXBRL 0")
        self.assertEqual([key for _, key, _ in calls], ["sec-facts-CIK0000021344"])

    def test_instance_period_must_reach_the_report_period(self):
        old = [f for f in SYN_FACTS if f[1] in ("h1p",)] + [
            ("us-gaap:Assets", "junp", "usd", "0", 4900)
        ]
        r = syn_collect(syn_instance(*old))
        self.assertEqual(
            (r["status"], r["issues"]), ("insufficient", ["companyfacts_lag"])
        )
        self.assertEqual(
            r["lagCheck"]["supplement"]["reason"],
            "instance period 2025-06-30 is earlier than the report period 2026-06-30",
        )
        self.assertEqual(r["withheld"]["periodEnd"], "2026-03-31")

    def test_reports_filed_on_or_after_as_of_are_never_read(self):
        calls = []
        r = us(KO, "2026-07-29", fetch=serve(calls=calls))  # the 10-Q's filing date
        self.assertEqual(
            (r["status"], r["issues"], r["periodEnd"]), ("ok", [], "2026-04-03")
        )
        self.assertEqual(r["lagCheck"]["latestReport"]["accession"], KO_Q1)
        self.assertIsNone(r["lagCheck"]["supplement"])
        self.assertEqual([key for _, key, _ in calls], ["sec-facts-CIK0000021344"])
        r = us(KO, "2026-07-30")
        self.assertEqual(
            (r["periodEnd"], r["issues"]), ("2026-07-03", [fx.SUPPLEMENT_ISSUE])
        )
        # The supplement itself refuses a report filed on or after asOf before fetching.
        report = r["lagCheck"]["latestReport"]
        with mock.patch.object(fx, "fetch") as fetch:
            facts, info = fx._us_filing(21344, "2026-07-29", report, False, None, [])
        fetch.assert_not_called()
        self.assertIsNone(facts)
        self.assertEqual(
            (info["status"], info["reason"]),
            ("unavailable", "filed 2026-07-29, not before asOf"),
        )

    def test_a_full_amendment_of_the_report_replaces_its_values(self):
        # Bloom Energy, gate 2026-10-05: companyfacts lacked both its 10-Q for
        # 2026-06-30 (filed 07-28) and the full inline-XBRL 10-Q/A for that period
        # filed the next day. The amendment's values win, as in companyfacts.
        calls = []
        restated = (SYN_B2, "2026-08-02", "2026-06-30", "10-Q/A")
        r = syn_collect(
            syn_instance(*SYN_FACTS),
            filings=[restated],
            originals=syn_amendment(SYN_B2, syn_instance(*SYN_RESTATED)),
            calls=calls,
        )
        self.assertEqual((r["status"], r["issues"]), ("ok", [fx.SUPPLEMENT_ISSUE]))
        self.assertEqual(
            (r["cfoTTM"], r["capexTTM"], r["assets"], r["periodEnd"]),
            (610 + 1000 - 450, 175 + 300 - 140, 5210, "2026-06-30"),
        )
        b2, a = (SYN_B2, "10-Q/A", "2026-08-02"), (SYN_A, "10-K", "2026-02-10")
        self.assertEqual(
            [
                (c["metric"], c["start"], c["end"], c["value"])
                + (c["accession"], c["form"], c["filedAt"])
                for c in r["components"]
            ],
            [
                ("cfo", "2026-01-01", "2026-06-30", 610) + b2,
                ("cfo", "2025-01-01", "2025-12-31", 1000) + a,
                ("cfo", "2025-01-01", "2025-06-30", 450) + b2,
                ("capex", "2026-01-01", "2026-06-30", 175) + b2,
                ("capex", "2025-01-01", "2025-12-31", 300) + a,
                ("capex", "2025-01-01", "2025-06-30", 140) + b2,
            ],
        )
        self.assertEqual([f["accession"] for f in r["filings"]], [SYN_A, SYN_B2])
        self.assertEqual(r["filedAt"], "2026-08-02")
        # The record companyfacts holding both filings would give.
        both = with_filings(
            synthetic(), syn_filing(SYN_B2, "2026-08-02", "10-Q/A", SYN_RESTATED)
        )
        full = synth("2026-09-30", both)
        fields = ("cfoTTM", "capexTTM", "assets", "shares", "sharesAsOf", "periodEnd")
        fields += ("components", "filings", "filedAt", "tags")
        self.assertEqual({f: r[f] for f in fields}, {f: full[f] for f in fields})
        supplement = r["lagCheck"]["supplement"]
        self.assertEqual(
            (supplement["status"], supplement["accession"], supplement["facts"]),
            ("used", SYN_B, 8),
        )
        self.assertEqual(
            supplement["amendments"],
            [
                dict(
                    accession=SYN_B2,
                    form="10-Q/A",
                    filedAt="2026-08-02",
                    status="read",
                    instance="syn-20260630_htm.xml",
                    facts=8,
                    reason=None,
                )
            ],
        )
        b2_keys = [f"sec-filing-index-{SYN_B2}", f"sec-filing-xbrl-{SYN_B2}"]
        self.assertEqual(
            [key for _, key, _ in calls][1:],
            [f"sec-filing-index-{SYN_B}", f"sec-filing-xbrl-{SYN_B}"] + b2_keys,
        )
        self.assertEqual([m["key"] for m in r["sources"]][-2:], b2_keys)
        self.assertEqual(
            r["notes"],
            [
                f"filing_xbrl_supplement: 10-Q {SYN_B} for 2026-06-30 filed 2026-08-01 "
                "read from its XBRL instance syn-20260630_htm.xml (8 facts); amended "
                f"by 10-Q/A {SYN_B2} filed 2026-08-02 (syn-20260630_htm.xml, 8 facts); "
                "companyfacts latest period 2026-03-31"
            ],
        )
        # An amendment restating one period: the others still come from the report.
        r = syn_collect(
            syn_instance(*SYN_FACTS),
            filings=[restated],
            originals=syn_amendment(SYN_B2, syn_instance((CFO, "h1", "usd", "0", 610))),
        )
        self.assertEqual(
            (r["status"], r["cfoTTM"], r["capexTTM"], r["assets"]),
            ("ok", 610 + 1000 - 450, 170 + 300 - 140, 5200),
        )
        self.assertEqual(
            [c["accession"] for c in r["components"]],
            [SYN_B2, SYN_A, SYN_B, SYN_B, SYN_A, SYN_B],
        )
        self.assertEqual([f["accession"] for f in r["filings"]], [SYN_A, SYN_B, SYN_B2])
        self.assertEqual(r["lagCheck"]["supplement"]["amendments"][0]["facts"], 1)

    def test_bloom_energy_reads_the_10q_amendment_filed_the_next_day(self):
        # Gate 2026-10-05, real originals: companyfacts ended with the March 10-Q;
        # the June 10-Q and its 10-Q/A (filed the next day, correcting contexts) were
        # on EDGAR. Their ratings facts agree; per period the 10-Q/A, the later
        # filing, is the one used.
        calls = []
        r = us(BE, "2026-10-05", fetch=serve(calls=calls))
        self.assertEqual((r["status"], r["issues"]), ("ok", [fx.SUPPLEMENT_ISSUE]))
        self.assertEqual((r["periodEnd"], r["method"]), ("2026-06-30", "ytd"))
        self.assertEqual(r["cfoTTM"], 300042000 + 113949000 - -323793000)
        self.assertEqual(r["capexTTM"], 77823000 + 56759000 - 21504000)
        self.assertEqual(r["assets"], 5628401000)
        self.assertEqual(
            (r["shares"], r["sharesBasis"], r["sharesAsOf"]),
            (294527346, "cover", "2026-07-22"),
        )
        amended, annual = (BE_Q2A, "10-Q/A", "2026-07-29"), (
            BE_10K,
            "10-K",
            "2026-02-09",
        )
        self.assertEqual(
            [
                (c["metric"], c["start"], c["end"])
                + (c["accession"], c["form"], c["filedAt"])
                for c in r["components"]
            ],
            [
                ("cfo", "2026-01-01", "2026-06-30") + amended,
                ("cfo", "2025-01-01", "2025-12-31") + annual,
                ("cfo", "2025-01-01", "2025-06-30") + amended,
                ("capex", "2026-01-01", "2026-06-30") + amended,
                ("capex", "2025-01-01", "2025-12-31") + annual,
                ("capex", "2025-01-01", "2025-06-30") + amended,
            ],
        )
        self.assertEqual([f["accession"] for f in r["filings"]], [BE_10K, BE_Q2A])
        supplement = r["lagCheck"]["supplement"]
        self.assertEqual(
            (supplement["accession"], supplement["instance"], supplement["facts"]),
            (BE_Q2, "be-20260630_htm.xml", 13),
        )
        self.assertEqual(
            supplement["amendments"],
            [
                dict(
                    accession=BE_Q2A,
                    form="10-Q/A",
                    filedAt="2026-07-29",
                    status="read",
                    instance="be-20260630_htm.xml",
                    facts=13,
                    reason=None,
                )
            ],
        )
        self.assertEqual(
            [key for _, key, _ in calls][1:],
            [f"sec-filing-{k}-{a}" for a in (BE_Q2, BE_Q2A) for k in ("index", "xbrl")],
        )
        # Without the 10-Q/A row the 10-Q gives the same values under its own filing.
        body = json.loads((FIXTURES / "sec-submissions-0001664703.json").read_text())
        recent = body["filings"]["recent"]
        row = recent["accessionNumber"].index(BE_Q2A)
        for column in recent.values():
            del column[row]
        blob = json.dumps(body).encode()
        alone = us(
            BE,
            "2026-10-05",
            latest=lambda key: (blob, manifest(key, SUBMISSIONS_RETRIEVED)),
        )
        fields = ("cfoTTM", "capexTTM", "assets", "shares", "sharesAsOf", "periodEnd")
        self.assertEqual({f: alone[f] for f in fields}, {f: r[f] for f in fields})
        self.assertEqual([f["accession"] for f in alone["filings"]], [BE_10K, BE_Q2])

    def test_a_part_iii_amendment_adds_nothing(self):
        # The lagging report is the 10-K (A, companyfacts holds nothing filed before
        # asOf); its Part III 10-K/A tags only its cover, so it adds no facts and
        # the record is the one without it.
        annual = {
            f"sec-filing-index-{SYN_A}": syn_index(
                "syn-20251231_htm.xml", folder=SYN_A.replace("-", "")
            ),
            f"sec-filing-xbrl-{SYN_A}": syn_instance(*SYN_ANNUAL),
        }
        part_iii = {
            f"sec-filing-index-{SYN_A2}": syn_index(
                "syn-20251231_htm.xml", folder=SYN_A2.replace("-", "")
            ),
            f"sec-filing-xbrl-{SYN_A2}": syn_instance(extra=SYN_PART_III),
        }
        calls = []
        r = syn_collect(
            None,
            as_of="2026-04-30",
            lacking=(SYN_A, SYN_B),
            filings=[(SYN_A2, "2026-04-20", "2025-12-31", "10-K/A")],
            originals={**annual, **part_iii},
            calls=calls,
        )
        alone = syn_collect(
            None, as_of="2026-04-30", lacking=(SYN_A, SYN_B), originals=annual
        )
        self.assertEqual(
            (r["status"], r["issues"], r["method"], r["periodEnd"]),
            ("ok", [fx.SUPPLEMENT_ISSUE], "annual", "2025-12-31"),
        )
        self.assertEqual(
            (r["cfoTTM"], r["capexTTM"], r["assets"], r["shares"]),
            (1000, 300, 5000, 1_000_000),
        )
        self.assertEqual([f["accession"] for f in r["filings"]], [SYN_A])
        self.assertEqual(
            r["lagCheck"]["supplement"]["amendments"],
            [
                dict(
                    accession=SYN_A2,
                    form="10-K/A",
                    filedAt="2026-04-20",
                    status="read",
                    instance="syn-20251231_htm.xml",
                    facts=0,
                    reason=None,
                )
            ],
        )
        self.assertEqual(
            [key for _, key, _ in calls][1:],
            [f"sec-filing-index-{SYN_A}", f"sec-filing-xbrl-{SYN_A}"]
            + [f"sec-filing-index-{SYN_A2}", f"sec-filing-xbrl-{SYN_A2}"],
        )
        # Apart from naming the amendment it read, the record is the one without it.
        self.assertEqual(alone["lagCheck"]["supplement"]["amendments"], [])
        for record in (r, alone):
            record["lagCheck"]["supplement"].pop("amendments")
            record.update(notes=None, sources=None)
        self.assertEqual(r, alone)

    def test_an_unreadable_amendment_leaves_companyfacts_lag(self):
        restated = (SYN_B2, "2026-08-02", "2026-06-30", "10-Q/A")
        good = syn_instance(*SYN_RESTATED)
        listing = syn_index("FilingSummary.xml", folder=SYN_B2.replace("-", ""))
        missing = f"No stored original for sec-filing-index-{SYN_B2}"  # offline
        cases = [
            (
                syn_amendment(SYN_B2, good, b"<html>busy</html>"),
                "filing index is not JSON",
            ),
            (syn_amendment(SYN_B2, good, listing), "no XBRL instance listed"),
            (
                syn_amendment(SYN_B2, syn_instance(*SYN_RESTATED, cik="0000000002")),
                "XBRL instance names another issuer",
            ),
            ({f"sec-filing-index-{SYN_B2}": FetchError(missing)}, missing),
        ]
        for originals, why in cases:
            with self.subTest(why=why):
                r = syn_collect(good, filings=[restated], originals=originals)
                self.assertEqual(
                    (r["status"], r["issues"]), ("insufficient", ["companyfacts_lag"])
                )
                self.assertEqual(
                    r["withheld"],
                    dict(
                        cfoTTM=1080, capexTTM=330, assets=5100, periodEnd="2026-03-31"
                    ),
                )
                reason = f"amended_by {SYN_B2} unreadable: {why}"
                supplement = r["lagCheck"]["supplement"]
                self.assertEqual(
                    (supplement["status"], supplement["reason"]),
                    ("unavailable", reason),
                )
                # The report itself was read; the amendment is what failed.
                self.assertEqual(
                    (supplement["instance"], supplement["facts"]),
                    ("syn-20260630_htm.xml", 8),
                )
                self.assertEqual(
                    [(x["accession"], x["status"]) for x in supplement["amendments"]],
                    [(SYN_B2, "unreadable")],
                )
                self.assertTrue(
                    r["error"].endswith(f"filing_xbrl_unavailable: {reason}"),
                    r["error"],
                )
                self.assertNotIn(fx.SUPPLEMENT_ISSUE, r["issues"])
        # A failure ends the supplement: amendments not reached stay unread (and are
        # not fetched), also when the report itself could not be read.
        later = ("0000000001-26-000006", "2026-08-03", "2026-06-30", "10-Q/A")
        calls = []
        r = syn_collect(
            good,
            filings=[restated, later],
            originals=syn_amendment(SYN_B2, good, b"<html>busy</html>"),
            calls=calls,
        )
        self.assertEqual(
            [
                (x["accession"], x["status"])
                for x in r["lagCheck"]["supplement"]["amendments"]
            ],
            [(SYN_B2, "unreadable"), (later[0], "unread")],
        )
        self.assertNotIn(f"sec-filing-index-{later[0]}", [k for _, k, _ in calls])
        unstored = f"No stored original for sec-filing-index-{SYN_B}"
        r = syn_collect(
            good,
            filings=[restated],
            originals={f"sec-filing-index-{SYN_B}": FetchError(unstored)},
        )
        supplement = r["lagCheck"]["supplement"]
        self.assertEqual(
            (supplement["reason"], supplement["instance"]), (unstored, None)
        )
        self.assertEqual(
            [(x["accession"], x["status"]) for x in supplement["amendments"]],
            [(SYN_B2, "unread")],
        )

    def test_amendments_read_are_those_of_the_report_filed_before_as_of(self):
        body = submissions(
            (SYN_B, "2026-08-01", "2026-06-30", "10-Q"),
            ("0000000001-26-000011", "2026-07-31", "2026-06-30", "10-Q/A"),  # earlier
            ("0000000001-26-000012", "2026-08-01", "2026-06-30", "10-Q/A"),  # same day
            ("0000000001-26-000013", "2026-08-20", "2026-06-30", "10-K/A"),
            ("0000000001-26-000014", "2026-08-21", "2026-06-30", "10-Q/A", 0),
            ("0000000001-26-000015", "2026-09-30", "2026-06-30", "10-Q/A"),  # on asOf
            ("0000000001-26-000016", "2026-08-22", "2026-03-31", "10-Q/A"),  # Q's
            ("0000000001-26-000017", "2026-08-23", "2026-06-30", "8-K"),
        )
        through = "2026-09-29"  # asOf 2026-09-30
        report = fx._us_latest_report(body, 1, through)
        self.assertEqual(report["accession"], SYN_B)
        self.assertEqual(
            [
                (x["accession"], x["form"], x["isXBRL"])
                for x in fx._us_amendments(body, 1, report, through)
            ],
            [
                ("0000000001-26-000012", "10-Q/A", 1),
                ("0000000001-26-000013", "10-K/A", 1),
                ("0000000001-26-000014", "10-Q/A", 0),
            ],
        )
        self.assertEqual(fx._us_amendments(body, 1, None, through), [])
        # In a record: one marked isXBRL 0 is not read but named; the others are not
        # fetched at all and the report's values stand.
        calls = []
        r = syn_collect(
            syn_instance(*SYN_FACTS),
            filings=[
                (SYN_B2, "2026-08-21", "2026-06-30", "10-Q/A", 0),
                ("0000000001-26-000015", "2026-09-30", "2026-06-30", "10-Q/A"),
                ("0000000001-26-000016", "2026-08-22", "2026-03-31", "10-Q/A"),
            ],
            calls=calls,
        )
        self.assertEqual((r["status"], r["cfoTTM"], r["capexTTM"]), ("ok", 1150, 330))
        self.assertEqual(
            [key for _, key, _ in calls][1:],
            [f"sec-filing-index-{SYN_B}", f"sec-filing-xbrl-{SYN_B}"],
        )
        skipped = "SEC submissions mark it isXBRL 0"
        self.assertEqual(
            r["lagCheck"]["supplement"]["amendments"],
            [
                dict(
                    accession=SYN_B2,
                    form="10-Q/A",
                    filedAt="2026-08-21",
                    status="skipped",
                    instance=None,
                    facts=0,
                    reason=skipped,
                )
            ],
        )
        self.assertIn(
            f"; 10-Q/A {SYN_B2} filed 2026-08-21 not read ({skipped}); ", r["notes"][0]
        )

    def test_online_retrieval_failures_are_errors_collected_again(self):
        # Online, a failed retrieval of the filing index or instance is no lag: the
        # record is an error, which collect retries (HTTP 503 after fetch's retries;
        # 403, SEC's rate-limit answer, and network failures likewise). The real
        # ratings.common.fetch runs against a refusing urlopen; nothing is stored.
        def collect_online(failing, answer):
            keys = []

            def fetch(url, key, **kwargs):
                keys.append(key)
                if key == failing:
                    return common.fetch(url, key, **kwargs)
                return sec_fetch(url, key, **kwargs)

            with mock.patch.dict(
                os.environ, {"SEC_USER_AGENT": "test test@example.com"}
            ), mock.patch.object(fx, "fetch", side_effect=fetch), mock.patch.object(
                fx, "latest", side_effect=stored()
            ), mock.patch.object(
                common, "urlopen", side_effect=answer
            ) as urlopen, mock.patch.object(
                common.time, "sleep"
            ), mock.patch.object(
                common, "store", side_effect=AssertionError("nothing is stored")
            ):
                r = fx.collect(KO, "2026-10-05")
            return r, keys, urlopen.call_count

        for failing in (KO_INDEX, KO_XBRL):
            for answer, error, attempts in (
                (HTTPError(KO_ARCHIVE, 503, "Unavailable", {}, None), "HTTP 503", 4),
                (HTTPError(KO_ARCHIVE, 403, "Forbidden", {}, None), "HTTP 403", 1),
                (URLError("connection reset"), "URLError", 4),
            ):
                with self.subTest(failing=failing, error=error):
                    r, keys, tried = collect_online(failing, answer)
                    self.assertEqual(
                        (r["status"], r["error"]),
                        ("error", f"SEC: {error} for {failing}"),
                    )
                    self.assertEqual(r["missing"], list(fx.REQUIRED["US"]))
                    self.assertEqual((keys[-1], tried), (failing, attempts))
        # An amendment's failed retrieval is an error too.
        failed = f"SEC: HTTP 503 for sec-filing-index-{SYN_B2}"
        r = syn_collect(
            syn_instance(*SYN_FACTS),
            filings=[(SYN_B2, "2026-08-02", "2026-06-30", "10-Q/A")],
            originals={f"sec-filing-index-{SYN_B2}": FetchError(failed)},
            online=True,
        )
        self.assertEqual((r["status"], r["error"]), ("error", failed))
        # Content stays content online: an unreadable index still leaves the lag.
        with mock.patch.dict(
            os.environ, {"SEC_USER_AGENT": "test test@example.com"}
        ), mock.patch.object(
            fx, "fetch", side_effect=serve({KO_INDEX: b"<html>busy</html>"})
        ), mock.patch.object(
            fx, "latest", side_effect=stored()
        ):
            r = fx.collect(KO, "2026-10-05")
        self.assertLagStands(r, "filing index is not JSON")

    def test_absurd_decimals_or_values_do_not_make_an_error(self):
        # decimals far beyond any real fact once overflowed the decimal context and
        # made the record an error; the ranges now use at most DECIMALS_LIMIT places.
        self.assertEqual(fx._consistent([(600, -(10**7)), (601, -(10**7))]), [600, 601])
        self.assertEqual(fx._consistent([(601, -(10**7)), (600, 0)]), [600])
        self.assertEqual(fx._consistent([(7, 10**7), (7.4, 0)]), [7])
        self.assertEqual(fx._consistent([(7, 10**7), (8, 10**7)]), [7, 8])
        vague = (CFO, "h1", "usd", "-1000001", 601)  # agrees with 600 (decimals 0)
        r = syn_collect(syn_instance(*SYN_FACTS, vague))
        self.assertEqual((r["status"], r["cfoTTM"]), ("ok", 1150))
        # A value no float holds makes the instance unreadable (once: an error).
        huge = (CFO, "h1p", "usd", "0", "1" + "0" * 400)
        r = syn_collect(syn_instance(*SYN_FACTS, huge))
        self.assertEqual(
            (r["status"], r["issues"]), ("insufficient", ["companyfacts_lag"])
        )
        self.assertEqual(
            r["lagCheck"]["supplement"]["reason"], f"unreadable value for {CFO} in h1p"
        )

    def test_rules_and_protocol_describe_the_supplement(self):
        source = fx.RULES["us"]["source"]
        self.assertTrue(source.startswith("SEC companyfacts first"))
        self.assertIn("own XBRL instance in the EDGAR archives", source)
        self.assertIn("with every amendment of it filed before asOf", source)
        self.assertIn("companyfacts_lag", source)
        self.assertIn("online retrieval fails the record is an error", source)
        rules = fx.RULES["us"]["filingXbrl"]
        self.assertIn(
            "periods the report does not state still come from companyfacts",
            rules["facts"],
        )
        self.assertIn("different values where one lacks decimals", rules["duplicates"])
        self.assertIn(f"name must match {fx.FILING_INSTANCE}", rules["instance"])
        self.assertIn("amended_by <accession> unreadable", rules["amendments"])
        self.assertIn("Part III 10-K/A", rules["amendments"])
        self.assertEqual(rules["amendmentForms"], ["10-K/A", "10-Q/A"])
        self.assertIn("403", rules["onlineFailure"])
        self.assertEqual(rules["decimalsLimit"], fx.DECIMALS_LIMIT)
        self.assertEqual(fx.RULES["version"], "ratings-v1-fundamentals-4")
        hashed = rating.PROTOCOL["moduleRules"]["fundamentals"]["us"]["filingXbrl"]
        self.assertEqual(hashed, json.loads(json.dumps(rules)))
        text = rating.PROTOCOL["pointInTime"]["fundamentalsSource"]
        for phrase in (
            "companyfacts first",
            "EDGAR archives",
            "every 10-K/A or 10-Q/A for its period",
            "companyfacts_lag",
            "online retrieval failure makes the record an error",
        ):
            self.assertIn(phrase, text)
        self.assertIn("report or amendment", rating.PROTOCOL["pointInTime"]["filings"])
        self.assertEqual(protocol_hash(rating.PROTOCOL), rating.PROTOCOL_HASH)


PPE, PRODUCTIVE, OTHER_PPE = fx.US_CAPEX
TOTAL_CFO, CONTINUING_CFO = fx.US_CFO
MACHINERY = "PaymentsToAcquireMachineryAndEquipment"
EXPLORE = "PaymentsToExploreAndDevelopOilAndGasProperties"
OIL_GAS_PPE = "PaymentsToAcquireOilAndGasPropertyAndEquipment"
OLDER_10Q = "0000000001-25-000003"  # the synthetic issuer's H1 10-Q a year earlier


def regrouped(tag, **rows):
    """synthetic() with its us-gaap ``tag`` rows handed to the named tags: each pick an
    index into synthetic()'s rows (0 annual, 1-2 first quarters, 3-4 half-years) or a
    fact row; ``tag`` keeps only what it is handed itself."""
    body = synthetic()
    usgaap = body["facts"]["us-gaap"]
    old = usgaap.pop(tag)["units"]["USD"]
    for name, picks in rows.items():
        found = [copy.deepcopy(old[p]) if isinstance(p, int) else p for p in picks]
        usgaap[name] = {"units": {"USD": found}}
    return body


def capex_of(r):
    return [(c["tag"], c["value"], c["accession"]) for c in r["components"][3:]]


class TagChainTests(unittest.TestCase):
    """RULES us.cfoTag, capexTag, tagChain and capexUnderstated."""

    def test_capex_tag_switch_between_the_annual_and_quarterly_reports(self):
        # The 10-K tags capex as productive assets, every 10-Q as PP&E (ANET, MAR).
        body = regrouped(PPE, **{PPE: [1, 2, 3, 4], PRODUCTIVE: [0]})
        r = synth("2026-09-30", body)
        self.assertEqual((r["status"], r["capexTTM"]), ("ok", 170 + 300 - 140))
        self.assertEqual(
            capex_of(r),
            [
                (f"us-gaap:{PPE}", 170, SYN_B),
                (f"us-gaap:{PRODUCTIVE}", 300, SYN_A),
                (f"us-gaap:{PPE}", 140, SYN_B),
            ],
        )
        self.assertEqual(r["tags"]["capex"], f"us-gaap:{PPE}, us-gaap:{PRODUCTIVE}")
        self.assertIn(
            f"capex from the tag chain us-gaap:{PPE}, us-gaap:{PRODUCTIVE} (scope not "
            "reconciled)",
            r["notes"],
        )
        # One tag reporting every period stays the rule: nothing changes then.
        self.assertEqual(synth("2026-09-30", synthetic())["tags"]["capex"], CAPEX)

    def test_previous_ytd_comes_from_the_current_ytd_tag(self):
        # PP&E holds the annual and last year's half-year (from that year's 10-Q);
        # the current 10-Q states both half-years as productive assets.
        older = fact("2025-01-01", "2025-06-30", 140, "2025-08-01", OLDER_10Q)
        body = regrouped(PPE, **{PPE: [0, older], PRODUCTIVE: [3, 4]})
        r = synth("2026-09-30", body)
        self.assertEqual((r["status"], r["capexTTM"]), ("ok", 330))
        self.assertEqual(
            capex_of(r),
            [
                (f"us-gaap:{PRODUCTIVE}", 170, SYN_B),
                (f"us-gaap:{PPE}", 300, SYN_A),
                (f"us-gaap:{PRODUCTIVE}", 140, SYN_B),
            ],
        )

    def test_a_tag_reporting_a_period_otherwise_withholds_the_chain(self):
        older = fact("2025-01-01", "2025-06-30", 150, "2025-08-01", OLDER_10Q)
        body = regrouped(PPE, **{PPE: [0, older], PRODUCTIVE: [3, 4]})
        r = synth("2026-09-30", body)
        self.assertEqual((r["status"], r["missing"]), ("insufficient", ["capexTTM"]))
        self.assertEqual(r["cfoTTM"], 1150)
        self.assertIn(
            f"capexTTM: us-gaap:{PPE} reports 2025-01-01..2025-06-30 otherwise than "
            f"us-gaap:{PRODUCTIVE} (tag chain withheld)",
            r["error"],
        )
        self.assertNotIn(fx.CAPEX_UNDERSTATED, r["issues"])

    def test_capex_more_tags_are_read_in_order_after_the_capex_tags(self):
        # DOW: the latest 10-Q moved capex to machinery and equipment; gas field
        # development is a smaller side line of its own.
        side = [
            fact("2025-01-01", "2025-12-31", 25, "2026-02-10", SYN_A, "10-K"),
            fact("2026-01-01", "2026-06-30", 10, "2026-08-01", SYN_B),
            fact("2025-01-01", "2025-06-30", 8, "2026-08-01", SYN_B),
        ]
        body = regrouped(
            PPE, **{PRODUCTIVE: [0, 4], MACHINERY: [0, 3, 4], EXPLORE: side}
        )
        r = synth("2026-09-30", body)
        self.assertEqual((r["status"], r["capexTTM"]), ("ok", 330))
        self.assertEqual(r["tags"]["capex"], f"us-gaap:{MACHINERY}")
        self.assertIn(
            f"capex from fallback tag us-gaap:{MACHINERY} (scope not reconciled)",
            r["notes"],
        )
        # Were the side line listed first, the capex tag stating the annual and last
        # year's half-year otherwise would withhold it rather than take it.
        later = tuple(reversed(fx.US_CAPEX_MORE))
        with mock.patch.object(fx, "US_CAPEX_MORE", later):
            r = synth("2026-09-30", body)
        self.assertEqual((r["capexTTM"], r["missing"]), (None, ["capexTTM"]))
        self.assertIn(
            f"us-gaap:{PRODUCTIVE} reports 2025-01-01..2025-12-31 otherwise than "
            f"us-gaap:{EXPLORE} (tag chain withheld)",
            r["error"],
        )
        # A capex tag reporting every period leaves the capexMore tags unread.
        rows = synthetic()["facts"]["us-gaap"][PPE]["units"]["USD"]
        double = [dict(f, val=2 * f["val"]) for f in rows]
        r = synth("2026-09-30", synthetic(**{f"us-gaap__{MACHINERY}": double}))
        self.assertEqual((r["capexTTM"], r["tags"]["capex"]), (330, CAPEX))

    def test_a_capex_tag_chain_comes_before_a_capex_more_tag(self):
        # A capexMore tag reporting every period (here a side line) never replaces a
        # chain of the capex tags that covers the trailing year.
        side = [
            fact("2025-01-01", "2025-12-31", 25, "2026-02-10", SYN_A, "10-K"),
            fact("2026-01-01", "2026-06-30", 10, "2026-08-01", SYN_B),
            fact("2025-01-01", "2025-06-30", 8, "2026-08-01", SYN_B),
        ]
        improvements = "PaymentsForCapitalImprovements"
        body = regrouped(
            PPE, **{PPE: [1, 2, 3, 4], PRODUCTIVE: [0], improvements: side}
        )
        r = synth("2026-09-30", body)
        self.assertEqual((r["status"], r["capexTTM"]), ("ok", 330))
        self.assertEqual(r["tags"]["capex"], f"us-gaap:{PPE}, us-gaap:{PRODUCTIVE}")

    def test_the_filing_supplement_reads_capex_more_tags(self):
        machinery = f"us-gaap:{MACHINERY}"
        for tag in fx.US_CAPEX_COMPARE:
            self.assertIn(("us-gaap", tag, "USD"), fx.FILING_CONCEPTS)
        rows = [(machinery if c == CAPEX else c, *rest) for c, *rest in SYN_FACTS]
        r = syn_collect(syn_instance(*rows))
        self.assertEqual((r["status"], r["issues"]), ("ok", [fx.SUPPLEMENT_ISSUE]))
        self.assertEqual(r["capexTTM"], 170 + 300 - 140)
        self.assertEqual(
            capex_of(r),
            [(machinery, 170, SYN_B), (CAPEX, 300, SYN_A), (machinery, 140, SYN_B)],
        )
        self.assertEqual(r["lagCheck"]["supplement"]["facts"], len(SYN_FACTS))

    def test_cfo_tag_chain_across_total_and_continuing_operations(self):
        # APD, GEHC: the 10-K tags CFO from continuing operations, every 10-Q the total.
        body = regrouped(TOTAL_CFO, **{TOTAL_CFO: [1, 2, 3, 4], CONTINUING_CFO: [0]})
        r = synth("2026-09-30", body)
        self.assertEqual((r["status"], r["method"]), ("ok", "ytd"))
        self.assertEqual((r["cfoTTM"], r["capexTTM"]), (600 + 1000 - 450, 330))
        names = f"us-gaap:{TOTAL_CFO}, us-gaap:{CONTINUING_CFO}"
        self.assertEqual(r["tags"]["cfo"], names)
        self.assertIn(f"CFO from the tag chain {names}", r["notes"])
        # Both tags stating last year's half-year alike keep the chain...
        same = fact("2025-01-01", "2025-06-30", 450, "2026-08-01", SYN_B)
        body = regrouped(
            TOTAL_CFO, **{TOTAL_CFO: [1, 2, 3, 4], CONTINUING_CFO: [0, same]}
        )
        self.assertEqual(synth("2026-09-30", body)["cfoTTM"], 1150)
        # ...while different values withhold CFO, and capex with it: never mixed.
        body = regrouped(
            TOTAL_CFO,
            **{TOTAL_CFO: [1, 2, 3, 4], CONTINUING_CFO: [0, dict(same, val=440)]},
        )
        r = synth("2026-09-30", body)
        self.assertEqual((r["cfoTTM"], r["capexTTM"]), (None, None))
        self.assertIn(
            f"us-gaap:{CONTINUING_CFO} reports 2025-01-01..2025-06-30 otherwise than "
            f"us-gaap:{TOTAL_CFO} (tag chain withheld)",
            r["error"],
        )
        self.assertIn("capexTTM: no CFO trailing year to align with", r["error"])

    def test_a_larger_capex_category_total_withholds_a_fallback_tag(self):
        # EOG: capex only as other PP&E while oil and gas additions are far larger.
        rows = synthetic()["facts"]["us-gaap"][PPE]["units"]["USD"]
        small = [dict(f, val=f["val"] // 10) for f in rows]
        body = regrouped(PPE, **{OTHER_PPE: small, OIL_GAS_PPE: [0, 1, 2, 3, 4]})
        r = synth("2026-09-30", body)
        self.assertEqual((r["status"], r["missing"]), ("insufficient", ["capexTTM"]))
        self.assertEqual((r["cfoTTM"], r["issues"]), (1150, [fx.CAPEX_UNDERSTATED]))
        self.assertIn(
            f"capexTTM: us-gaap:{OIL_GAS_PPE} reports every trailing period with a "
            "larger total (330 > 33; capex_tag_understated)",
            r["error"],
        )
        # A smaller one leaves the fallback tag's trailing year in place...
        ones = [dict(f, val=1) for f in rows]
        body = regrouped(PPE, **{OTHER_PPE: small, OIL_GAS_PPE: ones})
        r = synth("2026-09-30", body)
        self.assertEqual((r["status"], r["capexTTM"], r["issues"]), ("ok", 33, []))
        # ...and a trailing year wholly from the first capex tag is never compared.
        tenfold = [dict(f, val=10 * f["val"]) for f in rows]
        r = synth("2026-09-30", synthetic(**{f"us-gaap__{OIL_GAS_PPE}": tenfold}))
        self.assertEqual((r["status"], r["capexTTM"]), ("ok", 330))

    def test_conflicting_values_in_one_filing_withhold_a_chain(self):
        # The 10-K states PP&E's annual twice (300 and 310): PP&E drops that period,
        # and the chain that takes it from productive assets is withheld.
        twice = [
            fact("2025-01-01", "2025-12-31", 300, "2026-02-10", SYN_A, "10-K"),
            fact("2025-01-01", "2025-12-31", 310, "2026-02-10", SYN_A, "10-K"),
        ]
        body = regrouped(PPE, **{PPE: [1, 2, 3, 4, *twice], PRODUCTIVE: [0]})
        r = synth("2026-09-30", body)
        self.assertEqual((r["status"], r["missing"]), ("insufficient", ["capexTTM"]))
        self.assertEqual(r["cfoTTM"], 1150)
        self.assertIn(
            f"capexTTM: us-gaap:{PPE} reports 2025-01-01..2025-12-31 otherwise than "
            f"us-gaap:{PRODUCTIVE} (tag chain withheld)",
            r["error"],
        )
        # The same in the CFO chain withholds CFO, and capex with it.
        twice = [dict(f, val=v) for f, v in zip(twice, (1000, 1010))]
        body = regrouped(
            TOTAL_CFO, **{TOTAL_CFO: [1, 2, 3, 4, *twice], CONTINUING_CFO: [0]}
        )
        r = synth("2026-09-30", body)
        self.assertEqual((r["cfoTTM"], r["capexTTM"]), (None, None))
        self.assertIn(
            f"us-gaap:{TOTAL_CFO} reports 2025-01-01..2025-12-31 otherwise than "
            f"us-gaap:{CONTINUING_CFO} (tag chain withheld)",
            r["error"],
        )

    def test_a_chain_holding_pp_and_e_is_compared_too(self):
        # Not taken wholly from PP&E: a larger capex-category total withholds it.
        rows = synthetic()["facts"]["us-gaap"][PPE]["units"]["USD"]
        tenfold = [dict(f, val=10 * f["val"]) for f in rows]
        body = regrouped(
            PPE, **{PPE: [1, 2, 3, 4], PRODUCTIVE: [0], OIL_GAS_PPE: tenfold}
        )
        r = synth("2026-09-30", body)
        self.assertEqual((r["capexTTM"], r["issues"]), (None, [fx.CAPEX_UNDERSTATED]))
        self.assertIn(
            f"capexTTM: us-gaap:{OIL_GAS_PPE} reports every trailing period with a "
            "larger total (3300 > 330; capex_tag_understated)",
            r["error"],
        )

    def test_the_understatement_guard_needs_a_strictly_larger_total(self):
        rows = synthetic()["facts"]["us-gaap"][PPE]["units"]["USD"]
        small = [dict(f, val=f["val"] // 10) for f in rows]  # 17 + 30 - 14 = 33
        equal = copy.deepcopy(small)
        r = synth(
            "2026-09-30", regrouped(PPE, **{OTHER_PPE: small, OIL_GAS_PPE: equal})
        )
        self.assertEqual((r["status"], r["capexTTM"], r["issues"]), ("ok", 33, []))
        above = [dict(f, val=18) if k == 3 else f for k, f in enumerate(equal)]
        r = synth(
            "2026-09-30", regrouped(PPE, **{OTHER_PPE: small, OIL_GAS_PPE: above})
        )
        self.assertEqual((r["capexTTM"], r["issues"]), (None, [fx.CAPEX_UNDERSTATED]))
        self.assertIn("(34 > 33; capex_tag_understated)", r["error"])

    def test_capex_check_comes_before_the_understatement_guard(self):
        # Last year's half-year (35) above last year's annual (30) withholds capex by
        # capexCheck; the larger oil and gas total then adds no understatement issue.
        rows = synthetic()["facts"]["us-gaap"][PPE]["units"]["USD"]
        small = [
            dict(f, val=35 if k == 4 else f["val"] // 10) for k, f in enumerate(rows)
        ]
        body = regrouped(PPE, **{OTHER_PPE: small, OIL_GAS_PPE: [0, 1, 2, 3, 4]})
        r = synth("2026-09-30", body)
        self.assertEqual((r["status"], r["missing"]), ("insufficient", ["capexTTM"]))
        self.assertEqual(r["issues"], [])
        self.assertIn(
            "capexTTM: previous same-length YTD exceeds previous annual "
            "(reclassification or restatement)",
            r["error"],
        )
        self.assertNotIn("capex_tag_understated", r["error"])

    def test_rules_describe_the_tag_chain(self):
        rules = fx.RULES["us"]
        self.assertEqual(
            fx.US_CAPEX_MORE,
            (
                "PaymentsForCapitalImprovements",
                "PaymentsToAcquireMachineryAndEquipment",
                "PaymentsForConstructionInProcess",
                "PaymentsToExploreAndDevelopOilAndGasProperties",
            ),
        )
        self.assertEqual(rules["capexMore"], [f"us-gaap:{t}" for t in fx.US_CAPEX_MORE])
        self.assertEqual(
            rules["capexCompare"], [f"us-gaap:{t}" for t in fx.US_CAPEX_COMPARE]
        )
        self.assertIn("tagChain over cfo", rules["cfoTag"])
        self.assertIn("first capexMore tag reporting every period", rules["capexTag"])
        self.assertIn("from the current YTD's tag", rules["tagChain"])
        self.assertIn("conflicting values in one filing", rules["tagChain"])
        self.assertIn(f"issue {fx.CAPEX_UNDERSTATED}", rules["capexUnderstated"])
        hashed = rating.PROTOCOL["moduleRules"]["fundamentals"]["us"]
        for key in ("cfoTag", "capexMore", "capexTag", "tagChain", "capexUnderstated"):
            self.assertEqual(hashed[key], json.loads(json.dumps(rules[key])))
        self.assertEqual(protocol_hash(rating.PROTOCOL), rating.PROTOCOL_HASH)


class SeparateStatementTests(unittest.TestCase):
    def test_ofs_fallback_is_used_only_when_filed_before_as_of(self):
        # The CFS previous annual is missing and the OFS half-year comes from a filing
        # received after asOf (e.g. a later correction): it must not be used.
        late = [dict(x, rcept_no="20261005000001") for x in dart_rows(2026, "11012")]
        overrides = {
            (2025, "11011", "CFS"): None,
            (2026, "11012", "OFS"): late,
            (2025, "11011", "OFS"): scaled(dart_rows(2025, "11011"), 2),
        }
        calls = []
        r = kr("2026-09-30", overrides, calls=calls)
        self.assertEqual((r["status"], r["fsDiv"]), ("insufficient", "CFS"))
        self.assertEqual(r["missing"], ["cfoTTM", "capexTTM"])
        self.assertIn("OFS 2026 H1 filed 20261005, not before as_of", r["error"])
        self.assertTrue(any("not before as_of; not used" in n for n in r["notes"]))
        self.assertEqual({c["fsDiv"] for c in r["components"]}, set())
        self.assertNotIn((2025, "11011", "OFS"), calls)
        self.assertEqual(r["assets"], 759480516000000)  # the CFS balance sheet stands


if __name__ == "__main__":
    unittest.main()
