"""Apple product/service gross profit and separately labelled cash assumptions."""

import json

from .data import ROOT, canonical, digest, read_verified
from .narrative import extract, load
from .xbrl import company_filing, instance_rows, select

CURRENT = "0000320193-26-000020"
ANNUAL = "0000320193-25-000079"
CORPUS = "68b4ce050be11471fffcb7ea0db86254024e6ecec9d42573f1205d29a3f36d52"
CURRENT_XBRL = "28f986bb243c8fdd445560d381df4b57912ca290b03b8451ecd518e63cdb5d2b"
ANNUAL_XBRL = "e1076735f1c81bc96d5c1ff6e1a9d23515d6eacf52b405cb1f7da3e379ac533b"
ANNUAL_HTML = "aec600ecc03ebe37c1d40b1d941f17ea8a94e35f65a5995941130e437328ad1e"
WC = [
    ("IncreaseDecreaseInAccountsReceivable", "매출채권 변동", -1),
    ("IncreaseDecreaseInOtherReceivables", "공급업체 비매출채권 변동", -1),
    ("IncreaseDecreaseInInventories", "재고 변동", -1),
    ("IncreaseDecreaseInOtherOperatingAssets", "기타 영업자산 변동", -1),
    ("IncreaseDecreaseInAccountsPayable", "매입채무 변동", 1),
    ("IncreaseDecreaseInOtherOperatingLiabilities", "기타 영업부채 변동", 1),
]
CASH = [
    ("NetIncomeLoss", "순이익", 1),
    ("DepreciationDepletionAndAmortization", "감가상각·상각 조정", 1),
    ("ShareBasedCompensation", "주식보상 조정", 1),
    ("OtherNoncashIncomeExpense", "기타 비현금 조정", -1),
    *WC,
]
TAGS = {
    "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "grossProfit": "GrossProfit",
    "research": "ResearchAndDevelopmentExpense",
    "selling": "SellingGeneralAndAdministrativeExpense",
    "operatingIncome": "OperatingIncomeLoss",
    "nonoperating": "NonoperatingIncomeExpense",
    "pretax": "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "tax": "IncomeTaxExpenseBenefit",
    "cfo": "NetCashProvidedByUsedInOperatingActivities",
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
}
READINGS = [170, 347, 352, 354, 355, 356, 361, 362, 363, 380, 381]


