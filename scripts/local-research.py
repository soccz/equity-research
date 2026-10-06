"""Run stored-source research and private GPU inference; never publish remotely."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab.local_ai import LocalClient, review, read_reviews
from equitylab.pipeline import load_latest, export, run


def gpu_available():
    memory = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    )
    used = [int(x.strip()) for x in memory.stdout.splitlines() if x.strip()]
    if not used or any(n > 512 for n in used):
        return False
    applications = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    )
    # A model can have a small allocation while starting. Memory alone is not
    # proof that another project's GPU job has finished.
    return not applications.stdout.strip()


def wait_for_gpu(seconds=0):
    if seconds < 0:
        raise ValueError("GPU wait must be nonnegative")
    deadline = time.monotonic() + seconds
    while not gpu_available():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                "GPU already in use; wait expired; other workloads unchanged"
            )
        print("Waiting for GPU; other workloads unchanged", flush=True)
        time.sleep(min(30, remaining))


class GpuGatedClient(LocalClient):
    """Reading installed model metadata and reusing records need no GPU."""

    def __init__(self, *, wait_gpu_seconds=0, **kwargs):
        if wait_gpu_seconds < 0:
            raise ValueError("GPU wait must be nonnegative")
        super().__init__(**kwargs)
        self.wait_gpu_seconds = wait_gpu_seconds
        self.gpu_checked = False
        self.gpu_error = None

    def call(self, path, body=None):
        unload_only = (
            path == "generate"
            and isinstance(body, dict)
            and set(body) == {"model", "keep_alive"}
            and body["keep_alive"] == 0
        )
        if path in ("chat", "generate") and not unload_only and not self.gpu_checked:
            if self.gpu_error is not None:
                raise RuntimeError(self.gpu_error)
            try:
                wait_for_gpu(self.wait_gpu_seconds)
            except Exception as exc:
                # A batch may catch a failed company request and try the next.
                # The wait allowance belongs to this runtime, not every company.
                self.gpu_error = str(exc)
                raise
            self.gpu_checked = True
        return super().call(path, body)


@contextmanager
def runtime(thinking=False, model="qwen3.5:9b", go_template=None, wait_gpu_seconds=0):
    binary = ROOT / ".local/ollama/bin/ollama"
    models = ROOT / ".local/models"
    if not binary.is_file() or not models.is_dir():
        raise RuntimeError(
            "Install a project-local Ollama runtime and local model first; see docs/local-runtime.md"
        )
    # Bind probe prevents reusing or stopping an unrelated local endpoint.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 11435))
    temp = ROOT / ".local/tmp"
    temp.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "OLLAMA_HOST": "127.0.0.1:11435",
        "OLLAMA_MODELS": str(models),
        "OLLAMA_NO_CLOUD": "1",
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_CONTEXT_LENGTH": "8192",
        "OLLAMA_KEEP_ALIVE": "0",
        "TMPDIR": str(temp),
    }
    if go_template is not None:
        env["OLLAMA_GO_TEMPLATE"] = "1" if go_template else "0"
    for k in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        env.pop(k, None)
    client = GpuGatedClient(thinking=thinking, wait_gpu_seconds=wait_gpu_seconds)
    if model == "qwen3:14b":
        # Partial GPU offload is expected on 8 GB cards. Preserve the response
        # deadline separately from generation settings and never use a remote fallback.
        client.timeout = 600
    if go_template is not None:
        client.inference_config["runtimeProfile"] = {
            "goTemplate": go_template,
            "version": "ollama-template-choice-v1",
        }
    if model.startswith("qwen3:"):
        client.inference_config["options"].update(
            temperature=0.6 if thinking else 0.7, presence_penalty=0.0
        )
    logs = ROOT / "artifacts/local"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / (
        "runtime-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".log"
    )
    with log.open("w") as stream:
        process = subprocess.Popen(
            [str(binary), "serve"],
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(
                        "Private model runtime exited; inspect " + str(log)
                    )
                try:
                    client.call("version")
                    break
                except Exception:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Private model runtime did not become ready")
            yield client
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--wait-gpu-seconds", type=int, default=0)
    parser.add_argument(
        "--thinking",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Thinking profile; use --no-thinking for a separately evaluated direct profile",
    )
    parser.add_argument("--company", action="append", choices=["MU", "000660"])
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="Run the frozen synthetic development suite before reviewing companies",
    )
    parser.add_argument(
        "--evaluation-only",
        action="store_true",
        help="Run the suite without generating company notes",
    )
    parser.add_argument(
        "--recalculate",
        action="store_true",
        help="Recalculate from stored filings and prices before inference",
    )
    args = parser.parse_args()
    snapshot = load_latest()
    if args.recalculate:
        snapshot = run(snapshot["asOf"], online=False)
    selected = args.company or ["MU", "000660"]
    records = []
    evaluation = None
    with runtime(
        thinking=args.thinking, model=args.model, wait_gpu_seconds=args.wait_gpu_seconds
    ) as client:
        if args.evaluate or args.evaluation_only:
            from equitylab.model_evaluation import evaluate

            evaluation = evaluate(client, args.model)
            print(
                json.dumps(
                    {
                        "evaluationGate": evaluation["gatePassed"],
                        "counts": evaluation["counts"],
                    }
                ),
                flush=True,
            )
        existing = read_reviews(snapshot) if args.resume else {}
        installed = client.model(args.model)
        for company in (
            []
            if args.evaluation_only
            or (evaluation and evaluation["status"] != "completed")
            else snapshot["companies"]
        ):
            if company["id"] not in selected:
                continue
            if not company.get("dossier"):
                raise RuntimeError(
                    "Recalculate first to build current evidence dossiers"
                )
            previous = existing.get(company["id"], {})
            reused = (
                previous.get("status") not in (None, "stale", "failed")
                and previous.get("modelDigest") == installed["digest"]
                and previous.get("inferenceConfig") == client.inference_config
            )
            if reused:
                record = previous
            else:
                print("Local GPU review: " + company["id"], flush=True)
                record = review(company, snapshot["contentHash"], client, args.model)
            records.append(record)
            print(
                json.dumps(
                    {
                        "company": company["id"],
                        "status": record["status"],
                        "model": record["model"],
                        "error": record.get("error"),
                        "reused": reused,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if not reused:
                client.call("generate", dict(model=args.model, keep_alive=0))
    export(snapshot)
    report = {
        "status": (
            "passed" if all(r["status"] != "failed" for r in records) else "failed"
        ),
        "mode": "local_only",
        "interpretationStatus": "independent_review_pending",
        "externalAIUsed": False,
        "model": args.model,
        "inferenceConfig": client.inference_config,
        "snapshotHash": snapshot["contentHash"],
        "evaluationHash": evaluation["recordHash"] if evaluation else None,
        "evaluationGatePassed": evaluation["gatePassed"] if evaluation else None,
        "reviews": [
            {
                "company": r["company"],
                "recordHash": r["recordHash"],
                "status": r["status"],
            }
            for r in records
        ],
    }
    (ROOT / "artifacts/local/latest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    if report["status"] == "failed":
        raise SystemExit(1)
    if evaluation and not evaluation["gatePassed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
