"""Explicit primary-filing supplements when SEC companyfacts lacks a filing."""

import json
from .data import ROOT, US_TAGS, read_verified
from .xbrl import instance_rows


def supplement(company, existing):
    path = ROOT / "data/sec-filing-imports.json"
    if not path.exists():
        return [], []
    added, sources = [], []
    for spec in json.loads(path.read_text()):
        if spec["company"] != company["id"]:
            continue
        meta_source, source = spec["metadata"], spec["source"]
        meta = json.loads(
            read_verified(ROOT / meta_source["file"], meta_source["sha256"])
        )
        if int(meta["cik"]) != company["cik"] or source["cik"] != company["cik"]:
            raise ValueError("SEC supplemental issuer mismatch")
        recent = meta["filings"]["recent"]
        i = recent["accessionNumber"].index(source["accession"])
        if recent["form"][i] not in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
            raise ValueError("Unsupported supplemental filing")
        rows = instance_rows(
            read_verified(ROOT / source["file"], source["sha256"]),
            company,
            source,
            source["accession"],
            recent["filingDate"][i],
        )
        lookup = {}
        for r in rows:
            if (
                r["dimensions"]
                or r["unit"] != company["currency"]
                or r["taxonomy"].split("/")[2:3] != ["fasb.org"]
            ):
                continue
            key = (r["tag"], r["start"], r["end"], r["unit"])
            if key in lookup and lookup[key]["value"] != r["value"]:
                raise ValueError("Conflicting supplemental XBRL facts")
            lookup[key] = r
        for metric, tags in US_TAGS.items():
            for priority, tag in enumerate(tags):
                for r in lookup.values():
                    if r["tag"] != tag:
                        continue
                    same = [
                        f
                        for f in existing
                        if f["tag"].split(":")[-1] == tag
                        and all(
                            f[k] == r[k] for k in ("start", "end", "unit", "accession")
                        )
                    ]
                    if any(f["value"] != r["value"] for f in same):
                        raise ValueError("Companyfacts disagrees with primary filing")
                    if same:
                        continue
                    added.append(
                        dict(
                            r,
                            metric=metric,
                            tag="us-gaap:" + tag,
                            priority=priority,
                            standard="US-GAAP",
                            basis="consolidated",
                            provenance="primary_filing_supplement",
                        )
                    )
        sources.extend([meta_source, source])
    return added, sources
