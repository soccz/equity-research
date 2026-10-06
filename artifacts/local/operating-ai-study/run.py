"""Isolated GPU pilot, no production records or UI exported."""
from pathlib import Path
import json,sys,importlib.util,copy
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[3];STAGE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(STAGE))
import protocol
from equitylab.data import canonical,digest
from equitylab.local_ai import ask_recorded
from equitylab import coverage_reasoning as base

def main():
 run=json.loads((ROOT/'artifacts/local/runs/20261002T073020194947Z/run.json').read_text())
 if run['status']!='artifacts_verified':raise RuntimeError('Finish the frozen production run before this GPU pilot')
 frozen=json.loads((STAGE/'frozen-inputs.json').read_text())
 if protocol.protocol_hash()!=frozen['protocolHash']:raise RuntimeError('Pilot protocol changed after freezing inputs')
 packets={i:json.loads((STAGE/(i+'-input.json')).read_text()) for i in frozen['inputs']}
 if any(digest(canonical(p))!=frozen['inputs'][i] for i,p in packets.items()):raise RuntimeError('Pilot packet changed')
 if digest((STAGE/'suite.json').read_bytes())!=frozen['suiteHash']:raise RuntimeError('Evaluation suite changed after freezing')
 suite=json.loads((STAGE/'suite.json').read_text());stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out=STAGE/stamp;out.mkdir()
 spec=importlib.util.spec_from_file_location('pilot_runtime',ROOT/'scripts/local-research.py');runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
 report=dict(startedAt=datetime.now(timezone.utc).isoformat(),status='running',protocolHash=protocol.protocol_hash(),suiteHash=digest((STAGE/'suite.json').read_bytes()),inputHashes=frozen['inputs'],productionSnapshot=run['snapshotHash'],externalAIUsed=False,independentReview=False,financialApproval=False,scope=suite['scope'],evaluation=[],companies=[])
 def save(): (out/'result.json').write_bytes(canonical(report))
 save()
 (out/'protocol.py').write_bytes((STAGE/'protocol.py').read_bytes())
 (out/'suite.json').write_bytes((STAGE/'suite.json').read_bytes())
 (out/'frozen-inputs.json').write_bytes((STAGE/'frozen-inputs.json').read_bytes())
 for ident,p in packets.items():(out/(ident+'-input.json')).write_bytes(canonical(p))
 try:
  with runtime.runtime(thinking=True,model='qwen3:8b',go_template=False,wait_gpu_seconds=600) as client:
   client.inference_config['options']['num_ctx']=8192
   model=client.model('qwen3:8b');report.update(modelDigest=model['digest'],inferenceConfig=copy.deepcopy(client.inference_config));save()
   probe,stats=ask_recorded(client,'qwen3:8b',out,'format-probe',protocol.SYSTEM,protocol.DRAFT_TASK,protocol.prompt_packet(packets['TXN']),protocol.DRAFT_SCHEMA)
   protocol.validate_notes(probe);report['formatProbe']=dict(status='passed',notes=probe,runtime=stats);save()
   for case in suite['cases']:
    item={k:case[k] for k in ['id','role','text']};row=dict(case=case['id'],split=case['split'],expectedAccept=case['accept'],expected=case['expected'],status='failed')
    try:
     result,timing=ask_recorded(client,'qwen3:8b',out,case['id'],protocol.SYSTEM,protocol.REVIEW_TASK,dict(input=protocol.prompt_packet(packets[case['company']]),items=[item]),protocol.review_schema([item]))
     protocol.validate_assessments(result,[item]);a=result['assessments'][0];row.update(status='completed',assessment=a,accepted=protocol.accepted(a,case['role'],case['text']),modelAccepted=protocol.model_accepted(a,case['role']),runtime=timing)
    except Exception as exc:row['error']=type(exc).__name__+': '+str(exc)[:500]
    report['evaluation'].append(row);save();print('Evaluation',case['id'],row['status'],row.get('accepted'),flush=True)
   rows=report['evaluation'];counts=dict(falseAccepts=sum(r.get('accepted') is True for r in rows if not r['expectedAccept']),falseRejects=sum(r.get('accepted') is False for r in rows if r['expectedAccept']),invalid=sum(r['status']=='failed' for r in rows),total=len(rows))
   report['evaluationSummary']=dict(counts=counts,gatePassed=counts['falseAccepts']==0 and counts['falseRejects']<=1 and counts['invalid']==0,financialApproval=False);save()
   for ident,p in packets.items():
    row=dict(company=ident,status='failed',rounds=[])
    try:
     draft,stats=ask_recorded(client,'qwen3:8b',out,ident+'-draft',protocol.SYSTEM,protocol.DRAFT_TASK,protocol.prompt_packet(p),protocol.DRAFT_SCHEMA);protocol.validate_notes(draft);row['notes']=draft;row['draftRuntime']=stats;save()
     scrutiny=dict(assessments=[]);items=protocol.review_items(draft)
     for item in items:
      critique,timing=ask_recorded(client,'qwen3:8b',out,ident+'-review-'+item['id'],protocol.SYSTEM,protocol.REVIEW_TASK,dict(input=protocol.prompt_packet(p),items=[item]),protocol.review_schema([item]));protocol.validate_assessments(critique,[item]);scrutiny['assessments'].extend(critique['assessments']);row['rounds'].append(dict(item=item,critique=critique,runtime=timing))
     row.update(status='reviewed_pilot' if protocol.all_accepted(scrutiny,items) else 'revision_required',scrutiny=scrutiny,styleFindings=protocol.style_findings(items),financialApproval=False)
    except Exception as exc:row['error']=type(exc).__name__+': '+str(exc)[:500]
    report['companies'].append(row);save();print('Company',ident,row['status'],flush=True)
   report['loadedModels']=client.call('ps').get('models',[])
   report['status']='completed'
 except BaseException as exc:
  report['status']='failed';report['error']=type(exc).__name__+': '+str(exc)[:500];raise
 finally:
  report['finishedAt']=datetime.now(timezone.utc).isoformat();save();print('Pilot archive',out.relative_to(ROOT),flush=True)
if __name__=='__main__':main()
