from pathlib import Path
import json,shutil
ROOT=Path(__file__).resolve().parents[3];STAGE=Path(__file__).resolve().parent
if not (ROOT/'equitylab/txn_operating.py').exists():raise RuntimeError('Integrate the reviewed TI candidate first')
if (ROOT/'equitylab/adi_operating.py').exists():raise RuntimeError('Do not repeat ADI integration')
pending={}
def edit(name,old,new):
 p=ROOT/name;s=pending.get(p,p.read_text())
 if s.count(old)!=1:raise ValueError(f'Ambiguous anchor: {name} {old[:70]}')
 pending[p]=s.replace(old,new)
edit('equitylab/operating_model.py','def build(c, as_of):\n','def build(c, as_of):\n    if c["id"] == "ADI":\n        from .adi_operating import build as adi\n\n        return adi(c, as_of)\n')
edit('app/operating-model.js','  function incentiveEvidence(m){',(STAGE/'adi-renderer.js').read_text()+'  function incentiveEvidence(m){')
edit('app/operating-model.js','${incentiveEvidence(m)}','${incentiveEvidence(m)}${analogEvidence(m)}')
p=ROOT/'app/styles.css';pending[p]=p.read_text()+'\n.operating-analog-evidence{margin:24px 0}.analog-chart-scroll{overflow-x:auto}.analog-chart-scroll svg{display:block;width:100%;min-width:780px}.operating-analog-evidence h3,.operating-analog-evidence h4{break-after:avoid}@media print{.analog-chart-scroll{overflow:visible}.analog-chart-scroll svg{min-width:0}.analog-market-group,.analog-scope-group{break-inside:avoid}}\n'
browser='''    await go('company/ADI');
    await expect('ADI has four revenue markets but one real profit segment', 'document.querySelectorAll(".analog-market-chart g[data-current]").length===4 && [...document.querySelectorAll(".analog-market-chart g[data-current]")].reduce((s,e)=>s+Number(e.dataset.current),0)===10805627000 && document.querySelector(".operating-segments").textContent.includes("단일")');
    await expect('ADI retains source disagreement and different interim cash detail', 'document.querySelector(".analog-sale-scope").textContent.includes("24.2") && document.querySelector(".analog-sale-scope").textContent.includes("24.4") && document.querySelector(".analog-scope-group").textContent.includes("1,592.044") && document.querySelector(".analog-cash-periods").textContent.includes("-0.941")');
    const adiBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=capexEnd]");e.value=8;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),adiBefore);checks.push('ADI reinvestment assumptions recompute source-bound cash');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('ADI restores researcher assumptions and preserves reported cash', 'Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===.08 && document.querySelector("#operating-message").textContent.includes("복원") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="ADI").operatingModel.bridge.reportedCfo===5545325000');
    await js('localStorage.removeItem("equity-operating-path-v1-ADI")');await click('#operating-reset');
    await viewport(390);await expect('ADI market chart scrolls without breaking mobile width', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".analog-chart-scroll").scrollWidth>document.querySelector(".analog-chart-scroll").clientWidth');await screenshotRegion('mobile-adi-operating.png','.operating-analog-evidence');await viewport(1440);
    await screenshotRegion('desktop-adi-operating.png','.operating-analog-evidence');await pdf('analog-devices.pdf');
'''
edit('scripts/check-live.mjs',"    await go('company/TXN');",browser+"    await go('company/TXN');")
pair='''    await go('compare/analog-manufacturing');
    await expect('TI ADI paired cash preserves government, acquisition and fiscal-window differences', '!!document.querySelector("#pair-result") && document.querySelector(".source-pair").textContent.includes("CHIPS") && document.querySelector(".source-pair").textContent.includes("Empower")');
    const analogBefore=await js('document.querySelector("#pair-result").textContent');
    await js('{const e=document.querySelectorAll("[data-pair-key=capexEnd]")[1];e.value=8;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#pair-result").textContent'),analogBefore);checks.push('Independent ADI reinvestment changes paired cash judgment');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Analog comparison restores exact independent assumptions', 'Number(document.querySelectorAll("[data-pair-key=capexEnd]")[1].dataset.exact)===.08 && document.querySelector("#pair-message").textContent.includes("복원")');
    await viewport(390);await expect('Analog comparison fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await pdf('comparison-analog.pdf');
'''
edit('scripts/check-live.mjs',"    await go('compare/software-contracts');",pair+"    await go('compare/software-contracts');")
for prefix in ['\n    ','\n        ']:
 edit('scripts/check-artifacts.py',prefix+'"texas-instruments",\n',prefix+'"analog-devices",'+prefix+'"comparison-analog",'+prefix+'"texas-instruments",\n')
