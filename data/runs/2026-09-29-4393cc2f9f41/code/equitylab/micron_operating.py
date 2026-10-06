"""Micron's recast segments and tax-aware cash path, with explicit annual anchors."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract
from .operating_model import calculate

ANNUAL_ROOT = ROOT
CURRENT = "0000723125-26-000015"
ANNUAL = "0000723125-25-000028"
CORPUS = "f786d3bea1848df0beeb3e46a866aaadf7fbcd5a3614a4f3651b66f664f2112a"
CURRENT_SHA = "de68a2e57df77b0b26d9af3a0f5494aa821ffc927685dd535ccae5b8193203e2"
ANNUAL_SHA = "d4eede66eac20393a3c93849bdd72477dd977d59e36d8e742381d1da6e393ed8"
ANNUAL_HTML = "8c2010f3c838747c2fec10b261a78e85ca10fe5b240f0e15c8a8a9d960f169bc"
ROLES = [
    ("NetIncomeLoss", "연결 순이익", 1),
    ("DepreciationDepletionAndAmortization", "감가상각·무형상각", 1),
    ("ShareBasedCompensation", "주식보상 되돌림", 1),
    ("IncreaseDecreaseInReceivables", "채권 변동", -1),
    ("IncreaseDecreaseInInventories", "재고 변동", -1),
    (
        "IncreaseDecreaseInAccountsPayableAndAccruedLiabilities",
        "매입채무·미지급비용 변동",
        1,
    ),
    ("IncreaseDecreaseInOtherCurrentLiabilities", "기타 유동부채 변동", 1),
    ("OtherOperatingActivitiesCashFlowStatement", "기타 영업현금 조정", 1),
]
TAGS = dict(
    cfo="NetCashProvidedByUsedInOperatingActivities",
    revenue="RevenueFromContractWithCustomerExcludingAssessedTax",
    operatingIncome="OperatingIncomeLoss",
    pretax="IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    tax="IncomeTaxExpenseBenefit",
    netIncome="NetIncomeLoss",
    equityIncome="IncomeLossFromEquityMethodInvestments",
    depreciationAmortization="DepreciationDepletionAndAmortization",
    sbc="ShareBasedCompensation",
    interestIncome="InvestmentIncomeNet",
    interestExpense="InterestExpenseNonoperating",
    capex="PaymentsToAcquirePropertyPlantAndEquipment",
    governmentIncentives="ProceedsFromGovernmentAssistance",
)


def build(c, as_of):
    h = c.get("segmentHistory") or {}
    if (
        c["id"] != "MU"
        or c.get("narrative", {}).get("accession") != CURRENT
        or c.get("narrative", {}).get("evidenceHash") != CORPUS
        or h.get("status") != "ready"
    ):
        return dict(
            status="source_review_required",
            reason="Micron의 부문 재작성·세금·정부지원·리스 범위 검토가 필요합니다.",
        )
    source, current = company_filing(c, as_of)
    annual_source = h["review"]["annualSource"]
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if (
        source["sha256"] != CURRENT_SHA
        or annual_source["sha256"] != ANNUAL_SHA
        or core["accession"] != ANNUAL
        or core["filedAt"] > as_of
    ):
        raise ValueError("Micron source identity changed")
    annual = instance_rows(
        read_verified(ANNUAL_ROOT / annual_source["file"], ANNUAL_SHA),
        c,
        annual_source,
        ANNUAL,
        core["filedAt"],
    )
    f = c["financials"]
    periods = [
        (1, annual, core["start"], core["end"]),
        (1, current, f["start"], f["end"]),
        (-1, current, f["priorStart"], f["priorEnd"]),
    ]
    if [(p[2], p[3]) for p in periods] != [
        ("2024-08-30", "2025-08-28"),
        ("2025-08-29", "2026-05-28"),
        ("2024-08-30", "2025-05-29"),
    ]:
        raise ValueError("Micron source periods changed")

    def exact(rows, tag, start, end):
        fact = select(
            [r for r in rows if r["decimals"] == "-6"], tag, start, end, (), "USD"
        )
        if fact is None:
            raise ValueError("Micron missing exact fact: " + tag)
        return fact

    def combine(tag):
        parts = [
            dict(coefficient=sign, fact=exact(rows, tag, start, end))
            for sign, rows, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            sourceUrl=source["primaryUrl"],
            start=h["start"],
            end=h["end"],
            unit="USD",
            derived=True,
        )

    facts = {k: combine(tag) for k, tag in TAGS.items()}
    v = lambda k: facts[k]["value"]
    bridge_parts = []
    checks = []
    current_parts = []
    for i, (sign, rows, start, end) in enumerate(periods):
        # Annual Other is aggregate; the two nine-month statements separately
        # disclose noncurrent liabilities. Do not invent an annual zero.
        roles = ROLES + (
            [("IncreaseDecreaseInOtherNoncurrentLiabilities", "기타 장기부채 변동", 1)]
            if i
            else []
        )
        parts = [
            dict(
                label=label,
                value=coefficient * exact(rows, tag, start, end)["value"],
                fact=exact(rows, tag, start, end),
                tag=tag,
                coefficient=coefficient,
            )
            for tag, label, coefficient in roles
        ]
        reported = exact(rows, TAGS["cfo"], start, end)["value"]
        residual = reported - sum(p["value"] for p in parts)
        ni = (
            exact(rows, TAGS["pretax"], start, end)["value"]
            - exact(rows, TAGS["tax"], start, end)["value"]
            + exact(rows, TAGS["equityIncome"], start, end)["value"]
        )
        if residual or ni != exact(rows, TAGS["netIncome"], start, end)["value"]:
            raise ValueError("Micron period cash or income reconciliation failed")
        checks.append(
            dict(
                start=start,
                end=end,
                coefficient=sign,
                reportedCfo=reported,
                residual=residual,
                incomeResidual=0,
                parts=parts,
            )
        )
        if i == 1:
            current_parts = parts
        for p in parts:
            group = (
                "other"
                if p["tag"]
                in (
                    "OtherOperatingActivitiesCashFlowStatement",
                    "IncreaseDecreaseInOtherNoncurrentLiabilities",
                )
                else p["tag"]
            )
            item = next((r for r in bridge_parts if r["tag"] == group), None)
            if item is None:
                item = dict(
                    tag=group,
                    label=(
                        "기타 영업현금·장기부채 조정(연간 통합·9개월 분리)"
                        if group == "other"
                        else p["label"]
                    ),
                    value=0,
                    components=[],
                )
                bridge_parts.append(item)
            item["value"] += sign * p["value"]
            item["components"].append(
                dict(coefficient=sign * p["coefficient"], fact=p["fact"])
            )
    if sum(p["value"] for p in bridge_parts) != v("cfo"):
        raise ValueError("Micron trailing cash bridge failed")
    for part in bridge_parts:
        part["fact"] = dict(
            value=part["value"],
            sourceUrl=source["primaryUrl"],
            start=h["start"],
            end=h["end"],
            unit="USD",
            derived=True,
            components=part.pop("components"),
        )
    revenue = v("revenue")
    recon = h["reconciliations"]["operatingIncome"]
    corporate = -recon["adjustment"]
    if (
        corporate < 0
        or recon["subtotal"] - corporate != v("operatingIncome")
        or sum(s["revenue"]["value"] for s in h["segments"]) != revenue
    ):
        raise ValueError("Micron segment reconciliation failed")
    business = {s["id"]: s for s in c["business"]["segments"]}
    segments = [
        dict(
            id=s["id"],
            label=s["label"],
            revenue=s["revenue"]["value"],
            margin=s["margin"],
            observedGrowth=business[s["id"]]["current"]["revenue"]["value"]
            / business[s["id"]]["previous"]["revenue"]["value"]
            - 1,
            evidence=[
                p["fact"]
                for p in s["revenue"]["components"] + s["operatingIncome"]["components"]
            ],
        )
        for s in h["segments"]
    ]
    annual_ppe = select(
        [r for r in annual if r["decimals"] == "-7"],
        "Depreciation",
        core["start"],
        core["end"],
        (),
        "USD",
    )
    if annual_ppe is None:
        raise ValueError("Micron annual PPE depreciation missing")
    annual_da = exact(
        annual, TAGS["depreciationAmortization"], core["start"], core["end"]
    )
    annual_lease = exact(
        annual, "FinanceLeasePrincipalPayments", core["start"], core["end"]
    )
    annual_revenue = exact(annual, TAGS["revenue"], core["start"], core["end"])
    # Estimation belongs to the assumption, never to the observed fact record.
    depreciation_assumption = (
        v("depreciationAmortization") * annual_ppe["value"] / annual_da["value"]
    )
    wc_tags = {
        "IncreaseDecreaseInReceivables",
        "IncreaseDecreaseInInventories",
        "IncreaseDecreaseInAccountsPayableAndAccruedLiabilities",
        "IncreaseDecreaseInOtherCurrentLiabilities",
    }
    working = sum(p["value"] for p in current_parts if p["tag"] in wc_tags)
    growth = sum(
        b["current"]["revenue"]["value"] - b["previous"]["revenue"]["value"]
        for b in business.values()
    )
    if growth <= 0:
        raise ValueError("Review Micron capital driver when revenue contracts")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=facts["tax"]["components"][1]["fact"]["value"]
        / facts["pretax"]["components"][1]["fact"]["value"],
        netInterest=(v("interestIncome") - v("interestExpense")) / revenue,
        depreciation=depreciation_assumption / revenue,
        workingCapital=-working / growth,
        capexStart=v("capex") / revenue,
        capexEnd=v("capex") / revenue,
        leaseStart=annual_lease["value"] / annual_revenue["value"],
        leaseEnd=annual_lease["value"] / annual_revenue["value"],
        discount=0.11,
        terminal=0.02,
        corporateStart=corporate / revenue,
        corporateEnd=corporate / revenue,
    )
    corpus = load(c)
    by = {p["ordinal"]: p for p in corpus["passages"]}
    if not all(
        text in by[i]["text"]
        for i, text in [
            (337, "$422 million"),
            (344, "$5.79 billion"),
            (344, "$648 million"),
            (488, "$27 billion"),
            (487, "clawback"),
        ]
    ):
        raise ValueError("Micron funding context changed")
    manifest = json.loads(
        (ANNUAL_ROOT / f"data/sources/filing-{ANNUAL}.manifest.json").read_text()
    )
    if (
        manifest["sha256"] != ANNUAL_HTML
        or manifest["accession"] != ANNUAL
        or manifest["cik"] != 723125
    ):
        raise ValueError("Micron annual cash anchor source changed")
    annual_passages = extract(
        read_verified(ANNUAL_ROOT / manifest["file"], ANNUAL_HTML)
    )
    if (
        "$8.28 billion" not in annual_passages[824]["text"]
        or "Finance leases | 323" not in annual_passages[836]["text"]
    ):
        raise ValueError("Micron annual cash caption changed")
    historical = [
        dict(
            p,
            sourceUrl=manifest["url"],
            sourceHash=manifest["sha256"],
            sourceFile=manifest["file"],
        )
        for p in annual_passages
        if p["ordinal"] in [824, 836]
    ]
    for item in [manifest]:
        if item["file"] not in {s["file"] for s in c["sources"]}:
            c["sources"].append(item)
    anchors = [
        dict(
            label="연간 설비 감가상각",
            value=annual_ppe["value"],
            period="2024-08-30–2025-08-28",
            scope="연간 감가상각/전체 상각 비중을 미래 감가 가정에 사용",
            sourceUrl=manifest["url"],
        ),
        dict(
            label="연간 금융리스 원금 지급",
            value=annual_lease["value"],
            period="2024-08-30–2025-08-28",
            scope="연간 매출 대비 비율을 미래에 유지하는 가정",
            sourceUrl=manifest["url"],
        ),
        dict(
            label="최근1년 금융리스 원금 지급",
            value=None,
            period=h["start"] + "–" + h["end"],
            scope="현재9개월 별도 지급 미확인; 영으로 대체하지 않음",
            sourceUrl=source["primaryUrl"],
        ),
        dict(
            label="최근1년 정부지원 수취 현금",
            value=v("governmentIncentives"),
            period=h["start"] + "–" + h["end"],
            scope="보고 투자현금 유입; 기본 미래 가정에서는 반복 제외",
            sourceUrl=source["primaryUrl"],
        ),
    ]
    model = dict(
        status="research_workspace",
        version="micron-segment-cash-path-v1",
        unallocatedPath=True,
        sourcePeriod=[h["start"], h["end"]],
        accession=CURRENT,
        corpusHash=c["narrative"]["evidenceHash"],
        basisLabel="재작성 사업부와 정부지원·세금 시점을 구분한 최근1년",
        growthLabel="최근 9개월 전년 대비",
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        intro="시장별 메모리 부문 이익에서 본사 비용과 재투자를 연결합니다. 장기 미지급 세금 증가를 고객 선수금이나 반복 가능한 자금 조달로 바꾸지 않습니다.",
        businessCaption="CMBU 전체가 HBM은 아니며 DRAM·NAND 제품 축과 사업부를 더하지 않습니다. 현재9개월 성장과 최근1년 이익률은 기간이 다릅니다.",
        corporateLabel="본사 미배분 비용",
        capexLabel="정부지원 차감 전 설비 취득",
        leaseLabel="금융리스 원금 가정",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        passages=[
            by[i]
            for i in [
                337,
                342,
                343,
                344,
                350,
                351,
                353,
                354,
                355,
                356,
                357,
                450,
                451,
                467,
                468,
                469,
                470,
                487,
                488,
            ]
        ],
        cashAnchors=anchors,
        historicalPassages=historical,
        bridgeLabel="공시 연결 순이익 → 영업현금 대사",
        bridge=dict(
            parts=bridge_parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=v("cfo") - v("capex") - v("sbc"),
        ),
        observedResidualLabel="설비 취득·주식보상 대체 후 / 정부지원 가산·금융리스 원금 차감 전",
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=growth,
            unallocatedCost=corporate,
            annualPpeDepreciation=annual_ppe,
            annualDepreciationAmortization=annual_da,
            assumedPpeDepreciation=depreciation_assumption,
            trailingPpeDepreciation=None,
            annualFinanceLeasePaid=annual_lease,
            trailingFinanceLeasePrincipalPaid=None,
        ),
        anchorSummary="영업자금 계수는 당기9개월 채권·재고·매입채무/미지급비용·기타 유동부채만 반영합니다. 기타 장기부채 5.203bn 증가와 기타 현금 조정은 제외합니다. 장기 세금채무 잔액의 차이는 실제 세금 현금흐름이 아닙니다.",
        rules=[
            "현재 부문 마진·성장0%에서 출발하며 호황 이익률의 정상 지속을 승인하지 않습니다.",
            "본사 미배분 비용과 주식보상 대체 비용을 유지합니다. 주식보상 현금 되돌림은 미래에 더하지 않습니다.",
            "미래 설비 감가상각은 최근1년 전체 상각에 직전 연간 설비 감가 비중을 곱한 연구 가정입니다. 실제 최근1년 설비 감가로 표시하지 않습니다.",
            "금융리스는 연간 실제 지급/연간 매출 비율에서 출발합니다. 최근1년 금융리스 지급은 미확인입니다. 차입 상환 총액 차이를 리스 지급으로 단정하지 않습니다.",
            "정부지원 수취는 현재 보고 금액으로 보존하고 미래 기본 가정에서 제외합니다. 지원 조건·환수 가능성에 따라 별도로 순투자 가정을 수정해야 합니다. 현재 총설비 취득을 회사의 연간 순투자 계획27bn과 같은 숫자로 비교하지 않습니다.",
            "최근9개월 보고세율을 가정의 출발점으로 사용합니다. 세금 납부 이연 효과와 지분법 이익, 부채 조기상환 손실은 미래 순이자에 반복하지 않습니다.",
        ],
        remaining=[
            "메모리 가격·출하·제품 구성과 정상 부문 마진의 하강 경로",
            "세금채무의 실제 납부 일정과 계약 선수금의 별도 현금 변동",
            "정부지원의 유지 조건·환수 가능성과 지원 제외 순투자 부담",
            "현재 설비 감가·금융리스 실제 원금 지급 및 추가 자산 취득",
            "초과 금융자산·차입 차환·주식수와 정상 주주 현금 배분",
        ],
        independentFinancialApproval=False,
    )
    model["initial"] = calculate(model, defaults)
    model["evidenceHash"] = digest(canonical(model))
    return model
