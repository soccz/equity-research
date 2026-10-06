(() => {
  const payload=window.EQUITY_SNAPSHOT;
  if(!payload){document.querySelector('#runtime-error').textContent='저장한 분석 파일이 없습니다. 프로젝트 폴더에서 python3 start.py status로 상태를 확인하세요.';return;}
  const s=payload.snapshot,ready=s.companies.filter(c=>c.status==='ready');
  document.querySelector('#analysis-status').textContent=`자료 기준 ${s.asOf} · 미국 ${ready.filter(c=>c.market==='US').length} / 한국 ${ready.filter(c=>c.market==='KR').length} · 분석 ${s.contentHash.slice(0,12)}. PDF는 마지막 출력본이므로 문서에 적힌 버전을 확인하세요.`;
  for(const button of document.querySelectorAll('[data-copy]'))button.addEventListener('click',async()=>{
    const code=button.previousElementSibling;
    try{await navigator.clipboard.writeText(code.textContent);button.textContent='복사됨';}
    catch{const range=document.createRange();range.selectNodeContents(code);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);button.textContent='선택한 명령을 복사하세요';}
  });
})();
