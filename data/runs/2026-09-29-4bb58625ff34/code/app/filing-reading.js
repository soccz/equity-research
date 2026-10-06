(() => {
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function render(c,payload){
    if(payload.publication)return '';
    const r=payload.filingReadings?.[c.id];if(!r)return '';
    if(r.status!=='unreviewed_draft')return `<section class="panel filing-reading"><h2>공시 본문 로컬 판독</h2><p>${r.status==='stale'?'공시·조사 문단 변경으로 새 판독 필요':'이번 판독 실패 · 이전 출력으로 대체하지 않음'}</p><p>${esc(r.reason||r.error)}</p></section>`;
    const source=id=>r.input.passages.find(p=>p.id===id);
    const link=id=>{const p=source(id);return `<a href="${esc(p.sourceUrl)}" target="_blank" rel="noopener noreferrer">본문 #${p.ordinal} ↗</a>`;};
    const d=r.draft;
    return `<section class="panel filing-reading"><span class="eyebrow">LOCAL MODEL / FILING READING</span><h2>사업 설명을 읽은 로컬 초안</h2><p>${esc(r.input.focus)}</p><p class="reading-state">원문 직접 연결 · 해석 의미 미검토</p><p class="chart-caption">${esc(r.input.selectionScope)} ${esc(r.scope)}</p><details class="reading-draft"><summary>원문과 모델의 해석 대조하기</summary>${d.observations.map(o=>`<article class="reading-observation"><div><h3>회사가 공시한 원문</h3><blockquote>${esc(source(o.passageId).text)}</blockquote>${link(o.passageId)}<details><summary>기준 기간 확인</summary><small>공시 ${esc(r.input.filedAt)} · 보고 기간 ${esc(r.input.reportPeriod.join('–'))}</small></details></div><div><h3>모델이 읽은 의미 · 미검토</h3><p>${esc(o.reading)}</p></div></article>`).join('')}<h3>사업·가격 가정에 대한 잠정 해석</h3><p>${esc(d.implication.text)}</p><p>${d.implication.evidenceIds.map(link).join(' · ')}</p><h3>판단을 약화시킬 수 있는 다음 관측 질문</h3><p>${esc(d.question.text)}</p><p>${d.question.evidenceIds.map(link).join(' · ')}</p><button type="button" id="reading-to-notebook">이 초안과 원문을 내 연구로 가져오기</button><p class="chart-caption">반론·비교·실제 가격 가정은 직접 보완하고 새 연구 버전으로 저장합니다. 원 모델 출력은 별도로 남습니다.</p><small>${esc(r.model)} · ${esc(r.createdAt)} · 기록 ${esc(r.recordHash.slice(0,12))}</small></details></section>`;
  }
  function bind(c,payload){const b=document.querySelector('#reading-to-notebook');if(b)b.onclick=async()=>{
    const r=payload.filingReadings[c.id],d=r.draft;
    const ids=[...new Set([...d.observations.map(o=>o.passageId),...d.implication.evidenceIds,...d.question.evidenceIds])];
    await window.EquityNotebook.startFromSource(c,payload,ids,{thesis:'로컬 모델 미검토 초안 · 기록 '+r.recordHash+'\n'+d.observations.map(o=>o.reading).join('\n'),assumptions:d.implication.text,changes:d.question.text});
    document.querySelector('.notebook')?.scrollIntoView({behavior:'smooth',block:'start'});
  };}
  window.EquityFilingReading={render,bind};
})();
