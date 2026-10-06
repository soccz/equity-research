"""LG Innotek: three segments, working-cash movements and customer scope."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "20260814001879"
CORPUS = "f3bf7589130e41e9072cbad39a5587db22b8d0f693606e80512150e6a6491c37"
SOURCE = "14baaa75381f0d838b315c5ad2533e4dd72f54ff674ecab9e8bba93e32993c1d"
ANNUAL = "20260312001270"
ANNUAL_SHA = "ac5cf58f77fbd287af8e91693d378ee42949c3be731f87c5e1e35524e9b9d86c"
ANNUAL_DOC = "bb2d666bd835dd2f7b943fdb2b3c5a96a3c74047b3fd9110bf1f14a9ef7c97c6"
CON = [("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")]
REPORTED = CON + [
    (
        "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis",
        "ReportedAmountMember",
    )
]
TAGS = dict(
    revenue="Revenue",
    operatingIncome="OperatingIncomeLoss",
    netIncome="ProfitLoss",
    generated="CashFlowsFromUsedInOperations",
    cfo="CashFlowsFromUsedInOperatingActivities",
    interestPaid="InterestPaidClassifiedAsOperatingActivities",
    interestReceived="InterestReceivedClassifiedAsOperatingActivities",
    taxPaid="IncomeTaxesPaidRefundClassifiedAsOperatingActivities",
    capex="PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    intangibles="PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
    lease="PaymentsOfFinanceLeaseLiabilitiesClassifiedAsFinancingActivities",
    statementDepreciation="DepreciationExpense",
)
ADJUSTMENTS = dict(
    depreciation="AdjustmentsForDepreciationExpense",
    amortization="AdjustmentsForAmortisationExpense",
    interestExpense="AdjustmentsForInterestExpense",
    working="AdjustmentsForAssetsLiabilitiesOfOperatingActivities",
    costAdjustments="AdjustmentsToReconcileLossOfCashFlowsFromUsedInOperationsOfCashFlowsFromUsedInOperatingActivitiesTableOfItems",
    gainAdjustments="AdjustmentsToReconcileProfitOfCashFlowsFromUsedInOperationsOfCashFlowsFromUsedInOperatingActivitiesTableOfItems",
    receivables="AdjustmentsForDecreaseIncreaseInTradeAccountReceivable",
    inventory="AdjustmentsForDecreaseIncreaseInInventories",
    payables="AdjustmentsForIncreaseDecreaseInTradeAccountPayable",
)
CASH = [
    ("netIncome", "연결 순이익", 1),
    ("costAdjustments", "비현금 비용 등 가산", 1),
    ("gainAdjustments", "비현금 수익 등 차감", -1),
    ("working", "영업자산·부채 현금 변동", 1),
    ("interestPaid", "현금 이자 지급", -1),
    ("interestReceived", "현금 이자 수령", 1),
    ("taxPaid", "법인세 지급", -1),
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="LG이노텍 부문·운전자본·주요 고객 범위와 비용 부호를 새 공시에서 다시 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    source_url = c["financials"]["current"]["cfo"]["sourceUrl"]
    annual_fact = c["trailingYear"]["values"]["cfo"]["components"][0]["fact"]
    annual_source = next(
        s for s in c["sources"] if s["file"] == annual_fact["sourceFile"]
    )
    doc = json.loads(
        (
            DOCUMENT_ROOT / f"data/sources/dart-document-{ANNUAL}.manifest.json"
        ).read_text()
    )
    annual_document = next(
        x for x in doc["files"] if x["originalName"] == ANNUAL + ".xml"
    )
    if (
        source["sha256"] != SOURCE
        or annual_source["sha256"] != ANNUAL_SHA
        or annual_fact["accession"] != ANNUAL
        or doc["receipt"] != ANNUAL
        or annual_document["sha256"] != ANNUAL_DOC
    ):
        raise ValueError("LG Innotek source identity changed")
    annual = instance_rows(
        read_verified(ROOT / annual_source["file"], ANNUAL_SHA),
        c,
        annual_source,
        ANNUAL,
        "2026-03-12",
    )
    periods = [
        (1, annual, "2025-01-01", "2025-12-31"),
        (1, rows, "2026-01-01", "2026-06-30"),
        (-1, rows, "2025-01-01", "2025-06-30"),
    ]
    if (
        c["financials"]["start"] != "2026-01-01"
        or c["financials"]["end"] != "2026-06-30"
    ):
        raise ValueError("LG Innotek period changed")

    def exact(rs, tag, start, end, dims=CON):
        r = select(rs, tag, start, end, dims, "KRW")
        if r is None:
            raise ValueError(
                "LG Innotek fact missing " + tag + " " + str(start) + " " + end
            )
        return r

    def combined(tag, dims=CON):
        parts = [
            dict(coefficient=k, fact=exact(rs, tag, start, end, dims))
            for k, rs, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            sourceUrl=source_url,
            unit="KRW",
        )

    facts = {k: combined(tag) for k, tag in TAGS.items()}
    facts.update({k: combined(tag, REPORTED) for k, tag in ADJUSTMENTS.items()})
    disposal = []
    for i, (coefficient, rs, start, end) in enumerate(periods):
        tag = (
            "LossesOnDispositionOfReceivablesFinancialExpense"
            if i == 0
            else "LossesOnDispositionOfReceivables"
        )
        # Annual category table reports related income/(expense); the interim
        # expense convention is positive. Preserve both raw facts and signs.
        expense_sign = -1 if i == 0 else 1
        disposal.append(
            dict(
                coefficient=coefficient * expense_sign,
                expenseSign=expense_sign,
                fact=exact(rs, tag, start, end),
            )
        )
    facts["receivableDisposalCost"] = dict(
        value=sum(p["coefficient"] * p["fact"]["value"] for p in disposal),
        components=disposal,
        sourceUrl=source_url,
        unit="KRW",
    )
    v = lambda key: facts[key]["value"]
    segments = []
    for member, label in [
        (
            "OpticsSolutionSegmentsMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
            "광학솔루션",
        ),
        (
            "SubstrateAndMaterialSegmentsMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
            "패키지솔루션",
        ),
        (
            "AutomotiveComponentsSegmentsMemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
            "모빌리티솔루션",
        ),
    ]:
        dims = CON + [("SegmentsAxis", member)]
        sales = combined("Revenue", dims)
        profit = combined("OperatingIncomeLoss", dims)
        segments.append(
            dict(
                id=member,
                label=label,
                revenue=sales["value"],
                margin=profit["value"] / sales["value"],
                observedGrowth=sales["components"][1]["fact"]["value"]
                / sales["components"][2]["fact"]["value"]
                - 1,
                evidence=[sales, profit],
            )
        )
    checks = []
    for i, (_, rs, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        parts = [
            dict(
                label=label,
                value=sign * val(key),
                fact=facts[key]["components"][i]["fact"],
            )
            for key, label, sign in CASH
        ]
        generated = (
            val("netIncome")
            + val("costAdjustments")
            - val("gainAdjustments")
            + val("working")
        )
        if (
            generated != val("generated")
            or sum(p["value"] for p in parts) != val("cfo")
            or any(
                sum(
                    s["evidence"][j]["components"][i]["fact"]["value"] for s in segments
                )
                != val(key)
                for j, key in [(0, "revenue"), (1, "operatingIncome")]
            )
        ):
            raise ValueError("LG Innotek period cash/segment reconciliation failed")
        checks.append(
            dict(
                start=start,
                end=end,
                netIncome=val("netIncome"),
                costAdjustments=val("costAdjustments"),
                gainAdjustments=val("gainAdjustments"),
                generated=generated,
                working=val("working"),
                receivables=val("receivables"),
                inventory=val("inventory"),
                payables=val("payables"),
                remainingWorking=val("working")
                - val("receivables")
                - val("inventory")
                - val("payables"),
                reportedCfo=val("cfo"),
                components=parts,
                residual=0,
                revenueResidual=0,
                incomeResidual=0,
                depreciationCash=val("depreciation"),
                depreciationStatement=val("statementDepreciation"),
                depreciationDifference=val("depreciation")
                - val("statementDepreciation"),
            )
        )
    stock = [
        dict(
            coefficient=coefficient,
            label=label,
            fact=exact(rows, tag, None, "2026-06-30"),
        )
        for coefficient, label, tag in [
            (1, "순매출채권", "CurrentTradeReceivables"),
            (1, "재고자산", "Inventories"),
            (
                -1,
                "매입채무 · 원문 재무상태표 구분",
                "TradeAndOtherCurrentPayablesToTradeSuppliers",
            ),
        ]
    ]
    stock_net = sum(p["coefficient"] * p["fact"]["value"] for p in stock)
    revenue = v("revenue")
    investment = v("capex") + v("intangibles")
    funding_cost = v("interestExpense") + v("receivableDisposalCost")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.25,
        netInterest=-funding_cost / revenue,
        depreciation=(v("depreciation") + v("amortization")) / revenue,
        workingCapital=stock_net / revenue,
        capexStart=investment / revenue,
        capexEnd=investment / revenue,
        leaseStart=v("lease") / revenue,
        leaseEnd=v("lease") / revenue,
        discount=0.12,
        terminal=0.02,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    business_customer = index["6714c8e854c22f2896e6"]
    if "8,841,475백만원" not in business_customer["text"]:
        raise ValueError("LG Innotek customer business text changed")
    note_customer = exact(
        rows,
        "Revenue",
        "2026-01-01",
        "2026-06-30",
        CON
        + [
            (
                "MajorCustomersAxis",
                "SingleCustomerMemberOfMajorCustomersDomainOfDisclosureOfMajorCustomersTableOfMember",
            )
        ],
    )
    annual_ps = extract(
        read_verified(DOCUMENT_ROOT / annual_document["file"], ANNUAL_DOC)
    )
    annual_index = {p["id"]: p for p in annual_ps}
    expense_note = annual_index["c3fd43da6a31d1f9c551"]
    if "(25,927)" not in expense_note["text"]:
        raise ValueError("LG Innotek annual signed financial expense missing")
    s = dict(
        annual_document,
        provider="OpenDART",
        url=doc["url"],
        retrievedAt=doc["retrievedAt"],
    )
    if s["file"] not in {x["file"] for x in c["sources"]}:
        c["sources"].append(s)
    parts = [
        dict(
            label=label,
            value=sign * v(key),
            fact=dict(
                sourceUrl=source_url,
                components=[
                    dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                    for p in facts[key]["components"]
                ],
            ),
        )
        for key, label, sign in CASH
    ]
    if sum(p["value"] for p in parts) != v("cfo"):
        raise ValueError("LG Innotek trailing cash bridge failed")
    customer_scope = dict(
        status="scope_review_required",
        note=note_customer,
        businessValue=8841475000000,
        businessSource=business_customer,
        difference=note_customer["value"] - 8841475000000,
        noteRatio=note_customer["value"]
        / facts["revenue"]["components"][1]["fact"]["value"],
        businessRatio=8841475000000
        / facts["revenue"]["components"][1]["fact"]["value"],
    )
    m = dict(
        status="research_workspace",
        version="innotek-segment-working-cash-v1",
        sourcePeriod=["2025-07-01", "2026-06-30"],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="KRW",
        displayScale=1e12,
        displayUnit="조 원",
        basisLabel="세 기간 부문 손익·현금 대사",
        growthLabel="같은 반기 대비",
        groupLabel="세 보고부문",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        netInterestLabel="이자·매출채권 처분 비용",
        capexLabel="설비·무형자산 취득",
        leaseLabel="리스 원금 지급 가정",
        intro="광학·패키지·모빌리티의 매출과 영업이익을 연결 합계와 대사하고, 증가한 매출·이익이 영업현금에 그대로 이어졌는지 공시 현금표로 구분합니다. 주요 고객의 두 공시 금액은 범위가 확인될 때까지 병치합니다.",
        businessCaption="부문 손익은 지원부문 공통비용을 회사 기준으로 배분한 영업이익입니다. 카메라·기판의 전체 수요나 단일 고객 실적과 동일시하지 않습니다. 과거 기타 사업의 이관을 현재 신규 매출로 만들지 않습니다.",
        anchorSummary="기말 순매출채권+재고−원문 매입채무를 최근1년 매출로 나눈 비율을 미래 증가 매출의 자금 소요로 가정합니다. 기타수취채권·기타지급채무는 합산하지 않습니다. 기말 잔액 비율은 실제 회수일수나 미래 회수 개선의 증거가 아닙니다. 성장0·세율25%와 현재 비용 비율의 반복은 명시적 연구 가정입니다.",
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            periods=checks,
            residual=0,
            cashAfterInvestmentLeaseSbc=None,
        ),
        observedResidualLabel="전체 주식보상 현금 대체액 미확인 / 보고 현금과 미래 비용 가정 구분",
        anchors=dict(
            workingStockTerms=stock,
            workingStockNet=stock_net,
            actualFinanceLeasePrincipal=v("lease"),
            shareCompensationReplacement=None,
        ),
        manufacturingEvidence=dict(
            periods=checks,
            workingStockTerms=stock,
            workingStockNet=stock_net,
            customerScope=customer_scope,
            receivableDisposalCost=facts["receivableDisposalCost"],
        ),
        cashAnchors=[
            dict(
                label=label,
                period=period,
                value=amount,
                sourceUrl=source_url,
                scope=scope,
            )
            for label, period, amount, scope in [
                (
                    "설비·무형자산 취득",
                    "최근1년",
                    investment,
                    "투자현금 분류; 금융자산·대여금 취득과 구분",
                ),
                (
                    "리스 원금 지급",
                    "최근1년",
                    v("lease"),
                    "재무활동 분류. 미래 현금에서 한 번 차감",
                ),
                (
                    "현금표 감가·무형상각 되돌림",
                    "최근1년",
                    v("depreciation") + v("amortization"),
                    "미래 영업이익에 한 번 가산",
                ),
                (
                    "총이자 비용",
                    "최근1년",
                    v("interestExpense"),
                    "현금 지급·수령과 구분, 미래에는 비용 비율 가정",
                ),
                (
                    "매출채권 처분 비용",
                    "최근1년",
                    v("receivableDisposalCost"),
                    "연간 순금융손익 표의 부호와 반기 비용 표의 부호를 대사",
                ),
                (
                    "채권·재고−매입채무",
                    "2026-06-30",
                    stock_net,
                    "기말 순영업 잔액의 좁은 대용, 현재 현금 유출 아님",
                ),
                (
                    "전체 주식보상 현금 대체액",
                    "최근1년",
                    None,
                    "미확인을 영으로 확정하지 않음. 미래 영업비용은 유지",
                ),
            ]
        ],
        passages=[
            index[pid]
            for pid in [
                "08240a1bbeff44f1cab6",
                "e4f17e566f3b3ac5f57d",
                "6714c8e854c22f2896e6",
                "62aeec10d6d53ccad830",
                "039359f68790d47de720",
            ]
        ],
        historicalPassages=[
            dict(expense_note, sourceUrl=doc["url"], sourceHash=ANNUAL_DOC)
        ],
        rules=[
            "연간+현재 반기−전년 반기로 연결하며 모든 기간의 부문 매출·영업이익과 순이익→창출 현금→영업현금을 대사한다.",
            "영업자산·부채 총변동을 채권·재고·매입채무와 나머지로 분해한다. 나머지를 임의로 수금 개선·재고 처분으로 해석하지 않는다. 기말 잔액 증감과 현금표 변동은 환율·비현금 변동 때문에 동일하지 않을 수 있다.",
            "공시 사업 설명과 주요고객 주석의 금액 차이를 그대로 남긴다. 고객 실명을 추정하거나 금액 범위 차이를 매출 오류·악재로 확정하지 않는다.",
            "연간 금융상품 관련수익(비용)의 음수 처분손실과 반기 양수 비용 항목의 원문·계수를 보존한다. 미래에는 이자와 함께 비용으로 한 번 차감하며 투자수익·환산손익은 반복하지 않는다.",
            "주석 감가상각과 현금표 감가상각 되돌림의 반기 차이를 보존한다. 현금표 되돌림을 미래 가정의 근거로 사용하며 미대사 차이를 덮어쓰지 않는다.",
            "전액 주식보상은 자료 미확인이다. 미래 영업비용은 그대로 남기며 확인되지 않은 비현금 비용을 추가 가산하지 않는다.",
            "현재 취득비율이 상각보다 작아도 정상 유지 투자로 승인하지 않는다. 생산능력·가동률·제품전환 주기와 무형개발 취득을 확인해야 한다.",
        ],
        remaining=[
            "주요 고객 두 공시의 연결·제품 범위 대사",
            "광학 제품 구성·단가·신제품 전환과 수율",
            "차세대 패키지·모빌리티 설비의 사용률과 유지·확장 투자",
            "채권 매각·재고·매입채무의 실제 결제와 비현금 잔액 변동",
            "전체 보상 대체비·금융자산 배분·비반복 손익의 추가 검토",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
