"""Reviewed short table captions omitted by the long-passage search index."""

import re
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from .data import ROOT, read_verified, canonical, digest


def table_context(c, passages):
    if c["id"] != "030200" or c["narrative"]["accession"] != "20260814003463":
        return None
    source = next(p for p in passages if p["id"] == "ddeabdb2e1f6743b83b4")
    if (
        source["sourceHash"]
        != "2b1798a46d13c8a2ea8214fd679953ca3400b56966e2ea185519b5f65ee2ac6a"
    ):
        raise ValueError("KT reviewed short table captions changed")
    # This DART document has unescaped legacy XML text. Use the same tolerant
    # HTML parsing convention as the filing index, then demand exact captions.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        root = BeautifulSoup(
            read_verified(ROOT / source["sourceFile"], source["sourceHash"]),
            "html.parser",
        )

    def text(element):
        return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()

    excerpts = []
    for markers, title, unit, expected_periods in [
        (
            ["사업부문", "제45기 반기", "제 44기", "9,358,050"],
            "사업부문별 영업수익",
            "(단위 : 백만원, %)",
            ["제45기 반기", "제 44기", "제 43기"],
        ),
        (
            ["유형자산및투자부동산의 취득", "1,184,005", "2,171,624"],
            "연결 현금흐름표",
            "(단위 : 백만원)",
            ["2026.01.01", "2026.06.30", "2025.01.01", "2025.06.30"],
        ),
    ]:
        tables = [
            t for t in root.find_all("table") if all(m in text(t) for m in markers)
        ]
        if len(tables) != 1:
            raise ValueError("KT table context is missing or ambiguous")
        table = tables[0]
        caption_table = table.find_previous_sibling("table")
        if caption_table is None:
            raise ValueError("KT table caption is missing")
        caption = text(caption_table)
        header = " ".join(text(t) for t in table.find_all("thead", recursive=False))
        if (
            title not in caption
            or unit not in caption
            or not all(p in caption + " " + header for p in expected_periods)
        ):
            raise ValueError("KT table unit or period context changed")
        excerpts.append(
            dict(
                caption=caption,
                columnHeaders=header,
                tableHash=digest(str(table).encode()),
            )
        )
    result = dict(
        sourceFile=source["sourceFile"],
        sourceHash=source["sourceHash"],
        sourceUrl=source["sourceUrl"],
        excerpts=excerpts,
        scope="원 XML에서 선택 표와 바로 앞 표제를 대조했습니다. 사업부 매출 표의 반기·연간 열과 현금표의 반기·전년반기 열을 구분합니다. 금액 단위를 모델이 추정하지 않습니다.",
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
