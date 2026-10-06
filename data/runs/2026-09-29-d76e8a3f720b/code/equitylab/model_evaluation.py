"""Small, authored development evaluation; never an accuracy or alpha claim."""

from datetime import datetime, timezone
import json
from .data import ROOT, canonical, digest
from . import reasoning

SUITE = ROOT / "data/evaluation/local-claims-v1.json"


def evaluate(client, model):
    from .local_ai import ask_recorded

    suite_bytes = SUITE.read_bytes()
    suite = json.loads(suite_bytes)
    model_info = client.model(model)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "data/local-evaluations" / stamp
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
                {"input": suite["input"], "items": [item]},
                reasoning.review_schema([item]),
            )
            reasoning.validate_assessments(result, [item])
            a = result["assessments"][0]
            row.update(
                status="completed",
                accepted=reasoning.accepted(a, case["role"]),
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
        if row["status"] == "failed":
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


def read_evaluation():
    root = ROOT / "data/local-evaluations"
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


def gate_for(model_digest, inference_config):
    result = read_evaluation()
    if (
        not result
        or result["modelDigest"] != model_digest
        or result.get("inferenceConfig") != inference_config
        or result["protocolHash"] != reasoning.protocol_hash()
        or result["suiteHash"] != digest(SUITE.read_bytes())
    ):
        return {"status": "missing_or_stale", "passed": False}
    return {
        "status": "passed" if result["gatePassed"] else "failed",
        "passed": result["gatePassed"],
        "recordHash": result["recordHash"],
        "counts": result["counts"],
        "completion": result["status"],
        "scope": result["scope"],
    }
