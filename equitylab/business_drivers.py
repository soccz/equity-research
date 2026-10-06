"""Issuer-specific reported changes, reconciled without inferring causation."""

import re
from bs4 import BeautifulSoup
from .data import ROOT, read_verified, canonical, digest


def table_from_source(passage, markers, preceding_caption=None):
    blob = read_verified(ROOT / passage["sourceFile"], passage["sourceHash"])
    soup = BeautifulSoup(blob, "html.parser")
    matches = [
        t
        for t in soup.find_all("table")
        if all(m in t.get_text(" ", strip=True) for m in markers)
    ]
    if len(matches) != 1:
        raise ValueError("Business driver table selection is ambiguous or missing")
    if preceding_caption:
        text = soup.get_text(" ", strip=True)
        position = text.index(matches[0].get_text(" ", strip=True))
        if preceding_caption not in text[max(0, position - 500) : position]:
            raise ValueError("Business driver table unit or scope changed")
    return matches[0]


def table_numbers(table, label, count):
    rows = []
    for tr in table.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        if text.startswith(label + " "):
            tail = text[len(label) :].strip()
            if tail.startswith("%"):
                continue
            rows.append(tail)
    if len(rows) != 1:
        raise ValueError("Business driver row selection is ambiguous or missing")
    tokens = re.findall(r"\(?\d[\d,]*(?:\.\d+)?\)?", rows[0])
    if len(tokens) != count:
        raise ValueError("Business driver table columns changed")
    return [
        float(t.strip("()").replace(",", "")) * (-1 if t.startswith("(") else 1)
        for t in tokens
    ]


def amount(text, pattern, scale=1):
    matches = re.findall(pattern, text)
    if len(matches) != 1:
        raise ValueError("Business driver explanation changed")
    return float(matches[0].replace(",", "")) * scale


def row(label, value, kind="delta", basis="원문 금액"):
    return dict(label=label, value=value, kind=kind, basis=basis)


def bridge(title, period, rows, explanation, sources):
    if (
        abs(rows[0]["value"] + sum(r["value"] for r in rows[1:-1]) - rows[-1]["value"])
        > 1e-6
    ):
        raise ValueError("Business driver changes do not reconcile")
    return dict(
        title=title, period=period, rows=rows, explanation=explanation, sources=sources
    )


