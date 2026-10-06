"""Rebuild the latest analysis from its frozen code, manifests and verified originals."""

import hashlib
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
temp_root = Path(os.environ.get("EQUITY_TMPDIR", ROOT / "data/cache/tmp"))
temp_root.mkdir(parents=True, exist_ok=True)
pointer = json.loads((ROOT / "data/latest.json").read_text())
run = ROOT / pointer["snapshot"]
snapshot = json.loads(run.read_text())


def verified_copy(source, target, expected):
    blob = source.read_bytes()
    if hashlib.sha256(blob).hexdigest() != expected:
        raise ValueError(f"Frozen input changed: {source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)


with tempfile.TemporaryDirectory(prefix="equity-replay-", dir=temp_root) as folder:
    replay = Path(folder)
    for group in ["engineFiles", "renderFiles"]:
        for relative, expected in snapshot[group].items():
            verified_copy(run.parent / "code" / relative, replay / relative, expected)
    for relative, expected in snapshot["inputFiles"].items():
        verified_copy(run.parent / "inputs" / relative, replay / relative, expected)
    sources = {
        s["file"]: s["sha256"]
        for company in snapshot["companies"]
        for s in company.get("sources", [])
    }
    sources.update(
        {s["file"]: s["sha256"] for s in snapshot.get("registrySources", [])}
    )
    for relative, expected in sources.items():
        verified_copy(ROOT / relative, replay / relative, expected)
    completed = subprocess.run(
        [sys.executable, "-m", "equitylab", "refresh", "--as-of", snapshot["asOf"]],
        cwd=replay,
        capture_output=True,
        text=True,
        # Sixty issuer-specific filings include large Korean XBRL documents.
        # Keep a finite ceiling without treating the old 40-company time budget
        # as an assertion about financial reproducibility.
        timeout=600,
    )
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    rebuilt_pointer = json.loads((replay / "data/latest.json").read_text())
    rebuilt = json.loads((replay / rebuilt_pointer["snapshot"]).read_text())
    fields = [
        "companies",
        "peerStudies",
        "failures",
        "experiments",
        "fundamentalExperiments",
        "universeHash",
        "registrySources",
        "researchCohort",
        "researchProtocol",
        "engineFiles",
        "renderFiles",
        "inputFiles",
    ]
    for field in fields:
        if snapshot[field] != rebuilt[field]:
            raise AssertionError(f"Reproduction differs: {field}")

report = dict(
    checkedAt=datetime.now(timezone.utc).isoformat(),
    status="passed",
    snapshotHash=snapshot["contentHash"],
    verifiedRawSources=len(sources),
    identicalFields=fields,
    method="isolated offline rebuild from archived code, input manifests and hash-verified originals",
    exclusions="generation time, online retrieval mode, condition/model-note ledgers and local inference records are separate events",
)
(ROOT / "artifacts/live/replay-verification.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n"
)
print(
    f"PASS isolated replay: {len(sources)} originals; {len(fields)} identical analysis fields"
)
