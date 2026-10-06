"""Import one periodic XBRL only after matching an archived official issuer listing."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab import data, dart


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticker", required=True)
    p.add_argument("--receipt", required=True)
    p.add_argument("--dart-env", required=True)
    args = p.parse_args()
    c = next(c for c in data.UNIVERSE if c["id"] == args.ticker and c["market"] == "KR")
    current = json.loads((ROOT / f'data/sources/dart-sync-{c["id"]}.json').read_text())
    rows = [
        r
        for q in current["queries"]
        for r in json.loads(data.read_verified(ROOT / q["file"], q["sha256"]))["list"]
        if r["rcept_no"] == args.receipt
    ]
    if len(rows) != 1:
        raise ValueError("Receipt missing or duplicated in official issuer listing")
    filing, code = dart.choose_filing(rows, c, "9999-12-31")
    dart.load_key_file(args.dart_env)
    result = dart.fetch_package(c, filing, code)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
