"""Prospective accounting-condition tracking, without an invented forecast."""

from datetime import datetime
import math
from zoneinfo import ZoneInfo
from . import ledger
from .data import ROOT, canonical, digest

CONTRACT = dict(
    version="receivable-burden-v1",
    metric="receivableAverageDaysChange",
    operator="<=",
    threshold=0,
    unit="days",
    formula="current ((opening net trade receivables + closing net trade receivables) / 2 / cumulative total revenue * actual period days) minus same-length prior-year equivalent",
    diagnosticVersion="receivables-v1",
    missingPolicy="unresolved_not_zero",
    filingRule="period end and local filing date must both be strictly after registration baseline",
)


def register(snapshot):
    path = ROOT / "data/ledger/conditions.jsonl"
    existing = {r["eventId"] for r in ledger.read(path)}
    registered = []
    for company in snapshot["companies"]:
        d = (company.get("dossier") or {}).get("receivables")
        if not d or d["averageDaysChange"] is None:
            continue
        event_id = f"{CONTRACT['version']}:{company['id']}:{d['current']['end']}"
        if event_id in existing:
            continue
        row = dict(
            eventId=event_id,
            type="registration",
            company=company["id"],
            periodEnd=d["current"]["end"],
            metric=CONTRACT["metric"],
            definition="다음 정기공시의 순매출채권 두 시점 평균 / 누적 총매출 × 기간 일수가 동일 길이 전년 동기보다 증가하지 않음",
            baseline="동일 길이 전년 동기의 대용일수 유지(차이 0일). 실제 회수 개선·악화와 별도인 회계 조건",
            operator=CONTRACT["operator"],
            threshold=CONTRACT["threshold"],
            unit="days",
            contract=CONTRACT,
            contractHash=digest(canonical(CONTRACT)),
            baselineValue=d["averageDaysChange"],
            expected=None,
            snapshotHash=snapshot["contentHash"],
            evidenceHash=company["dossier"]["evidenceHash"],
            cutoff=snapshot["asOf"],
            predictionStatus="방향 예측 미등록 · 조건만 추적",
            timestampProof="로컬 해시 체인 · 외부 시점 인증 없음",
        )
        registered.append(ledger.append(path, row))
    return registered


def evaluate(registration, company):
    unresolved = lambda reason: dict(
        status="unresolved", reason=reason, predictionCorrect=None
    )
    if registration.get("contract") != CONTRACT or registration.get(
        "contractHash"
    ) != digest(canonical(CONTRACT)):
        return unresolved("채권 조건의 정의 또는 버전 불일치")
    d = (company.get("dossier") or {}).get("receivables")
    if not d or d.get("version") != CONTRACT["diagnosticVersion"]:
        return unresolved("같은 정의의 채권 분석 자료 미확인")
    core = d["current"]["revenue"]
    zone = ZoneInfo("Asia/Seoul" if company["market"] == "KR" else "America/New_York")
    day = (
        datetime.fromisoformat(registration["recordedAt"])
        .astimezone(zone)
        .date()
        .isoformat()
    )
    if core["end"] <= registration["periodEnd"] or core["filedAt"] <= day:
        return dict(
            status="pending",
            reason="등록 후 새로운 기간의 정기공시 대기",
            predictionCorrect=None,
        )
    if abs(d["current"]["days"] - d["previous"]["days"]) > 8:
        return unresolved("전년 동기 누적기간 길이 불일치")
    values, sources = [], []
    for p in ("current", "previous"):
        period = d[p]
        facts = [period["balances"][s]["tradeNet"] for s in ("opening", "closing")]
        rev = period["revenue"]
        if any(f is None for f in facts) or rev["value"] <= 0:
            return unresolved("채권 기초·기말 또는 양의 매출 미확보")
        if any(
            f["unit"] != company["currency"] or f["basis"] != "consolidated"
            for f in [*facts, rev]
        ):
            return unresolved("채권과 매출의 통화 또는 연결 범위 불일치")
        if any(f["filedAt"] > core["filedAt"] for f in [*facts, rev]):
            return unresolved("판정 공시일 이후 수정 자료 포함")
        values.append(
            sum(f["value"] for f in facts) / 2 / rev["value"] * period["days"]
        )
        sources.extend([*facts, rev])
    value = values[0] - values[1]
    if (
        not math.isfinite(value)
        or d["averageDaysChange"] is None
        or not math.isclose(value, d["averageDaysChange"], abs_tol=1e-9)
    ):
        return unresolved("저장 지표와 원문 재계산이 일치하지 않음")
    met = value <= 0
    expected = registration.get("expected")
    return dict(
        status="met" if met else "not_met",
        value=value,
        unit="days",
        currentDays=values[0],
        previousDays=values[1],
        filedAt=core["filedAt"],
        periodEnd=core["end"],
        predictionCorrect=None if expected is None else met == expected,
        contractHash=registration["contractHash"],
        evidenceHash=company["dossier"]["evidenceHash"],
        evidence=sources,
        interpretation="잔액/매출 대용일수의 조건 판정. 실제 회수나 투자 성과 판정 아님",
    )
