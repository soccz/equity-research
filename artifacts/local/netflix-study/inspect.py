from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from equitylab.xbrl import instance_rows
from equitylab.narrative import extract
B=Path(__file__).resolve().parent;c=json.loads((B/'company-start.json').read_text());a=json.loads((B/'data/sources/filing-0001065280-26-000034-xbrl.manifest.json').read_text());h=json.loads((B/'data/sources/filing-0001065280-26-000034.manifest.json').read_text());r=instance_rows((B/a['file']).read_bytes(),c,a,a['accession'],'2026-01-23');p=extract((B/h['file']).read_bytes());(B/'annual-rows.json').write_text(json.dumps(r,ensure_ascii=False));(B/'annual-passages.json').write_text(json.dumps(p,ensure_ascii=False,indent=2))
r=json.loads((B/'current-rows.json').read_text())
for x in r:
 if x['start']=='2026-01-01' and x['end']=='2026-06-30' and not x['dimensions'] and x['unit']=='USD':print(x['tag'],x['value'])
