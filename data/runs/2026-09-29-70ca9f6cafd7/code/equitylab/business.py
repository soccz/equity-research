"""Filing-specific operating segments, capital commitments and cash boundaries."""

from datetime import date
from .data import canonical, digest
from .dossier import price_requirements
from .xbrl import instance_rows, select, company_filing
from .segment_profiles import PROFILES, build_profile

CONSOLIDATED = ("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")
SEGMENTS = ("SegmentConsolidationItemsAxis", "OperatingSegmentsMember")
ELIMINATION = (
    "SegmentConsolidationItemsAxis",
    "EliminationOfIntersegmentAmountsMember",
)


def required(fact, description):
    if fact is None:
        raise ValueError("Business note missing: " + description)
    return fact


def reconcile(parts, total, adjustment=None):
    if any(p is None for p in parts) or total is None:
        return dict(status="unresolved", reason="필수 원문 항목 미확인")
    subtotal = sum(p["value"] for p in parts)
    residual = total["value"] - subtotal
    tolerance = max(1, abs(total["value"]) * 1e-10)
    explained = adjustment["value"] if adjustment else 0
    return dict(
        status=(
            "reconciled"
            if abs(residual - explained) <= tolerance
            else "unresolved_difference"
        ),
        subtotal=subtotal,
        reportedTotal=total["value"],
        reportedAdjustment=adjustment["value"] if adjustment else None,
        residual=residual,
        unexplained=residual - explained,
        evidence=parts + [total] + ([adjustment] if adjustment else []),
    )


