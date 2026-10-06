/* Filing calculations across the coverage universe; no generated investment verdicts. */
(() => {
  const esc = v => String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const n=(v,d=2)=>v==null?'미확인':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d,minimumFractionDigits:d});
  const pct=v=>v==null?'미확인':n(v*100,1)+'%';
  const amount=(v,c)=>n(v/(c.currency==='KRW'?1e12:1e9));
  const unit=c=>c.currency==='KRW'?'조 원':'십억 달러';
  function annualChart(rows) {
    if(!rows.length)return '<p>동일 기간의 연간 매출·현금·투자지출을 아직 연결하지 못했습니다.</p>';
    const vals=rows.flatMap(r=>[r.cfoMargin,r.cashMargin,r.operatingMargin]).filter(v=>v!==null),lo=Math.min(0,...vals),hi=Math.max(.05,...vals),range=hi-lo||1;
    const x=i=>65+i/Math.max(rows.length-1,1)*490,y=v=>175-(v-lo)/range*140;
    let body='';for(let i=0;i<=4;i++){const v=lo+range*i/4;body+=`<line class="grid" x1="60" x2="565" y1="${y(v)}" y2="${y(v)}"/><text x="51" y="${y(v)+4}" text-anchor="end">${n(v*100,0)}%</text>`;}
    for(const [key,color] of [['operatingMargin','#b36a43'],['cfoMargin','#849976'],['cashMargin','#245d53']]){
      let previous=false,path='';rows.forEach((r,i)=>{if(r[key]==null){previous=false;return;}path+=`${previous?'L':'M'}${x(i)},${y(r[key])} `;previous=true;body+=`<circle cx="${x(i)}" cy="${y(r[key])}" r="3" fill="${color}"/>`;});body+=`<path d="${path}" stroke="${color}" stroke-width="2" fill="none"/>`;
    }
    body+=rows.map((r,i)=>`<text x="${x(i)}" y="202" text-anchor="middle">${esc(r.end)}</text>`).join('');
    return `<svg class="chart annual-chart" viewBox="0 0 625 220" role="img" aria-label="공시기간별 영업이익률, 영업현금 마진, 투자자산 취득 후 현금 마진">${body}</svg><div class="policy-legend"><span style="--swatch:#b36a43">영업이익 / 매출</span><span style="--swatch:#849976">영업현금 / 매출</span><span style="--swatch:#245d53">투자자산 취득 후 현금 / 매출</span></div>`;
  }
  function trailing(c){
    const t=c.trailingYear;if(!t)return '';
    if(t.status==='unresolved')return `<section class="panel trailing-year"><h2>최근 일 년으로 기간을 맞춰 보기</h2><p>${esc(t.reason)}</p></section>`;
    const labels={revenue:'매출',operating_income:'영업이익',net_income:'순이익',cfo:'영업현금',capex:'투자자산 취득'};
    const rows=Object.entries(t.values).map(([key,v])=>`<tr><th>${labels[key]}</th><td>${v?amount(v.value,c):'미확인'}</td><td>${v?v.components.map(p=>`${p.coefficient<0?'−':'+'} ${amount(p.fact.value,c)}`).join(' '):'기간·정의 추가 확인'}</td></tr>`).join('');
    const evidence=Object.entries(t.values).filter(([k,v])=>v).map(([k,v])=>`<h3>${labels[k]}</h3>${v.components.map(p=>`<p>${esc(p.label)} · ${p.fact.start}–${p.fact.end} · <a href="${esc(p.fact.sourceUrl)}" target="_blank" rel="noopener noreferrer">${amount(p.fact.value,c)} · 공시 ${p.fact.filedAt} ↗</a></p>`).join('')}`).join('');
    return `<section class="panel trailing-year"><span class="eyebrow">COMPARABLE PERIOD / TRAILING YEAR</span><h2>반기·분기 공시를 최근 일 년으로 연결하기</h2><p class="panel-subtitle">${t.start}–${t.end} · ${t.days}일 · ${unit(c)} · ${t.method==='reported'?'보고된 연간·12개월 공시':'직전 연간 + 당기 누적 − 전년 누적'}</p><div class="table-wrap" tabindex="0"><table><thead><tr><th>항목</th><th>최근 일 년</th><th>공시 금액 연결</th></tr></thead><tbody>${rows}</tbody></table></div><div class="driver-grid"><div><small>영업이익 / 매출</small><strong>${pct(t.metrics.operatingMargin)}</strong></div><div><small>영업현금 / 매출</small><strong>${pct(t.metrics.cfoMargin)}</strong></div><div><small>투자 이후 현금 / 매출</small><strong>${pct(t.metrics.cashMargin)}</strong></div></div><p class="chart-caption">${esc(t.scope)} 투자 범위: ${esc(t.investmentScope||'미확인')}.</p><details><summary>기간을 연결한 공시 근거</summary>${evidence}</details></section>`;
  }
  function comparison(c,other) {
    const trailingReady=c.trailingYear?.status==='ready'&&other.trailingYear?.status==='ready';
    const period=x=>trailingReady?x.trailingYear:x.financials;
    const metrics=x=>trailingReady?x.trailingYear.metrics:x.metrics;
    const scope=x=>trailingReady?x.trailingYear.investmentScope:x.investmentScope;
    const cautions=[];
    if(c.peerGroup!==other.peerGroup)cautions.push('서로 다른 조사 분류');
    if(c.financials.standard!==other.financials.standard)cautions.push('회계 기준 차이');
    if(Math.abs(period(c).days-period(other).days)>8)cautions.push('기간 길이 차이: 우열 비교 보류');
    if(Math.abs(Date.parse(period(c).end)-Date.parse(period(other).end))>35*86400000)cautions.push('기간 종료일 차이');
    if(scope(c)!==scope(other))cautions.push('투자지출 정의 차이: 보고 비율만 병치하고 현금·투자 우열 비교는 보류');
    const pairs=trailingReady?[['영업이익 / 매출','operatingMargin'],['영업현금 / 매출','cfoMargin'],['투자자산 취득 / 매출','investmentMargin'],['투자 이후 현금 / 매출','cashMargin']]:[['매출 증가율','revenueGrowth'],['영업이익 / 매출','operatingMargin'],['영업현금 / 매출','cfoMargin'],['투자자산 취득 / 매출','capexIntensity'],['투자 이후 현금 / 매출','cashMargin']];
    return `<p class="comparison-period-basis">${trailingReady?'두 기업 모두 최근 일 년으로 연결한 공시 금액의 비율입니다.':'최근 일 년 연결 자료가 부족해 확보된 누적기간을 표시합니다.'}</p><p class="comparison-cautions">${cautions.length?esc(cautions.join(' · ')):'기간·회계 기준·투자지출 분류의 기본 조건 일치'}. 제품 구성·사업부·금융 자회사 차이는 별도 검토가 필요합니다.</p><div class="table-wrap" tabindex="0"><table class="company-peer-table"><thead><tr><th>관측 항목</th><th>${esc(c.name)}</th><th>${esc(other.name)}</th></tr></thead><tbody><tr><td>기간</td>${[c,other].map(x=>`<td>${period(x).start}–${period(x).end}<small>${period(x).days}일 · ${x.financials.standard}</small></td>`).join('')}</tr><tr><td>투자지출 정의</td>${[c,other].map(x=>`<td>${esc(scope(x))}</td>`).join('')}</tr>${pairs.map(([label,key])=>`<tr><td>${label}</td>${[c,other].map(x=>`<td>${pct(metrics(x)[key])}</td>`).join('')}</tr>`).join('')}<tr><td>원문</td>${[c,other].map(x=>`<td><a href="${esc(x.financials.current.cfo.sourceUrl)}" target="_blank" rel="noopener noreferrer">공시 ${x.financials.filedAt} ↗</a></td>`).join('')}</tr></tbody></table></div><p class="chart-caption">통화 간 금액을 합산하지 않고 비율을 비교합니다. 같은 비율도 회계 범위와 재투자가 다르면 가치평가의 우열이 아닙니다.</p><button class="arrow-link" data-company="${other.id}">${esc(other.name)} 분석으로 이동 ↗</button>`;
  }
  function render(c,payload) {
    const a=c.analysis;if(!a)return '';
    const others=payload.snapshot.companies.filter(x=>x.id!==c.id&&x.status==='ready').sort((x,y)=>Number(y.peerGroup===c.peerGroup)-Number(x.peerGroup===c.peerGroup)||Number(y.market!==c.market)-Number(x.market!==c.market));
    const b=a.profitBridge, cash=a.cashChange;
    const bridge=b?`<div class="driver-grid"><div><small>매출 변화 × 전년 영업이익률</small><strong>${amount(b.revenueEffect,c)}</strong></div><div><small>당기 매출 × 영업이익률 변화</small><strong>${amount(b.marginEffect,c)}</strong></div><div><small>영업이익 변화</small><strong>${amount(b.change,c)}</strong></div></div><p class="chart-caption">${unit(c)} · ${esc(b.definition)}. ${esc(b.limitation)}</p>`:'<p>동일 길이 전년 동기의 영업이익 자료가 없어 분해를 보류합니다.</p>';
    return `<div class="company-analysis"><section class="panel business-drivers"><span class="eyebrow">BUSINESS / CASH CHANGE</span><h2>이익과 현금은 무엇이 달라졌는가</h2><p class="panel-subtitle">${c.financials.priorStart||'비교 기간 미확보'}–${c.financials.priorEnd||''} → ${c.financials.start}–${c.financials.end}</p>${bridge}${cash?`<h3>투자자산 취득 후 현금 변화</h3><div class="driver-grid"><div><small>영업현금 변화</small><strong>${amount(cash.cfoEffect,c)}</strong></div><div><small>투자지출 변화의 차감 효과</small><strong>${amount(cash.investmentEffect,c)}</strong></div><div><small>현금잉여 변화</small><strong>${amount(cash.totalChange,c)}</strong></div></div><p class="chart-caption">${unit(c)} · ${esc(c.investmentScope)}. 주주에게 배분할 수 있는 정상 현금이나 FCFF가 아닙니다.</p>`:'<p>투자지출의 비교 범위를 확인하기 전까지 현금 변화 분해를 보류합니다.</p>'}<a href="${esc(c.financials.current.revenue.sourceUrl)}" target="_blank" rel="noopener noreferrer">계산에 사용한 공시 ↗</a></section><section class="panel annual-panel"><span class="eyebrow">HISTORY / ACCOUNTING PERIODS</span><h2>이번 현금 수준은 과거와 얼마나 다른가</h2>${(a.sourceGaps||[]).length?`<p class="comparison-cautions">과거 공시 추가 연결 실패: ${a.sourceGaps.map(g=>esc(g.accession)).join(' · ')}. 현재 반기 공시는 연결했으며, 해당 과거 기간은 보완이 필요합니다.</p>`:''}${(c.correctionNotes||[]).map(n=>`<p class="correction-note">정정 범위 확인: ${esc(n.scope)}. 원 사업보고서 ${esc(n.originalReceipt)}의 재무제표를 사용합니다. <a href="${esc(n.sources[1].url)}" target="_blank" rel="noopener noreferrer">첨부 정정표 ↗</a></p>`).join('')}${annualChart(a.annual)}<p class="chart-caption">${esc(a.annualScope)}. ${a.annual.length}개 구간이며 과거 수준을 정상 이익·미래 확률로 간주하지 않습니다.</p><details class="annual-sources"><summary>기간별 정의와 원문</summary><div class="table-wrap" tabindex="0"><table><thead><tr><th>기간</th><th>영업현금 마진</th><th>투자 후 현금 마진</th><th>투자 범위</th><th>원문</th></tr></thead><tbody>${a.annual.map(r=>`<tr><td>${r.start}–${r.end}</td><td>${pct(r.cfoMargin)}</td><td>${pct(r.cashMargin)}</td><td>${esc(r.investmentScope)}</td><td><a href="${esc(r.evidence[0].sourceUrl)}" target="_blank" rel="noopener noreferrer">${r.filedAt} ↗</a></td></tr>`).join('')}</tbody></table></div></details></section>${trailing(c)}<section class="panel business-questions"><span class="eyebrow">RESEARCH AGENDA / ${esc(c.sector||c.group)}</span><h2>${esc(a.title)}</h2><ol>${a.questions.map(q=>`<li>${esc(q)}</li>`).join('')}</ol><p class="chart-caption">${esc(a.questionStatus)}. ${esc(a.nextAction)}.</p></section>${others.length?`<section class="panel peer-analysis"><span class="eyebrow">COMPARISON / SHARED QUESTIONS</span><h2>다른 기업을 같은 기준으로 살펴보기</h2><label for="analysis-peer">비교 기업 선택</label><select id="analysis-peer">${others.map(x=>`<option value="${x.id}">${esc(x.name)} · ${x.id} · ${x.market}${x.peerGroup===c.peerGroup?' · 같은 조사 분류':''}</option>`).join('')}</select><div id="analysis-peer-body">${comparison(c,others[0])}</div></section>`:''}</div>`;
  }
  function bind(c,payload){const selector=document.querySelector('#analysis-peer');if(selector)selector.addEventListener('change',()=>{const other=payload.snapshot.companies.find(x=>x.id===selector.value);document.querySelector('#analysis-peer-body').innerHTML=comparison(c,other);});}
  window.EquityCompanyAnalysis={render,bind};
})();
