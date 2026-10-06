(() => {
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=x=>Number(x).toLocaleString('en-US',{maximumFractionDigits:2});
  function driverChart(d){
    let position=d.rows[0].value;
    const points=d.rows.map((r,i)=>{const start=i===0||r.kind==='end'?0:position,end=i===0||r.kind==='end'?r.value:position+r.value;position=end;return {...r,start,end};});
    const lo=Math.min(0,...points.flatMap(p=>[p.start,p.end])),hi=Math.max(0,...points.flatMap(p=>[p.start,p.end]));
    const y=v=>45+(hi-v)/(hi-lo||1)*200,step=700/points.length,bar=Math.min(78,step*.6);
    return `<svg class="business-driver-chart" viewBox="0 0 760 320" role="img" aria-label="${esc(d.title)}. ${esc(d.rows.map(r=>r.label+' '+num(r.value)).join(', '))}"><line x1="30" x2="730" y1="${y(0)}" y2="${y(0)}" stroke="#9eaaa6"/>${points.map((p,i)=>{const x=30+step*(i+.5),color=p.kind==='start'||p.kind==='end'?'#245951':p.basis.includes('잔차')?'#88918b':p.value>=0?'#418c7a':'#b57350';return `<g data-value="${p.value}"><rect x="${x-bar/2}" y="${Math.min(y(p.start),y(p.end))}" width="${bar}" height="${Math.max(1,Math.abs(y(p.end)-y(p.start)))}" fill="${color}"/><text x="${x}" y="${Math.min(y(p.start),y(p.end))-9}" text-anchor="middle">${p.kind==='delta'&&p.value>0?'+':''}${num(p.value)}</text><text x="${x}" y="278" text-anchor="middle">${esc(p.label.split(' ').slice(0,-1).join(' '))}</text><text x="${x}" y="301" text-anchor="middle">${esc(p.label.split(' ').at(-1))}</text></g>`;}).join('')}</svg>`;
  }
  function drivers(r){
    const d=r.drivers;if(!d)return '';
    return `<section class="panel business-drivers"><span class="eyebrow">REPORTED CHANGE / BUSINESS DRIVERS</span><h2>사업 변화의 금액을 원문과 연결하기</h2><p class="chart-caption">단위: ${esc(d.unit)} · ${esc(d.scope)}</p>${d.charts.map(c=>`<article class="business-driver"><h3>${esc(c.title)}</h3><p class="chart-caption">${esc(c.period)} · ${esc(d.unit)}</p>${driverChart(c)}<p>${esc(c.explanation)}</p><p class="chart-caption">${c.sources.map(p=>`<a href="${esc(p.sourceUrl)}" target="_blank" rel="noopener noreferrer">본문 #${p.ordinal} ↗</a>`).join(' · ')} · <a href="${esc(d.sourceTable.sourceUrl)}" target="_blank" rel="noopener noreferrer">보고 표 ↗</a></p><details><summary>금액과 출처 설명</summary><ul>${c.rows.map(p=>`<li>${esc(p.label)}: ${num(p.value)} — ${esc(p.basis)}</li>`).join('')}</ul></details></article>`).join('')}<details class="driver-source-table"><summary>대사에 사용한 원문 표 전체</summary><p>${esc(d.sourceTable.text)}</p></details></section>`;
  }
  function render(c){
    const r=c.businessInsight;if(!r)return '';
    if(r.status==='stale')return `<section class="panel business-insight"><h2>사업 해석 근거 갱신 필요</h2><p>${esc(r.reason)}</p></section>`;
    return `<section class="panel business-insight"><span class="eyebrow">BUSINESS EVIDENCE / RESEARCH JUDGMENT</span><h2>${esc(r.title)}</h2><p class="panel-subtitle">공시 ${esc(r.filedAt)} · ${r.period.join('–')} · ${esc(r.authorship)}</p><div class="insight-reading"><h3>회사가 공시한 설명</h3><p>${esc(r.observation)}</p><p class="insight-sources">${r.sources.map((s,i)=>`<a href="${esc(s.sourceUrl)}" target="_blank" rel="noopener noreferrer">근거 공시 ${i+1} ↗</a> <small>본문 #${s.ordinal}</small>`).join(' · ')}</p></div><div class="insight-columns"><article><h3>잠정 해석</h3><p>${esc(r.interpretation)}</p></article><article><h3>반론</h3><p>${esc(r.countercase)}</p></article></div><h3>가격 가정과 비교에 주는 의미</h3><p>${esc(r.priceImplication)}</p><p>${esc(r.comparison)}</p><div class="insight-next"><h3>다음 공시에서 판단을 바꿀 관측</h3><p>${esc(r.changeCondition)}</p></div><p class="chart-caption">${esc(r.scope)}</p><button type="button" id="insight-to-notebook">이 근거로 내 연구 초안 시작</button></section>${drivers(r)}`;
  }
  function bind(c,payload){const button=document.querySelector('#insight-to-notebook');if(button)button.onclick=async()=>{await window.EquityNotebook.startFromInsight(c,payload);document.querySelector('.notebook')?.scrollIntoView({behavior:'smooth',block:'start'});};}
  window.EquityInsights={render,bind};
})();
