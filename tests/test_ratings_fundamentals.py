"""ratings.fundamentals on trimmed real originals (see fixtures provenance.json), offline.

SEC companyfacts and submissions and OpenDART statements and filing lists are served from
tests/fixtures/ratings/fundamentals; no test reads data/ratings/sources or the network.
"""

import copy
from datetime import date
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from ratings import fundamentals as fx
from ratings.common import FetchError, protocol_hash

FIXTURES = Path(__file__).parent / "fixtures/ratings/fundamentals"
AAPL = dict(id="US:0000320193", market="US", ticker="AAPL", cik=320193)
GOOGL = dict(id="US:0001652044", market="US", ticker="GOOGL", cik="0001652044")
NVDA = dict(id="US:0001045810", market="US", ticker="NVDA", cik=1045810)
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
    return (FIXTURES / f"{key}.json").read_bytes(), manifest(key)


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


def us(member, as_of, facts=None, latest=None):
    fetch = sec_fetch if facts is None else lambda *a, **k: (facts, manifest("facts"))
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
    """A SEC submissions body whose recent filings are (accession, filed, period, form)."""
    names = ("accessionNumber", "filingDate", "reportDate", "form")
    recent = {name: [row[i] for row in rows] for i, name in enumerate(names)}
    recent["isXBRL"] = [1] * len(rows)
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
                return fx._us_lag(1, through_as_of, period_end, False, None, [])

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
