"""Integrate the held-price Salesforce model after the Adobe run is verified."""
from pathlib import Path
import json
import shutil

ROOT=Path(__file__).resolve().parents[3]
STAGE=Path(__file__).resolve().parent
run=json.loads((ROOT/'artifacts/local/runs/20261002T053841513746Z/run.json').read_text())
if run['status']!='artifacts_verified':raise RuntimeError('Finish and inspect Adobe first')
if (ROOT/'equitylab/salesforce_operating.py').exists():raise RuntimeError('Do not rerun this integration')
pending={}
def edit(name,old,new):
    p=ROOT/name;s=pending.get(p,p.read_text())
    if s.count(old)!=1:raise ValueError(f'Ambiguous integration anchor: {name} {old[:80]}')
    pending[p]=s.replace(old,new)
edit('equitylab/operating_model.py','def build(c, as_of):\n','def build(c, as_of):\n    if c["id"] == "CRM":\n        from .salesforce_operating import build as salesforce\n\n        return salesforce(c, as_of)\n')
edit('app/operating-model.js','  function creativeEvidence(m){',(STAGE/'salesforce-renderer.js').read_text()+'  function creativeEvidence(m){')
edit('app/operating-model.js','${creativeEvidence(m)}','${creativeEvidence(m)}${salesforceEvidence(m)}')
old="'<p class=\"operating-security-hold\">증권별 권리 배분 또는 현재 유통주식수 범위가 미확정이므로 현금 경로가 양수여도 주당 가치와 현재 가격 요구액은 보류합니다.</p>'"
new="'<p class=\"operating-security-hold\">'+esc(m.priceHoldReason||'증권별 권리 배분 또는 현재 유통주식수 범위가 미확정이므로 현금 경로가 양수여도 주당 가치와 현재 가격 요구액은 보류합니다.')+'</p>'"
edit('app/operating-model.js',old,new)
old="'<section class=\"operating-implied-margins\"><h3>현재 가격에 필요한 사업부 마진</h3><p>증권별 권리·유통 수량 범위가 미확정이므로 현재 주가를 사업부 마진으로 역산하지 않습니다. 위 사업 현금 경로는 계속 편집할 수 있습니다.</p></section>'"
new="'<section class=\"operating-implied-margins\"><h3>현재 가격에 필요한 사업부 마진</h3><p>'+esc(m.priceHoldReason||'증권별 권리·유통 수량 범위가 미확정이므로 현재 주가를 사업부 마진으로 역산하지 않습니다.')+' 위 사업 현금 경로는 계속 편집할 수 있습니다.</p></section>'"
edit('app/operating-model.js',old,new)
p=ROOT/'app/styles.css';pending[p]=p.read_text()+'\n.operating-salesforce-evidence{margin:24px 0}.salesforce-chart-scroll{overflow-x:auto}.salesforce-chart-scroll svg{display:block;width:100%;min-width:800px}.operating-salesforce-evidence h3,.operating-salesforce-evidence h4{break-after:avoid}.salesforce-financing-scope{padding:16px;border-left:3px solid #ad8548;background:#faf5e9}.salesforce-debt th{max-width:320px;white-space:normal}.salesforce-debt small{display:block;font-weight:normal}@media print{.salesforce-chart-scroll{overflow:visible}.salesforce-chart-scroll svg{min-width:0;break-inside:avoid}.salesforce-financing-scope{break-inside:avoid}}\n'
edit('tests/test_operating_comparison.py','            oracle_operating,\n','            oracle_operating,\n            adobe_operating,\n            salesforce_operating,\n')
edit('tests/test_operating_comparison.py','            ("ORCL", oracle_operating),\n','            ("ORCL", oracle_operating),\n            ("ADBE", adobe_operating),\n            ("CRM", salesforce_operating),\n')
edit('tests/test_operating_comparison.py','\n                "cloud-build-operate",\n','\n                "cloud-build-operate",\n                "software-contracts",\n')
edit('tests/test_operating_comparison.py','\n                    "cloud-build-operate",\n','\n                    "cloud-build-operate",\n                    "software-contracts",\n')
p=ROOT/'data/peer-studies.json';d=json.loads(p.read_text());study=next(s for s in d['studies'] if s['id']=='software-contracts')
crm=next(s for s in study['sides'] if s['company']=='CRM');adobe=next(s for s in study['sides'] if s['company']=='ADBE')
for pid in ['d23dc3e2c9f3f15e7832','607f80f7312039c25400','287ff3ce2d63ecb41f26']:
    if pid not in crm['passageIds']:crm['passageIds'].append(pid)
