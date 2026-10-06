"""NAVER single operating segment, source-bound cash and customer-fund limits."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract
from .naver_investments import build as investment_evidence

CURRENT = "20260814002266"
CORPUS = "829b89239fbd97611fd092f12dc7d74a98a2bb6c47da84be7f0aff28e8d0ed36"
CURRENT_SHA = "d2c1112408796ecddf462b96b0891c1e98d72b237b945b62051015b50d3e5a3c"
ANNUAL_SHA = "05cc24c7784ba0c7d8ae1314d59481f098619e9d3f77d51a7101712b3abb4446"
ANNUAL_DOC = "c872eecd699a5b3337da733e448d51570da122df8d4ac56702d03752521f9774"
CON = [("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")]
IND = CON + [
    (
        "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis",
        "ReportedAmountMember",
    )
]
TAGS = dict(
    revenue="Revenue",
    operatingIncome="OperatingIncomeLoss",
    netIncome="ProfitLoss",
    cfo="CashFlowsFromUsedInOperatingActivities",
    generated="CashFlowsFromUsedInOperations",
    interestReceived="InterestReceivedClassifiedAsOperatingActivities",
    interestPaid="InterestPaidClassifiedAsOperatingActivities",
    dividends="DividendsReceivedClassifiedAsOperatingActivities",
    taxCash="IncomeTaxesPaidRefundClassifiedAsOperatingActivities",
    depreciation="DepreciationPropertyPlantAndEquipment",
    amortization="AmortisationIntangibleAssetsOtherThanGoodwill",
    rou="DepreciationRightofuseAssets",
    ppe="PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    intangible="PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
    lease="PaymentsOfFinanceLeaseLiabilitiesClassifiedAsFinancingActivities",
    minority="ProfitLossAttributableToNoncontrollingInterests",
)
CASH = [
    ("generated", "영업에서 창출한 현금 (비현금·운전자본 합계 포함)", 1),
    ("interestReceived", "현금 이자 수취", 1),
    ("interestPaid", "현금 이자 지급", -1),
    ("dividends", "현금 배당 수취", 1),
    ("taxCash", "현금 법인세 지급", -1),
]
PASSAGES = [
    "54eada88c7482f71aac2",
    "f24bb0b28e55319f0170",
    "7d7de55530ca8b75ad68",
    "a478a354e70fb078d45a",
    "37057894b78e45be3329",
    "5f4095c3796a130e9873",
    "c702d5a8c2dfc387beaf",
    "365e9d8b0c4c8dd414d8",
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="네이버의 서비스 재분류·고객 자금과 현금 범위를 새 공시에서 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if (
        source["sha256"] != CURRENT_SHA
        or core["sourceHash"] != ANNUAL_SHA
        or core["accession"] != "20260313001021"
    ):
        raise ValueError("NAVER source identity changed")
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
                "NAVER fact missing: " + tag + " " + str(start) + " " + end
            )
        return r

    facts = {}
    for key, tag in TAGS.items():
        ps = [
            dict(
                coefficient=k,
                fact=exact(
                    rs,
                    tag,
                    start,
                    end,
                    IND if i and key in {"depreciation", "amortization"} else CON,
                ),
            )
            for i, (k, rs, start, end) in enumerate(periods)
        ]
        facts[key] = dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in ps),
            components=ps,
            unit="KRW",
            sourceUrl=source["url"],
        )
    v = lambda k: facts[k]["value"]
    checks = []
    for i, (_, rs, start, end) in enumerate(periods):
        val = lambda k: facts[k]["components"][i]["fact"]["value"]
        reconstructed = sum(sign * val(k) for k, _, sign in CASH)
        if reconstructed != val("cfo"):
            raise ValueError("NAVER cash-generated bridge failed")
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=val("cfo"),
                reconstructedCfo=reconstructed,
                residual=0,
                generated=val("generated"),
                netIncome=val("netIncome"),
                combinedNoncashAndWorking=val("generated") - val("netIncome"),
            )
        )
    trade = [
        exact(annual, tag, core["start"], core["end"], IND)
        for tag in [
            "AdjustmentsForDecreaseIncreaseInTradeAccountReceivable",
            "AdjustmentsForDecreaseIncreaseInInventories",
        ]
    ]
    prior_revenue = exact(annual, "Revenue", "2024-01-01", "2024-12-31")
    increase = (
        facts["revenue"]["components"][0]["fact"]["value"] - prior_revenue["value"]
    )
    working = sum(x["value"] for x in trade)
    sbc = exact(
        annual, "AdjustmentsForShareBasedPayment", core["start"], core["end"], IND
    )
    other_liabilities = exact(
        annual,
        "AdjustmentsForIncreaseDecreaseInOtherCurrentLiabilities",
        core["start"],
        core["end"],
        IND,
    )
    if increase <= 0:
        raise ValueError("NAVER annual growth anchor requires review")
    revenue = v("revenue")
    segment = dict(
        id="ConsolidatedPlatform",
        label="단일 연결 플랫폼 사업",
        revenue=revenue,
        margin=v("operatingIncome") / revenue,
        observedGrowth=facts["revenue"]["components"][1]["fact"]["value"]
        / facts["revenue"]["components"][2]["fact"]["value"]
        - 1,
        evidence=[facts["revenue"], facts["operatingIncome"]],
    )
    # Negative consolidated minority profit is not projected as a benefit to common holders.
    defaults = dict(
        segments=[dict(growthStart=0, growthEnd=0, marginEnd=segment["margin"])],
        tax=0.275,
        netInterest=(v("interestReceived") - v("interestPaid")) / revenue,
        depreciation=(v("depreciation") + v("amortization") + v("rou")) / revenue,
        workingCapital=-working / increase,
        capexStart=(v("ppe") + v("intangible")) / revenue,
        capexEnd=(v("ppe") + v("intangible")) / revenue,
        leaseStart=v("lease") / revenue,
        leaseEnd=v("lease") / revenue,
        minority=max(0, v("minority")) / revenue,
        discount=0.12,
        terminal=0.02,
        equityInvestmentValue=None,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    if any(p not in index for p in PASSAGES):
        raise ValueError("NAVER passages missing")
    manifest = json.loads(
        (ROOT / "data/sources/dart-document-20260313001021.manifest.json").read_text()
    )
    doc = next(x for x in manifest["files"] if x["sha256"] == ANNUAL_DOC)
    ps = extract(read_verified(ROOT / doc["file"], ANNUAL_DOC))
    selected_ids = {
        "4be4ad0e781ddff25691",
        "1bc0b35bbd8cc1182933",
        "b39b23f3a611457423a8",
        "1e433cadeeedd0384d42",
        "b9234694db279afcdff0",
        "164bf1acb36ea452ecb3",
    }
    selected = [p for p in ps if p["id"] in selected_ids]
    if len(selected) != len(selected_ids):
        raise ValueError("NAVER annual cash passages changed")
    item = dict(
        doc, provider="DART", url=manifest["url"], retrievedAt=manifest["retrievedAt"]
    )
    if item["file"] not in {s["file"] for s in c["sources"]}:
        c["sources"].append(item)
    m = dict(
        status="research_workspace",
        version="naver-platform-investment-scope-v2",
        sourcePeriod=["2025-07-01", f["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="KRW",
        displayScale=1e12,
        displayUnit="조 원",
        basisLabel="세 기간 연결 현금 대사 · 일부 연간 가정",
        groupLabel="단일 공시 영업부문",
        growthLabel="같은 상반기 대비",
        segments=[segment],
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        equityInvestmentPath=True,
        equityInvestments=investment_evidence(c, rows, list(index.values())),
        minorityPath=True,
        minorityScope="최근1년 비지배 손실을 미래 주주 현금의 가산 항목으로 반복하지 않습니다. 기본 배분 0은 미래 가정이며 당기 비지배 손익이 영이라는 뜻이 아닙니다.",
        netInterestLabel="현금 순이자 대용",
        capexLabel="유형·무형 현금 취득",
        leaseLabel="리스 원금",
        intro="서비스별 매출 분류와 단일 영업부문을 구분합니다. 네이버 플랫폼·파이낸셜·글로벌 서비스별 이익을 만들지 않으며, 연결 이익에서 투자·리스·세금과 비지배 배분 가정을 계산합니다.",
        businessCaption="서비스 분류 변경에 따른 매출 이동을 유기 성장으로 확정하지 않습니다. 연결 공통 마진은 개별 광고·결제·콘텐츠의 수익성을 식별하지 않습니다.",
        anchorSummary="반기에 간접현금 세부 조정이 없어 2025년 매출채권·재고 현금 효과만 같은 연간 매출 증가로 나눈 대용계수를 씁니다. 고객 예수금·정산금이 섞일 수 있는 기타부채 증가는 제외합니다. 이는 전체 운전자본의 정상 소요가 아닙니다. 순이자는 최근1년 수취−지급 대용, 세율27.5%는 연구 가정입니다.",
        bridgeLabel="창출 현금 → 이자·배당·세금 후 영업현금 대사",
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
        observedResidualLabel="최근1년 전체 주식보상 현금 대체액 미확인으로 관측 잔여 현금 미산정",
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=increase,
            workingPeriod=[core["start"], core["end"]],
            tradeFacts=trade,
            annualSbc=sbc,
            actualShareCompensationReplacement=None,
            excludedOtherLiabilityCash=other_liabilities,
            reportedMinorityProfit=v("minority"),
        ),
        customerFunds=dict(
            periods=[
                dict(
                    end="2024-12-31",
                    value=162541e6,
                    sourceUrl=manifest["url"],
                    sourceHash=ANNUAL_DOC,
                ),
                dict(
                    end="2025-12-31",
                    value=385584e6,
                    sourceUrl=manifest["url"],
                    sourceHash=ANNUAL_DOC,
                ),
                dict(
                    end="2026-06-30",
                    value=639676e6,
                    sourceUrl=source["url"],
                    sourceHash=CORPUS,
                ),
            ],
            additionalRestrictions=[
                dict(currency="JPY", value=1392e6),
                dict(currency="CAD", value=9e6),
            ],
            scope="한국 선불충전금 신탁 잔액입니다. 현금및현금성자산에 포함되지만 주주에게 자유 배분할 자산으로 더하지 않습니다. 일본·캐나다 제한예금은 별도 통화로 표시하고 임의 합산하지 않습니다. 잔액 증가가 영업현금 증가와 일치한다고 가정하지 않습니다.",
        ),
        cashAnchors=[
            dict(
                label=label,
                period=period,
                value=value,
                sourceUrl=source["url"] if period != "2025연간" else manifest["url"],
                scope=scope,
            )
            for label, period, value, scope in [
                (
                    "감가·무형·사용권 상각",
                    "최근1년",
                    v("depreciation") + v("amortization") + v("rou"),
                    "영업이익에 포함된 비용을 미래에 되돌림; 손상 제외",
                ),
                (
                    "현금표 주식보상 조정",
                    "2025연간",
                    sbc["value"],
                    "최근1년 전체 대체부담 아님; 미래 마진 안의 주식보상을 되돌리지 않음",
                ),
                (
                    "영업현금의 기타유동부채 증가",
                    "2025연간",
                    other_liabilities["value"],
                    "고객 자금 분리가 안 된 합계; 성장 자금 원천으로 반복하지 않음",
                ),
                (
                    "비지배 주주 귀속 손익",
                    "최근1년",
                    v("minority"),
                    "순손실을 미래 지배주주 현금에 가산하지 않음",
                ),
                (
                    "보고 영업현금의 배당 수취",
                    "최근1년",
                    v("dividends"),
                    "미래 사업 현금에는 제외; 지분법 투자 가치 미포함",
                ),
            ]
        ],
        passages=[index[p] for p in PASSAGES],
        historicalPassages=[
            dict(p, sourceUrl=manifest["url"], sourceHash=ANNUAL_DOC) for p in selected
        ],
        rules=[
            "연간+현재반기−전년반기 세 기간에서 창출 현금·이자·배당·법인세를 대사합니다. 창출 현금−순이익 차이는 비현금과 운전자본의 합계이며 원인을 임의 배분하지 않습니다.",
            "단일 영업부문 이익을 사용합니다. 서비스별 광고·커머스·금융 매출 비중만으로 독립 이익률을 만들지 않습니다.",
            "반기의 운전자본 상세는 미확인입니다. 연간 매출채권·재고만 사용한 좁은 대용은 연간 기간으로 표시하며 고객 정산금·예수금 증가를 자동 자금 조달로 가정하지 않습니다.",
            "고객 선불충전금 신탁은 현금에 포함되더라도 주주 초과현금에 더하지 않습니다. 해외 제한예금은 원화로 임의 합산하거나 이중 차감하지 않습니다.",
            "설비·무형 취득과 리스 원금을 차감하고 유형·무형·사용권 상각을 되돌립니다. 데이터센터 성장투자와 유지투자는 아직 분리하지 않습니다.",
            "마진에 포함된 주식보상은 비용으로 남깁니다. 연간 현금표 조정만 확인됐으므로 최근1년 전체 금액을 채워 넣지 않습니다.",
            "최근1년 비지배 손실은 반복 가산하지 않고 미래 배분0에서 시작합니다. 손실의 소멸·흑자 전환과 자회사별 배분은 다른 가정입니다.",
            "현금 순이자는 손익 순이자와 일치하지 않는 미래 대용 가정입니다. 세율27.5%·요구수익률·영구성장은 관측이나 회사 전망이 아닙니다.",
            "지분법 투자 손익과 수취 배당은 미래 영업이익에 더하지 않습니다. 투자자산 및 초과 현금 가치도 포함하지 않아 전체 적정가치 평가가 아닙니다.",
            "8월 자기주식 소각은 발행주식수와 자기주식수를 함께 줄여 유통수를 그대로 유지하는 사건입니다. 향후 주식보상용 보유 계획을 이미 발행된 희석주식으로 바꾸지 않습니다.",
        ],
        remaining=[
            "반기 영업자산·부채와 고객 정산 자금의 순현금 분리",
            "AI 데이터센터 유지·성장 투자 및 이용률",
            "서비스별 비용 배분과 글로벌 자회사 손익의 지속성",
            "관계기업 가치·자회사 지분 배분 및 미래 주식보상",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
