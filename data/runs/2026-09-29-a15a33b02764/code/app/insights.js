(() => {
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function render(c){
    const r=c.businessInsight;if(!r)return '';
    if(r.status==='stale')return `<section class="panel business-insight"><h2>사업 해석 근거 갱신 필요</h2><p>${esc(r.reason)}</p></section>`;
    return `<section class="panel business-insight"><span class="eyebrow">BUSINESS EVIDENCE / RESEARCH JUDGMENT</span><h2>${esc(r.title)}</h2><p class="panel-subtitle">공시 ${esc(r.filedAt)} · ${r.period.join('–')} · ${esc(r.authorship)}</p><div class="insight-reading"><h3>회사가 공시한 설명</h3><p>${esc(r.observation)}</p><p class="insight-sources">${r.sources.map((s,i)=>`<a href="${esc(s.sourceUrl)}" target="_blank" rel="noopener noreferrer">근거 공시 ${i+1} ↗</a> <small>본문 #${s.ordinal}</small>`).join(' · ')}</p></div><div class="insight-columns"><article><h3>잠정 해석</h3><p>${esc(r.interpretation)}</p></article><article><h3>반론</h3><p>${esc(r.countercase)}</p></article></div><h3>가격 가정과 비교에 주는 의미</h3><p>${esc(r.priceImplication)}</p><p>${esc(r.comparison)}</p><div class="insight-next"><h3>다음 공시에서 판단을 바꿀 관측</h3><p>${esc(r.changeCondition)}</p></div><p class="chart-caption">${esc(r.scope)}</p><button type="button" id="insight-to-notebook">이 근거로 내 연구 초안 시작</button></section>`;
  }
  function bind(c,payload){const button=document.querySelector('#insight-to-notebook');if(button)button.onclick=async()=>{await window.EquityNotebook.startFromInsight(c,payload);document.querySelector('.notebook')?.scrollIntoView({behavior:'smooth',block:'start'});};}
  window.EquityInsights={render,bind};
})();
