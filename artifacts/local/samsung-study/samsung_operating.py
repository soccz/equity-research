"""Samsung's gross segment sales, consolidation and separately observed cash."""

import json
from .data import ROOT, canonical, digest, read_verified
from .narrative import load, extract
from .xbrl import company_filing, instance_rows, select

DOCUMENT_ROOT = ROOT / "artifacts/local/samsung-study"
CURRENT = "20260814003699"
CORPUS = "a440da29601475dc70793fc6189e5ab7f8905a603367885313c0fd1805ec9bfb"
CURRENT_SHA = "03888e356c499e3643712810c7ba66e11a65ba490d209463e19000b4fb36074e"
ANNUAL_SHA = "28c27272eacc7bc9364ece8951da38039e915adff27e81924c1444b354223c07"
ANNUAL_DOC = "d31bac56ff210dfc52fc0b4d8457116371a21dd5203364e6367a8f5cf64dc60c"
CON = [("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")]
IND = sorted(
    CON
    + [
        (
            "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis",
            "ReportedAmountMember",
        )
    ]
)
TAGS = dict(
    revenue="Revenue",
    operatingIncome="OperatingIncomeLoss",
    netIncome="ProfitLoss",
    adjustments="AdjustmentsForReconcileProfitLoss",
    working="AdjustmentsForAssetsLiabilitiesOfOperatingActivities",
    cfo="CashFlowsFromUsedInOperatingActivities",
    interestReceived="InterestReceivedClassifiedAsOperatingActivities",
    interestPaid="InterestPaidClassifiedAsOperatingActivities",
    dividends="DividendsReceivedClassifiedAsOperatingActivities",
    taxCash="IncomeTaxesPaidRefundClassifiedAsOperatingActivities",
    depreciation="DepreciationExpense",
    amortization="AmortisationExpense",
    ppe="PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    intangible="PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
    lease="PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities",
    minority="ProfitLossAttributableToNoncontrollingInterests",
)
WORKING = {
    "receivables": "AdjustmentsForDecreaseIncreaseInTradeAccountReceivable",
    "otherReceivables": "AdjustmentsForDecreaseincreaseInOtherReceivables",
    "prepaids": "AdjustmentsForDecreaseIncreaseInPrepaidExpenses",
    "inventory": "AdjustmentsForDecreaseIncreaseInInventories",
    "payables": "AdjustmentsForIncreaseDecreaseInTradeAccountPayable",
    "otherPayables": "AdjustmentsForIncreasedecreaseInOtherPayables",
    "advances": "AdjustmentsForIncreasedecreaseInAdvancesCustomers",
    "withholdings": "AdjustmentsForIncreasedecreaseInWithholdingsBanks",
    "accrued": "AdjustmentsForIncreasedecreaseInAccruedExpenses",
}
CASH = [
    ("netIncome", "연결 순이익", 1),
    ("adjustments", "현금표 비현금·손익 조정 합계", 1),
    ("working", "영업자산·부채 현금 변동 합계", 1),
    ("interestReceived", "현금 이자 수취", 1),
    ("interestPaid", "현금 이자 지급", -1),
    ("dividends", "현금 배당 수취", 1),
    ("taxCash", "법인세 현금 납부", -1),
]
PASSAGES = [
    "7e0707c101e893dff0c1",
    "fe9179c2540cf0762ddd",
    "4f98d9233ab9d48442a5",
    "6137aad6bcf1f5a45496",
    "0bb288cd03ab007bd4b8",
    "cb039026673c9efa7a39",
    "b1b96c54e895ddc7943d",
    "906782332c4ce12f0681",
    "27e1f08f982c0266ecb5",
    "be368ff981479efc8af5",
    "c6e9781f4231377d202c",
    "c83c4d63eb5fad4da8a9",
]


