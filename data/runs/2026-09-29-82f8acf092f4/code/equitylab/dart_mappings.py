"""Reviewed issuer extensions, bound to an exact filing and original caption."""

from .data import ROOT, read_verified

KT_TAG = "AcquisitionOfIntangibleAssetAndInvestmentPropertyOfCashFlowsFromUsedInInvestingActivities"
KT_CURRENT = {
    "ticker": "030200",
    "accession": "20260814003463",
    "sha256": "1c2fd7198950dcd4ea0a4cc9df6c6379448bca9296f7499ebb6fb30643c4b6a5",
    "namespace": "http://dart.fss.or.kr/taxonomy/2026-06-30/entity00190321",
    "source": {
        "provider": "DART",
        "file": "data/sources/dart-document-20260814003463-0-2b1798a46d13c8a2.xml",
        "sha256": "2b1798a46d13c8a2ea8214fd679953ca3400b56966e2ea185519b5f65ee2ac6a",
        "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814003463",
        "retrievedAt": "2026-10-01T10:24:35.897799+00:00",
    },
    "caption": "유형자산및투자부동산의 취득 (1,184,005) (2,029,371)",
}
KT_ANNUAL = {
    "ticker": "030200",
    "accession": "20260323001553",
    "sha256": "eb264090e629bc0c9b34315e6a58eacc3d5ad9a5e6e09230cae71951af9c0c9a",
    "namespace": "http://dart.fss.or.kr/taxonomy/2025-12-31/entity00190321",
    "source": {
        "provider": "DART",
        "file": "data/sources/dart-document-20260323001553-2-e380270546616845.xml",
        "sha256": "e3802705466168454d966dbaa3c8674f36c1f996ad3680e8f9e1a12cc5fbd723",
        "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260323001553",
        "retrievedAt": "2026-10-01T10:26:31.024891+00:00",
    },
    "caption": "유형자산및투자부동산의 취득 (3,596,545) (2,909,481) (3,692,972)",
}


def reviewed(item):
    contract = next(
        (
            c
            for c in (KT_CURRENT, KT_ANNUAL)
            if (item["ticker"], item["filing"]["rcept_no"])
            == (c["ticker"], c["accession"])
        ),
        None,
    )
    if contract is None:
        return {}
    if item["sha256"] != contract["sha256"]:
        raise ValueError("Reviewed DART extension source changed")
    from .narrative import extract

    source = contract["source"]
    passages = extract(read_verified(ROOT / source["file"], source["sha256"]))
    found = [p for p in passages if p["text"] == contract["caption"]]
    if len(found) != 1:
        raise ValueError("Reviewed DART investment caption changed")
    return {
        "{"
        + contract["namespace"]
        + "}"
        + KT_TAG: {
            "metric": "capex",
            "investmentScope": "유형자산·투자부동산 취득",
            "reportedLabel": "유형자산 및 투자부동산의 취득",
            "captionSource": source,
            "captionPassage": found[0],
            "scopeNote": "영문 태그는 intangible로 표기하지만 한국어 원 보고서와 라벨은 유형자산·투자부동산이다. 무형 취득은 별도 항목이다. 순수 설비투자와 같은 범위로 비교하지 않는다.",
        }
    }
