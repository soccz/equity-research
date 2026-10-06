"""Compare issuer-specific cash assumptions with each issuer's observed price."""

from .data import canonical, digest
from .operating_model import calculate

VERSION = "paired-operating-workspace-v1"


def summarize(model, assumptions):
    r = calculate(model, assumptions)
    revenue = r["terminal"]["revenue"]
    market = model["security"]["marketCapProxy"]
    selected = (
        r["investmentBridge"]["selectedSubtotal"]
        if "investmentBridge" in r
        else r["equityValue"]
    )
    return dict(
        cashPath=r,
        terminalCashMargin=r["terminal"]["cash"] / revenue if revenue > 0 else None,
        requiredCashMargin=(
            r["requiredTerminalCash"] / revenue
            if revenue > 0 and r["requiredTerminalCash"] is not None
            else None
        ),
        marginGap=(
            r["terminalCashGap"] / revenue
            if revenue > 0 and r["terminalCashGap"] is not None
            else None
        ),
        explicitCoverage=r["explicitPv"] / market if market else None,
        valueToMarket=(selected / market if selected is not None and market else None),
    )


def build(study, companies):
    missing = [
        s["company"]
        for s in study["sides"]
        if (companies.get(s["company"], {}).get("operatingModel") or {}).get("status")
        != "research_workspace"
    ]
    if missing or study["status"] != "source_draft":
        return dict(
            status="source_review_required",
            missingModels=missing,
            reason="양쪽 현재 공시의 개별 사업 현금 모델이 필요합니다. 공통 과거비율로 대체하지 않습니다.",
        )
    models = []
    for side in study["sides"]:
        c = companies[side["company"]]
        m = c["operatingModel"]
        models.append(
            dict(
                company=c["id"],
                name=c["name"],
                currency=c["currency"],
                modelHash=m["evidenceHash"],
                modelVersion=m["version"],
                sourcePeriod=m["sourcePeriod"],
                corpusHash=c["narrative"]["evidenceHash"],
                price=c["priceSummary"],
                security=m["security"],
                defaults=m["defaults"],
                initial=summarize(m, m["defaults"]),
            )
        )
    result = dict(
        status="research_workspace",
        version=VERSION,
        study=study["id"],
        studyHash=study["evidenceHash"],
        sides=models,
        sameSourcePeriod=models[0]["sourcePeriod"] == models[1]["sourcePeriod"],
        samePriceDate=models[0]["price"]["lastDate"] == models[1]["price"]["lastDate"],
        scope="각 회사의 현재 가격에 필요한 말기 현금을 그 회사의 가정 매출로 나눕니다. 환율 환산·수익률 예측·자동 투자 순위가 아닙니다. 사업·회계·증권 범위와 재투자 가정 차이는 별도로 남깁니다.",
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
