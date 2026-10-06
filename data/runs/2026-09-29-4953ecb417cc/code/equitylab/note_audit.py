"""Exact-record review holds: retain model errors without rewriting its output."""

from .data import ROOT, canonical, digest
from . import ledger

PATH = ROOT / "data/ledger/model-note-holds.jsonl"
ROLES = {"hypothesis", "alternative", "distinguish", "missing"}


def hold(record, role, reason, reviewer, path=PATH):
    if role not in ROLES or not record.get("notes", {}).get(role):
        raise ValueError("Select a sentence in a completed archived model record")
    if not reason.strip() or not reviewer.strip():
        raise ValueError("A concrete reason and identified reviewer are required")
    if (
        digest(canonical({k: v for k, v in record.items() if k != "recordHash"}))
        != record["recordHash"]
    ):
        raise ValueError("Audit requires the unchanged original model record")
    event = dict(
        type="model_note_hold",
        company=record["company"],
        recordHash=record["recordHash"],
        evidenceHash=record["evidenceHash"],
        role=role,
        quote=record["notes"][role],
        reason=reason.strip(),
        reviewer=reviewer.strip(),
        independentFinancialApproval=False,
    )
    event["eventId"] = "model-note-hold:" + digest(canonical(event))
    return ledger.append(path, event)


def findings(record, path=PATH):
    result = []
    for row in ledger.read(path):
        if row["recordHash"] != record["recordHash"]:
            continue
        if (
            row["company"] != record["company"]
            or row["evidenceHash"] != record["evidenceHash"]
            or row["role"] not in ROLES
            or row["quote"] != record["notes"][row["role"]]
        ):
            raise ValueError(
                "Recorded review hold no longer matches the original sentence"
            )
        result.append(row)
    return result
