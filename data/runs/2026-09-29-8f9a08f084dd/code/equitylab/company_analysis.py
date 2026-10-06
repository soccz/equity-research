"""General company observations and explicit accounting decompositions."""

from datetime import date
from .data import canonical, digest, select_fact

PROFILES = {
    "enterprise-software": (
        "계약·구독과 고객별 현금 회수",
        [
            "구독·사용량·구축 매출을 나누고 계약잔액의 해지·인식 조건을 확인했는가",
            "고객 수·계약 규모·갱신·가격 중 성장의 근거를 구별할 수 있는가",
            "주식보상·판매수수료 자산화·인수와 인프라 투자가 현금에 만드는 부담은 무엇인가",
        ],
    ),
    "content": (
        "콘텐츠 수익과 제작·개발비 회수",
        [
            "기존 작품과 신작·지역·가입자 또는 이용자 지출을 구별할 수 있는가",
            "콘텐츠 제작·라이선스·개발 지출의 자산화와 상각 시차는 얼마인가",
            "플랫폼 수수료·마케팅·인수 비용을 포함해 매출 증가가 현금으로 이어지는가",
        ],
    ),
    "retail": (
        "기존점·신규점과 재고·회원 수익",
        [
            "기존점의 고객 수·객단가 변화와 신규점·인수 효과를 구분할 수 있는가",
            "회원비·상품 마진·광고 등 수익원을 나누고 매출총이익 정의를 맞췄는가",
            "재고·공급업체 결제·점포 리스와 투자 부담이 현금에 어떻게 반영되는가",
        ],
    ),
    "telecom": (
        "가입자 수익과 통신망·주파수 투자",
        [
            "가입자·해지율·요금과 단말 판매·기업서비스의 변화를 분리할 수 있는가",
            "망 구축·주파수·리스·가입자 확보비의 현금 및 상각 시차는 무엇인가",
            "보상·보안 비용·구조조정과 자회사 실적을 반복 통신 수익과 구별했는가",
        ],
    ),
    "consumer": (
        "브랜드·지역·유통 채널과 현금",
        [
            "판매 수량·가격·제품 구성·환율 중 지역별 매출을 설명하는 항목은 무엇인가",
            "유통 채널 재고·반품·판촉과 소비자 판매가 같은 방향으로 변하는가",
            "원재료·마케팅·공장 투자와 인수 효과를 반복 현금에서 구별할 수 있는가",
        ],
    ),
    "memory": (
        "메모리의 가격·물량과 재투자",
        [
            "제품 가격과 출하량 중 매출 변화를 설명하는 항목은 무엇인가",
            "증설·전환 투자와 감가상각이 향후 현금에 어떤 조건을 만드는가",
            "고객 집중·재고·회수 조건이 이익의 지속성을 약화하는가",
        ],
    ),
    "chip-design": (
        "제품 구성·공급 계약과 현금",
        [
            "제품·고객별 성장과 가격 효과를 분리할 수 있는가",
            "구매 약정·선급금·재고에 묶인 자금은 얼마인가",
            "설비 지출 밖의 연구개발·인수·주식보상이 주주 몫에 어떻게 반영되는가",
        ],
    ),
    "chip-manufacturing": (
        "제조 가동률과 투자 회수",
        [
            "제품별 수익과 외부 고객 사업의 손익이 구분되는가",
            "가동률·수율·단위 원가의 변화가 확인되는가",
            "설비 투자·보조금·감가상각의 시점 차이가 얼마나 큰가",
        ],
    ),
    "electronics": (
        "사업부 구성과 자본 배분",
        [
            "사업부별 매출·마진 중 연결 이익 변화를 설명하는 것은 무엇인가",
            "서비스·하드웨어·연결 자회사의 현금 구조가 어떻게 다른가",
            "사업별 재투자와 주주 환원 사이에 어떤 제약이 있는가",
        ],
    ),
    "internet": (
        "플랫폼 성장의 현금 비용",
        [
            "광고·커머스·구독 등 수익원별 성장과 비용이 구분되는가",
            "인프라 투자·리스·감가상각 증가가 현금에 어떻게 반영되는가",
            "선수금·정산 주기·주식보상 효과를 구분할 수 있는가",
        ],
    ),
    "cloud": (
        "계약 매출과 인프라 투자",
        [
            "계약 잔액·매출 인식·수금이 같은 방향으로 변하는가",
            "서버 투자와 리스 의무가 증가분의 수익성을 지지하는가",
            "사업부별 성장과 투자 회수 조건을 분리할 수 있는가",
        ],
    ),
    "semicap": (
        "수주와 인도·서비스의 연결",
        [
            "장비 출하·인도·매출 인식과 수금의 시점 차이는 무엇인가",
            "신규 장비와 서비스의 매출·마진을 구분할 수 있는가",
            "고객 투자 계획·재고·계약 의무가 다음 기간에 미치는 영향은 무엇인가",
        ],
    ),
    "automotive": (
        "판매 구성과 제조·금융 현금",
        [
            "판매 대수·가격·제품 구성·인센티브를 구분할 수 있는가",
            "제조업과 금융 자회사 현금·부채를 분리할 수 있는가",
            "설비·개발비·보증 비용이 반복 현금에 만드는 부담은 무엇인가",
        ],
    ),
    "industrials": (
        "수주·원가·공정과 현금",
        [
            "수주 잔액이 어떤 조건으로 매출과 현금으로 전환되는가",
            "공정률·계약자산·고객 선급금이 이익과 현금 차이를 설명하는가",
            "원가 추정 변경·충당부채·사업 재편 효과는 반복 가능한가",
        ],
    ),
    "healthcare": (
        "제품 매출·개발비와 생산 능력",
        [
            "제품별 수익과 기술료·계약금 등 일시 항목을 구분할 수 있는가",
            "연구개발 비용·무형자산·인수 지출이 모두 반영됐는가",
            "생산 증설·재고·제품 집중이 현금 회수에 만드는 조건은 무엇인가",
        ],
    ),
    "materials": (
        "가격·가동률과 투자 부담",
        [
            "판매량·원재료 가격·제품 가격이 매출과 마진에 어떻게 반영되는가",
            "가동률과 증설 일정이 감가상각·투자 회수 조건을 바꾸는가",
            "보조금·재고 평가·지분 관계 손익이 반복 수익과 구분되는가",
        ],
    ),
}