for pid in ['8db6695981f504610b20','9f68f65109efc87d459f','8e255c106f24daef4730']:
    if pid not in adobe['passageIds']:adobe['passageIds'].append(pid)
study['tradeoff']+=' Salesforce는 사용권 상각과 리스 부채 현금 조정, 계약 취득비와 현재 차입금 이자를 함께 연결한다. Adobe는 계약 취득비 상각을 판매비에 남기고 순자산 자금 소요를 별도로 가정한다. 서로 다른 상각·지급 경로를 같은 현금 마진으로 단순 비교하지 않는다.'
study['priceImplication']+=' Salesforce의 금융의무 원금과 연간 금융리스 주석의 범위 차이 및 관련 이자가 대사되기 전 이 모델의 주당 계산은 보류한다. 인수 지출 제외는 동일 성장의 유지나 정상 투자 수준을 승인한 것이 아니다.'
study['discriminator']+=' 현재 차입 만기·차환, 금융의무와 리스 주석 범위, 계약 취득비의 현금·상각·순잔액을 같은 기간에 대조한다.'
pending[p]=json.dumps(d,ensure_ascii=False,indent=2)+'\n'
browser='''    await go('company/CRM');
    await expect('Salesforce removes strategic gains from operating cash and retains contract and ROU costs', '[...document.querySelectorAll(".salesforce-cash-chart g[data-value]")].map(e=>Number(e.dataset.value)).join(",")==="5633000000,-3171000000,1951000000,1173000000,1763000000,621000000,7970000000"');
    await expect('Salesforce financing obligations are not silently narrowed to lease principal', 'document.querySelector(".salesforce-financing-scope").textContent.includes("584") && document.querySelector(".salesforce-financing-scope").textContent.includes("367") && document.querySelector(".salesforce-financing-scope").textContent.includes("217") && document.querySelector(".operating-security-hold").textContent.includes("금융의무") && document.querySelector(".operating-implied-margins").textContent.includes("2.17억")');
    await expect('Salesforce debt table retains current floating rate and undrawn facility without an invented coupon', 'document.querySelectorAll(".salesforce-debt tbody tr").length===16 && document.querySelector(".salesforce-debt").textContent.includes("4.24%") && document.querySelector(".salesforce-debt").textContent.includes("미사용") && document.querySelector(".operating-salesforce-evidence").textContent.includes("1.824275")');
    await js('{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="CRM").operatingModel;for(const key of ["capexStart","capexEnd"]){const el=document.querySelector("[data-operating="+key+"]");el.value=m.salesforceEvidence.reinvestmentExcludingAcquisitionRatio*100;el.dispatchEvent(new Event("input",{bubbles:true}));}}');
    await expect('Salesforce acquisition exclusion can make cash positive but does not release its model scope hold', 'document.querySelector(".operating-years").textContent.includes("배분 가정 현금") && !document.querySelector("#operating-result").textContent.includes("가치를 영으로 확정") && document.querySelector(".operating-security-hold").textContent.includes("2.17억")');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Salesforce preserves editable cash assumptions and the financing scope hold after reload', 'document.querySelector("#operating-message").textContent.includes("복원") && document.querySelector(".operating-security-hold").textContent.includes("금융의무")');
    await js('localStorage.removeItem("equity-operating-path-v1-CRM")');await click('#operating-reset');
    await viewport(390);await expect('Salesforce funding table and graph fit the mobile page', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".salesforce-chart-scroll").scrollWidth>document.querySelector(".salesforce-chart-scroll").clientWidth');await screenshotRegion('mobile-salesforce-operating.png','.salesforce-financing-scope');await viewport(1440);await pdf('salesforce.pdf');
'''
edit('scripts/check-live.mjs',"    await go('company/ADBE');",browser+"    await go('company/ADBE');")
paired='''    await go('compare/software-contracts');
    await expect('CRM Adobe paired cash preserves different contract amortization and financing scopes', 'document.querySelector(".source-pair").textContent.includes("계약 취득비") && document.querySelector(".pair-security-hold").textContent.includes("2.17억") && !!document.querySelector("#pair-result")');
    await js('{const e=document.querySelectorAll("[data-pair-key=capexEnd]")[1];e.value=12;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Software comparison restores exact assumptions without approving held Salesforce price', 'Number(document.querySelectorAll("[data-pair-key=capexEnd]")[1].dataset.exact)===.12 && document.querySelector("#pair-message").textContent.includes("복원") && document.querySelector(".pair-security-hold").textContent.includes("금융의무")');
    await viewport(390);await expect('Software cash comparison fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await pdf('comparison-software.pdf');
'''
edit('scripts/check-live.mjs',"    await go('compare/enterprise-delivery');",paired+"    await go('compare/enterprise-delivery');")
edit('scripts/check-artifacts.py','\n    "adobe",\n','\n    "adobe",\n    "salesforce",\n    "comparison-software",\n')
edit('scripts/check-artifacts.py','\n        "adobe",\n','\n        "adobe",\n        "salesforce",\n        "comparison-software",\n')
artifact='''    if name == "salesforce":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["투자손익과구독사업의현금을분리", "3.171", "584", "367", "217", "612", "574", "4.24%", "1.824275", "미사용", "2.17억"]:
            if term not in all_text:
                raise ValueError("Salesforce financing scope evidence missing: " + term)
    if name == "comparison-software":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["계약취득비", "금융의무", "2.17억", "12%", "ARR"]:
            if term not in all_text:
                raise ValueError("Software cash comparison evidence missing: " + term)
'''
edit('scripts/check-artifacts.py','    if name == "adobe":',artifact+'    if name == "adobe":')
for name in ['README.md','docs/product-design.md','docs/local-runtime.md']:
    p=ROOT/name;s=p.read_text().replace('모델26개','모델27개').replace('모델은 26개','모델은 27개').replace('현금 비교13쌍','현금 비교14쌍').replace('현금 가정 비교13쌍','현금 가정 비교14쌍').replace('그중 13쌍','그중 14쌍');pending[p]=s
