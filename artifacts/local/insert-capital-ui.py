from pathlib import Path
p=Path('app/valuation.js');s=p.read_text()
insert='''  function preferredConversion(t,p){
    if(!Number.isFinite(p)||p<=0)throw new Error('계약상 평균가격은 양수여야 합니다.');
    return p>t.thresholdPrice?t.minimumRate:p<t.initialPrice?t.maximumRate:Math.round(1000/p*10000)/10000;
  }
  function capitalEvidence(c){
    const r=c.valuation?.security?.capitalReview;if(!r)return '';
    const x=p=>50+(p-150)/550*630,y=n=>150-(n-2.2)/.7*115;
    const colors=['#287c7c','#ad693c'];
    return `<details open class="valuation-capital-contract"><summary>Alphabet 전환우선주 · 현금 배당과 기본 전환 조건</summary><p>${esc(r.commonRights)}</p><p>${esc(r.quantityScope)}</p><div class="table-wrap"><table><thead><tr><th>우선주 → 보통주</th><th>낮은 평균가격 구간 / 전환 수</th><th>중간 구간</th><th>높은 평균가격 구간 / 전환 수</th></tr></thead><tbody>${r.terms.map(t=>`<tr><th><a href="${esc(t.sourceUrl)}" target="_blank" rel="noopener noreferrer">Series ${t.series} → Class ${t.commonClass} ↗</a></th><td>$${num(t.initialPrice,4)} 미만 / ${num(t.maximumRate,4)}주</td><td>$1,000 ÷ 해당 평균가격</td><td>$${num(t.thresholdPrice,4)} 초과 / ${num(t.minimumRate,4)}주</td></tr>`).join('')}</tbody></table></div><p>예정 의무 전환일 ${r.mandatoryConversionDate} · 우선주 한 주당 청산우선금액 $1,000 · 연율 배당권 $62.50.</p><p>${esc(r.dividendScope)}</p><svg viewBox="0 0 740 205" role="img" aria-label="미래 평균가격 가정에 따른 우선주 한 주의 기본 전환 보통주 수"><path d="M50 20 V160 H700" fill="none" stroke="#83999c"/>${r.terms.map((t,i)=>`<polyline points="${Array.from({length:111},(_,j)=>150+j*5).map(p=>x(p)+','+y(preferredConversion(t,p))).join(' ')}" fill="none" stroke="${colors[i]}" stroke-width="3"/><text x="${80+i*310}" y="23" fill="${colors[i]}" font-size="13">Series ${t.series} → Class ${t.commonClass}</text>`).join('')}<text x="8" y="47" font-size="12">2.9주</text><text x="8" y="152" font-size="12">2.2주</text><text x="50" y="179" font-size="12">$150</text><text x="647" y="179" font-size="12">$700</text><text x="155" y="200" font-size="12">각 종류의 미래 계약상 평균가격 가정 / 오늘의 종가가 아님</text></svg><div class="control-grid">${r.terms.map(t=>`<label>Class ${t.commonClass} 미래 평균가격 가정 ($)<input data-preferred-series="${t.series}" type="number" value="400" min="1" step="1"><output data-preferred-result="${t.series}"></output></label>`).join('')}</div><p class="chart-caption">${esc(r.scope)}</p><p>${esc(r.capScope)}</p><p>전체 주당 계산에 남은 확인 사항: ${r.remaining.map(esc).join(' · ')}.</p><a href="${esc(r.sourceUrl)}" target="_blank" rel="noopener noreferrer">현재 분기 공시의 우선주·보통주 권리 ↗</a></details>`;
  }
  function bindCapital(c){
    const r=c.valuation?.security?.capitalReview;if(!r)return;
    for(const input of document.querySelectorAll('[data-preferred-series]')){
      const t=r.terms.find(t=>t.series===input.dataset.preferredSeries),out=document.querySelector(`[data-preferred-result="${t.series}"]`);
      const update=()=>{try{out.textContent=`우선주 한 주 → 기본 ${num(preferredConversion(t,Number(input.value)),4)} 보통주 · 누적 미지급 배당·반희석 조정·capped call 정산 별도`;}catch(e){out.textContent=e.message;}};
      input.addEventListener('input',update);update();
    }
  }
'''
s=s.replace('  function render(c){',insert+'  function render(c){')
s=s.replace('${shareEvidence}${rightsEvidence}<div', '${shareEvidence}${rightsEvidence}${capitalEvidence(c)}<div')
s=s.replace('    update();\n  }\n  window.EquityValuation=', '    update();bindCapital(c);\n  }\n  window.EquityValuation=')
s=s.replace('{render,bind,calculate,impliedGrowth};','{render,bind,calculate,impliedGrowth,preferredConversion};')
p.write_text(s)