def investment_scope(fact):
    if fact.get("investmentScope"):
        return fact["investmentScope"]
    tag = fact.get("tag", "").split(":")[-1]
    return {
        "PaymentsToAcquireProductiveAssets": "유형·무형자산 취득",
        "PaymentsToAcquireOtherPropertyPlantAndEquipment": "기타 분류 유형자산 취득",
    }.get(tag, "유형자산 취득")


def profit_bridge(current, previous):
    needed = [
        g.get(k) for g in (current, previous) for k in ("revenue", "operating_income")
    ]
    if (
        any(f is None for f in needed)
        or min(current["revenue"]["value"], previous["revenue"]["value"]) <= 0
    ):
        return None
    r0, r1 = previous["revenue"]["value"], current["revenue"]["value"]
    p0, p1 = previous["operating_income"]["value"], current["operating_income"]["value"]
    scale = (r1 - r0) * p0 / r0
    margin = r1 * (p1 / r1 - p0 / r0)
    if abs(scale + margin - (p1 - p0)) > max(1, abs(p1 - p0) * 1e-12):
        raise ValueError("Profit bridge does not reconcile")
    return dict(
        previous=p0,
        current=p1,
        change=p1 - p0,
        revenueEffect=scale,
        marginEffect=margin,
        evidence=needed,
        definition="매출 변화 × 전년 영업이익률 + 당기 매출 × 영업이익률 변화 = 영업이익 변화",
        limitation="회계 항등식의 순서가 정해진 분해. 매출 효과에는 가격·물량·제품 구성 등이 섞여 있으며 인과 기여도로 해석하지 않는다.",
    )


