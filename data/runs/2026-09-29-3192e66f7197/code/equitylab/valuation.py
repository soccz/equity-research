"""Historical cash assumptions and security-aware equity scenario workspaces."""

from datetime import date
import math
import statistics
from .data import canonical, digest
from .dossier import price_requirements
from .xbrl import company_filing, select


def share_scope(c, rows, share_table=None):
    end, price_date = c["financials"]["end"], c["priceSummary"]["lastDate"]
    available = [
        r
        for r in rows
        if r["unit"] == "shares"
        and r["start"] is None
        and end <= r["end"] <= price_date
    ]
    issues, classes, additional_share_evidence = [], [], []
    rights_review = None
    if c["market"] == "US":
        share_tags = (
            "EntityCommonStockSharesOutstanding",
            "CommonStockSharesOutstanding",
        )
        members = sorted(
            {
                member
                for r in available
                if r["tag"] in share_tags
                for axis, member in r["dimensions"]
                if axis == "StatementClassOfStockAxis"
            }
        )
        classes = members
        if len(members) > 1:
            issues.append("여러 보통주 종류의 가격·경제적 권리와 유통주식수 연결 필요")
        preferred = [
            r
            for r in available
            if r["tag"] == "PreferredStockSharesOutstanding"
            and all(axis == "StatementClassOfStockAxis" for axis, _ in r["dimensions"])
            and r["value"] > 0
        ]
        if preferred:
            issues.append("발행된 우선주의 현금·청산 권리 배분 필요")
        candidates = [
            r for r in available if r["tag"] in share_tags and not r["dimensions"]
        ]
        chosen = None
        # Header outstanding shares are often newer and more precise than the
        # rounded balance-sheet count. Preserve their own observation date.
        for day in sorted({r["end"] for r in candidates}, reverse=True):
            for tag in share_tags:
                chosen = select(candidates, tag, None, day, (), "shares")
                if chosen:
                    break
            if chosen:
                break
    else:
        common = [
            ("ClassesOfShareCapitalAxis", "OrdinarySharesMember"),
            ("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember"),
        ]
        pref = [
            ("ClassesOfShareCapitalAxis", "PreferenceSharesMember"),
            ("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember"),
        ]
        preferred = [
            r
            for r in available
            if r["tag"] in ("NumberOfSharesOutstanding", "NumberOfSharesIssued")
            and r["dimensions"] == pref
            and r["value"] > 0
        ]
        if preferred:
            issues.append("보통주와 우선주의 현금·청산 권리 배분 필요")
        chosen = select(
            available, "NumberOfSharesOutstanding", None, end, common, "shares"
        )
        classes = ["OrdinarySharesMember"] + (
            ["PreferenceSharesMember"] if preferred else []
        )
        if share_table:
            issues.extend(share_table["issues"])
            api_shares = share_table["shares"]
            additional_share_evidence = [
                r
                for r in available
                if r["end"] == end
                and r["tag"] == "NumberOfSharesOutstanding"
                and ("ClassesOfShareCapitalAxis", "PreferenceSharesMember")
                not in r["dimensions"]
                and (
                    r["dimensions"]
                    == [
                        ("ClassesOfShareCapitalAxis", "OrdinarySharesMember"),
                        (
                            "ConsolidatedAndSeparateFinancialStatementsAxis",
                            "SeparateMember",
                        ),
                    ]
                    or r["dimensions"]
                    == [
                        (
                            "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis",
                            "ReportedAmountMember",
                        ),
                        (
                            "ConsolidatedAndSeparateFinancialStatementsAxis",
                            "ConsolidatedMember",
                        ),
                    ]
                )
            ]
            if api_shares and any(
                r["value"] != api_shares["value"] for r in additional_share_evidence
            ):
                issues.append(
                    "다른 주식수 주석의 같은 기준일 유통주식수와 총수 표가 다름. 범위 차이 확인 필요"
                )
            if api_shares and chosen and api_shares["value"] != chosen["value"]:
                issues.append("같은 접수·기준일의 XBRL과 주식 총수 표 유통주식수 충돌")
                chosen = None
            elif api_shares:
                chosen = api_shares
    if c["id"] == "META":
        from .security_rights import meta_entitlement

        rights_review = meta_entitlement(c, available, classes, preferred)
        if rights_review:
            chosen = rights_review["shares"]
            issues = [
                i
                for i in issues
                if i != "여러 보통주 종류의 가격·경제적 권리와 유통주식수 연결 필요"
            ]
    capital_review = None
    subsequent_review = None
    warrant_review = None
    if c["id"] == "AMD":
        from .amd_capital import build as amd_capital

        warrant_review = amd_capital(c)
        issues.append(warrant_review["issue"])
    if c["id"] == "000660":
        from .hynix_capital import build as hynix_capital

        subsequent_review = hynix_capital(c, chosen)
        if subsequent_review:
            issues.append(subsequent_review["issue"])
    if c["id"] == "GOOGL":
        from .alphabet_capital import build as capital_terms

        capital_review = capital_terms(c)
    if chosen is None or chosen["value"] <= 0:
        issues.append(
            "정확한 범위의 유통주식수 미확인. 발행주식수·가중평균주식수로 대체하지 않음"
        )
        chosen = None
    if c["id"] in ("GM", "F", "CAT", "005380"):
        issues.append("제조·금융 자회사 현금과 자본요구를 먼저 분리해야 함")
    if c["id"] == "030200":
        issues.append(
            "통신과 신용카드·대출 자회사의 현금·금융채권·자본요구를 먼저 분리해야 함"
        )
    return dict(
        status="available" if chosen and not issues else "unresolved",
        shares=chosen,
        classes=classes,
        preferredEvidence=preferred,
        **({"rightsReview": rights_review["evidence"]} if rights_review else {}),
        **({"capitalReview": capital_review} if capital_review else {}),
        **({"subsequentReview": subsequent_review} if subsequent_review else {}),
        **({"warrantReview": warrant_review} if warrant_review else {}),
        shareTable=share_table,
        additionalShareEvidence=additional_share_evidence,
        issues=issues,
        priceDate=price_date,
        shareAgeDays=(
            (date.fromisoformat(price_date) - date.fromisoformat(chosen["end"])).days
            if chosen
            else None
        ),
        marketCapProxy=(
            chosen["value"] * c["priceSummary"]["close"]
            if chosen and not issues
            else None
        ),
        scope="공시에 기재된 유통주식수의 자체 기준일과 관측 종가의 시점 차이를 보존한다. 이후 발행·소각을 반영한 실시간 시가총액은 아니다."
        + (" " + rights_review["assumption"] if rights_review else ""),
    )


