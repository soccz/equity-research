"""Run and archive project-local reasoning for the actual coverage universe."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab import coverage_reasoning as protocol
from equitylab.data import canonical, digest
from equitylab.local_ai import read_reviews, review
from equitylab.model_evaluation import evaluate
from equitylab.pipeline import load_latest, export


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--company", action="append")
    p.add_argument("--evaluate", action="store_true")
    p.add_argument(
        "--evaluate-only",
        action="store_true",
        help="Evaluate this exact inference profile without regenerating company notes",
    )
    p.add_argument("--transfer-evaluate-only", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--model", default="qwen3:8b")
    p.add_argument(
        "--probe-format",
        action="store_true",
        help="Check runtime grammar without running financial reviews",
    )
    p.add_argument(
        "--thinking",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Deliberation by default; each profile requires a matching evaluation",
    )
    p.add_argument(
        "--wait-gpu-seconds",
        type=int,
        default=0,
        help="Wait for other GPU jobs without unloading or stopping them",
    )
    args = p.parse_args()
    snapshot = load_latest()
    companies = [
        c
        for c in snapshot["companies"]
        if c["status"] == "ready" and (not args.company or c["id"] in args.company)
    ]
    if not companies or (
        args.company and set(args.company) - {c["id"] for c in companies}
    ):
        p.error("Select available registered company IDs")
    spec = importlib.util.spec_from_file_location(
        "equity_private_runtime", ROOT / "scripts/local-research.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "artifacts/local" / ("coverage-run-" + stamp + ".json")
    report = dict(
        snapshotHash=snapshot["contentHash"],
        startedAt=datetime.now(timezone.utc).isoformat(),
        status="running",
        externalAIUsed=False,
        model=args.model,
        selected=[c["id"] for c in companies],
        records=[],
    )

    def save():
        out.write_bytes(canonical(report))

    save()
    try:
        with module.runtime(
            thinking=args.thinking,
            model=args.model,
            go_template=False,
            wait_gpu_seconds=args.wait_gpu_seconds,
        ) as client:
            # Preserve room for business evidence even in the faster no-thinking mode.
            client.inference_config["options"]["num_ctx"] = 8192
            installed = client.model(args.model)
            if args.probe_format:
                schema = {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string", "enum": ["LOCAL_FORMAT_OK"]}
                    },
                    "required": ["answer"],
                    "additionalProperties": False,
                }
                value, stats, raw = client.generate(
                    args.model,
                    [
                        {
                            "role": "user",
                            "content": "Explain the meaning of clouds in three paragraphs.",
                        }
                    ],
                    schema,
                    archive=out.with_name(out.stem + "-probe-raw.json"),
                )
                if value != {"answer": "LOCAL_FORMAT_OK"}:
                    raise ValueError("Runtime did not constrain the schema")
                packet = protocol.compact_packet(protocol.input_packet(companies[0]))
                value, stats, raw = client.generate(
                    args.model,
                    [
                        {"role": "system", "content": protocol.SYSTEM},
                        {
                            "role": "user",
                            "content": protocol.DRAFT_TASK
                            + "\n"
                            + json.dumps(packet, ensure_ascii=False),
                        },
                    ],
                    protocol.DRAFT_SCHEMA,
                    archive=out.with_name(out.stem + "-company-probe-raw.json"),
                )
                protocol.validate_notes(
                    protocol.attach_evidence(value, protocol.evidence(companies[0])),
                    protocol.evidence(companies[0]),
                )
                report.update(
                    status="format_probe_passed",
                    inferenceConfig=client.inference_config,
                    probe=value,
                    modelDigest=installed["digest"],
                )
                print("PASS runtime JSON schema constraint", flush=True)
                return
            if args.evaluate or args.evaluate_only:
                result = evaluate(
                    client,
                    args.model,
                    protocol=protocol,
                    suite_path=protocol.SUITE,
                    archive_name="coverage-evaluations",
                    fail_fast=False,
                )
                report["evaluation"] = {
                    k: result[k]
                    for k in ["recordHash", "gatePassed", "status", "counts"]
                }
                save()
                if result["status"] != "completed":
                    raise RuntimeError(
                        "Coverage evaluation incomplete; keep partial evidence"
                    )
                if args.evaluate_only:
                    report["status"] = "completed"
                    report["qualityHeld"] = not result["gatePassed"]
            if args.transfer_evaluate_only or (
                args.evaluate and not args.evaluate_only
            ):
                transfer = evaluate(
                    client,
                    args.model,
                    protocol=protocol,
                    suite_path=protocol.TRANSFER_SUITE,
                    archive_name="coverage-transfer-evaluations",
                    fail_fast=False,
                )
                report["transferEvaluation"] = {
                    k: transfer[k]
                    for k in ["recordHash", "gatePassed", "status", "counts"]
                }
                save()
                if args.transfer_evaluate_only:
                    report["status"] = "completed"
                    report["qualityHeld"] = not transfer["gatePassed"]
            if not (args.evaluate_only or args.transfer_evaluate_only):
                existing = (
                    read_reviews(
                        snapshot, protocol=protocol, archive_name="coverage-reviews"
                    )
                    if args.resume
                    else {}
                )
                for c in companies:
                    old = existing.get(c["id"], {})
                    if (
                        old.get("status") not in (None, "stale", "failed")
                        and old.get("modelDigest") == installed["digest"]
                        and old.get("inferenceConfig") == client.inference_config
                    ):
                        record = old
                        reused = True
                    else:
                        print("Local coverage review: " + c["id"], flush=True)
                        record = review(
                            c,
                            snapshot["contentHash"],
                            client,
                            args.model,
                            protocol=protocol,
                            archive_name="coverage-reviews",
                        )
                        reused = False
                    report["records"].append(
                        dict(
                            company=c["id"],
                            status=record["status"],
                            recordHash=record.get("recordHash"),
                            displayEligible=record.get(
                                "displayEligible", record["status"] == "reviewed_draft"
                            ),
                            reused=reused,
                            error=record.get("error"),
                        )
                    )
                    save()
                    print(
                        json.dumps(report["records"][-1], ensure_ascii=False),
                        flush=True,
                    )
                    # Export finished notes incrementally; every failed attempt stays archived.
                    if not reused:
                        export(load_latest())
                export(load_latest())
                report["status"] = (
                    "completed"
                    if all(r["status"] != "failed" for r in report["records"])
                    else "partial_failure"
                )
                report["qualityHeld"] = sum(
                    not r["displayEligible"] for r in report["records"]
                )
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = type(exc).__name__ + ": " + str(exc)
        save()
        raise
    finally:
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        save()
    print("Coverage run: " + str(out.relative_to(ROOT)), flush=True)
    if report["status"] != "completed" or report.get("qualityHeld"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
