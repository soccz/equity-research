(() => {
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function render(c,payload){
    if(payload.publication)return '';
    const rows=(payload.snapshot.peerStudies||[]).filter(r=>r.sides.some(s=>s.company===c.id));
    return rows.map(r=>renderStudy(r)).join('');
  }
  function renderStudy(r,link=true){return r.status==='stale'?`<section class="panel source-pair"><h2>${esc(r.title)}</h2><p>한쪽 공시가 달라 비교 근거를 다시 선정해야 합니다. 이전 판단을 재사용하지 않습니다.</p></section>`:`<section class="panel source-pair"><span class="eyebrow">PAIRED BUSINESS RESEARCH</span><h2>${esc(r.title)}</h2><p>${esc(r.shared)}</p><div class="source-pair-grid">${r.sides.map(s=>`<article><h3><a href="#company/${esc(s.company)}" data-company="${esc(s.company)}">${esc(s.name)} ↗</a> <small>${esc(s.market)}</small></h3><p>${esc(s.reading)}</p><p class="chart-caption">공시 ${esc(s.filedAt)} · 보고 기간 ${esc(s.sourcePeriod.join('–'))}</p><p>${s.sources.map(p=>`<a href="${esc(p.sourceUrl)}" target="_blank" rel="noopener noreferrer">근거 #${p.ordinal} ↗</a>`).join(' · ')}</p><details><summary>비교에 사용한 실제 문단</summary>${s.sources.map(p=>`<blockquote>${esc(p.text)}</blockquote>`).join('')}</details></article>`).join('')}</div><div class="source-pair-judgment"><h3>관측 차이를 해석하는 방법</h3><p>${esc(r.tradeoff)}</p>${r.countercase?`<h3>가장 강한 반론</h3><p>${esc(r.countercase)}</p>`:""}<h3>선호를 바꾸기 전에 구별할 근거</h3><p>${esc(r.discriminator)}</p><h3>가격 시나리오에 반영할 차이</h3><p>${esc(r.priceImplication)}</p></div>${link?`<p><button type="button" data-nav="compare/${esc(r.id)}">두 기업의 가격 가정·판단 비교 ↗</button></p>`:""}<p class="chart-caption">${esc(r.authorship)} · ${esc(r.preference)}. ${esc(r.scope)}</p></section>`;}
  window.EquityPeerStudies={render,renderStudy};
})();