def scenario(
    revenue,
    cfo_margin,
    investment_margin,
    burden_margin,
    growth,
    discount,
    shares=None,
    terminal=0.02,
    horizon=5,
):
    if not all(
        type(x) in (int, float) and math.isfinite(x)
        for x in (
            revenue,
            cfo_margin,
            investment_margin,
            burden_margin,
            growth,
            discount,
        )
    ):
        raise ValueError("Non-finite equity scenario")
    if shares is not None and (
        type(shares) not in (int, float) or not math.isfinite(shares) or shares <= 0
    ):
        raise ValueError("Invalid outstanding shares")
    if revenue <= 0 or not terminal < discount <= 0.5 or not -0.5 < growth < 1:
        raise ValueError("Invalid equity scenario assumptions")
    if min(investment_margin, burden_margin) < 0:
        raise ValueError("Investment and additional burdens cannot be negative")
    cash = revenue * (cfo_margin - investment_margin - burden_margin)
    multiple = (
        1
        / price_requirements(1, growth, discount, terminal, horizon)["requiredBaseCash"]
    )
    value = cash * multiple if cash > 0 else None
    return dict(
        cash=cash,
        equityValue=value,
        price=value / shares if value is not None and shares else None,
        positiveCash=cash > 0,
    )


def implied_growth(market_cap, cash, discount, terminal=0.02, horizon=5):
    """Solve a conditional constant growth rate, without forecasting that rate."""
    if cash <= 0:
        return dict(status="nonpositive_cash", growth=None)
    low, high = -0.49, 0.99
    required = lambda g: price_requirements(market_cap, g, discount, terminal, horizon)[
        "requiredBaseCash"
    ]
    if required(high) > cash:
        return dict(status="above_range", growth=None)
    if required(low) < cash:
        return dict(status="below_range", growth=None)
    for _ in range(70):
        mid = (low + high) / 2
        if required(mid) > cash:
            low = mid
        else:
            high = mid
    return dict(status="solved", growth=(low + high) / 2)


