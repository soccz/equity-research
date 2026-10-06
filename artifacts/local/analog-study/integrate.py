"""Integrate the TI candidate only after the software run and visual review."""
from pathlib import Path
import json,shutil
ROOT=Path(__file__).resolve().parents[3];STAGE=Path(__file__).resolve().parent
run=json.loads((ROOT/'artifacts/local/runs/20261002T071332632353Z/run.json').read_text())
if run['status']!='artifacts_verified':raise RuntimeError('Finish software integrated verification first')
if not (ROOT/'artifacts/local/salesforce-study/visual-review.json').exists():raise RuntimeError('Review the software PDFs first')
if (ROOT/'equitylab/txn_operating.py').exists():raise RuntimeError('TI is already integrated')
pending={}
def edit(name,old,new):
 p=ROOT/name;s=pending.get(p,p.read_text())
 if s.count(old)!=1:raise ValueError(f'Ambiguous anchor: {name} {old[:70]}')
 pending[p]=s.replace(old,new)
edit('equitylab/operating_model.py','def build(c, as_of):\n','def build(c, as_of):\n    if c["id"] == "TXN":\n        from .txn_operating import build as ti\n\n        return ti(c, as_of)\n')
edit('app/operating-model.js','  function creativeEvidence(m){',(STAGE/'incentive-renderer.js').read_text()+'  function creativeEvidence(m){')
edit('app/operating-model.js','${creativeEvidence(m)}','${creativeEvidence(m)}${incentiveEvidence(m)}')
p=ROOT/'app/styles.css';pending[p]=p.read_text()+'\n.operating-incentive-evidence{margin:24px 0}.incentive-chart-scroll{overflow-x:auto}.incentive-chart-scroll svg{display:block;width:100%;min-width:780px}.operating-incentive-evidence h3,.operating-incentive-evidence h4{break-after:avoid}@media print{.incentive-chart-scroll{overflow:visible}.incentive-chart-scroll svg{min-width:0}.incentive-chart-group,.incentive-future-scope{break-inside:avoid}}\n'
browser='''    await go('company/TXN');
    await expect('TI reconciles CFO, separate investment incentives and already-included tax benefits', '[...document.querySelectorAll(".incentive-cash-chart g[data-value]")].map(e=>Number(e.dataset.value)).join(",")==="8667000000,5355000000,6534000000,4922000000" && document.querySelector(".incentive-definition").textContent.includes("이중 계산")');
    await expect('TI preserves three fiscal windows, corporate items and annual depreciation benefit', 'document.querySelector(".incentive-periods").textContent.includes("2025-12-31") && document.querySelector(".incentive-periods").textContent.includes("0.301") && document.querySelector(".incentive-future-scope").textContent.includes("0.353") && document.querySelector(".incentive-working").textContent.includes("6.445")');
    const tiBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=capexEnd]");e.value=10;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),tiBefore);checks.push('TI gross reinvestment assumption changes future cash');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('TI restores exact source-bound assumptions without changing historical incentive cash', 'Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===.1 && document.querySelector("#operating-message").textContent.includes("복원") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="TXN").operatingModel.incentiveEvidence.issuerFreeCash===6534000000');
    await js('localStorage.removeItem("equity-operating-path-v1-TXN")');await click('#operating-reset');
    await viewport(390);await expect('TI incentive evidence scrolls inside its mobile container', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".incentive-chart-scroll").scrollWidth>document.querySelector(".incentive-chart-scroll").clientWidth');await screenshotRegion('mobile-ti-operating.png','.operating-incentive-evidence');await viewport(1440);
    await screenshotRegion('desktop-ti-operating.png','.operating-incentive-evidence');await pdf('texas-instruments.pdf');
'''
edit('scripts/check-live.mjs',"    await go('company/CRM');",browser+"    await go('company/CRM');")
edit('scripts/check-artifacts.py','\n    "adobe",\n','\n    "texas-instruments",\n    "adobe",\n')
edit('scripts/check-artifacts.py','        "adobe",\n','        "texas-instruments",\n        "adobe",\n')
check='''    if name == "texas-instruments":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["세금혜택과투자지원금을한번씩만연결", "8.667", "6.534", "4.922", "0.433", "1.179", "0.353", "6.445", "2025-12-31", "이미포함된세금혜택", "이중계산"]:
            if term not in all_text:
                raise ValueError("TI incentive cash evidence missing: " + term)
'''
edit('scripts/check-artifacts.py','    if name == "salesforce":',check+'    if name == "salesforce":')
for name in ['README.md','docs/product-design.md','docs/local-runtime.md']:
 p=ROOT/name;pending[p]=p.read_text().replace('모델27개','모델28개').replace('모델은 27개','모델은 28개')
note='Texas Instruments는 28번째 현금 모델이다. 아날로그·임베디드·기타의 연간/반기 사업 이익과 현금을 대사하고 CHIPS 납부 세금 감소(CFO 포함)와 투자활동 수취를 분리한다. 회사 정의 FCF·총설비 지출·CHIPS 제외 지급/수취 민감도를 별도로 표시한다. 감가상각 순액과 이미 포함된 혜택을 다시 가산하지 않으며 정부 지원 부재의 인과 추정이나 정상 현금으로 승격하지 않는다. 기타 투자 순지출은 범주를 좁게 단정하지 않고 미래 임시 부담에 포함한다. ADI의 기업별 현금 모델은 아직 미완성이며 이 쌍의 현금 우열을 확정하지 않는다.\n\n'
edit('docs/product-design.md','## 전체 목표와 남은 실질 산출물',note+'## 전체 목표와 남은 실질 산출물')
p=ROOT/'data/peer-studies.json';d=json.loads(p.read_text());s=next(x for x in d['studies'] if x['id']=='analog-manufacturing');side=s['sides'][0]
side['passageIds']+=['81b3e9e3a4f616fa73cd','dbf461f9a059862c8a3a','20e572529ffe41399b6e']
s['priceImplication']='TXN의 영업현금에 이미 포함된 CHIPS 세금 혜택과 투자활동 수취를 한 번씩만 연결한다. 총투자·지원 수취·세금·가동률을 따로 가정하고 회사의 연간 투자 전망을 최근1년 실적과 섞지 않는다. ADI의 인수·상각·지원 범위까지 대사하기 전 두 기업의 미래 현금 우열을 보류한다.'
pending[p]=json.dumps(d,ensure_ascii=False,indent=2)+'\n'
copies=[(STAGE/'txn_operating.py',ROOT/'equitylab/txn_operating.py'),(STAGE/'test_txn_operating.py',ROOT/'tests/test_txn_operating.py')]+[(p,ROOT/'data/sources'/p.name) for p in (STAGE/'data/sources').glob('filing-0000097476-26-000059*')]
for src,dest in copies:
 if dest.exists() and dest.read_bytes()!=src.read_bytes():raise ValueError('Source conflict '+str(dest))
for src,dest in copies:shutil.copy2(src,dest)
for p,s in pending.items():p.write_text(s)
print('Integrated TI28. Freeze after targeted verification and run full outputs.')
