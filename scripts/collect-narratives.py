"""Archive the exact current filings' business/management text for local research."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab.data import canonical, read_verified
from equitylab.pipeline import load_latest


def collect(company, dart_env):
    core = company["financials"]["current"]["cfo"]
    accession = core["accession"]
    if company["market"] == "US":
        manifest = ROOT / f"data/sources/filing-{accession}.manifest.json"
        if not manifest.exists():
            xbrl = json.loads(
                (
                    ROOT / f"data/sources/filing-{accession}-xbrl.manifest.json"
                ).read_text()
            )
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/archive-sec-filing.py"),
                    "--cik",
                    str(company["cik"]),
                    "--accession",
                    accession,
                    "--document",
                    Path(urlparse(xbrl["primaryUrl"]).path).name,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            time.sleep(0.15)
        source = json.loads(manifest.read_text())
        if source["accession"] != accession or source["cik"] != company["cik"]:
            raise ValueError("Narrative issuer or accession mismatch")
        sources = [source]
    else:
        manifest = ROOT / f"data/sources/dart-document-{accession}.manifest.json"
        if not manifest.exists():
            if not dart_env and not os.environ.get("DART_API_KEY"):
                raise ValueError("Current Korean narrative requires --dart-env")
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/archive-dart-document.py"),
                    "--receipt",
                    accession,
                ]
                + (["--dart-env", dart_env] if dart_env else []),
                check=True,
                capture_output=True,
                text=True,
            )
        archive = json.loads(manifest.read_text())
        if archive["receipt"] != accession:
            raise ValueError("Narrative receipt mismatch")
        # Attachments have different names; index only the filed main document.
        main = [s for s in archive["files"] if s["originalName"] == accession + ".xml"]
        if len(main) != 1:
            raise ValueError("Exactly one main DART document required")
        sources = [
            dict(
                **s,
                url=archive["url"],
                provider="DART",
                retrievedAt=archive["retrievedAt"],
            )
            for s in main
        ]
    for source in sources:
        read_verified(ROOT / source["file"], source["sha256"])
    return dict(
        company=company["id"],
        accession=accession,
        filedAt=core["filedAt"],
        period=[core["start"], core["end"]],
        status="archived",
        sources=sources,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dart-env")
    args = parser.parse_args()
    snapshot = load_latest()
    rows = []
    for company in snapshot["companies"]:
        if company["status"] != "ready":
            continue
        try:
            row = collect(company, args.dart_env)
        except Exception as exc:
            # Do not echo request details, environments, or subprocess output.
            row = dict(company=company["id"], status="failed", error=type(exc).__name__)
        rows.append(row)
        print(company["id"], row["status"], flush=True)
    record = dict(
        version="filing-narratives-v1",
        snapshotHash=snapshot["contentHash"],
        collectedAt=datetime.now(timezone.utc).isoformat(),
        results=rows,
    )
    (ROOT / "data/narratives.json").write_bytes(canonical(record))
    if any(r["status"] == "failed" for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
