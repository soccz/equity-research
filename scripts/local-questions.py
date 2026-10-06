"""Select source-bound research designs with the project-local model."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab import questions
from equitylab.data import canonical
from equitylab.pipeline import load_latest, export


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--company", action="append")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--model", default="qwen3:8b")
    p.add_argument("--wait-gpu-seconds", type=int, default=0)
    args = p.parse_args()
    snapshot = load_latest()
    companies = [
        c
        for c in snapshot["companies"]
        if c["status"] == "ready" and (not args.company or c["id"] in args.company)
    ]
    if (
        not companies
        or args.company
        and set(args.company) - {c["id"] for c in companies}
    ):
        p.error("Choose available registered companies")
    spec = importlib.util.spec_from_file_location(
        "question_runtime", ROOT / "scripts/local-research.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = ROOT / "artifacts/local" / ("question-run-" + stamp + ".json")
    result = dict(
        startedAt=datetime.now(timezone.utc).isoformat(),
        snapshotHash=snapshot["contentHash"],
        status="running",
        records=[],
    )
    path.write_bytes(canonical(result))
    try:
        with runtime.runtime(
            thinking=True,
            model=args.model,
            go_template=False,
            wait_gpu_seconds=args.wait_gpu_seconds,
        ) as client:
            installed = client.model(args.model)
            prior = questions.read(snapshot) if args.resume else {}
            for c in companies:
                old = prior.get(c["id"], {})
                reused = (
                    old.get("status") == "selected"
                    and old.get("modelDigest") == installed["digest"]
                    and old.get("inferenceConfig") == client.inference_config
                )
                r = (
                    old
                    if reused
                    else questions.select(
                        c, snapshot["contentHash"], client, args.model
                    )
                )
                result["records"].append(
                    dict(
                        company=c["id"],
                        status=r["status"],
                        choice=r.get("choice"),
                        recordHash=r["recordHash"],
                        reused=reused,
                        error=r.get("error"),
                    )
                )
                path.write_bytes(canonical(result))
                print(json.dumps(result["records"][-1], ensure_ascii=False), flush=True)
            result["status"] = (
                "completed"
                if all(r["status"] == "selected" for r in result["records"])
                else "partial_failure"
            )
        export(load_latest())
    except BaseException as exc:
        result.update(status="failed", error=type(exc).__name__ + ": " + str(exc))
        raise
    finally:
        result["finishedAt"] = datetime.now(timezone.utc).isoformat()
        path.write_bytes(canonical(result))
    print("Question selection: " + str(path.relative_to(ROOT)), flush=True)
    if result["status"] != "completed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
