/* Reported capital facts: no inferred zeroes, net-debt total or normalized FCF. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=v=>Number(v).toLocaleString('ko-KR',{maximumFractionDigits:2});
  function fact(f,c){
    if(!f)return '<span class="muted">미확인</span>';
    const scale=f.unit==='shares'?1e6:c.currency==='KRW'?1e12:1e9;
    return `<a href="${esc(f.sourceUrl)}" target="_blank" rel="noopener noreferrer" title="${esc(f.tag+' · '+f.accession+' · '+(f.start||'기말')+'–'+f.end)}">${num(f.value/scale)}${f.unit==='shares'?' 백만 주':''} ↗</a>`;
  }
  function render(c){
    const b=c.capital;if(!b)return '';
    if(b.status!=='ready')return `<section class="panel capital-review"><h2>현금·자본 원문 연결 상태</h2><p>${esc(b.reason)}</p></section>`;
    const unit=c.currency==='KRW'?'조 원':'십억 달러';
    const balances=Object.values(b.balances).filter(r=>r.current);
    const flows=Object.values(b.flows).filter(r=>r.current||r.previous);
    const gaps=b.gaps.filter(g=>g.period[1]===b.end);
    const balanceTable=`<div class="table-wrap"><table><thead><tr><th>기말 항목</th><th>공시 잔액</th></tr></thead><tbody>${balances.map(r=>`<tr><th>${esc(r.label)}</th><td>${fact(r.current,c)}</td></tr>`).join('')}</tbody></table></div>`;
    const flowTable=`<div class="table-wrap" tabindex="0"><table><thead><tr><th>기간 항목</th><th>당기</th><th>같은 공시의 전년 동기</th></tr></thead><tbody>${flows.map(r=>`<tr><th>${esc(r.label)}</th><td>${fact(r.current,c)}</td><td>${fact(r.previous,c)}</td></tr>`).join('')}</tbody></table></div>`;
    return `<section class="panel capital-review"><span class="eyebrow">CASH / CAPITAL / DISTRIBUTIONS</span><h2>주주 현금과 회계 이익 사이에서 확인할 항목</h2><p class="panel-subtitle">${b.start}–${b.end} · ${unit} · 주식수는 백만 주 · 비현금 비용과 실제 지급을 구분</p>${flowTable}<p class="chart-caption">${esc(b.cash.limitation)}</p><p class="chart-caption">배당과 자기주식 매입은 현금 배분 내역입니다. 이를 영업현금에서 다시 차감해 투자 전 현금으로 표시하지 않습니다.</p></section><section class="panel capital-balances"><span class="eyebrow">BALANCE / AS OF ${b.end}</span><h2>같은 기말의 유동성과 자본 구조</h2><p class="panel-subtitle">${unit} · 차입금 항목끼리 겹칠 수 있어 합산하지 않음</p>${balanceTable}<ul>${b.limits.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>${gaps.length?`<details><summary>추가 확인할 항목 ${gaps.length}개</summary><ul>${gaps.map(g=>`<li>${esc((b.balances[g.metric]||b.flows[g.metric])?.label||g.metric)}: ${esc(g.reason)}</li>`).join('')}</ul></details>`:''}<p class="chart-caption">공시 ${b.filedAt} · <a href="${esc(b.source.primaryUrl||b.source.url)}" target="_blank" rel="noopener noreferrer">사용한 원문 ↗</a></p></section>`;
  }
  window.EquityCapital={render};
})();
