"""Append exact-record editorial findings; keep original local-model replies."""
import json
from pathlib import Path
from equitylab.data import ROOT, canonical, digest
from equitylab.filing_reading import validate_audit


def record(symbol, findings):
    pointer=json.loads((ROOT/'data/filing-readings'/symbol/'latest.json').read_text())
    r=json.loads((ROOT/pointer['file']).read_text())
    assert r['recordHash']==digest(canonical({k:v for k,v in r.items() if k!='recordHash'}))
    assert r['status']=='unreviewed_draft'
    draft=r['draft'];texts={f'observation:{i}':v['reading'] for i,v in enumerate(draft['observations'])}
    texts.update({k:draft[k]['text'] for k in ['implication','question']})
    a=dict(company=symbol,recordHash=r['recordHash'],protocolVersion=r['protocolVersion'],reviewer='Codex 작성자 원문 대조 · 독립 금융 심사 아님',status='revision_required' if findings else 'no_material_issue_found',findings=[dict(role=k,text=texts[k],reason=v) for k,v in findings.items()])
    validate_audit(a,draft)
    path=ROOT/'data/filing-reading-audits.json';ledger=json.loads(path.read_text())
    old=[v for v in ledger['reviews'] if v['recordHash']==r['recordHash']]
    if old:
        assert old==[a], 'Existing exact record audit differs; preserve and review explicitly'
    else:
        ledger['reviews'].append(a);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
    print(symbol,a['status'],r['recordHash'])