def build(c, passages):
    """Called only after the authored accession and corpus hash match."""
    if c["id"] not in {"INTC", "QCOM"}:
        return None
    index = {p["id"]: p for p in passages}
    charts = []
    if c["id"] == "INTC":
        p = index["79e1f12b2bd591286d1c"]
        table = table_from_source(
            p,
            [
                "Six Months Ended",
                "($ In Millions)",
                "Jun 27, 2026",
                "Jun 28, 2025",
                "Operating loss",
                "5,765",
            ],
        )
        qcurrent, qprior, current, prior = table_numbers(table, "Operating loss", 4)
        text = p["text"]
        charges = amount(text, r"\$([\d.]+) billion of lower period charges", 1000)
        product = -amount(text, r"\$([\d.]+) million of lower product profit")
        residual = current - prior - charges - product
        charts.append(
            bridge(
                "파운드리 적자 축소 중 제품 수익의 기여는 음수",
                "2026 상반기 / 전년 동기 · Intel Foundry · 영업손익",
                [
                    row("전년 영업손익", prior, "start"),
                    row(
                        "기간 비용 감소",
                        charges,
                        basis="회사 설명 · 십억 달러 단위 반올림",
                    ),
                    row("제품 수익 감소", product, basis="회사 설명"),
                    row("반올림·기타 잔차", residual, basis="계산 잔차 · 원인 미배분"),
                    row("당기 영업손익", current, "end"),
                ],
                "기간 비용 감소에는 전년 손상·가속상각의 부재와 재고 비용 감소가 포함됩니다. 반올림된 회사 설명과 보고 표의 차이를 잔차로 남깁니다. 이를 추가 비용의 독립 식별이나 공정 수율의 인과 검증으로 보지 않습니다. 연결 전체의 제품 수익 변화와 범위가 다릅니다.",
                [index["63100509960a1bead134"], p],
            )
        )
    else:
        p = index["29c52ba32006ab8f5e70"]
        table = table_from_source(
            p,
            [
                "Nine Months Ended",
                "June 28, 2026",
                "June 29, 2025",
                "Handsets",
                "Automotive",
                "EBT",
                "Change",
            ],
            "QCT Segment (in millions, except percentages)",
        )
        handsets = table_numbers(table, "Handsets", 6)
        auto = table_numbers(table, "Automotive", 6)
        iot = table_numbers(table, "IoT (internet of things)", 6)
        total = table_numbers(table, "Total revenues (1)", 6)
        for values in [handsets, auto, iot, total]:
            if any(
                abs(values[k] - values[k + 1] - values[k + 2]) > 1e-6 for k in [0, 3]
            ):
                raise ValueError("QCT disclosed changes differ from period values")
        if any(
            abs(sum(v[k] for v in [handsets, auto, iot]) - total[k]) > 1e-6
            for k in range(6)
        ):
            raise ValueError("QCT business revenue does not reconcile")
        for name, offset, source in [
            ("3분기", 0, p),
            ("9개월 누적", 3, index["54291e386800cab6043b"]),
        ]:
            price = amount(
                source["text"], r"\$([\d.]+) million increase in revenues per unit"
            )
            shipment = amount(source["text"], r"\$([\d.]+) million in higher shipments")
            charts.append(
                bridge(
                    "자동차 증가분을 가격·구성과 출하로 분해",
                    f"2026 회계연도 {name} / 전년 동기 · QCT 자동차 매출",
                    [
                        row("전년 자동차", auto[offset + 1], "start"),
                        row("가격·구성 기여", price, basis="회사 설명 · 매출 기여액"),
                        row("출하 기여", shipment, basis="회사 설명 · 매출 기여액"),
                        row("당기 자동차", auto[offset], "end"),
                    ],
                    "가격·구성 금액은 매출 증가의 기여액이며 칩 한 개의 가격이 아닙니다. 매출 기여가 같은 금액의 이익·현금 기여를 의미하지 않습니다. 분기와 누적기간은 서로 더하지 않습니다.",
                    [source],
                )
            )
        charts.insert(
            0,
            bridge(
                "자동차·IoT 증가에도 QCT 전체 매출은 감소",
                "2026 회계연도 3분기 / 전년 동기 · QCT 매출",
                [
                    row("전년 QCT", total[1], "start"),
                    row("휴대폰 변화", handsets[2]),
                    row("자동차 변화", auto[2]),
                    row("IoT 변화", iot[2]),
                    row("당기 QCT", total[0], "end"),
                ],
                "제품군 매출의 전년 대비 차이를 대사한 것입니다. 휴대폰 감소의 독립 인과 검증이나 회사 전체 매출·영업이익 분해가 아닙니다. QTL 라이선스 사업은 이 표에 포함되지 않습니다.",
                [
                    index["f4d4959b417d224656db"],
                    index["2041ca02f3d687de621c"],
                    p,
                    index["8001d58dfcc9d9f4c495"],
                ],
            ),
        )
    result = dict(
        version="reported-business-drivers-v1",
        unit="백만 달러",
        charts=charts,
        financialApproval=False,
        sourceTable=dict(
            text=table.get_text(" ", strip=True),
            sourceFile=p["sourceFile"],
            sourceHash=p["sourceHash"],
            sourceUrl=p["sourceUrl"],
        ),
        scope="원문 표·회사 설명의 금액 대사. 정상 이익·현금 가치의 추정과 독립 인과 검증은 별도입니다.",
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
