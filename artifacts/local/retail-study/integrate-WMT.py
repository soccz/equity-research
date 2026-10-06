"""Integrate reviewed Walmart candidate only after the preceding frozen run ends."""
from pathlib import Path
import json
import shutil

ROOT=Path(__file__).resolve().parents[3]
STAGE=Path(__file__).resolve().parent
if (ROOT/'equitylab/walmart_operating.py').exists():raise RuntimeError('Do not repeat Walmart integration')
pending={}
def edit(name,old,new):
    p=ROOT/name;s=pending.get(p,p.read_text())
    if s.count(old)!=1:raise ValueError(f'Ambiguous anchor {name}: {old[:65]}')
    pending[p]=s.replace(old,new)

edit('equitylab/operating_model.py','def build(c, as_of):\n','def build(c, as_of):\n    if c["id"] == "WMT":\n        from .walmart_operating import build as walmart\n\n        return walmart(c, as_of)\n')
edit('app/operating-model.js','  function warehouseEvidence(m){',(STAGE/'walmart-renderer.js').read_text()+'  function warehouseEvidence(m){')
edit('app/operating-model.js','${warehouseEvidence(m)}','${warehouseEvidence(m)}${retailerEvidence(m)}')
edit('app/operating-model.js',"    if(m.normalizationPath)document.querySelector('#operating-known-gain').onclick=",'''    if(m.retailerEvidence)document.querySelector('#operating-refund-sensitivity').onclick=()=>{try{const a=read();a.segments[0].marginEnd=m.segments[0].margin-m.retailerEvidence.tariffRefundApprox/m.facts.revenue.value;write(a);update();message('환급 총액 비율만 5년차 마진에서 제외한 조건부 민감도입니다. 고객 가격 효과는 미대사이며 정상 이익·주당 계산 승인이 아닙니다.');}catch(e){message(e.message);}};
    if(m.normalizationPath)document.querySelector('#operating-known-gain').onclick=''')
