/* Research trade-offs and append-only interpretation history. */
(() => {
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct=x=>x==null?'미확인':(100*x).toLocaleString('ko-KR',{maximumFractionDigits:1})+'%';
  const pp=x=>x==null?'미확인':(x>0?'+':'')+(100*x).toLocaleString('ko-KR',{maximumFractionDigits:1})+'%p';
  const statuses={pending:'새 공시 대기',met:'조건 충족',not_met:'조건 미충족',unresolved:'비교 확인 필요'};
  function peerChart(c,r){
    const rows=[{id:c.id,name:c.name,metrics:c.trailingYear.metrics},...r.peers.filter(p=>p.investmentComparable)];
    const lo=Math.min(0,...rows.flatMap(x=>[x.metrics.cashMargin,x.metrics.investmentMargin])),hi=Math.max(.01,...rows.flatMap(x=>[x.metrics.cashMargin,x.metrics.investmentMargin]));
    const x=v=>210+(v-lo)/(hi-lo)*440,zero=x(0);
    return `<svg class="research-peer-chart" viewBox="0 0 820 ${rows.length*58+45}" role="img" aria-label="조사 비교군의 최근 일 년 투자 후 현금 비율과 투자 부담"><line x1="${zero}" x2="${zero}" y1="10" y2="${rows.length*58+6}" stroke="#86969a"/>${rows.map((p,i)=>`<text x="6" y="${i*58+32}" fill="currentColor" font-size="14">${esc(p.name.slice(0,20))}</text>${['cashMargin','investmentMargin'].map((key,j)=>`<rect x="${Math.min(zero,x(p.metrics[key]))}" y="${i*58+10+j*20}" height="15" width="${Math.max(.5,Math.abs(x(p.metrics[key])-zero))}" fill="${j?'#bba57c':'#287c7c'}"/><text x="${Math.max(zero,x(p.metrics[key]))+6}" y="${i*58+23+j*20}" font-size="12" fill="currentColor">${pct(p.metrics[key])}</text>`).join('')}`).join('')}<text x="210" y="${rows.length*58+30}" font-size="12" fill="currentColor">청록: 투자 후 현금 / 매출 · 황토: 투자자산 취득 / 매출</text></svg>`;
  }
  function history(c,payload){
    const journal=payload.researchJournal;if(!journal)return '';
    const rows=journal.history.filter(r=>r.company===c.id),watches=journal.watches.filter(r=>r.registration.company===c.id);
    const revisions=rows.map((r,i)=>{
      const old=rows[i-1],sameFiling=old?.basis.accession===r.basis.accession;
      const days=period=>(Date.parse(period[1])-Date.parse(period[0]))/86400000+1;
      const sameLength=old&&Math.abs(days(old.basis.period)-days(r.basis.period))<=8;
      const changes=[];
      if(old){
        if(!sameFiling)changes.push('새 접수 공시 반영');
        if(old.case.pricing.state!==r.case.pricing.state)changes.push(`연구 판단 ${old.case.pricing.state} → ${r.case.pricing.state}`);
        if(old.basis.price!==r.basis.price)changes.push(`가격 ${old.basis.price.toLocaleString('ko-KR')} → ${r.basis.price.toLocaleString('ko-KR')} ${c.currency}`);
        if(!sameLength)changes.push('공시 기간 길이가 달라 현금 마진의 직접 변화 해석 보류');
        else if(r.basis.metrics.cashMargin!==old.basis.metrics.cashMargin)changes.push('보고 현금 마진 차이 '+pp(r.basis.metrics.cashMargin-old.basis.metrics.cashMargin));
        if(!changes.length)changes.push('판단·관측 가격 유지 · 근거 또는 비교 정의 갱신');
      }
      const change=old?changes.map(esc).join(' · '):'최초 보존. 이전 시점 의견을 소급 작성하지 않았습니다.';
      return `<li><strong>${esc(r.case.pricing.state)}</strong><small>기록 ${new Date(r.recordedAt).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})} · 공시 ${esc(r.basis.filedAt)}</small><p>${change}</p><p>${esc(r.case.pricing.statement)}</p><details class="technical"><summary>당시 내용·해시와 공시</summary><p>${esc(r.case.thesis)} · ${esc(r.case.countercase)}</p><a href="${esc(r.case.source)}" target="_blank" rel="noopener noreferrer">접수 ${esc(r.basis.accession)} ↗</a><code>${esc(r.hash)}</code><code>${esc(r.snapshotHash)}</code></details></li>`;
    }).reverse().join('');
    return `<section class="panel research-journal"><div class="research-journal-heading"><span class="eyebrow">THESIS / REVISION HISTORY</span><h2>판단이 달라진 내용과 앞으로 확인할 조건</h2><p>조건의 성립을 추적합니다. 방향 예측을 등록하지 않았으므로 조건 미충족을 예측 실패로 채점하지 않습니다.</p></div>${watches.length?`<div class="table-wrap"><table><thead><tr><th>공시 전에 고정한 조건</th><th>판정</th><th>등록 시점 · 기준선</th></tr></thead><tbody>${watches.map(w=>`<tr><th>${esc(w.registration.condition.label)}<small>${esc(w.registration.condition.weakens)}</small></th><td>${esc(statuses[w.observation.status])}${w.observation.value!=null?'<small>'+pp(w.observation.value)+'</small>':''}</td><td>${w.registration.recordedAt.slice(0,10)}<small>전년 동기 변화 ${pp(w.registration.condition.baseline)} 초과 · 예측 없음</small></td></tr>`).join('')}</tbody></table></div>`:'<p>현재 연구 조건은 등록 전입니다. 로컬 갱신 실행 시 현재 시점으로 고정합니다.</p>'}<details class="research-revisions" open><summary>보존한 연구 판단 ${rows.length}건</summary><ol>${revisions||'<li>최초 기록 전</li>'}</ol></details><p class="chart-caption">${esc(journal.scope)}. 기간 길이가 다른 공시의 변화는 성장률로 해석하지 않습니다.</p></section>`;
  }
  function render(c,payload){
    const r=c.researchCase;if(!r)return '';
    const p=r.pricing;
    return `<section class="panel research-case"><span class="eyebrow">COMPANY THESIS / PRICE CONDITIONS</span><div class="panel-head"><div><h2>${esc(r.thesis)}</h2><p class="panel-subtitle">${esc(r.observationScope)}</p></div><span class="pillar">${esc(p.state)}</span></div><p class="research-case-statement">${esc(p.statement)}</p>${r.interpretation?`<p class="research-business-interpretation"><strong>원문 대조 연구 해석</strong> ${esc(r.interpretation)}</p>`:''}${p.basis==='issuer_operating_cash_path'?`<div class="research-operating-basis"><p>기업별 사업 현금 모델 · ${esc(p.sourcePeriod.join('–'))} · 명시적 연구 가정</p>${p.requiredCashMargin!=null?`<p>선택 경로의 6년차 현금 / 매출 ${pct(p.referenceCashMargin)} · 현재 가격에 필요한 비율 ${pct(p.requiredCashMargin)}. 첫 5년 현금과 말기 재투자를 포함한 역산이며 현재 영업현금 비율과 다릅니다.</p>`:'<p>사업 현금 경로와 증권별 배분·별도 투자 가치 검토를 구분합니다. 미확인 권리와 미평가 자산을 영으로 놓지 않습니다.</p>'}</div>`:''}<p><strong>경쟁하는 해석</strong> ${esc(r.countercase)}</p>${p.requiredCfoMargin!=null?`<p>기본 가정에서 현재 가격에 필요한 영업현금 / 매출 ${pct(p.requiredCfoMargin)}. 비교한 과거 범위 ${p.historicalRange.map(pct).join('–')}. 아래 작업표에서 가정을 바꾸면 가격 조건이 달라집니다.</p>`:''}${r.segments.length?`<div class="table-wrap"><table class="research-segment-change"><thead><tr><th>보고 부문</th><th>전년 매출 변화</th><th>당기 영업이익률</th><th>전년 대비 차이</th></tr></thead><tbody>${r.segments.map(s=>`<tr><th><a href="${esc(s.source)}" target="_blank" rel="noopener noreferrer">${esc(s.label)} ↗</a></th><td>${pct(s.revenueGrowth)}</td><td>${pct(s.margin)}</td><td>${pp(s.marginChange)}</td></tr>`).join('')}</tbody></table></div><p class="chart-caption">같은 공시에 제시된 전년 부문과 비교합니다. 내부거래·본사 비용은 위 부문 대사 범위를 따르며, 합계의 연결 기여도로 바꾸지 않습니다.</p>`:''}<h3>어떤 자료가 들어오면 판단이 달라지는가</h3><ul>${r.nextEvidence.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p class="chart-caption">${esc(r.scope)}</p></section>${r.peers.length?`<section class="panel research-tradeoffs"><span class="eyebrow">PEER TRADE-OFFS / TRAILING YEAR</span><h2>비교 기업보다 어떤 조건을 더 요구하는가</h2><p>같은 조사 분류의 연결 회사 비교입니다. 사업 구성·회계 분류를 일치시킨 순위가 아니며 금액을 환산해 합치지 않습니다.</p>${peerChart(c,r)}<p class="chart-caption">막대는 투자자산 취득 범위가 같은 기업만 표시합니다. 범위가 다른 기업은 아래 표에서 비교 보류로 남깁니다.</p><div class="table-wrap"><table><thead><tr><th>비교 대상</th><th>${esc(c.id)}의 현금 비율 차이</th><th>${esc(c.id)}의 투자 비율 차이</th><th>조사 판단과 비교 범위</th></tr></thead><tbody>${r.peers.map(p=>`<tr><th><a class="arrow-link" href="#company/${esc(p.id)}" data-company="${esc(p.id)}">${esc(p.name)} ↗</a><small>${p.period.join('–')}</small></th><td>${p.investmentComparable?pp(p.differences.cashMargin):'정의 차이로 보류'}</td><td>${p.investmentComparable?pp(p.differences.investmentMargin):'정의 차이로 보류'}</td><td>${esc(p.conclusion)}<small>${esc(p.cautions.join(' · ')||'기본 기간·회계·투자 정의 일치; 제품 구성은 별도 확인')}</small><a href="${esc(p.source)}" target="_blank" rel="noopener noreferrer">비교 원문 ↗</a></td></tr>`).join('')}</tbody></table></div></section>`:''}${history(c,payload)}`;
  }
  window.EquityResearchCase={render};
})();
