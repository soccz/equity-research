"""Collect one public annual filing into the isolated WMT research directory."""
from pathlib import Path
import importlib.util
import json
import hashlib
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
STAGE = Path(__file__).resolve().parent
(STAGE / 'data/sources').mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location('archive_xbrl', ROOT / 'scripts/archive-xbrl.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.ROOT = STAGE
source = m.archive(104169, '0000104169-26-000055')
path = STAGE / 'data/sources/filing-0000104169-26-000055.manifest.json'
if not path.exists():
    blob = m.fetch(source['primaryUrl'])
    if b'<html' not in blob[:4000].lower():
        raise ValueError('Annual filing is not HTML')
    sha = hashlib.sha256(blob).hexdigest()
    target = STAGE / f'data/sources/filing-0000104169-26-000055-{sha[:16]}.html'
    target.write_bytes(blob)
    manifest = dict(file=str(target.relative_to(STAGE)), sha256=sha,
                    url=source['primaryUrl'], provider='SEC', accession=source['accession'],
                    cik=source['cik'], retrievedAt=datetime.now(timezone.utc).isoformat())
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'xbrl':source['sha256'], 'annualHtml':json.loads(path.read_text())['sha256']}))
