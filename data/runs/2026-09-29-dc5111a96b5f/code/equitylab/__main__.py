import argparse
from .pipeline import run, register, observe, load_latest, export

parser = argparse.ArgumentParser(
    description="Batch equity research: sources → calculations → experiments → condition records → reports"
)
parser.add_argument(
    "command",
    choices=[
        "refresh",
        "register",
        "observe",
        "export",
        "import-dart",
        "sync-history",
        "build-site",
    ],
)
parser.add_argument("--as-of", default="2026-09-29")
parser.add_argument(
    "--online",
    action="store_true",
    help="Retrieve public SEC and price data; otherwise use verified local cache",
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
