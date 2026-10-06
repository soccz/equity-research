"""Separate observed issuance, reported treasury holdings and uncompleted buyback."""

import json
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from .data import ROOT, canonical, digest, read_verified
from .narrative import extract

DOCUMENT_ROOT = ROOT
SOURCES = [
    (
        "20260715000004",
        "2026-07-15",
        "9ac60312680fb50caf202694f9e2634bb7d71cccbfb81fe7477b88acad0d4135",
        [4, 10, 12],
    ),
    (
        "20260819000254",
        "2026-08-19",
        "d2affcfa8a71c4205e9ab7aa3792e8d1fbb7490e80925154a5b7bc0849f40cc7",
        [4, 5, 10, 24, 26],
    ),
    (
        "20260821000495",
        "2026-08-21",
        "e021de930ab2b6d2d7ae98b10470e76ce0c2117649c080f1385a6f73df1fedd3",
        [5, 8, 11],
    ),
    (
        "20260922000361",
        "2026-09-22",
        "62c7d36a2e9c1c2ba3fda83cededa40adbe560c537fd9854290e123babc8adfe",
        [],
    ),
]


def build(c, shares):
    core = c["financials"]["current"]["cfo"]
    price_date = c["priceSummary"]["lastDate"]
    if (
        c["id"] != "000660"
        or core["accession"] != "20260814003509"
        or not shares
        or shares["end"] != "2026-06-30"
        or price_date < "2026-07-15"
    ):
        return None
    if "issued" not in shares:
        from .security import load as share_table

        table = share_table(c, price_date)
        opening = table.get("shares") if table else None
        if (
            not opening
            or opening["value"] != shares["value"]
            or opening["end"] != shares["end"]
        ):
            raise ValueError("Hynix opening XBRL and share table disagree")
        shares = opening
    if (
        shares["issued"] != 712702365
        or shares["treasury"] != 1626865
        or shares["value"] != 711075500
    ):
        raise ValueError("Hynix starting share table changed")
    docs, passages = {}, []
    for receipt, filed, expected, ordinals in SOURCES:
        if filed > price_date:
            continue
        manifest = json.loads(
            (
                DOCUMENT_ROOT / f"data/sources/dart-document-{receipt}.manifest.json"
            ).read_text()
        )
        if manifest["receipt"] != receipt:
            raise ValueError("Hynix capital filing identity differs")
        source = next(s for s in manifest["files"] if s["sha256"] == expected)
        blob = read_verified(DOCUMENT_ROOT / source["file"], expected)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
            soup = BeautifulSoup(blob, "html.parser")
        selected = [
            dict(
                p,
                sourceUrl=manifest["url"],
                sourceHash=expected,
                sourceFile=source["file"],
                accession=receipt,
                filedAt=filed,
            )
            for p in extract(blob)
            if p["ordinal"] in ordinals
        ]
        if len(selected) != len(ordinals):
            raise ValueError("Hynix capital source passages missing")
        passages.extend(selected)
        docs[receipt] = dict(
            soup=soup, source=source, url=manifest["url"], filedAt=filed
        )
        if source["file"] not in {s["file"] for s in c["sources"]}:
            c["sources"].append(
                dict(
                    source,
                    provider="DART",
                    url=manifest["url"],
                    retrievedAt=manifest["retrievedAt"],
                )
            )
    issued = shares["issued"] + 17_790_000
    text = " ".join(p["text"] for p in passages if p["accession"] == "20260715000004")
    if not all(t in text for t in ["17,790,000", "10 ADR", "39,890,534,790,000"]):
        raise ValueError("Hynix issued shares/ADR conversion changed")
    observations = [
        dict(
            label="반기 말 발행 / 자기주식 / 유통",
            date=shares["end"],
            value="712,702,365 / 1,626,865 / 711,075,500주",
            scope="같은 기준일의 공시 주식 총수 표",
            sourceUrl=shares["sourceUrl"],
        ),
        dict(
            label="완료된 원주 신주 발행",
            date="2026-07-14",
            value="17,790,000주",
            scope="1 원주당 10 ADR. ADR 수량은 주식수에 추가하지 않음",
            sourceUrl=docs["20260715000004"]["url"],
        ),
    ]
    repurchase = None
    if "20260819000254" in docs:
        d = docs["20260819000254"]
        start = d["soup"].find(attrs={"aunit": "ACQ_BGN"})
        end = d["soup"].find(attrs={"aunit": "ACQ_END"})
        if (
            not start
            or not end
            or start.get("aunitvalue") != "20260820"
            or end.get("aunitvalue") != "20261119"
        ):
            raise ValueError("Hynix repurchase dates changed")
        repurchase = dict(
            start="2026-08-20",
            end="2026-11-19",
            plannedShares=24070000,
            plannedAmount=40004340000000,
            actualShares=None,
            status="actual_execution_unconfirmed",
            sourceUrl=d["url"],
        )
        observations.append(
            dict(
                label="취득·소각 목적의 계획",
                date="2026-08-20–2026-11-19",
                value="예정 24,070,000주",
                scope="주가에 따라 취득 수량 변동. 기준일 실제 취득·소각 완료 수량 미확인",
                sourceUrl=d["url"],
            )
        )
    treasury = None
    if "20260821000495" in docs:
        d = docs["20260821000495"]
        rows = [
            [
                x.get_text(" ", strip=True)
                for x in tr.find_all(["td", "te", "tu", "th"], recursive=False)
            ]
            for tr in d["soup"].find_all("tr")
        ]
        if not any(r[:2] == ["보통주식", "1,625,769"] for r in rows) or not any(
            r[:4] == ["2026년 08월 19일", "보통주식", "82", "82"] for r in rows
        ):
            raise ValueError("Hynix treasury disposal/holding differs")
        treasury = dict(value=1625769, end="2026-08-21", sourceUrl=d["url"])
        observations.extend(
            [
                dict(
                    label="자기주식 처분 결과",
                    date="2026-08-19",
                    value="82주",
                    scope="개별 처분 완료 수량. 반기 이후 전체 변동 합계가 아님",
                    sourceUrl=d["url"],
                ),
                dict(
                    label="처분 결과 보고서 보유 잔액",
                    date="2026-08-21",
                    value="자기주식 1,625,769주",
                    scope="이 날짜의 신고 잔액. 이후 진행 중 취득을 영으로 놓지 않음",
                    sourceUrl=d["url"],
                ),
            ]
        )
    latest_issued = None
    if "20260922000361" in docs:
        d = docs["20260922000361"]
        amounts = {
            e.get_text(strip=True).replace(",", "")
            for e in d["soup"].find_all(attrs={"acode": "FLT_SUM"})
        }
        if amounts != {str(issued)}:
            raise ValueError("Hynix later issued count does not match completed issue")
        latest_issued = dict(
            value=issued,
            filedAt=d["filedAt"],
            sourceUrl=d["url"],
            definition="임원 보고서의 발행주식 총수; 자기주식 차감 전",
        )
        observations.append(
            dict(
                label="후속 공시 발행 총수",
                date="2026-09-22 공시",
                value=f"{issued:,}주",
                scope="발행 총수는 신주 합계와 일치. 다른 날짜 자기주식 잔액을 빼서 현재 유통 수량으로 확정하지 않음",
                sourceUrl=d["url"],
            )
        )
    result = dict(
        status="subsequent_capital_changes_unresolved",
        version="hynix-capital-events-v1",
        asOf=price_date,
        reviewedThrough="2026-09-29",
        opening=shares,
        issuedAfterKnownIssue=issued,
        latestIssued=latest_issued,
        latestTreasury=treasury,
        repurchase=repurchase,
        currentOutstanding=None,
        observations=observations,
        passages=passages,
        issue="반기 이후 신주 발행과 자기주식 취득·처분이 있어 가격 기준일 유통주식수 재대사가 필요함",
        scope="공식 발행 결과·후속 보유 잔액·매입 계획을 구별합니다. 원주와 ADR을 중복 합산하거나 예정 취득 수량을 완료 수량으로 차감하지 않습니다. 알려진 신주 발행을 무시한 반기 말 주식수로 주당 계산을 유지하지 않습니다.",
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
