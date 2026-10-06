/* The model chooses a research design; its sentences and facts are not generated. */
(() => {
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function render(c,payload){
    if(payload.publication)return '';
    const r=payload.questionSelections?.[c.id];
    const heading='<span class="eyebrow">LOCAL MODEL / RESEARCH PRIORITIES</span><h2>이 기업에서 먼저 조사할 두 질문</h2>';
    if(!r||r.status!=='selected')return `<section class="panel question-selection">${heading}<p>${esc(r?.reason||r?.error||'현재 공시의 로컬 질문 선택을 실행하기 전입니다.')}</p></section>`;
    const cards=r.questions.map((q,i)=>{
      const facts=r.evidence.filter(f=>q.keys.some(k=>f.id.endsWith('.'+k)));
      const scale=c.currency==='KRW'?1e12:1e9,unit=c.currency==='KRW'?'조 원':'십억 USD';
      return `<article class="question-card"><span class="mini-label">조사 순서 ${i+1} · 모델이 선택한 연구 설계</span><h3>${esc(q.title)}</h3><div class="question-alternatives"><p><strong>검토할 설명 A</strong> ${esc(q.alternatives[0])}</p><p><strong>검토할 설명 B</strong> ${esc(q.alternatives[1])}</p></div><h4>추가로 확보할 근거</h4><p>${esc(q.evidenceNeeded)}</p><h4>어떤 관측이 판단을 바꾸는가</h4><p>${esc(q.discriminator)}</p><p class="chart-caption">${esc(q.limitation)}</p><details><summary>입력 공시의 관련 관측 · 원인 증명과는 별도</summary><ul>${facts.map(f=>`<li><a href="${esc(f.sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(f.label)} ${(f.value/scale).toLocaleString('ko-KR',{maximumFractionDigits:3})} ${unit} ↗</a> · ${f.start}–${f.end}</li>`).join('')}</ul></details></article>`;
    }).join('');
    return `<section class="panel question-selection">${heading}<p>로컬 모델이 공시 관측과 가격 조건을 읽고 정해진 연구 설계 중 두 가지를 골랐습니다. 아래 설명과 확인 방법은 명시된 설계 문구이며, 이 기업의 원인으로 확인된 사실은 아닙니다.</p><div class="question-grid">${cards}</div><p class="chart-caption">${esc(r.scope)} ${esc(r.model)} · ${r.createdAt.slice(0,10)}.</p><details class="technical"><summary>모델 선택과 원응답 버전</summary><code>${esc(r.recordHash)}</code><code>${esc(r.protocolVersion)} · ${esc(r.modelDigest)}</code><p>선택의 유효성·원응답 일치 검사는 투자 우선순위의 유효성 검증이 아닙니다.</p></details></section>`;
  }
  window.EquityQuestions={render};
})();
