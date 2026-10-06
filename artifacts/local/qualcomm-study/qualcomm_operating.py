"""Qualcomm candidate: chip/licensing pretax profit, investment exclusions and cash."""

import json
from pathlib import Path
from equitylab.data import ROOT, canonical, digest, read_verified
from equitylab.xbrl import company_filing, instance_rows, select
from equitylab.narrative import load, extract

DOCUMENT_ROOT = Path(__file__).resolve().parent
CURRENT = "0000804328-26-000086"
CORPUS = "b47511d1be90d2f4c7cb57d1659c9f36070dbb63f3b84fc8ef4eaaa23abf9ea8"
SOURCE = "97a3896647e1301aaf876ae15c36648b1fad9a1bcba45a07df68486f72570385"
ANNUAL = "0000804328-25-000085"
ANNUAL_SHA = "95e6768ec6e858de8abec345c5cb10c56ae6b3215f17779c7d2be54ac6f93646"
ANNUAL_HTML = "732bbe324f4dc94e5a1d4699f20a438566a9b511714af7ea9b74b7706c475f57"
PRETAX = "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"
RECON = [("ConsolidationItemsAxis", "MaterialReconcilingItemsMember")]
PASSAGES = [
    "d692e2f30522a8f3e125",
    "4f491b4e3a1e5245ff3c",
    "f7e1a2501c78fe33de8e",
    "c451d92f8508cbd904fa",
    "bb94a2dcf72feb635d7f",
    "c60ef66e48a060e1c4cf",
    "8c39fa114012b38da3f2",
    "adab6b860882c74c37b9",
    "433008fdf20706ad11c7",
    "dfceee45e0ffdeb55b58",
    "9c22d382fb5363dc7fb5",
    "cf528d439863140a3c32",
    "57bc513b7aec6d0d83d5",
    "87af72a89ebd8bdcb297",
]
CASH = [
    ("IncomeLossFromContinuingOperations", "연결 계속영업 순이익", 1),
    ("DepreciationDepletionAndAmortization", "감가상각·무형상각", 1),
    (
        "IncomeTaxProvisionLessThanInExcessOfIncomeTaxPayments",
        "법인세비용−실제 납부",
        1,
    ),
    ("ShareBasedCompensation", "주식보상 되돌림", 1),
    ("GainLossOnInvestments", "투자 순이익 제거", -1),
    (
        "ImpairmentLossesOnOtherInvestmentsWithoutReadilyDeterminableFairValue",
        "기타 투자 손상",
        1,
    ),
    ("OtherNoncashIncomeExpense", "기타 비현금 순이익 제거", -1),
    ("IncreaseDecreaseInReceivables", "채권 현금 효과", -1),
    ("IncreaseDecreaseInInventories", "재고 현금 효과", -1),
    ("IncreaseDecreaseInOtherOperatingAssets", "기타 영업자산", -1),
    ("IncreaseDecreaseInAccountsPayableTrade", "매입채무", 1),
    ("IncreaseDecreaseInAccruedLiabilities", "급여·복리후생·기타 부채", 1),
    ("IncreaseDecreaseInDeferredRevenue", "선수 수익", 1),
]
COSTS = [
    ("CostOfRevenue", "미배분 매출원가", 1),
    ("ResearchAndDevelopmentExpense", "미배분 연구개발", 1),
    ("SellingGeneralAndAdministrativeExpense", "미배분 판매관리", 1),
    ("OtherOperatingIncomeExpenseNet", "미배분 기타 비용", -1),
    ("InterestExpense", "미배분 이자", 1),
]


