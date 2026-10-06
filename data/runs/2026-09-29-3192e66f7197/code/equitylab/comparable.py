"""Trailing-year statement reconstruction with an explicit three-period bridge."""

from datetime import date, timedelta
from .data import canonical, digest, select_fact
from .company_analysis import investment_scope

METRICS = ("revenue", "operating_income", "net_income", "cfo", "capex")


def trailing_year(company, facts, as_of):
    s = company["financials"]
    current_start = date.fromisoformat(s["start"])
    current_end = date.fromisoformat(s["end"])
    direct = 350 <= s["days"] <= 380
    bridge = []
    if direct:
        start, end = s["start"], s["end"]
        bridge = [(1, start, end, "보고된 연간·12개월")]
    else:
        annual_end = (current_start - timedelta(days=1)).isoformat()
        annual_start = s.get("priorStart")
        prior_end = s.get("priorEnd")
        if not annual_start or not prior_end:
            return dict(
                status="unresolved", reason="직전 회계연도와 전년 누적기간 연결 불가"
            )
        annual_days = (
            date.fromisoformat(annual_end) - date.fromisoformat(annual_start)
        ).days + 1
        start = (date.fromisoformat(prior_end) + timedelta(days=1)).isoformat()
        end = s["end"]
        if (
            not 350 <= annual_days <= 380
            or not 350 <= (current_end - date.fromisoformat(start)).days + 1 <= 380
        ):
            return dict(
                status="unresolved",
                reason="연간·당기누적·전년누적의 기간 연결이 일 년을 구성하지 않음",
            )
        bridge = [
            (1, annual_start, annual_end, "직전 회계연도"),
            (1, s["start"], s["end"], "당기 누적"),
            (-1, annual_start, prior_end, "전년 누적"),
        ]
    values, gaps = {}, []
    for metric in METRICS:
        parts = []
        for coefficient, begin, finish, label in bridge:
            fact = select_fact(facts, metric, begin, finish, as_of)
            if (
                fact is None
                or fact["unit"] != company["currency"]
                or fact["filedAt"] > as_of
            ):
                parts = []
                gaps.append(
                    dict(
                        metric=metric,
                        reason="필수 기간·통화의 이용 가능한 공시 미확인",
                        start=begin,
                        end=finish,
                    )
                )
                break
            parts.append(dict(coefficient=coefficient, label=label, fact=fact))
        if (
            parts
            and metric == "capex"
            and len({investment_scope(p["fact"]) for p in parts}) != 1
        ):
            gaps.append(dict(metric=metric, reason="기간 사이 투자지출 정의 변경"))
            parts = []
        values[metric] = (
            dict(
                value=sum(p["coefficient"] * p["fact"]["value"] for p in parts),
                components=parts,
            )
            if parts
            else None
        )
    revenue = values["revenue"]["value"] if values["revenue"] else None
    cfo = values["cfo"]["value"] if values["cfo"] else None
    capex = values["capex"]["value"] if values["capex"] else None
    op = values["operating_income"]["value"] if values["operating_income"] else None
    residual = cfo - capex if cfo is not None and capex is not None else None
    metrics = dict(
        operatingMargin=(
            op / revenue if revenue and revenue > 0 and op is not None else None
        ),
        cfoMargin=(
            cfo / revenue if revenue and revenue > 0 and cfo is not None else None
        ),
        investmentMargin=(
            capex / revenue if revenue and revenue > 0 and capex is not None else None
        ),
        cashMargin=(
            residual / revenue
            if revenue and revenue > 0 and residual is not None
            else None
        ),
        cashResidual=residual,
    )
    result = dict(
        status=(
            "ready"
            if all(values[k] for k in ("revenue", "cfo", "capex"))
            else "partial"
        ),
        version="trailing-year-bridge-v1",
        method="reported" if direct else "annual_plus_current_less_prior",
        start=start,
        end=end,
        days=(current_end - date.fromisoformat(start)).days + 1,
        currency=company["currency"],
        values=values,
        metrics=metrics,
        gaps=gaps,
        filedAt=max(
            (
                p["fact"]["filedAt"]
                for v in values.values()
                if v
                for p in v["components"]
            ),
            default=None,
        ),
        investmentScope=(
            investment_scope(values["capex"]["components"][0]["fact"])
            if values["capex"]
            else None
        ),
        scope="연간 공시＋당기 누적−전년 누적으로 동일 기업의 최근 일 년을 연결한다. 단순 연환산·미래 전망·당시 투자 신호가 아니다. 과거 금액은 현재 기준일까지의 수정 공시를 반영할 수 있다.",
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
