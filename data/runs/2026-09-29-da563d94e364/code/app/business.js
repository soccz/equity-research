/* Operating-segment evidence and explicit cash/price assumptions. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=(v,d=2)=>v==null?'미확인':Number(v).toLocaleString('ko-KR',{minimumFractionDigits:d,maximumFractionDigits:d});
  const unit=c=>c.currency==='KRW'?'조 원':'십억 달러';
  const amount=(v,c)=>v==null?'미확인':num(v/(c.currency==='KRW'?1e12:1e9));
  const value=f=>f?.value??null;
  const pct=v=>v==null?'미확인':num(v*100,1)+'%';
  const fact=(f,c)=>f?`<a class="business-fact" href="${esc(f.sourceUrl)}" target="_blank" rel="noopener noreferrer" title="${esc(f.tag+' · '+f.accession)}">${amount(f.value,c)} ↗</a>`:'미확인';
  const block=(title,subtitle,body,cls='')=>`<section class="panel business-panel ${cls}"><span class="eyebrow">BUSINESS / CAPITAL EVIDENCE</span><h2>${title}</h2><p class="panel-subtitle">${subtitle}</p>${body}</section>`;
  function segments(c,b){
    const total=b.reconciliations.revenue.reportedTotal,colors=['#245d53','#819c81','#b17654'];
    const strip=`<div class="segment-strip" role="img" aria-label="부문별 외부 매출 구성">${b.segments.map((s,i)=>`<div style="width:${s.current.revenue.value/total*100}%;background:${colors[i]}"><span>${pct(s.current.revenue.value/total)}</span></div>`).join('')}</div><div class="policy-legend">${b.segments.map((s,i)=>`<span style="--swatch:${colors[i]}">${esc(s.label)}</span>`).join('')}</div>`;
    const table=`<div class="table-wrap" tabindex="0"><table class="business-table"><thead><tr><th>사업부</th><th>외부 매출</th><th>영업이익</th><th>전년 영업이익</th><th>이익 변화</th></tr></thead><tbody>${b.segments.map(s=>`<tr><th>${esc(s.label)}</th><td>${fact(s.current.revenue,c)}</td><td>${fact(s.current.operatingIncome,c)}</td><td>${fact(s.previous.operatingIncome,c)}</td><td>${s.previous.operatingIncome?amount(s.current.operatingIncome.value-s.previous.operatingIncome.value,c):'미확인'}</td></tr>`).join('')}</tbody></table></div>`;
    const rec=b.reconciliations.operatingIncome;
    return block('어느 사업에서 매출과 이익이 만들어졌는가',`${b.start}–${b.end} · ${unit(c)} · 비교 수치는 같은 공시에 실린 전년 동기`,strip+table+`<p class="chart-caption">${esc(b.segmentRevenueBasis)}</p><div class="business-reconcile"><span>부문 영업이익 합계 <b>${amount(rec.subtotal,c)}</b></span><span>공시 조정 ${rec.reportedAdjustment==null?'별도 조정 없이 합계 일치':amount(rec.reportedAdjustment,c)}</span><span>연결 영업이익 <b>${amount(rec.reportedTotal,c)}</b></span></div><p class="chart-caption">외부 매출 합계 ${amount(total,c)} ${unit(c)} · 연결 매출과 일치. 사업부 재편에 따른 전년 재표시 가능성이 있으며 과거 시점 투자 신호가 아닙니다.</p>`,'business-segments');
  }
  function bars(rows,c){
    const max=Math.max(...rows.map(r=>Math.abs(r.amount)),1);
    return `<div class="business-bars">${rows.map(r=>`<div class="business-bar"><span>${esc(r.label)}</span><div class="business-track"><i class="${r.amount<0?'negative':''}" style="left:${r.amount<0?50-Math.abs(r.amount)/max*48:50}%;width:${Math.abs(r.amount)/max*48}%"></i></div><b>${amount(r.amount,c)}</b></div>`).join('')}</div>`;
  }
  function cloud(c,b){
    const q=b.cash,l=b.leases,bal=b.balances;
    const cash=bars([{label:'보고 영업현금',amount:q.reportedCfo.value},{label:'현금 유형자산 취득',amount:-q.cashPurchases.value},{label:'금융리스 원금 상환',amount:-q.financingLeasePrincipal.value},{label:'세 항목 반영 잔액',amount:q.afterLeasePrincipal}],c);
    const other=`<div class="driver-grid"><div><small>비현금 금융리스 신규 취득</small><strong>${amount(value(l.noncashFinanceAdditions),c)}</strong></div><div><small>이미 영업현금에 반영된 금융리스 이자</small><strong>${amount(value(l.interest),c)}</strong></div><div><small>이미 영업현금에 반영된 영업리스 지급</small><strong>${amount(value(l.operatingPayments),c)}</strong></div></div>`;
    const capital=[['현금·현금성자산',bal.cash],['단기 투자자산',bal.shortInvestments],['장기차입금 유동분',bal.debtCurrent],['장기차입금 비유동분',bal.debtNoncurrent],['금융리스 부채',bal.financeLease],['영업리스 부채',bal.operatingLease]];
    return block('현금 지출과 리스 취득을 어떻게 구별하는가',`${unit(c)} · 당기 현금흐름과 신규 비현금 취득 분리`,cash+other+`<p class="chart-caption">${esc(q.limitation)}</p><details><summary>현금·리스 원문 항목</summary>${[q.reportedCfo,q.cashPurchases,...Object.values(l)].filter(Boolean).map(f=>`<p>${esc(f.tag)} · ${fact(f,c)}</p>`).join('')}</details>`,'business-leases')+block('같은 기말의 현금·차입금·리스는 얼마인가',`${b.end} · ${unit(c)} · 현금 유출이 아닌 재무상태 잔액`,`<div class="table-wrap"><table class="business-table"><thead><tr><th>항목</th><th>공시 잔액</th></tr></thead><tbody>${capital.map(([label,f])=>`<tr><td>${label}</td><td>${fact(f,c)}</td></tr>`).join('')}</tbody></table></div><p class="chart-caption">장기차입금 유동·비유동 합계 ${amount(bal.debt.value,c)}, 현금·단기투자 합계 ${amount(bal.cashAndInvestments.value,c)}를 각각 원문 합계와 대사했습니다. 이 표의 잔액만으로 순기업가치나 배분 가능 현금을 확정하지 않습니다.</p>`,'business-capital');
  }
  function automotive(c,b){
    const r=b.reconciliations.cfo,fields=[['영업현금','cfo'],['유형·무형 취득·처분 순현금','netAssetCash'],['현금·현금성자산 잔액','cash'],['유동 차입금 잔액','debtCurrent'],['비유동 차입금 잔액','debtNoncurrent'],['유동 금융채권 잔액','financialReceivablesCurrent'],['비유동 금융채권 잔액','financialReceivablesNoncurrent']];
    const t=`<div class="table-wrap" tabindex="0"><table class="business-table"><thead><tr><th>항목</th>${b.segments.map(s=>`<th>${esc(s.label)}</th>`).join('')}</tr></thead><tbody>${fields.map(([label,k])=>`<tr><th>${label}</th>${b.segments.map(s=>`<td>${fact(s.current[k],c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    return block('자동차와 금융의 현금·차입을 나누어 읽기',`${unit(c)} · 현금흐름 ${b.start}–${b.end} / 잔액 ${b.end}`,bars(b.segments.map(s=>({label:s.label+' 영업현금',amount:s.current.cfo.value})),c)+t+`<p class="chart-caption">금융채권은 금융부문의 자산 전체가 아닙니다. 유형·무형 취득·처분 순현금은 연결 총유형자산 취득과 범위가 달라 직접적인 현금잉여 비교에 사용하지 않습니다.</p><p class="chart-caption">${esc(b.balancePeriodNote)}</p><div class="business-unresolved"><h3>부문 현금과 연결 현금의 차이</h3><p>부문 합계 ${amount(r.subtotal,c)} → 연결 영업현금 ${amount(r.reportedTotal,c)} · <strong>원인 미연결 ${amount(r.unexplained,c)} ${unit(c)}</strong></p><p>수치 차이를 내부거래 제거액으로 단정하지 않습니다. 연결 조정과 분류에 관한 공시 근거를 추가로 확인해야 합니다.</p></div><p>연결 리스부채: 유동 ${fact(b.balances.leaseCurrent,c)} / 비유동 ${fact(b.balances.leaseNoncurrent,c)} ${unit(c)}. 부문별로 임의 배분하지 않습니다.</p>`,'business-finance');
  }
  function pricing(c,b){
    if(!b.pricing)return block('가격 판단 전에 필요한 가치 구분','가격 역산 보류',`<p>${esc(b.pricingHold)}</p>`,'business-price-hold');
    const p=b.pricing;
    return block('이 주식가치에 필요한 연간 현금은 얼마인가',`공시 주식수 ${p.shareDate} × 종가 ${p.priceDate} · ${p.shareAgeDays}일 시점 차이`, `<p>근사 주식가치 ${amount(p.marketCapProxy,c)} ${unit(c)} · 아래 성장률과 요구수익률은 사용자가 조정하는 가정입니다.</p><div class="control-grid"><label>향후 5년 현금 성장률 <output id="business-growth-value">10%</output><input id="business-growth" type="range" min="-10" max="30" step="1" value="10"></label><label>주주 요구수익률 <output id="business-discount-value">11%</output><input id="business-discount" type="range" min="6" max="18" step="1" value="11"></label></div><p class="chart-caption">이후 영구 성장률 2% 고정 · 지급 시점은 연말 · 주식가치에 대한 현금 할인 모형</p><div id="business-price-result" aria-live="polite"></div><p class="chart-caption">${esc(p.limitation)}</p>`,'business-pricing');
  }
  function render(c){
    const b=c.business;if(!b)return '';
    if(b.status!=='ready')return block('사업부 원문 연결 상태','추가 공시 확보 필요',`<p>${esc(b.reason)}</p>`);
    return `<div class="business-review">${segments(c,b)}${b.profile==='cloud_capital_and_leases'?cloud(c,b):automotive(c,b)}${pricing(c,b)}${block('확인된 계산과 아직 남은 질문','공시 계산 · 독립 금융 해석 승인 전',`<ul>${b.findings.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><h3>다음 조사</h3><ol>${b.remaining.map(x=>`<li>${esc(x)}</li>`).join('')}</ol><p class="chart-caption">공시 ${b.filedAt} · ${esc(b.accession)} · 사업부 자료는 연결 재무와 별도로 범위를 확인합니다.</p><a href="${esc(b.source.primaryUrl||b.source.url)}" target="_blank" rel="noopener noreferrer">사용한 공시 원문 ↗</a><details class="technical"><summary>보존 원문과 분석 무결성</summary><a href="../${esc(b.source.file)}">XBRL 원본 사본</a><code>${esc(b.source.sha256)}</code><code>${esc(b.evidenceHash)}</code></details>`)}</div>`;
  }
  function bind(c){
    if(!c.business?.pricing)return;
    const update=()=>{
      const g=Number(document.querySelector('#business-growth').value)/100,k=Number(document.querySelector('#business-discount').value)/100,p=c.business.pricing;
      const r=window.EquityDossier.pricing(p.marketCapProxy,g,k,.02,5);
      document.querySelector('#business-growth-value').textContent=pct(g);document.querySelector('#business-discount-value').textContent=pct(k);
      document.querySelector('#business-price-result').innerHTML=`<div class="driver-grid"><div><small>필요한 기준연도 배분 가능 현금</small><strong>${amount(r.requiredBaseCash,c)}</strong></div><div><small>관측 현금 잔액 · 정상화 전</small><strong>${amount(p.referenceCash,c)}</strong></div><div><small>영구가치의 현재가치 비중</small><strong>${pct(r.terminalShare)}</strong></div></div><p class="chart-caption">${unit(c)} / 년 · 관측 잔액 정의: ${esc(p.referenceDefinition)}. 두 현금은 같은 경제적 정의가 아니므로 차액을 저평가·고평가나 목표가로 바꾸지 않습니다.</p>`;
    };
    for(const id of ['business-growth','business-discount'])document.querySelector('#'+id).addEventListener('input',update);
    update();
  }
  window.EquityBusiness={render,bind};
})();
