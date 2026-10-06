"""Walmart: consolidated retail cash, segment reconciliation and tariff sensitivity."""

import copy
import json
from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows, select
from .narrative import load, extract

DOCUMENT_ROOT = ROOT
CURRENT = "0000104169-26-000154"
CORPUS = "45aaf841d0122e5297a140fc83cd44f3ffa256323247707ced65cd3f80cc27f1"
SOURCE = "2e39345b995eb8cdc9675225f308bdf3c49dc0ae05787c7d1c61a3291eab2ba5"
ANNUAL = "0000104169-26-000055"
ANNUAL_SHA = "07c72faa90cf8515eb1ff1ca264361ca8741c2663202d2f5a25ff9c694f4ef67"
ANNUAL_HTML = "a5a89df81bcfae169f814353a432251b999f94768792c7a5be9b0ff1fa066414"
TAGS = dict(
    revenue="Revenues",
    merchandise="RevenueFromContractWithCustomerExcludingAssessedTax",
    membershipOther="OtherIncome",
    cost="CostOfRevenue",
    selling="SellingGeneralAndAdministrativeExpense",
    operatingIncome="OperatingIncomeLoss",
    netIncome="ProfitLoss",
    depreciation="DepreciationAmortizationAndAccretionNet",
    investment="GainLossOnInvestments",
    deferred="IncreaseDecreaseInDeferredIncomeTaxes",
    other="OtherNoncashIncomeExpense",
    receivables="IncreaseDecreaseInAccountsAndOtherReceivables",
    inventory="IncreaseDecreaseInRetailRelatedInventories",
    payables="IncreaseDecreaseInAccountsPayable",
    accrued="IncreaseDecreaseInAccruedLiabilities",
    taxPayable="IncreaseDecreaseInAccruedTaxesPayable",
    cfo="NetCashProvidedByUsedInOperatingActivities",
    capex="PaymentsToAcquirePropertyPlantAndEquipment",
    otherInvesting="PaymentsForProceedsFromOtherInvestingActivities",
    otherFinancing="ProceedsFromPaymentsForOtherFinancingActivities",
    interest="InterestIncomeExpenseNonoperatingNet",
    minority="NetIncomeLossAttributableToNoncontrollingInterest",
)
CASH = [
    ("netIncome", "비지배 포함 연결 순이익", 1),
    ("depreciation", "감가·상각 (금융리스 포함)", 1),
    ("investment", "투자 손익 제거", -1),
    ("deferred", "이연법인세 조정", -1),
    ("other", "기타 비현금 조정", -1),
    ("receivables", "채권 현금 효과", -1),
    ("inventory", "재고 현금 효과", -1),
    ("payables", "매입채무 현금 효과", 1),
    ("accrued", "미지급 비용 현금 효과", 1),
    ("taxPayable", "납부세금 부채 현금 효과", 1),
]


