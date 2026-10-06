"""Public-source adapters. No upstream application code is imported."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import time
from datetime import date, datetime, timezone
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = [
    dict(
        id="MU",
        name="Micron",
        market="US",
        currency="USD",
        cik=723125,
        symbol="MU",
        group="메모리",
        caveat="8월 결산 · 메모리 중심",
    ),
    dict(
        id="NVDA",
        name="NVIDIA",
        market="US",
        currency="USD",
        cik=1045810,
        symbol="NVDA",
        group="반도체",
        caveat="팹리스 · 메모리 제조업과 투자 구조가 다름",
    ),
    dict(
        id="GOOGL",
        name="Alphabet",
        market="US",
        currency="USD",
        cik=1652044,
        symbol="GOOGL",
        group="플랫폼",
        caveat="복수 주식 종류 · 검색·클라우드·기타 사업",
    ),
    dict(
        id="AAPL",
        name="Apple",
        market="US",
        currency="USD",
        cik=320193,
        symbol="AAPL",
        group="전자·서비스",
        caveat="9월 결산 · 하드웨어·서비스 결합",
    ),
    dict(
        id="000660",
        name="SK하이닉스",
        market="KR",
        currency="KRW",
        dartCorpCode="00164779",
        symbol="000660.KS",
        group="메모리",
        caveat="12월 결산 · K-IFRS 연결",
    ),
    dict(
        id="005930",
        name="삼성전자",
        market="KR",
        currency="KRW",
        dartCorpCode="00126380",
        symbol="005930.KS",
        group="반도체·전자",
        caveat="메모리·파운드리·DX 혼합 · 우선주 존재",
    ),
    dict(
        id="035420",
        name="NAVER",
        market="KR",
        currency="KRW",
        dartCorpCode="00266961",
        symbol="035420.KS",
        group="플랫폼",
        caveat="국내 검색·커머스·콘텐츠 사업 구성",
    ),
    dict(
        id="066570",
        name="LG전자",
        market="KR",
        currency="KRW",
        dartCorpCode="00401731",
        symbol="066570.KS",
        group="전자·서비스",
        caveat="가전·전장 및 연결 자회사 · 우선주 존재",
    ),
]
UNIVERSE = (
    json.loads((ROOT / "data/universe.json").read_text())
    if (ROOT / "data/universe.json").exists()
    else DEFAULT_UNIVERSE
)
if len({c["id"] for c in UNIVERSE}) != len(UNIVERSE) or any(
    c["market"] not in ("US", "KR") for c in UNIVERSE
):
    raise ValueError("Invalid or duplicate universe member")
for member in UNIVERSE:
    if member["market"] == "US" and (
        not isinstance(member.get("cik"), int) or member["cik"] <= 0
    ):
        raise ValueError("US companies require a positive SEC CIK")
US_TAGS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquireOtherPropertyPlantAndEquipment",
    ],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "equity": ["StockholdersEquity"],
    "shares": ["CommonStockSharesOutstanding"],
}
KR_TAGS = {
    "revenue": ["Revenue"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["ProfitLoss"],
    "cfo": ["CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": ["Equity"],
    "cash": ["CashAndCashEquivalents"],
}


def ensure_storage(root=ROOT):
    (root / "data/sources").mkdir(parents=True, exist_ok=True)
    manifest = root / "data/dart-imports.json"
    if not manifest.exists():
        manifest.write_text("[]\n")


def work_temp() -> Path:
    folder = Path(os.environ.get("EQUITY_TMPDIR", ROOT / "data/cache/tmp"))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def read_verified(path: Path, expected: str) -> bytes:
    blob = path.read_bytes()
    if digest(blob) != expected:
        raise ValueError(f"Source hash mismatch: {path.name}")
    return blob


def fetch_json(url: str, key: str, online: bool) -> tuple[dict, dict]:
    """Keep content-addressed originals; never silently fall back after a refresh fails."""
    folder = ROOT / "data/sources"
    pointer = folder / f"{key}.manifest.json"
    if not online:
        manifest = json.loads(pointer.read_text())
        blob = read_verified(ROOT / manifest["file"], manifest["sha256"])
        return json.loads(blob), manifest
    request = Request(
        url,
        headers={
            "User-Agent": os.environ.get(
                "SEC_USER_AGENT", "EquityResearchLocal/0.2 research-client"
            ),
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=30) as response:
        blob = response.read(25_000_000)
    parsed = json.loads(blob)
    sha = digest(blob)
    path = folder / f"{key}-{sha[:16]}.json"
    path.write_bytes(blob)
    manifest = dict(
        url=url,
        sha256=sha,
        file=str(path.relative_to(ROOT)),
        retrievedAt=datetime.now(timezone.utc).isoformat(),
        provider="SEC" if "sec.gov" in url else "Yahoo Finance",
    )
    pointer.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    time.sleep(0.2)
    return parsed, manifest


def sec_facts(company: dict, online: bool) -> tuple[list, list]:
    cik = company["cik"]
    obj, source = fetch_json(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010}.json",
        f"sec-{company['id']}",
        online,
    )
    if int(obj["cik"]) != cik:
        raise ValueError("SEC company identifier mismatch")
    rows = []
    for metric, tags in US_TAGS.items():
        unit = "shares" if metric == "shares" else company["currency"]
        metric_tags = (
            ["PaymentsToAcquireProductiveAssets"]
            if company["id"] == "NVDA" and metric == "capex"
            else tags
        )
        for priority, tag in enumerate(metric_tags):
            for f in (
                obj["facts"]
                .get("us-gaap", {})
                .get(tag, {})
                .get("units", {})
                .get(unit, [])
            ):
                if f.get("form") not in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
                    continue
                if not isinstance(f["val"], (float, int)) or not math.isfinite(
                    f["val"]
                ):
                    continue
                accession = f["accn"]
                rows.append(
                    dict(
                        metric=metric,
                        value=f["val"],
                        start=f.get("start"),
                        end=f["end"],
                        filedAt=f["filed"],
                        unit=unit,
                        basis="consolidated",
                        standard="US-GAAP",
                        tag=f"us-gaap:{tag}",
                        priority=priority,
                        accession=accession,
                        sourceHash=source["sha256"],
                        sourceFile=source["file"],
                        sourceUrl=f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.html",
                    )
                )
    from .sec_supplements import supplement

    extra, supplemental_sources = supplement(company, rows)
    return rows + extra, [source, *supplemental_sources]


def parse_dart(blob: bytes, item: dict) -> list:
    root = ET.fromstring(blob)
    ns = {"x": "http://www.xbrl.org/2003/instance", "d": "http://xbrl.org/2006/xbrldi"}
    company = next((c for c in UNIVERSE if c["id"] == item["ticker"]), None)
    identifiers = {n.text for n in root.findall(".//x:identifier", ns)}
    if (
        not company
        or not company.get("dartCorpCode")
        or identifiers != {company["dartCorpCode"]}
    ):
        raise ValueError(
            "DART company identifier does not match the registered security"
        )
    contexts = {}
    for c in root.findall("x:context", ns):
        dims = c.findall(".//d:explicitMember", ns)
        # Only whole-entity consolidated contexts. Segment, parent and member facts are excluded.
        if (
            len(dims) != 1
            or dims[0].text.split(":")[-1] != "ConsolidatedMember"
            or not dims[0]
            .get("dimension", "")
            .endswith("ConsolidatedAndSeparateFinancialStatementsAxis")
        ):
            continue
        if c.findall(".//d:typedMember", ns):
            continue
        p = c.find("x:period", ns)
        contexts[c.get("id")] = {
            "start": p.findtext("x:startDate", namespaces=ns),
            "end": p.findtext("x:endDate", namespaces=ns)
            or p.findtext("x:instant", namespaces=ns),
        }
    units = {
        u.get("id"): u.findtext("x:measure", namespaces=ns)
        for u in root.findall("x:unit", ns)
    }
    aliases = {tag: metric for metric, tags in KR_TAGS.items() for tag in tags}
    filing = item["filing"]
    filed = date.fromisoformat(filing["filed_at"]).isoformat()
    rows = []
    seen = {}
    for e in root:
        tag = e.tag.split("}")[-1]
        metric = aliases.get(tag)
        period = contexts.get(e.get("contextRef"))
        if (
            not metric
            or not period
            or units.get(e.get("unitRef"), "").split(":")[-1] != "KRW"
        ):
            continue
        if not e.text or e.get("{http://www.w3.org/2001/XMLSchema-instance}nil") in (
            "true",
            "1",
        ):
            continue
        value = float(e.text)
        if not math.isfinite(value):
            raise ValueError("Non-finite DART fact")
        key = (metric, period["start"], period["end"])
        if key in seen and seen[key] != value:
            raise ValueError(f"Conflicting DART whole-entity facts: {key}")
        if key in seen:
            continue
        seen[key] = value
        rows.append(
            dict(
                metric=metric,
                value=value,
                **period,
                filedAt=filed,
                unit="KRW",
                basis="consolidated",
                standard="K-IFRS",
                tag=tag,
                context=e.get("contextRef"),
                priority=0,
                accession=filing["rcept_no"],
                sourceHash=item["sha256"],
                sourceFile=item["file"],
                sourceUrl=filing["url"],
            )
        )
    return rows


def dart_facts(company: dict) -> tuple[list, list]:
    items = json.loads((ROOT / "data/dart-imports.json").read_text())
    selected = [item for item in items if item["ticker"] == company["id"]]
    rows, sources = [], []
    sync_path = ROOT / "data/sources" / f"dart-sync-{company['id']}.json"
    checked = json.loads(sync_path.read_text()) if sync_path.exists() else None
    for item in selected:
        rows.extend(
            parse_dart(read_verified(ROOT / item["file"], item["sha256"]), item)
        )
        sources.append(
            dict(
                provider="DART",
                url=item["filing"]["url"],
                file=item["file"],
                sha256=item["sha256"],
                retrievedAt=item["importedAt"],
                mode=(
                    f"OPENDART 접수 확인 {checked['checkedAt'][:10]} · 원문 보존"
                    if checked
                    else "보존 공시 원문 재추출 · API 최신 확인 전"
                ),
            )
        )
    return rows, sources


def prices(company: dict, as_of: str, online: bool) -> tuple[list, dict]:
    obj, source = fetch_json(
        f"https://query2.finance.yahoo.com/v8/finance/chart/{company['symbol']}?range=5y&interval=1d&events=div%2Csplits",
        f"price-{company['id']}",
        online,
    )
    if obj["chart"].get("error") or not obj["chart"].get("result"):
        raise ValueError("Price provider returned no results")
    result = obj["chart"]["result"][0]
    meta = result["meta"]
    if meta["symbol"] != company["symbol"] or meta["currency"] != company["currency"]:
        raise ValueError("Price currency or security mismatch")
    tz = ZoneInfo(meta["exchangeTimezoneName"])
    quotes = result["indicators"]["quote"][0]
    adjusted = result["indicators"]["adjclose"][0]["adjclose"]
    rows = []
    for i, t in enumerate(result["timestamp"]):
        day = datetime.fromtimestamp(t, tz).date().isoformat()
        close, adj = quotes["close"][i], adjusted[i]
        if day > as_of or close is None or adj is None:
            continue
        if min(close, adj) <= 0 or not all(math.isfinite(v) for v in (close, adj)):
            raise ValueError("Invalid close")
        rows.append(
            dict(date=day, close=close, adjustedClose=adj, volume=quotes["volume"][i])
        )
    rows.sort(key=lambda row: row["date"])
    if len({r["date"] for r in rows}) != len(rows) or len(rows) < 300:
        raise ValueError("Duplicate dates or insufficient price history")
    source.update(
        currency=meta["currency"],
        timezone=meta["exchangeTimezoneName"],
        adjustment="Provider adjusted close for historical returns; close for last quote. Current-vintage corporate-action adjustments, not archived daily vintages.",
    )
    return rows, source


def select_fact(
    facts: list, metric: str, start: str | None, end: str, as_of: str
) -> dict | None:
    candidates = [
        f
        for f in facts
        if f["metric"] == metric
        and f["start"] == start
        and f["end"] == end
        and f["filedAt"] <= as_of
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda f: (f["filedAt"], -f["priority"], f["accession"]))
    return candidates[-1]


def statement(facts: list, as_of: str) -> dict:
    flows = [
        f
        for f in facts
        if f["metric"] == "cfo"
        and f["start"]
        and f["filedAt"] <= as_of
        and f["end"] <= as_of
    ]
    if not flows:
        raise ValueError("No available operating cash flow")
    end = max(f["end"] for f in flows)
    # CFO is normally cumulative year-to-date. Match every numerator and denominator to it.
    starts = sorted({f["start"] for f in flows if f["end"] == end})
    # Some filers also report trailing-twelve-month CFO. Never combine that
    # with six-month revenue/capex, or fall back to an older reporting end.
    start = next(
        (
            s
            for s in starts
            if all(select_fact(facts, m, s, end, as_of) for m in ("revenue", "capex"))
        ),
        starts[0],
    )
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    prior_candidates = [
        f
        for f in flows
        if 350 <= (date.fromisoformat(end) - date.fromisoformat(f["end"])).days <= 380
        and abs(
            (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days
            + 1
            - days
        )
        <= 8
    ]
    prior = (
        min(
            prior_candidates,
            key=lambda f: abs(
                (date.fromisoformat(end) - date.fromisoformat(f["end"])).days - 365
            ),
        )
        if prior_candidates
        else None
    )
    metrics = ["revenue", "operating_income", "net_income", "cfo", "capex"]
    current = {m: select_fact(facts, m, start, end, as_of) for m in metrics}
    previous = {
        m: select_fact(facts, m, prior["start"], prior["end"], as_of) if prior else None
        for m in metrics
    }
    if not all(current[m] for m in ["revenue", "cfo", "capex"]):
        raise ValueError("Same-period revenue, CFO or gross PP&E purchases missing")
    return dict(
        start=start,
        end=end,
        days=days,
        current=current,
        previous=previous,
        priorStart=prior["start"] if prior else None,
        priorEnd=prior["end"] if prior else None,
        basis="consolidated",
        standard=current["cfo"]["standard"],
        filedAt=max(f["filedAt"] for f in current.values() if f),
        availableAsOf=as_of,
    )


def import_dart(ticker: str, path: Path, receipt: str, filed_at: str):
    if ticker not in [c["id"] for c in UNIVERSE if c["market"] == "KR"]:
        raise ValueError("Register the Korean security in data/universe.json first")
    day = date.fromisoformat(filed_at).isoformat()
    if (
        len(receipt) != 14
        or not receipt.isdigit()
        or receipt[:8] != day.replace("-", "")
    ):
        raise ValueError("DART receipt must have 14 digits with the filing-date prefix")
    blob = path.read_bytes()
    sha = digest(blob)
    dest = ROOT / "data/sources" / f"{ticker}-{receipt}-{sha[:16]}.xbrl"
    item = dict(
        ticker=ticker,
        file=str(dest.relative_to(ROOT)),
        sha256=sha,
        filing=dict(
            rcept_no=receipt,
            filed_at=day,
            name="사용자 반입 정기공시",
            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
        ),
        originalPath=str(path.resolve()),
        importedAt=datetime.now(timezone.utc).isoformat(),
        independentlyParsed=True,
    )
    facts = parse_dart(blob, item)
    statement(
        facts, day
    )  # Reject a mismatched or unusable accounting contract before import.
    manifest = ROOT / "data/dart-imports.json"
    rows = json.loads(manifest.read_text())
    old = next((r for r in rows if r["filing"]["rcept_no"] == receipt), None)
    if old:
        if old["sha256"] != sha or old["ticker"] != ticker:
            raise ValueError(
                "Same receipt has different contents; preserve the correction with its new receipt"
            )
        return old
    dest.write_bytes(blob)
    rows.append(item)
    temp = manifest.with_suffix(".json.tmp")
    temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    os.replace(temp, manifest)
    return item
