"""Integrate the reviewed Adobe candidate after the preceding run is finished."""
from pathlib import Path
import json
import shutil

ROOT=Path(__file__).resolve().parents[3]
STAGE=Path(__file__).resolve().parent
run=json.loads((ROOT/'artifacts/local/runs/20261002T051936327218Z/run.json').read_text())
if run['status']!='artifacts_verified':raise RuntimeError('Finish and inspect the Innotek run first')
if (ROOT/'equitylab/adobe_operating.py').exists():raise RuntimeError('Do not rerun this integration')
pending={}
def edit(name,old,new):
    p=ROOT/name;s=pending.get(p,p.read_text())
    if s.count(old)!=1:raise ValueError(f'Ambiguous integration anchor: {name} {old[:80]}')
    pending[p]=s.replace(old,new)

edit('equitylab/operating_model.py','def build(c, as_of):\n','def build(c, as_of):\n    if c["id"] == "ADBE":\n        from .adobe_operating import build as adobe\n\n        return adobe(c, as_of)\n')
edit('app/operating-model.js','  function manufacturingEvidence(m){',(STAGE/'creative-renderer.js').read_text()+'  function manufacturingEvidence(m){')
edit('app/operating-model.js','${manufacturingEvidence(m)}','${manufacturingEvidence(m)}${creativeEvidence(m)}')
p=ROOT/'app/styles.css';pending[p]=p.read_text()+'\n.operating-creative-evidence{margin:24px 0}.creative-chart-scroll{overflow-x:auto}.creative-chart-scroll svg{display:block;width:100%;min-width:800px}.operating-creative-evidence h3,.operating-creative-evidence h4{break-after:avoid}@media print{.creative-chart-scroll{overflow:visible}.creative-chart-scroll svg{min-width:0;break-inside:avoid}}\n'
browser='''    await go('company/ADBE');
    await expect('Adobe current revenue groups preserve service losses and all shared expenses', '[...document.querySelectorAll(".creative-profit-chart g[data-value]")].map(e=>Number(e.dataset.value)).join(",")==="22904000000,298000000,-23000000,-4694000000,-7147000000,-1918000000,-149000000,9271000000" && document.querySelector(".operating-segments").textContent.includes("단일 보고부문")');
    await expect('Adobe contract amortization stays in selling costs and broader cash accretion is not repeated', 'document.querySelector(".creative-amortization").textContent.includes("282") && document.querySelector(".creative-amortization").textContent.includes("828") && document.querySelector(".creative-amortization").textContent.includes("818") && document.querySelector(".creative-amortization").textContent.includes("-10") && document.querySelector(".creative-working").textContent.includes("2,081") && document.querySelector(".creative-working").textContent.includes("815")');
    const adobeBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=capexEnd]");e.value=12;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),adobeBefore);checks.push('Adobe acquisition intensity changes the future cash path');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Adobe saves exact source-bound acquisition assumptions and preserves historical CFO', 'Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===.12 && document.querySelector("#operating-message").textContent.includes("복원") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="ADBE").operatingModel.bridge.reportedCfo===10806000000');
    await js('localStorage.removeItem("equity-operating-path-v1-ADBE")');await click('#operating-reset');
    await viewport(390);await expect('Adobe costs chart scrolls locally on mobile', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".creative-chart-scroll").scrollWidth>document.querySelector(".creative-chart-scroll").clientWidth');await screenshotRegion('mobile-adobe-operating.png','.operating-creative-evidence');await viewport(1440);
    await screenshotRegion('desktop-adobe-operating.png','.operating-creative-evidence');await pdf('adobe.pdf');
'''
edit('scripts/check-live.mjs',"    await go('company/011070');",browser+"    await go('company/011070');")
edit('scripts/check-artifacts.py','    "oracle",\n    "lg-innotek",','    "oracle",\n    "adobe",\n    "lg-innotek",')
edit('scripts/check-artifacts.py','        "oracle",\n','        "oracle",\n        "adobe",\n')
edit('scripts/check-artifacts.py','        "sk-hynix",\n        "celltrion",','        "sk-hynix",\n        "lg-innotek",\n        "celltrion",')
artifact='''    if name == "adobe":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["보고부문통합뒤에도원가와공통비용을구분", "22.904", "9.271", "236", "282", "828", "818", "차이원인미배분", "1.8439%", "계약취득비순자산", "Semrush"]:
            if term not in all_text:
                raise ValueError("Adobe contract-cost evidence missing: " + term)
'''
edit('scripts/check-artifacts.py','    if name == "lg-innotek":',artifact+'    if name == "lg-innotek":')
for name in ['README.md','docs/product-design.md','docs/local-runtime.md']:
    p=ROOT/name;s=p.read_text().replace('모델25개','모델26개').replace('모델은 25개','모델은 26개');pending[p]=s
note='Adobe는 26번째 현금 모델이다. 단일 보고부문으로 통합된 현재 공시에서 구독·제품·서비스의 매출총이익과 공통 비용을 세 기간별로 대사한다. 서비스 손실과 주식보상·영업권 손상 비용을 보존한다. 현금표 감가·상각·증가분을 전부 미래 현금에 가산하지 않고, 마지막 연간 설비 상각 비율과 최근1년 무형상각을 나누어 사용한다. 계약 취득비 상각은 판매비에 남기고 순자산 추가 소요를 자금 가정에 연결한다. 연간 주석 합계와 현금표 차이, 인수 총대가·순현금·성장 범위는 별도로 표시한다.\n\n'
edit('docs/product-design.md','## 전체 목표와 남은 실질 산출물',note+'## 전체 목표와 남은 실질 산출물')
copies=[(STAGE/'adobe_operating.py',ROOT/'equitylab/adobe_operating.py'),(STAGE/'test_adobe_operating.py',ROOT/'tests/test_adobe_operating.py')]
copies.extend((p,ROOT/'data/sources'/p.name) for p in (STAGE/'data/sources').iterdir())
for src,dest in copies:
    if dest.exists() and dest.read_bytes()!=src.read_bytes():raise ValueError(f'Conflicting existing file {dest}')
for src,dest in copies:shutil.copy2(src,dest)
for p,s in pending.items():p.write_text(s)
print('Integrated Adobe26; run targeted tests, then freeze inputs and run full verification')
