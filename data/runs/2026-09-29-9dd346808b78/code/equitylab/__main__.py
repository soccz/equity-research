import argparse
from datetime import datetime, timedelta, timezone
from .pipeline import run, register, observe, load_latest, export

parser = argparse.ArgumentParser(
    description="Batch equity research: sources → calculations → experiments → condition records → reports"
)
parser.add_argument(
    "command",
    choices=[
        "refresh",
        "register",
        "register-receivables",
        "observe",
        "export",
        "import-dart",
        "sync-history",
        "build-site",
        "register-study",
        "register-cases",
    ],
)
parser.add_argument(
    "--as-of",
    default=(datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat(),
)
parser.add_argument(
    "--online",
    action="store_true",
    help="Retrieve SEC, OpenDART and price data; Korean coverage requires DART_API_KEY or --dart-env",
)
parser.add_argument("--ticker")
parser.add_argument("--xbrl")
parser.add_argument("--receipt")
parser.add_argument("--filed-at")
parser.add_argument(
    "--dart-env",
    help="Read only DART_API_KEY from an existing local env file; never copy its contents",
)
args = parser.parse_args()
if args.dart_env:
    from .dart import load_key_file

    load_key_file(args.dart_env)
if args.command == "build-site":
    from .publication import build_site

    result = build_site()
    print(f"Static site: {len(result['files'])} files; {result['analysisHash'][:12]}")
elif args.command == "sync-history":
    from .dart import sync_history

    result = sync_history(args.as_of)
    print("Historical DART receipts:", len(result["results"]))
    if any(r["status"] == "unavailable" for r in result["results"]):
        print("Some historical filings unavailable; see data/dart-history-import.json")
elif args.command == "refresh":
    result = run(args.as_of, args.online)
    if result["failures"]:
        for item in result["failures"]:
            print(item)
        raise SystemExit(2)
elif args.command == "register":
    register()
elif args.command == "register-cases":
    from .research_journal import register as register_cases

    snapshot = load_latest()
    rows = register_cases(snapshot)
    export(snapshot)
    print(
        f"Research journal: {len(rows)} new revisions or observations; no return forecast"
    )
elif args.command == "register-study":
    from .forward_study import freeze

    snapshot = load_latest()
    study = freeze(snapshot)
    export(snapshot)
    print("Frozen forward study: " + study["protocolHash"])
elif args.command == "register-receivables":
    from .receivable_tracking import register as register_receivables

    snapshot = load_latest()
    rows = register_receivables(snapshot)
    export(snapshot)
    print(f"Registered {len(rows)} new receivable conditions; no direction forecasts")
elif args.command == "observe":
    observe()
elif args.command == "export":
    export(load_latest())
elif args.command == "import-dart":
    if not all([args.ticker, args.xbrl, args.receipt, args.filed_at]):
        parser.error("import-dart requires --ticker --xbrl --receipt --filed-at")
    from pathlib import Path
    from .data import import_dart

    print(
        import_dart(args.ticker, Path(args.xbrl), args.receipt, args.filed_at)["sha256"]
    )