def microsoft(c, rows):
    f = c["financials"]

    def item(tag, start=None, dims=()):
        return select(rows, tag, start, f["end"], dims, c["currency"])

    segments = []
    for key, label in [
        ("ProductivityAndBusinessProcesses", "생산성·비즈니스 프로세스"),
        ("IntelligentCloud", "인텔리전트 클라우드"),
        ("MorePersonalComputing", "개인용 컴퓨팅"),
    ]:
        dims = [("StatementBusinessSegmentsAxis", key + "Member")]
        periods = {}
        for period, start, end in [
            ("current", f["start"], f["end"]),
            ("previous", f["priorStart"], f["priorEnd"]),
        ]:
            periods[period] = {
                metric: select(rows, tag, start, end, dims, c["currency"])
                for metric, tag in [
                    ("revenue", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                    ("operatingIncome", "OperatingIncomeLoss"),
                ]
            }
        required(periods["current"]["revenue"], key + " revenue")
        required(periods["current"]["operatingIncome"], key + " operating profit")
        segments.append(dict(id=key, label=label, **periods))
    reconciliations = {
        key: reconcile([s["current"][key] for s in segments], f["current"][metric])
        for key, metric in [
            ("revenue", "revenue"),
            ("operatingIncome", "operating_income"),
        ]
    }
    if any(x["status"] != "reconciled" for x in reconciliations.values()):
        raise ValueError("Microsoft segment totals do not reconcile")
    balances = {
        key: item(tag)
        for key, tag in [
            ("cash", "CashAndCashEquivalentsAtCarryingValue"),
            ("shortInvestments", "ShortTermInvestments"),
            ("cashAndInvestments", "CashCashEquivalentsAndShortTermInvestments"),
            ("debt", "LongTermDebt"),
            ("debtCurrent", "LongTermDebtCurrent"),
            ("debtNoncurrent", "LongTermDebtNoncurrent"),
            ("financeLease", "FinanceLeaseLiability"),
            ("operatingLease", "OperatingLeaseLiability"),
        ]
    }
    balance_checks = {
        "debt": reconcile(
            [balances["debtCurrent"], balances["debtNoncurrent"]], balances["debt"]
        ),
        "liquidity": reconcile(
            [balances["cash"], balances["shortInvestments"]],
            balances["cashAndInvestments"],
        ),
    }
    if any(x["status"] != "reconciled" for x in balance_checks.values()):
        raise ValueError("Microsoft capital balances do not reconcile")
    lease = {
        key: item(tag, f["start"])
        for key, tag in [
            ("principal", "FinanceLeasePrincipalPayments"),
            ("interest", "FinanceLeaseInterestPaymentOnLiability"),
            ("operatingPayments", "OperatingLeasePayments"),
            (
                "noncashFinanceAdditions",
                "RightOfUseAssetObtainedInExchangeForFinanceLeaseLiability",
            ),
            (
                "noncashOperatingAdditions",
                "RightOfUseAssetObtainedInExchangeForOperatingLeaseLiability",
            ),
        ]
    }
    principal = required(lease["principal"], "finance lease principal")
    # Financing cash outflow is added to the cash deductions once. Operating
    # lease payments/finance interest are already within reported US-GAAP CFO.
    cash = dict(
        reportedCfo=f["current"]["cfo"],
        cashPurchases=f["current"]["capex"],
        financingLeasePrincipal=principal,
        afterCashPurchases=c["metrics"]["cashAfterInvestment"],
        afterLeasePrincipal=c["metrics"]["cashAfterInvestment"] - principal["value"],
        definition="영업현금 − 현금 유형자산 취득 − 금융리스 원금 상환",
        limitation="영업리스 지급·금융리스 이자는 영업현금에 이미 포함되어 다시 빼지 않는다. 신규 비현금 리스 취득은 당기 현금지출과 구분한다. 이 잔액은 정상화 FCFE가 아니다.",
    )
    shares = select(rows, "CommonStockSharesOutstanding", None, f["end"], (), "shares")
    pricing = None
    if shares and shares["value"] > 0:
        cap = shares["value"] * c["priceSummary"]["close"]
        pricing = dict(
            shares=shares,
            marketCapProxy=cap,
            close=c["priceSummary"]["close"],
            priceDate=c["priceSummary"]["lastDate"],
            shareDate=f["end"],
            shareAgeDays=(
                date.fromisoformat(c["priceSummary"]["lastDate"])
                - date.fromisoformat(f["end"])
            ).days,
            defaults=dict(growth=0.1, discount=0.11, terminal=0.02, horizon=5),
            base=price_requirements(cap, 0.1, 0.11),
            referenceCash=cash["afterLeasePrincipal"],
            referenceDefinition=cash["definition"],
            limitation="보통주 공시 잔액×관측 종가의 근사 주식가치. 이후 희석·소각 미반영. 요구 현금과 관측 잔액의 차이는 과대·과소평가 판정이 아니며 정상화·사업부 전망 검토가 필요하다.",
        )
    if pricing:
        pricing["sensitivity"] = [
            dict(
                growth=g,
                discount=k,
                **price_requirements(pricing["marketCapProxy"], g, k),
            )
            for k in [0.08, 0.11, 0.14]
            for g in [0, 0.1, 0.2]
        ]
    return dict(
        profile="cloud_capital_and_leases",
        segments=segments,
        segmentRevenueBasis="외부 고객 매출",
        reconciliations=reconciliations,
        balances=balances,
        balanceChecks=balance_checks,
        leases=lease,
        cash=cash,
        pricing=pricing,
        findings=[
            "사업부 매출과 영업이익 합계를 연결 공시와 대사했다. 인텔리전트 클라우드에는 Azure 외 사업도 포함되므로 해당 부문 전체를 AI 매출로 표시하지 않는다.",
            "현금 설비 취득과 금융리스로 새로 받은 자산을 분리한다. 비현금 취득액을 현금지출에 더해 이중 차감하지 않는다.",
        ],
        remaining=[
            "사업부별 설비투자·리스 배분과 정상 재투자 수준",
            "수주·계약 잔액의 매출·수금 전환과 AI 투자의 회수기간",
            "주식보상·희석·순차입을 반영한 정상 배분 가능 현금",
        ],
    )


def hyundai(c, rows):
    f = c["financials"]

    def dims(member, table, aggregate=True):
        return (
            [CONSOLIDATED]
            + ([SEGMENTS] if aggregate else [])
            + [
                (
                    "SegmentsAxis",
                    member
                    + "MemberOfReportableSegmentsMemberOf"
                    + table
                    + "TableOfMember",
                )
            ]
        )

    def get(tag, start, end, dimensions):
        return select(rows, tag, start, end, dimensions, c["currency"])

    def consolidated(tag, start=None):
        return get(tag, start, f["end"], [CONSOLIDATED])

    segments = []
    fields = {
        "revenue": ("Revenue", "DisclosureOfOperatingSegmentsNetRevenue", False, True),
        "grossRevenue": (
            "Revenue",
            "DetailedInformationOfOperatingSegments",
            True,
            True,
        ),
        "operatingIncome": (
            "OperatingIncomeLoss",
            "DetailedInformationOfOperatingSegments",
            True,
            True,
        ),
        "cfo": (
            "CashFlowsFromUsedInOperatingActivities",
            "CashFlowOfOperatingSegments",
            True,
            True,
        ),
        "netAssetCash": (
            "AcquisitionAndDisposalOfTangibleAndIntangibleAssetsOfCashFlowsFromUsedInInvestingActivitiesOfCashFlowOfOperatingSegmentsTableOfItems",
            "CashFlowOfOperatingSegments",
            True,
            True,
        ),
        "cash": (
            "CashAndCashEquivalents",
            "SummarizedInformationOfOperatingSegments",
            True,
            False,
        ),
        "debtCurrent": (
            "CurrentBorrowingsAndLoansOfCurrentLiabilitiesOfSummarizedInformationOfOperatingSegmentsTableOfItems",
            "SummarizedInformationOfOperatingSegments",
            True,
            True,
        ),
        "debtNoncurrent": (
            "NonCurrentBorrowingsAndLoansOfNonCurrentLiabilitiesOfSummarizedInformationOfOperatingSegmentsTableOfItems",
            "SummarizedInformationOfOperatingSegments",
            True,
            True,
        ),
        "financialReceivablesCurrent": (
            "CurrentReceivablesFinancialBusinessOfCurrentAssetsOfSummarizedInformationOfOperatingSegmentsTableOfItems",
            "SummarizedInformationOfOperatingSegments",
            True,
            True,
        ),
        "financialReceivablesNoncurrent": (
            "NonCurrentRreceivablesFinancialBusinessOfNonCurrentAssetsOfSummarizedInformationOfOperatingSegmentsTableOfItems",
            "SummarizedInformationOfOperatingSegments",
            True,
            True,
        ),
    }
    for member, label in [
        ("Vehicle", "자동차"),
        ("Finance", "금융"),
        ("OthersOperatingSegments", "기타"),
    ]:
        periods = {}
        for period, start, end in [
            ("current", f["start"], f["end"]),
            ("previous", f["priorStart"], f["priorEnd"]),
        ]:
            values = {}
            for key, (tag, table, aggregate, duration) in fields.items():
                m = (
                    "OtherOperatingSegments"
                    if member == "OthersOperatingSegments"
                    and table == "DetailedInformationOfOperatingSegments"
                    else member
                )
                values[key] = get(
                    tag, start if duration else None, end, dims(m, table, aggregate)
                )
            periods[period] = values
        for key in [
            "revenue",
            "operatingIncome",
            "cfo",
            "cash",
            "debtCurrent",
            "debtNoncurrent",
        ]:
            required(periods["current"][key], label + " " + key)
        segments.append(dict(id=member, label=label, **periods))
    op_adjustment = get(
        "ProfitLossFromOperatingActivities",
        f["start"],
        f["end"],
        [CONSOLIDATED, ELIMINATION],
    )
    reconciliations = {
        "revenue": reconcile(
            [s["current"]["revenue"] for s in segments], f["current"]["revenue"]
        ),
        "operatingIncome": reconcile(
            [s["current"]["operatingIncome"] for s in segments],
            f["current"]["operating_income"],
            op_adjustment,
        ),
        "cfo": reconcile([s["current"]["cfo"] for s in segments], f["current"]["cfo"]),
    }
    # A residual without an explicit reconciling disclosure stays unexplained.
    if (
        reconciliations["revenue"]["status"] != "reconciled"
        or reconciliations["operatingIncome"]["status"] != "reconciled"
    ):
        raise ValueError("Hyundai segment revenue/profit do not reconcile")
    balances = {
        "cash": consolidated("CashAndCashEquivalents"),
        "leaseCurrent": consolidated("CurrentLeaseLiabilities"),
        "leaseNoncurrent": consolidated("NoncurrentLeaseLiabilities"),
    }
    return dict(
        profile="automotive_and_finance",
        segments=segments,
        segmentRevenueBasis="부문 간 내부거래 제거 후 외부 매출. 부문 영업이익은 내부거래 조정 전이며 별도 조정액을 대사한다.",
        reconciliations=reconciliations,
        balances=balances,
        pricing=None,
        findings=[
            "자동차·금융·기타 부문의 외부 매출은 연결 매출과 대사했다. 부문 총매출에는 내부거래가 포함되므로 외부 매출과 혼용하지 않는다.",
            "부문 영업현금 합계와 연결 영업현금의 차이는 원인 미연결 잔액으로 남긴다. 금융부문의 현금 유출을 제조업의 현금 악화로 자동 해석하지 않는다.",
            "차입금은 부문별 유동·비유동 공시 잔액이며 현금과 같은 기말을 보여준다. 금융채권의 회수·만기·자금조달 위험을 별도로 검토한다.",
        ],
        remaining=[
            "부문 현금 합계와 연결 현금 사이의 차이에 대한 공시 주석 연결",
            "금융채권의 신용손실·만기와 자금조달 대응",
            "보통주·우선주·비지배지분 및 금융부문 가치를 분리한 주식가치",
            "부문 순유형·무형 취득/처분은 연결 총유형자산 취득과 정의가 다름",
        ],
        pricingHold="우선주·비지배지분·금융부문 가치를 분리하기 전까지 연결 현금을 보통주 한 종류의 가격에 대입하지 않는다.",
        balancePeriodNote="부문 차입금·금융채권은 기말 잔액을 담은 공시 표이다. 원 XBRL은 누적 기간 컨텍스트를 사용하므로 시작일도 근거에 보존한다.",
    )


def build(company, as_of):
    if company["id"] not in ("MSFT", "005380", *PROFILES):
        return None
    core = company["financials"]["current"]["cfo"]
    source, rows = company_filing(company, as_of)
    if source is None:
        return dict(
            status="awaiting_filing", reason="현재 공시의 사업부 XBRL 원문 미확보"
        )
    result = (
        build_profile(company, rows, reconcile)
        if company["id"] in PROFILES
        else (microsoft if company["id"] == "MSFT" else hyundai)(company, rows)
    )
    result.update(
        status="ready",
        version="business-notes-v1",
        start=core["start"],
        end=core["end"],
        filedAt=core["filedAt"],
        accession=core["accession"],
        source=source,
        independentInterpretationApproved=False,
    )
    result["evidenceHash"] = digest(canonical(result))
    if source["file"] not in {s["file"] for s in company["sources"]}:
        company["sources"].append(source)
    return result
