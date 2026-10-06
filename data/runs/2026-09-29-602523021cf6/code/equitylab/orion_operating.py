"""Orion: consolidated confectionery, geographic sales and separate investments."""

import copy
import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "20260818000305"
CORPUS = "6d89ba18d11dcac28fdb9a753f45a70d84d81d0a6346e4007728dbdc834ba4db"
SOURCE = "f14e26ce552195898de35fa84a56780bc1c2714678d4c8d68cc1e0de6d8bc8ec"
ANNUAL = "20260318001320"
ANNUAL_SHA = "282e0e1afec38b7d56a8f70db4c1f6f77a34c12125081856b9ffffebf0574e4a"
ANNUAL_DOC = "c5d35f8794757296037a238ceafebcd4ef60d59facfd6e34643e31716b64f02f"
CON = [("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")]
TAGS = dict(
    revenue="Revenue",
    operatingIncome="OperatingIncomeLoss",
    netIncome="ProfitLoss",
    minority="ProfitLossAttributableToNoncontrollingInterests",
    adjustments="AdjustmentsForReconcileProfitLoss",
    working="AdjustmentsForAssetsLiabilitiesOfOperatingActivities",
    cfo="CashFlowsFromUsedInOperatingActivities",
    interestPaid="InterestPaidClassifiedAsOperatingActivities",
    interestReceived="InterestReceivedClassifiedAsOperatingActivities",
    taxPaid="IncomeTaxesPaidClassifiedAsOperatingActivities",
    capex="PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    intangibles="PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
    lease="PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities",
    depreciation="AdjustmentsForDepreciationExpense",
    rou="AdjustmentsForDepreciationRightofuseAssets",
    propertyDep="AdjustmentsForDepreciationInvestmentProperty",
    amortization="AdjustmentsForAmortisationExpense",
    interestExpense="AdjustmentsForInterestExpenses",
    equityIncome="ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
    associatePurchase="PurchaseOfInterestsInAssociates",
    dividend="DividendsReceivedClassifiedAsInvestingActivities",
)
CASH = [
    ("netIncome", "연결 순이익", 1),
    ("adjustments", "손익의 비현금 등 조정", 1),
    ("working", "영업자산·부채 현금 변동", 1),
    ("interestPaid", "영업현금 이자 지급", -1),
    ("interestReceived", "영업현금 이자 수취", 1),
    ("taxPaid", "법인세 지급", -1),
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="오리온의 지역 매출·투자 취득·후속 바이오 투자를 새 공시에서 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    af = c["trailingYear"]["values"]["cfo"]["components"][0]["fact"]
    annual_source = next(s for s in c["sources"] if s["file"] == af["sourceFile"])
    doc = json.loads(
        (
            DOCUMENT_ROOT / f"data/sources/dart-document-{ANNUAL}.manifest.json"
        ).read_text()
    )
    document = next(x for x in doc["files"] if x["originalName"] == ANNUAL + ".xml")
    if (
        source["sha256"] != SOURCE
        or annual_source["sha256"] != ANNUAL_SHA
        or af["accession"] != ANNUAL
        or document["sha256"] != ANNUAL_DOC
        or doc["receipt"] != ANNUAL
        or as_of < "2026-08-18"
    ):
        raise ValueError("Orion source identity or date changed")
    if [c["financials"]["start"], c["financials"]["end"]] != [
        "2026-01-01",
        "2026-06-30",
    ]:
        raise ValueError("Orion reporting period changed")
    annual = instance_rows(
        read_verified(ROOT / annual_source["file"], ANNUAL_SHA),
        c,
        annual_source,
        ANNUAL,
        "2026-03-18",
    )
    periods = [
        (1, annual, "2025-01-01", "2025-12-31"),
        (1, rows, "2026-01-01", "2026-06-30"),
        (-1, rows, "2025-01-01", "2025-06-30"),
    ]
    url = c["financials"]["current"]["cfo"]["sourceUrl"]

    def exact(rs, tag, start, end, dims=CON):
        fact = select(rs, tag, start, end, dims, "KRW")
        if fact is None:
            raise ValueError(f"Orion missing fact {tag} {start} {end}")
        return fact

    def combined(tag):
        parts = [
            dict(coefficient=k, fact=exact(rs, tag, start, end))
            for k, rs, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            sourceUrl=url,
            unit="KRW",
        )

    facts = {k: combined(tag) for k, tag in TAGS.items()}
    v = lambda k: facts[k]["value"]
    cash_periods = []
    for i, (_, _, start, end) in enumerate(periods):
        parts = [
            dict(
                label=label,
                value=sign * facts[key]["components"][i]["fact"]["value"],
                fact=facts[key]["components"][i]["fact"],
            )
            for key, label, sign in CASH
        ]
        cfo = facts["cfo"]["components"][i]["fact"]["value"]
        if sum(p["value"] for p in parts) != cfo:
            raise ValueError("Orion period cash does not reconcile")
        cash_periods.append(
            dict(start=start, end=end, parts=parts, reportedCfo=cfo, residual=0)
        )
    geographic = []
    for member, label in [
        ("CountryOfDomicileMember", "본사 소재지"),
        ("CNMember", "중국"),
        ("OtherCountriesMember", "기타 국가"),
    ]:
        dims = CON + [("GeographicalAreasAxis", member)]
        cur = exact(rows, "Revenue", "2026-01-01", "2026-06-30", dims)
        prev = exact(rows, "Revenue", "2025-01-01", "2025-06-30", dims)
        geographic.append(
            dict(
                label=label,
                current=cur,
                previous=prev,
                growth=cur["value"] / prev["value"] - 1,
                operatingMargin=None,
            )
        )
    geography_residuals = [
        facts["revenue"]["components"][i]["fact"]["value"]
        - sum(g[key]["value"] for g in geographic)
        for i, key in [(1, "current"), (2, "previous")]
    ]
    if any(abs(r) >= 1000 for r in geography_residuals):
        raise ValueError("Orion geographic sales exceed disclosed precision")
    # The annual net business-combination caption differs from interim acquisition.
    # The exact difference is acquired cash, verified in the annual acquisition note.
    # Preserve raw arithmetic and reconcile both periods on a gross-consideration basis.
    acquisition = [
        exact(rs, tag, start, end)
        for (_, rs, start, end), tag in zip(
            periods,
            [
                "DecreaseDueToBusinessCombinationOfCashFlowsFromUsedInInvestingActivities",
                "PurchaseOfInvestmentsInSubsidiaries",
                "PurchaseOfInvestmentsInSubsidiaries",
            ],
        )
    ]
    acquisition_arithmetic = (
        acquisition[0]["value"] + acquisition[1]["value"] - acquisition[2]["value"]
    )
    acquisition_dims = CON + [
        (
            "BusinessCombinationsAxis",
            "MyPhuoc3ConfectionieryCoLtdMemberOfEntitysTotalForBusinessCombinationsMemberOfCarryingAmountOfAssetsAcquiredAndLiabilitiesAssumedAtAcquisitionDateTableOfMember",
        )
    ]
    consideration_dims = CON + [
        (
            "BusinessCombinationsAxis",
            "MyPhuoc3ConfectionieryCoLtdMemberOfEntitysTotalForBusinessCombinationsMemberOfConsiderationtransferreddetailsrelatedtobusinesscombinationTableOfMember",
        )
    ]
    consideration = exact(annual, "Cash", None, "2025-12-31", consideration_dims)
    acquired_cash = exact(
        annual,
        "CashAndCashEquivalentsRecognisedAsOfAcquisitionDate",
        None,
        "2025-12-31",
        acquisition_dims,
    )
    if (
        consideration["value"] - acquired_cash["value"] != acquisition[0]["value"]
        or consideration["value"] != acquisition[2]["value"]
    ):
        raise ValueError("Orion consideration/acquired cash no longer reconciles")
    normalized_acquisition = (
        consideration["value"] + acquisition[1]["value"] - acquisition[2]["value"]
    )
    acquisition_ratio = (
        acquisition[0]["value"] / facts["revenue"]["components"][0]["fact"]["value"]
    )
    stock = [
        dict(coefficient=k, label=label, fact=exact(rows, tag, None, "2026-06-30"))
        for k, label, tag in [
            (1, "순매출채권", "CurrentTradeReceivables"),
            (1, "재고", "Inventories"),
            (-1, "매입채무", "TradeAndOtherCurrentPayablesToTradeSuppliers"),
        ]
    ]
    stock_net = sum(p["coefficient"] * p["fact"]["value"] for p in stock)
    investment_book = exact(
        rows, "InvestmentAccountedForUsingEquityMethod", None, "2026-06-30"
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    annual_index = {
        p["id"]: p
        for p in extract(read_verified(DOCUMENT_ROOT / document["file"], ANNUAL_DOC))
    }
    for pid, marker in [
        ("dddd643361b6034c6927", "제과부문"),
        ("d971f057969240f00c88", "2026.07.24"),
        ("05fc56cd07bf337633f7", "684,549,080"),
        ("a8ceb1f08f3fd31ce5fa", "10,738,104,000"),
    ]:
        if marker not in index[pid]["text"]:
            raise ValueError("Orion current scope text changed")
    if "10,737,930,000" not in annual_index["2001864c76493f0d3c89"]["text"]:
        raise ValueError("Orion annual acquisition scope changed")
    document_source = dict(
        document, provider="OpenDART", url=doc["url"], retrievedAt=doc["retrievedAt"]
    )
    if document_source["file"] not in {x["file"] for x in c["sources"]}:
        c["sources"].append(document_source)
    revenue = v("revenue")
    reinvestment = (
        v("capex") + v("intangibles") + v("associatePurchase")
    ) / revenue + acquisition_ratio
    segments = [
        dict(
            id="consolidated-confectionery",
            label="제과 중심 연결 전체",
            revenue=revenue,
            margin=v("operatingIncome") / revenue,
            observedGrowth=facts["revenue"]["components"][1]["fact"]["value"]
            / facts["revenue"]["components"][2]["fact"]["value"]
            - 1,
            evidence=[facts["revenue"], facts["operatingIncome"]],
        )
    ]
    defaults = dict(
        segments=[dict(growthStart=0, growthEnd=0, marginEnd=segments[0]["margin"])],
        tax=0.25,
        netInterest=-v("interestExpense") / revenue,
        depreciation=sum(
            v(k) for k in ["depreciation", "rou", "propertyDep", "amortization"]
        )
        / revenue,
        workingCapital=stock_net / revenue,
        capexStart=reinvestment,
        capexEnd=reinvestment,
        leaseStart=v("lease") / revenue,
        leaseEnd=v("lease") / revenue,
        minority=max(0, v("minority")) / revenue,
        discount=0.12,
        terminal=0.02,
    )
    hold = "결산 후 바이오 취득의 자금·자산 변동과 투자 가치 배분이 미대사입니다. 관계·공동기업 장부금액을 공정가치로 더하지 않으며 전체 주당·역산 계산을 보류합니다."
    security = copy.deepcopy(c["valuation"]["security"])
    security.update(
        status="unresolved",
        marketCapProxy=None,
        issues=list(security.get("issues", [])) + [hold],
    )
    parts = [
        dict(
            label=label,
            value=sign * v(key),
            fact=dict(
                sourceUrl=url,
                components=[
                    dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                    for p in facts[key]["components"]
                ],
            ),
        )
        for key, label, sign in CASH
    ]
    m = dict(
        status="research_workspace",
        version="orion-confectionery-investments-v2",
        sourcePeriod=["2025-07-01", "2026-06-30"],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="KRW",
        displayScale=1e12,
        displayUnit="조 원",
        basisLabel="연결 제과·지역 매출·투자 범위 대사",
        groupLabel="연결 사업 손익",
        growthLabel="같은 반기 대비",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=security,
        priceHoldReason=hold,
        minorityPath=True,
        minorityScope="최근1년 비지배 순이익/매출을 미래 귀속 부담으로 가정합니다. 실제 배당 지급이나 모든 해외법인의 송금 가능액은 아닙니다.",
        capexLabel="설비·무형·관계기업 및 연간 인수 대용",
        leaseLabel="리스 원금 지급 가정",
        netInterestLabel="공시 총이자 비용",
        intro="제과 중심 연결 영업이익에서 시작합니다. 지역별 외부 매출은 따로 비교하며 국가별 영업이익을 만들지 않습니다. 바이오 관계기업 손익과 후속 투자·주식 권리는 제과 제품의 성과와 분리합니다.",
        businessCaption="주석의 동기 반기를 사용합니다. 사업 설명의 반기·연간 표나 내부거래가 포함된 해외법인 별도 합계를 연결 성장률로 사용하지 않습니다. 원화 지역 성장에는 환율·제품 구성·가격과 물량이 함께 반영될 수 있습니다.",
        anchorSummary="순채권+재고−매입채무의 기말 잔액을 증가 매출의 자금 대용으로 사용합니다. 성장0·세율25%·현재 마진 반복은 연구 가정입니다. 연간 인수 지출 비율을 임시 미래 부담에 포함하되 음수 최근1년 산술은 현금 유입으로 쓰지 않습니다.",
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            periods=cash_periods,
            residual=0,
            cashAfterInvestmentLeaseSbc=None,
        ),
        observedResidualLabel="투자·비지배·전체 보상 배분 검토 필요",
        anchors=dict(
            workingStockTerms=stock,
            workingStockNet=stock_net,
            actualFinanceLeasePrincipal=v("lease"),
            shareCompensationReplacement=None,
            reportedMinorityProfit=v("minority"),
        ),
        confectioneryEvidence=dict(
            geographies=geographic,
            geographyResiduals=geography_residuals,
            acquisitionPeriods=acquisition,
            acquisitionArithmetic=acquisition_arithmetic,
            acquisitionAdopted=normalized_acquisition,
            acquiredCash=acquired_cash,
            consideration=consideration,
            acquisitionReconciliationResidual=consideration["value"]
            - acquired_cash["value"]
            - acquisition[0]["value"],
            acquisitionProxyRatio=acquisition_ratio,
            associateBook=investment_book,
            equityIncome=facts["equityIncome"],
            dividends=facts["dividend"],
            postBalanceInvestment=dict(
                disclosedAcquisitionDate="2026-07-24",
                preferred=82500000000,
                convertible=42500000000,
                total=125000000000,
                cashSettlementConfirmed=False,
                source=index["d971f057969240f00c88"],
            ),
            periods=cash_periods,
            workingStockTerms=stock,
            workingStockNet=stock_net,
        ),
        cashAnchors=[
            dict(label=label, period=period, value=value, sourceUrl=url, scope=scope)
            for label, period, value, scope in [
                (
                    "설비·무형 취득",
                    "최근1년",
                    v("capex") + v("intangibles"),
                    "매각대금과 상계하지 않은 취득",
                ),
                (
                    "관계·공동기업 취득",
                    "최근1년",
                    v("associatePurchase"),
                    "반복 제과 성장과 구분; 초기 재투자에 포함",
                ),
                (
                    "종속기업 취득 산술",
                    "연간+반기−전년반기",
                    acquisition_arithmetic,
                    "총대가/순지급 차이는 취득 현금으로 대사. 현금 회수 아님",
                ),
                (
                    "연간 인수 지출 대용",
                    "2025 연간",
                    acquisition[0]["value"],
                    "연간 매출 대비 비율을 미래 가정에 임시 포함",
                ),
                (
                    "리스 원금 지급",
                    "최근1년",
                    v("lease"),
                    "사용권 상각 되돌림과 함께 한 번 차감",
                ),
                (
                    "감가·무형·사용권 상각",
                    "최근1년",
                    sum(
                        v(k)
                        for k in ["depreciation", "rou", "propertyDep", "amortization"]
                    ),
                    "영업이익에 한 번 가산; 주식보상 추가 가산 없음",
                ),
                (
                    "관계·공동기업 장부금액",
                    "2026-06-30",
                    investment_book["value"],
                    "시장가치·순처분가치 아님, 제과 현금에 더하지 않음",
                ),
                (
                    "전체 주식보상 대체액",
                    "자료 미확인",
                    None,
                    "미확인을 영으로 승인하지 않음",
                ),
            ]
        ],
        passages=[
            index[pid]
            for pid in [
                "dddd643361b6034c6927",
                "7052f6237b08df04c00e",
                "e248b3acb06314f6bc59",
                "a63e94da9604c64a48f2",
                "05fc56cd07bf337633f7",
                "d971f057969240f00c88",
                "a043b6896b068f667fba",
                "ab6c83a75e3175415cf8",
                "a8ceb1f08f3fd31ce5fa",
            ]
        ],
        historicalPassages=[
            dict(annual_index[pid], sourceUrl=doc["url"], sourceHash=ANNUAL_DOC)
            for pid in [
                "2001864c76493f0d3c89",
                "dc94089d265603d524cd",
                "0a36455eace27b550267",
            ]
        ],
        rules=[
            "연간+현재반기−전년반기의 순이익·비현금·자금 변동·이자·세금으로 보고 영업현금을 모두 대사한다.",
            "국가별 외부 매출과 법인별 내부거래 포함 별도 실적을 구분한다. 천원 단위 지역 합계와 원 단위 연결의 반올림 잔차를 보존한다.",
            "연간 순지급액에 인수 현금을 더하면 전년반기의 총취득대가와 일치한다. 같은 총대가 기준 최근1년 취득은 영이다. 원래 음수 산술은 회수가 아니며 미래에 쓰는 연간 비율은 별도 임시 가정이다.",
            "연결 영업이익에서 출발하므로 지분법 손실을 다시 가산하지 않는다. 투자활동 수취 배당과 금융자산 이자수입은 미래 제과 현금에 반복하지 않는다.",
            "결산 후 공개된 리가켐 전환우선주·전환사채 취득은 6월 현금도 미래 반복 제과 지출도 아니다. 실제 결제·자산 변동·세금·비지배 귀속을 대사하기 전 가격 계산을 보류한다.",
            "총이자 비용은 세전 현금 효과에서 차감한다. 리스 원금과 이자, 사용권 상각을 각각 한 번만 반영한다.",
        ],
        remaining=[
            "현지 통화 판매량·순단가·환율·원가의 분해",
            "공장 투자·리스 이전 후 반복 지출과 가동률",
            "바이오 투자 취득 후 현금·권리·순투자 가치와 비지배 배분",
            "전체 보상 대체비와 해외 자금의 송금 가능 범위",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
