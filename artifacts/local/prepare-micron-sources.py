from pathlib import Path
import importlib.util
import json,hashlib
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('archive_xbrl',ROOT/'scripts/archive-xbrl.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
staging=ROOT/'artifacts/local/micron-study';(staging/'data/sources').mkdir(parents=True,exist_ok=True);m.ROOT=staging
r=m.archive(723125,'0000723125-25-000028');print(json.dumps(r))
blob=m.fetch(r['primaryUrl']);sha=hashlib.sha256(blob).hexdigest();p=staging/f'data/sources/filing-0000723125-25-000028-{sha[:16]}.html';p.write_bytes(blob)
meta={k:r[k] for k in ['provider','accession','cik','retrievedAt']};meta.update(file=str(p.relative_to(staging)),sha256=sha,url=r['primaryUrl']);(staging/'data/sources/filing-0000723125-25-000028.manifest.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta))