def build(c, as_of):
    from equitylab.operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="Qualcomm의 QCT·QTL 세전이익, 전략투자와 미배분 비용·법인세·인수 범위를 새 원문에서 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    a = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}-xbrl.manifest.json").read_text()
    )
    h = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}.manifest.json").read_text()
    )
    if (
        source["sha256"] != SOURCE
        or a["sha256"] != ANNUAL_SHA
        or h["sha256"] != ANNUAL_HTML
        or a["cik"] != c["cik"]
        or as_of < "2026-07-29"
    ):
        raise ValueError("Qualcomm source identity or timing changed")
    annual = instance_rows(
        read_verified(DOCUMENT_ROOT / a["file"], ANNUAL_SHA), c, a, ANNUAL, "2025-11-05"
    )
    f = c["financials"]
    periods = [
        (1, annual, "2024-09-30", "2025-09-28"),
        (1, rows, f["start"], f["end"]),
        (-1, rows, f["priorStart"], f["priorEnd"]),
    ]
    if [(s, e) for _, _, s, e in periods][1:] != [
        ("2025-09-29", "2026-06-28"),
        ("2024-09-30", "2025-06-29"),
    ]:
        raise ValueError("Qualcomm fiscal windows changed")

    def exact(rs, tag, start, end, dims=()):
        x = select(rs, tag, start, end, dims, "USD")
        if x is None:
            raise ValueError("Qualcomm fact missing " + tag + " " + end)
        return x

    def combined(tag, dims=()):
        parts = [
            dict(coefficient=k, fact=exact(rs, tag, s, e, dims))
            for k, rs, s, e in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            sourceUrl=source["primaryUrl"],
            unit="USD",
        )

    facts = {
        key: combined(tag)
        for key, tag in dict(
            revenue="Revenues",
            pretax=PRETAX,
            operatingIncome="OperatingIncomeLoss",
            interestExpense="InterestExpense",
            tax="IncomeTaxExpenseBenefit",
            netIncome="IncomeLossFromContinuingOperations",
            cfo="NetCashProvidedByUsedInOperatingActivities",
            da="DepreciationDepletionAndAmortization",
            sbc="ShareBasedCompensation",
            ppe="PaymentsToAcquireProductiveAssets",
            acquisitionAndInvestments="AcquisitionsAndOtherInvestmentsNetofCashAcquired",
        ).items()
    }
    v = lambda k: facts[k]["value"]
    segments = []
    for member, label in [
        ("QctMember", "QCT · 반도체"),
        ("QtlMember", "QTL · 특허 라이선스"),
        ("AllOtherSegmentsMember", "비보고 사업 · 데이터센터·QGOV 등"),
    ]:
        dims = [
            (
                "ConsolidationItemsAxis",
                (
                    "MaterialReconcilingItemsMember"
                    if member == "AllOtherSegmentsMember"
                    else "OperatingSegmentsMember"
                ),
            ),
            ("StatementBusinessSegmentsAxis", member),
        ]
        rev = combined(
            "Revenues" if member == "AllOtherSegmentsMember" else REVENUE, dims
        )
        profit = combined(PRETAX, dims)
        segments.append(
            dict(
                id=member,
                label=label,
                revenue=rev["value"],
                margin=profit["value"] / rev["value"],
                minMargin=-1.5 if member == "AllOtherSegmentsMember" else -0.5,
                observedGrowth=rev["components"][1]["fact"]["value"]
                / rev["components"][2]["fact"]["value"]
                - 1,
                evidence=[rev, profit],
            )
        )
    qsi_dims = [
        ("ConsolidationItemsAxis", "OperatingSegmentsMember"),
        ("StatementBusinessSegmentsAxis", "QsiMember"),
    ]
    qsi = combined(PRETAX, qsi_dims)
    qsi_cost = combined("OperatingExpenses", qsi_dims)
    qsi_investment = combined("NonoperatingIncomeExpense", qsi_dims)
    unallocated_revenue = combined(
        "Revenues", RECON + [("LitigationCaseAxis", "LicensingAgreementsMember")]
    )
    unallocated_investment = combined("InvestmentIncomeNonoperating", RECON)
    cost_terms = [
        dict(label=label, coefficient=sign, fact=combined(tag, RECON))
        for tag, label, sign in COSTS
    ]
    gross_corporate = sum(t["coefficient"] * t["fact"]["value"] for t in cost_terms)
    if unallocated_revenue["value"] != 0:
        raise ValueError(
            "Unallocated Qualcomm licensing settlement requires separate future revenue treatment"
        )
    future_corporate = gross_corporate + qsi_cost["value"]
    excluded = qsi_investment["value"] + unallocated_investment["value"]
    research_pretax = (
        sum(s["evidence"][1]["value"] for s in segments) - future_corporate
    )
    if abs(v("pretax") - excluded - research_pretax) > 1:
        raise ValueError("Qualcomm future investment exclusion mismatch")
    checks = []
    for i, (_, rs, start, end) in enumerate(periods):
        parts = [
            dict(
                label=label,
                value=sign * (fct := exact(rs, tag, start, end))["value"],
                fact=fct,
            )
            for tag, label, sign in CASH
        ]
        if i == 0:
            imp = exact(rs, "AssetImpairmentCharges", start, end)
            parts.append(dict(label="연간 영업자산 손상", value=imp["value"], fact=imp))
        else:
            eq = exact(rs, "IncomeLossFromEquityMethodInvestments", start, end)
            parts.append(
                dict(label="누적 지분법 순이익 제거", value=-eq["value"], fact=eq)
            )
        cash = sum(x["value"] for x in parts)
        rev = sum(s["evidence"][0]["components"][i]["fact"]["value"] for s in segments)
        pre = sum(s["evidence"][1]["components"][i]["fact"]["value"] for s in segments)
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        component = lambda fact: fact["components"][i]["fact"]["value"]
        cost = sum(t["coefficient"] * component(t["fact"]) for t in cost_terms)
        recon_pre = (
            pre
            + component(qsi)
            + component(unallocated_revenue)
            - cost
            + component(unallocated_investment)
        )
        if (
            cash != val("cfo")
            or rev + component(unallocated_revenue) != val("revenue")
            or recon_pre != val("pretax")
            or val("pretax") - val("tax") != val("netIncome")
        ):
            raise ValueError(
                "Qualcomm source-period cash or pretax reconciliation failed " + end
            )
        checks.append(
            dict(
                start=start,
                end=end,
                parts=parts,
                reportedCfo=cash,
                residual=0,
                revenueResidual=0,
                incomeResidual=0,
                segmentRevenue=rev,
                unallocatedRevenue=component(unallocated_revenue),
                reportedPretax=val("pretax"),
                tax=val("tax"),
                netIncome=val("netIncome"),
                taxCashAdjustment=parts[2]["value"],
            )
        )
    bridge_parts = []
    for j, (tag, label, sign) in enumerate(CASH):
        parts = [
            dict(coefficient=k * sign, fact=checks[i]["parts"][j]["fact"])
            for i, (k, _, _, _) in enumerate(periods)
        ]
        bridge_parts.append(
            dict(
                label=label,
                value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
                fact=dict(components=parts, sourceUrl=source["primaryUrl"]),
            )
        )
    tail = [
        dict(
            coefficient=k * (1 if i == 0 else -1),
            fact=checks[i]["parts"][-1]["fact"],
        )
        for i, (k, _, _, _) in enumerate(periods)
    ]
    bridge_parts.append(
        dict(
            label="연간 영업자산 손상·누적 지분법 제거의 기간 연결",
            value=sum(p["coefficient"] * p["fact"]["value"] for p in tail),
            fact=dict(components=tail, sourceUrl=source["primaryUrl"]),
        )
    )
    if sum(x["value"] for x in bridge_parts) != v("cfo"):
        raise ValueError("Qualcomm TTM cash mismatch")
    stock = [
        dict(coefficient=k, label=label, fact=exact(rows, tag, None, f["end"]))
        for k, label, tag in [
            (1, "매출·기타 순채권", "AccountsAndOtherReceivablesNetCurrent"),
            (1, "재고", "InventoryNet"),
            (-1, "매입채무", "AccountsPayableCurrent"),
            (-1, "유동 선수수익", "DeferredRevenueCurrent"),
            (-1, "장기 선수수익", "DeferredRevenueNoncurrent"),
        ]
    ]
    working = sum(t["coefficient"] * t["fact"]["value"] for t in stock)
    rev = v("revenue")
    reinvestment = v("ppe") + v("acquisitionAndInvestments")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.25,
        netInterest=0,
        depreciation=v("da") / rev,
        workingCapital=working / rev,
        capexStart=reinvestment / rev,
        capexEnd=reinvestment / rev,
        leaseStart=0,
        leaseEnd=0,
        discount=0.12,
        terminal=0.02,
        corporateStart=future_corporate / rev,
        corporateEnd=future_corporate / rev,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    ps = [index[p] for p in PASSAGES]
    aps = extract(read_verified(DOCUMENT_ROOT / h["file"], ANNUAL_HTML))
    hist = [
        dict(p, sourceUrl=h["url"], sourceHash=ANNUAL_HTML)
        for p in aps
        if p["ordinal"] in list(range(748, 766)) + [1083]
    ]
    for s in [
        a,
        h,
        dict(a["indexSource"], provider="SEC", retrievedAt=a["retrievedAt"]),
    ]:
        read_verified(DOCUMENT_ROOT / s["file"], s["sha256"])
        if s["file"] not in {x["file"] for x in c["sources"]}:
            c["sources"].append(s)
    m = dict(
        status="research_workspace",
        version="qualcomm-core-pretax-cash-v1",
        sourcePeriod=["2025-06-30", f["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        basisLabel="칩·라이선스 세전이익 / 투자수익 분리",
        groupLabel="공시 사업·비보고 사업",
        marginLabel="세전이익률",
        growthLabel="같은9개월 누적 대비",
        pretaxPath=True,
        unallocatedPath=True,
        corporateLabel="미배분 비용·이자·QSI 운영비",
        netInterestLabel="추가 순이자 (미배분 비용 포함·0 고정)",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        capexLabel="설비·인수·기타 투자 현금",
        leaseLabel="금융리스 원금 가정",
        intro="QCT 반도체와 QTL 특허 라이선스, 데이터센터·정부 사업 등을 구분합니다. 보고 세전이익과 주식보상·인수비용을 포함한 미배분 항목을 대사하고 전략투자·미배분 투자수익의 반복은 미래 초기 가정에서 제외합니다.",
        businessCaption="QCT와 QTL은 서로 다른 사업입니다. 비보고 사업은 데이터센터·QGOV 등의 묶음이며 데이터센터 단독 손익이 아닙니다. 매출이 없는 QSI 전략투자의 이익을 칩·라이선스 마진에 섞지 않습니다. 부문 수치는 세전이익이며 미래 비용에 이자가 이미 포함돼 추가 순이자를 허용하지 않습니다.",
        anchorSummary="기말 매출·기타 순채권+재고−매입채무−유동·장기 선수수익을 최근1년 매출로 나눈 비율을 미래 증가 매출의 자금 소요로 가정합니다. 기타 채권이 섞인 잔액 대용이며 실제 회수일수가 아닙니다. 세율25%·금융리스0은 명시적 가정이고 실제 금융리스 지급0 확인은 아닙니다.",
        bridge=dict(
            parts=bridge_parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=None,
        ),
        anchors=dict(
            workingStockTerms=stock,
            workingStockNet=working,
            actualFinanceLeasePayment=None,
            shareCompensationReplacement=v("sbc"),
        ),
        qualcommEvidence=dict(
            reportedPretax=v("pretax"),
            excludedQsiInvestment=qsi_investment,
            excludedUnallocatedInvestment=unallocated_investment,
            researchPretax=research_pretax,
            reportedOperatingAfterInterest=v("operatingIncome") - v("interestExpense"),
            remainingAllocatedDifference=research_pretax
            - (v("operatingIncome") - v("interestExpense")),
            qsiOperatingCost=qsi_cost,
            costTerms=cost_terms,
            unallocatedRevenue=unallocated_revenue,
            workingStockTerms=stock,
            workingStockNet=working,
            periods=checks,
        ),
        cashAnchors=[
            dict(
                label=label,
                period="최근1년",
                value=value,
                sourceUrl=source["primaryUrl"],
                scope=scope,
            )
            for label, value, scope in [
                ("감가·무형상각", v("da"), "인수 무형상각을 포함한 비용 되돌림"),
                ("설비 현금 지출", v("ppe"), "공시 capital expenditures"),
                (
                    "기업 인수·기타 투자",
                    v("acquisitionAndInvestments"),
                    "두 범주를 공시가 합산함. 전체를 설비나 순수 기업 인수로 재명명하지 않음",
                ),
                (
                    "주식보상 현금표 되돌림",
                    v("sbc"),
                    "미래 비용에는 유지하며 되돌리지 않음",
                ),
                (
                    "전체 금융리스 원금",
                    None,
                    "자료 미확인. 기본0은 실제 지급0 확인이 아님",
                ),
            ]
        ],
        passages=ps,
        historicalPassages=hist,
        observedResidualLabel="인수·기타 투자 및 금융리스·부채 상환 범위 추가 검토",
        rules=[
            "연간+현재9개월−전년9개월로 연결하고 매출·세전이익·세금·현금을 세 기간 각각 대사합니다. 연간 영업자산 손상과 반기 지분법 조정의 별도 행을 임의로 같은 항목으로 바꾸지 않습니다.",
            "QSI와 미배분 투자수익을 미래 반복 이익에서 제외하되 QSI 운영비는 유지합니다. 별도 투자자산의 가치를 자동으로 더하지 않습니다. 부문 세전이익의 나머지 배분 차이는 보존하며 연결 영업이익으로 바꾸지 않습니다.",
            "이자가 이미 미배분 비용에 포함됩니다. 과거 비용의 반복은 현재 부채 만기별 차환을 완료한 분석이 아니며 원금 상환은 별도로 검토합니다.",
            "주식보상은 부문·미배분 비용 안에 남겨 두고 되돌리지 않습니다. 실제 자기주식 매입과 주식보상 대체액을 중복 차감하지 않습니다.",
            "소송 합의 라이선스 매출은 연간·전년 누적에서 상쇄된 최근1년 금액0을 확인했습니다. 과거 기간에 합의가 없었다는 뜻이 아닙니다.",
            "공시된 인수·기타 투자 합산 현금을 초기 재투자에 유지하며 투자증권 수익과 회수 전망으로 상계하지 않습니다.",
            "법인세 혜택·평가충당금 변동을 미래 세율로 자동 반복하지 않습니다. 장기 세율25%는 승인된 정상세율이 아닌 연구 가정입니다.",
        ],
        remaining=[
            "핸드셋 수요·고객 자체칩·라이선스 체결과 회수",
            "데이터센터 인수 후 비용·매출·사업별 구분",
            "반복 설비 투자와 인수·기타 투자 분리",
            "세금 정상화·부채 만기·금융리스·금융자산 배분",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m


if __name__ == "__main__":
    c = json.loads((DOCUMENT_ROOT / "company-start.json").read_text())
    m = build(c, "2026-09-29")
    (DOCUMENT_ROOT / "candidate-operating-model.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=2)
    )
    print(m["initial"]["years"][0]["cash"], m["bridge"]["reportedCfo"])