def build(company, facts, as_of):
    s = company["financials"]
    title, questions = PROFILES.get(
        company.get("peerGroup"),
        ("사업·재투자와 현금", ["사업부별 매출·이익과 현금의 연결을 확인한다"]),
    )
    current, previous = s["current"], s["previous"]
    cash = None
    comparable = (
        all(previous.get(k) for k in ("cfo", "capex"))
        and investment_scope(previous["capex"]) == company["investmentScope"]
    )
    if comparable:
        cash_effect = current["cfo"]["value"] - previous["cfo"]["value"]
        investment_effect = previous["capex"]["value"] - current["capex"]["value"]
        cash = dict(
            cfoEffect=cash_effect,
            investmentEffect=investment_effect,
            totalChange=cash_effect + investment_effect,
            evidence=[g[k] for g in (previous, current) for k in ("cfo", "capex")],
        )
    periods = {
        (f["start"], f["end"])
        for f in facts
        if f["metric"] == "cfo"
        and f["start"]
        and f["filedAt"] <= as_of
        and f["end"] <= as_of
        and 330
        <= (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days + 1
        <= 380
    }
    annual = []
    # One longest period per year-end; the exact dates stay visible.
    ends = sorted({end for _, end in periods}, reverse=True)[:24]
    for end in reversed(ends):
        start = min(start for start, e in periods if e == end)
        values = {
            k: select_fact(facts, k, start, end, as_of)
            for k in ("revenue", "operating_income", "cfo", "capex")
        }
        if (
            not all(values[k] for k in ("revenue", "cfo", "capex"))
            or values["revenue"]["value"] <= 0
        ):
            continue
        revenue = values["revenue"]["value"]
        annual.append(
            dict(
                start=start,
                end=end,
                filedAt=max(f["filedAt"] for f in values.values() if f),
                revenue=revenue,
                operatingMargin=(
                    values["operating_income"]["value"] / revenue
                    if values["operating_income"]
                    else None
                ),
                cfoMargin=values["cfo"]["value"] / revenue,
                cashMargin=(values["cfo"]["value"] - values["capex"]["value"])
                / revenue,
                investmentScope=investment_scope(values["capex"]),
                evidence=[f for f in values.values() if f],
            )
        )
    result = dict(
        version="company-analysis-v1",
        title=title,
        questions=questions,
        questionStatus="사업 분류별 조사 질문 · 공시에서 확인된 기업 사실이나 AI 결론이 아님",
        profitBridge=profit_bridge(current, previous),
        cashChange=cash,
        annual=annual[-6:],
        annualScope="현재 기준일까지 제출된 자료로 본 연간·12개월 구간. 서로 겹치는 최근 12개월 구간이 포함될 수 있으며 분기 성장률이나 과거 시점 신호가 아니다.",
        evidence=[f for g in (current, previous) for f in g.values() if f],
        depth="filing_calculations_and_research_questions",
        nextAction="사업부·제품·가격·물량과 계약 주석을 연결해 원인을 검토",
    )
    result["evidenceHash"] = digest(canonical(result))
    return result


def peers(company, companies):
    rows = []
    for other in companies:
        if (
            other["id"] == company["id"]
            or other.get("status") != "ready"
            or other.get("peerGroup") != company.get("peerGroup")
        ):
            continue
        reasons = []
        if any(
            x.get("cashScope", {}).get("status") == "review_required"
            for x in [company, other]
        ):
            reasons.append("중단영업 현금과 계속영업 매출·투자 범위 대사 필요")
        if other["financials"]["standard"] != company["financials"]["standard"]:
            reasons.append("회계 기준 차이")
        if abs(other["financials"]["days"] - company["financials"]["days"]) > 8:
            reasons.append("누적 기간 길이 차이")
        if (
            abs(
                (
                    date.fromisoformat(other["financials"]["end"])
                    - date.fromisoformat(company["financials"]["end"])
                ).days
            )
            > 35
        ):
            reasons.append("기간 종료일 차이")
        if other["investmentScope"] != company["investmentScope"]:
            reasons.append("투자지출 정의 차이")
        rows.append(
            dict(id=other["id"], cautions=reasons, directComparison=not reasons)
        )
    return rows
