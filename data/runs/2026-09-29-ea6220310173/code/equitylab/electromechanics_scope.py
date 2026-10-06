"""Preserve conflicting signs in two specific Samsung Electro-Mechanics filings."""

import json
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from .data import ROOT, canonical, digest, read_verified

DOCUMENTS = {
    "20260310003071": dict(
        sha256="4c5f2623fe66ebc8bd1c0bb13414bcc6b198dd69cf1cf9ce4ec0d22673a2c2e7",
        xbrl="7326bf3f9cd2a43ba9316c1682df7a1269e0ef987e6e6217e360d37ad006d585",
        table=1710,
        headers=["구분", "당기", "전기"],
        values=["2,881,532", "(6,870,800)"],
    ),
    "20260814003805": dict(
        sha256="bd105854daeaa427a5ca32225db5964b5687abb8e0867c7bfeae7844404da75b",
        xbrl="1f1185999ad4f1ed8a2da2a472618a3dd6f432a8f2ad600e6580f1e0951e8b6e",
        table=1314,
        headers=["구분", "당반기", "전반기"],
        values=["475,808", "556,263"],
    ),
}
PERIODS = [
    ("20260310003071", "2025-01-01", "2025-12-31", 1),
    ("20260814003805", "2026-01-01", "2026-06-30", 1),
    ("20260814003805", "2025-01-01", "2025-06-30", 2),
]


def document_table(receipt):
    spec = DOCUMENTS[receipt]
    manifest = json.loads(
        (ROOT / f"data/sources/dart-document-{receipt}.manifest.json").read_text()
    )
    if manifest["receipt"] != receipt:
        raise ValueError("Discontinued cash document receipt changed")
    source = next(s for s in manifest["files"] if s["sha256"] == spec["sha256"])
    blob = read_verified(ROOT / source["file"], source["sha256"])
    # These DART XML files contain malformed XML; use the installed tolerant HTML
    # parser, then check the exact file hash, table header, unit and source cells.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        tables = BeautifulSoup(blob, "html.parser").find_all("table")
    index = spec["table"]
    if "단위:천원" not in "".join(tables[index - 1].get_text().split()):
        raise ValueError("Discontinued cash narrative unit changed")
    table = tables[index]
    rows = [
        [
            " ".join(td.get_text(" ", strip=True).split())
            for td in tr.find_all(["td", "th"])
        ]
        for tr in table.find_all("tr")
    ]
    if ["".join(x.split()) for x in rows[0]] != spec["headers"]:
        raise ValueError("Discontinued cash narrative columns changed")
    cash = [r for r in rows if r[0] == "영업현금흐름"]
    if len(cash) != 1 or cash[0][1:] != spec["values"]:
        raise ValueError("Discontinued cash narrative row changed")
    return dict(
        sourceFile=source["file"],
        sourceHash=source["sha256"],
        sourceUrl=manifest["url"],
        retrievedAt=manifest["retrievedAt"],
        accession=receipt,
        tableIndex=index,
        sourceUnit="천원",
        rows=rows,
        tableHash=digest(canonical(rows)),
    )


def build(c, observations, as_of):
    expected = [(a, s, e) for a, s, e, _ in PERIODS]
    actual = [
        (
            o["reportedCfo"]["accession"],
            o["reportedCfo"]["start"],
            o["reportedCfo"]["end"],
        )
        for o in observations
    ]
    pending = dict(
        status="source_review_required",
        reason="이전 공시에서 XBRL과 본문 주석의 부호 불일치를 발견했다. 새 공시·기간의 부호와 계속영업 범위를 다시 대사해야 한다.",
        observations=[],
    )
    if c["id"] != "009150" or actual != expected or as_of < "2026-08-14":
        return pending
    for observation in observations:
        fact = observation["discontinuedCfo"]
        if fact is None:
            return pending
        source = next(s for s in c["sources"] if s["file"] == fact["sourceFile"])
        if source["sha256"] != DOCUMENTS[fact["accession"]]["xbrl"]:
            return pending
    documents = {receipt: document_table(receipt) for receipt in DOCUMENTS}
    comparisons = []
    for observation, (receipt, start, end, column) in zip(observations, PERIODS):
        document = documents[receipt]
        text = document["rows"][1][column]
        value = int(text.replace(",", "")) * 1000
        fact = observation["discontinuedCfo"]
        if fact["value"] != -value:
            raise ValueError("Reviewed discontinued cash sign conflict changed")
        comparisons.append(
            dict(
                label=observation["label"],
                start=start,
                end=end,
                status="source_conflict",
                xbrl=fact,
                narrative=dict(
                    value=value, unit="KRW", sourceText=text, column=column, **document
                ),
                selectedValue=None,
            )
        )
        observation["status"] = "source_conflict"
    for d in documents.values():
        if d["sourceFile"] not in {s["file"] for s in c["sources"]}:
            c["sources"].append(
                dict(
                    file=d["sourceFile"],
                    sha256=d["sourceHash"],
                    url=d["sourceUrl"],
                    provider="OpenDART",
                    retrievedAt=d["retrievedAt"],
                )
            )
    return dict(
        status="source_conflict",
        reason="같은 공시의 XBRL 중단영업 영업현금과 본문 주석의 부호가 반대다. 어느 쪽도 확정값으로 선택하지 않으며 계속영업 현금·투자 취득 범위와 가격 역산을 보류한다.",
        observations=comparisons,
        rule="원문 표의 천원 단위만 원으로 환산했다. 절댓값 보정·임의 상계·총액 차감을 하지 않는다. 순투자현금의 부호로 취득 지출을 영으로 판정하지 않는다.",
    )
