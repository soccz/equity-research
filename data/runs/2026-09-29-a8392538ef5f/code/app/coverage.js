/* Private company-wide research notes. Values come from the filing engine. */
(() => {
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels={hypothesis:'가능한 설명',alternative:'경쟁하는 설명',distinguish:'다음 공시에서 구별할 관측',missing:'아직 필요한 근거'};
  const states={supported:'입력과 일치한다고 자체 판정',conditional:'조건부 서술로 자체 판정',unsupported:'근거 없는 단정 지적',contradicted:'입력과 충돌 지적',unresolved:'판독 미해결'};
  function render(c,payload){
    if(payload.publication)return '';
    const r=payload.coverageReviews?.[c.id];
    const heading='<span class="eyebrow">LOCAL COMPANY RESEARCH</span><h2>공시에서 출발한 기업 연구 질문</h2>';
    if(!r||r.status==='stale'||r.status==='failed')return `<section class="panel coverage-review">${heading}<p>${esc(r?.reason||r?.error||'이 공시의 기업 전체 가설 판독은 아직 실행 전입니다.')}</p><p class="chart-caption">외부 AI 없이 저장된 공시를 읽는 로컬 판독입니다. 아래 계산과 별도로 검토합니다.</p></section>`;
    const assessments=Object.fromEntries(r.scrutiny.assessments.map(a=>[a.id,a]));
    const cards=Object.entries(labels).map(([id,label])=>{
      const a=assessments[id],accepted=a.classification===(id==='missing'?'supported':'conditional')&&!r.styleFindings?.[id];
      return `<article class="hypothesis-card ${accepted?'':'needs-review'}" data-coverage-role="${id}"><span class="mini-label">AI 제안 · ${label}</span><h3>${esc(r.notes[id])}</h3><details class="sentence-review"><summary>${esc(states[a.classification])}</summary><p>${esc(a.reason)}</p><blockquote>${esc(a.quote)}</blockquote>${r.styleFindings?.[id]?`<p>${esc(r.styleFindings[id])}</p>`:''}</details></article>`;
    }).join('');
    const scale=c.currency==='KRW'?1e12:1e9,unit=c.currency==='KRW'?'조 원':'십억 USD';
    const value=v=>v==null?'비교 보류':(v/scale).toLocaleString('ko-KR',{maximumFractionDigits:3});
    const rows=r.observations.map(o=>`<tr><td>${esc(o.label)}</td><td class="num">${value(o.previous)}</td><td class="num">${value(o.current)}</td><td class="num">${value(o.change)}</td><td>${esc(o.direction)}</td></tr>`).join('');
    const evidence=['previous','current'].flatMap(period=>['revenue','cfo','capex'].map(key=>{
      const f=c.financials[period][key];return f?`<a href="${esc(f.sourceUrl)}" target="_blank" rel="noopener noreferrer">${period==='previous'?'전년':'당기'} ${esc({revenue:'매출',cfo:'영업현금',capex:c.investmentScope}[key])}<small>${f.start}–${f.end} · ${esc(f.accession)}</small></a>`:'';
    })).join('');
    const body=`<div class="hypothesis-grid role-grid">${cards}</div><div class="claim-evidence"><strong>입력 관측의 원문 · 인과 증명은 별도</strong>${evidence}</div>${c.business?.status==='ready'?'<p>사업부·리스·연결 차이 자료도 함께 읽었습니다. 해당 원문과 대사표는 위 사업부 분석에서 확인할 수 있습니다.</p>':''}`;
    const gate=r.currentEvaluation||r.evaluation,counts=gate.counts;
    const evaluation=counts?`합성 개발 문장 ${counts.total}/${counts.plannedTotal}개 · 오류 허용 ${counts.falseAccepts}/${counts.shouldReject} · 적절한 문장 거부 ${counts.falseRejects}/${counts.shouldAccept} · 형식 실패 ${counts.invalidResponses}개. 모델 단독 오류 허용 ${counts.modelFalseAccepts}/${counts.shouldReject}. ${gate.passed?'개발 기준 충족':'개발 기준 미충족'}.`:'현재 모델·설정·프로토콜에 일치하는 평가가 없습니다.';
    return `<section class="panel coverage-review">${heading}<p class="panel-subtitle">${esc(r.model)} · ${esc(r.createdAt.slice(0,10))} · ${r.displayEligible?'검토용 가설':'검토 필요 · 채택 보류'}</p><div class="table-wrap" tabindex="0"><table><caption>코드가 계산한 입력 관측 · ${unit}</caption><thead><tr><th>항목</th><th>전년</th><th>당기</th><th>차이</th><th>관측</th></tr></thead><tbody>${rows}</tbody></table></div>${r.displayEligible?body:`<details class="withheld-notes"><summary>보류된 기업 가설과 문장별 지적 보기</summary>${body}</details>`}<p class="review-caveats">같은 로컬 모델의 작성·비판·수정 기록입니다. 독립 금융 해석 승인은 없으며, 제안한 관측은 사전 등록 예측이나 자동 채점 조건과 구분합니다.</p><details class="evaluation-details"><summary>개발 평가와 사용한 버전</summary><p>${evaluation}</p><p>작성자가 만든 합성 예문 평가입니다. 실제 기업 정확도·투자 성과·미사용 표본 평가가 아닙니다.</p><code>근거 ${esc(r.evidenceHash)}</code><code>판독 ${esc(r.promptVersion)}</code><code>모델 ${esc(r.modelDigest)}</code><code>기록 ${esc(r.recordHash)}</code><code>평가 ${esc(gate.recordHash||'미완료')}</code></details></section>`;
  }
  window.EquityCoverage={render};
})();
