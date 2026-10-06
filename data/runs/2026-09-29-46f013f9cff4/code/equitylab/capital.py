"""Reported capital and distributions with exact periods and explicit gaps."""

from .data import canonical, digest
from .xbrl import company_filing, select

US_BALANCE = {
    "cash": ("현금·현금성자산", ["CashAndCashEquivalentsAtCarryingValue"]),
    "currentAssets": ("유동자산", ["AssetsCurrent"]),
    "currentLiabilities": ("유동부채", ["LiabilitiesCurrent"]),
    "debtCurrent": ("유동 차입금·채무", ["DebtCurrent"]),
    "longDebtCurrent": ("장기차입금 유동분", ["LongTermDebtCurrent"]),
    "longDebtNoncurrent": ("장기차입금 비유동분", ["LongTermDebtNoncurrent"]),
    "operatingLease": ("영업리스 부채", ["OperatingLeaseLiability"]),
    "financeLease": ("금융리스 부채", ["FinanceLeaseLiability"]),
    "commonShares": ("공시 보통주 유통주식수", ["CommonStockSharesOutstanding"]),
}
US_FLOW = {
    "sbc": ("주식보상 비현금 조정", ["ShareBasedCompensation"]),
    "repurchases": ("보통주 매입 현금", ["PaymentsForRepurchaseOfCommonStock"]),
    "dividends": (
        "배당 현금",
        [
            "PaymentsOfDividends",
            "PaymentsOfDividendsCommonStock",
            "PaymentsOfOrdinaryDividends",
        ],
    ),
    "leasePrincipal": ("금융리스 원금 상환", ["FinanceLeasePrincipalPayments"]),
    "depreciation": (
        "감가상각·상각 조정",
        ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"],
    ),
    "dilutedShares": (
        "기간 가중평균 희석주식수",
        ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    ),
    "basicShares": (
        "기간 가중평균 기본주식수",
        ["WeightedAverageNumberOfSharesOutstandingBasic"],
    ),
}
KR_BALANCE = {
    "cash": ("현금·현금성자산", ["CashAndCashEquivalents"]),
    "currentAssets": ("유동자산", ["CurrentAssets"]),
    "currentLiabilities": ("유동부채", ["CurrentLiabilities"]),
    "debtCurrent": (
        "유동 차입금과 장기차입금 유동분",
        ["CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"],
    ),
    "shortBorrowings": ("단기차입금", ["ShorttermBorrowings"]),
    "longDebtNoncurrent": ("장기차입금", ["LongtermBorrowings"]),
    "leaseCurrent": ("리스부채 유동분", ["CurrentLeaseLiabilities"]),
    "leaseNoncurrent": ("리스부채 비유동분", ["NoncurrentLeaseLiabilities"]),
}
KR_FLOW = {
    "repurchases": (
        "자기주식 취득",
        ["AcquisitionOfTreasuryShares", "PurchaseOfTreasuryShares"],
    ),
    "dividends": (
        "재무활동 분류 배당 현금",
        ["DividendsPaidClassifiedAsFinancingActivities"],
    ),
    "leasePrincipal": (
        "재무활동 분류 리스 지급",
        [
            "PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities",
            "PaymentsOfFinanceLeaseLiabilitiesClassifiedAsFinancingActivities",
        ],
    ),
    "depreciation": ("유형자산 감가상각", ["DepreciationPropertyPlantAndEquipment"]),
    "sbc": (
        "주식보상 비현금 조정",
        ["AdjustmentsForShareBasedPayments", "AdjustmentsForShareBasedPayment"],
    ),
}


def build(company, as_of):
    source, rows = company_filing(company, as_of)
    if not source:
        return dict(
            status="awaiting_filing", reason="현재 공시의 자본·배분 원문 미확보"
        )
    f = company["financials"]
    kr = company["market"] == "KR"
    dims = (
        [("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")]
        if kr
        else []
    )
    balance_spec, flow_spec = (KR_BALANCE, KR_FLOW) if kr else (US_BALANCE, US_FLOW)
    gaps = []

    def fact(key, tags, start, end):
        unit = "shares" if key.endswith("Shares") else company["currency"]
        for tag in tags:
            try:
                item = select(rows, tag, start, end, dims, unit)
            except ValueError:
                gaps.append(
                    dict(
                        metric=key,
                        period=[start, end],
                        reason="같은 문맥의 상충 수치: " + tag,
                    )
                )
                return None
            if item is not None:
                return item
        gaps.append(
            dict(
                metric=key,
                period=[start, end],
                reason="해당 기간·연결 범위의 확인된 태그 없음",
            )
        )
        return None

    balances = {
        k: dict(label=label, current=fact(k, tags, None, f["end"]))
        for k, (label, tags) in balance_spec.items()
    }
    flows = {
        k: dict(
            label=label,
            current=fact(k, tags, f["start"], f["end"]),
            previous=fact(k, tags, f["priorStart"], f["priorEnd"]),
        )
        for k, (label, tags) in flow_spec.items()
    }
    base_cash = company["metrics"]["cashAfterInvestment"]
    principal = flows["leasePrincipal"]["current"]
    sbc = flows["sbc"]["current"]
    adjusted = base_cash - principal["value"] if principal else None
    # Missing amounts are not assumed to be zero. These are transparent deductions,
    # not a forecast or a valuation of outstanding share-based awards.
    cash = dict(
        reportedResidual=base_cash,
        afterReportedLeasePayments=adjusted,
        afterSbcExpenseProxy=(
            adjusted - sbc["value"] if adjusted is not None and sbc else None
        ),
        sbcIsCash=False,
        definition="영업현금−공시 투자자산 취득, 확인된 재무활동 리스 지급과 주식보상 비용 대용 차감은 별도 제시",
        limitation="주식보상 차감은 주주 부담의 비용 대용 가정이며 현금 유출이 아니다. 자기주식 매입과 함께 이중 차감하지 않는다. 리스·주식보상 결측은 영으로 넣지 않으며 정상화 FCFE를 뜻하지 않는다.",
    )
    result = dict(
        status="ready",
        version="reported-capital-v1",
        start=f["start"],
        end=f["end"],
        filedAt=f["current"]["cfo"]["filedAt"],
        source=source,
        balances=balances,
        flows=flows,
        cash=cash,
        gaps=gaps,
        limits=[
            "기말 잔액과 누적기간 현금흐름을 구별한다. 가중평균 희석주식수는 기말 주식수와 다르다.",
            "유동 총채무와 장기차입금 유동분·단기차입금은 겹칠 수 있어 합산하지 않는다. 장기차입금은 전체 차입금과 같지 않다.",
            "배당·주식 매입은 이미 지급한 현금이며 앞으로의 지속 가능한 배분액을 보장하지 않는다.",
            "연결 재무와 증권 종류·비지배지분을 확인하기 전에는 표의 현금을 보통주 가치로 치환하지 않는다.",
        ],
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
