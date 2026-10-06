"""Archive Korean share classes; read only DART_API_KEY from the authorized file."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab.pipeline import load_latest
from equitylab.dart import load_key_file
from equitylab.security import collect


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dart-env")
    p.add_argument("--company", action="append")
    a = p.parse_args()
    if a.dart_env:
        load_key_file(a.dart_env)
    s = load_latest()
    report = dict(
        snapshotHash=s["contentHash"],
        startedAt=datetime.now(timezone.utc).isoformat(),
        records=[],
    )
    out = (
        ROOT
        / "artifacts/local"
        / (
            "share-collection-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            + ".json"
        )
    )
    for c in s["companies"]:
        if (
            c["market"] != "KR"
            or c["status"] != "ready"
            or a.company
            and c["id"] not in a.company
        ):
            continue
        record = dict(company=c["id"])
        try:
            record.update(status="archived", source=collect(c))
        except Exception as exc:
            record.update(status="failed", error=str(exc))
        report["records"].append(record)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(c["id"], record["status"], record.get("error", ""), flush=True)
    report["finishedAt"] = datetime.now(timezone.utc).isoformat()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if not report["records"] or any(
        r["status"] != "archived" for r in report["records"]
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
