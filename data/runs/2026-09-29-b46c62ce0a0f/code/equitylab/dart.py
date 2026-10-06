"""Independent Open DART retrieval; credentials never enter source manifests."""

import io
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zipfile
from .data import (
    ROOT,
    UNIVERSE,
    digest,
    import_dart,
    parse_dart,
    read_verified,
    ensure_storage,
)


def load_key_file(path):
    for line in Path(path).read_text().splitlines():
        match = re.match(r"^\s*(?:export\s+)?DART_API_KEY\s*=\s*(.*?)\s*$", line)
        if match:
            key = match[1].strip().strip("\"'")
            if not re.fullmatch(r"[A-Za-z0-9]{40}", key):
                raise ValueError("DART key format invalid; value withheld")
            os.environ["DART_API_KEY"] = key
            return
    raise ValueError("DART_API_KEY absent in selected credential file")


def request(endpoint, params):
    key = os.environ.get("DART_API_KEY")
    if not key:
        raise ValueError("DART_API_KEY not configured")
    url = (
        "https://opendart.fss.or.kr/api/"
        + endpoint
        + "?"
        + urlencode({**params, "crtfc_key": key})
    )
    try:
        with urlopen(
            Request(url, headers={"User-Agent": "EquityResearchLocal/0.2"}), timeout=40
        ) as response:
            body = response.read(30_000_001)
        if len(body) > 30_000_000:
            raise ValueError("Response size limit")
        time.sleep(0.2)
        return body
    except Exception as exc:
        # Exception URL representations can contain the key. Report type only.
        raise RuntimeError(
            f"DART {endpoint}: {type(exc).__name__}; request details withheld"
        ) from None


def choose_filing(rows, company, as_of):
    candidates = []
    for row in rows:
        if (
            row["corp_code"] != company["dartCorpCode"]
            or row.get("stock_code") != company["id"]
        ):
            raise ValueError("DART listing issuer mismatch")
        if row["rcept_dt"] > as_of.replace("-", ""):
            continue
        name = row["report_nm"]
        match = re.search(r"(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)", name)
        if not match:
            continue
        kind, year, month = match.groups()
        code = (
            "11011"
            if kind == "사업"
            else (
                "11012" if kind == "반기" else {"03": "11013", "09": "11014"}.get(month)
            )
        )
        if code:
            candidates.append(
                (year + month, row["rcept_dt"], row["rcept_no"], code, row)
            )
    if not candidates:
        raise ValueError("No supported periodic filing before cutoff")
    selected = max(candidates, key=lambda x: x[:3])
    return selected[-1], selected[-2]


def sync(company, as_of):
    ensure_storage(ROOT)
    rows = []
    queries = []
    for page in range(1, 4):
        params = dict(
            corp_code=company["dartCorpCode"],
            bgn_de=f"{date.fromisoformat(as_of).year-1}0101",
            end_de=as_of.replace("-", ""),
            pblntf_ty="A",
            last_reprt_at="N",
            page_count=100,
            page_no=page,
            sort="date",
            sort_mth="desc",
        )
        blob = request("list.json", params)
        response = json.loads(blob)
        if response.get("status") != "000":
            raise ValueError(f"DART listing status {response.get('status')}")
        sha = digest(blob)
        path = ROOT / "data/sources" / f'dart-list-{company["id"]}-{sha[:16]}.json'
        path.write_bytes(blob)
        queries.append(
            dict(file=str(path.relative_to(ROOT)), sha256=sha, parameters=params)
        )
        rows.extend(response["list"])
        if int(response["total_page"]) <= page:
            break
    else:
        raise ValueError("DART listing exceeds bounded 300-filing retrieval")
    filing, code = choose_filing(rows, company, as_of)
    package_info = fetch_package(company, filing, code)
    receipt = dict(
        ticker=company["id"],
        asOf=as_of,
        checkedAt=datetime.now(timezone.utc).isoformat(),
        filing=filing,
        queries=queries,
        **package_info,
    )
    destination = ROOT / "data/sources" / f'dart-sync-{company["id"]}.json'
    destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return receipt


def fetch_package(company, filing, code):
    package = request(
        "fnlttXbrl.xml", dict(rcept_no=filing["rcept_no"], reprt_code=code)
    )
    if not package.startswith(b"PK"):
        raise ValueError("DART XBRL response is not a ZIP archive")
    sha = digest(package)
    archive = (
        ROOT / "data/sources" / f'dart-package-{filing["rcept_no"]}-{sha[:16]}.zip'
    )
    archive.write_bytes(package)
    extracted = []
    with zipfile.ZipFile(io.BytesIO(package)) as z:
        for entry in z.infolist():
            if entry.filename.lower().endswith(".xbrl"):
                if entry.file_size > 25_000_000:
                    raise ValueError("XBRL member exceeds size limit")
                blob = z.read(entry)
                raw_sha = digest(blob)
                path = ROOT / "data/sources" / f"dart-instance-{raw_sha[:16]}.xbrl"
                path.write_bytes(blob)
                try:
                    imported = import_dart(
                        company["id"], path, filing["rcept_no"], filing["rcept_dt"]
                    )
                    extracted.append(imported)
                except ValueError as exc:
                    if "identifier" not in str(exc):
                        raise
    if len(extracted) != 1:
        raise ValueError("Exactly one matching whole-company XBRL instance required")
    return dict(
        package=dict(file=str(archive.relative_to(ROOT)), sha256=sha),
        instanceHash=extracted[0]["sha256"],
    )


def sync_history(as_of):
    results = []
    for company in UNIVERSE:
        if company["market"] != "KR":
            continue
        pointer = ROOT / "data/sources" / f"dart-sync-{company['id']}.json"
        if not pointer.exists():
            sync(company, as_of)
        receipt = json.loads(pointer.read_text())
        if receipt["asOf"] != as_of:
            receipt = sync(company, as_of)
        rows = []
        for query in receipt["queries"]:
            rows.extend(
                json.loads(read_verified(ROOT / query["file"], query["sha256"]))["list"]
            )
        for row in sorted(rows, key=lambda r: r["rcept_no"]):
            if not re.search(
                r"(사업|반기|분기)보고서\s*\(\d{4}\.\d{2}\)", row["report_nm"]
            ):
                continue
            if row["rcept_dt"] > as_of.replace("-", ""):
                continue
            old = json.loads((ROOT / "data/dart-imports.json").read_text())
            if any(r["filing"]["rcept_no"] == row["rcept_no"] for r in old):
                continue
            print(
                f"DART history {company['id']} {row['rcept_no']} {row['report_nm']}",
                flush=True,
            )
            try:
                filing, code = choose_filing([row], company, as_of)
                result = fetch_package(company, filing, code)
                results.append(
                    dict(
                        ticker=company["id"],
                        receipt=row["rcept_no"],
                        status="imported",
                        **result,
                    )
                )
            except Exception as exc:
                results.append(
                    dict(
                        ticker=company["id"],
                        receipt=row["rcept_no"],
                        status="unavailable",
                        error=str(exc),
                    )
                )
    output = dict(
        asOf=as_of, checkedAt=datetime.now(timezone.utc).isoformat(), results=results
    )
    (ROOT / "data/dart-history-import.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )
    return output
