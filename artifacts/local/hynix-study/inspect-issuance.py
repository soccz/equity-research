from pathlib import Path
import json, os, sys
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from equitylab.dart import load_key_file, request
from equitylab.data import canonical, digest
from equitylab.pipeline import load_latest
c = next(c for c in load_latest()['companies'] if c['id'] == '000660')
load_key_file('/mnt/20t/report/.env')
rows, sources = [], []
for page in range(1, 5):
    params = dict(corp_code=c['dartCorpCode'], bgn_de='20260701', end_de='20260929',
                  last_reprt_at='N', page_count=100, page_no=page, sort='date', sort_mth='desc')
    body = request('list.json', params)
    if os.environ['DART_API_KEY'].encode() in body:
        raise ValueError('Credential in response; withheld')
    d = json.loads(body)
    if d.get('status') != '000':
        raise ValueError('DART list status: '+str(d.get('status')))
    sha = digest(body)
    f = Path(__file__).parent/'data/sources'/f'hynix-capital-list-{sha[:16]}.json'
    f.write_bytes(body)
    sources.append(dict(file=str(f.relative_to(Path(__file__).parent)), sha256=sha, parameters=params))
    rows.extend(d['list'])
    if int(d['total_page']) <= page:
        break
else:
    raise ValueError('Filing list exceeds retrieval bound')
result = dict(company=c['id'], asOf='2026-09-29', checkedAt=datetime.now(timezone.utc).isoformat(), sources=sources, filings=rows)
(Path(__file__).parent/'capital-filings.json').write_bytes(canonical(result))
for r in rows:
    print(r['rcept_dt'], r['rcept_no'], r['report_nm'])
