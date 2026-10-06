"""Exact-receipt share-class evidence from the official DART shares table."""

from datetime import datetime, timezone
import json
import os
import re
from .data import ROOT, canonical, digest, read_verified
from .dart import request

GUIDE = "https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS002&apiId=2020002"


def collect(company):
    f = company["financials"]
    end = f["end"]
    accession = f["current"]["cfo"]["accession"]
    params = dict(
        corp_code=company["dartCorpCode"],
        bsns_year=end[:4],
        reprt_code={"03": "11013", "06": "11012", "09": "11014", "12": "11011"}[
            end[5:7]
        ],
    )
    blob = request("stockTotqySttus.json", params)
    key = os.environ.get("DART_API_KEY", "")
    if key and key.encode() in blob:
        raise ValueError("Credential in response; content withheld")
    body = json.loads(blob)
    if body.get("status") != "000":
        raise ValueError("DART shares status " + str(body.get("status")))
    sha = digest(blob)
    path = ROOT / "data/sources" / f"shares-{company['id']}-{accession}-{sha[:16]}.json"
    path.write_bytes(blob)
    src = dict(
        provider="OpenDART",
        file=str(path.relative_to(ROOT)),
        sha256=sha,
        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={accession}",
        api="https://opendart.fss.or.kr/api/stockTotqySttus.json",
        guide=GUIDE,
        accession=accession,
        company=company["id"],
        params=params,
        retrievedAt=datetime.now(timezone.utc).isoformat(),
    )
    # Validate identity before installing a source manifest. Failed responses
    # stay archived but can never enter price calculations.
    parse(company, body, src)
    manifest = (
        ROOT / "data/sources" / f"shares-{company['id']}-{accession}.manifest.json"
    )
    manifest.write_bytes(canonical(src))
    return src


def number(value):
    if not isinstance(value, str) or not re.fullmatch(r"[\d,]+", value.strip()):
        return None
    return int(value.replace(",", ""))


def parse(c, body, source, xbrl_rows=()):
    f = c["financials"]
    accession = f["current"]["cfo"]["accession"]
    rows = body.get("list", [])
    if not rows or any(
        r.get("corp_code") != c["dartCorpCode"]
        or r.get("rcept_no") != accession
        or r.get("stlm_dt") != f["end"]
        for r in rows
    ):
        raise ValueError("Share table issuer, receipt or closing date mismatch")
    classes, issues = [], []
    totals = [r for r in rows if re.sub(r"\s", "", r["se"]) in ("合計", "합계", "계")]
    total = totals[0] if len(totals) == 1 else {}
    aggregate_labels = ("合計", "합계", "비고", "계")
    class_rows = [r for r in rows if re.sub(r"\s", "", r["se"]) not in aggregate_labels]
    # A dash remains missing. A complete aggregate can nevertheless show that
    # the reported common shares exhaust both issued and outstanding totals.
    aggregate_complete = all(
        number(total.get(k)) is not None
        and number(total.get(k)) == sum(number(r.get(k)) or 0 for r in class_rows)
        for k in ["istc_totqy", "distb_stock_co"]
    )
    common_dimensions = [
        ("ClassesOfShareCapitalAxis", "OrdinarySharesMember"),
        ("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember"),
    ]
    common_evidence = [
        r
        for r in xbrl_rows
        if r["accession"] == accession
        and r["end"] == f["end"]
        and r["start"] is None
        and r["unit"] == "shares"
        and r["dimensions"] == common_dimensions
        and r["tag"] in ("NumberOfSharesIssued", "NumberOfSharesOutstanding")
    ]
    for r in rows:
        label = re.sub(r"\s", "", r["se"])
        if label in aggregate_labels:
            continue
        values = {
            k: number(r.get(k)) for k in ["istc_totqy", "tesstk_co", "distb_stock_co"]
        }
        if (
            all(v is not None for v in values.values())
            and values["istc_totqy"] - values["tesstk_co"] != values["distb_stock_co"]
        ):
            raise ValueError("Issued minus treasury shares does not reconcile")
        common = label in (
            "보통주",
            "보통주식",
            "기명식보통주",
            "기명식보통주식",
            "의결권있는주식(보통주)",
        )
        proof = []
        # Voting rights alone do not establish a common-share class. Require
        # both issued and outstanding amounts to match exact ordinary-share
        # XBRL contexts, and the table to exhaust the issuer's share totals.
        if label == "의결권있는주식" and aggregate_complete:
            proof = [
                r
                for r in common_evidence
                if r["value"]
                == values[
                    (
                        "istc_totqy"
                        if r["tag"] == "NumberOfSharesIssued"
                        else "distb_stock_co"
                    )
                ]
            ]
            common = {r["tag"] for r in proof} == {
                "NumberOfSharesIssued",
                "NumberOfSharesOutstanding",
            }
            if not common:
                proof = []
        other_has_shares = values["distb_stock_co"] not in (None, 0)
        other_unknown = values["distb_stock_co"] is None and not aggregate_complete
        if not common and (other_has_shares or other_unknown):
            issues.append(label + "의 현금·청산 권리와 보통주 배분 확인 필요")
        fact = dict(
            value=values["distb_stock_co"],
            unit="shares",
            start=None,
            end=f["end"],
            filedAt=f["filedAt"],
            accession=accession,
            tag="OpenDART:distb_stock_co",
            dimensions=[["공시 주식 종류", r["se"]]],
            sourceUrl=source["url"],
            sourceFile=source["file"],
            sourceHash=source["sha256"],
            issued=values["istc_totqy"],
            treasury=values["tesstk_co"],
            definition="공시 유통주식수 (발행주식수−자기주식수)",
        )
        classes.append(
            dict(label=r["se"], common=common, fact=fact, classEvidence=proof)
        )
    common = [r["fact"] for r in classes if r["common"]]
    if len(common) != 1 or common[0]["value"] is None or common[0]["value"] <= 0:
        issues.append("공시 보통주 유통주식수 미확인")
    return dict(
        classes=classes,
        issues=issues,
        aggregateComplete=aggregate_complete,
        aggregate=total,
        shares=(
            common[0]
            if len(common) == 1
            and common[0]["value"] is not None
            and common[0]["value"] > 0
            else None
        ),
        source=source,
    )


def load(c, as_of, xbrl_rows=None):
    if c["market"] != "KR" or c["financials"]["filedAt"] > as_of:
        return None
    accession = c["financials"]["current"]["cfo"]["accession"]
    path = ROOT / "data/sources" / f"shares-{c['id']}-{accession}.manifest.json"
    if not path.exists():
        return None
    src = json.loads(path.read_text())
    if src["company"] != c["id"] or src["accession"] != accession:
        raise ValueError("Share source manifest identity mismatch")
    body = json.loads(read_verified(ROOT / src["file"], src["sha256"]))
    if xbrl_rows is None:
        from .xbrl import company_filing

        _, xbrl_rows = company_filing(c, as_of)
    result = parse(c, body, src, xbrl_rows)
    if src["file"] not in {s["file"] for s in c["sources"]}:
        c["sources"].append(src)
    return result
