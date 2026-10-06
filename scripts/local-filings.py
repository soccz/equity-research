"""Read selected filing paragraphs with the project-local model."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab import filing_reading as reading
from equitylab.data import canonical, digest
from equitylab.pipeline import load_latest, export


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--company", action="append")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--model", default="qwen3:8b")
    p.add_argument("--wait-gpu-seconds", type=int, default=0)
    p.add_argument(
        "--language-probe",
        action="store_true",
        help="Separate English development probe; never replaces production readings",
    )
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
    if args.language_probe and (
        not args.company or any(c["market"] != "US" for c in companies)
    ):
        p.error("The separate English probe requires explicitly chosen US companies")
    spec = importlib.util.spec_from_file_location(
        "reading_runtime", ROOT / "scripts/local-research.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = ROOT / "artifacts/local" / ("filing-reading-run-" + stamp + ".json")
    result = dict(
        startedAt=datetime.now(timezone.utc).isoformat(),
        snapshotHash=snapshot["contentHash"],
        status="running",
        mode="english_development_probe" if args.language_probe else "production",
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
            prior = reading.read(snapshot) if args.resume else {}
            for c in companies:
                if args.language_probe:
                    packet = reading.packet(c)
                    folder = path.with_suffix("") / c["id"]
                    folder.mkdir(parents=True, exist_ok=False)
                    (folder / "input.json").write_bytes(canonical(packet))
                    messages = reading.messages(packet)
                    messages[0]["content"] = messages[0]["content"].replace(
                        "Explain in Korean", "Explain in English"
                    )
                    messages[1]["content"] = messages[1]["content"].replace(
                        "complete Korean sentence", "complete English sentence", 1
                    )
                    draft, timing, _ = client.generate(
                        args.model,
                        messages,
                        reading.schema(packet),
                        archive=folder / "reading-raw.json",
                    )
                    reading.validate(draft, packet)
                    r = dict(
                        company=c["id"],
                        status="language_probe_unreviewed",
                        draft=draft,
                        modelDigest=installed["digest"],
                        inferenceConfig=client.inference_config,
                        runtime=timing,
                        loadedModels=client.call("ps").get("models", []),
                        semanticApproval=False,
                        scope="Same known development inputs, output language changed. No independent or out-of-sample accuracy claim.",
                    )
                    r["files"] = {
                        str(f.relative_to(ROOT)): digest(f.read_bytes())
                        for f in folder.iterdir()
                        if f.is_file()
                    }
                    r["recordHash"] = digest(canonical(r))
                    (folder / "record.json").write_bytes(canonical(r))
                    result["records"].append(r)
                    path.write_bytes(canonical(result))
                    print(
                        json.dumps(
                            dict(
                                company=c["id"],
                                status=r["status"],
                                recordHash=r["recordHash"],
                            )
                        ),
                        flush=True,
                    )
                    continue
                old = prior.get(c["id"], {})
                reused = (
                    old.get("status") == "unreviewed_draft"
                    and old.get("modelDigest") == installed["digest"]
                    and old.get("inferenceConfig") == client.inference_config
                )
                r = (
                    old
                    if reused
                    else reading.generate(
                        c, snapshot["contentHash"], client, args.model
                    )
                )
                result["records"].append(
                    dict(
                        company=c["id"],
                        status=r["status"],
                        semanticApproval=False,
                        recordHash=r["recordHash"],
                        reused=reused,
                        error=r.get("error"),
                    )
                )
                path.write_bytes(canonical(result))
                print(json.dumps(result["records"][-1], ensure_ascii=False), flush=True)
            result["status"] = (
                "completed"
                if all(
                    r["status"] in ("unreviewed_draft", "language_probe_unreviewed")
                    for r in result["records"]
                )
                else "partial_failure"
            )
        if not args.language_probe:
            export(load_latest())
    except BaseException as exc:
        result.update(status="failed", error=type(exc).__name__ + ": " + str(exc))
        raise
    finally:
        result["finishedAt"] = datetime.now(timezone.utc).isoformat()
        path.write_bytes(canonical(result))
    print("Filing reading: " + str(path.relative_to(ROOT)), flush=True)
    if result["status"] != "completed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
