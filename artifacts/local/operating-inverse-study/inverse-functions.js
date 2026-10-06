  function marginRequirements(m,a){
    calculate(m,a);
    const market=m.security.marketCapProxy,eligible=m.security.status==='available'&&Number.isFinite(market)&&market>0,rows=[];
    for(let i=0;i<m.segments.length;i++){
      const segment=m.segments[i],low=segment.minMargin??-.5,high=m.grossProfitPath?1:.9;
      const row={segment:segment.id,label:segment.label,lower:low,upper:high,currentAssumption:a.segments[i].marginEnd,requiredMargin:null,change:null,relativeMarketResidual:null,terminalCash:null,status:'security_unresolved'};
      if(!eligible){rows.push(row);continue;}
      const evaluate=value=>{const changed=structuredClone(a);changed.segments[i].marginEnd=value;const r=calculate(m,changed),signed=r.explicitPv+r.terminal.cash/(changed.discount-changed.terminal)/(1+changed.discount)**5;return [signed-market,r];};
      const [fl]=evaluate(low),[fh]=evaluate(high),tolerance=Math.max(1,market*1e-10);
      if(Math.abs(fh-fl)<=tolerance)row.status='no_margin_identification';
      else if(fh<fl)row.status='nonmonotone_review';
      else if(fl>tolerance)row.status='below_supported_range';
      else if(fh< -tolerance)row.status='above_supported_range';
      else{
        let lo=low,hi=high;
        for(let j=0;j<70;j++){const mid=(lo+hi)/2,[fm]=evaluate(mid);if(fm<0)lo=mid;else hi=mid;}
        const margin=(lo+hi)/2,[residual,result]=evaluate(margin);
        if(result.terminal.cash<=0||result.equityValue===null)row.status='nonpositive_terminal';
        else if(Math.abs(residual)>tolerance)row.status='residual_review';
        else Object.assign(row,{status:'solved',requiredMargin:margin,change:margin-row.currentAssumption,relativeMarketResidual:residual/market,terminalCash:result.terminal.cash});
      }
      rows.push(row);
    }
    return {version:'single-segment-margin-inverse-v1',rows,scope:'다른 선택 가정을 고정하고 각 사업부의 5년차 마진만 하나씩 바꾼 별도 역산이다. 행들을 동시에 적용하지 않는다. 본업 현금 경로 밖의 자산·계약 손실과 정상화 공백은 별도이며 실제 마진 전망·컨센서스·목표가가 아니다.'};
  }
  function impliedMarginEvidence(m,a){
    const r=marginRequirements(m,a),states={security_unresolved:'증권 범위 미확정',no_margin_identification:'이 경로에서 마진 식별 불가',above_supported_range:'지원 상단보다 높은 마진 필요',below_supported_range:'지원 하단보다 낮은 마진 필요',nonpositive_terminal:'양의 말기 현금 조건 미충족',nonmonotone_review:'단조성 재검토',residual_review:'계산 잔차 재검토'};
    if(r.rows.every(x=>x.status==='security_unresolved'))return '<section class="operating-implied-margins"><h3>현재 가격에 필요한 사업부 마진</h3><p>증권별 권리·유통 수량 범위가 미확정이므로 현재 주가를 사업부 마진으로 역산하지 않습니다. 위 사업 현금 경로는 계속 편집할 수 있습니다.</p></section>';
    return `<section class="operating-implied-margins"><h3>현재 가격과 일치하려면 필요한 사업부 마진</h3><p>5년차 ${esc(m.marginLabel||'영업이익률')}만 한 사업부씩 바꾸고, 성장·다른 부문의 마진·세금·재투자·할인 가정은 현재 선택을 유지합니다. 2–5년차 이익과 세금, 6년차 말기 현금을 모두 다시 계산합니다.</p><div class="table-wrap"><table><thead><tr><th>따로 역산한 사업부</th><th>선택 5년차 마진</th><th>가격 일치 마진</th><th>선택 대비 변화</th><th>탐색 범위</th></tr></thead><tbody>${r.rows.map((x,i)=>`<tr><th>${esc(x.label)}</th><td>${pct(x.currentAssumption)}</td><td>${x.status==='solved'?pct(x.requiredMargin):esc(states[x.status])}</td><td>${x.change==null?'—':n(x.change*100,2)+'%p'}${x.status==='solved'?`<button type="button" data-implied-margin="${i}">가정에 대입</button>`:''}</td><td>${pct(x.lower)}–${pct(x.upper)}</td></tr>`).join('')}</tbody></table></div><p>${esc(r.scope)} 범위를 벗어난 결과를 실제 달성 불가능이나 회피 의견으로 바꾸지 않습니다. 범위는 이 작업 도구의 지원 구간입니다.</p>${m.contractSupport?'<p>고객 금융의 일회성 순지급은 이 반복 사업 현금 역산에 합치지 않았습니다. 위 계약 스트레스와 별도로 검토하세요.</p>':''}</section>`;
  }
