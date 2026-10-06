"""Source-bound Mobis candidate; reserve use and reported cash differ."""

import json
from datetime import date, timedelta
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "20260814004065"
CORPUS = "49a752e3ba45479100d3f11b36ce582872f702776b8f4d8232d36726132dd07d"
CURRENT_SHA = "164c0544921c44480b993f95663e7734379af9dcf888f3d49e176ea71b6e87e5"
ANNUAL_SHA = "335a4ade6cbb46fa5850f8fdff742aea93781c71baf5d1526ed1777776c718de"
ANNUAL_DOC = "eebafd129bd1737e521603057c7827ce3e9492454cffc53f37d7461574358ac3"
CON = [("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")]
IND = CON + [
    (
        "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis",
        "ReportedAmountMember",
    )
]
WAR = CON + [("ClassesOfProvisionsAxis", "WarrantyProvisionMember")]
SEGMENTS = [
    ("AutoParts", "모듈·부품 제조"),
    ("PartsOfAfterSalesServices", "A/S용 부품"),
]
TAGS = dict(
    revenue=("Revenue", CON),
    operatingIncome=("OperatingIncomeLoss", CON),
    netIncome=("ProfitLoss", CON),
    cfo=("CashFlowsFromUsedInOperatingActivities", CON),
    adjustments=("AdjustmentsForReconcileProfitLoss", IND),
    working=("AdjustmentsForAssetsLiabilitiesOfOperatingActivities", IND),
    interestReceived=("InterestReceivedClassifiedAsOperatingActivities", CON),
    interestPaid=("InterestPaidClassifiedAsOperatingActivities", CON),
    dividends=("DividendsReceivedClassifiedAsOperatingActivities", CON),
    taxCash=("IncomeTaxesPaidRefundClassifiedAsOperatingActivities", CON),
    interestIncome=("InterestIncomeFinanceIncome", CON),
    interestExpense=("InterestExpenseFinanceExpense", CON),
    depreciation=("AdjustmentsForDepreciationExpense", IND),
    amortization=("AdjustmentsForAmortisationExpense", IND),
    rou=("AdjustmentsForDepreciationRightofuseAssets", IND),
    investmentDepreciation=("AdjustmentsForDepreciationInvestmentProperty", IND),
    ppe=("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", CON),
    intangible=("PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities", CON),
    lease=("PaymentsOfFinanceLeaseLiabilitiesClassifiedAsFinancingActivities", CON),
    minority=("ProfitLossAttributableToNoncontrollingInterests", CON),
    warrantyAdjustment=("AdjustmentsForProductWarrantyExpenses", IND),
    warrantyCfUse=(
        "AdjustmentsForIncreaseDecreaseInProvisionsForProductWarranties",
        IND,
    ),
    warrantyAdded=("AdditionalProvisionsOtherProvisions", WAR),
    warrantyUsed=("ProvisionUsedOtherProvisions", WAR),
    warrantyOther=(
        "IncreaseDecreaseThroughTransfersAndOtherChangesOtherProvisions",
        WAR,
    ),
    equityGain=(
        "AdjustmentsForProfitsOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
        IND,
    ),
    equityLoss=(
        "AdjustmentsForLossesOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
        IND,
    ),
)
CASH = [
    ("netIncome", "연결 순이익", 1),
    ("adjustments", "현금표 손익·비현금 조정", 1),
    ("working", "영업자산·부채 변동 합계", 1),
    ("interestReceived", "현금 이자 수취", 1),
    ("interestPaid", "현금 이자 지급", -1),
    ("dividends", "현금 배당 수취", 1),
    ("taxCash", "현금 법인세 지급", -1),
]
PASSAGES = [
    "a5ba7df341c975f48101",
    "4089ba060538d0c993fe",
    "7fd4a73c76eb24a908c4",
    "7346fd6075eea262d086",
    "56340a49400bc33bf487",
    "8d6308164535254f3810",
    "80abcc3fa5b974fe8b28",
    "6e60a790ad1ff5183471",
    "0e4c616af301d8285efd",
    "fd1d28af5cf9e3dde684",
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="모비스의 부문 내부거래·보증 변제자산과 현금 범위를 새 공시에서 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if (
        source["sha256"] != CURRENT_SHA
        or core["sourceHash"] != ANNUAL_SHA
        or core["accession"] != "20260309001878"
    ):
        raise ValueError("Mobis source identity changed")
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
            raise ValueError(
                "Mobis fact missing: " + tag + " " + str(start) + " " + end
            )
        return r

    def combined(tag, dims=CON):
        ps = [
            dict(coefficient=k, fact=exact(rs, tag, start, end, dims))
            for k, rs, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in ps),
            components=ps,
            unit="KRW",
            sourceUrl=source["url"],
        )

    facts = {k: combined(tag, dims) for k, (tag, dims) in TAGS.items()}
    v = lambda k: facts[k]["value"]
    segment_rows = []
    for prefix, label in SEGMENTS:
        dims = CON + [
            ("SegmentConsolidationItemsAxis", "OperatingSegmentsMember"),
            (
                "SegmentsAxis",
                prefix
                + "MemberOfReportableSegmentsMemberOfDisclosureOfOperatingSegmentsTableOfMember",
            ),
        ]
        revenue = combined("Revenue", dims)
        profit = combined("OperatingIncomeLoss", dims)
        segment_rows.append(
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
    eliminations = CON + [
        ("SegmentConsolidationItemsAxis", "EliminationOfIntersegmentAmountsMember")
    ]
    removed_revenue = combined("Revenue", eliminations)
    removed_profit = combined("OperatingIncomeLoss", eliminations)
    checks = []
    warranties = []
    for i, (_, rs, start, end) in enumerate(periods):
        val = lambda k: facts[k]["components"][i]["fact"]["value"]
        gross = sum(
            s["evidence"][0]["components"][i]["fact"]["value"] for s in segment_rows
        )
        income = sum(
            s["evidence"][1]["components"][i]["fact"]["value"] for s in segment_rows
        )
        eliminated = removed_revenue["components"][i]["fact"]["value"]
        profit_adj = removed_profit["components"][i]["fact"]["value"]
        cash = sum(sign * val(k) for k, _, sign in CASH)
        if (
            cash != val("cfo")
            or gross + eliminated != val("revenue")
            or income + profit_adj != val("operatingIncome")
        ):
            raise ValueError("Mobis period cash or consolidation reconciliation failed")
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=cash,
                residual=0,
                revenueResidual=0,
                incomeResidual=0,
                segmentRevenue=gross,
                internalRevenue=-eliminated,
                consolidatedRevenue=val("revenue"),
                unallocatedOperatingIncome=profit_adj,
            )
        )
        opening = exact(
            rs,
            "OtherProvisions",
            None,
            (date.fromisoformat(start) - timedelta(days=1)).isoformat(),
            WAR,
        )
        closing = exact(rs, "OtherProvisions", None, end, WAR)
        if (
            opening["value"]
            + val("warrantyAdded")
            - val("warrantyUsed")
            + val("warrantyOther")
            != closing["value"]
        ):
            raise ValueError("Mobis warranty reserve failed")
        warrants = dict(
            start=start,
            end=end,
            opening=opening,
            closing=closing,
            added=val("warrantyAdded"),
            used=val("warrantyUsed"),
            other=val("warrantyOther"),
            cashExpenseAdjustment=val("warrantyAdjustment"),
            cashUseAdjustment=val("warrantyCfUse"),
            usageLessCashAdjustment=val("warrantyUsed") + val("warrantyCfUse"),
            additionLessCashExpense=val("warrantyAdded") - val("warrantyAdjustment"),
            reimbursementAsset=select(
                rs,
                "AssetRecognisedForExpectedReimbursementOtherProvisions",
                None,
                end,
                IND,
                "KRW",
            ),
            residual=0,
        )
        warranties.append(warrants)
    revenue = v("revenue")
    gross = sum(s["revenue"] for s in segment_rows)
    trade = [
        exact(rows, tag, f["start"], f["end"], IND)
        for tag in [
            "AdjustmentsForDecreaseIncreaseInTradeAccountReceivable",
            "AdjustmentsForDecreaseIncreaseInInventories",
            "AdjustmentsForIncreaseDecreaseInTradeAccountPayable",
        ]
    ]
    working = sum(r["value"] for r in trade)
    increase = (
        facts["revenue"]["components"][1]["fact"]["value"]
        - facts["revenue"]["components"][2]["fact"]["value"]
    )
    if increase <= 0 or v("minority") < 0:
        raise ValueError("Mobis normalizing ratios require review")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"])
            for s in segment_rows
        ],
        tax=0.275,
        netInterest=(v("interestIncome") - v("interestExpense")) / revenue,
        depreciation=sum(
            v(k)
            for k in ["depreciation", "amortization", "rou", "investmentDepreciation"]
        )
        / revenue,
        workingCapital=-working / increase,
        capexStart=(v("ppe") + v("intangible")) / revenue,
        capexEnd=(v("ppe") + v("intangible")) / revenue,
        leaseStart=v("lease") / revenue,
        leaseEnd=v("lease") / revenue,
        discount=0.12,
        terminal=0.02,
        eliminationStart=-removed_revenue["value"] / gross,
        eliminationEnd=-removed_revenue["value"] / gross,
        otherProfitStart=removed_profit["value"] / revenue,
        otherProfitEnd=removed_profit["value"] / revenue,
        minority=v("minority") / revenue,
        warrantyAccrual=v("warrantyAdjustment") / revenue,
        warrantyUseStart=-v("warrantyCfUse") / revenue,
        warrantyUseEnd=-v("warrantyCfUse") / revenue,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    if any(p not in index for p in PASSAGES):
        raise ValueError("Mobis passages missing")
    manifest = json.loads(
        (
            DOCUMENT_ROOT / "data/sources/dart-document-20260309001878.manifest.json"
        ).read_text()
    )
    doc = next(x for x in manifest["files"] if x["sha256"] == ANNUAL_DOC)
    ps = extract(read_verified(DOCUMENT_ROOT / doc["file"], ANNUAL_DOC))
    selected = [p for p in ps if p["ordinal"] in [375, 751, 752, 753, 759, 762]]
    if len(selected) != 6:
        raise ValueError("Mobis annual paragraphs missing")
    item = dict(
        doc, provider="DART", url=manifest["url"], retrievedAt=manifest["retrievedAt"]
    )
    if item["file"] not in {s["file"] for s in c["sources"]}:
        c["sources"].append(item)
    m = dict(
        status="research_workspace",
        version="mobis-consolidation-warranty-cash-v1",
        sourcePeriod=["2025-07-01", f["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="KRW",
        displayScale=1e12,
        displayUnit="조 원",
        basisLabel="세 기간을 대사한 최근1년",
        growthLabel="같은 상반기 대비 내부매출 포함",
        groupLabel="두 공시 사업부",
        segments=segment_rows,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        consolidationPath=True,
        reservePath=True,
        consolidation=dict(
            periods=checks,
            segmentRevenue=gross,
            internalRevenue=-removed_revenue["value"],
            reportedRevenue=revenue,
            unallocatedOperatingIncome=removed_profit["value"],
            adjustmentLabel="공시 내부이익 제거",
            scope="두 부문 손익에 배분되지 않은 연결 내부이익 제거를 공시 총액으로 반영합니다. 공시된 조정이며 미표시 잔차가 아닙니다.",
        ),
        warrantyAccrualLabel="현금표 보증비 조정",
        warrantyUseLabel="현금표 보증 변동 대용",
        warrantyStressMode="settlement_only",
        netInterestLabel="이자수익 − 이자비용",
        capexLabel="유형·무형 현금 취득",
        leaseLabel="리스 원금",
        intro="모듈·부품 제조와 A/S용 부품의 내부거래 포함 손익에서 연결 제거를 분리합니다. 보증충당부채의 사용액과 현금표 변동액을 각각 대사하고, 제3자 변제자산이 있는 보증을 전액 직접 현금 지급으로 바꾸지 않습니다.",
        businessCaption="A/S 매출에는 내부거래가 포함됩니다. 부문 매출과 연결 외부매출을 구분하며 부문간 거래 제거율과 이익 제거액은 서로 다른 항목입니다. 모듈 적자를 A/S 이익과 혼합한 단일 마진만으로 설명하지 않습니다.",
        anchorSummary="매출채권·재고·매입채무의 현금 효과만 매출 증가의 대용계수로 사용합니다. 변제자산이 섞일 수 있는 기타 자산, 보증·퇴직·세금·금융상품 변동은 성장 대용에서 제외합니다. 세율27.5%와 요구수익률은 연구 가정입니다.",
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
            cashAfterInvestmentLeaseSbc=None,
        ),
        observedResidualLabel="전체 주식보상 대체액 미확인으로 관측 배분 현금 미산정",
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=increase,
            tradeFacts=trade,
            warrantyReconciliationPeriods=warranties,
            actualShareCompensationReplacement=None,
            dividendCash=v("dividends"),
            equityMethodNetIncome=v("equityGain") - v("equityLoss"),
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
                    "보증충당부채 사용",
                    "현재상반기",
                    warranties[1]["used"],
                    "총액 사용; 현금표 보증 변동과 다름",
                ),
                (
                    "현금표 보증 변동",
                    "현재상반기",
                    -warranties[1]["cashUseAdjustment"],
                    "부담 대용; 직접 지급과 동일하다고 확정하지 않음",
                ),
                (
                    "사용과 현금표 변동의 차이",
                    "현재상반기",
                    warranties[1]["usageLessCashAdjustment"],
                    "미대사 차이를 전부 현금 회수라고 만들지 않음",
                ),
                (
                    "제3자 변제자산",
                    "2026-06-30",
                    warranties[1]["reimbursementAsset"]["value"],
                    "잔액이며 당기 회수현금 아님",
                ),
                (
                    "보고 영업현금의 배당 수취",
                    "최근1년",
                    v("dividends"),
                    "미래 반복 사업 현금에는 제외",
                ),
                (
                    "지분법 순이익",
                    "최근1년",
                    v("equityGain") - v("equityLoss"),
                    "영업이익·현금 배당과 구분, 투자자산 가치 별도 미포함",
                ),
                (
                    "전체 주식보상 대체 부담",
                    "최근1년",
                    None,
                    "발견한 임금 조정을 전체 주식보상으로 확정하지 않음",
                ),
            ]
        ],
        passages=[index[p] for p in PASSAGES],
        historicalPassages=[
            dict(p, sourceUrl=manifest["url"], sourceHash=ANNUAL_DOC) for p in selected
        ],
        rules=[
            "원 연간+현재 상반기−전년 상반기로 연결하며 각 기간의 현금·내부매출·내부이익 제거를 먼저 대사합니다.",
            "부문 총매출에서 내부매출을 제거하고 부문 이익에서 공시된 내부이익 제거를 별도로 반영합니다. 미래 제거율과 순조정은 독립적인 연구 가정입니다.",
            "보증 신규 충당, 현금표 보증비 조정, 충당부채 사용, 현금표 보증 변동이 같지 않습니다. 각 차이와 변제자산을 남기며 회수현금이나 결함률을 만들어 채우지 않습니다.",
            "미래 현금표 보증비 조정을 되돌린 뒤 보증 변동 대용을 차감합니다. 미대사 차이 때문에 정상 보증 현금으로 승인하지 않습니다. 별도 부담 스트레스를 검토합니다.",
            "배터리셀 거래구조 변경에 따른 273,452백만원 보증의무와 동일 금액 변제자산 환입을 매출 성장·현금 유입으로 바꾸지 않습니다.",
            "유형·무형 취득과 리스 원금을 따로 차감합니다. 감가·상각에는 사용권 상각을 포함하며 리스 이자는 이자비용 안에 남깁니다.",
            "관계기업 지분법손익과 배당현금을 구분합니다. 미래 계산은 본업 영업이익과 순이자만 사용하며 투자자산 가치를 더하지 않아 지분법 투자 전체의 적정가치가 아닙니다.",
            "공급자금융약정 장부잔액은 지급 현금이 아닙니다. 만기·공급자 수령·회사 지급을 구분하고 지급조건 연장을 임의 가정하지 않습니다.",
            "보통주·우선주 권리 배분을 아직 확인하지 않아 주당 가치는 보류합니다. 전체 주식보상 미확인을 영으로 표시하지 않습니다.",
        ],
        remaining=[
            "보증 총사용과 현금표 변동의 차이·변제 회수 기간 대사",
            "전동화 모듈의 고객별 수익성·추가 설비투자",
            "A/S 외부매출과 내부마진의 지속성",
            "지분법 투자·보유 현금과 보통/우선주 권리 배분",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
