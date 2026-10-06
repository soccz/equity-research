/* Explicit, editable cash assumptions. A scenario is not a price forecast. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=(v,d=2)=>v==null?'계산 보류':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d});
  const pct=v=>v==null?'미확인':num(v*100,1)+'%';
  const scale=c=>c.currency==='KRW'?1e12:1e9;
  const amount=(v,c)=>v==null?'계산 보류':num(v/scale(c));
  const unit=c=>c.currency==='KRW'?'조 원':'십억 달러';
  function calculate(revenue,cfo,investment,burden,growth,discount,shares,terminal=.02,horizon=5){
    const factor=1/window.EquityDossier.pricing(1,growth,discount,terminal,horizon).requiredBaseCash;
    const cash=revenue*(cfo-investment-burden),equity=cash>0?cash*factor:null;
    return {cash,equity,price:equity!=null&&shares?equity/shares:null,factor};
  }
  function impliedGrowth(cap,cash,discount,terminal=.02,horizon=5){
    if(cash<=0)return {status:'nonpositive_cash',growth:null};
    const required=g=>window.EquityDossier.pricing(cap,g,discount,terminal,horizon).requiredBaseCash;
    let lo=-.49,hi=.99;
    if(required(hi)>cash)return {status:'above_range',growth:null};
    if(required(lo)<cash)return {status:'below_range',growth:null};
    for(let i=0;i<70;i++){const mid=(lo+hi)/2;if(required(mid)>cash)lo=mid;else hi=mid;}
    return {status:'solved',growth:(lo+hi)/2};
  }
  function cashChart(c,cases,required,selected){
    const rows=[...cases.map(p=>({label:p.label,value:p.cash})),{label:'선택한 가정',value:selected},{label:'현재 가격의 요구액',value:required}].filter(p=>p.value!=null);
    const lo=Math.min(0,...rows.map(p=>p.value)),hi=Math.max(0,...rows.map(p=>p.value)),left=240,width=460;
    const x=v=>left+(v-lo)/(hi-lo||1)*width,zero=x(0);
    return `<svg class="valuation-cash-chart" viewBox="0 0 830 ${rows.length*46+42}" role="img" aria-label="과거 현금 조합과 선택 가정, 현재 가격이 요구하는 기준연도 현금 비교"><line x1="${zero}" x2="${zero}" y1="12" y2="${rows.length*46+4}" stroke="#8a989d"/>${rows.map((r,i)=>`<g><text x="8" y="${i*46+32}" font-size="14" fill="currentColor">${esc(r.label)}</text><rect x="${Math.min(zero,x(r.value))}" y="${i*46+15}" width="${Math.max(.5,Math.abs(x(r.value)-zero))}" height="24" fill="${r.value<0?'#bb694e':i===rows.length-1&&required!=null?'#82634c':'#287c7c'}"/><text x="${Math.max(zero,x(r.value))+9}" y="${i*46+32}" font-size="14" fill="currentColor">${amount(r.value,c)}</text></g>`).join('')}<text x="${left}" y="${rows.length*46+31}" font-size="12" fill="currentColor">0 기준축 · ${unit(c)} / 년 · 확률 분포가 아닌 가정 비교</text></svg>`;
  }
  function render(c){
    const v=c.valuation;if(!v)return '';
    if(v.status!=='workspace')return `<section class="panel valuation-workspace"><h2>현금과 가격 시나리오</h2><p>${esc(v.reason)}</p></section>`;
    const d=v.defaults,control=(id,label,value,min,max,step='any')=>`<label>${label}<output id="valuation-${id}-value">${pct(value)}</output><input data-valuation-control id="valuation-${id}" type="range" min="${min}" max="${max}" step="${step}" value="${value*100}"></label>`;
    const cfoMax=Math.ceil(Math.max(1,...v.history.map(r=>r.cfoMargin)) *100+10),investMax=Math.ceil(Math.max(.5,...v.history.map(r=>r.investmentMargin))*100+10);
    const history=`<div class="table-wrap"><table><thead><tr><th>겹치지 않는 공시기간</th><th>영업현금 / 매출</th><th>투자자산 취득 / 매출</th></tr></thead><tbody>${v.history.map(r=>`<tr><th>${r.start}–${r.end}</th><td>${pct(r.cfoMargin)}</td><td>${pct(r.investmentMargin)}</td></tr>`).join('')}</tbody></table></div>`;
    const security=v.security;
    const securityText=security.status==='available'?`주식수 ${num(security.shares.value,0)}주 · 기준 ${security.shares.end} · 종가 ${num(c.priceSummary.close,c.currency==='KRW'?0:2)} ${c.currency} · ${security.priceDate} · 두 시점 ${security.shareAgeDays}일 차이. <a href="${esc(security.shares.sourceUrl)}" target="_blank" rel="noopener noreferrer">유통주식수 원문 ↗</a>${security.shares.issued!=null?`<br>${security.shares.treasury!=null?`공시 발행 ${num(security.shares.issued,0)} − 자기주식 ${num(security.shares.treasury,0)} = 유통 ${num(security.shares.value,0)}주.`:`공시 발행 ${num(security.shares.issued,0)}주 · 유통 ${num(security.shares.value,0)}주. 자기주식 수는 미기재이며 발행·유통 총수의 일치를 따로 확인했습니다.`} 공시 총수 표와 같은 접수·기준일을 대조했습니다.`:''}`:`주당 가격 계산을 보류하는 이유: ${security.issues.map(esc).join(' · ')}`;
    const sq=n=>n==null?'미기재':num(n,0);
    const otherShares=[...new Map((security.additionalShareEvidence||[]).map(f=>[JSON.stringify([f.value,f.end,f.dimensions]),f])).values()];
    const shareEvidence=security.shareTable?`<details class="valuation-share-evidence"><summary>공시 주식수 대사 · 발행·자기주식·유통 수량</summary><div class="table-wrap"><table><thead><tr><th>공시 주식 종류</th><th>발행</th><th>자기주식</th><th>유통</th></tr></thead><tbody>${security.shareTable.classes.map(r=>`<tr><th><a href="${esc(r.fact.sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(r.label)} ↗</a><small>${r.fact.end}${r.classEvidence?.length?' · XBRL 보통주 발행·유통 수량 모두 대조':''}</small></th><td>${sq(r.fact.issued)}</td><td>${sq(r.fact.treasury)}</td><td>${sq(r.fact.value)}</td></tr>`).join('')}</tbody></table></div>${otherShares.length?`<p>다른 XBRL 주석의 같은 기준일 유통주식수</p><ul>${otherShares.map(f=>`<li><a href="${esc(f.sourceUrl)}" target="_blank" rel="noopener noreferrer">${num(f.value,0)}주 ↗</a> · ${f.dimensions.some(d=>d[1]==='SeparateMember')?'별도 재무제표':'연결 재무제표'} · ${f.dimensions.some(d=>d[1]==='OrdinarySharesMember')?'보통주 맥락':'보고금액 맥락'}</li>`).join('')}</ul>`:''}<p class="chart-caption">미기재는 영이 아닙니다. 같은 접수의 주석끼리 수량이 다르면 범위를 확인할 때까지 주당 가격을 보류합니다.</p></details>`:'';
    const adjustments=v.adjustments.map(a=>`<li>${esc(a.label)}: 같은 누적기간 매출의 ${pct(a.ratio)}. <a href="${esc(a.evidence.sourceUrl)}" target="_blank" rel="noopener noreferrer">${amount(a.evidence.value,c)} ${unit(c)} · ${a.evidence.start}–${a.evidence.end} ↗</a></li>`).join('');
    return `<section class="panel valuation-workspace"><div class="valuation-heading"><span class="eyebrow">CASH ASSUMPTIONS / EQUITY SCENARIOS</span><h2>어떤 현금·재투자 조건에서 현재 가격이 설명되는가</h2><p class="panel-subtitle">기준 매출 ${v.revenuePeriod.join('–')} · ${amount(v.revenueBase,c)} ${unit(c)} · 과거 공시 범위에서 출발하는 가정</p></div><p class="valuation-security">${securityText}</p>${shareEvidence}<div class="valuation-controls control-grid">${control('cfo','영업현금 / 매출 가정',d.cfoMargin,Math.floor(Math.min(-.5,...v.history.map(r=>r.cfoMargin))*100-10),cfoMax)}${control('investment','투자자산 취득 / 매출 가정',d.investmentMargin,0,investMax)}${control('burden','추가 부담 / 매출 가정',d.burdenMargin,0,Math.max(50,Math.ceil(d.burdenMargin*100+10)))}${control('growth','명시기간 현금 성장 가정',d.growth,-10,80)}${control('discount','주주 요구수익률 가정',d.discount,6,20)}${control('terminal','이후 영구성장률 가정',d.terminal,0,4)}<label>명시적으로 가정할 기간<select id="valuation-horizon" data-valuation-control>${[5,10,15,20].map(n=>`<option value="${n}" ${n===d.horizon?'selected':''}>${n}년</option>`).join('')}</select></label></div><p class="chart-caption">명시기간 이후 영구가치로 이어집니다. 추가 부담은 확인된 리스 지급과 주식보상 비용 대용에서 출발합니다.</p><div id="valuation-result" aria-live="polite"></div><p class="valuation-unknown">${v.unknownAdjustments.length?`현재 미확인 추가 부담: ${v.unknownAdjustments.map(esc).join(' · ')}. 초기 계산에서 이 항목의 추가 부담은 0으로 가정했으며 실제 금액을 0으로 판정한 것이 아닙니다.`:'리스 지급·주식보상 조정의 당기 공시 근거를 연결했습니다.'}</p><details><summary>가정의 과거 공시 근거와 현금 조정</summary>${history}<ul>${adjustments}</ul><p>주식보상은 현금보상 대체 가정입니다. 자기주식 매입 현금을 다시 차감하지 않습니다.</p></details><details open class="valuation-assumptions"><summary>이 가격 조건에 포함한 가정</summary><ol>${v.assumptions.map(a=>`<li>${esc(a)}</li>`).join('')}</ol></details><p class="chart-caption">${esc(v.scope)}</p><button id="valuation-reset" type="button">공시 근거의 초기 가정으로 복원</button></section>`;
  }
  function bind(c){
    const v=c.valuation;if(v?.status!=='workspace')return;
    const update=()=>{
      const vals=Object.fromEntries(['cfo','investment','burden','growth','discount','terminal'].map(k=>[k,Number(document.querySelector('#valuation-'+k).value)/100]));
      for(const [k,n] of Object.entries(vals))document.querySelector('#valuation-'+k+'-value').textContent=pct(n);
      vals.horizon=Number(document.querySelector('#valuation-horizon').value);
      const shares=v.security.status==='available'?v.security.shares.value:null;
      const r=calculate(v.revenueBase,vals.cfo,vals.investment,vals.burden,vals.growth,vals.discount,shares,vals.terminal,vals.horizon);
      const cases=v.cases.map(p=>({...p,...calculate(v.revenueBase,p.cfoMargin,p.investmentMargin,vals.burden,vals.growth,vals.discount,shares,vals.terminal,vals.horizon)}));
      const required=v.security.marketCapProxy?v.security.marketCapProxy/r.factor:null;
      const implied=v.security.marketCapProxy?impliedGrowth(v.security.marketCapProxy,r.cash,vals.discount,vals.terminal,vals.horizon):null;
      const terminalShare=v.security.marketCapProxy?window.EquityDossier.pricing(v.security.marketCapProxy,vals.growth,vals.discount,vals.terminal,vals.horizon).terminalShare:null;
      const requiredMargin=required==null?null:required/v.revenueBase+vals.investment+vals.burden;
      const meaning=requiredMargin==null?'현재 확인된 주식 종류·유통주식수의 범위를 보완한 뒤 주당 가격 조건을 비교합니다.':requiredMargin>Math.max(...v.history.map(p=>p.cfoMargin))?'현재 가격을 설명하는 데 필요한 영업현금 마진이 표시한 과거 공시 범위를 넘습니다. 사업 성장·수금·재투자에 대한 추가 근거가 필요합니다.':requiredMargin>vals.cfo?'선택한 현금 마진으로는 현재 가격을 설명하지 못합니다. 더 높은 현금 창출, 낮은 재투자 또는 다른 성장·요구수익률 가정이 필요합니다.':'선택한 가정에서는 현금이 현재 가격의 요구액을 넘습니다. 이 가정의 지속성과 미확인 추가 부담을 확인해야 조건부 선호를 검토할 수 있습니다.';
      document.querySelector('#valuation-result').innerHTML=`<p class="valuation-selected">선택 가정: 영업현금 ${pct(vals.cfo)} · 투자 ${pct(vals.investment)} · 추가 부담 ${pct(vals.burden)} · 성장 ${pct(vals.growth)} · 요구수익률 ${pct(vals.discount)} · 명시기간 ${vals.horizon}년 · 이후 ${pct(vals.terminal)}</p><div class="driver-grid"><div><small>선택 가정의 기준연도 현금</small><strong>${amount(r.cash,c)}</strong></div><div><small>현재 가격에 필요한 기준연도 현금</small><strong>${amount(required,c)}</strong></div><div><small>필요한 영업현금 / 매출</small><strong>${pct(requiredMargin)}</strong></div></div><p class="chart-caption">현금 단위 ${unit(c)} / 년 · 선택 가정의 주당 가격 조건: ${num(r.price,c.currency==='KRW'?0:2)} ${r.price==null?'':c.currency}. 현금이 양수가 아니면 주당 가격을 0으로 만들지 않고 계산을 보류합니다.</p><p class="valuation-implied">선택 현금에서 현재 가격을 설명하는 명시기간 연 성장률: <strong>${implied?.status==='solved'?pct(implied.growth):implied?.status==='above_range'?'연 99% 초과 구간':implied?.status==='below_range'?'연 −49% 미만 구간':'계산 보류'}</strong>. 같은 요구수익률·영구성장률·${vals.horizon}년을 유지한 역산이며 시장 전체의 기대나 실적 전망이 아닙니다. 선택한 성장 가정의 현재가치 중 영구가치 ${pct(terminalShare)}.</p>${cashChart(c,cases,required,r.cash)}<div class="table-wrap"><table class="valuation-cases"><thead><tr><th>과거 범위 조합</th><th>영업현금 비율</th><th>투자 비율</th><th>기준연도 현금</th><th>주당 가격 조건</th></tr></thead><tbody>${cases.map(p=>`<tr><th>${esc(p.label)}</th><td>${pct(p.cfoMargin)}</td><td>${pct(p.investmentMargin)}</td><td>${amount(p.cash,c)}</td><td>${num(p.price,c.currency==='KRW'?0:2)} ${p.price==null?'':c.currency}</td></tr>`).join('')}</tbody></table></div><p class="chart-caption">비율의 최솟값·중앙값·최댓값을 조합한 스트레스 계산입니다. 실제로 함께 발생한 구간, 전망 확률, 목표가 범위가 아닙니다.</p><p class="valuation-meaning"><strong>판단에 주는 의미</strong><br>${meaning}</p>`;
    };
    for(const input of document.querySelectorAll('[data-valuation-control]'))input.addEventListener('input',update);
    document.querySelector('#valuation-reset').addEventListener('click',()=>{for(const [id,key] of [['cfo','cfoMargin'],['investment','investmentMargin'],['burden','burdenMargin'],['growth','growth'],['discount','discount'],['terminal','terminal']])document.querySelector('#valuation-'+id).value=v.defaults[key]*100;document.querySelector('#valuation-horizon').value=v.defaults.horizon;update();});
    update();
  }
  window.EquityValuation={render,bind,calculate,impliedGrowth};
})();
