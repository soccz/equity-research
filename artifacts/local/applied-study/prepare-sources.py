from pathlib import Path
import importlib.util,json,hashlib,sys
from urllib.request import urlopen,Request
from datetime import datetime,timezone
root=Path(__file__).resolve().parents[3]
stage=Path(__file__).resolve().parent
url='https://ir.appliedmaterials.com/static-files/50913916-d1d0-4eff-bb18-67c4886343d0'
manifest=stage/'data/sources/filing-AMAT-20260212-segment-recast.manifest.json'
if not manifest.exists():
    with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0', 'Accept':'application/pdf'}),timeout=60) as r:b=r.read(20_000_001)
    assert b.startswith(b'%PDF') and len(b)<20_000_000
    sha=hashlib.sha256(b).hexdigest();file=f'data/sources/filing-AMAT-20260212-segment-recast-{sha[:16]}.pdf';(stage/file).write_bytes(b)
    manifest.write_text(json.dumps(dict(file=file,sha256=sha,url=url,primaryUrl=url,provider='Applied Materials investor relations',company='AMAT',cik=6951,publishedAt='2026-02-12',retrievedAt=datetime.now(timezone.utc).isoformat(),scope='Earnings presentation, page 23: recast vs previously reported segment financial table',page=23),ensure_ascii=False,indent=2))
spec=importlib.util.spec_from_file_location('applied_archive',root/'scripts/archive-xbrl.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.ROOT=stage
r=m.archive(6951,'0001628280-25-056742');print('annual XBRL',r['sha256'],flush=True)
script=root/'scripts/archive-sec-filing.py'
source=script.read_text().replace('ROOT = Path(__file__).resolve().parents[1]','ROOT = Path('+repr(str(stage))+')')
sys.argv=[str(script),'--cik','6951','--accession','0001628280-25-056742','--document','amat-20251026.htm']
exec(compile(source,str(script),'exec'),{'__file__':str(script),'__name__':'__main__'})
print('IR PDF',json.loads(manifest.read_text())['sha256'])
