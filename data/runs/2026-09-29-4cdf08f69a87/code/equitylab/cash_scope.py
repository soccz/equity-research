"""Detect disclosed discontinued-operation cash before using mixed-scope ratios."""

import json

from .data import ROOT, canonical, digest, read_verified
from .xbrl import company_filing, instance_rows

TAGS = {
    "CashFlowsFromUsedInOperatingActivitiesDiscontinuedOperations",
    "NetCashProvidedByUsedInOperatingActivitiesDiscontinuedOperations",
    "CashProvidedByUsedInOperatingActivitiesDiscontinuedOperations",
}
ALLOWED_KR = {
    "ConsolidatedAndSeparateFinancialStatementsAxis": "ConsolidatedMember",
    "ContinuingAndDiscontinuedOperationsAxis": "DiscontinuedOperationsMember",
    "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis": "ReportedAmountMember",
}


def consolidated_total(row, market):
    dims = dict(row["dimensions"])
    if market == "US":
        return not dims
    return dims.get(
        "ConsolidatedAndSeparateFinancialStatementsAxis"
    ) == "ConsolidatedMember" and all(ALLOWED_KR.get(k) == v for k, v in dims.items())


def select_discontinued(rows, market, start, end, currency):
    matches = [
        r
        for r in rows
        if r["tag"] in TAGS
        and r["start"] == start
        and r["end"] == end
        and r["unit"] == currency
        and consolidated_total(r, market)
    ]
    if len({r["value"] for r in matches}) > 1:
        raise ValueError("Conflicting consolidated discontinued operating cash")
    return matches[0] if matches else None


def build(c, as_of):
    source, current_rows = company_filing(c, as_of)
    if source is None:
        return dict(
            status="unavailable", reason="중단영업 현금 범위의 공시 원문 미확보"
        )
    t = c.get("trailingYear", {})
    components = (t.get("values", {}).get("cfo") or {}).get("components", [])
    observations, cache = [], {}
    for part in components:
        fact = part["fact"]
        if c["market"] == "KR":
            path = fact["sourceFile"]
            if path not in cache:
                src = next(s for s in c["sources"] if s["file"] == path)
                cache[path] = instance_rows(
                    read_verified(ROOT / path, src["sha256"]),
                    c,
                    src,
                    fact["accession"],
                    fact["filedAt"],
                )
            rows = cache[path]
        elif fact["accession"] == source["accession"]:
            rows = current_rows
        else:
            path = ROOT / f"data/sources/filing-{fact['accession']}-xbrl.manifest.json"
            if not path.exists():
                rows = []
            else:
                src = json.loads(path.read_text())
                if (
                    src["accession"] != fact["accession"]
                    or src["cik"] != c["cik"]
                    or fact["filedAt"] > as_of
                ):
                    raise ValueError("Historical cash-scope filing identity differs")
                if src["file"] not in cache:
                    cache[src["file"]] = instance_rows(
                        read_verified(ROOT / src["file"], src["sha256"]),
                        c,
                        src,
                        fact["accession"],
                        fact["filedAt"],
                    )
                rows = cache[src["file"]]
                for item in [src, src.get("indexSource")]:
                    if item and item["file"] not in {s["file"] for s in c["sources"]}:
                        c["sources"].append(
                            dict(
                                item,
                                provider=src["provider"],
                                retrievedAt=src["retrievedAt"],
                            )
                        )
        discontinued = select_discontinued(
            rows, c["market"], fact["start"], fact["end"], c["currency"]
        )
        observations.append(
            dict(
                label=part["label"],
                coefficient=part["coefficient"],
                reportedCfo=fact,
                discontinuedCfo=discontinued,
                status="reported" if discontinued else "not_identified",
            )
        )
    detected = any(
        o["discontinuedCfo"] and o["discontinuedCfo"]["value"] != 0
        for o in observations
    )
    result = dict(
        version="cash-business-scope-v2",
        status="review_required" if detected else "not_detected",
        observations=observations,
        reason=(
            "기간 연결에 중단영업의 영업현금이 공시되어 있다. 매출·영업현금·투자자산 취득의 계속영업 범위를 대사하기 전 가격 역산과 현금 우열 비교를 보류한다."
            if detected
            else "확인한 기간·연결 맥락에서 비영 중단영업 현금을 발견하지 않음. 사업 범위 일치의 승인이나 미확인 금액이 영이라는 판정은 아님"
        ),
        rule="보고된 연결 총액만 선택한다. 별도 재무제표·사업별 상세 금액을 합산하지 않는다. 누락 항목은 영으로 바꾸지 않고 현금흐름 총액에서 임의 차감하지 않는다.",
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
