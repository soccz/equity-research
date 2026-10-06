"""Filing-bound cash diagnostics for the initial memory-company comparison."""

from __future__ import annotations

from datetime import date
import json
import math
import xml.etree.ElementTree as ET
from .data import ROOT, read_verified, canonical, digest

# Sign is the effect on operating cash, not the taxonomy's raw numeric sign.
US = {
    "da": ("감가상각·무형자산 상각", "DepreciationDepletionAndAmortization", 1),
    "sbc": ("주식보상 비현금 조정", "ShareBasedCompensation", 1),
    "receivables": ("채권 변동의 현금 효과", "IncreaseDecreaseInReceivables", -1),
    "inventory": ("재고 변동의 현금 효과", "IncreaseDecreaseInInventories", -1),
    "payables": (
        "매입채무·미지급비용 효과",
        "IncreaseDecreaseInAccountsPayableAndAccruedLiabilities",
        1,
    ),
    "current_liabilities": (
        "기타 유동부채 효과",
        "IncreaseDecreaseInOtherCurrentLiabilities",
        1,
    ),
    "noncurrent_liabilities": (
        "기타 비유동부채 효과",
        "IncreaseDecreaseInOtherNoncurrentLiabilities",
        1,
    ),
    "other": ("기타 영업현금 조정", "OtherOperatingActivitiesCashFlowStatement", 1),
}
KR = {
    "da": ("감가상각 조정", "AdjustmentsForDepreciationExpense", 1),
    "amortization": ("무형자산 상각 조정", "AdjustmentsForAmortisationExpense", 1),
    "sbc": ("주식보상 비현금 조정", "AdjustmentsForShareBasedPayment", 1),
    "fair_value": (
        "금융자산 평가이익 제거",
        "AdjustmentsForGainsOnEvaluationOfFairValueFinancialAssets",
        -1,
    ),
    "receivables": (
        "매출채권 변동의 현금 효과",
        "AdjustmentsForDecreaseIncreaseInTradeAccountReceivable",
        1,
    ),
    "inventory": (
        "재고 변동의 현금 효과",
        "AdjustmentsForDecreaseIncreaseInInventories",
        1,
    ),
    "payables": (
        "매입채무 변동의 현금 효과",
        "AdjustmentsForIncreaseDecreaseInTradeAccountPayable",
        1,
    ),
    "dividend_adjustment": ("배당수익 비현금 조정", "AdjustmentsForDividendIncome", 1),
    "dividends_received": (
        "실제 받은 배당",
        "DividendsReceivedClassifiedAsOperatingActivities",
        1,
    ),
    "tax_expense": ("법인세비용 되돌림", "AdjustmentsForIncomeTaxExpense", 1),
    "tax_paid": (
        "납부 법인세",
        "IncomeTaxesPaidRefundClassifiedAsOperatingActivities",
        -1,
    ),
}


def select_unique(rows, tag, start, end, accession, unit):
    matches = [
        r
        for r in rows
        if r["tag"].split(":")[-1] == tag
        and r["start"] == start
        and r["end"] == end
        and r["accession"] == accession
        and r["unit"] == unit
    ]
    if not matches:
        return None
    if len({r["value"] for r in matches}) != 1:
        raise ValueError("Conflicting filing facts: " + tag)
    return matches[0]


