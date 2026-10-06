"""Lam Research: one reportable segment, gross profit and warranty settlement."""

from .data import canonical, digest
from .xbrl import company_filing, select
from .narrative import load

CURRENT = "0000707549-26-000037"
CORPUS = "b909d8b8b109e5bfe1203219b815089fefa55082de07224a9ed22714c43d2f7c"
SOURCE = "245115118bda565a752cad0dd16ca255e524dc67da5624f9b8417f3f54519b6a"
SEG = [
    ("ConsolidationItemsAxis", "OperatingSegmentsMember"),
    ("StatementBusinessSegmentsAxis", "ReportableSegmentMember"),
]
ELIM = [("ConsolidationItemsAxis", "EliminationsAndReconcilingItemsMember")]
TAGS = dict(
    revenue="RevenueFromContractWithCustomerExcludingAssessedTax",
    gross="GrossProfit",
    research="ResearchAndDevelopmentExpense",
    selling="SellingGeneralAndAdministrativeExpense",
    restructuring="RestructuringChargesOperatingExpenseNet",
    operatingIncome="OperatingIncomeLoss",
    netIncome="NetIncomeLoss",
    pretax="IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    tax="IncomeTaxExpenseBenefit",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    depreciation="DepreciationAndAmortization",
    deferredTax="DeferredIncomeTaxExpenseBenefit",
    sbc="ShareBasedCompensation",
    otherNoncash="OtherNoncashIncomeExpense",
    receivables="IncreaseDecreaseInAccountsReceivable",
    inventory="IncreaseDecreaseInInventories",
    prepaids="IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets",
    payables="IncreaseDecreaseInAccountsPayableTrade",
    deferredProfit="IncreaseDecreaseInDeferredRevenue",
    accrued="IncreaseDecreaseInAccruedLiabilitiesAndOtherOperatingLiabilities",
    capex="PaymentsToAcquireProductiveAssets",
    lease="FinanceLeasePrincipalPayments",
    interestIncome="InvestmentIncomeInterest",
    interestExpense="InterestExpenseNonoperating",
    warrantyIssued="StandardProductWarrantyAccrualWarrantiesIssued",
    warrantyAdjustment="StandardProductWarrantyAccrualPreexistingIncreaseDecrease",
    warrantyUsed="StandardProductWarrantyAccrualPayments",
)
CASH = [
    ("netIncome", "연결 순이익", 1),
    ("depreciation", "감가상각·상각 조정", 1),
    ("deferredTax", "이연 법인세", 1),
    ("sbc", "주식보상 비용 조정", 1),
    ("otherNoncash", "기타 비현금 조정", -1),
    ("receivables", "매출채권 현금 변동", -1),
    ("inventory", "재고 현금 변동", -1),
    ("prepaids", "선급·기타 자산 현금 변동", -1),
    ("payables", "매입채무 현금 변동", 1),
    ("deferredProfit", "이연 이익 현금 변동", 1),
    ("accrued", "미지급·기타 부채 현금 변동", 1),
]
PASSAGES = [
    "d9e4bc4b8e3aef8bf377",
    "ccaafb047c6d62083132",
    "adfa15ff5795fafcea63",
    "96ca2aeb10fc403a0dba",
    "8722d26f723f7e8be695",
    "91434b122cdeaf4ac925",
    "19f4f321fe8a3d541529",
    "636be3e0225cfd1e3547",
    "6f6e2b5d6fb67be2a90b",
    "f250bfbaf3c9237413b9",
    "c4313cab99d43c9dad92",
    "6b9bd8b33efa51bd3aa7",
    "c54725b4e9c7b1f0517c",
    "58fe9e45fb0eb6a10db3",
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="Lam의 단일 사업·매출총이익 조정·보증 정산을 새 공시와 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    if not source or source["sha256"] != SOURCE:
        raise ValueError("Lam source identity changed")
    f = c["financials"]
    if [f["start"], f["end"]] != ["2025-06-30", "2026-06-28"]:
        raise ValueError("Lam annual period changed")

    def exact(tag, start, end, dims=()):
        r = select(rows, tag, start, end, dims, "USD")
        if r is None:
            raise ValueError("Lam fact missing: " + tag)
        return r

    all_facts = []
    checks = []
    warranties = []
    for start, end in [(f["start"], f["end"]), (f["priorStart"], f["priorEnd"])]:
        facts = {k: exact(t, start, end) for k, t in TAGS.items()}
        facts["segmentGross"] = exact("SegmentReportingGrossProfit", start, end, SEG)
        facts["segmentRevenue"] = exact(
            "RevenueFromContractWithCustomerExcludingAssessedTax", start, end, SEG
        )
        facts["otherCogs"] = exact(
            "CostOfGoodsAndServicesSoldExcludingRestructuringCharges", start, end, ELIM
        )
        facts["restructuringCogs"] = exact(
            "RestructuringChargesCostOfGoodsNet", start, end, ELIM
        )
        val = lambda k: facts[k]["value"]
        cash = sum(sign * val(k) for k, _, sign in CASH)
        if (
            cash != val("cfo")
            or val("segmentRevenue") != val("revenue")
            or val("segmentGross") - val("otherCogs") - val("restructuringCogs")
            != val("gross")
            or val("gross") - val("research") - val("selling") - val("restructuring")
            != val("operatingIncome")
            or val("pretax") - val("tax") != val("netIncome")
        ):
            raise ValueError("Lam period cash or gross-profit reconciliation failed")
        from datetime import date, timedelta

        opening = exact(
            "StandardProductWarrantyAccrual",
            None,
            (date.fromisoformat(start) - timedelta(days=1)).isoformat(),
        )
        closing = exact("StandardProductWarrantyAccrual", None, end)
        if (
            opening["value"]
            + val("warrantyIssued")
            + val("warrantyAdjustment")
            - val("warrantyUsed")
            != closing["value"]
        ):
            raise ValueError("Lam warranty reserve reconciliation failed")
        warranties.append(
            dict(
                start=start,
                end=end,
                opening=opening,
                closing=closing,
                issued=facts["warrantyIssued"],
                adjustment=facts["warrantyAdjustment"],
                settled=facts["warrantyUsed"],
                residual=0,
            )
        )
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=val("cfo"),
                residual=0,
                incomeResidual=0,
                revenueResidual=0,
                otherCogs=val("otherCogs"),
            )
        )
        all_facts.append(facts)
    facts = all_facts[0]
    v = lambda k: facts[k]["value"]
    revenue = v("revenue")
    prior = all_facts[1]
    working = sum(
        sign * v(k)
        for k, _, sign in CASH
        if k in {"receivables", "inventory", "prepaids", "payables", "deferredProfit"}
    )
    increase = revenue - prior["revenue"]["value"]
    if increase <= 0:
        raise ValueError("Lam growth working-capital proxy requires review")
    s = dict(
        id="ReportableSegmentMember",
        label="웨이퍼 가공 장비 제조·서비스",
        revenue=revenue,
        margin=v("segmentGross") / revenue,
        observedGrowth=revenue / prior["revenue"]["value"] - 1,
        evidence=[facts["segmentRevenue"], prior["segmentRevenue"]],
    )
    other = v("otherCogs") + v("restructuringCogs") + v("restructuring")
    defaults = dict(
        segments=[dict(growthStart=0, growthEnd=0, marginEnd=s["margin"])],
        tax=0.21,
        netInterest=(v("interestIncome") - v("interestExpense")) / revenue,
        depreciation=v("depreciation") / revenue,
        workingCapital=-working / increase,
        capexStart=v("capex") / revenue,
        capexEnd=v("capex") / revenue,
        leaseStart=v("lease") / revenue,
        leaseEnd=v("lease") / revenue,
        researchStart=v("research") / revenue,
        researchEnd=v("research") / revenue,
        sellingStart=v("selling") / revenue,
        sellingEnd=v("selling") / revenue,
        otherOperatingStart=other / revenue,
        otherOperatingEnd=other / revenue,
        minority=0,
        warrantyAccrual=(v("warrantyIssued") + v("warrantyAdjustment")) / revenue,
        warrantyUseStart=v("warrantyUsed") / revenue,
        warrantyUseEnd=v("warrantyUsed") / revenue,
        discount=0.12,
        terminal=0.02,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    if any(p not in index for p in PASSAGES):
        raise ValueError("Lam narrative changed")
    m = dict(
        status="research_workspace",
        version="lam-gross-profit-warranty-cash-v1",
        grossProfitPath=True,
        reservePath=True,
        sourcePeriod=[f["start"], f["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        basisLabel="보고된 연간 사업·현금 대사",
        growthLabel="직전 연간 대비",
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        segments=[s],
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        groupLabel="공시 단일 사업",
        marginLabel="부문 매출총이익률",
        bridgeLabel="연결 순이익 → 보고 영업현금 대사",
        capexLabel="설비·무형자산 현금 취득",
        leaseLabel="확인한 금융리스 원금",
        netInterestLabel="이자수익 − 이자비용",
        intro="공시 단일 사업의 매출총이익에서 비배분 원가·연구개발·판매관리비를 연결합니다. 시스템과 고객지원 매출은 구분되지만 이익은 별도 공시되지 않으므로 임의의 서비스 마진을 만들지 않습니다.",
        businessCaption="고객지원 매출에는 서비스·부품·업그레이드와 Reliant 비첨단 장비도 포함됩니다. 이를 모두 반복 구독매출로 읽지 않습니다. 공시 부문 이익은 영업이익이 아니라 일부 비배분 원가를 제외한 매출총이익입니다.",
        anchorSummary="매출채권·재고·선급·매입채무·이연 이익의 현금 효과만 같은 연간 매출 증가에 연결합니다. 보증·세금 등이 섞인 미지급·기타 부채는 성장 대용에서 제외합니다. 세율21%는 연구 가정이며 실제 현금납세와 구별합니다.",
        passages=[index[p] for p in PASSAGES],
        observedResidualLabel="영업현금 − 설비·무형 취득 − 금융리스 원금 − 주식보상 비용 조정",
        bridge=dict(
            parts=[
                dict(label=label, value=sign * v(k), fact=facts[k])
                for k, label, sign in CASH
            ],
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=v("cfo") - v("capex") - v("lease") - v("sbc"),
        ),
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=increase,
            unallocatedCost=other,
            actualFinanceLeasePrincipal=v("lease"),
            warrantyPeriods=warranties,
            reportedWarrantyNetAccrual=v("warrantyIssued") + v("warrantyAdjustment"),
            reportedWarrantySettlement=v("warrantyUsed"),
        ),
        cashAnchors=[
            dict(
                label=label,
                period=f["start"] + "–" + f["end"],
                value=value,
                sourceUrl=source["primaryUrl"],
                scope=scope,
            )
            for label, value, scope in [
                (
                    "미배분 원가",
                    v("otherCogs"),
                    "부문 총이익과 연결 총이익의 차이. 연구개발·판관비와 별도",
                ),
                (
                    "보증 신규 발생",
                    v("warrantyIssued"),
                    "기존 보증 조정과 합쳐 순비용 가정으로 사용",
                ),
                (
                    "기존 보증 추정 변경",
                    v("warrantyAdjustment"),
                    "부채 감소·비용 환입. 지급액이나 당기 결함률 아님",
                ),
                (
                    "보증 정산",
                    v("warrantyUsed"),
                    "부품·수리 등을 포함한 정산액의 미래 현금 대용. 고객 직접 현금 지급 전액으로 단정하지 않음",
                ),
                (
                    "보증 기초",
                    warranties[0]["opening"]["value"],
                    "기간 시작 전날의 총 충당부채",
                ),
                ("보증 기말", warranties[0]["closing"]["value"], "유동·비유동 합계"),
                (
                    "금융리스 원금",
                    v("lease"),
                    "장기부채 상환·발행비용 합계에서 별도 공시된 리스 원금만 사용",
                ),
            ]
        ],
        rules=[
            "현재 연간과 직전 연간의 현금·부문 총이익·연결 손익을 각각 대사합니다. 현재 연간 수치를 임의 연율화하거나 두 연간을 합치지 않습니다.",
            "부문 매출총이익에서 비배분 원가와 연구개발·판매관리비를 차감합니다. 감가·주식보상이 부문 원가에 배분되어 있다는 공시를 보존하고 주식보상은 미래 현금 대체 부담으로 남깁니다.",
            "기타 원가에는 인수 무형상각·이연보상 관련 부채 변동 등이 포함됩니다. 이자수익·비용만 미래 영업외 순액으로 쓰고 투자·이연보상 자산 이익은 제외하므로 대응 비용과의 정상화 대사가 추가로 필요합니다.",
            "보증 신규 발생과 기존 추정 변경을 합친 순비용을 되돌리고 별도 정산 대용액을 차감합니다. 설치·보증 비용 합계645.551백만 달러를 충당비용으로 쓰지 않습니다. 미지급·기타 부채를 운전자본 대용에서 제외하여 보증 효과를 이중으로 넣지 않습니다.",
            "보증 정산은 직접 현금 지급만을 의미하지 않을 수 있습니다. 현재 주석 정산액을 미래 부담 대용으로 쓰며 제품 결함률·현재 판매분의 고장률로 변환하지 않습니다.",
            "설비·무형 현금취득과 금융리스 원금4.971백만 달러를 분리합니다. 장기부채 상환·리스·발행비용755.428백만 달러 전액을 추가 설비부담으로 차감하지 않습니다.",
            "현금납세와 손익세금의 시차를 보존합니다. 해외 누적이익 전환세의 잔여 의무는 현재연간 정산됐다는 공시가 있어도 미래 법인세 전액 소멸로 읽지 않습니다.",
            "성장0·현재 부문총마진과 비용비율·요구수익률12%·영구성장2%는 비교 시작점입니다. 고객 구성·수출 규제·관세·설치 대수와 기술 전환에 따른 가정을 별도로 검토합니다.",
        ],
        remaining=[
            "단일 사업 안의 시스템·고객지원 비용과 이익 구성",
            "이연보상 자산이익·대응 비용·무형자산 정상화",
            "보증 정산의 현금·부품·서비스 범위와 실제 현금 부담",
            "장기 설비·무형 대체 투자와 세금·고객 믹스 변화",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
