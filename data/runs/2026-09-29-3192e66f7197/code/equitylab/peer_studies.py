"""Paired business research with both companies' exact filing evidence."""

import json
from .data import ROOT, canonical, digest
from .narrative import load


def build(companies):
    path = ROOT / "data/peer-studies.json"
    if not path.exists():
        return []
    company_map = {c["id"]: c for c in companies}
    results = []
    for study in json.loads(path.read_text())["studies"]:
        if len(study["sides"]) != 2 or len({s["company"] for s in study["sides"]}) != 2:
            raise ValueError("Paired study needs two distinct companies")
        sides, issues = [], []
        for spec in study["sides"]:
            c = company_map.get(spec["company"], {})
            meta = c.get("narrative") or {}
            if (
                meta.get("status") != "ready"
                or meta.get("accession") != spec["accession"]
                or meta.get("evidenceHash") != spec["corpusHash"]
            ):
                issues.append(
                    spec["company"] + ": current source selection needs review"
                )
                continue
            ps = {p["id"]: p for p in load(c)["passages"]}
            ids = spec["passageIds"]
            if not ids or len(set(ids)) != len(ids) or any(i not in ps for i in ids):
                raise ValueError("Paired study has unknown or duplicate passage")
            sides.append(
                dict(
                    **spec,
                    sourcePeriod=meta["period"],
                    filedAt=meta["filedAt"],
                    sources=[ps[i] for i in ids]
                )
            )
        r = dict(
            **study,
            status="stale" if issues else "source_draft",
            issues=issues,
            financialApproval=False,
            scope="양쪽 공시의 사업 설명을 대조한 작성자 연구 초안. 연결 비율의 순위나 상대 투자 선호의 승인과 구분합니다."
        )
        # Preserve both company identities even if one updated filing is missing.
        if not issues:
            r["sides"] = sides
            if study["id"] == "innovator-biosimilar":
                from .pharma_comparison import build as pharma_comparison

                r["pharmaComparison"] = pharma_comparison(
                    company_map["JNJ"],
                    company_map["068270"],
                    company_map["JNJ"]["financials"]["availableAsOf"],
                )
        r["evidenceHash"] = digest(canonical(r))
        from .operating_comparison import build as operating_comparison

        r["operatingComparison"] = operating_comparison(r, company_map)
        results.append(r)
    return results