def source_rows(company):
    """Use only already verified source copies. No model or network call here."""
    if company["id"] == "MU":
        src = next(s for s in company["sources"] if "data.sec.gov" in s["url"])
        obj = json.loads(read_verified(ROOT / src["file"], src["sha256"]))
        if int(obj["cik"]) != company["cik"]:
            raise ValueError("SEC identity mismatch")
        rows = []
        for tag, concept in obj["facts"]["us-gaap"].items():
            if tag not in {v[1] for v in US.values()} | {
                "CommonStockSharesOutstanding",
                "CashAndCashEquivalentsAtCarryingValue",
                "DebtCurrent",
                "LongTermDebtAndCapitalLeaseObligations",
            }:
                continue
            for unit, facts in concept["units"].items():
                for f in facts:
                    if f.get("form") not in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
                        continue
                    rows.append(
                        dict(
                            tag="us-gaap:" + tag,
                            value=f["val"],
                            start=f.get("start"),
                            end=f["end"],
                            filedAt=f["filed"],
                            accession=f["accn"],
                            unit=unit,
                            sourceHash=src["sha256"],
                            sourceUrl=f"https://www.sec.gov/Archives/edgar/data/{company['cik']}/{f['accn'].replace('-', '')}/{f['accn']}-index.html",
                        )
                    )
        return rows
    rows = []
    ns = {"x": "http://www.xbrl.org/2003/instance", "d": "http://xbrl.org/2006/xbrldi"}
    items = json.loads((ROOT / "data/dart-imports.json").read_text())
    wanted = {v[1] for v in KR.values()} | {
        "NumberOfSharesOutstanding",
        "CashAndCashEquivalents",
        "Borrowings",
        "LeaseLiabilities",
    }
    accessions = {
        f["accession"]
        for group in ("current", "previous")
        for f in company["financials"][group].values()
        if f
    }
    for item in items:
        if (
            item["ticker"] != company["id"]
            or item["filing"]["rcept_no"] not in accessions
        ):
            continue
        root = ET.fromstring(read_verified(ROOT / item["file"], item["sha256"]))
        if {e.text for e in root.findall(".//x:identifier", ns)} != {
            company["dartCorpCode"]
        }:
            raise ValueError("DART identity mismatch")
        contexts = {}
        for c in root.findall("x:context", ns):
            dims = [
                (e.get("dimension", "").split(":")[-1], (e.text or "").split(":")[-1])
                for e in c.findall(".//d:explicitMember", ns)
            ]
            allowed = {
                (
                    "ConsolidatedAndSeparateFinancialStatementsAxis",
                    "ConsolidatedMember",
                ),
                (
                    "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis",
                    "ReportedAmountMember",
                ),
                ("ClassesOfShareCapitalAxis", "OrdinarySharesMember"),
            }
            if (
                ("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")
                not in dims
                or not set(dims) <= allowed
                or c.findall(".//d:typedMember", ns)
            ):
                continue
            p = c.find("x:period", ns)
            contexts[c.get("id")] = (
                p.findtext("x:startDate", namespaces=ns),
                p.findtext("x:endDate", namespaces=ns)
                or p.findtext("x:instant", namespaces=ns),
                dims,
            )
        units = {
            u.get("id"): u.findtext("x:measure", namespaces=ns).split(":")[-1]
            for u in root.findall("x:unit", ns)
            if u.find("x:measure", ns) is not None
        }
        for e in root:
            tag = e.tag.split("}")[-1]
            ctx = contexts.get(e.get("contextRef"))
            if (
                tag not in wanted
                or not ctx
                or e.text is None
                or e.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
                in ("true", "1")
            ):
                continue
            # Ordinary-share dimensions may qualify a share count, never a cash-flow amount.
            share_dim = ("ClassesOfShareCapitalAxis", "OrdinarySharesMember") in ctx[2]
            if share_dim != (tag == "NumberOfSharesOutstanding"):
                continue
            value = float(e.text)
            if not math.isfinite(value):
                raise ValueError("Non-finite filing fact")
            rows.append(
                dict(
                    tag=tag,
                    value=value,
                    start=ctx[0],
                    end=ctx[1],
                    unit=units.get(e.get("unitRef")),
                    context=e.get("contextRef"),
                    accession=item["filing"]["rcept_no"],
                    filedAt=date.fromisoformat(item["filing"]["filed_at"]).isoformat(),
                    sourceHash=item["sha256"],
                    sourceUrl=item["filing"]["url"],
                )
            )
    return rows


def cash_bridge(company, rows, period):
    f = company["financials"]
    core = f[period]
    ni = core.get("net_income")
    cfo = core.get("cfo")
    if not ni or not cfo:
        return None
    specs = US if company["market"] == "US" else KR
    parts = [
        dict(
            id="net_income",
            label="순이익",
            value=ni["value"],
            evidence=[ni],
            kind="reported",
        )
    ]
    missing = []
    for key, (label, tag, sign) in specs.items():
        fact = select_unique(
            rows, tag, cfo["start"], cfo["end"], cfo["accession"], company["currency"]
        )
        if fact:
            parts.append(
                dict(
                    id=key,
                    label=label,
                    value=sign * fact["value"],
                    evidence=[fact],
                    kind="reported",
                    sign=sign,
                )
            )
        else:
            missing.append(key)
    residual = cfo["value"] - sum(p["value"] for p in parts)
    # This is an explicit reconciliation remainder, never labelled recurring/noncash/working capital.
    parts.append(
        dict(
            id="residual",
            label="미분해 조정 잔액",
            value=residual,
            evidence=[cfo],
            kind="residual",
        )
    )
    parts.append(
        dict(
            id="cfo",
            label="공시 영업현금",
            value=cfo["value"],
            evidence=[cfo],
            kind="total",
        )
    )
    return dict(
        start=cfo["start"],
        end=cfo["end"],
        parts=parts,
        missing=missing,
        residual=residual,
        residualShare=abs(residual) / max(abs(cfo["value"]), 1),
        reconciled=abs(sum(p["value"] for p in parts[:-1]) - cfo["value"])
        <= max(1, abs(cfo["value"]) * 1e-12),
    )


