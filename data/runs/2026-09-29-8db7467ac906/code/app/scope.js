(() => {
  window.addEventListener('beforeprint',()=>document.querySelectorAll('.cash-sign-review details:not([open])').forEach(e=>{e.dataset.scopePrintOpened='1';e.open=true;}));
  window.addEventListener('afterprint',()=>document.querySelectorAll('[data-scope-print-opened]').forEach(e=>{e.open=false;delete e.dataset.scopePrintOpened;}));
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function signReview(review){
    if(!review)return '';
    if(review.status!=='source_conflict')return `<div class="cash-sign-review"><h3>공시 부호를 다시 대사해야 함</h3><p>${esc(review.reason)}</p></div>`;
    const amount=x=>(x/1000).toLocaleString('ko-KR',{maximumFractionDigits:0,signDisplay:'always'});
    return `<div class="cash-sign-review"><h3>원문 안의 부호 불일치 · 값 선택 보류</h3><p>같은 기간의 중단영업 영업현금이 XBRL과 본문 주석에서 반대 부호로 표시되어 있습니다. 아래 두 값은 각각 보존한 원문에서 읽은 수치입니다.</p><div class="table-wrap"><table><thead><tr><th>기간</th><th>XBRL</th><th>본문 주석</th><th>계산에 채택한 값</th></tr></thead><tbody>${review.observations.map(o=>`<tr><th>${esc(o.label)}<small>${esc(o.start)}–${esc(o.end)}</small></th><td><a href="${esc(o.xbrl.sourceUrl)}" target="_blank" rel="noopener noreferrer">${amount(o.xbrl.value)} ↗</a></td><td><a href="${esc(o.narrative.sourceUrl)}" target="_blank" rel="noopener noreferrer">${amount(o.narrative.value)} ↗</a></td><td>선택 보류</td></tr>`).join('')}</tbody></table></div><p class="chart-caption">천 원 · ${esc(review.rule)}</p><details><summary>대조한 원문과 현금흐름 표 확인</summary>${[...new Map(review.observations.map(o=>[o.narrative.sourceHash,o.narrative])).values()].map(d=>`<div class="cash-sign-source"><h4>접수 ${esc(d.accession)} · 본문 표 ${d.tableIndex+1}</h4><p class="chart-caption">원문 SHA-256 ${esc(d.sourceHash)} · ${esc(d.sourceUnit)} · 원문 부호와 대시 그대로</p><div class="table-wrap"><table><tbody>${d.rows.map(row=>`<tr>${row.map((cell,i)=>`<${i?'td':'th'}>${esc(cell)}</${i?'td':'th'}>`).join('')}</tr>`).join('')}</tbody></table></div></div>`).join('')}</details></div>`;
  }
  function render(c){
    const s=c.cashScope;if(s?.status!=='review_required')return '';
    const amount=f=>f?`${(f.value/(c.currency==='KRW'?1e12:1e9)).toLocaleString('ko-KR',{maximumFractionDigits:4})}`:'항목 미확인';
    return `<section class="panel cash-scope"><span class="eyebrow">BUSINESS PERIMETER / CASH FLOW</span><h2>사업 분리 전후의 현금 범위를 먼저 대사</h2><p>${esc(s.reason)}</p>${signReview(s.signReview)}<div class="table-wrap"><table><thead><tr><th>최근 일 년을 구성하는 기간</th><th>보고 영업현금</th><th>${s.signReview?'XBRL 중단영업 영업현금 · 부호 대조 필요':'별도 공시한 중단영업 영업현금'}</th></tr></thead><tbody>${s.observations.map(o=>`<tr><th>${esc(o.label)}<small>${o.reportedCfo.start}–${o.reportedCfo.end}</small></th><td><a href="${esc(o.reportedCfo.sourceUrl)}" target="_blank" rel="noopener noreferrer">${amount(o.reportedCfo)} ↗</a></td><td>${o.discontinuedCfo?`<a href="${esc(o.discontinuedCfo.sourceUrl)}" target="_blank" rel="noopener noreferrer">${amount(o.discontinuedCfo)} ↗</a>`:'항목 미확인'}</td></tr>`).join('')}</tbody></table></div><p class="chart-caption">${c.currency==='KRW'?'조 원':'십억 달러'} · ${esc(s.rule)}</p><p>원문 합계와 별도 공시된 금액을 병치합니다. 계속영업 매출에 대응하는 현금·투자 취득의 범위를 확인하기 전 임의의 정상 현금이나 적정가치를 계산하지 않습니다. 자료 범위 문제를 사업 악화나 회피 의견으로 바꾸지 않습니다.</p></section>`;
  }
  window.EquityScope={render};
})();