p=ROOT/'app/styles.css';pending[p]=p.read_text()+'\n.operating-retailer-evidence{margin:24px 0}.retailer-chart-scroll{overflow-x:auto}.retailer-chart-scroll svg{display:block;width:100%;min-width:790px}.operating-retailer-evidence h3,.operating-retailer-evidence h4{break-after:avoid}@media print{.retailer-chart-scroll{overflow:visible}.retailer-chart-scroll svg{min-width:0}.retailer-refund-group,.retailer-segment-group,.retailer-membership-group,.retailer-lease-group{break-inside:avoid}#operating-refund-sensitivity{display:none}}\n'
browser='''    await go('company/WMT');
    await expect('Walmart source segments reconcile corporate income without a fictitious business margin', 'document.querySelectorAll(".retailer-segments tbody tr").length===5 && document.querySelector(".retailer-segments").textContent.includes("0.049") && document.querySelectorAll(".operating-segments tbody tr").length===1');
    await expect('Walmart gross refund sensitivity preserves unknown pricing use', 'document.querySelectorAll(".retailer-refund-chart g[data-profit]").length===3 && Number(document.querySelectorAll(".retailer-refund-chart g")[2].dataset.profit)===13976000000 && document.querySelector(".retailer-refund-group").textContent.includes("정상 영업이익이 아닙니다")');
    await expect('Walmart interest scope and membership differences stay visible', 'document.querySelector(".retailer-lease").textContent.includes("0.098") && document.querySelector(".retailer-membership-group").textContent.includes("4.4") && document.querySelector(".retailer-membership-group").textContent.includes("6.75")');
    const walmartBefore=await js('document.querySelector("#operating-result").textContent');await click('#operating-refund-sensitivity');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),walmartBefore);checks.push('Walmart refund sensitivity changes cash with price hold retained');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Walmart restores exact gross sensitivity and keeps source-based price hold', '(()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="WMT").operatingModel,a=JSON.parse(localStorage.getItem("equity-operating-path-v1-WMT")).assumptions;return Math.abs(a.segments[0].marginEnd-(m.segments[0].margin-2900000000/m.facts.revenue.value))<1e-12 && window.EquityOperatingModel.calculate(m,a).price===null && document.querySelector("#operating-message").textContent.includes("복원");})()');
    await js('localStorage.removeItem("equity-operating-path-v1-WMT")');await click('#operating-reset');
    await viewport(390);await expect('Walmart evidence is scrollable on mobile without page overflow', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".retailer-chart-scroll").scrollWidth>document.querySelector(".retailer-chart-scroll").clientWidth');await screenshotRegion('mobile-walmart-operating.png','.operating-retailer-evidence');await viewport(1440);
    await screenshotRegion('desktop-walmart-operating.png','.operating-retailer-evidence');await pdf('walmart.pdf');
'''
edit('scripts/check-live.mjs',"    await go('company/COST');",browser+"    await go('company/COST');")
pair='''    await go('compare/retail-repeat');
    await expect('Retail comparison preserves membership scope and Walmart financing hold', '!!document.querySelector("#pair-result") && document.querySelector(".source-pair").textContent.includes("순수 회원비") && document.querySelector(".pair-security-hold").textContent.includes("금융리스")');
    const retailBefore=await js('document.querySelector("#pair-result").textContent');
    await js('{const e=document.querySelectorAll("[data-pair-key=capexEnd]")[1];e.value=5;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#pair-result").textContent'),retailBefore);checks.push('Walmart reinvestment changes its own side of retail comparison');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Retail comparison restores separate assumptions', 'Number(document.querySelectorAll("[data-pair-key=capexEnd]")[1].dataset.exact)===.05 && document.querySelector("#pair-message").textContent.includes("복원")');
    await viewport(390);await expect('Retail comparison fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await pdf('comparison-retail.pdf');
'''
edit('scripts/check-live.mjs',"    await go('compare/analog-manufacturing');",pair+"    await go('compare/analog-manufacturing');")
for prefix in ['\n    ','\n        ']:edit('scripts/check-artifacts.py',prefix+'"costco",\n',prefix+'"walmart",'+prefix+'"comparison-retail",'+prefix+'"costco",\n')
check='''    if name == "walmart":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["관세환급과고객가격투자", "13.976", "0.049", "0.098", "4.4", "6.75", "자료미확인", "정상영업이익이아닙니다"]:
            if term not in all_text:
                raise ValueError("Walmart source or scope missing: " + term)
    if name == "comparison-retail":
        all_text = "".join("".join(p.get_text().split()) for p in doc)
        for term in ["순수회원비", "관세환급", "금융리스", "Costco", "Walmart"]:
            if term not in all_text:
                raise ValueError("Retail comparison scope missing: " + term)
'''
edit('scripts/check-artifacts.py','    if name == "costco":',check+'    if name == "costco":')
edit('tests/test_operating_comparison.py','            adi_operating,\n','            adi_operating,\n            costco_operating,\n            walmart_operating,\n')
edit('tests/test_operating_comparison.py','            ("ADI", adi_operating),\n','            ("ADI", adi_operating),\n            ("COST", costco_operating),\n            ("WMT", walmart_operating),\n')
for prefix in ['                ','                    ']:edit('tests/test_operating_comparison.py',prefix+'"analog-manufacturing",\n',prefix+'"analog-manufacturing",\n'+prefix+'"retail-repeat",\n')
p=ROOT/'data/peer-studies.json';d=json.loads(p.read_text());rows=d['studies'] if 'studies' in d else d['pairs'];r=next(r for r in rows if r['id']=='retail-repeat')
r['tradeoff']='Costco의 순수 회원비와 Walmart의 회원비 및 기타수입 전체는 범위가 다르다. Costco의 갱신은 과거 7~18개월 관측이며 미래 확률이 아니다. Walmart의 관세환급은 고객 가격·원가 완화에도 쓰여 총액 제거만으로 정상 이익을 확정할 수 없다.'
r['priceImplication']='상품·회원·광고의 이익 기여와 매장·설비·재고 부담을 구분한다. 양쪽 사업 현금 가정의 종료일과 자금 잔액 범위가 다르며 Walmart의 금융리스·기타 금융활동 범위가 미대사인 동안 주당·가격 역산을 보류한다.'
w=next(s for s in r['sides'] if s['company']=='WMT');w['passageIds']+=['8697bb7798567908b8de','aead6539ce98248353f2','2ee01a4888371f6a605f'];w['reading']+=' 관세환급을 원가 감소로 기록했으며 상당 부분을 고객 가격·원가 완화에 사용했다고 설명한다. 사용 금액은 미정량이다.'
pending[p]=json.dumps(d,ensure_ascii=False,indent=2)+'\n'
p=ROOT/'data/business-insights.json';d=json.loads(p.read_text());r=next(r for r in d['cases'] if r['company']=='WMT');r['passageIds']+=['8697bb7798567908b8de','aead6539ce98248353f2','2ee01a4888371f6a605f'];r['interpretation']+=' 환급 중 고객 가격·원가 완화에 사용된 금액이 미공시이므로, 환급 총액만 제거해 남은 이익을 정상 영업이익으로 부를 수 없다.';r['priceImplication']+=' 금융리스 원금의 최신 기간과 넓은 기타 금융활동 지급 범위가 확인될 때까지 이 현금 모형의 주당·가격 역산은 보류한다.';pending[p]=json.dumps(d,ensure_ascii=False,indent=2)+'\n'
for name in ['README.md','docs/product-design.md','docs/local-runtime.md']:
 p=ROOT/name;s=p.read_text().replace('모델31개','모델32개').replace('모델은 31개','모델은 32개').replace('현금 가정 비교15쌍','현금 가정 비교16쌍').replace('현금 비교15쌍','현금 비교16쌍').replace('아날로그 제조까지 15쌍','아날로그 제조와 Costco·Walmart의 회원제 소매까지 16쌍').replace('그중 15쌍','그중 16쌍').replace('나머지 6쌍','나머지 5쌍');pending[p]=s
note='Walmart는 32번째 현금 모델이며 Costco와 16번째 현금 가정 비교를 제공한다. 연결 상품·회원비 및 기타수입과 원가·판매관리비, 세 사업부 및 본사 수입·비용을 대사한다. 관세환급 총액만 제거하는 민감도는 미정량 고객 가격 효과 때문에 정상 이익이 아니다. 순수 회원비와 전체 기타수입, 연간 리스 원금 비율 대용·미확인 최근1년 실제값, 금융리스 이자 본표/주석 차이를 보존한다. 범위 대사 전 전체 주당·역산은 보류한다.\n\n'
edit('docs/product-design.md','## 전체 목표와 남은 실질 산출물',note+'## 전체 목표와 남은 실질 산출물')
copies=[(STAGE/'walmart_operating.py',ROOT/'equitylab/walmart_operating.py'),(STAGE/'test_walmart_operating.py',ROOT/'tests/test_walmart_operating.py')]+[(p,ROOT/'data/sources'/p.name) for p in (STAGE/'data/sources').glob('filing-0000104169-26-000055*')]
for src,dst in copies:
 if dst.exists() and src.read_bytes()!=dst.read_bytes():raise ValueError('Source conflict '+str(dst))
for src,dst in copies:shutil.copy2(src,dst)
for p,s in pending.items():p.write_text(s)
print('Integrated Walmart32 and retail comparison16; frozen full verification required')
