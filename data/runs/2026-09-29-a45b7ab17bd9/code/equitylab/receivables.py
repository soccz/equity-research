"""Traceable receivable balances and collection proxies, never a credit verdict."""

from datetime import date, timedelta
from html.parser import HTMLParser
import json
import math
import xml.etree.ElementTree as ET
from .data import ROOT, canonical, digest, read_verified

NS = {"x": "http://www.xbrl.org/2003/instance", "d": "http://xbrl.org/2006/xbrldi"}
CONSOLIDATED = ("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")
CARRY = "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis"
NUMERIC = {
    "TradeReceivables": "tradeNet",
    "TradeAndOtherReceivables": "totalNet",
}
TEXT = {
    "DescriptionOfTransfersAndRecognitionOfTradeReceivables": (
        "transfers",
        "채권 양도 정책",
        "일부 거래처의 채권은 위험·보상의 대부분을 이전하는 양도 시 장부에서 제거한다고 공시했다. 실제 회수와 양도를 구별할 금액 연결은 별도로 필요하다.",
    ),
    "DescriptionOfObjectivesPoliciesAndProcessesForManagingRisk": (
        "creditPolicy",
        "신용위험 관리 정책",
        "거래처 신용 검토·한도 관리와 해외 거래처 신용보험을 공시했다. 관리 정책의 존재가 실제 회수 성과를 입증하지는 않는다.",
    ),
}


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(text):
    parser = PlainText()
    parser.feed(text)
    return " ".join(" ".join(parser.parts).split())


def contexts(root, currency):
    """Dimension names alone are insufficient: reject segments, separate and typed contexts."""
    result = {}
    units = {
        u.get("id"): u.findtext("x:measure", namespaces=NS).split(":")[-1]
        for u in root.findall("x:unit", NS)
        if u.find("x:measure", NS) is not None
    }
    for ctx in root.findall("x:context", NS):
        dims = {
            (e.get("dimension", "").split(":")[-1], (e.text or "").split(":")[-1])
            for e in ctx.findall(".//d:explicitMember", NS)
        }
        if CONSOLIDATED not in dims or ctx.findall(".//d:typedMember", NS):
            continue
        extra = dims - {CONSOLIDATED}
        roles = {
            frozenset(): "net",
            frozenset({(CARRY, "ReportedAmountMember")}): "net",
            frozenset({(CARRY, "GrossCarryingAmountMember")}): "gross",
            frozenset({(CARRY, "AccumulatedImpairmentMember")}): "allowance",
            frozenset({("TypesOfRisksAxis", "CreditRiskMember")}): "credit",
        }
        role = roles.get(frozenset(extra))
        if not role:
            continue
        period = ctx.find("x:period", NS)
        result[ctx.get("id")] = dict(
            role=role,
            dimensions=sorted(dims),
            start=period.findtext("x:startDate", namespaces=NS),
            end=period.findtext("x:endDate", namespaces=NS)
            or period.findtext("x:instant", namespaces=NS),
        )
    return result, {k for k, v in units.items() if v == currency}


def korean_rows(company, cutoff):
    rows, notes = [], []
    verified = {s["file"]: s["sha256"] for s in company["sources"]}
    for item in json.loads((ROOT / "data/dart-imports.json").read_text()):
        filed = date.fromisoformat(item["filing"]["filed_at"]).isoformat()
        if item["ticker"] != company["id"] or filed > cutoff:
            continue
        if verified.get(item["file"]) != item["sha256"]:
            raise ValueError("Receivable source is outside the frozen company sources")
        root = ET.fromstring(read_verified(ROOT / item["file"], item["sha256"]))
        if {x.text for x in root.findall(".//x:identifier", NS)} != {
            company["dartCorpCode"]
        }:
            raise ValueError("Receivable entity mismatch")
        ctxs, units = contexts(root, company["currency"])
        for e in root:
            tag, ctx = e.tag.split("}")[-1], ctxs.get(e.get("contextRef"))
            if (
                not ctx
                or not e.text
                or e.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
                in ("1", "true")
            ):
                continue
            meta = dict(
                start=ctx["start"],
                end=ctx["end"],
                context=e.get("contextRef"),
                dimensions=ctx["dimensions"],
                tag=tag,
                filedAt=filed,
                accession=item["filing"]["rcept_no"],
                sourceFile=item["file"],
                sourceHash=item["sha256"],
                sourceUrl=item["filing"]["url"],
                unit=company["currency"],
                basis="consolidated",
            )
            if (
                tag in NUMERIC
                and not ctx["start"]
                and e.get("unitRef") in units
                and ctx["role"] != "credit"
            ):
                value = float(e.text)
                if not math.isfinite(value):
                    raise ValueError("Non-finite receivable balance")
                key = (
                    NUMERIC[tag]
                    if ctx["role"] == "net"
                    else NUMERIC[tag].replace("Net", ctx["role"].title())
                )
                rows.append(dict(**meta, key=key, value=value))
            elif tag in TEXT and ctx["start"]:
                key, label, summary = TEXT[tag]
                if (key == "transfers" and ctx["role"] != "net") or (
                    key == "creditPolicy" and ctx["role"] != "credit"
                ):
                    continue
                # Curated paraphrases are only attached when these exact disclosures exist.
                value = plain(e.text)
                anchors = (
                    ["위험과 보상의 대부분", "제거"]
                    if key == "transfers"
                    else ["신용보험", "신용한도"]
                )
                if all(a in value for a in anchors):
                    notes.append(
                        dict(
                            **meta,
                            id=key,
                            label=label,
                            text=summary,
                            kind="disclosed_policy",
                            excerptHash=digest(value.encode()),
                        )
                    )
    return rows, notes


