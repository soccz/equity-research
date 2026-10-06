"""Verify issuer identities, then collect only this project's public sources."""

import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab import data, dart


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def identities(plan):
    sec, sec_source = data.fetch_json(
        "https://www.sec.gov/files/company_tickers.json", "issuer-sec", True
    )
    us = {v["ticker"]: v for v in sec.values()}
    blob = dart.request("corpCode.xml", {})
    sha = data.digest(blob)
    path = ROOT / f"data/sources/issuer-dart-{sha[:16]}.zip"
    path.write_bytes(blob)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        entry = next(e for e in z.infolist() if e.filename.lower() == "corpcode.xml")
        if entry.file_size > 100_000_000:
            raise ValueError("Issuer registry exceeds size limit")
        root = ET.fromstring(z.read(entry))
    kr = {}
    for row in root.findall("list"):
        ticker = (row.findtext("stock_code") or "").strip()
        if ticker:
            kr.setdefault(ticker, []).append(row)
    old = {c["id"]: c for c in data.UNIVERSE}
    result = []
    for ticker, market, sector, peer in plan["companies"]:
        if market == "US":
            matched = us[ticker]
            spec = dict(
                id=ticker,
                name=matched["title"],
                market=market,
                currency="USD",
                symbol=ticker,
                cik=int(matched["cik_str"]),
            )
        else:
            matched = kr[ticker]
            if len(matched) != 1:
                raise ValueError("Ambiguous DART stock code: " + ticker)
            spec = dict(
                id=ticker,
                name=matched[0].findtext("corp_name"),
                market=market,
                currency="KRW",
                symbol=ticker + ".KS",
                dartCorpCode=matched[0].findtext("corp_code"),
            )
        if ticker in old:
            identity = "cik" if market == "US" else "dartCorpCode"
            if old[ticker][identity] != spec[identity]:
                raise ValueError("Existing issuer identity changed: " + ticker)
            spec = {**old[ticker], **spec, "name": old[ticker]["name"]}
        spec.update(sector=sector, peerGroup=peer, group=sector)
        spec.setdefault(
            "caveat", "조사 분류 내 제품·사업 범위와 회계 기준 차이를 추가 확인"
        )
        result.append(spec)
    write(ROOT / "data/universe.json", result)
    write(
        ROOT / "data/coverage-identities.json",
        dict(
            verifiedAt=datetime.now(timezone.utc).isoformat(),
            selectionRule=plan["selectionRule"],
            planHash=data.digest(data.canonical(plan)),
            sources=[
                sec_source,
                dict(
                    file=str(path.relative_to(ROOT)),
                    sha256=sha,
                    url="https://opendart.fss.or.kr/api/corpCode.xml",
                    provider="OpenDART",
                ),
            ],
            members=result,
        ),
    )
    data.UNIVERSE[:] = result
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dart-env", required=True)
    parser.add_argument("--as-of", default="2026-09-29")
    parser.add_argument("--reuse-identities", action="store_true")
    args = parser.parse_args()
    dart.load_key_file(args.dart_env)
    plan = json.loads((ROOT / "data/coverage-plan.json").read_text())
    specs = data.UNIVERSE if args.reuse_identities else identities(plan)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    previous = ROOT / "data/coverage-retrieval.json"
    if previous.exists():
        (ROOT / f"data/coverage-retrieval-before-{stamp}.json").write_bytes(
            previous.read_bytes()
        )
    results = []
    for c in specs:
        print("Coverage " + c["id"], flush=True)
        try:
            history_issues = []
            source_pointer = ROOT / f"data/sources/sec-{c['id']}.manifest.json"
            if c["market"] == "US":
                facts, _ = data.sec_facts(c, not source_pointer.exists())
            else:
                pointer = ROOT / f"data/sources/dart-sync-{c['id']}.json"
                receipt = (
                    json.loads(pointer.read_text())
                    if pointer.exists()
                    else dart.sync(c, args.as_of)
                )
                # One annual filing provides comparable annual history in addition to the current interim.
                rows = [
                    r
                    for q in receipt["queries"]
                    for r in json.loads(
                        data.read_verified(ROOT / q["file"], q["sha256"])
                    )["list"]
                    if "사업보고서" in r["report_nm"]
                    and r["rcept_dt"] <= args.as_of.replace("-", "")
                ]
                filing, code = dart.choose_filing(rows, c, args.as_of)
                imported = json.loads((ROOT / "data/dart-imports.json").read_text())
                if not any(
                    x["filing"]["rcept_no"] == filing["rcept_no"] for x in imported
                ):
                    try:
                        dart.fetch_package(c, filing, code)
                    except (ValueError, RuntimeError) as exc:
                        history_issues.append(
                            dict(accession=filing["rcept_no"], error=str(exc))
                        )
                facts, _ = data.dart_facts(c)
            price_pointer = ROOT / f"data/sources/price-{c['id']}.manifest.json"
            history, _ = data.prices(c, args.as_of, not price_pointer.exists())
            s = data.statement(facts, args.as_of)
            result = dict(
                ticker=c["id"],
                status="ready",
                periodEnd=s["end"],
                filedAt=s["filedAt"],
                priceObservations=len(history),
                historyIssues=history_issues,
            )
        except Exception as exc:
            result = dict(ticker=c["id"], status="unavailable", error=str(exc))
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        write(
            ROOT / "data/coverage-retrieval.json",
            dict(
                asOf=args.as_of,
                checkedAt=datetime.now(timezone.utc).isoformat(),
                results=results,
            ),
        )
    if any(x["status"] != "ready" for x in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
