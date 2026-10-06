"""Run the private, archived-source workflow through checked browser/PDF outputs."""

from datetime import datetime, timezone, timedelta
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of",
        default=(datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat(),
    )
    parser.add_argument(
        "--skip-model",
        action="store_true",
        help="Recalculate and render; retain only still-current archived model notes",
    )
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="Repeat the model's synthetic development evaluation",
    )
    parser.add_argument(
        "--wait-gpu-seconds",
        type=int,
        default=600,
        help="Maximum wait for each local GPU stage; other projects are never stopped",
    )
    args = parser.parse_args()
    if args.wait_gpu_seconds < 0:
        parser.error("--wait-gpu-seconds must be nonnegative")
    if args.skip_model and args.evaluate:
        parser.error("--evaluate cannot be combined with --skip-model")
    gpu_wait = ["--wait-gpu-seconds", str(args.wait_gpu_seconds)]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = ROOT / "artifacts/local/runs" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    report = dict(
        runId=run_id,
        startedAt=datetime.now(timezone.utc).isoformat(),
        status="running",
        mode="archived_sources_local_only",
        modelRequested=not args.skip_model,
        stages=[],
    )

    def save():
        (folder / "run.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )

    def stage(name, command, quality_codes=()):
        print(f"[{name}] {' '.join(command)}", flush=True)
        log = folder / (name + ".log")
        started = datetime.now(timezone.utc).isoformat()
        with log.open("w") as handle:
            result = subprocess.run(
                command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT
            )
        status = (
            "passed"
            if result.returncode == 0
            else (
                "quality_gate_failed"
                if result.returncode in quality_codes
                else "failed"
            )
        )
        report["stages"].append(
            dict(
                name=name,
                status=status,
                exitCode=result.returncode,
                startedAt=started,
                finishedAt=datetime.now(timezone.utc).isoformat(),
                log=str(log.relative_to(ROOT)),
                logHash=hashlib.sha256(log.read_bytes()).hexdigest(),
            )
        )
        save()
        print(f"[{name}] {status} — {log.relative_to(ROOT)}", flush=True)
        if status == "failed":
            raise RuntimeError(f"{name} failed; see {log.relative_to(ROOT)}")

    save()
    try:
        stage(
            "unit", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
        )
        stage(
            "analysis",
            [sys.executable, "-m", "equitylab", "refresh", "--as-of", args.as_of],
        )
        if not args.skip_model:
            # A failed semantic evaluation must remain visible, but need not prevent
            # a factual report with the disputed notes withheld from conclusions.
            stage(
                "local-model",
                [sys.executable, "scripts/local-research.py", "--resume"]
                + gpu_wait
                + (["--evaluate"] if args.evaluate else []),
                quality_codes=(2,),
            )
            stage(
                "coverage-model",
                [sys.executable, "scripts/local-coverage.py", "--resume"]
                + gpu_wait
                + (["--evaluate"] if args.evaluate else []),
                quality_codes=(2,),
            )
            stage(
                "question-model",
                [sys.executable, "scripts/local-questions.py", "--resume"] + gpu_wait,
                quality_codes=(2,),
            )
            stage(
                "filing-model",
                [sys.executable, "scripts/local-filings.py", "--resume"] + gpu_wait,
                quality_codes=(2,),
            )
        stage(
            "register-cash-conditions",
            [sys.executable, "-m", "equitylab", "register"],
        )
        stage(
            "register-receivable-conditions",
            [sys.executable, "-m", "equitylab", "register-receivables"],
        )
        stage("observe", [sys.executable, "-m", "equitylab", "observe"])
        stage("research-journal", [sys.executable, "-m", "equitylab", "register-cases"])
        stage("forward-study", [sys.executable, "-m", "equitylab", "register-study"])
        stage("price-crosscheck", ["node", "scripts/check-dossier.mjs"])
        stage("local-records", [sys.executable, "scripts/check-local-records.py"])
        stage("offline-replay", [sys.executable, "scripts/check-replay.py"])
        stage("browser-pdf", ["node", "scripts/check-live.mjs"])
        stage("artifacts", [sys.executable, "scripts/check-artifacts.py"])
        pointer = json.loads((ROOT / "data/latest.json").read_text())
        report["snapshotHash"] = pointer["contentHash"]
        payload = json.loads(
            (ROOT / "app/snapshot.js")
            .read_text()
            .removeprefix("window.EQUITY_SNAPSHOT = ")
            .rstrip(";\n")
        )
        report["modelReviewStates"] = {
            k: {
                "status": v["status"],
                "displayEligible": v.get("displayEligible", False),
                "recordHash": v.get("recordHash"),
            }
            for k, v in payload.get("localReviews", {}).items()
        }
        report["independentFinancialApproval"] = False
        report["filingReadingStates"] = {
            k: dict(
                status=v["status"],
                recordHash=v.get("recordHash"),
                semanticApproval=False,
            )
            for k, v in payload.get("filingReadings", {}).items()
        }
        report["questionSelectionStates"] = {
            k: {
                "status": v["status"],
                "recordHash": v.get("recordHash"),
                "choice": v.get("choice"),
            }
            for k, v in payload.get("questionSelections", {}).items()
        }
        report["coverageReviewStates"] = {
            k: {
                "status": v["status"],
                "displayEligible": v.get("displayEligible", False),
                "recordHash": v.get("recordHash"),
            }
            for k, v in payload.get("coverageReviews", {}).items()
        }
        report["status"] = "artifacts_verified"
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        save()
        latest = ROOT / "artifacts/local/last-verified-run.json"
        pending = latest.with_suffix(".tmp")
        pending.write_text(
            json.dumps(
                dict(
                    file=str((folder / "run.json").relative_to(ROOT)),
                    sha256=hashlib.sha256(
                        (folder / "run.json").read_bytes()
                    ).hexdigest(),
                ),
                indent=2,
            )
            + "\n"
        )
        pending.replace(latest)
        print(
            "Verified private outputs: app/index.html and artifacts/live/*.pdf",
            flush=True,
        )
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = type(exc).__name__ + ": " + str(exc)
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        save()
        raise


if __name__ == "__main__":
    lock_path = ROOT / "artifacts/local/workflow.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another private workflow is active; no stages started")
        main()
