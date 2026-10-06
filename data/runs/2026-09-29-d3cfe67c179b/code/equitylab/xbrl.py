"""Exact-context extraction for archived SEC and DART XBRL instances."""

import math
import json
import xml.etree.ElementTree as ET
from .data import ROOT, read_verified

NS = {"x": "http://www.xbrl.org/2003/instance", "d": "http://xbrl.org/2006/xbrldi"}


def company_filing(company, as_of):
    """Load the precise current cash-flow filing, never a silent older substitute."""
    core = company["financials"]["current"]["cfo"]
    if core["filedAt"] > as_of or core["end"] > as_of:
        raise ValueError("Business notes cannot use a future filing")
    if company["market"] == "US":
        path = ROOT / f"data/sources/filing-{core['accession']}-xbrl.manifest.json"
        if not path.exists():
            return None, []
        source = json.loads(path.read_text())
        if source["accession"] != core["accession"] or source["cik"] != company["cik"]:
            raise ValueError("Business-note manifest identity mismatch")
    else:
        source = next(s for s in company["sources"] if s["file"] == core["sourceFile"])
    rows = instance_rows(
        read_verified(ROOT / source["file"], source["sha256"]),
        company,
        source,
        core["accession"],
        core["filedAt"],
    )
    for item in [source, source.get("indexSource")]:
        if item:
            item = dict(item)
            item.setdefault("provider", source.get("provider", "SEC"))
            item.setdefault("retrievedAt", source["retrievedAt"])
            read_verified(ROOT / item["file"], item["sha256"])
            if item["file"] not in {s["file"] for s in company["sources"]}:
                company["sources"].append(item)
    return source, [r for r in rows if r["end"] <= as_of]


def instance_rows(blob, company, source, accession, filed_at):
    root = ET.fromstring(blob)
    identifiers = {e.text for e in root.findall(".//x:identifier", NS)}
    expected = str(company.get("cik", company.get("dartCorpCode")))
    if not identifiers or {x.lstrip("0") for x in identifiers} != {
        expected.lstrip("0")
    }:
        raise ValueError("Business-note issuer mismatch")
    units = {}
    for u in root.findall("x:unit", NS):
        measure = u.find("x:measure", NS)
        if measure is not None and len(list(u)) == 1:
            units[u.get("id")] = measure.text.split(":")[-1]
    contexts = {}
    for ctx in root.findall("x:context", NS):
        if ctx.findall(".//d:typedMember", NS):
            continue
        dims = sorted(
            (e.get("dimension").split(":")[-1], e.text.split(":")[-1])
            for e in ctx.findall(".//d:explicitMember", NS)
        )
        if len({d[0] for d in dims}) != len(dims):
            raise ValueError("Repeated dimension axis")
        period = ctx.find("x:period", NS)
        contexts[ctx.get("id")] = dict(
            start=period.findtext("x:startDate", namespaces=NS),
            end=period.findtext("x:endDate", namespaces=NS)
            or period.findtext("x:instant", namespaces=NS),
            dimensions=dims,
        )
    rows = []
    for e in root:
        ctx = contexts.get(e.get("contextRef"))
        unit = units.get(e.get("unitRef"))
        if (
            not ctx
            or unit not in (company["currency"], "shares")
            or e.text is None
            or e.get("{http://www.w3.org/2001/XMLSchema-instance}nil") in ("1", "true")
        ):
            continue
        value = float(e.text)
        if not math.isfinite(value):
            raise ValueError("Non-finite business-note amount")
        rows.append(
            dict(
                **ctx,
                tag=e.tag.split("}")[-1],
                taxonomy=e.tag.split("}")[0].lstrip("{"),
                value=value,
                unit=unit,
                context=e.get("contextRef"),
                factId=e.get("id"),
                decimals=e.get("decimals"),
                accession=accession,
                filedAt=filed_at,
                sourceFile=source["file"],
                sourceHash=source["sha256"],
                sourceUrl=source.get("primaryUrl", source["url"]),
            )
        )
    return rows


def select(rows, tag, start, end, dimensions=(), unit=None):
    dims = sorted(dimensions)
    matches = [
        r
        for r in rows
        if r["tag"] == tag
        and r["start"] == start
        and r["end"] == end
        and r["dimensions"] == dims
        and (unit is None or r["unit"] == unit)
    ]
    if not matches:
        return None
    if len({(r["value"], r["unit"], r["taxonomy"]) for r in matches}) != 1:
        raise ValueError("Conflicting business-note facts: " + tag)
    return matches[0]
