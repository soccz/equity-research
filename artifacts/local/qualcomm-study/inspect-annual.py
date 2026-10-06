from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from equitylab.xbrl import instance_rows
from equitylab.narrative import extract
B=Path(__file__).resolve().parent
c=json.loads((B/'company-start.json').read_text());a=json.loads((B/'data/sources/filing-0000804328-25-000085-xbrl.manifest.json').read_text());h=json.loads((B/'data/sources/filing-0000804328-25-000085.manifest.json').read_text())
r=instance_rows((B/a['file']).read_bytes(),c,a,a['accession'],'2025-11-05');p=extract((B/h['file']).read_bytes());(B/'annual-rows.json').write_text(json.dumps(r,ensure_ascii=False));(B/'annual-passages.json').write_text(json.dumps(p,ensure_ascii=False,indent=2))
for x in p:
 if any(t in x['text'] for t in ['Unallocated revenues','Unallocated cost','Unallocated R&D','Unallocated SG&A','Unallocated other','Unallocated interest','Unallocated investment','Income tax payments in excess','Provision for income taxes in excess','Acquisitions and other investments']):print(x['ordinal'],x['id'],x['text'])
print('CURRENT UNALLOCATED and CASH')
r=json.loads((B/'current-rows.json').read_text())
for x in r:
 if x['start']=='2025-09-29' and x['end']=='2026-06-28' and (not x['dimensions'] or any('MaterialReconcilingItemsMember' in str(t) for t in x['dimensions'])) and x['unit']=='USD':print(x['tag'],x['value'],x['dimensions'])
