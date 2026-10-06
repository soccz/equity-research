(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=v=>v==null?'자료 미확인':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:2});
  function render(c){
    const h=c.segmentHistory;
    if(!h)return '';
    if(h.status==='definition_review_required')return `<section class="panel segment-period-hold"><h3>사업부 최근 1년 연결</h3><p>${esc(h.reason)}</p></section>`;
    const scale=c.currency==='KRW'?1e12:1e9, amount=v=>v==null?'자료 미확인':num(v/scale);
    const unit=c.currency==='KRW'?'조 원':'십억 달러', exact=v=>`${num(v)} ${c.currency==='KRW'?'원':'달러'}`;
    const metric=k=>k==='revenue'?'매출':'영업이익';
    const parts=s=>s?.components.map(p=>`<li>${p.coefficient>0?'+':'−'} <a href="${esc(p.fact.sourceUrl)}" target="_blank" rel="noopener noreferrer">${p.fact.start}–${p.fact.end} · ${amount(p.fact.value)} ↗</a><small>${esc(p.label)} · ${p.fact.accession} · 원문 표시 정밀도 ${esc(p.fact.decimals??'미확인')}</small></li>`).join('')||'<li>자료 미확인</li>';
    const reconciliation=(k,r)=>r.status==='unresolved'
      ? `<p><strong>${metric(k)} 대사:</strong> ${esc(r.reason)}</p>`
      : `<p><strong>${metric(k)} 대사:</strong> 부문 합계 ${amount(r.subtotal)} + 공시 조정 ${amount(r.adjustment)} + 남은 차이 ${amount(r.residual)} = 연결 ${amount(r.total.value)}<small>남은 차이 원 단위: ${exact(r.residual)} · ${r.status==='reconciled'?'세 기간 각각의 연결 수치 대사 확인':'기간별 차이 확인 필요'}</small></p>`;
    const periodTable=(k,r)=>!r.periods?'':`<h3>${metric(k)} · 합산 전 세 기간도 대사</h3><div class="table-wrap"><table><thead><tr><th>공시 기간</th><th>부문 합계</th><th>조정</th><th>연결</th><th>남은 차이 (${c.currency==='KRW'?'원':'달러'})</th></tr></thead><tbody>${r.periods.map(p=>`<tr><th>${esc(p.label)}<small>${p.start}–${p.end}</small></th><td>${amount(p.subtotal)}</td><td>${amount(p.adjustment)}</td><td>${amount(p.total)}</td><td>${num(p.residual)}</td></tr>`).join('')}</tbody></table></div>`;
    return `<section class="panel segment-period-bridge">
      <div class="segment-period-heading"><span class="eyebrow">BUSINESS / TRAILING YEAR</span><h2>사업부를 최근 1년으로 맞춰 읽기</h2><p class="panel-subtitle">${h.start}–${h.end} · ${unit} · 직전 연간 + 당기 누적 − 전년 누적</p></div>
      <p>${esc(h.review.note)}</p>
      <p class="chart-caption">${h.status==='ready'?'매출·영업이익의 세 기간 연결 대사 확인':'사업부 기간 연결 · 미대사 항목 포함. 차이를 임의로 다른 부문에 배분하지 않습니다.'}</p>
      <div class="table-wrap"><table><thead><tr><th>보고 부문</th><th>최근 1년 매출</th><th>최근 1년 영업이익</th><th>부문 이익률</th></tr></thead><tbody>${h.segments.map(s=>`<tr><th>${esc(s.label)}</th><td>${amount(s.revenue?.value)}</td><td>${amount(s.operatingIncome?.value)}</td><td>${s.margin==null?'미확인':num(s.margin*100)+'%'}</td></tr>`).join('')}</tbody></table></div>
      <div class="segment-period-reconciliations">${Object.entries(h.reconciliations).map(([k,r])=>reconciliation(k,r)).join('')}</div>
      <p class="chart-caption">${esc(h.scope)}</p>
      <details><summary>기간별 원문·부문 정의와 조정 확인</summary>
        ${Object.entries(h.reconciliations).map(([k,r])=>periodTable(k,r)).join('')}
        ${h.segments.map(s=>`<h3>${esc(s.label)}</h3><div class="segment-source-columns"><div><strong>매출의 세 기간</strong><ul>${parts(s.revenue)}</ul></div><div><strong>영업이익의 세 기간</strong><ul>${parts(s.operatingIncome)}</ul></div></div>`).join('')}
        ${Object.entries(h.reconciliations).map(([k,r])=>(r.adjustments||[]).map(p=>`<p>${metric(k)} 조정 ${p.coefficient>0?'+':'−'} ${esc(p.series?.components[0].fact.tag||'미확인')}</p><ul>${parts(p.series)}</ul>`).join('')).join('')}
        <p>${esc(h.review.reviewer)} · ${esc(h.review.scope)}</p>
        <p><a href="${esc(h.review.annualSource.primaryUrl||h.review.annualSource.url)}" target="_blank" rel="noopener noreferrer">직전 연간 부문 주석 ↗</a></p>
        ${(h.review.annualNotes||[{text:h.review.annualText}]).map(n=>`<blockquote>${esc(n.text)}</blockquote>`).join('')}
        ${h.review.currentPassages.map(p=>`<p><a href="${esc(p.sourceUrl)}" target="_blank" rel="noopener noreferrer">현재 공시 부문 정의 ↗</a></p><blockquote>${esc(p.text)}</blockquote>`).join('')}
      </details>
    </section>`;
  }
  window.EquitySegmentHistory={render};
})();
