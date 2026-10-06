"""Conditional research views, with price and causal claims kept evidence-bound."""

from .data import canonical, digest


def build(c):
    m = c["metrics"]
    g = m["revenueGrowth"]
    change = m["cashMarginChange"]
    if c["assessment"]["issues"]:
        state = "자료 확인"
        question = "기간·투자 범위를 보완한 뒤 현금 변화 재검토"
    elif m["cashAfterInvestment"] <= 0:
        state = "관찰"
        question = "재투자 이후 현금이 회복되는 조건"
    elif g is not None and g > 0 and change is not None and change > 0:
        state = "관찰"
        question = "성장과 현금 마진 개선의 지속성"
    else:
        state = "관찰"
        question = "이익·현금·재투자의 엇갈림"
    b = c.get("business")
    d = c.get("dossier")
    price = (b or {}).get("pricing") or (d or {}).get("pricing")
    remaining = list(c["analysis"]["questions"])
    if b and b.get("status") == "ready":
        remaining = list(b["remaining"])
    elif d:
        remaining = list(d.get("receivables", {}).get("limitations", [])) or remaining
    result = dict(
        version="conditional-research-view-v1",
        state=state,
        question=question,
        derivation="공시 계산에 따른 조사 의견. 아래 세 관측의 결합은 원인·저평가·초과수익의 증거가 아니다.",
        horizon="다음 정기공시에서 재검토 · 수익률 예측 기간 미설정",
        observations=[
            dict(
                label="매출 전년 동기 변화",
                value=g,
                unit="ratio",
                source=c["financials"]["current"]["revenue"]["sourceUrl"],
            ),
            dict(
                label="투자 이후 현금 / 매출",
                value=m["cashMargin"],
                unit="ratio",
                source=c["financials"]["current"]["cfo"]["sourceUrl"],
            ),
            dict(
                label="동 현금 마진 전년 동기 차이",
                value=change,
                unit="pp",
                source=c["financials"]["current"]["capex"]["sourceUrl"],
            ),
        ],
        confirmation=dict(
            metric="cashMarginChange",
            operator=">",
            threshold=0,
            definition=f"다음 정기공시의 동일 길이 전년 동기 대비 (영업현금−{c['investmentScope']})/매출 개선",
            baseline="같은 길이 전년 동기 마진 유지",
            expected=None,
        ),
        countercondition="같은 정의의 현금 마진이 개선되지 않으면 현금 확장 지속성 가설을 약화하는 관측으로 남긴다. 투자 확대·수금 시점 등 원인은 별도로 조사한다.",
        priceStatus="assumption_workspace" if price else "unresolved",
        priceRequirement=(
            dict(
                requiredAnnualCash=price["base"]["requiredBaseCash"],
                referenceAnnualCash=price.get("referenceCash", m["cashAfterInvestment"])
                * 365
                / c["financials"]["days"],
                referenceDefinition=price.get(
                    "referenceDefinition", f"영업현금−{c['investmentScope']}"
                ),
                assumptions=price["defaults"],
                priceDate=price["priceDate"],
                shareDate=price["shareDate"],
                limitation="참고 현금은 보고 기간을 단순 연환산한 잔액이며 정상 배분 현금이 아니다. 두 금액의 차이를 저평가·고평가나 목표가로 해석하지 않는다.",
            )
            if price
            else None
        ),
        priceQuestion=(
            "가정한 성장·요구수익률에서 필요한 보통주 배분 가능 현금을 정상 재투자·순차입·희석과 대조해야 한다."
            if price
            else "보통주·우선주·비지배 지분과 정상 배분 가능 현금을 연결하기 전에는 가격의 유불리를 판정하지 않는다."
        ),
        remaining=remaining,
        financialApproval=False,
        sources=[c["financials"]["current"][k] for k in ["revenue", "cfo", "capex"]],
    )
    valuation = c.get("valuation")
    if valuation and valuation.get("status") == "workspace":
        requirement = valuation["priceRequirement"]
        result["version"] = "conditional-research-view-v2"
        result["priceStatus"] = "assumption_workspace" if requirement else "unresolved"
        result["priceRequirement"] = (
            dict(
                requiredAnnualCash=requirement["requiredBaseCash"],
                referenceAnnualCash=valuation["cases"][1]["cash"],
                referenceDefinition="최근 일 년 매출 × (과거 영업현금 비율 중앙값 − 투자 비율 중앙값 − 추가 부담 가정)",
                referenceBasis="과거 비율 중앙값을 적용한 조건부 현금",
                assumptions=valuation["defaults"],
                priceDate=valuation["security"]["priceDate"],
                shareDate=valuation["security"]["shares"]["end"],
                limitation="정상 현금 검증은 아니다. 미확인 추가 부담·순차입·희석·비지배 배분 가정을 아래 가격 작업표에서 확인한다.",
            )
            if requirement
            else None
        )
        result["priceQuestion"] = (
            "과거 비중복 연간 공시와 리스·주식보상 비용 가정에 비추어 현재 가격에 필요한 현금을 검토한다."
            if requirement
            else " · ".join(valuation["security"]["issues"])
        )
    result["evidenceHash"] = digest(canonical(result))
    return result
