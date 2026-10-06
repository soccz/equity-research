/* Paired research assumptions and private, source-bound judgment history. */
(() => {
  const KEY='equity-paired-research-v1',VERSION='paired-research-notes-v1';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const n=(v,d=1)=>v==null?'계산 보류':(v===0?0:v).toLocaleString('ko-KR',{maximumFractionDigits:d});
  const pct=v=>v==null?'계산 보류':n(v*100)+'%';
  const sha=async text=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))].map(v=>v.toString(16).padStart(2,'0')).join('');
  const noteFields={thesis:'잠정 비교 판단과 사업 근거',countercase:'이 판단에 가장 강한 반론',changes:'판단을 바꿀 관측과 확인 시점'};
  window.addEventListener('beforeprint',()=>document.querySelectorAll('.pair-selected:not([open])').forEach(e=>{e.dataset.printOpened='1';e.open=true;}));
  window.addEventListener('afterprint',()=>document.querySelectorAll('.pair-selected[data-print-opened]').forEach(e=>{e.open=false;delete e.dataset.printOpened;}));
  const stats=['price','terminalCash','terminalRevenue','requiredTerminalCash','terminalCashMargin','requiredCashMargin','marginGap','explicitCoverage','valueToMarket'];
  function summarize(m,a){
    const r=window.EquityOperatingModel.calculate(m,a),rev=r.terminal.revenue,market=m.security.marketCapProxy;
    return {price:r.price,terminalCash:r.terminal.cash,terminalRevenue:rev,requiredTerminalCash:r.requiredTerminalCash,terminalCashMargin:rev>0?r.terminal.cash/rev:null,requiredCashMargin:rev>0&&r.requiredTerminalCash!=null?r.requiredTerminalCash/rev:null,marginGap:rev>0&&r.terminalCashGap!=null?r.terminalCashGap/rev:null,explicitCoverage:market?r.explicitPv/market:null,valueToMarket:market&&r.equityValue?r.equityValue/market:null};
  }
  function validateRecord(r){
    if(!r||!/^[-a-zA-Z0-9]{10,80}$/.test(r.id)||!/^[-a-z0-9]{3,80}$/.test(r.study)||!Number.isFinite(Date.parse(r.recordedAt))||!['미결정','왼쪽 조건부 선호','오른쪽 조건부 선호','양쪽 관찰'].includes(r.opinion))throw Error('비교 기록 식별자·날짜·의견 오류');
    for(const k of ['snapshotHash','comparisonHash','studyHash'])if(!/^[a-f0-9]{64}$/.test(r[k]))throw Error('비교 근거 버전 오류');
    for(const k of Object.keys(noteFields))if(typeof r.notes?.[k]!=='string'||r.notes[k].length>12000)throw Error('비교 판단 문장 오류');
    if(!Array.isArray(r.sides)||r.sides.length!==2||new Set(r.sides.map(s=>s.company)).size!==2)throw Error('두 기업의 기록이 필요합니다.');
    for(const s of r.sides){
      if(!/^[A-Z0-9]{1,10}$/.test(s.company)||!['USD','KRW'].includes(s.currency)||!Array.isArray(s.period)||s.period.length!==2||!s.period.every(v=>/^\d{4}-\d{2}-\d{2}$/.test(v))||!Array.isArray(s.evidence)||s.evidence.length>30)throw Error('기업·기간·근거 오류');
      for(const k of ['modelHash','corpusHash'])if(!/^[a-f0-9]{64}$/.test(s[k]))throw Error('기업 근거 해시 오류');
      if(!s.assumptions||typeof s.assumptions!=='object'||!Array.isArray(s.assumptions.segments))throw Error('사업 가정 누락');
      for(const k of stats)if(s.result?.[k]!==null&&(typeof s.result?.[k]!=='number'||!Number.isFinite(s.result[k])))throw Error('저장 계산 결과 형식 오류');
      for(const e of s.evidence){
        const url=new URL(e.sourceUrl);
        if(!/^[a-f0-9]{20}$/.test(e.id)||!['www.sec.gov','dart.fss.or.kr'].includes(url.hostname)||url.protocol!=='https:'||!/^([a-f0-9]{64})$/.test(e.sourceHash)||typeof e.text!=='string'||e.text.length>50000)throw Error('비교 원문 형식 오류');
      }
    }
    return r;
  }
  function validateStore(s){
    if(s?.version!==VERSION||!Array.isArray(s.records)||s.records.length>500||!s.drafts||typeof s.drafts!=='object'||Array.isArray(s.drafts)||Object.keys(s.drafts).length>100)throw Error('비교 기록 파일 형식·크기 오류');
    const ids=new Set();for(const r of s.records){validateRecord(r);if(ids.has(r.id))throw Error('기록 ID 중복');ids.add(r.id);}
    for(const [k,r] of Object.entries(s.drafts)){validateRecord(r);if(k!==r.study)throw Error('임시 기록의 비교 대상 불일치');}
    return s;
  }
  function readStore(){return validateStore(JSON.parse(localStorage.getItem(KEY)||JSON.stringify({version:VERSION,records:[],drafts:{}})));}
  function writeStore(s){validateStore(s);localStorage.setItem(KEY,JSON.stringify(s));}
  async function exportText(){const bundle={...readStore(),exportedAt:new Date().toISOString()};return JSON.stringify({...bundle,checksum:await sha(JSON.stringify(bundle))},null,2);}
  async function importText(text){
    if(text.length>12_000_000)throw Error('가져올 기록은 12MB 이내여야 합니다.');
    const {checksum,...bundle}=JSON.parse(text);if(await sha(JSON.stringify(bundle))!==checksum)throw Error('비교 기록 파일의 해시가 다릅니다.');
    validateStore(bundle);const current=readStore(),next=structuredClone(current);let count=0;
    for(const r of bundle.records){const old=next.records.find(x=>x.id===r.id);if(old&&JSON.stringify(old)!==JSON.stringify(r))throw Error('같은 ID의 다른 기록이 있어 가져오기를 중단했습니다.');if(!old){next.records.push(r);count++;}}
    for(const [id,draft] of Object.entries(bundle.drafts)){if(!next.drafts[id])next.drafts[id]=draft;else if(JSON.stringify(next.drafts[id])!==JSON.stringify(draft)){
      // Preserve a conflicting imported draft as a separate historical entry.
      const saved={...draft,id:'import-'+await sha(JSON.stringify(draft))};
      if(!next.records.some(r=>r.id===saved.id)){next.records.push(saved);count++;}
    }}
    writeStore(next);return count;
  }
  function input(side,key,value,label,min,max){return `<label>${esc(label)}<input type="number" step="any" min="${min}" max="${max}" value="${Number((value*100).toFixed(3))}" data-pair-side="${side}" data-pair-key="${key}" data-exact="${value}"><small>% · 편집 가능한 연구 가정</small></label>`;}
  function cashSpecs(m){
    const keys=[['tax','세율',0,60],['netInterest',(m.netInterestLabel||'순이자')+' / 매출',-20,20],['depreciation','상각 / 매출',0,100],['workingCapital','추가 매출당 영업자금 소요',-50,100],['capexStart','1년차 '+(m.capexLabel||'설비 취득')+' / 매출',0,100],['capexEnd','5년차 '+(m.capexLabel||'설비 취득')+' / 매출',0,100],['leaseStart','1년차 '+(m.leaseLabel||'리스 원금')+' / 매출',0,100],['leaseEnd','5년차 '+(m.leaseLabel||'리스 원금')+' / 매출',0,100],['discount','주주 요구수익률',.1,30],['terminal','영구 매출 성장률',0,29]];
    if(m.consolidationPath)keys.push(['eliminationStart','1년차 내부매출 제거 / 부문 총매출',0,99.9],['eliminationEnd','5년차 내부매출 제거 / 부문 총매출',0,99.9],['otherProfitStart','1년차 기타 이익 / 연결매출',-10,10],['otherProfitEnd','5년차 기타 이익 / 연결매출',-10,10],['minority','비지배 배분 / 연결매출',0,100]);
    if(m.unallocatedPath)keys.push(['corporateStart','1년차 '+(m.corporateLabel||'본사 순비용')+' / 매출',0,100],['corporateEnd','5년차 '+(m.corporateLabel||'본사 순비용')+' / 매출',0,100]);
    if(m.normalizationPath)keys.push(['excludedProfitStart','1년차 별도 제외 영업이익 / 매출',0,50],['excludedProfitEnd','5년차 별도 제외 영업이익 / 매출',0,50]);
    if(m.reservePath)keys.push(['warrantyAccrual','현금표 보증비 되돌림 / 매출',0,20],['warrantyUseStart','1년차 보증 사용 / 매출',0,20],['warrantyUseEnd','5년차 보증 사용 / 매출',0,20]);
    if(m.grossProfitPath)for(const [k,l] of [['research','연구개발'],['selling','판매관리'],['otherOperating','구조조정·기타']])keys.push([k+'Start','1년차 '+l+' / 매출',0,100],[k+'End','5년차 '+l+' / 매출',0,100]);
    if(m.grossProfitPath)keys.push(['minority','비지배 분배 / 매출',0,100]);
    return keys;
  }
  function controls(c,i){
    const m=c.operatingModel,a=m.defaults,keys=cashSpecs(m);
    return `<article class="pair-input-side"><h3>${esc(c.name)} <small>${c.id}</small></h3><p>${m.sourcePeriod.join('–')} · ${c.currency} · <a href="#company/${c.id}">사업 가정의 원문·대사 읽기 ↗</a></p>${m.security.rightsReview?`<p class="pair-rights-assumption">${esc(m.security.rightsReview.assumption)}</p>`:''}<details><summary>사업별 성장·마진 편집</summary>${m.segments.map((s,j)=>`<fieldset><legend>${esc(s.label)}</legend><div class="pair-input-grid">${input(i,j+'.growthStart',a.segments[j].growthStart,'1년차 성장',(s.minGrowth??-.5)*100,80)}${input(i,j+'.growthEnd',a.segments[j].growthEnd,'5년차 성장',(s.minGrowth??-.5)*100,80)}${input(i,j+'.marginEnd',a.segments[j].marginEnd,'5년차 '+(m.marginLabel||'영업이익률'),(s.minMargin??-.5)*100,m.grossProfitPath?100:90)}</div></fieldset>`).join('')}</details><details><summary>현금·투자·할인 가정 편집</summary><div class="pair-input-grid">${keys.map(([k,l,lo,hi])=>input(i,k,a[k],l,lo,hi)).join('')}</div></details><details><summary>계산에 남아 있는 기업별 가정</summary><ul>${m.rules.map(v=>`<li>${esc(v)}</li>`).join('')}</ul></details></article>`;
  }
  function chart(companies,results){
    const finite=results.flatMap(r=>[r.terminalCashMargin,r.requiredCashMargin]).filter(v=>v!=null),lo=Math.min(0,...finite),hi=Math.max(0,...finite),x=v=>180+(v-lo)/(hi-lo||1)*440;
    return `<svg class="pair-requirement-chart" viewBox="0 0 800 230" role="img" aria-label="각 회사의 선택 말기 현금 비율과 현재 가격에 필요한 비율"><line x1="${x(0)}" x2="${x(0)}" y1="10" y2="205" stroke="#9baaa4"/>${companies.map((c,i)=>`<text x="0" y="${28+i*110}" font-size="16">${esc(c.id)}</text>${[['선택 경로',results[i].terminalCashMargin,'#267c76'],['가격 요구',results[i].requiredCashMargin,'#ac7757']].map(([label,value,color],j)=>`<text x="0" y="${51+i*110+j*36}" font-size="12">${label}</text>${value==null?`<text x="650" y="${51+i*110+j*36}" font-size="13">계산 보류</text>`:`<rect x="${Math.min(x(0),x(value))}" y="${36+i*110+j*36}" width="${Math.max(1,Math.abs(x(value)-x(0)))}" height="22" fill="${color}"/><text x="650" y="${52+i*110+j*36}" font-size="14">${pct(value)}</text>`}`).join('')}`).join('')}</svg>`;
  }
  function render(payload,id){
    const studies=payload.snapshot.peerStudies||[],study=studies.find(s=>s.id===id)||studies[0];if(!study)return '<h1>등록된 비교 연구가 없습니다.</h1>';
    const p=study.operatingComparison,companies=study.sides.map(s=>payload.snapshot.companies.find(c=>c.id===s.company));
    const ready=p?.status==='research_workspace';
    return `<div class="comparison-workspace" data-study="${esc(study.id)}"><div class="pair-heading"><span class="eyebrow">PAIRED ASSUMPTIONS / PRICE REQUIREMENTS</span><h1>두 기업의 가격이 요구하는 사업 조건</h1><p>사업 현금 가정을 바꾸고, 관측 가격에 필요한 현금과 대조합니다. 선택한 비교 판단은 개인 연구 기록으로 보존합니다.</p><label class="pair-picker">비교 연구<select id="pair-study-picker">${studies.map(s=>`<option value="${esc(s.id)}" ${s.id===study.id?'selected':''}>${esc(s.title)}${s.operatingComparison?.status==='research_workspace'?'':' · 원문 비교'}</option>`).join('')}</select></label><h2>${esc(study.title)}</h2></div>${ready?`<section class="panel pair-summary"><h2>같은 역산 질문, 각 기업의 사업 가정</h2><p>${esc(p.scope)}</p><p>사업 실적 기간 ${p.sameSourcePeriod?'일치':'상이'} · 종가 관측일 ${p.samePriceDate?'일치':'상이'}. 통화별 금액을 서로 더하지 않습니다.</p><div id="pair-result" aria-live="polite"></div></section><section class="panel pair-inputs"><h2>두 회사의 가정을 함께 검토</h2><div class="pair-common"><label>공통 요구수익률 %<input id="pair-discount" type="number" value="12" step="any"></label><label>공통 영구성장률 %<input id="pair-terminal" type="number" value="2" step="any"></label><button id="pair-apply-common" type="button">양쪽에 적용</button><button id="pair-reset" type="button">각 회사 초기 가정</button></div><div class="pair-controls">${companies.map(controls).join('')}</div></section><section class="panel pair-notes"><h2>비교 판단과 변경 조건</h2><p>작성 중 내용은 이 브라우저에 임시 보존합니다. 새 버전 저장으로 이전 판단을 남기세요. 사전 등록 원장·금융 심사와 구분됩니다.</p><label>나의 비교 의견<select id="pair-opinion"><option>미결정</option><option>왼쪽 조건부 선호</option><option>오른쪽 조건부 선호</option><option>양쪽 관찰</option></select></label><p>왼쪽 ${esc(companies[0].name)} · 오른쪽 ${esc(companies[1].name)}</p>${Object.entries(noteFields).map(([k,l])=>`<label>${l}<textarea id="pair-note-${k}" rows="3" maxlength="12000"></textarea></label>`).join('')}<div class="pair-actions"><button id="pair-use-reading" type="button">공시 비교 논지를 빈 항목에 채택</button><button id="pair-save" type="button">새 비교 버전 저장</button><button id="pair-export" type="button">전체 비교 기록 내보내기</button><label>기록 파일 가져오기<input id="pair-import" type="file" accept="application/json,.json"></label></div><p id="pair-message" role="status"></p><div id="pair-print-note"></div><details class="pair-history"><summary>이 비교의 이전 판단과 가정</summary><div id="pair-history"></div></details></section>`:`<section class="panel"><h2>사업 현금 비교를 위한 근거 보완</h2><p>${esc(p?.reason||'양쪽 현재 공시를 다시 확인해야 합니다.')}</p><p>${companies.filter(Boolean).map(c=>`<a href="#company/${c.id}">${esc(c.name)} 기업 연구 ↗</a>`).join(' · ')}</p></section>`}<div class="pair-originals">${window.EquityPeerStudies.renderStudy(study,false)}</div></div>`;
  }
  function bind(payload){
    const root=document.querySelector('.comparison-workspace');if(!root)return;
    const study=payload.snapshot.peerStudies.find(s=>s.id===root.dataset.study),p=study.operatingComparison;
    document.querySelector('#pair-study-picker').onchange=e=>{location.hash='compare/'+e.target.value;};
    if(p?.status!=='research_workspace')return;
    const companies=study.sides.map(s=>payload.snapshot.companies.find(c=>c.id===s.company));
    let current,results,storageError='';
    const message=t=>document.querySelector('#pair-message').textContent=t;
    const read=()=>{const a=companies.map(c=>structuredClone(c.operatingModel.defaults));for(const e of root.querySelectorAll('[data-pair-key]')){if(e.value.trim()==='')throw Error('빈 가정은 영으로 처리하지 않습니다.');const [j,k]=e.dataset.pairKey.split('.'),exact=Number(e.dataset.exact),v=Number(e.value)===Number((exact*100).toFixed(3))?exact:Number(e.value)/100;if(k)a[Number(e.dataset.pairSide)].segments[Number(j)][k]=v;else a[Number(e.dataset.pairSide)][j]=v;}return a;};
    const write=assumptions=>{for(const e of root.querySelectorAll('[data-pair-key]')){const [j,k]=e.dataset.pairKey.split('.'),a=assumptions[Number(e.dataset.pairSide)],v=k?a.segments[Number(j)][k]:a[j];e.value=Number((v*100).toFixed(3));e.dataset.exact=v;}};
    const record=(id)=>({id,study:study.id,recordedAt:new Date().toISOString(),snapshotHash:payload.snapshot.contentHash,comparisonHash:p.evidenceHash,studyHash:study.evidenceHash,opinion:document.querySelector('#pair-opinion').value,notes:Object.fromEntries(Object.keys(noteFields).map(k=>[k,document.querySelector('#pair-note-'+k).value.trim()])),sides:companies.map((c,i)=>({company:c.id,currency:c.currency,period:c.operatingModel.sourcePeriod,modelHash:c.operatingModel.evidenceHash,corpusHash:c.narrative.evidenceHash,price:p.sides[i].price,assumptions:current[i],result:results[i],evidence:study.sides[i].sources}))});
    function showNote(){document.querySelector('#pair-print-note').innerHTML=`<h3>나의 비교 의견: ${esc(document.querySelector('#pair-opinion').value)}</h3>${Object.entries(noteFields).map(([k,l])=>`<h4>${l}</h4><p>${esc(document.querySelector('#pair-note-'+k).value.trim()||'미작성')}</p>`).join('')}<p>직접 작성한 개인 연구 · 공시 ${companies.map(c=>c.narrative.accession).join(' / ')} · 투자 의견의 독립 승인 아님</p>`;}
    function update(persist=true){
      try{
        current=read();results=companies.map((c,i)=>summarize(c.operatingModel,current[i]));
        document.querySelector('#pair-result').innerHTML=chart(companies,results)+`<div class="table-wrap"><table class="pair-values"><thead><tr><th>조건부 계산</th>${companies.map(c=>`<th>${esc(c.name)}<br>${c.currency}</th>`).join('')}</tr></thead><tbody>${[['terminalCashMargin','선택 경로의 말기 현금 / 매출'],['requiredCashMargin','현재 가격이 요구하는 말기 현금 / 매출'],['marginGap','추가로 필요한 현금 비율'],['explicitCoverage','첫 5년 현금 현재가치 / 관측 시가총액'],['valueToMarket','조건부 현금 가치 / 관측 시가총액']].map(([k,l])=>`<tr><th>${l}</th>${results.map(r=>`<td>${k==='marginGap'&&r[k]!=null?n(r[k]*100)+'%p':pct(r[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="chart-caption">차이가 음수이면 선택 경로의 말기 현금이 요구액을 넘는다는 뜻입니다. 차이가 작다는 이유만으로 기업 선호를 자동 결정하지 않습니다. 음수 현금 경로의 가치를 영으로 대체하지 않습니다.</p><div class="pair-bases">${companies.map((c,i)=>`<article><h3>${esc(c.name)}</h3><p>종가 ${n(c.priceSummary.close,2)} ${c.currency} · ${c.priceSummary.lastDate}<br>주식수 ${n(c.operatingModel.security.shares?.value,0)} · ${esc(c.operatingModel.security.shares?.end||'미확인')}</p><p>요구수익률 ${pct(current[i].discount)} · 영구성장 ${pct(current[i].terminal)}<br>조건부 주당 값 ${n(results[i].price,c.currency==='KRW'?0:2)} ${c.currency}</p><p><strong>판단 전에 남은 근거:</strong> ${c.operatingModel.remaining.map(esc).join(' · ')}</p>${c.operatingModel.security.status!=='available'?`<p class="pair-security-hold">가격 계산 보류: ${c.operatingModel.security.issues.map(esc).join(' · ')}</p>`:''}</article>`).join('')}</div><details class="pair-selected"><summary>선택한 정확한 사업 가정</summary>${companies.map((c,i)=>`<h3>${esc(c.name)}</h3><p>${c.operatingModel.segments.map((s,j)=>`${esc(s.label)} 성장 ${pct(current[i].segments[j].growthStart)}→${pct(current[i].segments[j].growthEnd)}, ${esc(c.operatingModel.marginLabel||'영업이익률')} ${pct(current[i].segments[j].marginEnd)}`).join(' · ')}</p><div class="table-wrap"><table class="pair-assumption-table"><thead><tr><th>가정</th><th>선택값</th></tr></thead><tbody>${cashSpecs(c.operatingModel).map(([k,l])=>`<tr><th>${esc(l)}</th><td>${pct(current[i][k])}</td></tr>`).join('')}</tbody></table></div>`).join('')}</details>`;
        showNote();if(persist){if(storageError)throw Error(storageError);const store=readStore();const old=store.drafts[study.id];if(old&&old.comparisonHash!==p.evidenceHash){const archived={...old,id:'stale-'+old.comparisonHash};if(!store.records.some(r=>r.id===archived.id))store.records.push(archived);}store.drafts[study.id]=record('draft-pair-'+study.id);writeStore(store);}
        return true;
      }catch(e){results=null;document.querySelector('#pair-result').textContent=e.message;message(e.message);return false;}
    }
    function history(){const store=readStore();document.querySelector('#pair-history').innerHTML=store.records.filter(r=>r.study===study.id).map(r=>`<article><p>${esc(r.recordedAt)} · ${esc(r.opinion)} · ${r.comparisonHash===p.evidenceHash?'현재 양쪽 근거와 일치':'근거·가격 또는 계산 변경: 복원 보류'}</p><p>${esc(r.notes.thesis)}</p><button type="button" data-pair-restore="${esc(r.id)}">이 버전 복원</button></article>`).join('')||'<p>저장한 비교 버전이 없습니다.</p>';}
    function restore(r){validateRecord(r);if(r.study!==study.id||r.comparisonHash!==p.evidenceHash||r.sides.some((s,i)=>s.company!==companies[i].id||s.modelHash!==companies[i].operatingModel.evidenceHash))throw Error('공시·가격·계산 버전이 달라 과거 가정을 자동 적용하지 않습니다. 원문을 다시 검토하세요.');const assumptions=r.sides.map(s=>s.assumptions);companies.forEach((c,i)=>summarize(c.operatingModel,assumptions[i]));write(assumptions);for(const k of Object.keys(noteFields))document.querySelector('#pair-note-'+k).value=r.notes[k];document.querySelector('#pair-opinion').value=r.opinion;update(false);message('양쪽 기업의 정확한 가정과 연구 판단을 복원했습니다.');}
    try{const store=readStore();history();const draft=store.drafts[study.id];if(draft){try{restore(draft);}catch(e){update(false);message('이전 초안은 보존하고 현재 초기 가정을 표시합니다. '+e.message);}}else update(false);}catch(e){storageError=e.message;update(false);message('기존 기록은 유지합니다. '+e.message);}
    for(const e of root.querySelectorAll('[data-pair-key],textarea,#pair-opinion'))e.addEventListener('input',()=>update());
    document.querySelector('#pair-apply-common').onclick=()=>{try{const a=read();for(const v of a)for(const [k,id] of [['discount','pair-discount'],['terminal','pair-terminal']]){const e=document.getElementById(id);if(!e.value.trim())throw Error('공통 가정을 입력하세요.');v[k]=Number(e.value)/100;}companies.forEach((c,i)=>summarize(c.operatingModel,a[i]));write(a);update();message('같은 요구수익률·영구성장을 적용했습니다. 각 기업의 사업·현금 가정은 별도로 유지합니다.');}catch(e){message(e.message);}};
    document.querySelector('#pair-reset').onclick=()=>{write(companies.map(c=>c.operatingModel.defaults));update();message('각 기업의 초기 가정으로 돌아왔습니다. 작성한 판단 문장은 유지합니다.');};
    document.querySelector('#pair-use-reading').onclick=()=>{for(const [k,v] of Object.entries({thesis:study.tradeoff+'\n가격 가정: '+study.priceImplication,countercase:study.countercase||'',changes:study.discriminator})){const e=document.querySelector('#pair-note-'+k);if(!e.value.trim())e.value=v;}update();message('공시 비교 초안을 빈 항목에 채택했습니다. 원문과 반론을 검토하고 자신의 판단으로 수정하세요.');};
    document.querySelector('#pair-save').onclick=()=>{try{if(!update())return;const r=record(crypto.randomUUID());if(Object.values(r.notes).some(v=>!v))throw Error('판단·반론·변경 조건을 모두 작성하세요.');const store=readStore();store.records.push(r);writeStore(store);history();message('새 비교 버전을 저장했습니다. 이전 판단과 양쪽 공시 근거도 보존했습니다.');}catch(e){message(e.message);}};
    document.querySelector('#pair-export').onclick=async()=>{try{const url=URL.createObjectURL(new Blob([await exportText()],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='equity-paired-research.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message('두 기업의 가정·근거·판단을 포함한 전체 비교 기록을 내보냈습니다.');}catch(e){message(e.message);}};
    document.querySelector('#pair-import').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;const count=await importText(await f.text());history();message(`${count}개 기록을 추가했습니다. 이전 판단에서 복원을 선택하세요. 현재 작성 중 내용은 유지합니다.`);}catch(e){message(e.message);}finally{e.target.value='';}};
    document.querySelector('#pair-history').onclick=e=>{const b=e.target.closest('[data-pair-restore]');if(b)try{restore(readStore().records.find(r=>r.id===b.dataset.pairRestore));}catch(error){message(error.message);}};
  }
  window.EquityComparisonWorkspace={render,bind,summarize,exportText,importText};
})();