note='Salesforce는 27번째 현금 모델이며 Adobe와 14번째 현금 비교를 제공합니다. 순이익에 포함된 전략 투자 이익, 계약 취득비 상각·현금 취득, 사용권 상각과 운영리스 현금표 조정, 현재 채무의 고정·변동금리를 분리합니다. 현금표 금융의무 원금과 연간 금융리스 주석의 차이를 발견해 넓은 현금 지급을 유지하고 모델의 주당·역산은 보류합니다. 기존 회사 증권 식별과 이 모델의 자금 범위 보류를 구분합니다.\n\n'
edit('docs/product-design.md','## 전체 목표와 남은 실질 산출물',note+'## 전체 목표와 남은 실질 산출물')
copies=[(STAGE/'salesforce_operating.py',ROOT/'equitylab/salesforce_operating.py'),(STAGE/'test_salesforce_operating.py',ROOT/'tests/test_salesforce_operating.py')]
copies.extend((p,ROOT/'data/sources'/p.name) for p in (STAGE/'data/sources').iterdir())
for src,dest in copies:
    if dest.exists() and dest.read_bytes()!=src.read_bytes():raise ValueError(f'Conflicting file {dest}')
for src,dest in copies:shutil.copy2(src,dest)
for p,s in pending.items():p.write_text(s)
print('Integrated Salesforce27 / cash comparison14 with explicit financing scope hold; verification still required')