check='''    if name == "analog-devices":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["최종시장매출과공시단일부문이익을구별", "산업", "통신", "-0.941", "24.2", "24.4", "1,592.044", "시장별이익률은미공시", "3.639"]:
            if term not in all_text:
                raise ValueError("ADI market/cash scope missing: " + term)
    if name == "comparison-analog":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["CHIPS", "Empower", "2026-06-30", "2026-08-01", "재투자", "8%"]:
            if term not in all_text:
                raise ValueError("Analog comparison assumption/source missing: " + term)
'''
edit('scripts/check-artifacts.py','    if name == "texas-instruments":',check+'    if name == "texas-instruments":')
edit('tests/test_operating_comparison.py','            salesforce_operating,','            salesforce_operating,\n            txn_operating,\n            adi_operating,')
edit('tests/test_operating_comparison.py','            ("CRM", salesforce_operating),','            ("CRM", salesforce_operating),\n            ("TXN", txn_operating),\n            ("ADI", adi_operating),')
edit('tests/test_operating_comparison.py','                "software-contracts",\n            },','                "software-contracts",\n                "analog-manufacturing",\n            },')
edit('tests/test_operating_comparison.py','                    "software-contracts",','                    "software-contracts",\n                    "analog-manufacturing",')
for name in ['README.md','docs/product-design.md','docs/local-runtime.md']:
 p=ROOT/name;pending[p]=p.read_text().replace('모델28개','모델29개').replace('모델은 28개','모델은 29개').replace('현금14쌍','현금15쌍').replace('현금 비교14쌍','현금 비교15쌍').replace('현금 비교 14쌍','현금 비교 15쌍').replace('ADI의 기업별 현금 모델은 아직 미완성이며 이 쌍의 현금 우열을 확정하지 않는다.','ADI의 별도 모델과 양쪽 가정 편집을 연결하되 공시 종료일·인수·지원 범위 차이를 보존한다.')
note='Analog Devices는 29번째 현금 모델이다. 네 최종시장 매출은 현재/전년9개월만 비교하고 시장별 이익을 만들지 않는다. 단일부문의 연결 총이익에서 연구개발·판매관리·영업비용 상각·순특별비용을 대사한다. 현금표 총상각을 한 번 가산하고 주식보상·인수 거래비용을 비용에 유지한다. 연간 운전자본7개 상세와 누적 공시 합계를 보존하며 매각이익 주석24.2/MD&A24.4백만 달러 차이를 임의 정상화하지 않는다. TI/ADI는 15번째 현금 가정 비교이며 다른 기간·지원·인수의 상대 선호는 연구자 판단이다.\n\n'
edit('docs/product-design.md','## 전체 목표와 남은 실질 산출물',note+'## 전체 목표와 남은 실질 산출물')
p=ROOT/'data/peer-studies.json';d=json.loads(pending.get(p,p.read_text()));s=next(x for x in d['studies'] if x['id']=='analog-manufacturing');side=s['sides'][1];side['passageIds']+=['33137871febd3e1f1625','745a45a28f2897c358ba','5538e8b8e5610ffbc80a','e469a4c44bc4618832c0']
s['priceImplication']='TXN의 영업현금에 이미 포함된 CHIPS 세금 혜택과 투자활동 수취를 한 번씩만 연결한다. ADI의 인수·총상각·거래비용을 독립 가정으로 둔다. 양쪽 총투자·세금·가동률을 편집하고 공시 종료일과 매각이익의 주석/MD&A 차이를 보존한다. 시장별 매출을 독립 마진으로 바꾸거나 같은 지원금을 상속하지 않는다.'
pending[p]=json.dumps(d,ensure_ascii=False,indent=2)+'\n'
copies=[(STAGE/'adi_operating.py',ROOT/'equitylab/adi_operating.py'),(STAGE/'test_adi_operating.py',ROOT/'tests/test_adi_operating.py')]+[(p,ROOT/'data/sources'/p.name) for p in (STAGE/'data/sources').glob('filing-0000006281-25-000153*')]
for src,dst in copies:
 if dst.exists() and dst.read_bytes()!=src.read_bytes():raise ValueError('Source conflict '+str(dst))
for src,dst in copies:shutil.copy2(src,dst)
for p,s in pending.items():p.write_text(s)
print('Integrated ADI29 and analog cash pair15. Verify before claiming usable output.')