def build(c, as_of):
    from .operating_model import calculate

    h, meta = c.get("segmentHistory") or {}, c.get("narrative") or {}
    if (
        meta.get("accession") != CURRENT
        or meta.get("evidenceHash") != CORPUS
        or h.get("status") != "partial"
    ):
        return dict(
            status="source_review_required",
            reason="삼성전자 내부거래·기타 이익과 새 공시 범위를 다시 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    annual_source = h["review"]["annualSource"]
    if source["sha256"] != CURRENT_SHA or annual_source["sha256"] != ANNUAL_SHA:
        raise ValueError("Samsung source identity changed")
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if core["accession"] != "20260310002820":
        raise ValueError("Samsung annual identity changed")
    annual = instance_rows(
        read_verified(ROOT / annual_source["file"], ANNUAL_SHA),
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
            raise ValueError("Samsung consolidated fact missing: " + tag)
        return r

    def combine(key, tag):
        ps = [
            dict(
                coefficient=k,
                fact=exact(rs, tag, start, end, IND if key == "lease" else CON),
            )
            for k, rs, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in ps),
            components=ps,
            unit="KRW",
            sourceUrl=source["url"],
        )

    facts = {k: combine(k, tag) for k, tag in TAGS.items()}
    v = lambda key: facts[key]["value"]
    checks = []
    for i, (_, rs, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        cash = sum(sign * val(key) for key, _, sign in CASH)
        rev = h["reconciliations"]["revenue"]["periods"][i]
        income = h["reconciliations"]["operatingIncome"]["periods"][i]
        if (
            cash != val("cfo")
            or rev["status"] != "reconciled"
            or rev["total"] != val("revenue")
            or income["total"] != val("operatingIncome")
        ):
            raise ValueError("Samsung cash or segment scope differs")
        # This is a disclosed-table difference, not an independently disclosed
        # other-segment profit. The unallocated amount remains visible.
        difference = val("operatingIncome") - income["subtotal"]
        if difference != income["residual"]:
            raise ValueError("Samsung omitted segment difference changed")
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=cash,
                residual=0,
                revenueResidual=0,
                unallocatedOperatingIncome=difference,
                segmentRevenue=rev["subtotal"],
                internalRevenue=-rev["adjustment"],
                consolidatedRevenue=val("revenue"),
            )
        )
    if [p["unallocatedOperatingIncome"] for p in checks] != [
        242_924_000_000,
        36_860_000_000,
        131_863_000_000,
    ]:
        raise ValueError("Samsung source-specific omitted amounts differ")
    parts = [
        dict(
            label=label,
            value=sign * v(key),
            fact=dict(
                sourceUrl=source["url"],
                components=[
                    dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                    for p in facts[key]["components"]
                ],
            ),
        )
        for key, label, sign in CASH
    ]
    wc = {
        key: exact(rows, tag, f["start"], f["end"], IND) for key, tag in WORKING.items()
    }
    working = sum(p["value"] for p in wc.values())
    increase = (
        facts["revenue"]["components"][1]["fact"]["value"]
        - facts["revenue"]["components"][2]["fact"]["value"]
    )
    if increase <= 0:
        raise ValueError("Samsung working-capital proxy requires review")
    segments = []
    for s in h["segments"]:
        current, prior = [
            s["revenue"]["components"][i]["fact"]["value"] for i in [1, 2]
        ]
        segments.append(
            dict(
                id=s["id"],
                label=s["label"],
                revenue=s["revenue"]["value"],
                margin=s["operatingIncome"]["value"] / s["revenue"]["value"],
                observedGrowth=current / prior - 1,
                evidence=[p["fact"] for p in s["revenue"]["components"]],
            )
        )
    revenue = v("revenue")
    gross = sum(s["revenue"] for s in segments)
    elimination = -h["reconciliations"]["revenue"]["adjustment"]
    if gross - elimination != revenue:
        raise ValueError("Samsung intersegment sales do not reconcile")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.275,
        netInterest=(v("interestReceived") - v("interestPaid")) / revenue,
        depreciation=(v("depreciation") + v("amortization")) / revenue,
        workingCapital=-working / increase,
        capexStart=(v("ppe") + v("intangible")) / revenue,
        capexEnd=(v("ppe") + v("intangible")) / revenue,
        leaseStart=v("lease") / revenue,
        leaseEnd=v("lease") / revenue,
        discount=0.12,
        terminal=0.02,
        eliminationStart=elimination / gross,
        eliminationEnd=elimination / gross,
        otherProfitStart=0,
        otherProfitEnd=0,
        minority=v("minority") / revenue,
    )
    corpus = load(c)
    index = {p["id"]: p for p in corpus["passages"]}
    if any(p not in index for p in PASSAGES):
        raise ValueError("Samsung source passages changed")
    manifest = json.loads(
        (
            DOCUMENT_ROOT
            / f"data/sources/dart-document-{core['accession']}.manifest.json"
        ).read_text()
    )
    doc = next(x for x in manifest["files"] if x["sha256"] == ANNUAL_DOC)
    ps = extract(read_verified(DOCUMENT_ROOT / doc["file"], ANNUAL_DOC))
    annual_ps = [p for p in ps if p["ordinal"] in [1141, 1147, 1154, 1155, 1156, 1173]]
    if len(annual_ps) != 6 or "1,284,792" not in annual_ps[-1]["text"]:
        raise ValueError("Samsung annual cash/lease source changed")
    if doc["file"] not in {s["file"] for s in c["sources"]}:
        c["sources"].append(
            dict(
                doc,
                provider="DART",
                url=manifest["url"],
                retrievedAt=manifest["retrievedAt"],
            )
        )
    m = dict(
        status="research_workspace",
        version="samsung-consolidated-business-cash-v1",
        consolidationPath=True,
        sourcePeriod=[h["start"], h["end"]],
        accession=CURRENT,
        corpusHash=CORPUS,
        basisLabel="최근 1년 보고부문·내부매출·연결 현금 대사",
        growthLabel="최근 반기 전년 대비",
        currency="KRW",
        displayScale=1e12,
        displayUnit="조 원",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        consolidation=dict(
            reportedRevenue=revenue,
            segmentRevenue=gross,
            internalRevenue=elimination,
            reportedEliminationRate=elimination / gross,
            unallocatedOperatingIncome=h["reconciliations"]["operatingIncome"][
                "residual"
            ],
            periods=checks,
        ),
        netInterestLabel="현금 이자 수취−지급 대용",
        capexLabel="유형·무형 현금 취득",
        leaseLabel="리스 원금",
        bridgeLabel="연결 순이익 → 보고 영업현금 대사",
        intro="DS·DX·SDC·Harman의 내부거래 포함 매출에서 연결 제거액을 분리합니다. 보고 부문 이익에는 내부 이익 조정이 이미 배분돼 있습니다. 표에서 따로 표시되지 않은 기타 이익 차이는 남기며 미래 초기값은 영으로 가정합니다.",
        businessCaption="DS 이익은 메모리·HBM 단독 이익이 아닙니다. 제품별 매출과 영업부문 매출도 다른 구분입니다. 부문 매출을 단순 합산해 연결 매출로 쓰거나 내부거래 매출을 외부 고객 매출로 표시하지 않습니다.",
        anchorSummary="현재 반기 채권·재고·선급·미수·채무·선수·예수·미지급비용의 확인된 현금 효과를 연결 매출 증가로 나눕니다. 충당부채·퇴직 지급·내역 미분해 기타는 성장 비율에서 제외합니다. 세율27.5%는 한국 제조업 비교를 위한 연구 가정이며 회사의 글로벌 정상세율이 아닙니다.",
        passages=[index[p] for p in PASSAGES],
        historicalPassages=[
            dict(p, sourceUrl=manifest["url"], sourceHash=ANNUAL_DOC) for p in annual_ps
        ],
        observedResidualLabel="주식보상 전체 현금 대체 후 잔액 · 대체 금액 미확인",
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=None,
        ),
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=increase,
            workingFacts=wc,
            reportedCashAfterInvestmentAndLease=v("cfo")
            - v("ppe")
            - v("intangible")
            - v("lease"),
            actualShareCompensationReplacement=None,
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
                    "부문 간 내부매출 제거",
                    "최근 1년",
                    elimination,
                    "네 부문 합계에서 차감하여 연결 매출과 대사",
                ),
                (
                    "별도 표시되지 않은 기타 이익 차이",
                    "최근 1년",
                    h["reconciliations"]["operatingIncome"]["residual"],
                    "계산된 연결 차이이며 개별 사업·발생 원인 미확인",
                ),
                (
                    "확인된 리스 원금 지급",
                    "최근 1년",
                    v("lease"),
                    "재무현금 지급이며 유형·무형 현금 취득에 추가 차감",
                ),
                (
                    "전체 주식보상 현금 대체 금액",
                    "최근 1년",
                    None,
                    "PSU 비용·주식 지급·미지급비용 정산·자본변동은 다른 범위. 총대체액 미확인",
                ),
            ]
        ],
        rules=[
            "부문 매출 합계에서 내부매출 제거를 차감하여 각 기간 연결 매출을 대사합니다. 미래 제거율은 네 부문 총매출 대비 비율이며 1년차와5년차 사이 선형 변화로 가정합니다. 거래 상대 부문별 내부 판매가격을 식별한 전망이 아닙니다.",
            "보고 부문 이익은 감가·상각·영업이익의 내부거래 조정 배분 후 수치입니다. 매출 제거율로 부문 이익까지 다시 일괄 차감하지 않습니다. 미표시 기타 이익 차이는 계산값으로 남기며 현재 미래 경로에는0으로 가정합니다.",
            "영업자금 소요는 연결 매출의 전년 대비 증가와 대응합니다. 내부거래 제거율이 바뀌면 영업자금 소요도 전년 연결 매출에서 재계산합니다. 회사 전체 영업현금을 DS 또는 HBM 현금으로 표시하지 않습니다.",
            "현금표 조정 합계에는 금융·세금·감가상각·주식보상 등 여러 항목이 포함됩니다. 기타 조정이나 자본변동을 주식보상 비용 전체로 바꾸지 않습니다. 미래 영업이익에 주식보상 되돌림을 더하지 않습니다.",
            "미래 순이자는 보고 현금 이자 수취−지급 비율에서 시작하며 발생주의 순이자와 일치한다는 뜻이 아닙니다. 배당 유입·투자자산 평가·관계기업 이익과 비영업자산 가치는 기본 사업 현금에 배분하지 않습니다.",
            "유형·무형 현금 취득과 감가·상각, 리스 원금을 구분합니다. 인수대금·금융상품 매입·자기주식 취득은 유지 설비투자와 합치지 않습니다. 비지배 배분은 보고 비지배 순이익/연결매출 비율을 대용 가정으로 차감하며 실제 배당 지급액이 아닙니다.",
            "보통주·우선주 권리와 실제 주식수·성과연동 잠재 수량의 배분은 미해결입니다. 현재 사업 현금 계산을 보통주 한 주의 확정 가치로 바꾸지 않습니다.",
            "DS의 서버·HBM 수요 설명과 DX의 모바일 메모리 원가 상승은 함께 검토할 관측입니다. 내부거래 제거율과 마진을 독립 조정한 시나리오는 수요·원가의 인과 식별이 아니며 기본값이 정상 이익 전망이라는 뜻도 아닙니다.",
        ],
        remaining=[
            "기타 이익 차이의 원인·부문별 외부매출 및 내부 거래 상대",
            "HBM·메모리·파운드리별 손익과 DX 원가 전가",
            "성과연동 보상·희석·우선주·비지배 현금 권리",
            "정상 설비투자·리스 및 세계 세율·현금 이자 지속성",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
