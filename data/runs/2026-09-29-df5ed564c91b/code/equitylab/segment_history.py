"""Source-bound annual + current YTD - prior YTD operating-segment bridges."""

import json
import re
from html import unescape
import xml.etree.ElementTree as ET
from .data import ROOT, canonical, digest, read_verified
from .narrative import load
from .xbrl import company_filing, instance_rows, select
from .segment_profiles import PROFILES


def build(c, as_of):
    business = c.get("business") or {}
    trailing = c.get("trailingYear") or {}
    if (
        not business.get("segments")
        or trailing.get("method") != "annual_plus_current_less_prior"
    ):
        return None
    contract = json.loads((ROOT / "data/segment-continuity.json").read_text())
    review = next((r for r in contract["cases"] if r["company"] == c["id"]), None)
    if review is None:
        return dict(
            status="definition_review_required",
            reason="현재와 직전 연간 공시의 사업부 정의·문맥 대사가 남아 있습니다. 누적 수치를 임의로 연율화하지 않습니다.",
        )
    meta = c.get("narrative") or {}
    annual_core = trailing["values"]["revenue"]["components"][0]["fact"]
    if (
        review["currentAccession"] != meta.get("accession")
        or review["corpusHash"] != meta.get("evidenceHash")
        or review["annualAccession"] != annual_core["accession"]
    ):
        return dict(
            status="definition_review_required",
            reason="공시 변경으로 기존 사업부 기간 연결 검토가 만료됐습니다.",
        )
    if annual_core["filedAt"] > as_of:
        raise ValueError("Future annual segment source")
    corpus = load(c)
    index = {p["id"]: p for p in corpus["passages"]}
    if any(i not in index for i in review["currentPassageIds"]):
        raise ValueError("Missing current segment definition evidence")
    source = review["annualSource"]
    if source["accession"] != annual_core["accession"] or source["cik"] != c["cik"]:
        raise ValueError("Annual segment manifest identity mismatch")
    blob = read_verified(ROOT / source["file"], source["sha256"])
    paragraphs = set()
    for e in ET.fromstring(blob):
        if e.tag.split("}")[-1] == review["annualTextTag"]:
            paragraphs.add(
                re.sub(
                    r"\s+", " ", unescape(re.sub("<[^>]+>", " ", e.text or ""))
                ).strip()
            )
    text = next(
        (t for t in paragraphs if digest(t.encode()) == review["annualTextHash"]), None
    )
    if text is None:
        raise ValueError("Annual segment definition text changed")
    annual_rows = instance_rows(
        blob, c, source, annual_core["accession"], annual_core["filedAt"]
    )
    _, current_rows = company_filing(c, as_of)
    for item in [source, source.get("indexSource")]:
        if item:
            item = dict(item)
            item.setdefault("provider", "SEC")
            item.setdefault("retrievedAt", source["retrievedAt"])
            read_verified(ROOT / item["file"], item["sha256"])
            if item["file"] not in {s["file"] for s in c["sources"]}:
                c["sources"].append(item)
    f, config = c["financials"], PROFILES[c["id"]]
    periods = [
        (1, "직전 연간", annual_core["start"], annual_core["end"], annual_rows),
        (1, "당기 누적", f["start"], f["end"], current_rows),
        (-1, "전년 누적", f["priorStart"], f["priorEnd"], current_rows),
    ]

    def combine(tag, dims):
        components = []
        for coefficient, label, start, end, rows in periods:
            selected_tag, factor = tag, 1
            context = (
                [
                    (axis, review["dimensionAliases"].get(member, member))
                    for axis, member in dims
                ]
                if rows is annual_rows
                else dims
            )
            if rows is annual_rows:
                for override in review.get("annualFactOverrides", []):
                    if override["tag"] == tag and sorted(
                        map(tuple, override["dimensions"])
                    ) == sorted(dims):
                        selected_tag = override["sourceTag"]
                        context = list(map(tuple, override["sourceDimensions"]))
                        factor = override["coefficient"]
                        label += " · " + override["reason"]
            fact = select(rows, selected_tag, start, end, context, c["currency"])
            if fact is None:
                return None
            components.append(
                dict(coefficient=coefficient * factor, label=label, fact=fact)
            )
        return dict(
            value=sum(p["coefficient"] * p["fact"]["value"] for p in components),
            components=components,
        )

    segments = []
    for s in business["segments"]:
        result = dict(id=s["id"], label=s["label"])
        for metric in ("revenue", "operatingIncome"):
            r = s["current"][metric]
            result[metric] = combine(r["tag"], [tuple(d) for d in r["dimensions"]])
        result["margin"] = (
            result["operatingIncome"]["value"] / result["revenue"]["value"]
            if result["revenue"]
            and result["revenue"]["value"] > 0
            and result["operatingIncome"]
            else None
        )
        segments.append(result)
    reconciliations = {}
    for metric, core, key in [
        ("revenue", "revenue", "revenueAdjustments"),
        ("operatingIncome", "operating_income", "incomeAdjustments"),
    ]:
        adjustments = [
            dict(coefficient=sign, series=combine(tag, dims))
            for tag, dims, sign in config.get(key, [])
        ]
        parts, total = [s[metric] for s in segments], trailing["values"].get(core)
        if (
            any(p is None for p in parts)
            or total is None
            or any(p["series"] is None for p in adjustments)
        ):
            reconciliations[metric] = dict(
                status="unresolved", reason="같은 부문·기간의 필수 수치가 미확인입니다."
            )
            continue
        subtotal = sum(p["value"] for p in parts)
        adjustment = sum(p["coefficient"] * p["series"]["value"] for p in adjustments)
        residual = total["value"] - subtotal - adjustment
        reconciliations[metric] = dict(
            status=(
                "reconciled"
                if abs(residual) <= max(1, abs(total["value"]) * 1e-10)
                else "unresolved_difference"
            ),
            subtotal=subtotal,
            adjustments=adjustments,
            adjustment=adjustment,
            total=total,
            residual=residual,
        )
    result = dict(
        status=(
            "ready"
            if all(r["status"] == "reconciled" for r in reconciliations.values())
            else "partial"
        ),
        start=trailing["start"],
        end=trailing["end"],
        method="annual_plus_current_less_prior",
        segments=segments,
        reconciliations=reconciliations,
        review=dict(
            note=review["note"],
            reviewer=contract["reviewer"],
            scope=contract["scope"],
            annualSource=source,
            annualText=text,
            annualTextHash=review["annualTextHash"],
            currentPassages=[index[i] for i in review["currentPassageIds"]],
        ),
        scope="보고 부문의 최근 1년 합성값이다. 합병·신제품·환율을 제거한 유기 성장이나 정상 이익이 아니며 현금 배분을 뜻하지 않는다.",
    )
    result["evidenceHash"] = digest(canonical(result))
    return result
