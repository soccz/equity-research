from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[3];STAGE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(STAGE))
import protocol
from equitylab.data import canonical,digest
from equitylab.pipeline import load_latest
if (STAGE/'frozen.json').exists():raise RuntimeError('Do not rewrite frozen pilot inputs')
pointer=json.loads((ROOT/'artifacts/local/last-verified-run.json').read_text());run=json.loads((ROOT/pointer['file']).read_text());s=load_latest()
if run['status']!='artifacts_verified' or run['snapshotHash']!=s['contentHash'] or not any(c['id']=='271560' and (c.get('operatingModel') or {}).get('status')=='research_workspace' for c in s['companies']):raise RuntimeError('Wait for the current verified snapshot containing Orion')
cs={c['id']:c for c in s['companies']};inputs={}
for ident in protocol.FOCUS:
 packet=protocol.packet(cs[ident]);blob=canonical(packet);(STAGE/(ident+'-input.json')).write_bytes(blob);inputs[ident]=digest(blob)
frozen=dict(protocolHash=protocol.protocol_hash(),suiteHash=digest((STAGE/'suite.json').read_bytes()), runnerHash=digest((STAGE/'run.py').read_bytes()), inputs=inputs,snapshotHash=s['contentHash'],productionRun=pointer['file'],financialApproval=False)
(STAGE/'frozen.json').write_bytes(canonical(frozen));print('Frozen',len(inputs),'inputs',s['contentHash'])