def build(c, as_of):
    from .operating_model import calculate

    if c.get("narrative", {}).get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="Apple 새 공시의 제품·서비스 원가와 세금·리스 범위를 다시 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    if source["accession"] != CURRENT or source["sha256"] != CURRENT_XBRL:
        raise ValueError("Apple current XBRL identity changed")
    annual_source = json.loads(
        (ROOT / f"data/sources/filing-{ANNUAL}-xbrl.manifest.json").read_text()
    )
    annual_html = json.loads(
        (ROOT / f"data/sources/filing-{ANNUAL}.manifest.json").read_text()
    )
    if (
        annual_source["sha256"] != ANNUAL_XBRL
        or annual_html["sha256"] != ANNUAL_HTML
        or any(
            s["accession"] != ANNUAL or s["cik"] != c["cik"]
            for s in [annual_source, annual_html]
        )
        or as_of < "2025-10-31"
    ):
        raise ValueError("Apple annual source identity changed")
    annual = instance_rows(
        read_verified(ROOT / annual_source["file"], ANNUAL_XBRL),
        c,
        annual_source,
        ANNUAL,
        "2025-10-31",
    )
    annual_passages = {
        p["ordinal"]: p
        for p in extract(read_verified(ROOT / annual_html["file"], ANNUAL_HTML))
    }
    for number, phrases in {
        311: ["Statutory federal income tax rate", "21"],
        593: ["Depreciation expense on property, plant and equipment", "$8.0 billion"],
        664: ["Finance leases", "Other current liabilities", "538", "144"],
        668: ["Lease liability maturities as of September 27, 2025"],
    }.items():
        if number not in annual_passages or not all(
            t in annual_passages[number]["text"] for t in phrases
        ):
            raise ValueError("Apple annual cash assumption caption changed")
    for item in [annual_source, annual_source["indexSource"], annual_html]:
        item = dict(item, provider="SEC", retrievedAt=annual_source["retrievedAt"])
        read_verified(ROOT / item["file"], item["sha256"])
        if item["file"] not in {s["file"] for s in c["sources"]}:
            c["sources"].append(item)
    f = c["financials"]
    if (f["start"], f["end"], f["priorStart"], f["priorEnd"]) != (
        "2025-09-28",
        "2026-06-27",
        "2024-09-29",
        "2025-06-28",
    ):
        raise ValueError("Apple reviewed nine-month periods changed")
    periods = [
        (1, annual, "2024-09-29", "2025-09-27"),
        (1, rows, f["start"], f["end"]),
        (-1, rows, f["priorStart"], f["priorEnd"]),
    ]

    def exact(rs, tag, start, end, dims=(), precision="-6"):
        r = select(
            [r for r in rs if r["decimals"] == precision], tag, start, end, dims, "USD"
        )
        if r is None:
            raise ValueError("Apple source missing: " + tag)
        return r

    def combine(tag, dims=()):
        parts = [
            dict(coefficient=k, fact=exact(rs, tag, start, end, dims))
            for k, rs, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            derived=True,
            tag=tag,
            unit="USD",
            sourceUrl=source["primaryUrl"],
        )

    facts = {key: combine(tag) for key, tag in TAGS.items()}
    facts.update({tag: combine(tag) for tag, _, _ in CASH})
    v = lambda key: facts[key]["value"]
    segments = []
    for member, label in [("ProductMember", "제품"), ("ServiceMember", "서비스")]:
        dims = [("ProductOrServiceAxis", member)]
        rev = combine(TAGS["revenue"], dims)
        cost = combine("CostOfGoodsAndServicesSold", dims)
        segments.append(
            dict(
                id=member,
                label=label,
                revenue=rev["value"],
                grossProfit=rev["value"] - cost["value"],
                margin=(rev["value"] - cost["value"]) / rev["value"],
                observedGrowth=rev["components"][1]["fact"]["value"]
                / rev["components"][2]["fact"]["value"]
                - 1,
                evidence=[p["fact"] for p in rev["components"]],
                revenueFact=rev,
                costFact=cost,
            )
        )
    checks = []
    for i, (_, _, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        income = val("operatingIncome") + val("nonoperating") - val("tax")
        cfo = sum(sign * val(tag) for tag, _, sign in CASH)
        revenue = sum(
            s["revenueFact"]["components"][i]["fact"]["value"] for s in segments
        )
        cost = sum(s["costFact"]["components"][i]["fact"]["value"] for s in segments)
        if (
            income != val("NetIncomeLoss")
            or cfo != val("cfo")
            or val("pretax") != val("operatingIncome") + val("nonoperating")
            or revenue != val("revenue")
            or revenue - cost != val("grossProfit")
            or val("grossProfit") - val("research") - val("selling")
            != val("operatingIncome")
        ):
            raise ValueError("Apple period product/income/cash reconciliation failed")
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=cfo,
                residual=0,
                grossProfitResidual=0,
                operatingIncomeResidual=0,
                incomeResidual=0,
            )
        )
    if v("revenue") != c["trailingYear"]["values"]["revenue"]["value"]:
        raise ValueError("Apple trailing revenue scope differs")

    def part(label, terms):
        components = [
            dict(coefficient=sign * p["coefficient"], fact=p["fact"])
            for key, sign in terms
            for p in facts[key]["components"]
        ]
        return dict(
            label=label,
            value=sum(p["coefficient"] * p["fact"]["value"] for p in components),
            fact=dict(sourceUrl=source["primaryUrl"], components=components),
        )

    parts = [
        part("연결 영업이익", [("operatingIncome", 1)]),
        part("영업외 순손익", [("nonoperating", 1)]),
        part("법인세 비용", [("tax", -1)]),
    ]
    parts += [part(label, [(tag, sign)]) for tag, label, sign in CASH[1:]]
    if sum(p["value"] for p in parts) != v("cfo"):
        raise ValueError("Apple trailing cash bridge failed")
    depreciation = exact(
        annual, "Depreciation", "2024-09-29", "2025-09-27", precision="-8"
    )
    lease_current = exact(annual, "FinanceLeaseLiabilityCurrent", None, "2025-09-27")
    lease_gross = exact(
        annual, "FinanceLeaseLiabilityPaymentsDueNextTwelveMonths", None, "2025-09-27"
    )
    if (depreciation["value"], lease_current["value"], lease_gross["value"]) != (
        8e9,
        538e6,
        563e6,
    ):
        raise ValueError("Apple annual depreciation/lease anchors changed")
    working = sum(
        sign * facts[tag]["components"][1]["fact"]["value"] for tag, _, sign in WC
    )
    growth = f["current"]["revenue"]["value"] - f["previous"]["revenue"]["value"]
    if growth <= 0:
        raise ValueError("Apple operating-capital denominator requires review")
    annual_revenue = facts["revenue"]["components"][0]["fact"]["value"]
    revenue = v("revenue")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.21,
        netInterest=v("nonoperating") / revenue,
        depreciation=depreciation["value"] / annual_revenue,
        workingCapital=-working / growth,
        capexStart=v("capex") / revenue,
        capexEnd=v("capex") / revenue,
        leaseStart=lease_current["value"] / annual_revenue,
        leaseEnd=lease_current["value"] / annual_revenue,
        discount=0.11,
        terminal=0.02,
        researchStart=v("research") / revenue,
        researchEnd=v("research") / revenue,
        sellingStart=v("selling") / revenue,
        sellingEnd=v("selling") / revenue,
        otherOperatingStart=0,
        otherOperatingEnd=0,
        minority=0,
    )
    current_passages = {p["ordinal"]: p for p in load(c)["passages"]}
    if (
        "wholly owned subsidiaries" not in current_passages[170]["text"]
        or "tariff refunds" not in current_passages[361]["text"]
    ):
        raise ValueError("Apple reviewed business scope changed")
    historical = [
        dict(
            **annual_passages[n],
            sourceUrl=annual_html["url"],
            sourceFile=annual_html["file"],
            sourceHash=ANNUAL_HTML,
        )
        for n in [311, 593, 654, 655, 656, 657, 658, 664, 668]
    ]
    change_parts = []
    for key, label, sign in [
        ("grossProfit", "매출총이익 증가", 1),
        ("research", "연구개발비 증가", -1),
        ("selling", "판매관리비 증가", -1),
    ]:
        change_parts.append(
            dict(
                label=label,
                value=sign
                * (
                    facts[key]["components"][1]["fact"]["value"]
                    - facts[key]["components"][2]["fact"]["value"]
                ),
                evidence=facts[key]["components"][1:],
            )
        )
    previous = facts["operatingIncome"]["components"][2]["fact"]["value"]
    current = facts["operatingIncome"]["components"][1]["fact"]["value"]
    if previous + sum(p["value"] for p in change_parts) != current:
        raise ValueError("Apple profit change reconciliation failed")
    m = dict(
        status="research_workspace",
        version="apple-product-cash-path-v1",
        grossProfitPath=True,
        sourcePeriod=["2025-06-29", "2026-06-27"],
        accession=CURRENT,
        corpusHash=CORPUS,
        basisLabel="최근 1년 제품·서비스 손익·현금 연결",
        growthLabel="최근 9개월 전년 대비",
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        groupLabel="제품·서비스",
        marginLabel="매출총이익률",
        netInterestLabel="영업외 순손익",
        capexLabel="설비 현금 취득",
        leaseLabel="금융리스 부담 가정",
        intro="제품과 서비스의 매출총이익에서 공통 연구개발·판매관리비를 차감합니다. 보고 현금 대사와 연간 감가상각·리스 부채에서 출발한 미래 가정을 구분합니다.",
        businessCaption="제품군별 원가가 공개되지 않아 iPhone·Mac에 전체 제품 마진을 배분하지 않습니다. 제품 마진에는 금액 미공시 관세 환급이 포함됩니다. 지역별 영업이익률과 제품·서비스 매출총이익률도 구분합니다.",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        passages=[current_passages[n] for n in READINGS],
        historicalPassages=historical,
        profitChange=dict(
            start=previous,
            end=current,
            parts=change_parts,
            startLabel="전년 9개월",
            endLabel="당기 9개월",
            period="2026 회계연도 9개월 / 전년 9개월",
            caption="매출총이익 증가에서 연구개발·판매관리비 증가를 차감한 산술 대사입니다. 제품 구성·관세 환급·메모리 비용의 개별 기여액은 분리 공시되지 않아 인과 금액으로 나누지 않습니다.",
            sourceUrl=source["primaryUrl"],
        ),
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=v("cfo")
            - v("capex")
            - v("ShareBasedCompensation"),
        ),
        observedResidualLabel="영업현금 − 설비 취득 − 주식보상 비용 대용 (금융리스 원금 차감 전)",
        anchorSummary="보고 영업현금은 세 기간 각각 대사했습니다. 미래 감가상각 비율은 직전 연간의 설비 감가상각/연간 매출, 리스 비율은 같은 연말 유동 금융리스 부채/연간 매출입니다. 최근 1년 실제 감가상각·리스 지급으로 바꾸지 않습니다.",
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=growth,
            annualRevenue=annual_revenue,
            annualPpeDepreciation=depreciation,
            annualCurrentFinanceLeaseLiability=lease_current,
            annualNextYearGrossFinanceLeasePayments=lease_gross,
            trailingFinanceLeasePrincipalPaid=None,
            trailingPpeDepreciation=None,
            trailingBroadDepreciation=v("DepreciationDepletionAndAmortization"),
        ),
        cashAnchors=[
            dict(
                label="설비 감가상각",
                value=depreciation["value"],
                period="2024-09-29–2025-09-27",
                scope="직전 연간 비용; 최근 1년 재구성 아님",
                sourceUrl=depreciation["sourceUrl"],
            ),
            dict(
                label="유동 금융리스 부채",
                value=lease_current["value"],
                period="2025-09-27",
                scope="연말 부채 잔액; 미래 부담 비율의 대용 근거",
                sourceUrl=lease_current["sourceUrl"],
            ),
            dict(
                label="다음 회계연도 금융리스 지급표",
                value=lease_gross["value"],
                period="2025-09-27 기준 / 회계연도 2026",
                scope="미할인 원금·이자 합계; 실제 지급 아님",
                sourceUrl=lease_gross["sourceUrl"],
            ),
            dict(
                label="최근 1년 금융리스 원금 지급",
                value=None,
                period="2025-06-29–2026-06-27",
                scope="별도 금액 미확인; 영으로 대체하지 않음",
                sourceUrl=source["primaryUrl"],
            ),
        ],
        rules=[
            "직전 연간 + 당기 9개월 − 전년 9개월로 제품·서비스 매출과 원가, 연결 손익·영업현금을 각각 대사합니다. 분기 성장과 누적 성장을 섞지 않습니다.",
            "제품 마진의 관세 환급 기여액은 미정량입니다. 현재 제품 마진 유지는 환급 효과까지 반복하는 가정이므로 마진 하락 대안과 비교해야 합니다. 서비스에는 광고·클라우드 구성이 함께 작용합니다.",
            "공통 연구개발·판매관리비는 별도 차감합니다. 기타 영업비용의 시작값 영은 세 기간 손익 항등식 잔차가 영인 것에 근거하며 미확인 비용을 영으로 채운 것이 아닙니다. 완전자회사 연결 범위에서 비지배 배분의 시작값은 영입니다.",
            "세율 21%는 연간 공시의 미국 연방 법정세율에 근거한 연구 가정입니다. 해외 수익·세액공제·주식보상 효과가 섞인 보고 유효세율이나 회사의 정상 현금세율 예측이 아닙니다.",
            "미래 영업외 순손익은 최근 1년 보고 합계 비율을 유지하는 가정입니다. 순이자만 분리한 값이나 검증된 반복 수익이 아니므로 별도로 편집합니다. 투자자산 가치는 추가하지 않습니다.",
            "설비 감가상각은 직전 연간 80억 달러/연간 매출 비율을 사용합니다. 당기 9개월의 설비 감가상각이 별도 확인되지 않아 최근 1년 값을 만들지 않습니다. 무형 상각·영업리스 비용은 대체 비용 대용으로 손익에 남깁니다.",
            "미래 금융리스 부담은 2025-09-27 유동 금융리스 부채 5.38억 달러/연간 매출 비율의 반복 가정입니다. 5.63억 달러 만기도래 지급표는 이자를 포함하며, 두 금액 모두 최근 1년 실제 지급액이 아닙니다. 실제 리스 원금 차감 후 과거 현금 잔액은 미확인입니다.",
            "영업자금 계수에는 공급업체 비매출채권·기타 자산과 부채가 포함됩니다. 세금·계절성·환급 효과가 섞일 수 있어 정상 필요 자금으로 승인하지 않습니다. 주식보상 비용은 미래에 현금으로 되돌리지 않습니다.",
            "비리스 차입은 차환하고 초과 금융자산은 미배분하는 조건부 경로입니다. 요구수익률 11%·영구성장 2%는 연구자 가정이며 말기에도 증가 매출의 자금 소요와 재투자를 계산합니다.",
        ],
        remaining=[
            "관세 환급액·제품 구성·메모리 비용의 분리와 지속 마진",
            "서비스 구성·규제와 반복 수익성",
            "최신 설비 감가상각·금융리스 실제 원금 지급 및 무형 대체 투자",
            "세금·공급업체 채권과 정상 영업자금",
            "초과 현금·증권·차입 차환과 미래 주식수",
        ],
        independentFinancialApproval=False,
    )
    m["evidenceHash"] = digest(canonical(m))
    m["initial"] = calculate(m, defaults)
    return m
