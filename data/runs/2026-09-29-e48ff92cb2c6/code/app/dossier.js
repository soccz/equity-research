/* Local research views. Financial quantities are deterministic; model prose is labelled. */
(() => {
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = (v,d=2) => Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d,minimumFractionDigits:d});
  const unit = c => c.currency==='KRW'?'조 원':'십억 달러';
  const amount = (v,c) => number(v/(c.currency==='KRW'?1e12:1e9));
  const percent = v => number(v*100,1)+'%';
  function pricing(cap,g,k,t=.02,n=5) {
    if (![cap,g,k,t,n].every(Number.isFinite)||cap<=0||g<=-.9||g>=1||k<=0||k>=1||t<=-.1||t>=k||!Number.isInteger(n)||n<1||n>30) throw new Error('Invalid equity cash assumptions');
    let a=0;for(let i=1;i<=n;i++)a+=(1+g)**i/(1+k)**i;
    const tail=(1+g)**n*(1+t)/(k-t)/(1+k)**n;
    return {requiredBaseCash:cap/(a+tail),terminalShare:tail/(a+tail)};
  }
  function sensitivity(c,terminal,growth,discount) {
    const cap=c.dossier.pricing.marketCapProxy, annualRevenue=c.financials.current.revenue.value*365/c.financials.days;
    const rows=[.08,.11,.14],columns=[0,.1,.2];
    const values=rows.flatMap(k=>columns.map(g=>pricing(cap,g,k,terminal).requiredBaseCash));
    const low=Math.min(...values),high=Math.max(...values);
    return `<h3>가정을 함께 바꾸면 필요한 현금은 얼마나 달라지는가</h3><p class="chart-caption">각 칸은 필요한 기준연도 배분 가능 현금 / 단순 연환산 매출입니다. 색이 진할수록 필요한 현금이 큽니다. 칸을 선택하면 위 가정도 함께 바뀝니다.</p><div class="table-wrap" tabindex="0"><table class="sensitivity-table"><caption>요구수익률 × 향후 5년 성장률 · 영구 성장 ${percent(terminal)}</caption><thead><tr><th scope="col">요구수익률 ↓<br>5년 성장률 →</th>${columns.map(g=>`<th scope="col">${percent(g)}</th>`).join('')}</tr></thead><tbody>${rows.map(k=>`<tr><th scope="row">${percent(k)}</th>${columns.map(g=>{
      const r=pricing(cap,g,k,terminal),shade=.06+.24*(r.requiredBaseCash-low)/(high-low||1),selected=Math.abs(g-growth)<1e-9&&Math.abs(k-discount)<1e-9;
      return `<td><button data-price-growth="${g}" data-price-discount="${k}" aria-pressed="${selected}" aria-label="성장 ${percent(g)}, 요구수익률 ${percent(k)}, 필요 현금 ${amount(r.requiredBaseCash,c)} ${unit(c)}" style="background:rgba(53,110,98,${shade})"><strong>${percent(r.requiredBaseCash/annualRevenue)}</strong><small>${amount(r.requiredBaseCash,c)} ${unit(c)}</small>${selected?'<span class="scenario-selected">선택</span>':''}</button></td>`;
    }).join('')}</tr>`).join('')}</tbody></table></div><p class="context-note">이 격자의 필요 현금 범위 ${amount(low,c)}–${amount(high,c)} ${unit(c)}. 공시 현금흐름을 정상화한 값이나 가능한 현금의 상·하한은 아닙니다.</p>`;
  }
  function bridge(c,period='current') {
    const b=c.dossier[period];if(!b)return '<p>같은 기간 비교 원문이 없습니다.</p>';
    const max=Math.max(...b.parts.map(p=>Math.abs(p.value)),1);
    return `<p class="context-note">${b.start}–${b.end} · ${unit(c)} · 부호는 영업현금 연결 효과</p><div class="cash-bridge" role="table" aria-label="순이익에서 영업현금으로 연결">${b.parts.map(p=>{
      const w=Math.abs(p.value)/max*48;
      return `<div class="cash-bridge-row ${p.kind==='total'?'cash-total':''}" role="row"><span role="cell">${esc(p.label)}${p.kind==='residual'?'<small>원인 미확인 · 합계를 맞춘 잔액</small>':''}</span><div class="cash-bridge-track" aria-hidden="true"><i class="${p.value<0?'negative':'positive'}" style="left:${p.value<0?50-w:50}%;width:${w}%"></i></div><strong role="cell">${amount(p.value,c)}</strong></div>`;
    }).join('')}</div><p class="chart-caption">분해 잔액 / 영업현금 절댓값: ${percent(b.residualShare)}. 비현금 조정의 더하기는 현금 유입을 뜻하지 않습니다. 채권·재고의 현금 효과는 원문 부호를 검토해 통일했습니다.</p>`;
  }
  function computedObservations(c) {
    const e=Object.fromEntries(c.dossier.evidence.map(x=>[x.id,x]));
    const rows=[['receivables','채권의 현금 효과'],['cfo','영업현금흐름'],['revenue','매출']].map(([id,label])=>{
      const a=e['previous.'+id],b=e['current.'+id];if(!a||!b)return '';
      const diff=b.value-a.value;
      const direction=diff>0?'증가':diff<0?'감소':'같음';
      const message=id==='receivables'&&b.value<a.value&&a.value<=0?'채권 변동에 따른 현금 사용 증가':label+' '+direction;
      return `<article class="observation-card"><span class="mini-label">공시에서 계산 · ${esc(label)}</span><h3>${esc(message)}</h3><div class="observation-values"><div><small>전년 동기</small><strong>${amount(a.value,c)}</strong></div><span aria-hidden="true">→</span><div><small>당기</small><strong>${amount(b.value,c)}</strong></div></div><p class="observation-delta">차이 ${diff>0?'+':''}${amount(diff,c)} ${unit(c)}</p><div class="claim-evidence"><a href="${esc(b.sourceUrl)}" target="_blank" rel="noopener noreferrer">${a.start}–${a.end}<br>${b.start}–${b.end} · 공시 ↗</a></div></article>`;
    }).join('');
    return `<div class="computed-observations"><span class="eyebrow">OBSERVATION → EXPLANATION → NEXT EVIDENCE</span><h2>관측에서 설명으로 넘어갈 때</h2><div class="observation-grid">${rows}</div><p class="chart-caption">현금 사용 증가만으로 고객 신용이나 회수의 악화를 확정하지 않습니다. 매출 성장과 회수 지연을 구별하려면 채권의 연령·대손·후속 회수를 더 살펴야 합니다.</p></div>`;
  }
  function structuredReview(c,r) {
    const labels={hypothesis:'가능한 설명',alternative:'경쟁하는 설명',distinguish:'다음 공시에서 구별할 관측',missing:'아직 필요한 근거'};
    const states={supported:'입력과 일치한다고 자체 판정',conditional:'조건부 서술로 자체 판정',unsupported:'근거 없는 단정 지적',contradicted:'입력과 충돌 지적',unresolved:'판독 미해결'};
    const allowed={hypothesis:'conditional',alternative:'conditional',distinguish:'conditional',missing:'supported'};
    const assessments=Object.fromEntries(r.scrutiny.assessments.map(a=>[a.id,a]));
    const cards=Object.entries(labels).map(([id,label])=>{
      const a=assessments[id],ok=a.classification===allowed[id]&&!r.styleFindings?.[id];
      return `<article class="hypothesis-card ${ok?'':'needs-review'}" data-research-role="${id}"><span class="mini-label">AI 제안 · ${label}</span><h3>${esc(r.notes[id])}</h3><details class="sentence-review"><summary>${esc(states[a.classification])}</summary><p>${esc(a.reason)}</p>${r.styleFindings?.[id]?`<p class="failed-status">${esc(r.styleFindings[id])}</p>`:''}<blockquote>${esc(a.quote)}</blockquote></details></article>`;
    }).join('');
    const evidence=Object.fromEntries(c.dossier.evidence.map(e=>[e.id,e]));
    const links=r.notes.evidence.map(id=>{const e=evidence[id];return `<a href="${esc(e.sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(e.label)} ${amount(e.value,c)} ${unit(c)}<small>${e.start}–${e.end} · ${esc(id)}</small></a>`;}).join('');
    const reviewBody=`<div class="hypothesis-grid role-grid">${cards}</div><div class="claim-evidence"><strong>가설의 출발점인 관측 · 원인 증명은 별도</strong>${links}</div>`;
    const gate=r.currentEvaluation||r.evaluation, counts=gate.counts;
    const evaluation=counts?`<p>실행 전 고정한 합성 문장 ${counts.plannedTotal||counts.total}개 중 ${counts.total}개 평가: 문장 형식 조건과 모델 점검을 합쳐 오류 문장을 허용한 경우 ${counts.falseAccepts}/${counts.shouldReject}, 허용 문장을 거부한 경우 ${counts.falseRejects}/${counts.shouldAccept}, 응답 형식 실패 ${counts.invalidResponses}개. ${gate.passed?'설정한 개발 점검 기준 충족.':'설정한 개발 점검 기준 미충족.'}</p><p>모델 단독의 오류 허용 ${counts.modelFalseAccepts??counts.falseAccepts}/${counts.shouldReject}, 적절한 문장 거부 ${counts.modelFalseRejects??counts.falseRejects}/${counts.shouldAccept}. 유보 표현이 없는 가설을 형식 조건으로 차단한 문장은 ${counts.styleBlocks||0}개입니다.</p><p>개발자가 만든 예제에 대한 자체 평가입니다. 실제 기업 정확도나 미사용 표본 성과가 아닙니다.</p>`:'<p>현재 모델·판독 방식과 일치하는 개발 평가가 없어 가설 노출을 보류합니다.</p>';
    return `<section class="panel local-review">${computedObservations(c)}<div class="panel-head local-note-heading"><div><span class="eyebrow">LOCAL RESEARCH NOTES</span><h2>두 설명을 구별할 다음 근거</h2><p class="panel-subtitle">${esc(r.model)} · ${esc(r.createdAt.slice(0,10))} · ${r.displayEligible?'모델의 검토용 가설':'검토 필요 · 채택 보류'}</p></div></div>${r.displayEligible?reviewBody:`<p>문장 점검 또는 개발 평가가 해결되지 않아 해석 채택을 보류합니다.</p><details class="withheld-notes"><summary>보류된 제안과 문장별 지적 확인</summary>${reviewBody}</details>`}<div class="review-caveats"><strong>가설을 구별하는 질문이며 아직 확인된 원인은 아닙니다.</strong><p>로컬 모델이 쓰고 같은 모델이 문장별로 점검했습니다. 독립 승인이나 금융 해석의 정확성 보증은 아닙니다. 확인 질문은 사전 등록 예측이나 자동 채점 조건으로 등록되지 않았습니다.</p></div><details class="evaluation-details"><summary>이 판독 방식은 어디까지 점검했는가</summary>${evaluation}</details><details class="technical"><summary>근거와 모델 버전</summary><code>근거 ${esc(r.evidenceHash)}</code><code>모델 ${esc(r.modelDigest)}</code><code>검토 기록 ${esc(r.recordHash)}</code><code>평가 ${esc(gate.recordHash||'미완료')}</code><p>${esc(r.scope)}</p></details></section>`;
  }
  function localReview(c,payload) {
    const r=payload.localReviews?.[c.id];
    if(!r)return `<section class="panel local-review">${computedObservations(c)}<h2>로컬 모델의 가설과 반론</h2><p>이 근거에 대한 로컬 모델 검토 전입니다. 수치 분석은 아래에서 확인할 수 있습니다.</p></section>`;
    if(r.status==='stale')return `<section class="panel local-review">${computedObservations(c)}<h2>로컬 모델 해석 보류</h2><p>${esc(r.reason)}</p></section>`;
    if(r.schemaVersion===2)return structuredReview(c,r);
    const evidence=Object.fromEntries(c.dossier.evidence.map(e=>[e.id,e]));
    const flagged=new Set(r.critic.unsupportedClaims);
    const claims=r.draft.claims.map((q,i)=>`<article class="hypothesis-card"><span class="mini-label">${flagged.has(i)?'근거 재검토 필요':'모델이 제안한 해석 · 자체 점검'}</span><h3>${esc(q.text)}</h3><dl><dt>다른 설명</dt><dd>${esc(q.alternative)}</dd><dt>다음 확인</dt><dd>${esc(q.check)}</dd></dl><div class="claim-evidence">${q.evidence.map(id=>{const e=evidence[id];return `<a href="${esc(e.sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(e.label)} ${amount(e.value,c)} ${unit(c)}<small>${e.start}–${e.end} · ${esc(id)}</small></a>`;}).join('')}</div></article>`).join('');
    return `<section class="panel local-review"><div class="panel-head"><div><span class="eyebrow">LOCAL MODEL REVIEW</span><h2>가설을 세우고, 다른 설명을 남기기</h2><p class="panel-subtitle">${esc(r.model)} · ${esc(r.createdAt.slice(0,10))} · ${r.status==='revision_required'?'수정 필요':'초안 검토 기록'}</p></div></div>${r.status==='revision_required'?`<p>반론 점검에서 문제를 발견해 자동 해석을 보류했습니다. 공시 수치는 위 분해표에서 확인할 수 있습니다.</p><details><summary>수정 전 모델 초안 확인</summary><p>${esc(r.draft.summary)}</p><div class="hypothesis-grid">${claims}</div></details>`:`<p>${esc(r.draft.summary)}</p><div class="hypothesis-grid">${claims}</div>`}<div class="review-caveats"><strong>같은 모델의 반론 점검</strong><ul>${r.critic.issues.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p>외부 AI API를 사용하지 않았습니다. 같은 모델의 두 번 읽기이며 독립 승인이나 금융 해석의 정확성 보증은 아닙니다.</p></div><details class="technical"><summary>근거와 모델 버전</summary><code>근거 ${esc(r.evidenceHash)}</code><code>모델 ${esc(r.modelDigest)}</code><code>검토 기록 ${esc(r.recordHash)}</code><p>${esc(r.scope)}</p></details></section>`;
  }
  function render(c,payload) {
    const d=c.dossier;if(!d)return '';
    const p=d.pricing;
    const peer=payload.snapshot.companies.find(x=>x.id!==c.id&&x.dossier);
    return `<div class="dossier-section"><div class="section-heading"><div><span class="eyebrow">CASH QUALITY / FILING DIAGNOSTICS</span><h2>순이익이 현금이 되는 과정</h2><p>공시 조정 항목을 연결하고, 아직 설명하지 못한 부분을 드러냅니다.</p></div></div><section class="panel"><div class="segmented"><button data-cash-period="current" aria-pressed="true">당기</button><button data-cash-period="previous" aria-pressed="false">전년 동기</button></div><div id="cash-bridge-body">${bridge(c)}</div><a href="${esc(c.financials.current.cfo.sourceUrl)}" target="_blank" rel="noopener noreferrer">해당 공시와 주석 확인 ↗</a><details class="cash-change-details"><summary>어느 조정이 전년보다 달라졌는가</summary><div class="table-wrap" tabindex="0"><table><thead><tr><th>현금 연결 항목</th><th>전년</th><th>당기</th><th>변화</th></tr></thead><tbody>${d.changes.map(x=>`<tr><td>${esc(x.label)}</td><td class="num">${amount(x.previous,c)}</td><td class="num">${amount(x.current,c)}</td><td class="num">${amount(x.change,c)}</td></tr>`).join('')}</tbody></table></div></details></section>
    ${localReview(c,payload)}
    ${p?`<section class="panel expectation-panel"><span class="eyebrow">PRICE-IMPLIED REQUIREMENTS</span><h2>현재 주식가치에는 어느 정도 현금이 필요한가</h2><p class="panel-subtitle">현재 가격을 설명할 조건의 역산 · 적정가 또는 성장 예측 아님</p><p>공시 보통주 ${number(p.shares.value,0)}주 × 관측 종가 ${number(p.close,c.currency==='KRW'?0:2)} ${c.currency} = <strong>${amount(p.marketCapProxy,c)} ${unit(c)}</strong></p><p class="chart-caption">주식수 ${p.shareDate} / 가격 ${p.priceDate} · 시점 간격 ${p.shareAgeDays}일. 공시 이후 희석·소각을 확인하지 않은 시가총액 근사치입니다.</p><div class="control-grid price-controls"><div><label for="equity-growth">향후 5년 현금 성장 가정 <output id="equity-growth-label"></output></label><input id="equity-growth" type="range" min="-10" max="30" step="1" value="10"></div><div><label for="equity-discount">주주 요구수익률 가정 <output id="equity-discount-label"></output></label><input id="equity-discount" type="range" min="6" max="18" step="1" value="11"></div><div><label for="equity-terminal">5년 이후 영구 성장 가정 <output id="equity-terminal-label"></output></label><input id="equity-terminal" type="range" min="0" max="4" step="1" value="2"></div></div><div id="equity-requirement" aria-live="polite"></div><div id="equity-sensitivity"></div><p class="chart-caption">역산 대상은 모든 비용·재투자·순차입·비지배지분 등을 반영해 보통주에 배분 가능한 연간 현금입니다. 공시 영업현금에서 설비 취득을 뺀 값을 그대로 할인하지 않습니다. 이 모형은 기존 현금·부채를 별도로 가감하는 기업가치 모형이 아닙니다.</p><details><summary>산식과 공시 재무상태</summary><p>주식가치 = 향후 5년 현금의 할인합 + 5년말 영구가치의 할인액. 기준연도 현금 C₀를 역산합니다. 가정한 모든 지급은 연말이며, 미래 추가 주식 발행은 반영하지 않았습니다.</p><ul>${d.balances.map(b=>`<li>${esc(b.label)}: ${amount(b.fact.value,c)} ${unit(c)} · ${b.fact.end}</li>`).join('')}</ul><p>부채·금융리스 포함 범위는 나라별로 다릅니다. 이 표를 그대로 더해 국가 간 EV를 비교하지 않습니다.</p></details></section>`:''}
    ${peer?`<section class="panel memory-pair"><h2>미국·한국 메모리 기업을 같은 질문으로 보기</h2><p class="panel-subtitle">동종 비교의 첫 쌍 · 두 회사만으로 업종 순위나 백분위를 만들지 않습니다.</p><div class="table-wrap" tabindex="0"><table><thead><tr><th>항목</th><th>${esc(c.name)}</th><th>${esc(peer.name)}</th></tr></thead><tbody><tr><td>누적 기간</td>${[c,peer].map(x=>`<td>${x.financials.start}<br>${x.financials.end} · ${x.financials.days}일</td>`).join('')}</tr><tr><td>영업현금 / 매출</td>${[c,peer].map(x=>`<td>${percent(x.metrics.cfoMargin)}</td>`).join('')}</tr><tr><td>유형자산 취득 / 매출</td>${[c,peer].map(x=>`<td>${percent(x.metrics.capexIntensity)}</td>`).join('')}</tr><tr><td>채권·재고 현금 효과 / 매출</td>${[c,peer].map(x=>`<td>${percent(x.dossier.current.parts.filter(z=>['receivables','inventory'].includes(z.id)).reduce((a,z)=>a+z.value,0)/x.financials.current.revenue.value)}</td>`).join('')}</tr><tr><td>미분해 잔액 / 영업현금 절댓값</td>${[c,peer].map(x=>`<td>${percent(x.dossier.current.residualShare)}</td>`).join('')}</tr></tbody></table></div><p>기간·제품 구성·회계 분류가 달라 우열 판정은 보류합니다. 조정 항목과 다음 공시에서의 반복 여부를 함께 확인합니다.</p><button class="arrow-link" data-company="${peer.id}">${esc(peer.name)}의 근거와 반론 보기 ↗</button></section>`:''}</div>`;
  }
  function bind(c) {
    if(!c.dossier)return;
    document.querySelectorAll('[data-cash-period]').forEach(b=>b.addEventListener('click',()=>{document.querySelector('#cash-bridge-body').innerHTML=bridge(c,b.dataset.cashPeriod);document.querySelectorAll('[data-cash-period]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));}));
    if(!c.dossier.pricing)return;
    const update=()=>{
      const g=Number(document.querySelector('#equity-growth').value)/100,k=Number(document.querySelector('#equity-discount').value)/100,t=Number(document.querySelector('#equity-terminal').value)/100;
      document.querySelector('#equity-growth-label').textContent=percent(g);document.querySelector('#equity-discount-label').textContent=percent(k);document.querySelector('#equity-terminal-label').textContent=percent(t);
      const r=pricing(c.dossier.pricing.marketCapProxy,g,k,t),annualRevenue=c.financials.current.revenue.value*365/c.financials.days;
      document.querySelector('#equity-sensitivity').innerHTML=sensitivity(c,t,g,k);
      document.querySelector('#equity-requirement').innerHTML=`<div class="requirement-grid"><div><small>필요한 기준연도 배분 가능 현금</small><strong>${amount(r.requiredBaseCash,c)} ${unit(c)} / 년</strong></div><div><small>단순 연환산 매출 대비</small><strong>${percent(r.requiredBaseCash/annualRevenue)}</strong></div><div><small>현재가치 중 영구가치 비중</small><strong>${percent(r.terminalShare)}</strong></div></div><p class="context-note">가정: 성장 ${percent(g)} · 주주 요구수익률 ${percent(k)} · 영구 성장 ${percent(t)} · 5년. 매출의 단순 연환산은 계절성·업황을 정상화한 전망이 아닙니다.</p>`;
    };
    document.querySelector('#equity-sensitivity').addEventListener('click',event=>{const cell=event.target.closest('[data-price-growth]');if(!cell)return;document.querySelector('#equity-growth').value=Number(cell.dataset.priceGrowth)*100;document.querySelector('#equity-discount').value=Number(cell.dataset.priceDiscount)*100;update();});
    for(const id of ['equity-growth','equity-discount','equity-terminal'])document.querySelector('#'+id).addEventListener('input',update);
    update();
  }
  window.EquityDossier={render,bind,pricing};
})();
