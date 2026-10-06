"""NAVER equity-accounted investments: book evidence, never assumed fair value."""

from lxml import html
from .data import ROOT, read_verified
from .xbrl import select

DOCUMENT_SHA = "58c2b8f9094605a021500042312424be204b756ee898fe884ed6c7f3785f177f"
CON = [("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")]


def build(c, rows, passages):
    source = next(s for s in c["sources"] if s["sha256"] == DOCUMENT_SHA)
    blob = read_verified(ROOT / source["file"], DOCUMENT_SHA)
    root = html.fromstring(blob)
    tables = root.xpath("//table[not(.//table)]")

    def table_rows(*terms):
        matched = [t for t in tables if all(v in " ".join(t.itertext()) for v in terms)]
        if len(matched) != 1:
            raise ValueError("NAVER investment table identity changed")
        return [
            [" ".join(x.itertext()).strip() for x in tr.xpath("./td|./th")]
            for tr in matched[0].xpath(".//tr")
        ]

    def amount(v):
        if v == "-":
            return 0
        return int(v.replace(",", "").replace("(", "-").replace(")", "")) * 1000

    current = select(
        rows, "InvestmentAccountedForUsingEquityMethod", None, "2026-06-30", CON, "KRW"
    )
    previous = select(
        rows, "InvestmentAccountedForUsingEquityMethod", None, "2025-12-31", CON, "KRW"
    )
    if current is None or previous is None:
        raise ValueError("NAVER investment balance is missing")
    # The pinned original's table explicitly says KRW thousands. Its small
    # 'other change' row is absent from the narrative index, so read all rows.
    movements = table_rows("반기말금액", "16,648,890,155")
    labels = [
        "기초금액",
        "취득",
        "처분",
        "지분법손익",
        "지분법자본변동",
        "배당",
        "기타증감",
        "반기말금액",
    ]
    movement = []
    for label in labels:
        matched = [r for r in movements if label in r]
        if len(matched) != 1:
            raise ValueError("NAVER investment movement is missing: " + label)
        movement.append(dict(label=label, value=amount(matched[0][-1])))
    residual = movement[-1]["value"] - sum(x["value"] for x in movement[:-1])
    if residual != 0:
        raise ValueError("NAVER investment movement does not reconcile")
    rounding = dict(
        opening=movement[0]["value"] - previous["value"],
        closing=movement[-1]["value"] - current["value"],
    )
    if any(abs(v) > 500 for v in rounding.values()):
        raise ValueError("NAVER investment table/XBRL scope mismatch")
    holdings = table_rows("A Holdings Corporation", "14,929,275,576")
    arow = next(r for r in holdings if "A Holdings Corporation" in r)
    a_book, a_previous = amount(arow[-2]), amount(arow[-1])
    if arow[-3] != "50.00":
        raise ValueError("NAVER consolidated ownership needs review")
    ids = [
        "2e9f3958f833c3a1bbff",
        "ef0f68e749657a7cbb31",
        "bff652dd67aa7463057c",
        "ed1824217399a7a2ba47",
    ]
    index = {p["id"]: p for p in passages}
    if any(p not in index for p in ids):
        raise ValueError("NAVER investment ownership passages changed")
    return dict(
        status="value_assumption_required",
        end="2026-06-30",
        currency="KRW",
        source=source,
        total=current,
        previousTotal=previous,
        holdings=[
            dict(
                label="A Holdings (연결 보유분)",
                value=a_book,
                previousValue=a_previous,
                sourcePrecision=1000,
            ),
            dict(
                label="그 밖 관계·공동기업 (총액−A Holdings)",
                value=current["value"] - a_book,
                previousValue=previous["value"] - a_previous,
                sourcePrecision=1000,
            ),
        ],
        movements=movement,
        movementResidual=residual,
        tableToXbrlRounding=rounding,
        consolidatedOwnership=0.5,
        directOwnership=0.4225,
        approvedEquityValue=None,
        passages=[index[p] for p in ids],
        scope="연결 관계·공동기업 투자 장부금액이며 시장가치·즉시 처분대금·지배주주 귀속액이 아닙니다. A Holdings 연결 지분 50%와 별도 직접 지분 42.25%는 범위가 다릅니다. 연결 장부액에 50%를 다시 곱하거나 별도 원가를 더하지 않습니다.",
        assumptionScope="투자별 가치와 비지배 귀속, 처분세금·비용·시점을 검토한 뒤 지배주주 귀속 순현재가치를 별도로 입력합니다. 빈칸은 미평가, 명시적 0은 해당 가치를 제외한 연구 가정입니다. 장부금액을 자동 적용하지 않습니다.",
        noDoubleCount="사업 경로는 지분법손익·배당을 반복 현금에서 제외합니다. 투자 가치에 포함한 미래 배당을 다시 더하지 않습니다. 고객 자금·현금·차입금·리스 잔액은 이 투자 가정에 넣지 않습니다. 사업 경로에는 순이자·리스 지급 가정이 이미 있어 잔액을 기계적으로 더하거나 빼면 중복될 수 있습니다.",
        remaining="보유 투자별 시장·비상장 가치, 중간 보유법인과 비지배 귀속, 매각 제한·옵션·세금, 현금과 차입의 별도 배분은 미완성입니다. 이 작업표의 합계도 전체 적정가치가 아닙니다.",
    )
