/* Local research: exact filing passages, authored judgments, reversible versions. */
(() => {
  const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const KEY = 'equity-research-notebook-v1';
  const fields = {thesis:'핵심 판단과 사업 근거', comparison:'비교 기업보다 나은 점·불리한 점', assumptions:'가격 시나리오의 사업 가정', countercase:'가장 강한 반론', changes:'판단을 바꿀 관측과 시점'};
  const opinions = ['관찰','조건부 선호','선호','회피'];
  const corpora = new Map(), loading = new Map();
  let active, records = [], selected = [], storageFailure = '', drafts = [];
  const sha = async text => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))].map(x=>x.toString(16).padStart(2,'0')).join('');
  function validate(rows) {
    const companies = new Set(window.EQUITY_SNAPSHOT.snapshot.companies.map(c=>c.id));
    if (!Array.isArray(rows) || rows.length > 2000) throw Error('연구 기록 배열 또는 개수 오류');
    const ids = new Set();
    for (const r of rows) {
      if (!r || !companies.has(r.company) || !/^[a-zA-Z0-9-]{10,80}$/.test(r.id) || ids.has(r.id) || !opinions.includes(r.opinion) || !Number.isFinite(Date.parse(r.recordedAt)) || !/^[a-f0-9]{64}$/.test(r.snapshotHash) || !/^[a-f0-9]{64}$/.test(r.corpusHash)) throw Error('연구 기록 식별자·버전 오류');
      ids.add(r.id);
      for (const key of Object.keys(fields)) if (typeof r[key] !== 'string' || r[key].length > 12000) throw Error('연구 문장 길이 오류');
      if (!Array.isArray(r.evidence) || r.evidence.length > 30) throw Error('채택 근거 개수 오류');
      for (const p of r.evidence) {
        const url = new URL(p.sourceUrl);
        if (!/^[a-f0-9]{20}$/.test(p.id) || !/^[a-f0-9]{64}$/.test(p.sourceHash) || typeof p.text !== 'string' || p.text.length > 50000 || !['www.sec.gov','dart.fss.or.kr'].includes(url.hostname) || url.protocol !== 'https:') throw Error('채택 근거 형식 오류');
      }
    }
    return rows;
  }
  try { records = validate(JSON.parse(localStorage.getItem(KEY) || '[]')); }
  catch (e) { storageFailure = '이전 저장 기록을 읽지 못했습니다. 원 저장값을 유지합니다. ' + e.message; }
  try { drafts = validate(JSON.parse(localStorage.getItem(KEY+'-drafts') || '[]')); }
  catch(e) { storageFailure += ' 임시 작성 기록을 읽지 못했습니다. 원 저장값을 유지합니다. ' + e.message; }
  const history = c => records.filter(r=>r.company===c.id);
  function message(text) { const e=document.querySelector('#notebook-status'); if(e)e.textContent=text; }
  function persist(next) {
    validate(next);
    if (storageFailure) throw Error('기존 저장 오류를 해결하기 전에는 원 저장값을 덮어쓰지 않습니다.');
    localStorage.setItem(KEY, JSON.stringify(next));
    records = next;
  }
  function capture(c,payload,id=crypto.randomUUID()) {
    return {id,company:c.id,recordedAt:new Date().toISOString(),snapshotHash:payload.snapshot.contentHash,corpusHash:c.narrative.evidenceHash,opinion:document.querySelector('#notebook-opinion').value,...Object.fromEntries(Object.keys(fields).map(k=>[k,document.querySelector('#notebook-'+k).value.trim()])),evidence:structuredClone(selected)};
  }
  function saveDraft(c,payload) {
    if(storageFailure)throw Error(storageFailure);
    const next=validate([...drafts.filter(r=>r.company!==c.id),capture(c,payload,'draft-note-'+c.id)]);
    localStorage.setItem(KEY+'-drafts',JSON.stringify(next));drafts=next;
    message('작성 중인 내용을 이 브라우저에 임시 저장했습니다. 새 버전 저장으로 판단 이력에 남기세요.');
  }
  async function receive(body) {
    const c = window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id===body.company);
    const pending=loading.get(body.company);
    try {
      if (!c || c.narrative?.accession!==body.accession || await sha(JSON.stringify(body))!==c.narrative.evidenceHash) throw Error('공시 본문 해시 또는 접수번호 불일치');
      corpora.set(c.id,body); pending?.resolve(body);
    } catch(e) { pending?.reject(e); }
    finally { loading.delete(body.company); }
  }
  async function load(c) {
    if(corpora.has(c.id))return corpora.get(c.id);
    if(loading.has(c.id))return loading.get(c.id).promise;
    let resolve,reject;
    const promise=new Promise((a,b)=>{resolve=a;reject=b;});
    loading.set(c.id,{promise,resolve,reject});
    const script=document.createElement('script');
    script.src='../'+c.narrative.file;
    script.onerror=()=>{loading.delete(c.id);reject(Error('보존 본문을 열지 못했습니다. 수집·오프라인 재계산을 확인하세요.'));};
    document.head.append(script);
    return promise;
  }
  function render(c,payload) {
    if(payload.publication || c.narrative?.status!=='ready')return '';
    return `<section class="panel notebook" id="notebook"><div class="panel-head"><div><span class="eyebrow">RESEARCH / SOURCE WORKBENCH</span><h2>원문에서 판단까지, 나의 연구 작업</h2><p>공시 ${esc(c.narrative.filedAt)} · 본문 ${c.narrative.passageCount.toLocaleString()}개 문단·표행. 현재 기업의 본문만 열 때 읽습니다.</p></div><button type="button" class="notebook-open">연구 작업 열기</button></div><p class="notebook-summary">${history(c).length}개 연구 버전 저장 · 직접 작성한 판단이며 자동 금융 승인이나 사전 등록된 예측이 아닙니다.</p><div class="notebook-editor" hidden><div class="notebook-grid"><div><label for="filing-query">원문 검색</label><input type="search" id="filing-query" placeholder="가격, 수주, HBM, cash, customer…"><label class="notebook-table-toggle"><input type="checkbox" id="filing-tables"> 표행 포함</label><p class="chart-caption">띄어쓴 검색어를 모두 포함하는 문단을 찾습니다. 가격·출하량의 비교 기간은 주변 문단에서 확인합니다.</p><p id="filing-count" aria-live="polite"></p><div id="filing-results"></div></div><div><h3>채택한 근거와 연구 판단</h3><div id="notebook-evidence"></div><label for="notebook-opinion">나의 잠정 의견</label><select id="notebook-opinion">${opinions.map(x=>`<option>${x}</option>`).join('')}</select>${Object.entries(fields).map(([k,v])=>`<label for="notebook-${k}">${v}</label><textarea id="notebook-${k}" rows="3" maxlength="12000"></textarea>`).join('')}<div class="notebook-actions"><button type="button" data-notebook="save">새 버전 저장</button><button type="button" data-notebook="export">전체 연구 기록 내보내기</button><label class="notebook-import">기록 파일 가져오기<input type="file" id="notebook-import" accept="application/json,.json"></label></div><p id="notebook-status" role="status"></p><details><summary>이 기업의 이전 연구 버전</summary><div id="notebook-history"></div></details></div></div></div><div id="notebook-print"></div></section>`;
  }
  function evidenceStatus(r,c) {
    if(r.corpusHash!==c.narrative.evidenceHash)return '공시 본문 변경 · 이전 근거 재검토 필요';
    const body=corpora.get(c.id);
    if(!body)return '원문 대조 대기';
    return r.evidence.every(p=>body.passages.some(q=>q.id===p.id&&q.sourceHash===p.sourceHash&&q.text===p.text))?'현재 본문과 인용 일치 · 판단의 타당성은 별도':'원문과 인용 불일치 · 채택 재검토';
  }
  function displayRecords(c) {
    const rows=history(c),last=rows.at(-1),e=document.querySelector('#notebook-history');
    if(e)e.innerHTML=rows.slice().reverse().map(r=>`<article><strong>${esc(r.opinion)}</strong> · ${esc(r.recordedAt)}<p>${esc(evidenceStatus(r,c))}</p><p>${esc(r.thesis)}</p></article>`).join('')||'<p>저장한 기록이 없습니다.</p>';
    document.querySelector('.notebook-summary').textContent=`${rows.length}개 연구 버전 저장 · 직접 작성한 판단이며 자동 금융 승인이나 사전 등록된 예측이 아닙니다.`;
    document.querySelector('#notebook-print').innerHTML=last?`<h3>저장한 연구 판단 · ${esc(last.opinion)}</h3><p>${esc(last.recordedAt)} · ${esc(evidenceStatus(last,c))}</p>${Object.entries(fields).map(([k,v])=>`<h4>${v}</h4><p>${esc(last[k])}</p>`).join('')}<p>${last.evidence.map(p=>`<a href="${esc(p.sourceUrl)}" target="_blank" rel="noopener noreferrer">채택 근거 ${esc(p.id)} ↗</a>`).join(' · ')}</p>`:'';
  }
  function displaySelected(c) {
    const body=corpora.get(c.id);
    document.querySelector('#notebook-evidence').innerHTML=selected.map(p=>`<article><small>${body.passages.some(q=>q.id===p.id&&q.sourceHash===p.sourceHash&&q.text===p.text)?'현재 원문 일치':'이전/불일치 근거 · 재검토'}</small><p>${esc(p.text)}</p><a href="${esc(p.sourceUrl)}" target="_blank" rel="noopener noreferrer">공시 원문 ↗</a> <button type="button" data-remove-evidence="${esc(p.id)}">제외</button></article>`).join('')||'<p>왼쪽 원문에서 근거를 채택하세요. 회사 설명과 자신의 해석을 구분해 작성합니다.</p>';
  }
  function search(c) {
    const body=corpora.get(c.id),terms=document.querySelector('#filing-query').value.trim().toLowerCase().split(/\s+/).filter(Boolean),tables=document.querySelector('#filing-tables').checked;
    const rows=body.passages.filter(p=>(tables||p.kind!=='table')&&terms.every(q=>p.text.toLowerCase().includes(q)));
    document.querySelector('#filing-count').textContent=`${rows.length}개 일치 · 앞 ${Math.min(rows.length,40)}개 표시`;
    document.querySelector('#filing-results').innerHTML=rows.slice(0,40).map(p=>`<article><small>${p.kind==='table'?'표행 · 원문 머리글·단위 확인':'공시 문단'} · ${esc(p.heading)} · #${p.ordinal}</small><p>${esc(p.text)}</p><button type="button" data-pick-evidence="${p.id}">근거로 채택</button> <a href="${esc(p.sourceUrl)}" target="_blank" rel="noopener noreferrer">공시 원문 ↗</a><details><summary>앞뒤 문맥</summary>${body.passages.slice(Math.max(0,p.ordinal-2),p.ordinal+3).map(q=>`<p>${esc(q.text)}</p>`).join('')}</details></article>`).join('');
  }
  async function importText(text) {
    if(text.length>12_000_000)throw Error('파일 크기 제한 초과');
    const bundle=JSON.parse(text);
    if(bundle.version!=='equity-notebook-v2'||await sha(JSON.stringify({records:bundle.records,drafts:bundle.drafts}))!==bundle.sha256)throw Error('연구 파일 해시 또는 형식 불일치');
    const incoming=validate(bundle.records),known=new Map(records.map(r=>[r.id,r]));
    const incomingDrafts=validate(bundle.drafts);
    for(const r of incoming)if(known.has(r.id)&&JSON.stringify(known.get(r.id))!==JSON.stringify(r))throw Error('같은 기록 ID의 내용 충돌. 기존 기록을 유지합니다.');
    const added=incoming.filter(r=>!known.has(r.id));
    const next=[...records,...added].sort((a,b)=>a.recordedAt.localeCompare(b.recordedAt));
    // Existing in-progress writing wins; imported drafts only fill empty companies.
    const nextDrafts=validate([...drafts,...incomingDrafts.filter(r=>!drafts.some(d=>d.company===r.company))]);
    persist(next);
    localStorage.setItem(KEY+'-drafts',JSON.stringify(nextDrafts));drafts=nextDrafts;
    return added.length;
  }
  async function exportText() { return JSON.stringify({version:'equity-notebook-v2',records,drafts,sha256:await sha(JSON.stringify({records,drafts}))},null,2); }
  function bind(c,payload) {
    if(payload.publication||c.narrative?.status!=='ready')return;
    active=c.id;displayRecords(c);
    document.querySelector('.notebook-open').onclick=async()=>{
      try {
        await load(c);if(active!==c.id)return;
        document.querySelector('.notebook-editor').hidden=false;
        const r=drafts.find(r=>r.company===c.id)||history(c).at(-1);selected=r?structuredClone(r.evidence):[];
        for(const key of Object.keys(fields))document.querySelector('#notebook-'+key).value=r?.[key]||'';
        document.querySelector('#notebook-opinion').value=r?.opinion||'관찰';
        search(c);displaySelected(c);displayRecords(c);message(storageFailure||'이 브라우저에 저장됩니다. 이동·백업할 때 기록 파일을 내보내세요.');
      } catch(e){document.querySelector('.notebook-summary').textContent=e.message;}
    };
    document.querySelector('#filing-query').oninput=()=>search(c);
    document.querySelector('#filing-tables').onchange=()=>search(c);
    document.querySelector('.notebook').addEventListener('click',async e=>{
      const pick=e.target.closest('[data-pick-evidence]'),remove=e.target.closest('[data-remove-evidence]'),button=e.target.closest('[data-notebook]');
      try {
        if(pick){if(selected.length>=30)throw Error('한 버전의 근거는 최대 30개입니다.');const p=corpora.get(c.id).passages.find(p=>p.id===pick.dataset.pickEvidence);if(!selected.some(x=>x.id===p.id))selected.push(structuredClone(p));displaySelected(c);saveDraft(c,payload);}
        if(remove){selected=selected.filter(p=>p.id!==remove.dataset.removeEvidence);displaySelected(c);saveDraft(c,payload);}
        if(button?.dataset.notebook==='save'){
          const content=Object.fromEntries(Object.keys(fields).map(k=>[k,document.querySelector('#notebook-'+k).value.trim()]));
          if(!selected.length||!content.thesis||!content.countercase||!content.changes)throw Error('근거와 핵심 판단·반론·변경 조건을 작성하세요.');
          const record=capture(c,payload);saveDraft(c,payload);
          persist([...records,record]);displayRecords(c);message('새 연구 버전을 저장했습니다. 이전 버전도 유지합니다.');
        }
        if(button?.dataset.notebook==='export'){
          const blob=new Blob([await exportText()],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='equity-research-notebook.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message('전체 기업의 연구 기록 파일을 내보냈습니다.');
        }
      }catch(e){message(e.message);}
    });
    for(const e of document.querySelectorAll('.notebook textarea,#notebook-opinion'))e.addEventListener('input',()=>{try{saveDraft(c,payload)}catch(error){message(error.message)}});
    document.querySelector('#notebook-import').onchange=async e=>{
      try{const f=e.target.files[0];if(!f)return;if(f.size>12_000_000)throw Error('파일 크기 제한 초과');const n=await importText(await f.text());displayRecords(c);message(`${n}개 버전을 추가했습니다. 연구 작업 열기로 최신 내용을 불러오세요.`);}catch(e){message(e.message);}finally{e.target.value='';}
    };
  }
  window.EquityNotebook={render,bind,receive,load,validate,importText,exportText};
})();
