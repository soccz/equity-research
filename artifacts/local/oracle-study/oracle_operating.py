"""Oracle: operating segment margins, customer financing and data-center cash."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "0001193125-26-389274"
CORPUS = "ab8721298291eab8324955b049f4c7225ca933a2928385b42fa320f004ab7c2b"
SOURCE = "b060531e631ff72dd633b7926e5ee81aaebdea83db49388b4ac9ba07554d7fb0"
ANNUAL = "0001193125-26-277521"
ANNUAL_SHA = "2ece8288f124c7ddfc46ea2b90e242b7214e49dd423beaf8eefad8acea23852f"
ANNUAL_HTML = "914df37cc78d319da7d350f42628dc0bb70599bae6ec3c96a297e6f344c012ef"
TAGS = dict(
    revenue="RevenueFromContractWithCustomerExcludingAssessedTax",
    operatingIncome="OperatingIncomeLoss",
    netIncome="NetIncomeLoss",
    depreciation="Depreciation",
    amortization="AmortizationOfIntangibleAssets",
    deferredTax="DeferredIncomeTaxExpenseBenefit",
    sbc="ShareBasedCompensation",
    receivables="IncreaseDecreaseInAccountsReceivable",
    otherAssets="IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets",
    payables="IncreaseDecreaseInAccountsPayableAndOtherOperatingLiabilities",
    incomeTaxPayable="IncreaseDecreaseInAccruedIncomeTaxesPayable",
    financingPrepayments="IncreaseDecreaseInDeferredRevenuesFromCustomerPrepaymentsWithSignificantFinancingComponent",
    otherDeferred="IncreaseDecreaseInOtherDeferredRevenues",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    capex="PaymentsToAcquirePropertyPlantAndEquipment",
    research="ResearchAndDevelopmentExpense",
    administrative="GeneralAndAdministrativeExpense",
    restructuring="RestructuringAndOtherExpenses",
    segmentSbc="StockBasedCompensationSegment",
    allocations="ExpenseAllocationsAndOtherNet",
    interest="InterestExpense",
    leaseInterest="FinanceLeaseInterestExpense",
    leaseCash="FinanceLeasePrincipalAndInterestPayments",
    minority="NonOperatingIncomeExpenseAttributableToMinorityInterest",
)
CASH = [
    ("netIncome", "보고 순이익", 1),
    ("depreciation", "설비·금융리스 자산 감가상각", 1),
    ("amortization", "인수 무형상각", 1),
    ("deferredTax", "이연법인세", 1),
    ("sbc", "주식보상 되돌림", 1),
    ("receivables", "매출채권 현금 효과", -1),
    ("otherAssets", "선급·기타 영업자산", -1),
    ("payables", "매입채무·기타 영업부채", 1),
    ("incomeTaxPayable", "미지급 법인세", 1),
    ("financingPrepayments", "중요 금융요소 포함 고객 선급 현금 조정", 1),
    ("otherDeferred", "그 밖의 선수 수익 현금 조정", 1),
]
COSTS = [
    ("research", "연구개발비"),
    ("administrative", "일반관리비"),
    ("amortization", "인수 무형상각"),
    ("restructuring", "구조조정·기타"),
    ("segmentSbc", "부문 미배분 주식보상"),
    ("allocations", "그 밖의 배분·순비용"),
]
PASSAGES = [
    "1940448c13d341cc2487",
    "06e1ca6e5cb1e4067e67",
    "7d87a78b158b41ba5f37",
    "5a843365a216df755db9",
    "c9b3ab7418f36a54bb39",
    "04ed4cf1d8f5fd6cec29",
    "ed8b1acc7200d47e3b92",
    "2e64b75aa96332bb0be1",
    "be9cd15c77434ab10106",
    "7f159bc764cd97295e49",
    "cd2a46d5dd20c69cb559",
    "09caa8d0747ff0202402",
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="Oracle 사업부 비용·고객 금융·설비 투자와 우선주를 새 공시에서 다시 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    annual_source = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}-xbrl.manifest.json").read_text()
    )
    html = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}.manifest.json").read_text()
    )
    if (
        source["sha256"] != SOURCE
        or annual_source["sha256"] != ANNUAL_SHA
        or html["sha256"] != ANNUAL_HTML
        or annual_source["cik"] != c["cik"]
        or html["cik"] != c["cik"]
    ):
        raise ValueError("Oracle filing identity changed")
    annual = instance_rows(
        read_verified(DOCUMENT_ROOT / annual_source["file"], ANNUAL_SHA),
        c,
        annual_source,
        ANNUAL,
        "2026-06-22",
    )
    periods = [
        (1, annual, "2025-06-01", "2026-05-31"),
        (1, rows, "2026-06-01", "2026-08-31"),
        (-1, rows, "2025-06-01", "2025-08-31"),
    ]
    if (
        c["financials"]["start"] != "2026-06-01"
        or c["financials"]["end"] != "2026-08-31"
    ):
        raise ValueError("Oracle periods changed")

    def exact(rs, tag, start, end, dims=()):
        r = select(
            [x for x in rs if x["decimals"] == "-6"], tag, start, end, dims, "USD"
        )
        if r is None:
            raise ValueError(
                "Oracle missing fact " + tag + " " + str(start) + " " + end
            )
        return r

    def combined(tag, dims=()):
        parts = [
            dict(coefficient=k, fact=exact(rs, tag, s, e, dims))
            for k, rs, s, e in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            sourceUrl=source["primaryUrl"],
            unit="USD",
        )

    facts = {k: combined(tag) for k, tag in TAGS.items()}
    v = lambda key: facts[key]["value"]
    segments = []
    for member, label in [
        ("CloudAndSoftwareBusinessMember", "클라우드·소프트웨어"),
        ("HardwareBusinessMember", "하드웨어"),
        ("ServicesBusinessMember", "서비스"),
    ]:
        dims = [
            ("ConsolidationItemsAxis", "OperatingSegmentsMember"),
            ("StatementBusinessSegmentsAxis", member),
        ]
        sales = combined(TAGS["revenue"], dims)
        profit = combined(TAGS["operatingIncome"], dims)
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
    other_parts = []
    for i, (coefficient, rs, start, end) in enumerate(periods):
        val = lambda key: facts[key]["components"][i]["fact"]["value"]
        cash_parts = [
            dict(
                label=label,
                value=sign * val(key),
                fact=facts[key]["components"][i]["fact"],
            )
            for key, label, sign in CASH
        ]
        other = exact(
            rs,
            (
                "GainsFromInvestmentsAndOtherNet"
                if i == 0
                else "OtherNoncashIncomeExpense"
            ),
            start,
            end,
        )
        cash_parts.append(
            dict(
                label="투자손익·기타 조정" if i == 0 else "기타 비현금 조정",
                value=-other["value"],
                fact=other,
            )
        )
        other_parts.append(dict(coefficient=-coefficient, fact=other))
        reported = sum(p["value"] for p in cash_parts)
        sales = sum(
            s["evidence"][0]["components"][i]["fact"]["value"] for s in segments
        )
        profit = sum(
            s["evidence"][1]["components"][i]["fact"]["value"] for s in segments
        )
        cost = sum(val(k) for k, _ in COSTS)
        if (
            reported != val("cfo")
            or sales != val("revenue")
            or profit - cost != val("operatingIncome")
        ):
            raise ValueError("Oracle period cash/segment reconciliation failed")
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=reported,
                components=cash_parts,
                residual=0,
                revenueResidual=0,
                incomeResidual=0,
                operatingIncome=profit - cost,
                segmentOperatingIncome=profit,
                corporateCosts=cost,
                financingPrepayments=val("financingPrepayments"),
                cashWithoutFinancingAdjustment=reported - val("financingPrepayments"),
            )
        )
    parts = [
        dict(
            label=label,
            value=sign * v(key),
            fact=dict(
                sourceUrl=source["primaryUrl"],
                components=[
                    dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                    for p in facts[key]["components"]
                ],
            ),
        )
        for key, label, sign in CASH
    ]
    parts.append(
        dict(
            label="각 원 기간의 투자·기타 비현금 조정",
            value=sum(p["coefficient"] * p["fact"]["value"] for p in other_parts),
            fact=dict(sourceUrl=source["primaryUrl"], components=other_parts),
        )
    )
    if sum(p["value"] for p in parts) != v("cfo"):
        raise ValueError("Oracle trailing cash failed")
    revenue = v("revenue")
    corporate = sum(v(k) for k, _ in COSTS)
    lease_proxy = v("leaseCash") - v("leaseInterest")
    if lease_proxy < 0:
        raise ValueError("Oracle total lease less accrued interest proxy negative")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.25,
        netInterest=-v("interest") / revenue,
        depreciation=(v("depreciation") + v("amortization")) / revenue,
        workingCapital=0,
        capexStart=v("capex") / revenue,
        capexEnd=v("capex") / revenue,
        leaseStart=lease_proxy / revenue,
        leaseEnd=lease_proxy / revenue,
        corporateStart=corporate / revenue,
        corporateEnd=corporate / revenue,
        minority=v("minority") / revenue,
        discount=0.12,
        terminal=0.02,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    if any(x not in index for x in PASSAGES):
        raise ValueError("Oracle current passages changed")
    if not all(
        t in index["06e1ca6e5cb1e4067e67"]["text"]
        for t in ["$11.4 billion", "significant financing component"]
    ):
        raise ValueError("Oracle customer financing terms changed")
    if not all(
        t in index["c9b3ab7418f36a54bb39"]["text"]
        for t in ["$288 billion", "fifteen to nineteen"]
    ):
        raise ValueError("Oracle uncommenced leases changed")
    annual_ps = extract(read_verified(DOCUMENT_ROOT / html["file"], ANNUAL_HTML))
    historical = [
        p
        for p in annual_ps
        if "Cash paid for amounts included in the measurement of lease liabilities:"
        in p["text"]
        or "The margins reported reflect only the direct controllable costs"
        in p["text"]
    ]
    if len(historical) != 2:
        raise ValueError("Oracle annual lease/margin definitions missing")
    for item in [
        annual_source,
        html,
        dict(
            annual_source["indexSource"],
            provider="SEC",
            retrievedAt=annual_source["retrievedAt"],
        ),
    ]:
        read_verified(DOCUMENT_ROOT / item["file"], item["sha256"])
        if item["file"] not in {s["file"] for s in c["sources"]}:
            c["sources"].append(item)
    corporate_adjustments = [
        dict(label=label, coefficient=-1, series=facts[key]) for key, label in COSTS
    ]
    m = dict(
        status="research_workspace",
        version="oracle-financing-capacity-cash-v1",
        unallocatedPath=True,
        minorityPath=True,
        capexLimit=2,
        sourcePeriod=["2025-09-01", "2026-08-31"],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        basisLabel="세 기간 부문·현금 대사 / 고객 금융 구분",
        growthLabel="같은 3개월 대비",
        groupLabel="세 보고부문",
        marginLabel="직접 통제비용 차감 마진",
        corporateLabel="연구개발·관리·상각·구조조정·미배분 비용",
        netInterestLabel="총이자 비용 가정 · 리스 발생이자 포함",
        capexLabel="설비 취득 현금",
        leaseLabel="금융리스 원금 대용",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        intro="클라우드·소프트웨어, 하드웨어, 서비스의 직접 통제비용 차감 마진에서 미배분 비용을 모두 뺍니다. 높은 영업현금과 대규모 설비 투자를 고객 선급 금융·추가 리스·신규 자본 조달과 함께 읽습니다.",
        businessCaption="클라우드·소프트웨어는 하나의 보고부문입니다. 클라우드 매출 구분을 별도 클라우드 영업이익으로 만들지 않습니다. 부문 마진은 GAAP 연결 영업이익률이 아니며 연구개발·관리비·상각·주식보상 등을 아래에서 차감합니다.",
        anchorSummary="운전자본 계수0은 영업자금의 추가 소요와 신규 고객 선급 금융을 모두 반복하지 않는 명시적 연구 가정입니다. 투자 미지급·영업 매입채무 및 장기 선급금의 분리 잔액을 확인하지 못했으므로 기말 순부채 비율을 관측 근거로 넣지 않았습니다. 세율25%·성장0도 전망이 아닙니다. 금융리스 총지급−발생이자를 원금 대용으로 사용하며 실제 원금 지급으로 표시하지 않습니다.",
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            residual=0,
            periods=checks,
            cashAfterInvestmentLeaseSbc=None,
        ),
        observedResidualLabel="금융리스 실제 원금과 고객 선급 금융의 귀속·차환 미대사",
        anchors=dict(
            reportedCorporateCost=corporate,
            corporateAdjustments=corporate_adjustments,
            actualFinanceLeasePayment=None,
            financeLeasePrincipalProxy=lease_proxy,
            shareCompensationReplacement=v("sbc"),
            workingStockNet=None,
        ),
        capacityEvidence=dict(
            periods=checks,
            financingPrepayments=facts["financingPrepayments"],
            currentGrossPrepayments=11400000000,
            currentGrossSource=index["06e1ca6e5cb1e4067e67"],
            leaseTotal=facts["leaseCash"],
            leaseInterest=facts["leaseInterest"],
            leasePrincipalProxy=lease_proxy,
            uncommencedLeases=288000000000,
            uncommencedSource=index["c9b3ab7418f36a54bb39"],
            capex=facts["capex"],
            capexRatio=v("capex") / revenue,
            rpo=664000000000,
            rpoSource=index["5a843365a216df755db9"],
        ),
        cashAnchors=[
            dict(
                label=label,
                period="최근1년",
                value=amount,
                sourceUrl=source["primaryUrl"],
                scope=scope,
            )
            for label, amount, scope in [
                (
                    "영업현금에 포함된 고객 선급 금융 조정",
                    v("financingPrepayments"),
                    "현금표 조정액. 총수령액·계약 잔액과 구분",
                ),
                (
                    "설비 취득 현금",
                    v("capex"),
                    "최근 매출보다 큰 지출을 100%로 잘라내지 않음",
                ),
                (
                    "총 감가·무형상각",
                    v("depreciation") + v("amortization"),
                    "금융리스 자산 감가상각 포함; 미래에 한 번 되돌림",
                ),
                (
                    "주식보상 되돌림",
                    v("sbc"),
                    "미래 GAAP 비용에는 주식보상을 남기고 가산하지 않음",
                ),
                ("금융리스 총지급", v("leaseCash"), "원금과 이자가 합쳐진 지급"),
                (
                    "금융리스 발생이자",
                    v("leaseInterest"),
                    "실제 현금이자와 일치한다는 것은 가정",
                ),
                (
                    "총지급−발생이자 원금 대용",
                    lease_proxy,
                    "실제 원금 지급 미확인. 미래 총이자와 함께 차감",
                ),
                (
                    "비지배 순이익 귀속",
                    v("minority"),
                    "실제 배당이 아닌 미래 배분 대용",
                ),
            ]
        ],
        passages=[index[x] for x in PASSAGES],
        historicalPassages=[
            dict(p, sourceUrl=html["url"], sourceHash=ANNUAL_HTML) for p in historical
        ],
        rules=[
            "최근1년은 원 연간+현재 분기−전년 분기이다. 모든 기간의 부문 매출·미배분 비용·연결 이익과 순이익→영업현금을 대사한다.",
            "보고 영업현금에서 고객 선급 금융 조정만 뺀 수치는 세금·고객 계약 이행을 고정한 민감도다. 정상 현금이나 무차입 자금조달 가능액으로 표시하지 않는다.",
            "설비 투자 비율의 지원 범위는 0–200%이다. 현재 원문 지출이 매출을 넘기 때문에 100%로 자르지 않는다. 음수 미래 현금을 자금 조달 계획으로 메우지 않는다.",
            "영업리스 비용은 부문·본사 비용 안에 유지한다. 금융리스는 총이자 안의 발생이자와 별도 원금 대용을 합쳐 총지급에 맞춘 미래 가정이다. 실제 현금이자·원금의 독립 대사는 아니다.",
            "개시 전 리스2880억 달러는 장기간 명목 약정이다. 현재 인식 리스부채나 당기 취득에 추가로 통째로 차감하지 않는다. 추가 개시 후 원가·매출·차환은 이 초기 고정비율 경로에 반영되지 않았다.",
            "대규모 유상증자·우선주·부채 조달은 사업 수익이 아니다. 우선주 보통주 전환과 현재 권리 배분 미확정으로 주당 가격 역산을 보류한다.",
            "투자수익·현금 자산 가치를 가산하지 않고 총이자와 비지배 귀속을 비용으로 유지한다. 구조조정·보험 수령을 임의로 정상화하지 않는다.",
        ],
        remaining=[
            "클라우드 계약별 서비스 개시와 선급금 상각·금융요소 이자",
            "기존 및 추가 데이터센터 사용률·전력·감가상각과 총재투자",
            "투자 미지급·영업 매입채무 및 장기 선급 잔액 분리",
            "금융리스 실제 원금·현금이자와 신규 개시 일정",
            "보통주·필수전환우선주 권리 배분 및 부채 차환",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
