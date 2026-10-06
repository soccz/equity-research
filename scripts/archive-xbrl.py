"""Archive SEC extracted XBRL, preserving exact issuer and filing identity."""

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def fetch(url):
    request = Request(
        url,
        headers={
            "User-Agent": os.environ.get(
                "SEC_USER_AGENT", "EquityResearchLocal/0.2 research-client"
            )
        },
    )
    with urlopen(request, timeout=60) as response:
        blob = response.read(20_000_001)
    if len(blob) > 20_000_000:
        raise ValueError("SEC document exceeds size limit")
    return blob


def archive(cik, accession, document=None):
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise ValueError("Invalid accession")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
    manifest_path = ROOT / f"data/sources/filing-{accession}-xbrl.manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if (
            old["cik"] != cik
            or old["accession"] != accession
            or hashlib.sha256((ROOT / old["file"]).read_bytes()).hexdigest()
            != old["sha256"]
        ):
            raise ValueError("Existing filing manifest mismatch")
        return old
    index_source = None
    if document is None:
        index_url = base + accession + "-index.html"
        index = fetch(index_url)
        links = []

        class Links(HTMLParser):
            def handle_starttag(self, tag, attrs):
                target = urljoin(index_url, dict(attrs).get("href", ""))
                if (
                    tag == "a"
                    and target.startswith(base)
                    and target.endswith("_htm.xml")
                ):
                    links.append(target[len(base) :])

        Links().feed(index.decode("utf-8"))
        if len(set(links)) != 1:
            raise ValueError(
                "Filing index does not identify exactly one extracted XBRL"
            )
        document = links[0]
        sha = hashlib.sha256(index).hexdigest()
        path = ROOT / f"data/sources/filing-{accession}-index-{sha[:16]}.html"
        path.write_bytes(index)
        index_source = dict(file=str(path.relative_to(ROOT)), sha256=sha, url=index_url)
        time.sleep(0.2)
    if not re.fullmatch(r"[a-zA-Z0-9_-]+_htm\.xml", document):
        raise ValueError("Invalid extracted XBRL document name")
    url = base + document
    blob = fetch(url)
    root = ET.fromstring(blob)
    ns = {"x": "http://www.xbrl.org/2003/instance"}
    identifiers = {int(e.text) for e in root.findall(".//x:identifier", ns)}
    if identifiers != {cik}:
        raise ValueError("Filing issuer identity mismatch")
    sha = hashlib.sha256(blob).hexdigest()
    path = ROOT / f"data/sources/filing-{accession}-{sha[:16]}.xbrl"
    path.write_bytes(blob)
    manifest = dict(
        file=str(path.relative_to(ROOT)),
        sha256=sha,
        url=url,
        primaryUrl=url.replace("_htm.xml", ".htm"),
        provider="SEC",
        accession=accession,
        cik=cik,
        retrievedAt=datetime.now(timezone.utc).isoformat(),
    )
    if index_source:
        manifest["indexSource"] = index_source
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cik", type=int)
    p.add_argument("--accession")
    p.add_argument("--document")
    p.add_argument("--company", action="append")
    p.add_argument("--universe", action="store_true")
    p.add_argument(
        "--as-of", help="Select the current filing from archived SEC facts at this date"
    )
    a = p.parse_args()
    if not a.universe and not a.company:
        if not a.cik or not a.accession:
            p.error("Provide --cik/--accession, --company, or --universe")
        print(json.dumps(archive(a.cik, a.accession, a.document), ensure_ascii=False))
        return
    if a.cik or a.accession or a.document or (a.universe and a.company):
        p.error("Select one filing, named companies, or the registered US universe")
    pointer = json.loads((ROOT / "data/latest.json").read_text())
    snapshot = json.loads((ROOT / pointer["snapshot"]).read_text())
    companies = [
        c
        for c in snapshot["companies"]
        if c["market"] == "US"
        and c["status"] == "ready"
        and (a.universe or c["id"] in a.company)
    ]
    if a.as_of:
        sys.path.insert(0, str(ROOT))
        from equitylab.data import UNIVERSE, sec_facts, statement

        companies = [
            dict(c, financials=statement(sec_facts(c, False)[0], a.as_of))
            for c in UNIVERSE
            if c["market"] == "US" and (a.universe or c["id"] in a.company)
        ]
    if not companies or a.company and set(a.company) != {c["id"] for c in companies}:
        p.error("Only available registered US companies may be selected")
    report = dict(
        startedAt=datetime.now(timezone.utc).isoformat(),
        snapshotHash=snapshot["contentHash"],
        asOf=a.as_of or snapshot["asOf"],
        records=[],
    )
    out = (
        ROOT
        / "artifacts/local"
        / (
            "filing-collection-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            + ".json"
        )
    )
    for c in companies:
        r = dict(
            company=c["id"], accession=c["financials"]["current"]["cfo"]["accession"]
        )
        try:
            r.update(status="archived", source=archive(c["cik"], r["accession"]))
        except Exception as exc:
            r.update(status="failed", error=type(exc).__name__ + ": " + str(exc)[:400])
        report["records"].append(r)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(c["id"], r["status"], flush=True)
        time.sleep(0.2)
    report["finishedAt"] = datetime.now(timezone.utc).isoformat()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if any(r["status"] == "failed" for r in report["records"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