def us_rows(company, cutoff):
    src = next(s for s in company["sources"] if "data.sec.gov" in s["url"])
    obj = json.loads(read_verified(ROOT / src["file"], src["sha256"]))
    if int(obj["cik"]) != company["cik"]:
        raise ValueError("SEC receivable entity mismatch")
    rows = []
    tags = {
        "AccountsReceivableNetCurrent": "tradeNet",
        "ReceivablesNetCurrent": "totalNet",
    }
    for tag, key in tags.items():
        for f in (
            obj["facts"]["us-gaap"]
            .get(tag, {})
            .get("units", {})
            .get(company["currency"], [])
        ):
            if (
                f.get("start")
                or f["filed"] > cutoff
                or f.get("form") not in ("10-K", "10-Q", "10-K/A", "10-Q/A")
            ):
                continue
            if not math.isfinite(f["val"]):
                raise ValueError("Non-finite SEC balance")
            rows.append(
                dict(
                    key=key,
                    value=f["val"],
                    start=None,
                    end=f["end"],
                    tag="us-gaap:" + tag,
                    unit=company["currency"],
                    basis="consolidated",
                    accession=f["accn"],
                    filedAt=f["filed"],
                    sourceFile=src["file"],
                    sourceHash=src["sha256"],
                    sourceUrl=f"https://www.sec.gov/Archives/edgar/data/{company['cik']}/{f['accn'].replace('-', '')}/{f['accn']}-index.html",
                )
            )
    return rows


def select(rows, key, end, cutoff, accession=None):
    values = [
        r
        for r in rows
        if r["key"] == key
        and r["end"] == end
        and r["filedAt"] <= cutoff
        and (accession is None or r["accession"] == accession)
    ]
    if not values:
        return None
    latest = max(r["filedAt"] for r in values)
    values = [r for r in values if r["filedAt"] == latest]
    if len({r["value"] for r in values}) != 1:
        raise ValueError("Conflicting receivable balances: " + key + " " + end)
    return sorted(values, key=lambda r: (r["accession"], r.get("context", "")))[0]


def period_view(revenue, rows, current):
    opening = (date.fromisoformat(revenue["start"]) - timedelta(days=1)).isoformat()
    days = (
        date.fromisoformat(revenue["end"]) - date.fromisoformat(revenue["start"])
    ).days + 1
    # Current balances must come from the same filing. Comparative balances can be
    # in older filings, with each accession retained and no future filing allowed.
    accession = revenue["accession"] if current else None
    points = {}
    for side, end in [("opening", opening), ("closing", revenue["end"])]:
        points[side] = {
            key: select(rows, key, end, revenue["filedAt"], accession)
            for key in ("tradeNet", "totalNet", "tradeGross", "tradeAllowance")
        }
        n, g, a = (
            points[side][k] for k in ("tradeNet", "tradeGross", "tradeAllowance")
        )
        if n and n["value"] < 0:
            raise ValueError("Negative net trade receivables")
        if (
            n
            and g
            and a
            and (
                g["value"] < 0
                or a["value"] > 0
                or abs(g["value"] + a["value"] - n["value"]) > 1
            )
        ):
            raise ValueError("Gross / signed impairment / net do not reconcile")
    start, end = points["opening"]["tradeNet"], points["closing"]["tradeNet"]
    metrics = None
    if start and end and revenue["value"] > 0:
        avg = (start["value"] + end["value"]) / 2
        gross, allowance = (
            points["closing"]["tradeGross"],
            points["closing"]["tradeAllowance"],
        )
        metrics = dict(
            averageNet=avg,
            netChange=end["value"] - start["value"],
            averageDaysProxy=avg / revenue["value"] * days,
            closingDaysProxy=end["value"] / revenue["value"] * days,
            allowanceRate=(
                -allowance["value"] / gross["value"]
                if gross and allowance and gross["value"] > 0
                else None
            ),
        )
    return dict(
        start=revenue["start"],
        end=revenue["end"],
        openingDate=opening,
        days=days,
        revenue=revenue,
        balances=points,
        metrics=metrics,
    )


