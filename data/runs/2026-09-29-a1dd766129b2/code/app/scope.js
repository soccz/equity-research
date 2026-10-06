(() => {
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function render(c){
    const s=c.cashScope;if(s?.status!=='review_required')return '';
    const amount=f=>f?`${(f.value/(c.currency==='KRW'?1e12:1e9)).toLocaleString('ko-KR',{maximumFractionDigits:4})}`:'항목 미확인';
    return `<section class="panel cash-scope"><span class="eyebrow">BUSINESS PERIMETER / CASH FLOW</span><h2>사업 분리 전후의 현금 범위를 먼저 대사</h2><p>${esc(s.reason)}</p><div class="table-wrap"><table><thead><tr><th>최근 일 년을 구성하는 기간</th><th>보고 영업현금</th><th>별도 공시한 중단영업 영업현금</th></tr></thead><tbody>${s.observations.map(o=>`<tr><th>${esc(o.label)}<small>${o.reportedCfo.start}–${o.reportedCfo.end}</small></th><td><a href="${esc(o.reportedCfo.sourceUrl)}" target="_blank" rel="noopener noreferrer">${amount(o.reportedCfo)} ↗</a></td><td>${o.discontinuedCfo?`<a href="${esc(o.discontinuedCfo.sourceUrl)}" target="_blank" rel="noopener noreferrer">${amount(o.discontinuedCfo)} ↗</a>`:'항목 미확인'}</td></tr>`).join('')}</tbody></table></div><p class="chart-caption">${c.currency==='KRW'?'조 원':'십억 달러'} · ${esc(s.rule)}</p><p>원문 합계와 별도 공시된 금액을 병치합니다. 계속영업 매출에 대응하는 현금·투자 취득의 범위를 확인하기 전 임의의 정상 현금이나 적정가치를 계산하지 않습니다. 자료 범위 문제를 사업 악화나 회피 의견으로 바꾸지 않습니다.</p></section>`;
  }
  window.EquityScope={render};
})();
