"""Samsung SDS candidate: source-bound IT/logistics cash and capital limits."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "20260814003604"
CORPUS = "c433f60634fbc13d42802d4152396e026e7f758f7a0063c8110588ba6db73244"
CURRENT_SHA = "6f1283bfa55a5abdde211405b2d25eca94a2b9fba415a3ddded4c9e589acc5e6"
ANNUAL_SHA = "976db5e4ef0c9c32ee41b447bba67bdd9433245763f64314cecbba189903f7ad"
ANNUAL_DOC = "c4222519a2e3d6d4f8b5d759b5232bd7c05bff01c89031b1215742fe43001edb"
CON = [("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")]
IND = CON + [
    (
        "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis",
        "ReportedAmountMember",
    )
]
SEG = [("ItService", "IT서비스"), ("LogisticsService", "물류")]
TAGS = dict(
    revenue=("Revenue", CON),
    operatingIncome=("OperatingIncomeLoss", CON),
    netIncome=("ProfitLoss", CON),
    cfo=("CashFlowsFromUsedInOperatingActivities", CON),
    generated=("CashFlowsFromUsedInOperations", CON),
    adjustments=("AdjustmentsForReconcileProfitLoss", IND),
    working=("AdjustmentsForAssetsLiabilitiesOfOperatingActivities", IND),
    interestReceived=("InterestReceivedClassifiedAsOperatingActivities", CON),
    dividends=("DividendsReceivedClassifiedAsOperatingActivities", CON),
    interestPaid=("InterestPaidClassifiedAsOperatingActivities", CON),
    taxCash=("IncomeTaxesPaidRefundClassifiedAsOperatingActivities", CON),
    depreciation=("DepreciationPropertyPlantAndEquipment", CON),
    amortization=("AmortisationIntangibleAssetsOtherThanGoodwill", CON),
    rou=("DepreciationRightofuseAssets", CON),
    ppe=("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", CON),
    intangible=("PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities", CON),
    lease=("PaymentsOfFinanceLeaseLiabilitiesClassifiedAsFinancingActivities", CON),
    minority=("ProfitLossAttributableToNoncontrollingInterests", CON),
    sbc=("ExpenseFromSharebasedPaymentTransactionsWithEmployees", IND),
)
CASH = [
    ("generated", "영업에서 창출한 현금", 1),
    ("interestReceived", "현금 이자 수취", 1),
    ("interestPaid", "현금 이자 지급", -1),
    ("dividends", "현금 배당 수취", 1),
    ("taxCash", "현금 법인세 지급", -1),
]
PASSAGES = [
    "73328148291cf4370fea",
    "e1316999d71caf127461",
    "dc32f5a1f3ef0d016670",
    "3c4ca09fc934b333b654",
    "4922373ee3e56e51571d",
    "4a0454dfb8b131be344c",
    "010b96ac08a061013cd8",
    "639add2274b5bac54111",
    "c3197d8fb8f5784ac581",
    "1525c83c05387e376c95",
    "a7760c9a8e1e60a4b099",
    "4a8a62a9dc59014e811f",
    "db2d2ecab4dd15197b86",
    "f9d944b5b8820bd132bb",
    "940a76b4a3dbf1aba8e7",
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="삼성SDS의 부문 정의·내부거래·공급자금융·정부 GPU와 전환사채 범위를 새 공시에서 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if (
        source["sha256"] != CURRENT_SHA
        or core["sourceHash"] != ANNUAL_SHA
        or core["accession"] != "20260310002989"
    ):
        raise ValueError("SDS source identity differs")
    annual_source = next(s for s in c["sources"] if s["file"] == core["sourceFile"])
    annual = instance_rows(
        read_verified(ROOT / core["sourceFile"], ANNUAL_SHA),
        c,
        annual_source,
        core["accession"],
        core["filedAt"],
    )
    f = c["financials"]
    periods = [
        (1, annual, core["start"], core["end"]),
        (1, rows, f["start"], f["end"]),
        (-1, rows, f["priorStart"], f["priorEnd"]),
    ]

    def exact(rs, tag, start, end, dims=CON):
        r = select(rs, tag, start, end, dims, "KRW")
        if r is None:
            raise ValueError("SDS fact missing: " + tag + " " + str(start) + " " + end)
        return r

    def combined(tag, dims=CON):
        parts = [
            dict(
                coefficient=k,
                fact=exact(rs, tag, start, end, dims(i) if callable(dims) else dims),
            )
            for i, (k, rs, start, end) in enumerate(periods)
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            unit="KRW",
            sourceUrl=source["url"],
        )

    facts = {key: combined(tag, dims) for key, (tag, dims) in TAGS.items()}
    v = lambda key: facts[key]["value"]
    segments = []
    for prefix, label in SEG:

        def dims(i):
            table = (
                "DisclosureOfReportingSegmentstitleTableOfMember"
                if i == 0
                else "DisclosureOfOperatingSegmentsTableOfMember"
            )
            return CON + [
                ("SegmentConsolidationItemsAxis", "OperatingSegmentsMember"),
                ("SegmentsAxis", prefix + "MemberOfReportableSegmentsMemberOf" + table),
            ]

        revenue, profit = combined("Revenue", dims), combined(
            "OperatingIncomeLoss", dims
        )
        segments.append(
            dict(
                id=prefix,
                label=label,
                revenue=revenue["value"],
                margin=profit["value"] / revenue["value"],
                observedGrowth=revenue["components"][1]["fact"]["value"]
                / revenue["components"][2]["fact"]["value"]
                - 1,
                evidence=[revenue, profit],
            )
        )
    eliminated_dims = CON + [
        ("SegmentConsolidationItemsAxis", "EliminationOfIntersegmentAmountsMember")
    ]
    removed_revenue = combined("Revenue", eliminated_dims)
    removed_profit = combined("OperatingIncomeLoss", eliminated_dims)
    checks = []
    for i, (_, rs, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        gross = sum(
            s["evidence"][0]["components"][i]["fact"]["value"] for s in segments
        )
        profit = sum(
            s["evidence"][1]["components"][i]["fact"]["value"] for s in segments
        )
        removal = removed_revenue["components"][i]["fact"]["value"]
        adjustment = removed_profit["components"][i]["fact"]["value"]
        cash = sum(sign * val(key) for key, _, sign in CASH)
        rr, pr = (
            val("revenue") - gross - removal,
            val("operatingIncome") - profit - adjustment,
        )
        indirect = (
            val("generated") - val("netIncome") - val("adjustments") - val("working")
        )
        if cash != val("cfo") or max(abs(rr), abs(pr)) > 1001 or abs(indirect) > 3001:
            raise ValueError(
                f"SDS period cash/consolidation reconciliation failed: {start} {end} cfo {cash-val('cfo')} revenue {rr} profit {pr} indirect {indirect}"
            )
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=cash,
                residual=0,
                revenueResidual=rr,
                incomeResidual=pr,
                indirectPrecisionResidual=indirect,
                segmentRevenue=gross,
                internalRevenue=-removal,
                consolidatedRevenue=val("revenue"),
                unallocatedOperatingIncome=adjustment,
            )
        )
    # The observed half-year trade cash release is not a perpetual financing source.
    trade = [
        exact(rows, tag, f["start"], f["end"], IND)
        for tag in [
            "AdjustmentsForDecreaseIncreaseInTradeAccountReceivable",
            "AdjustmentsForIncreaseDecreaseInTradeAccountPayable",
        ]
    ]
    annual_trade = [
        exact(annual, tag, core["start"], core["end"], IND)
        for tag in [
            "AdjustmentsForDecreaseIncreaseInTradeAccountReceivable",
            "AdjustmentsForIncreaseDecreaseInTradeAccountPayable",
        ]
    ]
    prior_revenue = exact(annual, "Revenue", "2024-01-01", "2024-12-31")
    annual_increase = (
        facts["revenue"]["components"][0]["fact"]["value"] - prior_revenue["value"]
    )
    annual_working = sum(r["value"] for r in annual_trade)
    if annual_increase <= 0 or annual_working >= 0 or v("minority") < 0:
        raise ValueError("SDS working-capital or minority anchor needs review")
    stock_terms = [
        (1, "매출채권 순액", "CurrentTradeReceivables", CON),
        (1, "재고자산", "Inventories", CON),
        (1, "계약자산 순액", "ContractAssets", CON),
        (-1, "매입채무", "TradeAndOtherCurrentPayablesToTradeSuppliers", CON),
        (-1, "계약부채 유동·비유동", "ContractLiabilities", IND),
    ]
    working_stock = [
        dict(coefficient=k, label=label, fact=exact(rows, tag, None, f["end"], dims))
        for k, label, tag, dims in stock_terms
    ]
    net_stock = sum(x["coefficient"] * x["fact"]["value"] for x in working_stock)
    revenue = v("revenue")
    gross = sum(s["revenue"] for s in segments)
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.275,
        netInterest=(v("interestReceived") - v("interestPaid")) / revenue,
        depreciation=(v("depreciation") + v("amortization") + v("rou")) / revenue,
        workingCapital=net_stock / revenue,
        capexStart=(v("ppe") + v("intangible")) / revenue,
        capexEnd=(v("ppe") + v("intangible")) / revenue,
        leaseStart=v("lease") / revenue,
        leaseEnd=v("lease") / revenue,
        minority=v("minority") / revenue,
        discount=0.12,
        terminal=0.02,
        eliminationStart=-removed_revenue["value"] / gross,
        eliminationEnd=-removed_revenue["value"] / gross,
        otherProfitStart=removed_profit["value"] / revenue,
        otherProfitEnd=removed_profit["value"] / revenue,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    if any(p not in index for p in PASSAGES):
        raise ValueError("SDS operating source passages missing")
    manifest = json.loads(
        (
            DOCUMENT_ROOT / "data/sources/dart-document-20260310002989.manifest.json"
        ).read_text()
    )
    doc = next(d for d in manifest["files"] if d["sha256"] == ANNUAL_DOC)
    annual_text = extract(read_verified(DOCUMENT_ROOT / doc["file"], ANNUAL_DOC))
    selected = [
        p
        for p in annual_text
        if p["ordinal"] in [447, 449, 450, 454, 455, 460, 1124, 1126, 1127]
    ]
    if len(selected) != 9 or not any("7,974,695,401" in p["text"] for p in selected):
        raise ValueError("SDS annual segment source table differs")
    if doc["file"] not in {s["file"] for s in c["sources"]}:
        c["sources"].append(
            dict(
                doc,
                provider="DART",
                url=manifest["url"],
                retrievedAt=manifest["retrievedAt"],
            )
        )
    retirement = dict(
        currentOperatingIncome=facts["operatingIncome"]["components"][1]["fact"][
            "value"
        ],
        priorOperatingIncome=facts["operatingIncome"]["components"][2]["fact"]["value"],
        sellingCost=26400000000,
        productionCost=97300000000,
        totalCost=123700000000,
        scope="회사가 평균임금 범위에 관한 대법원 판결에 따라 재검토한 퇴직급여 산정 영향을 당반기 비용에 반영한 공시입니다. 두 기능별 금액은 억원 단위 반올림이며 IT·물류 부문별 배분이 아닙니다. 비용을 더한 단순 비교는 조정 EBITDA·정상 이익·즉시 현금 회복 전망이 아닙니다.",
        source=index["4a8a62a9dc59014e811f"],
    )
    if not all(
        x in retirement["source"]["text"]
        for x in ["판매관리비 264억", "매출원가 973억", "당반기"]
    ):
        raise ValueError("SDS retirement cost source changed")
    retirement["illustrativeProfitBeforeEffect"] = (
        retirement["currentOperatingIncome"] + retirement["totalCost"]
    )
    retirement["remainingProfitDifference"] = (
        retirement["illustrativeProfitBeforeEffect"]
        - retirement["priorOperatingIncome"]
    )
    m = dict(
        status="research_workspace",
        version="sds-services-logistics-cash-v1",
        sourcePeriod=["2025-07-01", f["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="KRW",
        displayScale=1e12,
        displayUnit="조 원",
        basisLabel="세 기간 현금·부문 대사 / 기말 영업잔액 대용",
        growthLabel="같은 상반기 대비 내부매출 포함",
        groupLabel="IT서비스·물류 두 부문",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        consolidationPath=True,
        sdsEvidence=dict(
            retirement=retirement,
            workingStockTerms=working_stock,
            workingStockNet=net_stock,
            workingRevenue=revenue,
        ),
        minorityScope="연결 비지배 이익/매출의 최근1년 비율을 미래 배분의 대용으로 가정합니다. 실제 배당 현금이나 종속회사별 권리 배분과 동일하지 않습니다.",
        consolidation=dict(
            periods=checks,
            segmentRevenue=gross,
            internalRevenue=-removed_revenue["value"],
            reportedRevenue=revenue,
            unallocatedOperatingIncome=removed_profit["value"],
            adjustmentLabel="공시 부문간 내부거래 이익 조정",
            profitScope="부문 이익에 배분하지 않은 내부거래 조정을 별도로 한 번 반영합니다.",
            scope="부문 총매출과 외부매출의 차이 및 이익 조정은 서로 다른 공시 항목입니다. 천원 단위 부문 표와 원 단위 연결 수치의 잔차를 보존합니다.",
        ),
        netInterestLabel="현금 순이자 대용",
        capexLabel="유형·무형 현금 취득",
        leaseLabel="리스 원금",
        intro="IT서비스·물류의 내부거래 포함 매출과 이익을 연결 총액에 대사합니다. 정부 소유 GPU 운영과 회사 소유 설비 취득, 공급자 조기 수령과 회사의 매입채무 지급을 구분합니다.",
        businessCaption="IT서비스 전체 마진을 클라우드·GPUaaS 단독 마진으로 만들지 않습니다. 물류 총매출은 운임과 외주 원가의 영향을 받으므로 플랫폼 구독 매출처럼 비교하지 않습니다. 내부거래 제거 전후의 영업이익을 섞지 않습니다.",
        anchorSummary="현재 반기 매출채권·매입채무 순유입과 작은 전년 연간 매출 증가에 나눈 높은 과거 소요계수를 미래에 반복하지 않습니다. 기말 순매출채권+재고+순계약자산−매입채무−계약부채를 최근1년 매출로 나눈 잔액 비율을 미래 증가 매출의 자금 소요로 가정합니다. 계약자산은 미수금의 하위항목이므로 미수금 총액을 추가하지 않습니다. 실제 회수일수나 현금 전환주기, 정상 운전자본 전망이 아니며 세율27.5%도 연구 가정입니다.",
        bridgeLabel="창출 현금 → 현금 이자·세금 후 영업현금",
        bridge=dict(
            parts=[
                dict(
                    label=label,
                    value=sign * v(k),
                    fact=dict(
                        sourceUrl=source["url"],
                        components=[
                            dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                            for p in facts[k]["components"]
                        ],
                    ),
                )
                for k, label, sign in CASH
            ],
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=v("cfo")
            - v("ppe")
            - v("intangible")
            - v("lease")
            - v("sbc"),
        ),
        anchors=dict(
            workingCashEffect=annual_working,
            revenueIncrease=annual_increase,
            tradeFacts=annual_trade,
            currentTradeCashEffect=sum(r["value"] for r in trade),
            currentTradeFacts=trade,
            shareCompensationReplacement=v("sbc"),
            workingStockTerms=working_stock,
            workingStockNet=net_stock,
            annualFlowCoefficient=-annual_working / annual_increase,
        ),
        cashAnchors=[
            dict(
                label=label,
                period=period,
                value=value,
                sourceUrl=source["url"],
                scope=scope,
            )
            for label, period, value, scope in [
                (
                    "주식보상 비용 대체 대용",
                    "최근1년",
                    v("sbc"),
                    "자본변동이 아닌 손익 비용. 미래 영업이익에 비용으로 남겨 되돌리지 않음",
                ),
                (
                    "매출채권·매입채무 현금 효과",
                    "현재상반기",
                    sum(r["value"] for r in trade),
                    "순유입을 향후 성장의 영구 자금 공급으로 반복하지 않음",
                ),
                (
                    "매출채권·매입채무 현금 효과",
                    "2025년",
                    annual_working,
                    "다른 운전자본 항목을 제외한 과거 흐름. 미래 기본 계수로 사용하지 않음",
                ),
                (
                    "순영업 잔액 대용",
                    "2026-06-30",
                    net_stock,
                    "순채권+재고+순계약자산−매입채무−계약부채. 미수금과 계약자산 중복 합산 금지",
                ),
                (
                    "순현금 이자 수취",
                    "최근1년",
                    v("interestReceived") - v("interestPaid"),
                    "미래 보유 금융자산·금리·신규 전환사채 쿠폰과 별도 검토",
                ),
                (
                    "정부 소유 GPU의 회사 소유 가치",
                    "계약기간",
                    None,
                    "공공 목적 운영과 제한적 자체 활용. 회사 소유 GPU 현금 취득으로 합산하지 않음",
                ),
            ]
        ],
        passages=[index[p] for p in PASSAGES],
        historicalPassages=[
            dict(p, sourceUrl=manifest["url"], sourceHash=ANNUAL_DOC) for p in selected
        ],
        rules=[
            "연간+현재반기−전년반기. 세 기간의 부문·내부거래 이익 및 영업현금을 먼저 대사하고 원문 표의 단위 잔차를 보존합니다.",
            "연간 원문의 전년 부문 수치와 동일하게 보이는 별도 XBRL 맥락을 섞지 않습니다. OperatingSegmentsMember가 있는 당기 부문 값과 원문 연간 표를 대조합니다.",
            "배당 수취는 보고 영업현금 대사에 포함하고 미래 본업 영업이익에는 가산하지 않습니다. 순이자는 최근1년 현금 대용입니다. 4월에 발행된 전환사채의 전년도 미발행 기간을 포함하므로 이 비율을 전환사채 정상 연이자로 해석하지 않습니다.",
            "공급자금융약정은 매입채무로 남고 지급기한은 일반 매입채무와 같은 송장 후 3개월 이내입니다. 다른 회사의 재무활동 분류·기간 연장 처리를 가져오지 않습니다.",
            "유형·무형 취득과 리스 원금을 따로 차감하고 사용권 상각을 되돌립니다. 주식보상은 영업이익 안에 남기는 현금보상 대체 가정입니다.",
            "매출 증가와 설비 확장은 GPU 투자 수익률이나 고객 수요의 인과 증거가 아닙니다. 자체 데이터센터와 정부 소유 GPU의 권리를 먼저 구분합니다.",
            "전환사채의 이자·상환·희석과 후속 가액 조정 때문에 주당 계산은 보류합니다. 초과현금·투자자산·소수주주별 배분도 별도 검토 대상입니다.",
        ],
        remaining=[
            "클라우드·AI 서비스와 기존 SI의 제품별 외부 매출·마진",
            "물류 운임·취급량·외주비와 삼성 계열 고객 노출",
            "기말 잔액 비율의 미래 지속성과 공급자별 지급 시점",
            "GPU 소유권·계약별 사용권·현금 투자와 리스",
            "전환·상환 경로별 권리와 현금·투자자산 배분",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