def sec_note(company, core):
    manifest_path = ROOT / f"data/sources/filing-{core['accession']}.manifest.json"
    if not manifest_path.exists():
        return []
    src = json.loads(manifest_path.read_text())
    if src["cik"] != company["cik"] or src["accession"] != core["accession"]:
        raise ValueError("SEC filing note identity mismatch")
    text = plain(read_verified(ROOT / src["file"], src["sha256"]).decode())
    if not any(s["sha256"] == src["sha256"] for s in company["sources"]):
        company["sources"].append(src)
    anchor = "a significant increase in receivables due to higher revenue"
    if anchor not in text:
        return []
    return [
        dict(
            id="managementExplanation",
            label="경영진의 설명",
            kind="management_attribution",
            text="경영진은 매출 증가에 따른 채권 증가가 영업현금 증가분을 일부 상쇄했다고 설명했다. 이는 회사의 원인 설명이며 회수 지연이 없다는 독립 증거는 아니다.",
            anchor=anchor,
            start=core["start"],
            end=core["end"],
            filedAt=core["filedAt"],
            accession=core["accession"],
            sourceUrl=src["url"],
            sourceFile=src["file"],
            sourceHash=src["sha256"],
        )
    ]


def build(company, cash_bridge, as_of):
    core = company["financials"]["current"]["revenue"]
    cutoff = min(core["filedAt"], as_of)
    if company["market"] == "US":
        rows, notes = us_rows(company, cutoff), sec_note(company, core)
    else:
        rows, notes = korean_rows(company, cutoff)
        notes = [
            n
            for n in notes
            if (n["accession"], n["start"], n["end"])
            == (core["accession"], core["start"], core["end"])
        ]
    periods = {
        key: period_view(company["financials"][key]["revenue"], rows, key == "current")
        for key in ("current", "previous")
    }
    cur, prev = periods["current"], periods["previous"]
    cf = next(p for p in cash_bridge["parts"] if p["id"] == "receivables")
    scope_key = "totalNet" if company["market"] == "US" else "tradeNet"
    start, end = (cur["balances"][s][scope_key] for s in ("opening", "closing"))
    reconciliation = dict(
        scope="유동 채권 전체" if scope_key == "totalNet" else "순매출채권",
        cashEffect=cf["value"],
        cashEvidence=cf["evidence"][0],
        balanceChange=end["value"] - start["value"] if start and end else None,
        unexplainedDifference=(
            cf["value"] + end["value"] - start["value"] if start and end else None
        ),
        limitation="잔액 증가의 음수와 현금흐름 조정액의 차이다. 환율·양도·비현금·범위 차이 중 어느 원인인지 아직 대사하지 않았다.",
    )
    delta = (
        cur["metrics"]["averageDaysProxy"] - prev["metrics"]["averageDaysProxy"]
        if cur["metrics"] and prev["metrics"]
        else None
    )
    gaps = [
        "채권 연령별·연체 구간 잔액을 이 분석에 아직 연결하지 못함",
        "실제 후속 회수와 계약상 결제기일 자료 미확보",
        "기간 내 월별 평균 잔액·신용매출액 미확보",
        "잔액 변화와 현금흐름 조정 차이의 상세 연결 미완료",
    ]
    if not cur["balances"]["closing"]["tradeAllowance"]:
        gaps.append("이번 입력에 매출채권 대손충당금 수치 미확보")
    return dict(
        version="receivables-v1",
        **periods,
        notes=notes,
        reconciliation=reconciliation,
        averageDaysChange=delta,
        missingEvidence=gaps,
        definition="(기초+기말) 순매출채권 ÷ 2 ÷ 같은 기간 총매출 × 실제 기간 일수. 두 시점 평균 대용치이며 실제 회수일수나 연체일수가 아니다.",
        limitations=[
            "총매출을 신용매출 대신 사용한다. 계절성과 기간 말 매출 급증의 영향을 받는다.",
            "기말 잔액 기준 대용치도 함께 표시한다. 두 지표의 차이는 기간 내 잔액 경로를 모른다는 한계를 드러낸다.",
            "전년 비교 잔액은 다른 공시에서 보완될 수 있으며 각 수치의 공시일과 접수번호를 보존한다.",
            "충당금은 예상손실의 회계 추정이며 실제 연체나 회수 성공을 직접 나타내지 않는다.",
        ],
        followUp=[
            dict(
                id="burden",
                question="매출 대비 채권 부담이 계속 커지는가",
                measure="다음 정기공시의 동일 길이 전년 동기 평균 잔액 대용일수 차이",
                rule="차이 > 0이면 부담 증가, ≤ 0이면 증가하지 않음. 회수 지연 판정은 별도.",
                baseline=delta,
                unit="일",
                status="research_condition_not_registered",
            ),
            dict(
                id="credit",
                question="신용 관련 증거도 함께 악화하는가",
                measure="동일 범위 연체 비중·충당금/총매출채권·후속 회수와 양도 금액",
                rule="대용일수 하나로 판정하지 않는다. 연체·회수·회계 추정의 방향을 각각 확인한다.",
                baseline=cur["metrics"]["allowanceRate"] if cur["metrics"] else None,
                unit="ratio",
                status="research_condition_not_registered",
            ),
        ],
    )
