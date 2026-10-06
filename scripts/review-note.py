"""Record a specific model sentence error; never override it into financial approval."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab import note_audit
from equitylab.pipeline import load_latest, export


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--company", required=True)
    p.add_argument("--record-hash", required=True)
    p.add_argument("--role", choices=sorted(note_audit.ROLES), required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--reviewer", required=True)
    args = p.parse_args()
    companies = {c["id"] for c in load_latest()["companies"]}
    if args.company not in companies:
        p.error("Choose a registered company")
    folder = ROOT / "data/coverage-reviews" / args.company
    records = [json.loads(f.read_text()) for f in folder.glob("*/review.json")]
    matches = [r for r in records if r["recordHash"] == args.record_hash]
    if len(matches) != 1:
        p.error("An exact archived record hash is required")
    saved = note_audit.hold(matches[0], args.role, args.reason, args.reviewer)
    export(load_latest())
    print("Recorded sentence hold: " + saved["hash"])


if __name__ == "__main__":
    main()
