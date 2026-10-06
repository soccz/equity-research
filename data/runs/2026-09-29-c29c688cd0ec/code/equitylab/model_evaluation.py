"""Small, authored development evaluation; never an accuracy or alpha claim."""

from datetime import datetime, timezone
import json
from .data import ROOT, canonical, digest
from . import reasoning

SUITE = ROOT / "data/evaluation/local-claims-v1.json"


def evaluate(
    client,
    model,
    *,
    protocol=None,
    suite_path=None,
    archive_name="local-evaluations",
    fail_fast=True
):
    from .local_ai import ask_recorded
    from . import reasoning as default_reasoning

    reasoning = protocol or default_reasoning
    if archive_name not in (
        "local-evaluations",
        "coverage-evaluations",
        "coverage-transfer-evaluations",
    ):
        raise ValueError("Unknown evaluation archive")

    suite_bytes = (suite_path or SUITE).read_bytes()
    suite = json.loads(suite_bytes)
    model_info = client.model(model)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "data" / archive_name / stamp
    out.mkdir(parents=True, exist_ok=False)
    (out / "suite.json").write_bytes(suite_bytes)
    protocol = {
        "suiteHash": digest(suite_bytes),
        "protocolHash": reasoning.protocol_hash(),
        "model": model,
        "modelDigest": model_info["digest"],
        "inferenceConfig": client.inference_config,
        "system": reasoning.SYSTEM,
        "task": reasoning.REVIEW_TASK,
        "gate": suite["gate"],
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "failFast": fail_fast,
    }
    (out / "protocol.json").write_bytes(canonical(protocol))
    rows = []
    for case in suite["cases"]:
        item = {k: case[k] for k in ("id", "role", "text")}
        row = dict(
            case=case["id"],
            role=case["role"],
            expectedAccept=case["accept"],
            expectedClassification=case["expected"],
            status="failed",
        )
        try:
            result, timing = ask_recorded(
                client,
                model,
                out,
                case["id"],
                reasoning.SYSTEM,
                reasoning.REVIEW_TASK,
                {"input": case.get("input", suite.get("input")), "items": [item]},
                reasoning.review_schema([item]),
            )
            reasoning.validate_assessments(result, [item])
            a = result["assessments"][0]
            row.update(
                status="completed",
                accepted=reasoning.accepted(a, case["role"], case["text"]),
                modelAccepted=reasoning.model_accepted(a, case["role"]),
                styleFindings=reasoning.style_findings([item]),
                assessment=a,
                runtime=timing,
            )
        except Exception as exc:
            row["error"] = type(exc).__name__ + ": " + str(exc)[:400]
        rows.append(row)
        with (out / "progress.jsonl").open("ab") as stream:
            stream.write(canonical(row) + b"\n")
        print(
            "Evaluation "
            + case["id"]
            + ": "
            + row["status"]
            + " "
            + str(row.get("accepted")),
            flush=True,
        )
        # One malformed/truncated response already violates the frozen runtime gate.
        # Stop the costly profile and preserve partial progress, never mark it complete.
        if row["status"] == "failed" and fail_fast:
            break
    complete = len(rows) == len(suite["cases"])
    safe = [r for r in rows if r["expectedAccept"]]
    unsafe = [r for r in rows if not r["expectedAccept"]]
    counts = dict(
        total=len(rows),
        plannedTotal=len(suite["cases"]),
        shouldAccept=len(safe),
        shouldReject=len(unsafe),
        falseAccepts=sum(r.get("accepted") is True for r in unsafe),
        falseRejects=sum(r.get("accepted") is False for r in safe),
        modelFalseAccepts=sum(r.get("modelAccepted") is True for r in unsafe),
        modelFalseRejects=sum(r.get("modelAccepted") is False for r in safe),
        styleBlocks=sum(bool(r.get("styleFindings")) for r in rows),
        invalidResponses=sum(r["status"] == "failed" for r in rows),
        exactClassifications=sum(
            r.get("assessment", {}).get("classification") == r["expectedClassification"]
            for r in rows
        ),
    )
    gate = suite["gate"]
    passed = (
        complete
        and counts["falseAccepts"] <= gate["maxFalseAccepts"]
        and counts["falseRejects"] <= gate["maxFalseRejects"]
        and counts["invalidResponses"] <= gate["maxInvalidResponses"]
    )
    report = dict(
        **protocol,
        completedAt=datetime.now(timezone.utc).isoformat(),
        scope=suite["scope"],
        status="completed" if complete else "incomplete",
        gatePassed=passed,
        counts=counts,
        rows=rows,
        independentReview=False,
        loadedModels=client.call("ps").get("models", [])
    )
    report["recordHash"] = digest(canonical(report))
    path = out / "evaluation.json"
    path.write_bytes(canonical(report))
    pointer = out.parent / "latest.json"
    temp = pointer.with_suffix(".tmp")
    temp.write_bytes(
        canonical({"file": str(path.relative_to(ROOT)), "hash": report["recordHash"]})
    )
    temp.replace(pointer)
    return report


def read_evaluation(archive_name="local-evaluations"):
    if archive_name not in (
        "local-evaluations",
        "coverage-evaluations",
        "coverage-transfer-evaluations",
    ):
        raise ValueError("Unknown evaluation archive")
    root = ROOT / "data" / archive_name
    pointer = root / "latest.json"
    if not pointer.exists():
        return None
    p = json.loads(pointer.read_text())
    path = (ROOT / p["file"]).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Evaluation pointer outside archive")
    result = json.loads(path.read_text())
    if (
        digest(canonical({k: v for k, v in result.items() if k != "recordHash"}))
        != p["hash"]
        or result["recordHash"] != p["hash"]
    ):
        raise ValueError("Evaluation integrity mismatch")
    return result


def gate_for(
    model_digest,
    inference_config,
    *,
    protocol=None,
    suite_path=None,
    archive_name="local-evaluations"
):
    from . import reasoning as default_reasoning

    reasoning = protocol or default_reasoning
    result = read_evaluation(archive_name)
    if (
        not result
        or result["modelDigest"] != model_digest
        or result.get("inferenceConfig") != inference_config
        or result["protocolHash"] != reasoning.protocol_hash()
        or result["suiteHash"] != digest((suite_path or SUITE).read_bytes())
    ):
        return {"status": "missing_or_stale", "passed": False}
    gate = {
        "status": "passed" if result["gatePassed"] else "failed",
        "passed": result["gatePassed"],
        "recordHash": result["recordHash"],
        "counts": result["counts"],
        "completion": result["status"],
        "scope": result["scope"],
    }
    if archive_name == "coverage-evaluations" and hasattr(reasoning, "TRANSFER_SUITE"):
        transfer = gate_for(
            model_digest,
            inference_config,
            protocol=reasoning,
            suite_path=reasoning.TRANSFER_SUITE,
            archive_name="coverage-transfer-evaluations",
        )
        gate["transfer"] = transfer
        gate["passed"] = gate["passed"] and transfer["passed"]
        gate["status"] = "passed" if gate["passed"] else "failed_or_incomplete"
    return gate
