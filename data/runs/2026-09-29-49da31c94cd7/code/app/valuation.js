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
  function preferredConversion(t,p){
    if(!Number.isFinite(p)||p<=0)throw new Error('계약상 평균가격은 양수여야 합니다.');
    return p>t.thresholdPrice?t.minimumRate:p<t.initialPrice?t.maximumRate:Math.round(1000/p*10000)/10000;
  }
  function capitalEvidence(c){
    const r=c.valuation?.security?.capitalReview;if(!r)return '';
    const x=p=>50+(p-150)/550*630,y=n=>150-(n-2.2)/.7*115;
    const colors=['#287c7c','#ad693c'];
    return `<details open class="valuation-capital-contract"><summary>Alphabet 전환우선주 · 현금 배당과 기본 전환 조건</summary><p>${esc(r.commonRights)}</p><p>${esc(r.quantityScope)}</p><div class="table-wrap"><table><thead><tr><th>우선주 → 보통주</th><th>낮은 평균가격 구간 / 전환 수</th><th>중간 구간</th><th>높은 평균가격 구간 / 전환 수</th></tr></thead><tbody>${r.terms.map(t=>`<tr><th><a href="${esc(t.sourceUrl)}" target="_blank" rel="noopener noreferrer">Series ${t.series} → Class ${t.commonClass} ↗</a></th><td>$${num(t.initialPrice,4)} 미만 / ${num(t.maximumRate,4)}주</td><td>$1,000 ÷ 해당 평균가격</td><td>$${num(t.thresholdPrice,4)} 초과 / ${num(t.minimumRate,4)}주</td></tr>`).join('')}</tbody></table></div><p>예정 의무 전환일 ${r.mandatoryConversionDate} · 우선주 한 주당 청산우선금액 $1,000 · 연율 배당권 $62.50.</p><p>${esc(r.dividendScope)}</p><svg viewBox="0 0 740 205" role="img" aria-label="미래 평균가격 가정에 따른 우선주 한 주의 기본 전환 보통주 수"><path d="M50 20 V160 H700" fill="none" stroke="#83999c"/>${r.terms.map((t,i)=>`<polyline points="${Array.from({length:111},(_,j)=>150+j*5).map(p=>x(p)+','+y(preferredConversion(t,p))).join(' ')}" fill="none" stroke="${colors[i]}" stroke-width="3"/><text x="${80+i*310}" y="23" fill="${colors[i]}" font-size="13">Series ${t.series} → Class ${t.commonClass}</text>`).join('')}<text x="8" y="47" font-size="12">2.9주</text><text x="8" y="152" font-size="12">2.2주</text><text x="50" y="179" font-size="12">$150</text><text x="647" y="179" font-size="12">$700</text><text x="155" y="200" font-size="12">각 종류의 미래 계약상 평균가격 가정 / 오늘의 종가가 아님</text></svg><div class="control-grid">${r.terms.map(t=>`<label>Class ${t.commonClass} 미래 평균가격 가정 ($)<input data-preferred-series="${t.series}" type="number" value="400" min="1" step="1"><output data-preferred-result="${t.series}"></output></label>`).join('')}</div><p class="chart-caption">${esc(r.scope)}</p><p>${esc(r.capScope)}</p><p>전체 주당 계산에 남은 확인 사항: ${r.remaining.map(esc).join(' · ')}.</p><a href="${esc(r.sourceUrl)}" target="_blank" rel="noopener noreferrer">현재 분기 공시의 우선주·보통주 권리 ↗</a></details>`;
  }
  function bindCapital(c){
    const r=c.valuation?.security?.capitalReview;if(!r)return;
    for(const input of document.querySelectorAll('[data-preferred-series]')){
      const t=r.terms.find(t=>t.series===input.dataset.preferredSeries),out=document.querySelector(`[data-preferred-result="${t.series}"]`);
      const update=()=>{try{out.textContent=`우선주 한 주 → 기본 ${num(preferredConversion(t,Number(input.value)),4)} 보통주 · 누적 미지급 배당·반희석 조정·capped call 정산 별도`;}catch(e){out.textContent=e.message;}};
      input.addEventListener('input',update);update();
    }
  }
  function subsequentCapital(c){
    const r=c.valuation?.security?.subsequentReview;if(!r)return '';
    return `<details open class="valuation-capital-events"><summary>반기 뒤 자본 변동 · 현재 유통주식수 대사</summary><p>${esc(r.scope)}</p><div class="table-wrap"><table><thead><tr><th>공시 관측</th><th>기준일·기간</th><th>수량</th><th>해석 범위</th></tr></thead><tbody>${r.observations.map(o=>`<tr><th><a href="${esc(o.sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(o.label)} ↗</a></th><td>${esc(o.date)}</td><td>${esc(o.value)}</td><td>${esc(o.scope)}</td></tr>`).join('')}</tbody></table></div><p>가격 기준 ${esc(r.asOf)}의 실제 유통 수량은 자료 미확인입니다. 날짜가 다른 발행·자기주식 수량을 합쳐 확정하거나 예정 취득 수량을 이미 소각한 것으로 계산하지 않습니다.</p><p>공시 조사 범위 ${esc(r.reviewedThrough)}까지 · ${esc(r.issue)}</p></details>`;
  }
  function customerWarrants(c){
    const r=c.valuation?.security?.warrantReview;if(!r)return '';
    if(!r.terms?.length)return `<p class="valuation-customer-warrants">${esc(r.issue)}</p>`;
    return `<details open class="valuation-customer-warrants"><summary>고객 구매에 연동된 워런트 · 현재 주식수와 조건부 희석</summary><p>${esc(r.scope)}</p><div class="table-wrap"><table><thead><tr><th>고객</th><th>최대 원주 수량</th><th>주당 행사가격</th><th>행사 기한</th></tr></thead><tbody>${r.terms.map(t=>`<tr><th>${esc(t.holder)}</th><td>${num(t.maximumShares,0)}주</td><td>$${num(t.exercisePrice,2)}</td><td>${esc(t.expiry)}</td></tr>`).join('')}</tbody></table></div><p>관측 ${esc(r.observedAt)}: 가득 ${num(r.vestedSharesAtObservation,0)}주 · 행사 가능 ${num(r.exercisableSharesAtObservation,0)}주. 가격 기준 ${esc(r.priceDate)}의 가득 수량은 자료 미확인입니다.</p><p>${esc(r.conditions)}</p><a href="${esc(r.sourceUrl)}" target="_blank" rel="noopener noreferrer">공시 고객 워런트 조건 ↗</a></details>`;
  }
  function capitalClaims(c){
    const r=c.valuation?.security?.claimsReview;if(!r)return '';
    if(!r.observations?.length)return `<p class="valuation-capital-claims">${esc(r.issue)}</p>`;
    return `<details open class="valuation-capital-claims"><summary>${esc(r.title)}</summary><p>${esc(r.scope)}</p><div class="table-wrap"><table><thead><tr><th>관측·권리</th><th>공시 조건</th><th>가격 판단에 필요한 구분</th></tr></thead><tbody>${r.observations.map(o=>`<tr><th>${esc(o.label)}</th><td>${esc(o.value)}</td><td>${esc(o.scope)}</td></tr>`).join('')}</tbody></table></div><p>공시 관측 ${esc(r.observedAt)} · 제출 ${esc(r.filedAt)} · 가격 ${esc(r.priceDate)}. <a href="${esc(r.sourceUrl)}" target="_blank" rel="noopener noreferrer">발행·정산 조건 원문 ↗</a></p></details>`;
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
    const rights=security.rightsReview;
    const rightsEvidence=rights?`<details open class="valuation-rights-evidence"><summary>주식 종류별 현금 권리와 같은 날짜의 유통 수량</summary><p>${esc(rights.assumption)}</p><blockquote>${esc(rights.quote)} <a href="${esc(rights.sourceUrl)}" target="_blank" rel="noopener noreferrer">공시 권리 원문 ↗</a></blockquote><div class="table-wrap"><table><thead><tr><th>주식 종류</th><th>기준일</th><th>공시 유통 수량</th></tr></thead><tbody>${rights.classes.map(r=>`<tr><th>${esc(r.label)}</th><td>${r.fact.end}</td><td>${num(r.fact.value,0)}주</td></tr>`).join('')}</tbody></table></div></details>`:'';
    const adjustments=v.adjustments.map(a=>`<li>${esc(a.label)}: 같은 누적기간 매출의 ${pct(a.ratio)}. <a href="${esc(a.evidence.sourceUrl)}" target="_blank" rel="noopener noreferrer">${amount(a.evidence.value,c)} ${unit(c)} · ${a.evidence.start}–${a.evidence.end} ↗</a></li>`).join('');
    return `<section class="panel valuation-workspace"><div class="valuation-heading"><span class="eyebrow">CASH ASSUMPTIONS / EQUITY SCENARIOS</span><h2>어떤 현금·재투자 조건에서 현재 가격이 설명되는가</h2><p class="panel-subtitle">기준 매출 ${v.revenuePeriod.join('–')} · ${amount(v.revenueBase,c)} ${unit(c)} · 과거 공시 범위에서 출발하는 가정</p></div><p class="valuation-security">${securityText}</p>${shareEvidence}${rightsEvidence}${capitalEvidence(c)}${subsequentCapital(c)}${customerWarrants(c)}${capitalClaims(c)}<div class="valuation-controls control-grid">${control('cfo','영업현금 / 매출 가정',d.cfoMargin,Math.floor(Math.min(-.5,...v.history.map(r=>r.cfoMargin))*100-10),cfoMax)}${control('investment','투자자산 취득 / 매출 가정',d.investmentMargin,0,investMax)}${control('burden','추가 부담 / 매출 가정',d.burdenMargin,0,Math.max(50,Math.ceil(d.burdenMargin*100+10)))}${control('growth','명시기간 현금 성장 가정',d.growth,-10,80)}${control('discount','주주 요구수익률 가정',d.discount,6,20)}${control('terminal','이후 영구성장률 가정',d.terminal,0,4)}<label>명시적으로 가정할 기간<select id="valuation-horizon" data-valuation-control>${[5,10,15,20].map(n=>`<option value="${n}" ${n===d.horizon?'selected':''}>${n}년</option>`).join('')}</select></label></div><p class="chart-caption">명시기간 이후 영구가치로 이어집니다. 추가 부담은 확인된 리스 지급과 주식보상 비용 대용에서 출발합니다.</p><div id="valuation-result" aria-live="polite"></div><p class="valuation-unknown">${v.unknownAdjustments.length?`현재 미확인 추가 부담: ${v.unknownAdjustments.map(esc).join(' · ')}. 초기 계산에서 이 항목의 추가 부담은 0으로 가정했으며 실제 금액을 0으로 판정한 것이 아닙니다.`:'리스 지급·주식보상 조정의 당기 공시 근거를 연결했습니다.'}</p><details><summary>가정의 과거 공시 근거와 현금 조정</summary>${history}<ul>${adjustments}</ul><p>주식보상은 현금보상 대체 가정입니다. 자기주식 매입 현금을 다시 차감하지 않습니다.</p></details><details open class="valuation-assumptions"><summary>이 가격 조건에 포함한 가정</summary><ol>${v.assumptions.map(a=>`<li>${esc(a)}</li>`).join('')}</ol></details><p class="chart-caption">${esc(v.scope)}</p><button id="valuation-reset" type="button">공시 근거의 초기 가정으로 복원</button></section>`;
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
    update();bindCapital(c);
  }
  window.EquityValuation={render,bind,calculate,impliedGrowth,preferredConversion};
})();
