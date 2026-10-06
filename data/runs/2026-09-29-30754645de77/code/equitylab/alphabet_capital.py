"""Filing-bound preferred terms; basic conversion is not total equity dilution."""

from decimal import Decimal, ROUND_HALF_UP
import json
import math

from .data import ROOT, read_verified, canonical, digest
from .narrative import extract

CURRENT = "0001652044-26-000071"
CURRENT_HASH = "edb04d9212ab1188f7e240c8f069d801bc71ce67245c791dfa2c39c1cfef9fa7"
EXHIBIT_ACCESSION = "0001193125-26-259830"
TERMS = (
    (
        "A",
        "A",
        "ex31",
        "3b480288c8868330abfba10253dd1d863cba53ddaf497dca3085cee5e087d272",
        2.2520,
        2.8160,
        355.1136,
        444.0497,
    ),
    (
        "B",
        "C",
        "ex32",
        "45135a3f39daf123398f511311055134630a7322936170970291951537627f78",
        2.2740,
        2.8420,
        351.8649,
        439.7537,
    ),
)


def conversion(term, applicable_market_value):
    """Initial contract, one preferred share, no later adjustments or dividend stock."""
    if (
        type(applicable_market_value) not in (int, float)
        or not math.isfinite(applicable_market_value)
        or applicable_market_value <= 0
    ):
        raise ValueError("A finite positive contractual averaging price is required")
    if applicable_market_value > term["thresholdPrice"]:
        return term["minimumRate"]
    if applicable_market_value < term["initialPrice"]:
        return term["maximumRate"]
    return float(
        (Decimal(1000) / Decimal(str(applicable_market_value))).quantize(
            Decimal(".0001"), rounding=ROUND_HALF_UP
        )
    )


def _source(c, key, expected, accession):
    manifest = json.loads(
        (ROOT / f"data/sources/filing-{key}.manifest.json").read_text()
    )
    if (
        manifest["sha256"] != expected
        or manifest["accession"] != accession
        or manifest["cik"] != 1652044
    ):
        raise ValueError("Alphabet capital contract source changed; review required")
    rows = extract(read_verified(ROOT / manifest["file"], expected))
    return manifest, rows


def build(c):
    core = c.get("financials", {}).get("current", {}).get("cfo", {})
    if (
        c["id"] != "GOOGL"
        or core.get("accession") != CURRENT
        or core["filedAt"] > c["priceSummary"]["lastDate"]
    ):
        return None
    source, rows = _source(c, CURRENT, CURRENT_HASH, CURRENT)
    selected = [rows[i] for i in [47, 98, 677, 678, 679, 680, 683, 684, 685, 700]]
    if not all(
        text in rows[i]["text"]
        for i, text in [
            (677, "1/20th"),
            (679, "6.25%"),
            (700, "identical, except with respect to voting"),
        ]
    ):
        raise ValueError("Alphabet current capital terms need review")
    sources = [source]
    terms = []
    for series, stock, suffix, sha, minimum, maximum, initial, threshold in TERMS:
        manifest, contract = _source(
            c, f"{EXHIBIT_ACCESSION}-{suffix}", sha, EXHIBIT_ACCESSION
        )
        sections = []
        for prefix in [
            "Part 1. Designation",
            "“Dividend Payment Date”",
            "“Final Averaging Period”",
            "“Initial Price”",
            "“Threshold Appreciation Price”",
            "SECTION 3. Dividends. (a)",
            "(i) if the Applicable Market Value",
            "(ii) if the Applicable Market Value",
            "(iii) if the Applicable Market Value",
            "(c) If the Corporation declares a dividend for the Dividend Period ending on May 15, 2029",
        ]:
            found = [p for p in contract if p["text"].startswith(prefix)]
            if len(found) != 1:
                raise ValueError(
                    "Missing or ambiguous preferred stock contract section"
                )
            sections.append(found[0])
        checks = [
            (0, "9,625,000"),
            (2, "20 consecutive Trading Day"),
            (3, f"{initial:.4f}"),
            (4, f"{threshold:.4f}"),
            (5, "$62.50"),
            (6, f"{minimum:.4f}"),
            (8, f"{maximum:.4f}"),
            (9, "additional number of shares"),
        ]
        if not all(text in sections[i]["text"] for i, text in checks):
            raise ValueError("Preferred terms differ from reviewed contract")
        terms.append(
            dict(
                series=series,
                commonClass=stock,
                liquidationPreference=1000,
                dividendRate=0.0625,
                annualDividendPerPreferred=62.5,
                designatedShares=9625000,
                currentOutstandingExact=None,
                minimumRate=minimum,
                maximumRate=maximum,
                initialPrice=initial,
                thresholdPrice=threshold,
                sourceUrl=manifest["url"],
                sourceHash=sha,
                passages=sections,
            )
        )
        sources.append(manifest)
    for s in sources:
        if s["file"] not in {x["file"] for x in c["sources"]}:
            c["sources"].append(s)
    result = dict(
        version="alphabet-preferred-contract-v1",
        status="terms_reviewed_allocation_unresolved",
        financialApproval=False,
        accession=CURRENT,
        observedAt=c["financials"]["end"],
        availableBy=core["filedAt"],
        sourceUrl=source["url"],
        sourceHash=CURRENT_HASH,
        passages=selected,
        mandatoryConversionDate="2029-05-15",
        terms=terms,
        commonRights="A·B·C 보통주의 배당·청산권은 동일하고 의결권은 다릅니다. 전환우선주의 권리는 별도입니다.",
        quantityScope="현재 공시는 우선주 19백만 주와 예탁주 385백만 주를 반올림해 표시합니다. 각 계약의 9,625,000주는 지정 수량이며 현재 유통 수량으로 대체하지 않습니다.",
        scope="우선주 한 주당 최초 계약의 기본 전환만 계산합니다. 입력은 미래 최종 20거래일의 계약상 평균가격 가정이며 오늘의 주가나 목표가가 아닙니다. 전체 희석·주당 가치 계산은 보류합니다.",
        remaining=[
            "같은 기준일의 정확한 우선주 유통 수량과 A·B·C 보통주 수량",
            "지급된 배당·미지급 누적배당과 현금·보통주 지급 선택",
            "반희석 조정·조기 전환·기업 재편 조건 적용 여부",
            "capped call의 실제 순정산과 상대방 이행, 추가 ATM 발행",
        ],
        dividendScope="연 62.50달러는 우선주 한 주의 연율 기준 배당권입니다. 현금·주식·혼합 지급이 가능하므로 실제 현금 유출이나 전환일까지의 총배당과 다릅니다. 미지급 배당은 추가 주식과 잔여 현금 의무를 만들 수 있습니다.",
        capScope="회사 공시는 capped call이 잠재 희석을 줄이기 위한 것이라고 설명합니다. 기본 전환 주식 수에서 정산 수량을 확인 없이 차감하지 않습니다.",
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
