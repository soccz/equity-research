"""Authored business readings tied to exact current filing passages."""

import json
from .data import ROOT, canonical, digest
from .narrative import load


def build(c):
    path = ROOT / "data/business-insights.json"
    if not path.exists():
        return None
    case = next(
        (r for r in json.loads(path.read_text())["cases"] if r["company"] == c["id"]),
        None,
    )
    if case is None:
        return None
    meta = c.get("narrative", {})
    if (
        meta.get("status") != "ready"
        or case["accession"] != meta["accession"]
        or case["corpusHash"] != meta["evidenceHash"]
    ):
        return dict(
            status="stale",
            reason="현재 공시 본문이 달라 사업 해석 초안의 근거를 다시 확인해야 합니다.",
        )
    body = load(c)
    passages = {p["id"]: p for p in body["passages"]}
    if len(set(case["passageIds"])) != len(case["passageIds"]) or any(
        id not in passages for id in case["passageIds"]
    ):
        raise ValueError("Business reading refers to an unknown or duplicate passage")
    result = dict(
        status="source_draft",
        **case,
        sources=[
            dict(
                id=id,
                sourceUrl=passages[id]["sourceUrl"],
                sourceHash=passages[id]["sourceHash"],
                ordinal=passages[id]["ordinal"],
            )
            for id in case["passageIds"]
        ],
        filedAt=meta["filedAt"],
        period=meta["period"],
        scope="회사 설명과 이를 읽은 연구 해석·반론을 구분합니다. 로컬 모델 생성문이나 독립 금융 심사 결과가 아닙니다."
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
