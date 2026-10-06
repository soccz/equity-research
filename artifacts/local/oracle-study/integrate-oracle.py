"""Apply the reviewed candidate only after the preceding frozen run succeeds."""
from pathlib import Path
import json, shutil

ROOT=Path(__file__).resolve().parents[3]
STAGE=Path(__file__).resolve().parent
run=json.loads((ROOT/'artifacts/local/runs/20261002T043944903765Z/run.json').read_text())
if run['status']!='artifacts_verified':raise SystemExit('Keep engine frozen: preceding run has not passed')

def replace(file,old,new):
 p=ROOT/file;s=p.read_text()
 if old not in s:raise ValueError('Missing edit anchor '+str(file))
 p.write_text(s.replace(old,new,1))

shutil.copyfile(STAGE/'oracle_operating.py',ROOT/'equitylab/oracle_operating.py')
shutil.copyfile(STAGE/'test_oracle_operating.py',ROOT/'tests/test_oracle_operating.py')
for p in (STAGE/'data/sources').iterdir():shutil.copyfile(p,ROOT/'data/sources'/p.name)
replace('equitylab/operating_model.py','def build(c, as_of):\n','def build(c, as_of):\n    if c["id"] == "ORCL":\n        from .oracle_operating import build as oracle\n\n        return oracle(c, as_of)\n')
old='    if any(\n        not 0 <= a[k] <= 1\n        for k in ("depreciation", "capexStart", "capexEnd", "leaseStart", "leaseEnd")\n    ):\n        raise ValueError("Invalid asset or lease intensity")'
new='''    capex_limit = model.get("capexLimit", 1)
    if type(capex_limit) not in (int, float) or not math.isfinite(capex_limit) or not 1 <= capex_limit <= 3:
        raise ValueError("Invalid source-specific capex limit")
    if any(not 0 <= a[k] <= 1 for k in ("depreciation", "leaseStart", "leaseEnd")) or any(not 0 <= a[k] <= capex_limit for k in ("capexStart", "capexEnd")):
        raise ValueError("Invalid asset or lease intensity")'''
replace('equitylab/operating_model.py',old,new)
replace('app/operating-model.js',"if(['depreciation','capexStart','capexEnd','leaseStart','leaseEnd'].some(k=>a[k]<0||a[k]>1)","const capexLimit=m.capexLimit===undefined?1:m.capexLimit;if(typeof capexLimit!=='number'||!Number.isFinite(capexLimit)||capexLimit<1||capexLimit>3)throw Error('원문별 재투자 입력 범위를 확인하세요.');\n    if(['depreciation','leaseStart','leaseEnd'].some(k=>a[k]<0||a[k]>1)||['capexStart','capexEnd'].some(k=>a[k]<0||a[k]>capexLimit)")
for file in ['app/operating-model.js','app/comparison-workspace.js']:
 for key in ['capexStart','capexEnd']:
  label='1년차 ' if key=='capexStart' else '5년차 '
  old="['"+key+"','"+label+"'+(m.capexLabel||'설비 취득')+' / 매출',0,100]"
  replace(file,old,old.replace(',0,100]',',0,100*(m.capexLimit??1)]'))
replace('app/operating-model.js','  function contentEvidence(m){',(STAGE/'capacity-renderer.js').read_text()+'  function contentEvidence(m){')
replace('app/operating-model.js','${contentEvidence(m)}${customerFundEvidence(m)}','${contentEvidence(m)}${capacityEvidence(m)}${customerFundEvidence(m)}')
p=ROOT/'app/styles.css';p.write_text(p.read_text()+'\n.operating-capacity-evidence{margin:24px 0}.capacity-chart-scroll{overflow-x:auto}.capacity-chart-scroll svg{display:block;width:100%;min-width:730px}.operating-capacity-evidence h3,.operating-capacity-evidence h4{break-after:avoid}@media print{.capacity-chart-scroll{overflow:visible}.capacity-chart-scroll svg{min-width:0;break-inside:avoid}}\n')
p=ROOT/'data/peer-studies.json';b=json.loads(p.read_text());new=json.loads((STAGE/'peer-study.json').read_text());assert new['id'] not in {s['id'] for s in b['studies']};b['studies'].append(new);p.write_text(json.dumps(b,ensure_ascii=False,indent=2)+'\n')
replace('tests/test_peer_studies.py','self.assertEqual(len(rows), 20)','self.assertEqual(len(rows), 21)')
replace('tests/test_operating_comparison.py','            sds_operating,','            sds_operating,\n            oracle_operating,')
replace('tests/test_operating_comparison.py','            ("018260", sds_operating),','            ("018260", sds_operating),\n            ("ORCL", oracle_operating),')
replace('tests/test_operating_comparison.py','                "enterprise-delivery",','                "enterprise-delivery",\n                "cloud-build-operate",')
replace('tests/test_operating_comparison.py','                    "innovator-biosimilar",','                    "innovator-biosimilar",\n                    "cloud-build-operate",')
replace('scripts/check-dossier.mjs','  if(m.equityInvestmentPath)changes.push(',"  if(m.capexLimit>1)changes.push({capexStart:1.5,capexEnd:1.2},{capexStart:2,capexEnd:.15});\n  if(m.equityInvestmentPath)changes.push(")
for file in ['README.md','docs/product-design.md','docs/local-runtime.md']:
 p=ROOT/file;s=p.read_text()
 for old,new in [('모델은 23개','모델은 24개'),('모델23개','모델24개'),('20쌍','21쌍'),('12쌍','13쌍')]:s=s.replace(old,new)
 s=s.replace('ServiceNow·Qualcomm·Netflix까지','ServiceNow·Qualcomm·Netflix·Oracle까지').replace('ServiceNow·삼성SDS의 기업용 서비스까지','ServiceNow·삼성SDS의 기업용 서비스와 Oracle·삼성SDS의 인프라 소유·운영까지')
 p.write_text(s)
p=ROOT/'docs/product-design.md';s=p.read_text();anchor='## 전체 목표와 남은 실질 산출물';s=s.replace(anchor,'Oracle은 24번째 현금 모델이다. 세 기간의 부문 마진·미배분 비용·연결 손익·영업현금을 대사하고 고객 선급 금융 조정과 총수령 설명을 구분한다. 설비 지출이 매출을 넘는 원문 비율을 보존하도록 이 모델의 재투자 범위를 200%로 두며, 음수 경로의 가치를 영으로 바꾸지 않는다. 금융리스 총지급−발생이자는 원금 대용이고 실제 원금으로 승인하지 않는다. 개시 전 리스·우선주·차환과 미확인 운전자본 범위를 표시한다. 삼성SDS와 13번째 현금 비교는 자체 자산과 정부 소유 GPU 운영을 구별하며 양쪽 권리 배분 미확정으로 주당 계산을 보류한다.\n\n'+anchor,1);p.write_text(s)
print('Integrated candidate, calculator, research pair and docs. Browser assertions still to add before any run.')