def build(c, as_of):
    t = c.get("trailingYear")
    if not t or t.get("status") != "ready":
        return dict(
            status="unresolved",
            reason="같은 최근 일 년의 매출·영업현금·투자 근거가 필요",
        )
    source, rows = company_filing(c, as_of)
    if not source:
        return dict(status="unresolved", reason="증권 범위와 자본 조정의 원문 필요")
    from .security import load as load_share_table

    security = share_scope(c, rows, load_share_table(c, as_of, rows))
    if c.get("cashScope", {}).get("status") == "review_required":
        security["issues"].append(c["cashScope"]["reason"])
        security["status"] = "unresolved"
        security["marketCapProxy"] = None
    history = [
        dict(
            start=t["start"],
            end=t["end"],
            cfoMargin=t["metrics"]["cfoMargin"],
            investmentMargin=t["metrics"]["investmentMargin"],
            basis="최근 일 년 연결",
            evidenceHash=t["evidenceHash"],
        )
    ]
    # Do not count overlapping rolling-year observations as independent years.
    next_start = t["start"]
    for r in reversed(c["analysis"]["annual"]):
        if r["end"] < next_start and r["investmentScope"] == t["investmentScope"]:
            history.append(
                dict(
                    start=r["start"],
                    end=r["end"],
                    cfoMargin=r["cfoMargin"],
                    investmentMargin=r["cfoMargin"] - r["cashMargin"],
                    basis="이전 비중복 연간 공시",
                    evidence=r["evidence"],
                )
            )
            next_start = r["start"]
        if len(history) == 4:
            break
    revenue = t["values"]["revenue"]["value"]
    current_revenue = c["financials"]["current"]["revenue"]["value"]
    adjustments, unknown = [], []
    for key, label in [
        ("leasePrincipal", "재무활동 리스 지급"),
        ("sbc", "주식보상의 현금보상 대체"),
    ]:
        field = c.get("capital", {}).get("flows", {}).get(key, {})
        f = field.get("current")
        if f and f["value"] >= 0:
            adjustments.append(
                dict(
                    id=key,
                    label=label,
                    ratio=f["value"] / current_revenue,
                    evidence=f,
                    assumption="같은 누적기간 매출 대비 비율이 다음 일 년에도 유지된다는 가정",
                )
            )
        else:
            unknown.append(label)
    burden = sum(a["ratio"] for a in adjustments)
    cm, im = [r["cfoMargin"] for r in history], [r["investmentMargin"] for r in history]
    defaults = dict(
        growth=0.05,
        discount=0.12,
        terminal=0.02,
        horizon=5,
        burdenMargin=burden,
        cfoMargin=statistics.median(cm),
        investmentMargin=statistics.median(im),
    )
    cases = []
    for id, label, cash_m, investment_m in [
        ("pressure", "과거 범위의 현금 부담 조합", min(cm), max(im)),
        (
            "reference",
            "과거 범위의 중앙값 조합",
            statistics.median(cm),
            statistics.median(im),
        ),
        ("recovery", "과거 범위의 현금 여유 조합", max(cm), min(im)),
    ]:
        cases.append(
            dict(
                id=id,
                label=label,
                cfoMargin=cash_m,
                investmentMargin=investment_m,
                **scenario(
                    revenue,
                    cash_m,
                    investment_m,
                    burden,
                    defaults["growth"],
                    defaults["discount"],
                    (
                        security["shares"]["value"]
                        if security["status"] == "available"
                        else None
                    ),
                ),
            )
        )
    required = (
        price_requirements(
            security["marketCapProxy"], defaults["growth"], defaults["discount"]
        )
        if security["marketCapProxy"]
        else None
    )
    result = dict(
        status="workspace",
        version="cash-equity-scenarios-v2",
        security=security,
        revenueBase=revenue,
        revenuePeriod=[t["start"], t["end"]],
        history=history,
        adjustments=adjustments,
        unknownAdjustments=unknown,
        defaults=defaults,
        cases=cases,
        priceRequirement=required,
        impliedGrowth=(
            implied_growth(
                security["marketCapProxy"], cases[1]["cash"], defaults["discount"]
            )
            if security["marketCapProxy"]
            else None
        ),
        historicalCfoRange=[min(cm), max(cm)],
        historicalInvestmentRange=[min(im), max(im)],
        requiredCfoMargin=(
            required["requiredBaseCash"] / revenue
            + defaults["investmentMargin"]
            + burden
            if required
            else None
        ),
        assumptions=[
            "최근 일 년 매출을 기준 규모로 두고 서로 겹치지 않는 최대 네 연간 관측의 현금·투자 비율 범위를 사용한다. 가격·물량·사업부 전망을 추정한 결과는 아니다.",
            "현금 성장률 연5%, 요구수익률12%, 영구성장률2%, 명시기간5년은 공통 비교 가정이다. 기업별 추정치·시장 컨센서스가 아니며 화면에서 조정한다.",
            "주식보상은 현금보상으로 대체한다는 비용 가정으로 차감한다. 자기주식 매입액은 다시 빼지 않는다. 순차입·추가 희석·인수 지출·비지배 배분의 추가 조정은 영으로 둔 조건부 계산이다.",
            "미확인 리스·주식보상 항목을 실제 영으로 확정하지 않는다. 해당 추가 부담을 영으로 둔 가정의 결과이며 부담을 반영하면 가격 한도는 낮아진다.",
            "현금·부채 잔액을 자동 가감하지 않는다. 영업현금에 포함된 이자·세금의 처리와 증권별 배분을 추가 검토해야 한다.",
        ],
        scope="과거 공시에서 출발한 조건부 주주 현금 시나리오. 정상 FCFE 검증·목표가·매수 의견·성공 확률이 아니다.",
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
