"""Tesla product gross profit, unallocated costs and reviewed cash adjustments."""

import json

from .data import ROOT, canonical, digest, read_verified
from .narrative import extract, load
from .xbrl import company_filing, instance_rows, select

ANNUAL = "0001628280-26-003952"
CURRENT = "0001628280-26-049270"
PRODUCTS = [
    ("AutomotiveSalesMember", "자동차 판매"),
    ("AutomotiveRegulatoryCreditsMember", "규제 크레딧"),
    ("AutomotiveLeasingMember", "자동차 리스"),
    ("EnergyGenerationAndStorageMember", "에너지 발전·저장"),
    ("ServicesAndOtherMember", "서비스·기타"),
]
CASH_ROLES = [
    ("ProfitLoss", "연결 순이익", 1),
    ("DepreciationAmortizationAndImpairment", "상각·손상 조정", 1),
    ("ShareBasedCompensation", "주식보상 조정", 1),
    ("InventoryWriteDown", "재고 평가감", 1),
    ("ForeignCurrencyTransactionGainLossUnrealized", "미실현 환손익 조정", -1),
    ("DeferredIncomeTaxExpenseBenefit", "이연법인세 조정", 1),
    (
        "NoncashInterestIncomeExpenseAndOtherOperatingActivities",
        "비현금 이자·기타 조정",
        -1,
    ),
    ("GainLossOnDigitalAssets", "디지털자산 손익 조정", -1),
    ("IncreaseDecreaseInAccountsReceivable", "매출채권 변동", -1),
    ("IncreaseDecreaseInInventories", "재고 변동", -1),
    ("IncreaseDecreaseInOperatingLeaseVehicles", "영업리스 차량 변동", -1),
    (
        "IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets",
        "선급·기타 자산 변동",
        -1,
    ),
    (
        "IncreaseDecreaseInAccountsPayableAndAccruedLiabilities",
        "매입채무·미지급 변동",
        1,
    ),
    ("IncreaseDecreaseInContractWithCustomerLiability", "선수 수익 변동", 1),
]
TAGS = {
    "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "grossProfit": "GrossProfit",
    "operatingIncome": "OperatingIncomeLoss",
    "research": "ResearchAndDevelopmentExpense",
    "selling": "SellingGeneralAndAdministrativeExpense",
    "otherOperating": "RestructuringAndOtherExpenses",
    "pretax": "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "tax": "IncomeTaxExpenseBenefit",
    "cfo": "NetCashProvidedByUsedInOperatingActivities",
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
    "lease": "FinanceLeasePrincipalPayments",
    "interestIncome": "InvestmentIncomeInterest",
    "interestExpense": "InterestExpenseNonoperating",
    "minorityDistributions": "MinorityInterestDecreaseFromDistributionsToNoncontrollingInterestHolders",
    "redeemableDistributions": "TemporaryEquityDistributionsToNoncontrollingInterests",
}
PASSAGES = [
    "b25585fa9897caa17a72",
    "8390c02e25bf982903a8",
    "250b30b08702b7a6a9d7",
    "308d0d1c4c7e80d8379f",
    "639982b40a6067bb23ee",
    "719503b29f7dcba3fca4",
    "3ad2563cb840588ecc0b",
    "b46c2555c3c885c219ed",
    "9d87ccdf0edeb03fcde7",
    "a6847b66a66fb6adefd6",
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if (
        meta.get("accession") != CURRENT
        or meta.get("evidenceHash")
        != "62910896d45e4802db0177c78f33b6971a3063b8ff57993d712f253d99dd6f91"
    ):
        return dict(
            status="source_review_required",
            reason="Tesla의 새 공시에서 상품 원가·공통 비용·투자 범위를 다시 대사해야 합니다.",
        )
    core = c["trailingYear"]["values"]["revenue"]["components"][0]["fact"]
    if core["accession"] != ANNUAL or core["filedAt"] > as_of:
        return dict(
            status="source_review_required",
            reason="Tesla 연간 기준 공시의 기간 검토가 필요합니다.",
        )
    source, rows = company_filing(c, as_of)
    annual_source = json.loads(
        (ROOT / f"data/sources/filing-{ANNUAL}-xbrl.manifest.json").read_text()
    )
    if (
        source["sha256"]
        != "0c1972e6e14862f645f42baa356cd912af9500e7f5d4591f4b600568170192b4"
        or annual_source["sha256"]
        != "71f1e6d30adccb13ee4e3e1b03855f4bfe956f5a0245863019049cd0509e1524"
        or annual_source["accession"] != ANNUAL
        or annual_source["cik"] != c["cik"]
    ):
        raise ValueError("Tesla reviewed XBRL identity changed")
    annual = instance_rows(
        read_verified(ROOT / annual_source["file"], annual_source["sha256"]),
        c,
        annual_source,
        ANNUAL,
        core["filedAt"],
    )
    annual_html = json.loads(
        (ROOT / f"data/sources/filing-{ANNUAL}.manifest.json").read_text()
    )
    if (
        annual_html["sha256"]
        != "dd60f2be391b70360457a6a4e05e346358f7b04188e235367c27d12e4291f584"
    ):
        raise ValueError("Tesla reviewed annual narrative changed")
    annual_rows = extract(
        read_verified(ROOT / annual_html["file"], annual_html["sha256"])
    )
    annual_gain_row = next(
        p
        for p in annual_rows
        if p["text"].startswith("Unrealized net (loss) gain on investments, net of tax")
    )
    for item in [annual_source, annual_source["indexSource"], annual_html]:
        item = dict(item, provider="SEC", retrievedAt=annual_source["retrievedAt"])
        read_verified(ROOT / item["file"], item["sha256"])
        if item["file"] not in {s["file"] for s in c["sources"]}:
            c["sources"].append(item)
    f = c["financials"]
    periods = [
        (1, annual, "2025-01-01", "2025-12-31"),
        (1, rows, f["start"], f["end"]),
        (-1, rows, f["priorStart"], f["priorEnd"]),
    ]
    if [(start, end) for _, _, start, end in periods][1:] != [
        ("2026-01-01", "2026-06-30"),
        ("2025-01-01", "2025-06-30"),
    ]:
        raise ValueError("Tesla reviewed half-year period changed")
    corpus = load(c)
    index = {p["id"]: p for p in corpus["passages"]}
    if any(p not in index for p in PASSAGES):
        raise ValueError("Tesla reviewed business passages changed")

    def exact(rs, tag, start, end, dims=(), precision="-6"):
        result = select(
            [r for r in rs if r["decimals"] == precision], tag, start, end, dims, "USD"
        )
        if result is None:
            raise ValueError("Tesla source missing: " + tag)
        return result

    def combine(tag, dims=(), precision="-6"):
        parts = [
            dict(coefficient=k, fact=exact(rs, tag, start, end, dims, precision))
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
    facts.update({tag: combine(tag) for tag, _, _ in CASH_ROLES})
    # PPE note is rounded to $10m; unlike the broader cash-flow addback it
    # excludes the separately reported operating-lease vehicle/energy assets.
    facts["depreciation"] = combine("Depreciation", precision="-7")
    # The current CF row names SpaceX; the identically named annual tag is a
    # comprehensive-income short-term-investment item, NOT that CF adjustment.
    gain = exact(rows, "UnrealizedGainLossOnInvestments", f["start"], f["end"])
    facts["equityGain"] = dict(
        value=gain["value"],
        components=[dict(coefficient=1, fact=gain)],
        sourceUrl=gain["sourceUrl"],
        scopeEvidence=index["b46c2555c3c885c219ed"],
    )
    facts["equityGain"]["priorHalfFact"] = exact(
        rows, "UnrealizedGainLossOnInvestments", f["priorStart"], f["priorEnd"]
    )
    facts["equityGain"]["excludedAnnualSameTag"] = exact(
        annual, "UnrealizedGainLossOnInvestments", "2025-01-01", "2025-12-31"
    )
    facts["equityGain"][
        "scope"
    ] = "당기 현금표 SpaceX 평가이익 1,005m·전년 반기 0. 연간 같은 태그 −7m는 단기투자 기타포괄손익이므로 현금 조정에서 제외. 연간 현금표 별도 완전 대사."
    facts["equityGain"]["excludedAnnualLabel"] = dict(
        **annual_gain_row,
        sourceUrl=annual_html["url"],
        sourceFile=annual_html["file"],
        sourceHash=annual_html["sha256"],
    )
    if facts["equityGain"]["priorHalfFact"]["value"] != 0:
        raise ValueError("Prior SpaceX CF adjustment requires renewed review")
    v = lambda key: facts[key]["value"]
    segments = []
    for member, label in PRODUCTS:
        dims = [("ProductOrServiceAxis", member)]
        revenue = combine(TAGS["revenue"], dims)
        if member == "AutomotiveRegulatoryCreditsMember":
            components = []
            for sign, group in [
                (1, "AutomotiveRevenuesMember"),
                (-1, "AutomotiveSalesMember"),
                (-1, "AutomotiveLeasingMember"),
            ]:
                part = combine("CostOfRevenue", [("ProductOrServiceAxis", group)])
                components += [
                    dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                    for p in part["components"]
                ]
            cost = dict(
                value=sum(p["coefficient"] * p["fact"]["value"] for p in components),
                components=components,
                scope="자동차 원가 소계−판매−리스; 보고 원가 배분이며 경제적 비용 영의 뜻이 아님",
            )
        else:
            cost = combine("CostOfRevenue", dims)
        segments.append(
            dict(
                id=member,
                label=label,
                revenue=revenue["value"],
                grossProfit=revenue["value"] - cost["value"],
                margin=(revenue["value"] - cost["value"]) / revenue["value"],
                observedGrowth=revenue["components"][1]["fact"]["value"]
                / revenue["components"][2]["fact"]["value"]
                - 1,
                minGrowth=-1 if member == "AutomotiveRegulatoryCreditsMember" else -0.5,
                evidence=[p["fact"] for p in revenue["components"]],
                revenueFact=revenue,
                costFact=cost,
            )
        )
    checks = []
    for i, (_, rs, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        cfo = sum(sign * val(tag) for tag, _, sign in CASH_ROLES) - (
            gain["value"] if i == 1 else 0
        )
        revenue = sum(
            s["revenueFact"]["components"][i]["fact"]["value"] for s in segments
        )
        costs = []
        for s in segments:
            if s["id"] == "AutomotiveRegulatoryCreditsMember":
                # Period-by-period reconciliation prevents cancelling errors.
                cost = sum(
                    p["coefficient"] / periods[i][0] * p["fact"]["value"]
                    for p in s["costFact"]["components"]
                    if p["fact"]["start"] == start and p["fact"]["end"] == end
                )
            else:
                cost = s["costFact"]["components"][i]["fact"]["value"]
            costs.append(cost)
        if (
            cfo != val("cfo")
            or revenue != val("revenue")
            or revenue - sum(costs) != val("grossProfit")
            or val("grossProfit")
            - sum(val(k) for k in ("research", "selling", "otherOperating"))
            != val("operatingIncome")
            or val("pretax") - val("tax") != val("ProfitLoss")
        ):
            raise ValueError("Tesla period cash/product/earnings reconciliation failed")
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=cfo,
                residual=0,
                revenueResidual=0,
                grossProfitResidual=0,
                operatingIncomeResidual=0,
            )
        )
    revenue = v("revenue")
    if revenue != c["trailingYear"]["values"]["revenue"]["value"]:
        raise ValueError("Tesla trailing revenue scope differs")

    def bridge_part(label, terms):
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
        bridge_part("연결 영업이익", [("operatingIncome", 1)]),
        bridge_part(
            "순이익까지의 영업외·세금 차이",
            [("ProfitLoss", 1), ("operatingIncome", -1)],
        ),
    ]
    parts += [bridge_part(label, [(tag, sign)]) for tag, label, sign in CASH_ROLES[1:]]
    parts.append(bridge_part("지분 투자 평가이익 되돌림", [("equityGain", -1)]))
    if sum(p["value"] for p in parts) != v("cfo"):
        raise ValueError("Tesla trailing cash bridge failed")
    # This broad proxy includes prepaid/other assets. Lease vehicles are
    # excluded: their depreciation remains a cash replacement-cost proxy.
    wc_roles = [
        r for r in CASH_ROLES[8:] if r[0] != "IncreaseDecreaseInOperatingLeaseVehicles"
    ]
    working = sum(
        sign * facts[tag]["components"][1]["fact"]["value"] for tag, _, sign in wc_roles
    )
    growth = f["current"]["revenue"]["value"] - f["previous"]["revenue"]["value"]
    if growth <= 0:
        raise ValueError("Tesla working-capital growth denominator changed")
    intangible = exact(rows, "PaymentsToAcquireIntangibleAssets", f["start"], f["end"])
    intangible_ratio = intangible["value"] / f["current"]["revenue"]["value"]
    minority = v("minorityDistributions") + v("redeemableDistributions")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=v("tax") / v("pretax"),
        netInterest=(v("interestIncome") - v("interestExpense")) / revenue,
        depreciation=v("depreciation") / revenue,
        workingCapital=-working / growth,
        capexStart=v("capex") / revenue + intangible_ratio,
        capexEnd=v("capex") / revenue + intangible_ratio,
        leaseStart=v("lease") / revenue,
        leaseEnd=v("lease") / revenue,
        discount=0.12,
        terminal=0.02,
        minority=minority / revenue,
    )
    for key in ("research", "selling", "otherOperating"):
        defaults[key + "Start"] = defaults[key + "End"] = v(key) / revenue
    change_parts = []
    for key, label, sign in [
        ("grossProfit", "매출총이익 증가", 1),
        ("research", "연구개발비 증가", -1),
        ("selling", "판매관리비 증가", -1),
        ("otherOperating", "구조조정비 감소", -1),
    ]:
        fact = facts[key]
        change_parts.append(
            dict(
                label=label,
                value=sign
                * (
                    fact["components"][1]["fact"]["value"]
                    - fact["components"][2]["fact"]["value"]
                ),
                evidence=fact["components"][1:],
            )
        )
    previous_op = facts["operatingIncome"]["components"][2]["fact"]["value"]
    current_op = facts["operatingIncome"]["components"][1]["fact"]["value"]
    if previous_op + sum(p["value"] for p in change_parts) != current_op:
        raise ValueError("Tesla year-on-year profit bridge failed")
    m = dict(
        status="research_workspace",
        version="tesla-product-cash-path-v1",
        grossProfitPath=True,
        sourcePeriod=["2025-07-01", "2026-06-30"],
        accession=CURRENT,
        corpusHash=meta["evidenceHash"],
        basisLabel="최근 1년 상품 손익·현금 연결",
        growthLabel="최근 반기 전년 대비",
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        groupLabel="공시 상품군",
        marginLabel="매출총이익률",
        intro="다섯 상품군의 매출총이익에서 공통 연구개발비·판매관리비·구조조정비를 차감합니다. 주식보상과 평가이익을 미래 현금에 더하지 않습니다.",
        businessCaption="자동차 보고 부문에는 서비스·기타가 포함됩니다. 이 표는 중복 없는 상품별 매출·원가이며 상품별 영업이익이 아닙니다. 크레딧의 보고 원가 배분은 영이지만 경제적 비용이 없다는 뜻은 아닙니다.",
        capexLabel="순설비·무형 현금 취득",
        leaseLabel="금융리스 원금",
        observedResidualLabel="영업현금 − 매각 차감 설비 취득 − 금융리스 원금 − 주식보상 비용 대용",
        anchorSummary="설비 취득 태그는 매각액 차감 금액입니다. 미래 무형 취득에는 최근 반기 비율을 별도 더합니다. 보고 현금 잔액은 무형·지분 투자·비지배 배분 전입니다. 넓은 선급·기타 자산을 포함한 반기 영업자금 계수와 영의 계수를 비교해야 합니다.",
        passages=[index[p] for p in PASSAGES],
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        profitChange=dict(
            start=previous_op,
            end=current_op,
            parts=change_parts,
            period="2026년 반기 / 2025년 반기",
            sourceUrl=source["primaryUrl"],
        ),
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=v("cfo")
            - v("capex")
            - v("lease")
            - v("ShareBasedCompensation"),
        ),
        anchors=dict(
            workingCashEffect=working,
            revenueIncrease=growth,
            intangibleFact=intangible,
            intangibleRatio=intangible_ratio,
            minorityDistributions=minority,
            ppeDepreciation=v("depreciation"),
            broaderDepreciation=v("DepreciationAmortizationAndImpairment"),
        ),
        investmentStress=dict(
            calendarYear=2026,
            lowerBound=25e9,
            minimumRatio=25e9 / revenue + intangible_ratio,
            passageId="8390c02e25bf982903a8",
            scope="회사는 2026년 설비투자 250억 달러 초과를 설명합니다. 비교 버튼은 그 하한/기초매출 비율을 미래 경로에 적용하는 스트레스이며 달력연도 예산 예측이 아닙니다.",
        ),
        rules=[
            "기초 실적은 연간+당기 반기−전년 반기이며 세 기간의 상품 매출·원가·공통 비용·영업현금을 각각 대사했습니다.",
            "상품 마진은 매출총이익률입니다. 연구개발·판매관리·구조조정 비용은 배분하지 않고 연결 매출 비율로 따로 차감합니다. 비용 안의 주식보상은 미래 현금에서 되돌리지 않습니다.",
            "매출 성장 0%와 현재 상품 마진·공통 비용 비율 유지가 시작 가정입니다. 크레딧의 판매 중단은 해당 매출 −100%로 비교하며 다른 사업 마진 개선을 자동 가정하지 않습니다.",
            "지분 투자·디지털자산·환율 평가손익과 현금표 비현금 조정은 보고 영업현금 대사에만 사용합니다. 미래에는 순이자 비율만 유지하며 SpaceX 투자금·가치를 별도 배분하지 않습니다.",
            "미래 addback은 유형자산 주석의 감가상각만 사용합니다. 현금표 총 상각·손상이나 재고 평가감을 전액 되돌리지 않습니다. 영업리스 차량·에너지 임대자산의 감가상각은 비용을 대체 투자 대용으로 유지하는 가정이며 실제 신규 임대자산 투자 경로가 아닙니다.",
            "설비 현금 취득은 매각 차감 순액입니다. 무형 취득은 최근 반기 700만 달러/반기 매출의 비율을 별도 적용하며 확인되지 않은 연간 무형 취득을 영으로 채우지 않습니다.",
            "반기 영업자금 계수에는 선급·기타 자산이 포함되고 리스 차량은 제외됩니다. 음수 계수를 정상 자금 조달 구조로 승인하지 않습니다. 세율은 보고 법인세/세전이익이며 평가손익이 섞인 과거 세율입니다.",
            "비지배·상환가능 지분 분배는 최근 1년 현금 비율로 차감합니다. 이것이 미래 권리 배분의 확정액은 아닙니다. 비리스 차입은 차환, 금융자산 초과가치는 미배분의 조건부 가정입니다.",
            "요구수익률 12%·영구 매출 성장 2%는 연구자 가정입니다. 말기에도 공통 비용·추가 영업자금·재투자·비지배 분배를 다시 계산합니다.",
        ],
        remaining=[
            "차량 인도·실현 가격·원가 및 보증 조정의 분리",
            "자율주행·로봇의 비용·상용화 실적과 자본 지출 회수",
            "크레딧 계약·규제와 에너지·서비스 구성 변화",
            "임대자산 투자·손상, 초과 금융자산·출자 약정 및 증권 권리 배분",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
