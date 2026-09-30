"""Run a complete publication refresh on a GitHub-hosted runner."""

from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab.data import ensure_storage
from equitylab.dart import sync_history
from equitylab.pipeline import run, observe, register


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit(
            "This publication job runs in GitHub Actions. No local service is required."
        )
    if not os.environ.get("DART_API_KEY") or not os.environ.get("SEC_USER_AGENT"):
        raise SystemExit(
            "Configure the DART_API_KEY secret and SEC_USER_AGENT repository variable before requesting a refresh."
        )
    today = datetime.now(timezone.utc).date()
    cutoff = (
        os.environ.get("RESEARCH_AS_OF", "").strip()
        or (today - timedelta(days=1)).isoformat()
    )
    if date.fromisoformat(cutoff) >= today:
        raise SystemExit("Use a completed date before today's UTC date.")
    ensure_storage(ROOT)
    # No workstation archive is needed: official DART filings can bootstrap a clean runner.
    result = sync_history(cutoff)
    if any(r["status"] == "unavailable" for r in result["results"]):
        raise SystemExit(
            "Historical filings incomplete; retain the previous publication."
        )
    snapshot = run(cutoff, online=True)
    if snapshot["failures"]:
        raise SystemExit("Source refresh incomplete; retain the previous publication.")
    observe()
    register()
    print(
        f"Prepared {len(snapshot['companies'])} companies for {cutoff}; publication still requires tests."
    )


if __name__ == "__main__":
    main()
