"""Append-only local condition records, hash chained but not externally timestamped."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import fcntl
from .data import canonical, digest


def verify_records(records: list) -> list:
    previous = "0" * 64
    for row in records:
        payload = {k: v for k, v in row.items() if k != "hash"}
        if payload.get("previousHash") != previous or digest(
            canonical(payload)
        ) != row.get("hash"):
            raise ValueError("Condition ledger integrity failure")
        previous = row["hash"]
    return records


def read(path: Path) -> list:
    if not path.exists():
        return []
    return verify_records(
        [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    )


def append(path: Path, event: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        rows = verify_records(
            [json.loads(line) for line in handle.read().splitlines() if line.strip()]
        )
        same = next((r for r in rows if r["eventId"] == event["eventId"]), None)
        if same:
            if any(same.get(k) != v for k, v in event.items()):
                raise ValueError("Cannot revise an existing ledger event")
            return same
        row = {
            **event,
            "recordedAt": datetime.now(timezone.utc).isoformat(),
            "previousHash": rows[-1]["hash"] if rows else "0" * 64,
        }
        row["hash"] = digest(canonical(row))
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        return row


def evaluate(registration: dict, company: dict) -> dict:
    statement = company["financials"]
    if registration.get("investmentScope") != company.get("investmentScope"):
        return dict(
            status="unresolved",
            reason="투자자산 취득 항목의 정의 변경",
            predictionCorrect=None,
        )
    # Date-only filing metadata cannot establish intra-day ordering: require a later date.
    registration_day = registration["recordedAt"][:10]
    if (
        statement["end"] <= registration["periodEnd"]
        or statement["filedAt"] <= registration_day
    ):
        return dict(
            status="pending",
            reason="등록 후의 새로운 정기공시 대기",
            predictionCorrect=None,
        )
    value = company["metrics"]["cashMarginChange"]
    if value is None:
        return dict(
            status="unresolved",
            reason="동일 길이 전년 동기 자료 미확인",
            predictionCorrect=None,
        )
    met = value > 0
    expected = registration.get("expected")
    return dict(
        status="met" if met else "not_met",
        value=value,
        filedAt=statement["filedAt"],
        periodEnd=statement["end"],
        predictionCorrect=None if expected is None else met == expected,
    )