def price_requirements(market_cap, growth, discount, terminal=0.02, horizon=5):
    """Required base-year cash available to ordinary equity, not reported CFO-capex."""
    if (
        not all(math.isfinite(x) for x in [market_cap, growth, discount, terminal])
        or market_cap <= 0
        or not -0.9 < growth < 1
        or not 0 < discount < 1
        or not -0.1 < terminal < discount
        or type(horizon) is not int
        or not 1 <= horizon <= 30
    ):
        raise ValueError("Invalid discounted-equity-cash assumptions")
    explicit = sum(
        (1 + growth) ** t / (1 + discount) ** t for t in range(1, horizon + 1)
    )
    tail = (
        (1 + growth) ** horizon
        * (1 + terminal)
        / (discount - terminal)
        / (1 + discount) ** horizon
    )
    required = market_cap / (explicit + tail)
    return dict(
        requiredBaseCash=required,
        terminalShare=tail / (explicit + tail),
        presentValue=required * (explicit + tail),
    )


def build(company, as_of):
    if company["id"] not in ("MU", "000660"):
        return None
    rows = [
        r for r in source_rows(company) if r["filedAt"] <= as_of and r["end"] <= as_of
    ]
    current = cash_bridge(company, rows, "current")
    previous = cash_bridge(company, rows, "previous")
    if not current or not current["reconciled"]:
        raise ValueError("Cash bridge unavailable")
    core = company["financials"]["current"]["cfo"]
    end = core["end"]
    acc = core["accession"]
    market = company["market"]
    share_tag = (
        "CommonStockSharesOutstanding"
        if market == "US"
        else "NumberOfSharesOutstanding"
    )
    shares = select_unique(rows, share_tag, None, end, acc, "shares")
    price = company["priceSummary"]
    pricing = None
    if shares and shares["value"] > 0:
        cap = shares["value"] * price["close"]
        pricing = dict(
            shares=shares,
            shareDate=end,
            shareAgeDays=(
                date.fromisoformat(price["lastDate"]) - date.fromisoformat(end)
            ).days,
            close=price["close"],
            priceDate=price["lastDate"],
            marketCapProxy=cap,
            defaults=dict(growth=0.1, discount=0.11, terminal=0.02, horizon=5),
            base=price_requirements(cap, 0.1, 0.11),
            sensitivity=[
                dict(growth=g, discount=k, **price_requirements(cap, g, k))
                for k in [0.08, 0.11, 0.14]
                for g in [0, 0.1, 0.2]
            ],
            limitation="공시 보통주 유통주식수 × 관측 종가. 공시 후 희석·소각·증권 변동 미반영. 요구 현금은 모든 비용·재투자·순차입·비지배지분 등을 반영한 보통주 배분 가능 현금 가정이며 CFO−유형자산 취득과 다르다.",
        )
    balances = []
    tags = [
        (
            "현금·현금성자산",
            (
                "CashAndCashEquivalentsAtCarryingValue"
                if market == "US"
                else "CashAndCashEquivalents"
            ),
        )
    ]
    tags += (
        [
            ("유동 차입금·금융리스", "DebtCurrent"),
            ("비유동 차입금·금융리스", "LongTermDebtAndCapitalLeaseObligations"),
        ]
        if market == "US"
        else [("차입금", "Borrowings"), ("리스부채", "LeaseLiabilities")]
    )
    for label, tag in tags:
        fact = select_unique(rows, tag, None, end, acc, company["currency"])
        if fact:
            balances.append(dict(label=label, fact=fact))
    prev = {p["id"]: p for p in previous["parts"]} if previous else {}
    changes = [
        dict(
            id=p["id"],
            label=p["label"],
            current=p["value"],
            previous=prev[p["id"]]["value"],
            change=p["value"] - prev[p["id"]]["value"],
        )
        for p in current["parts"]
        if p["id"] in prev
    ]
    facts = []
    for period, bridge in [("current", current), ("previous", previous)]:
        if not bridge:
            continue
        revenue = company["financials"][period]["revenue"]
        if (revenue["start"], revenue["end"]) != (bridge["start"], bridge["end"]):
            raise ValueError("Revenue and cash diagnostics must cover the same period")
        facts.append(
            dict(
                id=period + ".revenue",
                label="매출",
                value=revenue["value"],
                unit=revenue["unit"],
                start=revenue["start"],
                end=revenue["end"],
                kind="reported",
                sourceUrl=revenue["sourceUrl"],
            )
        )
        for part in bridge["parts"]:
            facts.append(
                dict(
                    id=period + "." + part["id"],
                    label=part["label"],
                    value=part["value"],
                    unit=company["currency"],
                    start=bridge["start"],
                    end=bridge["end"],
                    kind=part["kind"],
                    sourceUrl=part["evidence"][0]["sourceUrl"],
                )
            )
    return dict(
        version="cash-dossier-v2",
        current=current,
        previous=previous,
        changes=changes,
        pricing=pricing,
        balances=balances,
        evidence=facts,
        evidenceHash=digest(canonical(facts)),
        status="accounting_diagnostics_not_causal_proof",
        boundaries=[
            "수치 분해는 회계 연결이며 사업 원인이나 지속성을 입증하지 않는다.",
            "미분해 잔액을 전부 비현금 또는 운전자본으로 분류하지 않는다.",
            "현금흐름 조정에는 세금·금융자산·배당과 지급 시차가 섞여 있다.",
        ],
    )
