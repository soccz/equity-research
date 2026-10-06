"""Keep customer warrants separate from currently outstanding common shares."""

import json
from .data import ROOT, canonical, digest, read_verified
from .narrative import extract

CURRENT = "0000002488-26-000123"
SHA = "ccb3f436da6c8ce4755c9a31dbd92e57e1cdd1dc73188c5f33a1f4b073afda8c"
PASSAGE = "9a21c5bbea6f3395b74c"


def build(c):
    core = c["financials"]["current"]["cfo"]
    if core["accession"] != CURRENT:
        return dict(
            status="review_required",
            terms=[],
            issue="AMD 고객 워런트의 새 공시·가득·행사 조건을 다시 검토해야 함",
        )
    if core["filedAt"] > c["priceSummary"]["lastDate"]:
        raise ValueError("AMD warrant source is later than the price observation")
    manifest = json.loads(
        (ROOT / f"data/sources/filing-{CURRENT}.manifest.json").read_text()
    )
    if (
        manifest["accession"] != CURRENT
        or manifest["cik"] != c["cik"]
        or manifest["sha256"] != SHA
    ):
        raise ValueError("AMD warrant source identity changed")
    passages = extract(read_verified(ROOT / manifest["file"], SHA))
    p = next((p for p in passages if p["id"] == PASSAGE), None)
    if p is None or not all(
        s in p["text"]
        for s in [
            "each entitling",
            "160 million",
            "$0.01",
            "October 5, 2030",
            "February 23, 2031",
            "no warrant shares had vested or become exercisable",
        ]
    ):
        raise ValueError("AMD customer warrant terms changed")
    if manifest["file"] not in {s["file"] for s in c["sources"]}:
        c["sources"].append(manifest)
    result = dict(
        version="amd-customer-warrants-v1",
        status="conditional_rights_unresolved",
        accession=CURRENT,
        sourceHash=SHA,
        sourceUrl=manifest["url"],
        filedAt=core["filedAt"],
        observedAt="2026-06-27",
        priceDate=c["priceSummary"]["lastDate"],
        terms=[
            dict(
                holder=name,
                maximumShares=160_000_000,
                exercisePrice=0.01,
                expiry=expiry,
            )
            for name, expiry in [("OpenAI", "2030-10-05"), ("Meta", "2031-02-23")]
        ],
        maximumCombinedShares=320_000_000,
        vestedSharesAtObservation=0,
        exercisableSharesAtObservation=0,
        vestedSharesAtPriceDate=None,
        issue="OpenAI·Meta 고객 워런트의 구매·주가·추가 조건에 따른 희석과 가격 기준일 가득 수량을 대사해야 함",
        scope="각 계약의 최대 수량은 현재 발행·유통 수량이 아닙니다. 결산일 가득·행사 가능 수량 영을 가격 기준일에도 영으로 연장하지 않습니다. 원계약별 조건과 후속 이행을 대사하기 전 전체 주당 값은 보류합니다.",
        conditions="GPU 구매 이정표·주가 목표, OpenAI 주가 성과 기준, 추가 기술·상업 조건. 일정 조건 충족 전에는 부채로 분류하며 공시 요약만으로 실제 미래 희석을 확정하지 않습니다.",
        passage=p,
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
