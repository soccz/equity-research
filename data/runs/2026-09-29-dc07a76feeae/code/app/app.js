(() => {
  'use strict';
  const payload = window.EQUITY_SNAPSHOT;
  const data = payload.snapshot;
  const main = document.querySelector('main'), dialog = document.querySelector('dialog');
  const state = { view: 'universe', company: 'MU', market: 'ALL', sector: 'ALL', query: '', candidates: false, sort: 'cashMarginChange', lab: 'US', cfoShock: 0, capexShock: 0 };
  const titles = { universe: '종목 탐색', company: '기업과 가설', lab: '실험과 기준선', tracking: '판단 이력', sources: '자료와 검증' };
  let trigger;
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct = (v, digits=1) => v === null || v === undefined ? '미확인' : `${(v*100).toFixed(digits)}%`;
  const pp = v => v === null || v === undefined ? '미확인' : `${v>0?'+':''}${(v*100).toFixed(1)}%p`;
  const num = (v,d=1) => v===null || v===undefined ? '미확인' : Number(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
  const good = () => data.companies.filter(c => c.status==='ready');
  const company = () => data.companies.find(c => c.id===state.company);
  const unit = c => c.currency==='KRW' ? '조 원' : '십억 달러';
  const amount = (v,c) => num(v/(c.currency==='KRW'?1e12:1e9),2);
  const source = (id,type='financial') => {
    const c=data.companies.find(c=>c.id===id);
    const urls=type==='price'?[c.sources.find(s=>s.provider==='Yahoo Finance').url]:[...new Set([...Object.values(c.financials.current),...Object.values(c.financials.previous)].filter(Boolean).map(f=>f.sourceUrl))];
    return `<button class="source-button" data-evidence="${id}" data-kind="${type}">계산과 원문 ↗</button><span class="print-source">${urls.map((url,i)=>`<a href="${esc(url)}">${type==='price'?'Yahoo 가격 원문':'공시 원문 '+(i+1)} ↗</a>`).join('<br>')}</span>`;
  };
  const heading = (eyebrow,title,description,meta='') => `<div class="heading-row"><div><span class="eyebrow">${eyebrow}</span><h1>${title}</h1><p class="lede">${description}</p><div class="metadata">${meta}</div></div><div class="edition">RESEARCH / 02<br>${data.asOf}</div></div>`;
  const stat = (label,value,note) => `<div><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`;
  const panel = (title,subtitle,body,extra='') => `<section class="panel"><div class="panel-head"><div><h2>${title}</h2><p class="panel-subtitle">${subtitle}</p></div>${extra}</div>${body}</section>`;
  const svg = (w,h,label,body) => `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label)}">${body}</svg>`;
  const byId = id => data.companies.find(c=>c.id===id)?.name ?? id;
  const pillar = text => `<span class="pill ${text==='심층 조사 후보'?'positive':'neutral'}">${esc(text)}</span>`;
  const selectedPeriod = c => `${c.financials.start}–${c.financials.end}`;
  const context = {
    MU: ['메모리 성장과 설비 투자를 함께 읽기','현재 매출·현금 증가가 가격 상승의 순환 효과인지, 고객 수요의 지속성인지 구별해야 합니다.','고객 선급금·보조금·운전자본 변화가 영업현금과 회사 발표 조정 FCF에 미치는 영향을 원문 주석에서 분리합니다.'],
    NVDA: ['설비 지출 밖에 있는 공급 의무까지 보기','팹리스 기업은 자체 설비 지출이 작아도 구매 약정과 공급망 선급금에 자본이 묶일 수 있습니다.','유형·무형자산 취득의 통합 항목을 사용합니다. 제조업의 유형자산 지출과 직접적인 효율 순위로 비교하지 않습니다.'],
    GOOGL: ['이익 성장과 인프라 투자 이후 현금의 차이','순이익과 영업현금의 차이를 검색·클라우드 경쟁력만으로 설명할 수 없습니다.','투자자산 평가손익, AI 인프라의 감가상각·회수기간, 리스와 설비 지급 시차를 다음 조사에서 분리합니다.'],
    AAPL: ['제품·서비스 이익이 주주 현금으로 이어지는 경로','회계연도 누적 현금 전환이 계절적 운전자본 회수에 의존하는지 확인해야 합니다.','공급자 지급 시점과 자사주 매입은 다른 층의 현금입니다. 연결 영업현금을 곧바로 주주 환원 여력으로 단정하지 않습니다.'],
    '000660': ['메모리의 이익과 현금이 같은 속도로 늘었는가','매출보다 큰 순이익이 관측되면 본업 이익 외 항목을 먼저 구분해야 합니다.','비현금 평가손익·세금·운전자본을 원문 주석으로 연결하기 전에는 순이익 증가율을 정상 수익력으로 쓰지 않습니다.'],
    '005930': ['연결 현금이 어느 사업에서 만들어졌는가','연결 수치에는 메모리 외 사업이 함께 들어갑니다. 메모리 전문 기업과 같은 사업체로 취급할 수 없습니다.','DS·DX의 자본 배분과 사업부 실적을 분리해야 연결 현금 개선을 기업별 경쟁력으로 해석할 수 있습니다.'],
    '035420': ['플랫폼 성장에 필요한 재투자의 크기','매출 증가와 인프라·서비스 투자 이후 남는 현금은 다른 방향으로 움직일 수 있습니다.','서버와 기타 투자 구성을 확인하고 인수·무형자산 지출을 더해 재투자 부담을 재평가합니다.'],
    '066570': ['현금 회수가 사업의 개선을 반영하는가','가전·전장 및 연결 자회사의 현금은 사업 구조와 고객 결제 조건이 다릅니다.','운전자본 회수의 계절성과 사업별 설비투자·리스 의무를 분리해 다음 공시와 비교합니다.']
  };

  function scatter(rows) {
    if(!rows.length)return '<p class="empty-search">조건에 맞는 기업이 없습니다. 검색어나 사업 분류를 바꿔보세요.</p>';
    const w=580,h=295,xMax=Math.max(.4,...rows.map(c=>c.metrics.capexIntensity))*1.15,yMin=Math.min(0,...rows.map(c=>c.metrics.cashMargin)),yMax=Math.max(.6,...rows.map(c=>c.metrics.cashMargin))*1.15,x=v=>55+v/xMax*465,y=v=>245-(v-yMin)/(yMax-yMin)*210;
    let b='';
    for(let i=0;i<5;i++){const t=xMax*i/4;b+=`<line class="grid" x1="${x(t)}" x2="${x(t)}" y1="35" y2="245"/><text x="${x(t)}" y="264" text-anchor="middle">${num(t*100,0)}</text>`;}
    for(let i=0;i<4;i++){const t=yMin+(yMax-yMin)*i/3;b+=`<line class="grid" x1="55" x2="520" y1="${y(t)}" y2="${y(t)}"/><text x="42" y="${y(t)+4}" text-anchor="end">${num(t*100,0)}</text>`;}
    b+='<text x="55" y="20">현금잉여 / 매출 (%)</text><text x="285" y="291" text-anchor="middle">공시 투자자산 취득 / 매출 (%) →</text>';
    for(const c of rows) b+=`<a href="#company/${c.id}" aria-label="${esc(c.name)} 분석"><title>${esc(c.name)} · ${c.id} · 투자 ${pct(c.metrics.capexIntensity)} · 현금 ${pct(c.metrics.cashMargin)}</title><circle cx="${x(c.metrics.capexIntensity)}" cy="${y(c.metrics.cashMargin)}" r="5.5" fill="${c.market==='KR'?'#245d53':'#af5b35'}"/>${rows.length<=10?`<text x="${x(c.metrics.capexIntensity)+9}" y="${y(c.metrics.cashMargin)-6}" style="font-size:10px">${c.id}</text>`:''}</a>`;
    return svg(w,h,'기업별 투자 지출 비율과 해당 공시기간의 현금잉여 마진',b);
  }

  function pairedBars(previous,current,lo,hi) {
    const x=v=>(v-lo)/(hi-lo||1)*100,zero=x(0);
    return `<div class="bars signed-bars" style="--zero:${zero}%">${[previous,current].map((v,i)=>v==null?'<div class="bar-track missing-bar">미확인</div>':`<div class="bar-track"><i class="${i?'current':'previous'} ${v<0?'negative':''}" style="left:${Math.min(zero,x(v))}%;width:${Math.abs(x(v)-zero)}%"></i></div>`).join('')}</div>`;
  }

  function renderUniverse() {
    const rows=good().filter(c=>(state.market==='ALL'||c.market===state.market)&&(state.sector==='ALL'||c.sector===state.sector)&&(!state.query||[c.id,c.name,c.symbol].join(' ').toLowerCase().includes(state.query.toLowerCase()))&&(!state.candidates||c.assessment.priority==='심층 조사 후보')).sort((a,b)=>(b.metrics[state.sort]??b.priceSummary[state.sort]??-Infinity)-(a.metrics[state.sort]??a.priceSummary[state.sort]??-Infinity));
    main.innerHTML=heading('CROSS-MARKET OBSERVATORY / 01','성장의 현금 대가는 얼마인가','실제 공시와 가격으로 기업의 현재 조건을 살펴보고, 다음 조사와 검증으로 연결합니다.',`<span>기준 ${data.asOf}</span><span>미국 ${data.companies.filter(c=>c.market==='US').length} · 한국 ${data.companies.filter(c=>c.market==='KR').length}</span><span>연결 · 현지 통화</span>`)+
      `<div class="metric-grid">${stat('자료 연결',`${good().length} / ${data.companies.length}`,'누락은 후보에서 제외')}${stat('심층 조사 후보',good().filter(c=>c.assessment.priority==='심층 조사 후보').length,'공개된 재무 조건 3개 충족')}${stat('사업 분류',new Set(good().map(c=>c.sector||c.group)).size,'제품·회계 범위 차이 별도 표시')}${stat('판단 조건',payload.ledger.length,'사전 방향 예측과 별도 기록')}</div>
      <div class="workbench-intro"><article class="thesis-card"><span class="eyebrow">CURRENT RESEARCH QUESTION</span><h2>이익이 늘어난 기업에서<br>투자 이후 현금도 늘었는가</h2><p>매출 성장, 투자자산 취득 이후 현금, 같은 기간의 전년 대비 마진을 함께 확인합니다. 가격 위험과 후속 관측은 별도의 증거로 검토합니다.</p><span class="mini-label">현재 조건 → 기업별 반론 → 연구 실험</span><div class="card-bottom"><span>현재 재무를 과거에 소급하지 않습니다.</span><button data-nav="lab">실험 보기 ↗</button></div></article>${panel('성장에 들어간 현금과 남은 현금','기업별 최근 누적 공시 · 단위: 매출 대비 %',scatter(rows)+`<p class="chart-caption">기업별 회계기간·사업 구성·투자지출 정의가 다릅니다. 시장과 사업 분류를 좁혀 비교하세요. 점을 선택하면 기업 분석으로 이동합니다. 미국은 갈색, 한국은 녹색이며 축은 상대 순위나 성공 확률이 아닙니다.</p>`)}</div>
      <div class="section-heading"><div><h2>조사할 기업과 아직 필요한 증거</h2><p>기업을 선택하면 수치·원문·반론·변경 조건이 연결됩니다.</p></div><div class="table-controls"><div class="segmented">${['ALL','US','KR'].map(m=>`<button data-market="${m}" aria-pressed="${state.market===m}">${m==='ALL'?'전체':m==='US'?'미국':'한국'}</button>`).join('')}</div><label>기업명·종목코드 <input id="company-search" type="search" value="${esc(state.query)}" placeholder="기업 또는 코드" autocomplete="off"></label><label>사업 분류 <select id="sector-filter"><option value="ALL">전체 분류</option>${[...new Set(good().map(c=>c.sector||c.group))].sort().map(x=>`<option value="${esc(x)}" ${state.sector===x?'selected':''}>${esc(x)}</option>`).join('')}</select></label><label><input id="candidate-only" type="checkbox" ${state.candidates?'checked':''}> 조사 후보만</label><select id="sort" class="company-select" aria-label="정렬 지표"><option value="cashMarginChange" ${state.sort==='cashMarginChange'?'selected':''}>현금 마진 변화순</option><option value="revenueGrowth" ${state.sort==='revenueGrowth'?'selected':''}>매출 증가순</option><option value="momentum63" ${state.sort==='momentum63'?'selected':''}>63일 가격 변화순</option></select></div></div>
      <div class="table-wrap" tabindex="0" aria-label="실제 종목 비교표, 작은 화면에서는 가로 스크롤"><table class="live-table"><thead><tr><th>기업 · 사업</th><th>관측 기간</th><th>매출 증가율</th><th>현금 마진 변화</th><th>63일 가격 변화</th><th>조사 판단</th><th>가격 가정에 따른 연구 판단</th></tr></thead><tbody>${rows.map(c=>`<tr data-company-row="${c.id}"><td><button class="company-button" data-company="${c.id}">${esc(c.name)}<small>${c.market} · ${c.id} · ${c.group}</small></button></td><td>${c.financials.end}<small>${c.financials.days}일 누적 · 전년 동기 비교</small></td><td class="num">${pct(c.metrics.revenueGrowth)}</td><td class="num">${pp(c.metrics.cashMarginChange)}</td><td class="num">${pct(c.priceSummary.momentum63)}</td><td>${pillar(c.assessment.priority)}</td><td>${esc(c.researchCase?.pricing.state||c.assessment.investmentView)}<small>${c.researchCase?'현금·성장·할인 가정 확인':'정상 현금·기업가치 검토 전'}</small></td></tr>`).join('')}</tbody></table></div><p class="row-count" aria-live="polite">${rows.length}개 표시 · 고정 개발 대상군이며 시장 전체의 추천 순위가 아닙니다.</p>
      <div class="bottom-note"><div><strong>조사 후보의 조건</strong><p>전년 동기 매출 증가, 영업현금−공시 투자자산 취득 > 0, 해당 현금잉여의 매출 대비 비율 개선. 어느 조건이 빠졌는지 기업 화면에서 확인합니다.</p></div><div><strong>연구가 판단에 주는 정보</strong><p>기준선보다 나아졌는지, 위험 조정을 제거하면 무엇이 달라지는지, 완전예지라도 개선 여지가 있는지 실험합니다. 가격 실험을 재무 선별의 성과로 사용하지 않습니다.</p></div></div>`;
  }

  function lineChart(series, width=690, height=240, label='가격 변화') {
    const vals=series.flatMap(s=>s.values), lo=Math.min(...vals)*.95, hi=Math.max(...vals)*1.05, maxN=Math.max(...series.map(s=>s.values.length));
    const x=i=>46+i/(maxN-1)*600,y=v=>200-(v-lo)/(hi-lo||1)*170;
    let b='';
    for(let i=0;i<4;i++){const v=lo+(hi-lo)*i/3;b+=`<line class="grid" x1="46" x2="648" y1="${y(v)}" y2="${y(v)}"/><text x="38" y="${y(v)+4}" text-anchor="end">${num(v,0)}</text>`;}
    for(const s of series)b+=`<path d="${s.values.map((v,i)=>`${i?'L':'M'}${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(' ')}" fill="none" stroke="${s.color}" stroke-width="2" ${s.dashed?'stroke-dasharray="5 4"':''}/>`;
    return svg(width,height,label,b);
  }

  function renderCompany() {
    const c=company();
    if(!c||c.status!=='ready'){main.innerHTML=heading('DATA STATUS','자료 미확인','이 기업의 원문·가격 연결을 완료하지 못했습니다.');return;}
    const f=c.financials,m=c.metrics,p=c.priceSummary,current=f.current,previous=f.previous;
    const notes=context[c.id]||[c.analysis?.title||'사업과 현금의 연결',c.analysis?.questions?.[0]||'사업부와 현금의 연결을 확인합니다.',c.analysis?.questions?.[1]||'제품 구성과 재투자 범위를 확인합니다.'], barValues=['revenue','cfo','capex'].flatMap(k=>[current[k]?.value??0,previous[k]?.value??0]),barLo=Math.min(0,...barValues),barHi=Math.max(0,...barValues);
    const chart=c.prices.slice(-253), base=chart[0].adjustedClose;
    main.innerHTML=heading('COMPANY & HYPOTHESIS / 02',esc(c.name),notes[0],`<span>${c.id} · ${c.market}</span><span>${selectedPeriod(c)}</span><span>공시 ${f.filedAt}</span><span>${f.standard}</span>`)+
      `<div class="company-links"><label for="company-picker">분석 기업</label><select id="company-picker">${good().map(row=>`<option value="${row.id}" ${row.id===c.id?'selected':''}>${esc(row.name)} · ${row.id} · ${row.market}</option>`).join('')}</select><button data-nav="universe">종목 탐색으로 ↗</button></div>
      <article class="opinion-banner actual-opinion"><div><span class="label">현재 재무 조건</span><div class="opinion">${c.assessment.priority}</div><span class="label">가격 연구: ${esc(c.researchCase?.pricing.state||c.assessment.investmentView)}</span></div><div><h2>${c.assessment.businessView}</h2><p>${notes[1]}</p><p class="source-period">${esc(c.caveat)} · ${c.dossier?'현금·채권 주석 분석 연결':c.business?.status==='ready'?'사업부·현금·재무구조 원문 연결':'공통 공시 계산·사업 조사 질문 연결'} · 가격 가정과 비교 근거는 아래 연구 의견에서 확인</p></div></article>
      <div class="metric-grid">${stat('매출 전년 동기',pct(m.revenueGrowth),`${f.days}일 누적`)}${stat('투자 이후 현금 / 매출',pct(m.cashMargin),`전년 대비 ${pp(m.cashMarginChange)}`)}${stat('영업현금 / 순이익',num(m.cashConversion,2)+'배','비현금·운전자본 원인은 별도 확인')}${stat('관측 종가',num(p.close,c.currency==='KRW'?0:2),`${c.currency} · ${p.lastDate}`)}</div>
      <div class="cash-comparison">${panel('실적과 현금의 같은 기간 비교',`${unit(c)} · 옅은 색 전년 / 진한 색 당기`,['revenue','cfo','capex'].map((k,i)=>`<div class="paired-row"><span>${['매출','영업현금',c.investmentScope][i]}</span>${pairedBars(previous[k]?.value,current[k].value,barLo,barHi)}<span class="amount"><small>${previous[k]?amount(previous[k].value,c):'미확인'}</small>${amount(current[k].value,c)}</span></div>`).join('')+`<div class="cash-equation"><div><small>영업현금</small>${amount(current.cfo.value,c)}</div><span>−</span><div><small>${c.investmentScope}</small>${amount(current.capex.value,c)}</div><span>=</span><div><small>현금잉여</small>${amount(m.cashAfterInvestment,c)}</div></div><p class="chart-caption">이 계산은 FCFF나 회사의 조정 FCF가 아닙니다. 인수·리스·회계 분류 차이를 포함한 투자 가능 현금의 검토는 추가로 필요합니다.</p>`,source(c.id))}
      ${panel('원문 숫자가 통과한 조건','가중 점수 없이 조건별로 읽기',`<ul class="criteria-list">${c.assessment.gates.map(g=>`<li>${g.label}<b>${g.passed==null?'자료 미확인':g.passed?'충족':'미충족'}</b></li>`).join('')}</ul><h3>해석을 바꿀 수 있는 것</h3><p class="company-note">${notes[2]}</p><ul class="risk-list">${[...c.assessment.risks,...c.assessment.issues].map(x=>`<li>${esc(x)}</li>`).join('')||'<li>추가 위험 항목은 사업·주석 조사에서 확인합니다.</li>'}</ul>`)}</div>
      <section class="panel assumption-panel"><div class="panel-head"><div><h2>현금 회수와 투자 지출이 달라지면</h2><p class="panel-subtitle">동일 기간·매출 고정 시나리오 · 기업가치 예측 아님</p></div></div><div class="control-grid"><div><label for="cfo-shock">영업현금 변화 <output id="cfo-shock-value">0%</output></label><input id="cfo-shock" type="range" min="-50" max="50" step="5" value="${state.cfoShock}"></div><div><label for="capex-shock">투자자산 취득 변화 <output id="capex-shock-value">0%</output></label><input id="capex-shock" type="range" min="-30" max="80" step="5" value="${state.capexShock}"></div></div><div id="scenario" aria-live="polite"></div><p class="chart-caption">다른 조건을 고정한 민감도입니다. 매출·마진·투자의 인과관계나 발생 확률을 추정한 결과가 아닙니다.</p></section>
      ${panel('가격이 보여준 경로와 위험',`${chart[0].date}–${p.lastDate} · 조정 종가 시작=100`,lineChart([{values:chart.map(r=>r.adjustedClose/base*100),color:'#245d53'}],690,240,`${c.name}의 최근 252거래일 가격 지수`)+`<div class="metric-grid">${stat('63일 가격 변화',pct(p.momentum63),'배당·분할 조정 공급자 시계열')}${stat('252일 가격 변화',pct(p.return252),'현지 통화 기준')}${stat('21일 변동성',pct(p.volatility21),'일별 로그수익 표준편차 × √252')}${stat('252일 최대 낙폭',pct(p.maxDrawdown252),'252일 구간 내 고점 대비')}</div><p class="chart-caption">조정 종가 기반 기술 통계이며 목표가·상승 확률·향후 손실 한도가 아닙니다. 자료 출처: Yahoo Finance.</p>`,source(c.id,'price'))}
      <div class="bottom-note"><div><strong>등록할 판단 변경 조건</strong><p>다음 정기공시에서 같은 길이 전년 동기 대비 (영업현금−${c.investmentScope})/매출이 개선되는지 확인합니다. 조건이 실패해도 사전 방향 예측이 없다면 예측 실패로 채점하지 않습니다.</p><button class="arrow-link" data-nav="tracking">보존한 조건 읽기 ↗</button></div><div><strong>가격 판단의 남은 작업</strong><p>정상 현금흐름, 전 주식 종류의 가치, 부채·리스·비영업자산을 검증해야 투자 선호와 가격 기대를 연결할 수 있습니다. 현금창출 조건만으로 적정 가격을 결정하지 않습니다.</p></div></div>`;
    main.querySelector('.actual-opinion').insertAdjacentHTML('afterend',window.EquityResearchView.render(c,payload));
    if(c.investmentDefinition){const d=c.investmentDefinition;main.insertAdjacentHTML('beforeend',`<section class="panel investment-definition"><h2>투자지출 태그와 실제 공시 표제</h2><p>${esc(d.explanation)}</p><p>확인 금액 ${amount(d.evidence.value,c)} ${unit(c)} · ${d.evidence.start}–${d.evidence.end}</p><a href="${esc(d.source.url)}" target="_blank" rel="noopener noreferrer">원 보고서에서 확인 ↗</a></section>`);}
    main.insertAdjacentHTML('beforeend',window.EquityCompanyAnalysis.render(c,payload));
    window.EquityCompanyAnalysis.bind(c,payload);
    main.insertAdjacentHTML('beforeend',window.EquityBusiness.render(c));
    window.EquityBusiness.bind(c);
    main.insertAdjacentHTML('beforeend',window.EquityCapital.render(c));
    main.insertAdjacentHTML('beforeend',window.EquityValuation.render(c));
    window.EquityValuation.bind(c);
    main.insertAdjacentHTML('beforeend',window.EquityResearchCase.render(c,payload));
    main.insertAdjacentHTML('beforeend',window.EquityQuestions.render(c,payload));
    main.insertAdjacentHTML('beforeend',window.EquityCoverage.render(c,payload));
    main.insertAdjacentHTML('beforeend',window.EquityDossier.render(c,payload));
    window.EquityDossier.bind(c);
    main.insertAdjacentHTML('beforeend',window.EquityIndustry.render(c));
    main.insertAdjacentHTML('beforeend',window.EquityNotebook.render(c,payload));
    window.EquityNotebook.bind(c,payload);
    updateScenario();
  }

  function updateScenario(){
    const c=company(),f=c.financials.current;
    const value=f.cfo.value*(1+state.cfoShock/100)-f.capex.value*(1+state.capexShock/100);
    document.querySelector('#cfo-shock-value').textContent=`${state.cfoShock}%`;
    document.querySelector('#capex-shock-value').textContent=`${state.capexShock}%`;
    document.querySelector('#scenario').innerHTML=`<div class="scenario-result">${amount(value,c)} <small>${unit(c)}</small></div><p class="context-note">투자 이후 현금 / 고정 매출: <strong>${pct(value/f.revenue.value)}</strong> · 실제 공시 기준 대비 ${pp(value/f.revenue.value-c.metrics.cashMargin)}</p>`;
  }

  const policies={equal_weight:['동일가중 기준선','#83917b'],momentum63:['63일 모멘텀','#245d53'],momentum_risk:['모멘텀 / 21일 위험','#af5b35'],oracle:['완전예지 상한','#8d7caa']};
  function renderLab(){
    const e=data.experiments.find(e=>e.market===state.lab);
    main.innerHTML=heading('EXPERIMENTS & BASELINES / 03','새로운 판단이 기준선보다 나았는가','현재 재무 선별과 별개로, 실제 가격에서 단순 규칙과 위험 정보의 기여를 시험합니다.',`<span>현재 생존 기업의 탐색 표본</span><span>시장별 현지 통화</span><span>미래 정보는 상한에만 사용</span>`)+`<div class="segmented lab-tabs">${['US','KR'].map(m=>`<button data-lab="${m}" aria-pressed="${state.lab===m}">${m==='US'?'미국':'한국'} 실험</button>`).join('')}</div>`;
    if(e.status!=='exploratory'){main.innerHTML+=`<p>${esc(e.reason)}</p>`;return;}
    const baseline=e.policies[0],oracle=e.policies.find(p=>p.id==='oracle');
    main.innerHTML+=`<div class="metric-grid">${stat('종목',e.members.length,e.members.join(' · '))}${stat('비중첩 관측 구간',e.windowCount,'보유 21거래일 · 통계적 독립 보장 아님')}${stat('실험 시작',e.start,'최소 126일 과거 정보 이후')}${stat('실험 종료',e.end,'미래 결과가 완성된 구간만')}</div>`+
      panel('같은 제약에서 비교한 가격 기반 결과',`시작 100 · 비용 미반영 · ${e.start}–${e.end}`,`<img class="research-image" src="../artifacts/live/${data.contentHash.slice(0,12)}-${e.market}-research.svg" alt="현재 기업 ${e.members.length}곳의 탐색 결과. 누적 경로는 로그 눈금이고 아래는 규칙별 기준선 차이와 95% 구간입니다."><p class="chart-caption">초기 개발 표본 ${e.members.length}곳의 실험입니다. 현재 조사 대상 ${data.companies.length}종목 전체의 성과가 아닙니다. 역사적 시장 전체의 투자 성과·업종 중립 알파로 해석하지 않습니다. 점선 완전예지는 실행 가능한 전략이 아닙니다.</p>`)+
      `<div class="oracle-box"><strong>완벽히 알았더라도 추가로 얻을 수 있는 범위</strong><br>같은 날짜·상위 2개 동일가중 제약에서 완전예지 누적 결과는 ${pct(oracle.cumulativeReturn)}, 전체 동일가중은 ${pct(baseline.cumulativeReturn)}입니다. 차이는 가능한 개선의 상한이며 현실적인 기대수익이 아닙니다.</div>
      <div class="table-wrap print-policy-table" tabindex="0"><table class="experiment-table"><thead><tr><th>규칙</th><th>누적 결과</th><th>창 평균 기준선 차이</th><th>차이의 95% 구간</th><th>연구 상태</th></tr></thead><tbody>${e.policies.map(p=>`<tr><td>${policies[p.id][0]}<small>${p.id==='momentum_risk'?'위험 조정 제거 → 순수 모멘텀':p.id==='oracle'?'실현된 미래를 사용 · 실행 불가':p.id==='equal_weight'?'개발 대상 전체 동일가중':'과거 63일 가격 변화 상위 2개'}</small></td><td class="num">${pct(p.cumulativeReturn)}</td><td class="num">${pp(p.meanExcess)}</td><td class="num">${p.excessInterval.length?`[${pp(p.excessInterval[0])}, ${pp(p.excessInterval[1])}]`:'표본 부족'}</td><td>${p.status==='baseline'?'기준선':p.status==='oracle_not_tradeable'?'완전예지 상한':p.status==='exploratory_positive'?'탐색상 양의 차이':'우위 확인 안 됨'}</td></tr>`).join('')}</tbody></table></div>
      <div class="report-section lab-method">${panel('변동성 예측의 기여는 별도로 평가','목표: 다음 21일 평균 로그수익 제곱 · 낮은 QLIKE가 작은 손실',`<div class="table-wrap" tabindex="0"><table class="experiment-table"><thead><tr><th>분산 예측</th><th>평균 QLIKE</th><th>126일 기준선과 차이</th><th>차이의 95% 구간</th></tr></thead><tbody>${e.risk.map(r=>`<tr><td>${{rv126:'과거 126일 제곱수익 평균',rv21:'과거 21일 제곱수익 평균',blend:'21일·126일 50:50 혼합'}[r.id]}</td><td class="num">${num(r.qlike,4)}</td><td class="num">${num(r.difference,4)}</td><td class="num">${r.interval.length?`[${num(r.interval[0],4)}, ${num(r.interval[1],4)}]`:'미확인'}</td></tr>`).join('')}</tbody></table></div><p class="chart-caption">종목별 일별 종가로 만든 분산 대용치입니다. 기존 논문의 월간 WML 분산 결과와 다른 분석입니다. 위험 예측 손실을 선별 수익으로 치환하지 않습니다.</p>`)}</div>
      <div class="research-summary"><div><h3>시점 검사</h3><p>t일까지의 정보로 신호를 만들고 t+1 종가부터 21거래일 뒤까지 비교합니다. 현재 공시의 재무 수치를 과거 신호에 넣지 않았습니다.</p></div><div><h3>제거 실험</h3><p>모멘텀/위험에서 위험 항목을 제거한 순수 모멘텀을 함께 남깁니다. 혼합 분산에서 최근 21일을 제거하면 126일 기준선이 됩니다.</p></div><div><h3>불확실성</h3><p>${e.contract.interval}. 시간창 비중첩이 통계적 독립을 보장하지 않습니다.</p></div></div>
      <div class="evidence-note">${e.limitations.map(l=>`<p>${esc(l)}</p>`).join('')}</div><div class="bottom-note"><div><strong>논문에서 가져온 방법</strong><p>예측과 경제적 가치의 분리, 강한 기준선, 완전예지 상한, 요소 제거 검사를 실제 주식 가격에서 다시 실행합니다.</p><a class="arrow-link" href="about.html#methods">연구 방법과 범위 읽기 ↗</a></div><div><strong>재무 규칙의 별도 평가</strong><p>위 가격 규칙의 결과를 현재 재무 선별의 성과로 사용하지 않습니다. 아래 실험은 당시 공시로 재무 조건을 직접 다시 계산합니다.</p></div></div>`;
    main.innerHTML+=fundamentalPanel();
    main.innerHTML+=window.EquityForwardStudy.render(payload,state.lab);
    renderWindowEvidence();
  }

  function fundamentalPanel(){
    const e=data.fundamentalExperiments?.find(e=>e.market===state.lab);
    if(!e)return '';
    if(e.status!=='exploratory')return `<section class="report-section"><h2>재무 선별 규칙의 검사</h2><p>${esc(e.reason)}</p></section>`;
    const names={equal_weight:'동일가중 기준선',financial_screen:'재무 조건 3개',without_growth:'매출 성장 조건 제거',oracle_one:'완전예지 1종목 상한'};
    return `<section class="report-section fundamental-report"><span class="eyebrow">POINT-IN-TIME FUNDAMENTAL EXPLORATION</span><h2>그때 공개된 공시로 선별했어도 나아졌는가</h2><p class="context-note">${e.start}–${e.end} · ${e.windowCount}개 평가 구간 · 자료 미충족 ${e.unresolvedWindows.length}개 구간 제외 · 현재 선택한 기업의 탐색 결과</p>
      ${panel('재무 조건과 조건 제거의 결과','신호일 전날까지 제출된 원문 수치만 사용',`<img class="research-image fundamental-image" src="../artifacts/live/${data.contentHash.slice(0,12)}-${e.market}-fundamental.svg" alt="재무 조건 3개와 성장 조건 제거의 기준선 대비 탐색 결과와 95% 구간"><p class="chart-caption">현재 재무 수치를 과거에 소급하지 않았습니다. 모든 종목의 공시 비교가 가능한 구간만 연결한 경로입니다. 제외된 구간의 수익은 이 누적 결과에 포함되지 않습니다.</p>`)}
      <div class="table-wrap print-policy-table" tabindex="0"><table class="experiment-table"><thead><tr><th>규칙</th><th>평가 구간 누적</th><th>창 평균 기준선 차이</th><th>탐색 95% 구간</th><th>판정</th></tr></thead><tbody>${e.policies.map(p=>`<tr><td>${names[p.id]}</td><td class="num">${pct(p.cumulativeReturn)}</td><td class="num">${pp(p.meanExcess)}</td><td class="num">${p.interval.length?`[${pp(p.interval[0])}, ${pp(p.interval[1])}]`:'표본 부족'}</td><td>${p.status==='baseline'?'기준선':p.status==='oracle_not_tradeable'?'실행 불가 상한':p.status==='exploratory_positive'?'탐색상 양의 차이':'우위 확인 안 됨'}</td></tr>`).join('')}</tbody></table></div>
      <div class="research-summary"><div><h3>정보 이용 시점</h3><p>${esc(e.contract.information)} ${esc(e.contract.missing)}</p></div><div><h3>고정 규칙과 제거</h3><p>${esc(e.contract.selection)} ${esc(e.contract.ablation)} 선택이 바뀐 구간 ${e.ablationChangedWindows}/${e.windowCount}개. 바뀐 구간이 없으면 성장 조건의 추가 기여를 확인하지 못한 것입니다.</p></div><div><h3>상한의 제약</h3><p>${esc(e.contract.oracle)} 비용·집중 위험은 비교 제약에 반영하지 않았습니다.</p></div></div><div class="evidence-note">${esc(e.contract.limitations)}</div>
      <section class="research-inspector panel"><div class="panel-head"><div><h3>그날의 선별을 원문까지 되짚기</h3><p class="panel-subtitle">판단일을 바꾸면 사용한 공시·조건·선택이 함께 바뀝니다.</p></div><label for="research-window">판단일 <select id="research-window" class="company-select">${e.windows.map((w,i)=>`<option value="${i}">${w.signalDate}</option>`).join('')}</select></label></div><div id="window-evidence" aria-live="polite"></div>
      <details class="missing-windows"><summary>자료 미충족으로 제외한 구간 ${e.unresolvedWindows.length}개</summary>${e.unresolvedWindows.length?e.unresolvedWindows.map(w=>`<p>${w.signalDate} · ${Object.entries(w.issues).map(([id,issue])=>`${esc(byId(id))}: ${esc(issue)}`).join(' / ')}</p>`).join(''):'제외한 구간이 없습니다.'}</details></section></section>`;
  }

  function renderWindowEvidence(){
    const target=document.querySelector('#window-evidence');if(!target)return;
    const e=data.fundamentalExperiments.find(e=>e.market===state.lab),w=e.windows[Number(document.querySelector('#research-window').value)];
    target.innerHTML=`<p class="context-note">판단 ${w.signalDate} · 진입 ${w.entryDate} · 평가 종료 ${w.endDate}<br>선택: ${w.picks.financial_screen.map(byId).map(esc).join(' · ')}${w.fallbackToEqualWeight?' · 충족 종목이 없어 전체 동일가중 적용':''}</p><div class="table-wrap" tabindex="0"><table class="experiment-table"><thead><tr><th>기업 · 사용 공시</th><th>회계기간 종료</th><th>매출 증가</th><th>현금잉여</th><th>현금 마진 변화</th><th>조건</th></tr></thead><tbody>${Object.entries(w.signals).map(([id,s])=>{const c=data.companies.find(c=>c.id===id),hashes=[...new Set(s.evidence.map(f=>f.sourceHash))],sources=hashes.map(h=>c.sources.find(x=>x.sha256===h)).filter(Boolean);return `<tr><td>${esc(c.name)}<small>사용 항목 최종 제출 ${s.filedAt}</small>${sources.map((src,i)=>`<a class="window-source" href="${esc(src.file?'../'+src.file:src.url)}" target="_blank" rel="noopener noreferrer">${src.file?'보존':'공시'} 원문 ${i+1} ↗</a>`).join(' · ')}</td><td>${s.periodEnd}</td><td class="num">${pct(s.metrics.revenueGrowth)}</td><td class="num">${amount(s.metrics.cashAfterInvestment,c)}<small>${unit(c)}</small></td><td class="num">${pp(s.metrics.cashMarginChange)}</td><td>${s.passes?'모두 충족':'일부 미충족'}</td></tr>`;}).join('')}</tbody></table></div><p class="chart-caption">사용한 모든 입력의 제출일은 ${w.signalDate}보다 앞섭니다. 과거 선택은 현재 보유한 공시 원문으로 재구성한 탐색이며 당시 작성한 추천이 아닙니다.</p>`;
  }

  function renderTracking(){
    const selected=location.hash.split('/')[1],rows=payload.ledger.filter(x=>!selected||x.registration.company===selected);
    main.innerHTML=heading('DECISION RECORD / 04','지금의 조건을 다음 공시와 연결합니다','실제 기업의 조건을 저장하고, 조건의 성립과 사전 예측의 적중을 구분합니다.',`<span>${rows.length}개 조건</span><span>방향 예측 미등록</span><span>판단 기록의 해시 체인</span>`)+
      `<div class="evidence-note">등록 시점 이후 제출된 새로운 정기공시만 채점 대상으로 삼습니다. 공시일만 확인되는 경우 같은 날 자료는 선후 관계를 입증할 수 없어 제외합니다. 로컬 해시는 변경 탐지용이며 외부 시점 인증을 대신하지 않습니다.</div><p class="context-note">판단 기록은 연구 결과와 함께 갱신됩니다. 이 화면에서는 저장된 기록과 최초 관측을 확인할 수 있습니다.</p>`+
      (selected?`<p class="context-note">${esc(byId(selected))}의 조건 · <button data-nav="tracking">전체 기업 보기</button></p>`:'')+rows.map(({registration:r,observation:o})=>`<article class="record-card"><div class="record-top"><h3>${esc(byId(r.company))} · ${r.company}</h3>${pillar(({pending:'공시 대기',unresolved:'자료 미확인',met:'조건 충족',not_met:'조건 미충족'})[o.status])}</div><p>${esc(r.definition)}</p><div class="source-period">등록 ${new Date(r.recordedAt).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',hour12:false})} KST · 기준 공시기간 ${r.periodEnd}</div><p>기준선: ${esc(r.baseline)}<br>예측 채점: ${o.predictionCorrect===null?'사전 예측 없음 · 채점 대상 아님':o.predictionCorrect?'적중':'미적중'}<br>현재 관측: ${esc(o.reason??`${o.filedAt} 공시 · 변화 ${o.unit==='days'?num(o.value,2)+'일':pp(o.value)}`)}</p><details class="technical"><summary>기록 무결성과 입력 버전</summary><code>${r.hash}</code><code>입력 ${r.snapshotHash}</code><code>연결 ${r.previousHash}</code></details></article>`).join('');
  }

  function renderSources(){
    main.innerHTML=heading('PROVENANCE & QUALITY / 05','어떤 자료로 어떤 판단을 만들었는가','외부 원문, 회계 정의, 계산과 연구의 상태를 함께 확인합니다.',`<span>분석 기준 ${data.asOf}</span><span>생성 ${data.generatedAt.slice(0,10)}</span><span>${data.failures.length}개 연결 실패</span>`)+
      `<div class="evidence-note">${data.boundaries.map(x=>`<p>${esc(x)}</p>`).join('')}</div><p class="context-note">이 로컬 분석의 자료 기준일과 출처입니다. 저장 원문으로 다시 계산할 수 있으며 수집 실패와 공시 이력 공백은 각 기업에 표시합니다.</p><ul class="source-list">`+
      data.companies.map(c=>`<li><div class="panel-head"><h3>${esc(c.name)} · ${c.id}</h3>${c.status==='ready'?source(c.id):'<span class="failed-status">자료 미확인</span>'}</div>${c.status==='ready'?`<p>${selectedPeriod(c)} · ${c.financials.standard} 연결 · 공시 ${c.financials.filedAt}<br>투자 정의: ${c.investmentScope} · 가격 ${c.priceSummary.lastDate} ${c.currency}</p>${c.sources.map(s=>`<p><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.provider)} 원문 ↗</a> · 수집 ${s.retrievedAt.slice(0,10)}${s.mode?' · '+esc(s.mode):''}</p><details class="technical"><summary>원본 무결성 SHA-256</summary>${s.file?`<a href="../${esc(s.file)}">이 프로젝트의 원본 사본</a>`:"<p>수집 원본은 연구 실행 자료에 보존합니다. 공개 페이지는 위 제공기관 원문으로 연결됩니다.</p>"}<code>${s.sha256}</code></details>`).join('')}`:`<p>${esc(c.error)}</p>`}</li>`).join('')+`</ul><div class="bottom-note"><div><strong>프로그램과 금융 해석은 다른 검증입니다.</strong><p>숫자·기간·원문 무결성과 계산을 자동 검사합니다. 기업 해석의 독립 승인, 가격의 적정성, 선별의 표본외 초과수익은 아직 별도 검증이 필요합니다.</p></div><div><strong>분석 버전</strong><p>${data.universeVersion}</p><details class="technical"><summary>스냅샷 해시</summary><code>${data.contentHash}</code></details></div></div>`;
  }

  function evidence(id,kind){
    const c=data.companies.find(c=>c.id===id);if(!c||c.status!=='ready')return;
    trigger=document.activeElement;
    document.querySelector('#evidence-title').textContent=`${c.name} · ${kind==='price'?'가격 정의':'같은 기간의 공시와 계산'}`;
    const f=c.financials;
    document.querySelector('#evidence-body').innerHTML=kind==='price'?`<p>관측 종가 ${num(c.priceSummary.close,2)} ${c.currency} · ${c.priceSummary.lastDate}</p><p>과거 변화와 위험은 공급자의 adjusted close를 사용합니다. 종가는 close 필드입니다. 통화와 종목 식별자를 확인하고 ${data.asOf} 이후의 관측을 제외했습니다.</p><p>변동성: 일별 로그수익의 표본 표준편차 × √252. 최대낙폭: 최근 252거래일 구간의 직전 고점 대비 하락률 최솟값.</p><a href="${esc(c.sources.find(s=>s.provider==='Yahoo Finance').url)}" target="_blank" rel="noopener noreferrer">가격 원문 ↗</a>`:
      `<p>${selectedPeriod(c)} · ${f.standard} 연결 · 단위 ${unit(c)}</p><div class="table-wrap" tabindex="0"><table class="evidence-table"><thead><tr><th>항목</th><th>전년 동기</th><th>당기</th></tr></thead><tbody>${['revenue','operating_income','net_income','cfo','capex'].map((k,i)=>`<tr><td>${['매출','영업이익','순이익','영업현금',c.investmentScope][i]}</td><td class="num">${f.previous[k]?amount(f.previous[k].value,c):'미확인'}</td><td class="num">${f.current[k]?amount(f.current[k].value,c):'미확인'}</td></tr>`).join('')}</tbody></table></div><p>현금잉여 마진 = (영업현금−${c.investmentScope}) / 매출 = ${pct(c.metrics.cashMargin)}. 전년 대비 ${pp(c.metrics.cashMarginChange)}.</p><p>비교 전년 기간: ${f.priorStart}–${f.priorEnd}. 입력은 기준일 이내에 제출된 연결 공시로 제한합니다.</p><a href="${esc(f.current.cfo.sourceUrl)}" target="_blank" rel="noopener noreferrer">해당 공시 원문 ↗</a><details class="technical"><summary>태그·문서·원문 해시</summary>${Object.entries(f.current).filter(([,v])=>v).map(([k,v])=>`<code>${k}: ${esc(v.tag)} / ${esc(v.context??v.accession)} / ${v.value} ${v.unit}</code>`).join('')}<code>${f.current.cfo.sourceHash}</code></details>`;
    dialog.showModal();
  }

  function route(){if(location.hash==='#content')return;const [view,id]=location.hash.slice(1).split('/');state.view=Object.hasOwn(titles,view)?view:'universe';if(id&&data.companies.some(c=>c.id===id))state.company=id;document.querySelector('#current-title').textContent=titles[state.view];document.title=state.view==='company'?`${data.companies.find(c=>c.id===state.company)?.name||state.company} (${state.company}) · ${data.asOf} · 주식 연구실`:`${titles[state.view]} · 주식 연구실`;document.querySelectorAll('[data-view]').forEach(a=>{if(a.dataset.view===state.view)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});main.dataset.view=state.view;({universe:renderUniverse,company:renderCompany,lab:renderLab,tracking:renderTracking,sources:renderSources})[state.view]();main.focus({preventScroll:true});scrollTo(0,0);}
  function navigate(hash){if(location.hash===`#${hash}`)route();else location.hash=hash;}
  document.addEventListener('click',event=>{const b=event.target.closest('button');if(!b)return;const d=b.dataset;if(d.company)navigate(`company/${d.company}`);else if(d.nav)navigate(d.nav);else if(d.market){state.market=d.market;renderUniverse();document.querySelector(`[data-market="${d.market}"]`).focus({preventScroll:true});}else if(d.lab){state.lab=d.lab;renderLab();document.querySelector(`[data-lab="${d.lab}"]`).focus({preventScroll:true});}else if(d.evidence)evidence(d.evidence,d.kind);else if(d.action==='close')dialog.close();else if(d.action==='print')print();});
  document.addEventListener('change',event=>{if(event.target.id==='company-picker'){navigate('company/'+event.target.value);}else if(event.target.id==='sector-filter'){state.sector=event.target.value;renderUniverse();document.querySelector('#sector-filter').focus({preventScroll:true});}else if(event.target.id==='candidate-only'){state.candidates=event.target.checked;renderUniverse();document.querySelector('#candidate-only').focus({preventScroll:true});}else if(event.target.id==='sort'){state.sort=event.target.value;renderUniverse();document.querySelector('#sort').focus({preventScroll:true});}else if(event.target.id==='research-window')renderWindowEvidence();});
  document.addEventListener('input',event=>{if(event.target.id==='company-search'){const pos=event.target.selectionStart;state.query=event.target.value;renderUniverse();const e=document.querySelector('#company-search');e.focus({preventScroll:true});e.setSelectionRange(pos,pos);}if(event.target.id==='cfo-shock'){state.cfoShock=Number(event.target.value);updateScenario();}if(event.target.id==='capex-shock'){state.capexShock=Number(event.target.value);updateScenario();}});
  dialog.addEventListener('close',()=>{if(trigger?.isConnected)trigger.focus();});
  document.querySelector('.preview-notice span').textContent=`실제 자료 · 조사 대상 ${data.companies.length}종목 · 계산·주석 분석·AI 판독의 범위를 구분합니다.`;
  document.querySelector('#asof-label').textContent=`자료 기준 ${data.asOf}`;
  document.querySelector('.footer span:last-child').textContent=`자료 ${data.asOf} · 분석 버전 ${data.contentHash.slice(0,12)}`;
  const printStamp=document.createElement('div');
  printStamp.className='print-stamp';
  printStamp.textContent=`주식 연구실 · 자료 ${data.asOf} · 분석 버전 ${data.contentHash.slice(0,12)} · SEC / DART / Yahoo Finance`;
  document.body.prepend(printStamp);
  addEventListener('hashchange',route);route();
})();
