"""Costco: geographic operating profit, membership recognition and retail funding."""

import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "0000909832-26-000051"
CORPUS = "46df96241e0aace626c522b3f5cf75f0daa5af961f095c9e2e9196ac291bdb7c"
SOURCE = "bb9bffef746e7e82ade8d9331861424934273c55c6ef7d2fbaedefd25c907582"
ANNUAL = "0000909832-25-000101"
ANNUAL_SHA = "6d06826d798a21684e74f07edb35e8e48db55261e2edd63c4ac169e0b0d6d89e"
ANNUAL_HTML = "233fcf9d91cc8d536adbc49cbfe44a990e72fe50d43d1a3ca4aafc9d8af97d3e"
TAGS = dict(
    revenue="RevenueFromContractWithCustomerExcludingAssessedTax",
    netIncome="NetIncomeLoss",
    operatingIncome="OperatingIncomeLoss",
    depreciation="DepreciationDepletionAndAmortization",
    leaseNoncash="OperatingandFinancingLeaseRightofUseAssetAmortization",
    sbc="ShareBasedCompensation",
    inventory="IncreaseDecreaseInInventories",
    payables="IncreaseDecreaseInAccountsPayable",
    otherWorking="IncreaseDecreaseInOtherOperatingCapitalNet",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    capex="PaymentsToAcquirePropertyPlantAndEquipment",
    lease="FinanceLeasePrincipalPayments",
    interest="InterestExpense",
    otherInvesting="PaymentsForProceedsFromOtherInvestingActivities",
)
CASH = [
    ("netIncome", "연결 순이익", 1),
    ("depreciation", "감가·상각", 1),
    ("leaseNoncash", "비현금 리스 비용", 1),
    ("sbc", "주식보상 되돌림", 1),
    ("other", "기타 비현금 조정", -1),
    ("inventory", "재고의 현금 효과", -1),
    ("payables", "매입채무의 현금 효과", 1),
    ("otherWorking", "기타 영업자산·부채", -1),
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="Costco의 회원비·지역 손익·리스와 재고 자금의 범위를 새 공시에서 대사해야 합니다.",
        )
    source, rows = company_filing(c, as_of)
    a = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}-xbrl.manifest.json").read_text()
    )
    h = json.loads(
        (DOCUMENT_ROOT / f"data/sources/filing-{ANNUAL}.manifest.json").read_text()
    )
    if (
        source["sha256"] != SOURCE
        or a["sha256"] != ANNUAL_SHA
        or h["sha256"] != ANNUAL_HTML
        or any(x["cik"] != 909832 or x["accession"] != ANNUAL for x in [a, h])
        or as_of < "2026-06-03"
    ):
        raise ValueError("Costco source identity or date changed")
    annual = instance_rows(
        read_verified(DOCUMENT_ROOT / a["file"], ANNUAL_SHA), c, a, ANNUAL, "2025-10-08"
    )
    periods = [
        (1, annual, "2024-09-02", "2025-08-31"),
        (1, rows, "2025-09-01", "2026-05-10"),
        (-1, rows, "2024-09-02", "2025-05-11"),
    ]
    if [c["financials"]["start"], c["financials"]["end"]] != [
        "2025-09-01",
        "2026-05-10",
    ]:
        raise ValueError("Costco 36-week period changed")

    def exact(rs, tag, start, end, dims=()):
        result = select(rs, tag, start, end, dims, "USD")
        if result is None:
            raise ValueError(f"Costco missing fact {tag} {start} {end}")
        return result

    def combined(tags, dims=()):
        ts = [tags] * 3 if isinstance(tags, str) else tags
        parts = [
            dict(coefficient=k, fact=exact(rs, ts[i], start, end, dims))
            for i, (k, rs, start, end) in enumerate(periods)
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            sourceUrl=source["primaryUrl"],
            unit="USD",
        )

    facts = {k: combined(tag) for k, tag in TAGS.items()}
    facts["other"] = combined(
        [
            "ImpairmentOfAssetsAndOtherNonCashOperatingActivitiesNet",
            "OtherNoncashIncomeExpense",
            "OtherNoncashIncomeExpense",
        ]
    )
    facts["membership"] = combined(
        TAGS["revenue"], [("ProductOrServiceAxis", "MembershipMember")]
    )
    facts["merchandise"] = combined(
        TAGS["revenue"], [("ProductOrServiceAxis", "ProductMember")]
    )
    v = lambda k: facts[k]["value"]
    segments = []
    for member, label in [
        ("UnitedStatesMember", "미국"),
        ("CanadaMember", "캐나다"),
        ("OtherInternationalMember", "기타 국제"),
    ]:
        dims = [
            ("ConsolidationItemsAxis", "OperatingSegmentsMember"),
            ("StatementBusinessSegmentsAxis", member),
        ]
        sales = combined(["Revenues", TAGS["revenue"], TAGS["revenue"]], dims)
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
    for i, (_, _, start, end) in enumerate(periods):
        val = lambda k: facts[k]["components"][i]["fact"]["value"]
        parts = [
            dict(
                label=label, value=sign * val(k), fact=facts[k]["components"][i]["fact"]
            )
            for k, label, sign in CASH
        ]
        if (
            sum(x["value"] for x in parts) != val("cfo")
            or val("membership") + val("merchandise") != val("revenue")
            or any(
                sum(
                    x["evidence"][j]["components"][i]["fact"]["value"] for x in segments
                )
                != val(k)
                for j, k in [(0, "revenue"), (1, "operatingIncome")]
            )
        ):
            raise ValueError("Costco cash/segment/membership reconciliation failed")
        checks.append(
            dict(
                start=start,
                end=end,
                reportedCfo=val("cfo"),
                operatingIncome=val("operatingIncome"),
                membership=val("membership"),
                merchandise=val("merchandise"),
                parts=parts,
                residual=0,
            )
        )
    stock = [
        dict(coefficient=k, label=label, fact=exact(rows, tag, None, "2026-05-10"))
        for k, label, tag in [
            (1, "총수취채권 · 공급사·카드·재보험·약국 등", "ReceivablesNetCurrent"),
            (1, "상품 재고", "InventoryNet"),
            (-1, "매입채무", "AccountsPayableCurrent"),
            (-1, "이연 회원비", "DeferredRevenueCurrent"),
        ]
    ]
    stock_net = sum(x["coefficient"] * x["fact"]["value"] for x in stock)
    annual_finance_amort = exact(
        annual, "FinanceLeaseRightOfUseAssetAmortization", "2024-09-02", "2025-08-31"
    )
    annual_operating_cost = exact(
        annual, "OperatingLeaseCost", "2024-09-02", "2025-08-31"
    )
    annual_operating_cash = exact(
        annual, "OperatingLeasePayments", "2024-09-02", "2025-08-31"
    )
    annual_revenue = facts["revenue"]["components"][0]["fact"]["value"]
    finance_amort_ratio = annual_finance_amort["value"] / annual_revenue
    revenue = v("revenue")
    defaults = dict(
        segments=[
            dict(growthStart=0, growthEnd=0, marginEnd=s["margin"]) for s in segments
        ],
        tax=0.25,
        netInterest=-v("interest") / revenue,
        depreciation=v("depreciation") / revenue + finance_amort_ratio,
        workingCapital=stock_net / revenue,
        capexStart=v("capex") / revenue,
        capexEnd=v("capex") / revenue,
        leaseStart=v("lease") / revenue,
        leaseEnd=v("lease") / revenue,
        discount=0.12,
        terminal=0.02,
    )
    index = {p["id"]: p for p in load(c)["passages"]}
    annual_index = {
        p["id"]: p
        for p in extract(read_verified(DOCUMENT_ROOT / h["file"], ANNUAL_HTML))
    }
    for pid, text in [
        ("90ca49f51eaa0106e648", "4,057"),
        ("a2d7ede4eec902109ae8", "Deferred membership fees"),
        ("c2436f6a9ddcb9d87333", "recognized ratably"),
        ("cfbe51577066f1375915", "seven to eighteen"),
        ("3057a4fd9e0e5e9117e5", "221"),
    ]:
        if text not in index[pid]["text"]:
            raise ValueError("Costco current scope changed")
    if "(117)" not in annual_index["81750dcb13d16be014c5"]["text"]:
        raise ValueError("Costco annual other-noncash sign changed")
    for source_ in [a, h]:
        if source_["file"] not in {x["file"] for x in c["sources"]}:
            c["sources"].append(source_)
    parts = [
        dict(
            label=label,
            value=sign * v(k),
            fact=dict(
                sourceUrl=source["primaryUrl"],
                components=[
                    dict(coefficient=sign * p["coefficient"], fact=p["fact"])
                    for p in facts[k]["components"]
                ],
            ),
        )
        for k, label, sign in CASH
    ]
    m = dict(
        status="research_workspace",
        version="costco-membership-retail-cash-v1",
        sourcePeriod=["2025-05-12", "2026-05-10"],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        basisLabel="52주 연간+현재36주−전년36주",
        growthLabel="동기36주 대비",
        groupLabel="공시 지역별 영업부문",
        segments=segments,
        facts=facts,
        defaults=defaults,
        security=c["valuation"]["security"],
        netInterestLabel="총이자 비용",
        capexLabel="설비 현금 취득",
        leaseLabel="금융리스 원금",
        intro="미국·캐나다·기타 국제의 공시 영업이익을 연결합니다. 회원비는 각 부문 매출과 이익에 이미 들어 있으며 추가 이익으로 다시 더하지 않습니다. 가격·방문 빈도·휘발유·환율에 관한 회사 설명은 독립 원인 검증과 구분합니다.",
        businessCaption="부문 간 매출·비용과 로열티는 연결 금액 계산에서 제거됐습니다. 회원비가 중요한 경제 구조라는 사실을 무비용 독립 이익으로 바꾸지 않습니다. 본문 상품 총마진의 분모는 순상품매출이며 회원비 포함 총매출과 다릅니다.",
        anchorSummary="공급사·카드·재보험·약국 등이 섞인 수취채권+재고−매입채무−이연 회원비의 좁은 잔액을 증가 매출 자금의 대용으로 사용합니다. 음수는 영구적 무상 자금이나 실제 회전일수가 아닙니다. 성장0·세율25%와 현재 비율의 반복은 연구 가정입니다.",
        bridge=dict(
            parts=parts,
            reportedCfo=v("cfo"),
            periods=checks,
            residual=0,
            cashAfterInvestmentLeaseSbc=None,
        ),
        observedResidualLabel="보고 현금과 정상 주주 현금의 구분 필요",
        anchors=dict(
            workingStockTerms=stock,
            workingStockNet=stock_net,
            actualFinanceLeasePrincipal=v("lease"),
            shareCompensationReplacement=v("sbc"),
        ),
        retailEvidence=dict(
            periods=checks,
            membership=facts["membership"],
            merchandise=facts["merchandise"],
            deferredMembership=stock[-1]["fact"],
            workingStockTerms=stock,
            workingStockNet=stock_net,
            annualFinanceAmortization=annual_finance_amort,
            financeAmortizationRatio=finance_amort_ratio,
            actualTrailingFinanceAmortization=None,
            annualOperatingLeaseCost=annual_operating_cost,
            annualOperatingLeaseCash=annual_operating_cash,
            annualLeaseTimingDifference=annual_operating_cost["value"]
            - annual_operating_cash["value"],
            renewalWindowMonths=[7, 18],
            renewalFutureProbability=None,
        ),
        cashAnchors=[
            dict(
                label=label,
                period=period,
                value=value,
                sourceUrl=source["primaryUrl"],
                scope=scope,
            )
            for label, period, value, scope in [
                (
                    "설비 현금 취득",
                    "최근52주",
                    v("capex"),
                    "순투자 총액·비현금 신규 리스와 구분",
                ),
                (
                    "금융리스 원금",
                    "최근52주",
                    v("lease"),
                    "현금에서 한 번 차감, 이자와 별도",
                ),
                (
                    "감가·상각 현금표 항목",
                    "최근52주",
                    v("depreciation"),
                    "비현금 리스 항목 전체를 다시 가산하지 않음",
                ),
                (
                    "금융리스 자산 상각",
                    "마지막 연간",
                    annual_finance_amort["value"],
                    "연간 매출 비율의 미래 대용. 실제 최근52주 금융상각 미확인",
                ),
                (
                    "비현금 리스 비용 전체",
                    "최근52주",
                    v("leaseNoncash"),
                    "전액 미래 가산을 피하고 영업리스 비용은 부문 이익에 유지",
                ),
                (
                    "주식보상 비용",
                    "최근52주",
                    v("sbc"),
                    "미래 영업비용에 유지, 보고 CFO 가산과 구분",
                ),
                (
                    "회원비 수익",
                    "최근52주",
                    v("membership"),
                    "기간 배분한 매출. 별도 현금 유입·무비용 이익 아님",
                ),
            ]
        ],
        passages=[
            index[pid]
            for pid in [
                "b0dfd5236d7c37c5f26c",
                "cfbe51577066f1375915",
                "c2436f6a9ddcb9d87333",
                "d8f93c4e1984a17d56a0",
                "da49dc6d4dd7cd99d9c0",
                "a9ea5d4b557d048003be",
                "606be59e56641838740d",
                "3057a4fd9e0e5e9117e5",
            ]
        ],
        historicalPassages=[
            dict(annual_index[pid], sourceUrl=h["url"], sourceHash=ANNUAL_HTML)
            for pid in [
                "1182782fcb4bddbbeaae",
                "81750dcb13d16be014c5",
                "4508074376067e3f3778",
                "65060562f7087b3a6323",
                "9d4ac2d6557ec8c0dfde",
            ]
        ],
        rules=[
            "52주 연간과 같은36주 누적을 연결하고 지역 손익·회원비 포함 매출·간접현금표를 각각 대사한다.",
            "회원비는 일년 기간에 걸쳐 인식한다. 이연 회원비 잔액과 당기 회원비 수익을 두 번의 현금 유입으로 더하지 않는다.",
            "갱신율은 보고일 전 일곱~열여덟 달의 갱신을 포착하는 회사의 과거 계산이다. 향후 고객 유지 확률·추천 확률로 사용하지 않는다.",
            "기타 비현금 조정은 원문 부호로 연결한다. 순수 상품매출·회원비 포함 총매출·휘발유 가격 제외 비율은 분모가 다르다.",
            "금융리스 자산의 최근52주 상각은 미확인이다. 확인된 연간 상각/매출을 미래 대용으로 따로 가산하며 전체 비현금 리스 되돌림을 다시 더하지 않는다. 영업리스 비용은 부문 이익에 남기는 현금 지급 대용 가정이다.",
            "총이자 비용과 금융리스 원금은 따로 차감한다. 주식보상 가산·기타 투자 순유입·금융이자수입을 미래 반복 현금에 추가하지 않는다.",
        ],
        remaining=[
            "최근52주 금융리스 상각 및 영업리스 비용·지급 시차",
            "갱신 코호트·회원 구성·인상 효과와 신규 창고의 기여",
            "상품별 가격·물량·휘발유·환율 효과와 경쟁 가격",
            "재고·공급사 결제·할인·혼합 수취채권의 지속 가능한 자금 구조",
            "창고 유지·확장 투자와 비현금 신규 리스·순초과자산 배분",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
