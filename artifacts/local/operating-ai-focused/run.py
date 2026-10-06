"""Frozen, source-quoted local assumption pilot; never publishes generated advice."""
from pathlib import Path
from datetime import datetime, timezone
import json
import sys
import copy
import importlib.util

ROOT = Path(__file__).resolve().parents[3]
STAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(STAGE))
import protocol
from equitylab.data import canonical, digest
from equitylab.local_ai import ask_recorded
from equitylab import coverage_reasoning as base


def main():
    frozen = json.loads((STAGE / "frozen.json").read_text())
    if digest(Path(__file__).read_bytes()) != frozen["runnerHash"]:
        raise ValueError("Frozen runner changed")
    if protocol.protocol_hash() != frozen["protocolHash"]:
        raise ValueError("Frozen protocol changed")
    run = json.loads((ROOT / frozen["productionRun"]).read_text())
    if run["status"] != "artifacts_verified" or run["snapshotHash"] != frozen["snapshotHash"]:
        raise ValueError("Production snapshot verification is incomplete")
    suite = json.loads((STAGE / "suite.json").read_text())
    if digest((STAGE / "suite.json").read_bytes()) != frozen["suiteHash"]:
        raise ValueError("Frozen suite changed")
    packets = {i: json.loads((STAGE / (i + "-input.json")).read_text()) for i in frozen["inputs"]}
    if any(digest(canonical(p)) != frozen["inputs"][i] for i, p in packets.items()):
        raise ValueError("Frozen input changed")
    out = STAGE / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out.mkdir()
    for name in ["protocol.py", "run.py", "freeze.py", "suite.json", "frozen.json", *[i + "-input.json" for i in packets]]:
        (out / name).write_bytes((STAGE / name).read_bytes())
    report = dict(status="running", startedAt=datetime.now(timezone.utc).isoformat(), frozen=frozen, externalAIUsed=False, independentReview=False, financialApproval=False, scope="Same-author focused development examples and real issuer drafts. No independent accuracy estimate or automatic production adoption.", evaluation=[], companies=[])

    def save():
        (out / "result.json").write_bytes(canonical(report))

    spec = importlib.util.spec_from_file_location("focused_runtime", ROOT / "scripts/local-research.py")
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    save()
    try:
        with runtime.runtime(thinking=True, model="qwen3:8b", go_template=False, wait_gpu_seconds=600) as client:
            client.inference_config["options"]["num_ctx"] = 8192
            report.update(modelDigest=client.model("qwen3:8b")["digest"], inferenceConfig=copy.deepcopy(client.inference_config))
            save()
            p = packets["TXN"]
            draft, timing = ask_recorded(client, "qwen3:8b", out, "actual-packet-format-probe", protocol.SYSTEM, protocol.TASK, p, protocol.schema(p))
            protocol.validate(draft, p)
            report["formatProbe"] = dict(status="passed", notes=draft, runtime=timing)
            save()
            for case in suite["cases"]:
                item = {k: case[k] for k in ["id", "role", "text"]}
                row = dict(id=case["id"], expectedAccept=case["accept"], status="failed")
                try:
                    result, timing = ask_recorded(client, "qwen3:8b", out, case["id"], protocol.SYSTEM, protocol.REVIEW_TASK, dict(input=packets[case["company"]], items=[item]), base.review_schema([item]))
                    base.validate_assessments(result, [item])
                    assessment = result["assessments"][0]
                    row.update(status="completed", assessment=assessment, accepted=base.accepted(assessment, case["role"], case["text"]), modelAccepted=base.model_accepted(assessment, case["role"]), runtime=timing)
                except Exception as exc:
                    row["error"] = type(exc).__name__ + ": " + str(exc)[:500]
                report["evaluation"].append(row)
                save()
                print("Evaluation", case["id"], row["status"], row.get("accepted"), flush=True)
            rows = report["evaluation"]
            counts = dict(falseAccepts=sum(x.get("accepted") is True for x in rows if not x["expectedAccept"]), falseRejects=sum(x.get("accepted") is False for x in rows if x["expectedAccept"]), invalid=sum(x["status"] == "failed" for x in rows), total=len(rows))
            report["evaluationSummary"] = dict(counts=counts, gatePassed=counts["falseAccepts"] == 0 and counts["falseRejects"] <= 1 and counts["invalid"] == 0, independentReview=False, financialApproval=False)
            save()
            for ident, p in packets.items():
                row = dict(company=ident, status="failed", rounds=[], financialApproval=False)
                try:
                    draft, timing = ask_recorded(client, "qwen3:8b", out, ident + "-draft", protocol.SYSTEM, protocol.TASK, p, protocol.schema(p))
                    protocol.validate(draft, p)
                    row.update(notes=draft, runtime=timing)
                    assessments = []
                    for item in protocol.items(draft):
                        result, timing = ask_recorded(client, "qwen3:8b", out, ident + "-review-" + item["id"], protocol.SYSTEM, protocol.REVIEW_TASK, dict(input=p, items=[item]), base.review_schema([item]))
                        base.validate_assessments(result, [item])
                        assessments.extend(result["assessments"])
                        row["rounds"].append(dict(item=item, scrutiny=result, runtime=timing))
                    row["status"] = "reviewed_pilot" if base.all_accepted(dict(assessments=assessments), protocol.items(draft)) else "revision_required"
                except Exception as exc:
                    row["error"] = type(exc).__name__ + ": " + str(exc)[:500]
                report["companies"].append(row)
                save()
                print("Company", ident, row["status"], flush=True)
            report["loadedModels"] = client.call("ps").get("models", [])
            report["status"] = "completed"
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = type(exc).__name__ + ": " + str(exc)[:500]
        raise
    finally:
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        save()
        print("Pilot archive", out.relative_to(ROOT), flush=True)


if __name__ == "__main__":
    main()
