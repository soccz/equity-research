"""Append-only research revisions and company-specific observation contracts."""

from datetime import datetime
from zoneinfo import ZoneInfo
from .data import ROOT, canonical, digest
from . import ledger

PATH = ROOT / "data/ledger/research-journal.jsonl"


def evaluate(record, company):
    f = company["financials"]
    local_day = (
        datetime.fromisoformat(record["recordedAt"])
        .astimezone(
            ZoneInfo("Asia/Seoul" if company["market"] == "KR" else "America/New_York")
        )
        .date()
        .isoformat()
    )
    base = dict(predictionCorrect=None)
    if f["end"] <= record["periodEnd"] or f["filedAt"] <= local_day:
        return dict(
            base, status="pending", reason="등록일 이후 새로운 기간의 공시 대기"
        )
    if record["investmentScope"] != company["investmentScope"]:
        return dict(base, status="unresolved", reason="투자자산 취득 정의가 달라짐")
    condition = record["condition"]
    if condition["metric"] == "cashMarginChange":
        value = company["metrics"].get("cashMarginChange")
    elif condition["metric"] == "segmentMarginChange":
        segment = next(
            (
                s
                for s in company.get("researchCase", {}).get("segments", [])
                if s["id"] == condition["segmentId"]
            ),
            None,
        )
        value = segment["marginChange"] if segment else None
        previous_segments = record.get("segmentIds", [])
        current_segments = [
            s["id"] for s in company.get("researchCase", {}).get("segments", [])
        ]
        if previous_segments != current_segments:
            return dict(
                base, status="unresolved", reason="보고 부문 구성·범위 변화 확인 필요"
            )
    else:
        return dict(base, status="unresolved", reason="지원되지 않은 관측 조건")
    if value is None:
        return dict(
            base, status="unresolved", reason="같은 범위·전년 동기 비교 자료 미확인"
        )
    return dict(
        base,
        status="met" if value > condition["baseline"] else "not_met",
        value=value,
        filedAt=f["filedAt"],
        periodEnd=f["end"],
        source=f["current"]["cfo"]["sourceUrl"],
    )


def register(snapshot, path=PATH):
    rows = ledger.read(path)
    added = []
    for c in snapshot["companies"]:
        case = c.get("researchCase")
        if c.get("status") != "ready" or not case:
            continue
        histories = [r for r in rows if r["type"] == "case" and r["company"] == c["id"]]
        old = histories[-1] if histories else None
        if not old or old["case"]["evidenceHash"] != case["evidenceHash"]:
            event = dict(
                type="case",
                eventId="case:"
                + c["id"]
                + ":"
                + digest(
                    canonical([case["evidenceHash"], old["hash"] if old else None])
                ),
                company=c["id"],
                snapshotHash=snapshot["contentHash"],
                previousRevisionHash=old["hash"] if old else None,
                case=case,
                basis=dict(
                    period=[c["financials"]["start"], c["financials"]["end"]],
                    filedAt=c["financials"]["filedAt"],
                    accession=c["financials"]["current"]["cfo"]["accession"],
                    metrics=c["metrics"],
                    price=c["priceSummary"]["close"],
                    priceDate=c["priceSummary"]["lastDate"],
                ),
            )
            saved = ledger.append(path, event)
            added.append(saved)
            rows.append(saved)
        for condition in case["watch"]:
            event_id = ":".join(
                ["watch", c["id"], c["financials"]["end"], condition["id"]]
            )
            if any(r["eventId"] == event_id for r in rows):
                continue
            saved = ledger.append(
                path,
                dict(
                    type="watch",
                    eventId=event_id,
                    company=c["id"],
                    periodEnd=c["financials"]["end"],
                    filedAt=c["financials"]["filedAt"],
                    snapshotHash=snapshot["contentHash"],
                    caseHash=case["evidenceHash"],
                    investmentScope=c["investmentScope"],
                    condition=condition,
                    segmentIds=[s["id"] for s in case["segments"]],
                    expected=None,
                ),
            )
            rows.append(saved)
            added.append(saved)
    # Only the first eligible observation is locked; re-runs cannot rewrite it.
    for r in rows[:]:
        if r["type"] != "watch" or any(
            x.get("registrationHash") == r["hash"] for x in rows
        ):
            continue
        c = next(
            (
                c
                for c in snapshot["companies"]
                if c["id"] == r["company"] and c["status"] == "ready"
            ),
            None,
        )
        if not c:
            continue
        observation = evaluate(r, c)
        if observation["status"] not in ("met", "not_met"):
            continue
        saved = ledger.append(
            path,
            dict(
                type="observation",
                eventId="observed:" + r["hash"],
                registrationHash=r["hash"],
                company=r["company"],
                snapshotHash=snapshot["contentHash"],
                **observation
            ),
        )
        rows.append(saved)
        added.append(saved)
    return added


def payload(snapshot, path=PATH):
    rows = ledger.read(path)
    companies = {c["id"]: c for c in snapshot["companies"] if c["status"] == "ready"}
    observations = {
        r["registrationHash"]: r for r in rows if r["type"] == "observation"
    }
    return dict(
        scope="로컬 해시 연결 기록. 외부 타임스탬프 인증·사전 수익 예측이 아님",
        history=[r for r in rows if r["type"] == "case"],
        watches=[
            dict(
                registration=r,
                observation=observations.get(r["hash"])
                or (
                    evaluate(r, companies[r["company"]])
                    if r["company"] in companies
                    else dict(
                        status="unresolved",
                        reason="기업 공시 미확인",
                        predictionCorrect=None,
                    )
                ),
                persisted=r["hash"] in observations,
            )
            for r in rows
            if r["type"] == "watch"
        ],
    )
