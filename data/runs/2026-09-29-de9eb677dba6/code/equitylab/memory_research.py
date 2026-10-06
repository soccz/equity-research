"""A sourced memory-industry case; accounting adjustments remain explicit choices."""

from .data import canonical, digest
from .narrative import load

CLAIMS = {
    "MU": [
        dict(
            anchor="Sales of DRAM products increased 211%",
            title="DRAM 확대는 출하량만의 결과가 아니다",
            observation="회사는 누적 DRAM 매출 증가를 가격 약 140%, 비트 출하량 약 30% 증가와 연결한다.",
            basis="2026 회계연도 9개월 / 전년 동기",
            kind="management_explanation",
            interpretation="출하량 증가가 유지되어도 가격이 되돌아가면 매출 경로는 달라진다. 가격·물량·믹스를 분리한 가정이 필요하다.",
            countercase="공급 제약과 고부가 제품 비중이 가격을 지지할 수 있다. 가격 상승 전체를 곧바로 일시적 효과로 제거하지 않는다.",
        ),
        dict(
            anchor="Sales of NAND products increased 183%",
            title="NAND 역시 가격과 물량을 따로 추적",
            observation="회사는 누적 NAND 매출 증가를 가격 약 130%, 비트 출하량 20% 초반대 증가로 설명한다.",
            basis="2026 회계연도 9개월 / 전년 동기",
            kind="management_explanation",
            interpretation="DRAM과 NAND에 같은 성장률을 일괄 적용하면 제품별 가격·수요 차이가 사라진다.",
            countercase="제품 믹스·측정 단위가 변하면 가격과 비트 출하량의 곱만으로 보고 매출을 정확히 재현하지 못한다.",
        ),
        dict(
            anchor="MCBU revenue increased 254% and 190%",
            title="모든 사업부가 물량 확대로 성장한 것은 아니다",
            observation="회사는 MCBU의 분기·누적 매출 증가를 가격 상승으로 설명하며 출하량 감소가 일부 상쇄했다고 서술한다.",
            basis="2026 회계연도 3분기 및 9개월 / 각각 전년 동기",
            kind="management_explanation",
            interpretation="연결 매출 증가를 모든 고객군의 실수요 확대로 읽는 가설은 이 설명과 충돌한다.",
            countercase="비트 감소가 제품 전환·고부가 믹스에서 발생했을 가능성은 남는다. 고객 재고와 제품별 출하 자료가 구별 자료다.",
        ),
    ],
    "000660": [
        dict(
            anchor="나. 주요 제품 등의 가격변동추이 DRAM은 HBM3E",
            title="출하 증가와 가격 상승의 기준 기간을 분리",
            observation="회사는 DRAM 출하량 소폭 증가와 ASP 30% 중반 상승을 설명한다. 같은 문단의 NAND 출하량·ASP는 전분기 대비 각각 10% 중반·50% 중반 상승으로 명시한다.",
            basis="2026 반기보고서 사업 설명 / NAND는 전분기 대비 명시, DRAM 비교 기준은 해당 문장만으로 확정하지 않음",
            kind="management_explanation",
            interpretation="Micron의 누적 전년 대비 수치와 나란히 순위를 매기지 않는다. 먼저 같은 분기·제품·단위로 비교해야 한다.",
            countercase="가격·믹스 강세가 지속된다면 단순 과거 중앙 현금 비율이 새 사업 구성을 과소평가할 수 있다. 지속성에는 계약·제품별 마진 근거가 더 필요하다.",
        ),
    ],
}


def sensitivity(price, volume):
    if not -0.9 <= price <= 1 or not -0.9 <= volume <= 1:
        raise ValueError("Memory sensitivity outside supported range")
    return dict(
        revenueChange=(1 + price) * (1 + volume) - 1,
        volumeToOffsetPrice=1 / (1 + price) - 1,
    )


def build(company, companies):
    if company["id"] not in CLAIMS:
        return None
    body = load(company)
    if body is None:
        return dict(status="missing", reason="현재 사업 설명 원문 미확보")
    # The authored reading belongs to one filing, never silently a future one.
    expected = {"MU": "0000723125-26-000015", "000660": "20260814003509"}
    if body["accession"] != expected[company["id"]]:
        return dict(status="stale", reason="새 공시의 사업 설명을 다시 판독해야 함")
    claims = []
    for spec in CLAIMS[company["id"]]:
        matches = [p for p in body["passages"] if spec["anchor"] in p["text"]]
        if len(matches) != 1:
            raise ValueError("Memory case source anchor missing or ambiguous")
        claims.append(
            dict(
                **spec,
                evidence=matches[0],
                corpusHash=company["narrative"]["evidenceHash"]
            )
        )
    rows = []
    for c in companies:
        if c["id"] not in CLAIMS or c.get("status") != "ready":
            continue
        f, d = c["financials"], c.get("dossier")
        if not d:
            continue
        parts = {p["id"]: p for p in d["current"]["parts"]}
        revenue, cfo, capex = [
            f["current"][k]["value"] for k in ["revenue", "cfo", "capex"]
        ]
        dividend = parts.get("dividends_received")
        sbc = parts.get("sbc")
        # No unstated zero for missing US dividends or other cash components.
        cash_ex_dividend = cfo - dividend["value"] if dividend else None
        rows.append(
            dict(
                company=c["id"],
                name=c["name"],
                currency=c["currency"],
                period=[f["start"], f["end"]],
                revenue=revenue,
                cfo=cfo,
                capex=capex,
                reportedCashMargin=(cfo - capex) / revenue,
                dividend=dividend,
                sbc=sbc,
                exDividendCashMargin=(
                    (cash_ex_dividend - capex) / revenue if dividend else None
                ),
                exDividendAndSbcMargin=(
                    (cash_ex_dividend - capex - sbc["value"]) / revenue
                    if dividend and sbc
                    else None
                ),
                valuationState=c["valuation"]["status"],
                source=f["current"]["cfo"],
                investmentScope=c["investmentScope"],
            )
        )
    result = dict(
        status="ready",
        version="memory-business-case-v1",
        claims=claims,
        comparisons=rows,
        thesis="두 회사의 매출 확대를 AI 수요 하나로 설명하기보다 가격·비트 출하·제품 믹스와 현금 분류를 나눠 검토한다.",
        cashJudgment="SK하이닉스의 영업현금에 포함된 배당을 제외하면 현금 비율 차이가 줄어든다. 이 배당을 비경상으로 확정한 것은 아니며 포함 여부의 민감도다. Micron은 동일 배당 항목을 확보하지 못해 영으로 놓지 않는다.",
        preference="현재 자료로 가격·현금 구조가 맞춰진 상대 선호를 확정하기 어렵다. 잠정 판단은 가격 강세 지속 조건의 관찰이며, 두 회사에 같은 매출 성장률을 적용하는 전망은 채택하지 않는다.",
        nextEvidence=[
            "두 회사의 같은 분기 DRAM·NAND 가격 및 비트 출하량",
            "HBM과 범용 제품의 매출·이익·투자 분리 및 공급 계약의 가격 조정 조건",
            "배당 유입의 기초 자산·반복성, 채권·선수금의 현금 전환",
        ],
        sensitivity=[
            dict(price=p, volume=v, **sensitivity(p, v))
            for p in [-0.3, -0.2, -0.1, 0, 0.1]
            for v in [0, 0.1, 0.2, 0.3]
        ],
        scope="공시 경영진 설명 + 근거를 읽은 연구 초안. 독립 인과 검증·투자 성과 승인 없음. 현금 비교는 9개월과 6개월로 길이가 달라 단순 우열 순위로 사용하지 않는다.",
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
