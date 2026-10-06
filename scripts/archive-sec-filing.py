"""Archive a specific public SEC filing; failures never reuse an older document."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument("--cik", type=int, required=True)
p.add_argument("--accession", required=True)
p.add_argument("--document", required=True)
p.add_argument("--exhibit", help="Separate exhibit manifest suffix, e.g. ex31")
a = p.parse_args()
if a.exhibit and not re.fullmatch(r"ex[0-9a-z-]{1,20}", a.exhibit):
    p.error(
        "An exhibit suffix must start with ex and contain letters, digits or hyphens"
    )
if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", a.accession) or not re.fullmatch(
    r"[a-zA-Z0-9_-]+\.htm", a.document
):
    p.error("An accession and a plain .htm document name are required")
url = f"https://www.sec.gov/Archives/edgar/data/{a.cik}/{a.accession.replace('-', '')}/{a.document}"
request = Request(
    url,
    headers={
        "User-Agent": os.environ.get(
            "SEC_USER_AGENT", "EquityResearchLocal/0.2 research-client"
        ),
        "Accept": "text/html",
    },
)
with urlopen(request, timeout=45) as response:
    blob = response.read(12_000_001)
if len(blob) > 12_000_000 or b"<html" not in blob[:4000].lower():
    raise ValueError("Not a supported filing HTML document")
sha = hashlib.sha256(blob).hexdigest()
path = ROOT / f"data/sources/filing-{a.accession}-{sha[:16]}.html"
path.write_bytes(blob)
manifest = dict(
    file=str(path.relative_to(ROOT)),
    sha256=sha,
    url=url,
    provider="SEC",
    accession=a.accession,
    cik=a.cik,
    retrievedAt=datetime.now(timezone.utc).isoformat(),
)
suffix = f"-{a.exhibit}" if a.exhibit else ""
(ROOT / f"data/sources/filing-{a.accession}{suffix}.manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
)
print(json.dumps(manifest, ensure_ascii=False))