def build(c, as_of):
    from .operating_model import calculate

    meta = c.get("narrative") or {}
    if meta.get("accession") != CURRENT or meta.get("evidenceHash") != CORPUS:
        return dict(
            status="source_review_required",
            reason="Walmart의 관세환급·회원비 및 기타수입·리스 범위를 새 공시에서 대사해야 합니다.",
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
        or any(x["cik"] != 104169 or x["accession"] != ANNUAL for x in [a, h])
        or as_of < "2026-08-28"
    ):
        raise ValueError("Walmart source identity or date changed")
    annual = instance_rows(
        read_verified(DOCUMENT_ROOT / a["file"], ANNUAL_SHA), c, a, ANNUAL, "2026-03-13"
    )
    periods = [
        (1, annual, "2025-02-01", "2026-01-31"),
        (1, rows, "2026-02-01", "2026-07-31"),
        (-1, rows, "2025-02-01", "2025-07-31"),
    ]
    if [c["financials"]["start"], c["financials"]["end"]] != [
        "2026-02-01",
        "2026-07-31",
    ]:
        raise ValueError("Walmart six month scope changed")

    def exact(rs, tag, start, end, dims=()):
        # The prose rounds 14.203bn to 14.2bn; the cash table reports exact millions.
        if tag in {
            "DepreciationAmortizationAndAccretionNet",
            "AllocatedShareBasedCompensationExpense",
        }:
            rs = [r for r in rs if r.get("decimals") == "-6"]
        result = select(rs, tag, start, end, dims, "USD")
        if result is None:
            raise ValueError(f"Walmart missing fact {tag} {start} {end}")
        return result

    def combined(tag, dims=()):
        parts = [
            dict(coefficient=k, fact=exact(rs, tag, start, end, dims))
            for k, rs, start, end in periods
        ]
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
            components=parts,
            sourceUrl=source["primaryUrl"],
            unit="USD",
        )

    facts = {k: combined(tag) for k, tag in TAGS.items()}
    v = lambda k: facts[k]["value"]
    geographies = []
    for member, label in [
        ("WalmartUSMember", "Walmart 미국"),
        ("WalmartInternationalMember", "Walmart 국제"),
        ("SamsClubUSMember", "Sam’s Club 미국"),
    ]:
        dims = [
            ("ConsolidationItemsAxis", "OperatingSegmentsMember"),
            ("StatementBusinessSegmentsAxis", member),
        ]
        geographies.append(
            dict(
                label=label,
                merchandise=combined(TAGS["merchandise"], dims),
                membershipOther=combined("OtherIncome", dims),
                operatingIncome=combined("OperatingIncomeLoss", dims),
            )
        )
    corporate_dims = [("ConsolidationItemsAxis", "CorporateAndReconcilingItemsMember")]
    corporate_income = combined("OtherIncome", corporate_dims)
    corporate_profit = combined("OperatingIncomeLoss", corporate_dims)
    checks = []
    for i, (_, _, start, end) in enumerate(periods):
        val = lambda k: facts[k]["components"][i]["fact"]["value"]
        parts = [
            dict(
                label=label, value=sign * val(k), fact=facts[k]["components"][i]["fact"]
            )
            for k, label, sign in CASH
        ]
        segment_revenue = sum(
            x[k]["components"][i]["fact"]["value"]
            for x in geographies
            for k in ["merchandise", "membershipOther"]
        )
        segment_op = sum(
            x["operatingIncome"]["components"][i]["fact"]["value"] for x in geographies
        )
        other_income = corporate_income["components"][i]["fact"]["value"]
        other_profit = corporate_profit["components"][i]["fact"]["value"]
        if (
            sum(x["value"] for x in parts) != val("cfo")
            or val("revenue") - val("cost") - val("selling") != val("operatingIncome")
            or val("merchandise") + val("membershipOther") != val("revenue")
            or segment_revenue + other_income != val("revenue")
            or segment_op + other_profit != val("operatingIncome")
        ):
            raise ValueError("Walmart period cash/profit/segment reconciliation failed")
        checks.append(
            dict(
                start=start,
                end=end,
                parts=parts,
                reportedCfo=val("cfo"),
                operatingIncome=val("operatingIncome"),
                revenue=val("revenue"),
                membershipOther=val("membershipOther"),
                segmentRevenue=segment_revenue,
                corporateIncome=other_income,
                corporateProfit=other_profit,
                corporateCosts=other_income - other_profit,
                residual=0,
            )
        )
    stock = [
        dict(coefficient=k, label=label, fact=exact(rows, tag, None, "2026-07-31"))
        for k, label, tag in [
            (1, "수취채권 순액", "ReceivablesNetCurrent"),
            (1, "상품 재고", "InventoryNet"),
            (-1, "매입채무", "AccountsPayableCurrent"),
        ]
    ]
    stock_net = sum(x["coefficient"] * x["fact"]["value"] for x in stock)
    yearly = lambda tag: exact(annual, tag, "2025-02-01", "2026-01-31")
    lease = yearly("FinanceLeasePrincipalPayments")
    acquisition = yearly("PaymentsToAcquireBusinessesNetOfCashAcquired")
    annual_lease_interest = yearly("FinanceLeaseInterestExpense")
    face_interest = yearly("FinanceLeaseAndFinancingObligationInterestExpense")
    annual_sbc = yearly("AllocatedShareBasedCompensationExpense")
    annual_lease_cost = yearly("OperatingLeaseCost")
    annual_lease_cash = yearly("OperatingLeasePayments")
    annual_revenue = facts["revenue"]["components"][0]["fact"]["value"]
    revenue = v("revenue")
    margin = (revenue - v("cost")) / revenue
    defaults = dict(
        segments=[dict(growthStart=0, growthEnd=0, marginEnd=margin)],
        researchStart=0,
        researchEnd=0,
        sellingStart=v("selling") / revenue,
        sellingEnd=v("selling") / revenue,
        otherOperatingStart=0,
        otherOperatingEnd=0,
        minority=v("minority") / revenue,
        tax=0.25,
        netInterest=v("interest") / revenue,
        depreciation=v("depreciation") / revenue,
        workingCapital=stock_net / revenue,
        capexStart=(v("capex") + v("otherInvesting")) / revenue
        + acquisition["value"] / annual_revenue,
        capexEnd=(v("capex") + v("otherInvesting")) / revenue
        + acquisition["value"] / annual_revenue,
        leaseStart=lease["value"] / annual_revenue,
        leaseEnd=lease["value"] / annual_revenue,
        discount=0.12,
        terminal=0.02,
    )
    if v("otherInvesting") < 0:
        raise ValueError("Review net other-investing inflow before using a future cost")
    index = {p["id"]: p for p in load(c)["passages"]}
    annual_index = {
        p["id"]: p
        for p in extract(read_verified(DOCUMENT_ROOT / h["file"], ANNUAL_HTML))
    }
    for pid, text in [
        ("b508d00fd64fc56ca244", "2.9 billion"),
        ("8697bb7798567908b8de", "price investment"),
        ("aead6539ce98248353f2", "gift card"),
        ("2ee01a4888371f6a605f", "(1,643)"),
    ]:
        if text not in index[pid]["text"]:
            raise ValueError("Walmart current scope changed")
    if (
        "$4.4 billion" not in annual_index["915bcd947a06204fe180"]["text"]
        or "finance leases" not in annual_index["d54cf73a43d525abb16a"]["text"]
    ):
        raise ValueError("Walmart annual membership/depreciation scope changed")
    for s in [
        a,
        h,
        dict(a["indexSource"], provider="SEC", retrievedAt=a["retrievedAt"]),
    ]:
        read_verified(DOCUMENT_ROOT / s["file"], s["sha256"])
        if s["file"] not in {x["file"] for x in c["sources"]}:
            c["sources"].append(s)
    hold = "연간 금융리스 이자 본표/주석 차이와 최근1년 순수 리스원금·취득 지출, 관세환급을 사용한 가격투자 범위 대사가 필요합니다."
    security = copy.deepcopy(c["valuation"]["security"])
    security.update(status="unresolved", marketCapProxy=None)
    m = dict(
        status="research_workspace",
        version="walmart-retail-refund-cash-v1",
        sourcePeriod=["2025-08-01", "2026-07-31"],
        accession=CURRENT,
        corpusHash=CORPUS,
        currency="USD",
        displayScale=1e9,
        displayUnit="십억 달러",
        basisLabel="연간+현재반기−전년반기 · 연결 소매 현금",
        groupLabel="연결 전체 (세 사업부·본사 포함)",
        growthLabel="반기 동기 대비",
        marginLabel="연결 총매출−상품 원가 비율",
        grossProfitPath=True,
        grossProfitLabel="회원비·기타수입 포함 연결 총매출−원가",
        sellingLabel="판매관리비",
        otherOperatingLabel="추가 공통 비용 가정",
        capexLabel="설비·기타 투자·연간 인수 대용",
        leaseLabel="연간 금융리스 원금 비율 대용",
        netInterestLabel="공시 순이자 (비용−)",
        intro="상품매출·회원비 및 기타수입에서 원가·판매관리비를 빼는 연결 현금 경로입니다. 세 사업부의 실제 이익과 본사 수입·비용은 별도 대사표로 보존합니다. 본사 수입을 가짜 네 번째 사업의 이익률로 만들지 않습니다.",
        businessCaption="총매출에서 원가를 뺀 비율에는 회원비와 기타수입이 포함됩니다. 상품 매출만 분모로 하는 회사의 gross profit rate와 다릅니다. 세 사업부의 독립 미래 가정은 이 연결 경로에서 분리해 추정하지 않습니다.",
        anchorSummary="수취채권+재고−매입채무의 좁은 기말 잔액을 추가 매출의 자금 대용으로 사용합니다. 이연 회원비·세금·기타 부채의 전체 현금 전환을 포괄하지 않습니다. 성장0·세율25%와 공시 비율의 반복은 연구자 가정입니다.",
        segments=[
            dict(
                id="ConsolidatedRetail",
                label="연결 소매·회원비·기타수입",
                revenue=revenue,
                margin=margin,
                observedGrowth=facts["revenue"]["components"][1]["fact"]["value"]
                / facts["revenue"]["components"][2]["fact"]["value"]
                - 1,
                evidence=[facts["revenue"], facts["cost"]],
            )
        ],
        facts=facts,
        defaults=defaults,
        security=security,
        priceHoldReason=hold,
        bridge=dict(
            parts=[
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
            ],
            periods=checks,
            reportedCfo=v("cfo"),
            residual=0,
            cashAfterInvestmentLeaseSbc=None,
        ),
        anchors=dict(
            workingStockTerms=stock,
            workingStockNet=stock_net,
            actualFinanceLeasePrincipal=None,
            shareCompensationReplacement=None,
        ),
        retailerEvidence=dict(
            periods=checks,
            geographies=geographies,
            corporateIncome=corporate_income,
            corporateProfit=corporate_profit,
            tariffRefundApprox=2900000000,
            refundUseQuantified=None,
            refundScope="관세환급 약29억 달러는 현금 수취·원가 감소입니다. 상당 부분을 고객 가격·원가 완화에 사용했으나 금액은 미공시입니다. 환급 총액만 제거한 값은 다른 효과를 고정한 민감도이며 정상 영업이익이 아닙니다.",
            currentOperatingIncome=checks[1]["operatingIncome"],
            profitExcludingGrossRefund=checks[1]["operatingIncome"] - 2900000000,
            annualMembershipApprox=4400000000,
            annualMembershipOther=facts["membershipOther"]["components"][0]["fact"],
            actualTrailingMembership=None,
            annualFinanceLeasePrincipal=lease,
            annualFinanceInterestFace=face_interest,
            annualFinanceInterestNote=annual_lease_interest,
            annualFinanceInterestDifference=face_interest["value"]
            - annual_lease_interest["value"],
            annualSbc=annual_sbc,
            actualTrailingSbc=None,
            actualTrailingFinancePrincipal=None,
            otherFinancing=facts["otherFinancing"],
            annualAcquisitions=acquisition,
            actualTrailingAcquisitions=None,
            annualOperatingLeaseCost=annual_lease_cost,
            annualOperatingLeaseCash=annual_lease_cash,
            annualLeaseTimingDifference=annual_lease_cost["value"]
            - annual_lease_cash["value"],
            workingStockTerms=stock,
            workingStockNet=stock_net,
        ),
        passages=[
            index[x]
            for x in [
                "8697bb7798567908b8de",
                "aead6539ce98248353f2",
                "5890a49b75093e55b8f6",
                "2a41993eec109e244627",
                "2ee01a4888371f6a605f",
                "b1254947c2bce0621975",
            ]
        ],
        historicalPassages=[
            dict(annual_index[x], sourceUrl=h["url"], sourceHash=ANNUAL_HTML)
            for x in [
                "915bcd947a06204fe180",
                "d54cf73a43d525abb16a",
                "190b8bf07a0b07476cef",
                "3a3e035ca56374994dec",
            ]
        ],
        rules=[
            "관세환급을 이미 포함한 보고 마진에서 출발한다. 환급을 또 가산하거나 환급 총액 제거만으로 정상화를 확정하지 않는다.",
            "회원비 및 기타수입에는 임대·재활용·기프트카드 소멸·본사 시설 수입이 포함된다. 전액을 Costco 순수 회원비와 비교하지 않는다.",
            "금융리스 자산 상각은 현금표 감가상각에 이미 포함되어 미래 현금에 다시 가산하지 않는다. 주식보상은 미래 비용에 유지한다.",
            "연간 금융리스 원금·인수 지출/연간 매출을 미래 대용으로 명시한다. 최근1년 실제값 미확인을 영으로 바꾸지 않는다. 넓은 기타 금융활동 지급을 순수 리스 지급으로 대체하지 않는다.",
            "영업리스 비용은 영업비용에 유지한다. 연간 비용·현금 시차와 이자 본표/주석 차이는 미대사로 남기고 주당·가격 역산을 보류한다.",
        ],
        remaining=[
            "관세환급을 사용한 가격투자 금액과 재고 판매 시점",
            "이자 본표/리스 주석 차이와 최근1년 리스·기업취득 현금",
            "순수 회원비·광고·전자상거래의 비용 및 사업부 기여",
            "유지·자동화·확장 투자와 공급사 자금의 지속 가능성",
            "현재 가격에 필요한 정상 주주 현금·비지배 귀속",
        ],
    )
    m["initial"] = calculate(m, defaults)
    m["evidenceHash"] = digest(canonical(m))
    return m
