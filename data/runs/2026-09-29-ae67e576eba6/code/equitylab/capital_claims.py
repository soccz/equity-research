"""Filing-bound parent capital claims, distinct from outstanding common shares."""

import json
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from .data import ROOT, canonical, digest, read_verified
from .narrative import extract
from .xbrl import select

CONTRACTS = {
    "018260": (
        "20260814003604",
        "eb8fbda33a251682fc9674760367571f73a96273f554d4094af9b2860817075b",
    ),
    "INTC": (
        "0000050863-26-000157",
        "8dd3354a69cef1e99d1e6097c66d7fad0b890f06c6f1076bc8a0b9586f239451",
    ),
}


def build(c, rows):
    if c["id"] not in CONTRACTS:
        return None
    receipt, sha = CONTRACTS[c["id"]]
    core = c["financials"]["current"]["cfo"]
    if core["filedAt"] > c["priceSummary"]["lastDate"]:
        raise ValueError("Capital claim filing is later than the price observation")
    if core["accession"] != receipt:
        return dict(
            status="review_required",
            title="전환·조건부 주식 권리의 새 공시 검토",
            observations=[],
            issue="발행된 전환·조건부 주식 권리의 새 공시와 이행을 대사해야 함",
        )
    manifest_path = (
        f"data/sources/dart-document-{receipt}.manifest.json"
        if c["market"] == "KR"
        else f"data/sources/filing-{receipt}.manifest.json"
    )
    manifest = json.loads((ROOT / manifest_path).read_text())
    if c["market"] == "KR":
        if manifest["receipt"] != receipt or c["dartCorpCode"] != "00126186":
            raise ValueError("SDS capital filing identity differs")
        source = dict(next(s for s in manifest["files"] if s["sha256"] == sha))
        source.update(
            provider="DART", url=manifest["url"], retrievedAt=manifest["retrievedAt"]
        )
    else:
        if manifest["accession"] != receipt or manifest["cik"] != c["cik"]:
            raise ValueError("Intel capital filing identity differs")
        source = manifest
    if source["sha256"] != sha:
        raise ValueError("Capital claim source hash differs")
    blob = read_verified(ROOT / source["file"], sha)
    passages = {p["id"]: p for p in extract(blob)}

    def passage(pid, terms):
        p = passages[pid]
        if not all(t in p["text"] for t in terms):
            raise ValueError("Capital claim passage terms differ")
        return dict(
            p, sourceHash=sha, sourceFile=source["file"], sourceUrl=source["url"]
        )

    if c["id"] == "018260":
        dims = [
            ("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")
        ]
        carrying = select(rows, "ConvertibleBondsNet", None, "2026-06-30", dims, "KRW")
        principal = select(
            rows,
            "ConvertibleBondsNet",
            None,
            "2026-06-30",
            dims
            + [
                (
                    "CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis",
                    "GrossCarryingAmountMember",
                )
            ],
            "KRW",
        )
        if (
            not carrying
            or not principal
            or carrying["value"] != 1092677876058
            or principal["value"] != 1220000000000
            or any(r["accession"] != receipt for r in [carrying, principal])
            or any(
                r["sourceHash"]
                != "6f1283bfa55a5abdde211405b2d25eca94a2b9fba415a3ddded4c9e589acc5e6"
                for r in [carrying, principal]
            )
        ):
            raise ValueError("SDS current consolidated convertible amounts differ")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
            soup = BeautifulSoup(blob, "html.parser")
        tables = [t.get_text(" ", strip=True) for t in soup.find_all("table")]
        terms = next(
            (
                t
                for t in tables
                if all(
                    s in t
                    for s in [
                        "권면총액(원) 1,220,000,000,000",
                        "이자율(%) 2.5",
                        "대상주식수(주) 6,777,777",
                        "전환가액(원) 180,000",
                        "발행일 2026년 04월 30일",
                        "만기일 2032년 04월 30일",
                    ]
                )
            ),
            None,
        )
        if not terms:
            raise ValueError("SDS issued convertible contract table missing")
        selected = [
            passage("38b15740be840b4082b0", ["삼성에스디에스 주식회사 기명식 보통주"]),
            passage("dab5105505f9dd6d3a12", ["2027년 4월 30일", "2032년 4월 23일"]),
            passage("39576cbdfad00528cc7a", ["원금의 100%", "2032년 4월 30일"]),
            passage("ad6ce6f13fbb0713ef6a", ["기한의 이익 상실", "서면합의"]),
        ]
        detail = dict(
            title="삼성SDS 발행 전환사채 · 상환과 전환의 별도 경로",
            principal=principal["value"],
            carryingAmount=carrying["value"],
            couponRate=0.025,
            disclosedConversionPrice=180000,
            disclosedPotentialShares=6777777,
            conversionStart="2027-04-30",
            conversionEnd="2032-04-23",
            maturity="2032-04-30",
            actualConvertedSharesAtPriceDate=None,
            adjustedConversionPriceAtPriceDate=None,
            termsTable=terms,
            facts=[carrying, principal],
            observations=[
                dict(
                    label="발행 원금 / 연결 부채 장부금액",
                    value="1.220조 / 1.092678조 원",
                    scope="부채 할인과 자본요소를 포함한 계약을 원금과 구분",
                ),
                dict(
                    label="공시 전환가액 / 전환 대상 수량",
                    value="180,000원 / 6,777,777주",
                    scope="현재 유통주식수에 더하지 않음. 가격 기준일 조정 조건 미대사",
                ),
                dict(
                    label="표면이율 / 만기",
                    value="연 2.5% / 2032-04-30",
                    scope="미전환·미상환 원금 100% 상환. 전환과 원금 상환을 같은 경로에서 중복 차감하지 않음",
                ),
                dict(
                    label="전환 청구 기간",
                    value="2027-04-30–2032-04-23",
                    scope="현재 종가가 전환가액을 넘는다는 이유로 이미 전환한 것으로 처리하지 않음",
                ),
            ],
            issue="삼성SDS 전환사채의 이자·미전환 상환·전환 희석과 가격 기준일 조정 조건을 대사해야 함",
            scope="정관상 발행 한도가 아닌 실제 발행 계약입니다. 현재 보통주 수량은 보존하되, 전환 여부·시점·가액 조정과 상환 재원을 사업 현금에 연결하기 전 주당 가격을 보류합니다. 조기상환권 제한에도 계약상 기한이익 상실·서면합의 예외가 있습니다.",
        )
    else:
        selected = [
            passage(
                "277ce09abd11c8222de1", ["7 million and 13 million", "Escrowed Shares"]
            ),
            passage(
                "010e0f5769d1a3d05953",
                ["143 million", "71 million", "contingently issuable"],
            ),
            passage(
                "68c1a1aaa24754de16a5",
                ["241 million", "$20.00", "51%", "net cash or net shares"],
            ),
        ]
        detail = dict(
            title="Intel 정부 워런트·에스크로 주식 · 조건부 현금과 희석",
            maximumWarrantShares=241000000,
            warrantExercisePrice=20,
            escrowUnreleasedRoundedShares=143000000,
            actualWarrantExerciseAtPriceDate=None,
            facts=[],
            observations=[
                dict(
                    label="정부 워런트",
                    value="최대 241,000,000주 / $20",
                    scope="파운드리 지분을 직·간접으로 51% 이상 보유하지 않게 될 때 행사 가능",
                ),
                dict(
                    label="행사 시 정산 선택",
                    value="순현금 또는 순주식",
                    scope="최대 수량을 현재 유통주식에 더하거나 실제 현금 지급액으로 처리하지 않음",
                ),
                dict(
                    label="미해제 에스크로 주식",
                    value="약 143,000,000주",
                    scope="공시상 두 약 71백만 주 범주의 합과 반올림 차이를 보존. 기본 EPS 포함 여부와 실제 유통 수량은 별도",
                ),
                dict(
                    label="당기 해제 수량",
                    value="분기 약 7백만 / 반기 약 13백만 주",
                    scope="겹치는 기간이므로 두 수량을 더하지 않음. 가격 기준일까지 후속 해제 미대사",
                ),
            ],
            issue="Intel 정부 워런트의 순현금·순주식 정산과 에스크로 후속 해제·유통 수량을 대사해야 함",
            scope="결산일 미행사와 EPS상 반희석 제외는 권리 소멸이 아닙니다. 원문에 제시된 조건과 반올림 수량을 보존하며 주당 가격을 보류합니다. 워런트 최대 수량·에스크로·공시 유통 수량을 중복 합산하지 않습니다.",
        )
    if source["file"] not in {s["file"] for s in c["sources"]}:
        c["sources"].append(source)
    result = dict(
        version="parent-capital-claims-v1",
        status="conditional_rights_unresolved",
        accession=receipt,
        sourceHash=sha,
        sourceUrl=source["url"],
        filedAt=core["filedAt"],
        observedAt=core["end"],
        priceDate=c["priceSummary"]["lastDate"],
        passages=selected,
        **detail,
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
