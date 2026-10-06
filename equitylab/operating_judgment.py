"""Price conditions from the actual issuer model, without an automatic rating."""

from .operating_model import calculate


def build(c):
    model = c.get("operatingModel") or {}
    if model.get("status") != "research_workspace":
        return None
    r = calculate(model, model["defaults"])
    scope = c.get("cashScope") or {}
    security = model["security"]
    required = r["requiredTerminalCash"]
    if scope.get("status") == "review_required":
        state, statement = "사업 범위 대사", scope["reason"]
        required = None
    elif model.get("priceHoldReason"):
        state, statement = "현금 항목 범위 대사", model["priceHoldReason"]
        required = None
    elif security["status"] != "available":
        state = "증권 범위 보완"
        statement = "사업별 현금 경로는 계산했지만 증권 종류별 배분이 미확정입니다. 우선주·전환·비지배 권리와 현재 주식수를 대사한 뒤 가격 요건을 계산합니다."
        required = None
    elif (r.get("investmentBridge") or {}).get("status") == "investment_unassessed":
        state = "투자자산 가치 보완"
        statement = "관계·공동기업 투자 장부금액은 확인했지만 지배주주 귀속 가치는 아직 평가하지 않았습니다. 사업 현금만의 가치를 회사 전체 주가와 비교해 성장 부족이나 고평가로 판단하지 않습니다. 투자 가치 가정을 별도로 입력한 뒤 잔여 가격이 요구하는 사업 조건을 확인합니다."
        required = None
    elif r["terminal"]["cash"] <= 0 or r["equityValue"] is None:
        state = "현금 전환 가정 필요"
        statement = "현재 사업 마진·투입 구조를 유지한 경로의 말기 현금 또는 현재가치가 양수가 아닙니다. 성장만 늘리기 전에 사업별 마진·재투자·리스 부담이 바뀔 근거를 검토합니다."
    elif r["equityValue"] < security["marketCapProxy"]:
        state = "사업 가정 보완"
        statement = "현재 사업 마진·투입 구조를 유지한 현금 경로가 관측 가격에 미달합니다. 어느 사업의 성장·마진 또는 자금·투자 부담이 얼마나 달라져야 하는지 비교하고 그 근거를 확인합니다."
    else:
        state = "가정 충족 여부 검토"
        statement = "현재 선택한 사업 현금 가정의 현재가치가 관측 가격에 도달합니다. 정상 재투자·권리 배분의 미확인 항목과 경쟁 기업의 대안을 검토해야 하며 이 계산만으로 투자 선호를 확정하지 않습니다."
    terminal_revenue = r["terminal"]["revenue"]
    return dict(
        basis="issuer_operating_cash_path",
        state=state,
        statement=statement,
        referencePrice=r["price"] if required is not None else None,
        price=c["priceSummary"]["close"],
        requiredTerminalCash=required,
        referenceTerminalCash=r["terminal"]["cash"],
        terminalRevenue=terminal_revenue,
        requiredCashMargin=(
            required / terminal_revenue if required is not None else None
        ),
        referenceCashMargin=r["terminal"]["cash"] / terminal_revenue,
        firstFiveYearsPv=r["explicitPv"],
        assumptions=model["defaults"],
        sourcePeriod=model["sourcePeriod"],
        modelVersion=model["version"],
        evidenceHash=model["evidenceHash"],
        priceDate=security["priceDate"],
        shareDate=(security.get("shares") or {}).get("end"),
        unknownAdjustments=model["remaining"],
        limitation="첫 5년의 선택 현금과 명시한 별도 투자 가치 가정을 차감한 잔여 가격을 설명하는 6년차 현금입니다. 현재 연간 현금이나 시장 컨센서스가 아닙니다. 과거 수치는 유지 가정의 출발점이며 정상 현금 전망은 미승인입니다.",
        financialApproval=False,
    )
