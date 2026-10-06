import sys,json,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from equitylab.pipeline import load_latest
from equitylab import segment_history
stage=Path(__file__).resolve().parent
s=load_latest();c=copy.deepcopy(next(c for c in s['companies'] if c['id']=='MU'))
note=json.loads((stage/'research-preparation.json').read_text())
contract=json.loads((ROOT/'data/segment-continuity.json').read_text())
record=dict(company='MU',dimensionAliases={},currentAccession=c['financials']['current']['cfo']['accession'],corpusHash=c['narrative']['evidenceHash'],annualAccession=note['annualAccession'],annualSource=note['annualSource'],annualTextTag=note['annualSegmentPolicyTag'],annualTextHash=note['annualSegmentPolicyHash'],currentPassageIds=note['currentDefinitionPassages'],note='2025년 4분기 새 시장 중심 부문으로 재편한 연간 공시와 비교 재작성된 현재9개월 공시를 연결한다. CMBU·CDBU·MCBU·AEBU·기타 및 본사 미배분 손익을 각각 보존한다. 배분 방식·제품 구성 불변이나 유기 성장으로 승인하지 않는다.')
contract['cases']=[r for r in contract['cases'] if r['company']!='MU']+[record]
(stage/'data/segment-continuity.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n')
segment_history.ROOT=stage
h=segment_history.build(c,s['asOf']);c['segmentHistory']=h
(stage/'segment-candidate.json').write_text(json.dumps(h,ensure_ascii=False,indent=2)+'\n');(stage/'company-candidate.json').write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n')
print(h['status']);print([(r['id'],r['revenue']['value'],r['operatingIncome']['value']) for r in h['segments']]);print({k:{'residual':r.get('residual'),'periods':[p['residual'] for p in r.get('periods',[])]} for k,r in h['reconciliations'].items()})
