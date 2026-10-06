import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const publishedSite = process.argv.includes('--site');
const out = path.join(root, publishedSite ? 'artifacts/site' : 'artifacts/live');
const tempRoot = process.env.EQUITY_TMPDIR || path.join(root, 'data/cache/tmp');
fs.mkdirSync(tempRoot, { recursive: true });
fs.mkdirSync(out, { recursive: true });
const priorReport = path.join(out, 'browser-verification.json');
if (fs.existsSync(priorReport) && JSON.parse(fs.readFileSync(priorReport, 'utf8')).status === 'failed') {
  fs.copyFileSync(priorReport, path.join(out, `browser-verification-failed-${Date.now()}.json`));
}
const profile = fs.mkdtempSync(path.join(tempRoot, 'equity-preview-chrome-'));
const chrome = spawn(process.env.CHROME_BIN || '/usr/bin/google-chrome', [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
  '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
  '--disable-component-update', '--disable-sync', '--disable-extensions',
  '--disable-crash-reporter', '--password-store=basic',
  `--user-data-dir=${profile}`, `--disk-cache-dir=${profile}/cache`,
  `--crash-dumps-dir=${profile}/crashes`, '--remote-debugging-pipe', 'about:blank'
], { stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe'], env: { ...process.env, TMPDIR: profile } });
let nextId = 0, buffer = '', stderr = '', sessionId;
const pending = new Map(), runtimeErrors = [], checks = [], requests = [], checkedLinks = new Set(), pdfFiles = new Set();
chrome.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-6000); });
chrome.stdio[3].on('error', error => {
  for (const item of pending.values()) { clearTimeout(item.timer); item.reject(error); }
  pending.clear();
});
chrome.stdio[4].setEncoding('utf8');
chrome.on('error', error => { for (const item of pending.values()) item.reject(error); });
chrome.on('exit', () => { for (const item of pending.values()) { clearTimeout(item.timer); item.reject(new Error(`Chrome exited: ${stderr}`)); } pending.clear(); });
chrome.stdio[4].on('data', chunk => {
  buffer += chunk.toString();
  let index;
  while ((index = buffer.indexOf('\0')) >= 0) {
    const part = buffer.slice(0, index); buffer = buffer.slice(index + 1);
    if (!part) continue;
    const message = JSON.parse(part);
    if (message.id && pending.has(message.id)) {
      const item = pending.get(message.id); clearTimeout(item.timer); pending.delete(message.id);
      if (message.error) item.reject(new Error(JSON.stringify(message.error)));
      else item.resolve(message.result);
    } else if (message.method === 'Network.requestWillBeSent') requests.push(message.params.request);
    else if (message.method === 'Runtime.exceptionThrown') runtimeErrors.push(message.params.exceptionDetails);
  }
});
function send(method, params = {}, useSession = true) {
  if (chrome.exitCode !== null) return Promise.reject(new Error(`Chrome already exited: ${stderr}`));
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Timeout ${method}: ${stderr}`)); }, 25000);
    pending.set(id, { resolve, reject, timer });
    chrome.stdio[3].write(JSON.stringify({ id, method, params, ...(useSession && sessionId ? { sessionId } : {}) }) + '\0');
  });
}
async function js(expression) {
  const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function ready() {
  for (let i = 0; i < 100; i++) {
    if (await js('document.readyState === "complete" && !!document.querySelector("main h1")')) break;
    await new Promise(resolve => setTimeout(resolve, 60));
  }
  await js('(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return true})()');
  for (const href of await js('[...document.querySelectorAll("a[href]")].map(a=>new URL(a.getAttribute("href"),location.href).href)')) {
    const url = new URL(href);
    if (url.protocol === 'file:') {
      const file = fileURLToPath(url);
      assert.ok(fs.existsSync(file), `Missing linked file: ${file}`);
      checkedLinks.add(file);
    }
  }
}
async function go(hash) {
  await js(`location.hash = ${JSON.stringify(hash)}`);
  await new Promise(resolve => setTimeout(resolve, 80));
  await ready();
}
async function click(selector) {
  const point = await js(`(async()=>{const e=document.querySelector(${JSON.stringify(selector)});e.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));const r=e.getBoundingClientRect();const p={x:r.left+r.width/2,y:r.top+r.height/2};if(!e.contains(document.elementFromPoint(p.x,p.y)))throw new Error('Click target is obscured: '+${JSON.stringify(selector)});return p})()`);
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', ...point, button: 'left', clickCount: 1 });
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...point, button: 'left', clickCount: 1 });
  await new Promise(r => setTimeout(r, 70)); await ready();
}
async function expect(name, expression) {
  assert.equal(await js(expression), true, name); checks.push(name); console.log(`PASS ${name}`);
}
async function viewport(width, height = 1050) {
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  await ready();
}
async function screenshot(name, full = true) {
  await js('document.activeElement?.blur();window.scrollTo({top:0,left:0,behavior:"instant"});new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  const metrics = await send('Page.getLayoutMetrics');
  const size = metrics.cssContentSize;
  const screenshot = await send('Page.captureScreenshot', {
    format: 'png', captureBeyondViewport: full,
    ...(full ? { clip: { x: 0, y: 0, width: Math.max(size.width, await js('innerWidth')), height: size.height, scale: 1 } } : {})
  });
  fs.writeFileSync(path.join(out, name), Buffer.from(screenshot.data, 'base64'));
}
async function screenshotRegion(name, selector) {
  // A nonzero Chrome capture origin can move fixed offscreen accessibility links
  // into the image. Capture the document once, then crop actual pixels locally.
  await screenshot(name,true);
  // Chrome removes scrollbars during full capture, which can slightly reflow
  // the captured document. Retain context around the section rather than cut
  // text at a box edge measured after Chrome restores the scrollbar.
  const rect=await js(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return [Math.floor(r.x+scrollX-18),Math.floor(r.y+scrollY-24),Math.ceil(r.right+scrollX+32),Math.ceil(r.y+scrollY+Math.min(r.height,2300)+24)];})()`);
  const crop=spawnSync('python3',['-c','from PIL import Image; import json,sys; p=sys.argv[1]; r=json.loads(sys.argv[2]); im=Image.open(p); im.crop((max(0,r[0]),max(0,r[1]),min(im.width,r[2]),min(im.height,r[3]))).save(p)',path.join(out,name),JSON.stringify(rect)],{encoding:'utf8'});
  assert.equal(crop.status,0,crop.stderr);
}
async function pdf(name) {
  const result = await send('Page.printToPDF', { printBackground: true, preferCSSPageSize: true, displayHeaderFooter: false });
  fs.writeFileSync(path.join(out, name), Buffer.from(result.data, 'base64'));
  pdfFiles.add(name);
}

try {
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' }, false);
  ({ sessionId } = await send('Target.attachToTarget', { targetId, flatten: true }, false));
  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
  if(!publishedSite && !process.env.RESEARCH_URL){
    await send('Network.setBlockedURLs',{urls:['http://*','https://*']});
    checks.push('Private file workflow tested with HTTP and HTTPS requests blocked');
  }
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1050, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: process.env.RESEARCH_URL || pathToFileURL(path.join(root, publishedSite ? 'site/app/index.html' : 'app/index.html')).href });
  await ready();
  const companies=await js('window.EQUITY_SNAPSHOT.snapshot.companies.filter(c=>c.status==="ready").map(c=>({id:c.id,market:c.market}))');
  if(!publishedSite)await expect('Printed version and page counts use a reserved page-margin box', 'document.body.classList.contains("page-margin-footer") && document.querySelector("#page-footer-style").textContent.includes("counter(pages)")');
  await expect('Registered real companies with a source cutoff', 'document.querySelectorAll("[data-company-row]").length==='+companies.length+' && document.querySelector(".preview-notice").textContent.includes(window.EQUITY_SNAPSHOT.snapshot.asOf)');
  await screenshot('desktop-universe.png'); await pdf('universe.pdf');
  await click('[data-market="US"]');
  const usCount=companies.filter(c=>c.market==='US').length;
  await expect('US filter affects table and scatter', 'document.querySelectorAll("[data-company-row]").length==='+usCount+' && document.querySelectorAll("svg circle").length==='+usCount);
  await click('[data-market="KR"]');
  await expect('Korean filter contains real Korean securities', '[...document.querySelectorAll("[data-company-row]")].every(r=>/^[0-9]{6}$/.test(r.dataset.companyRow))');
  await click('[data-market="ALL"]');
  if (await js('!!document.querySelector("#company-search")')) {
    await js('document.querySelector("#company-search").value="MSFT";document.querySelector("#company-search").dispatchEvent(new Event("input",{bubbles:true}))');
    await expect('Ticker search selects Microsoft in the table and chart', 'document.querySelectorAll("[data-company-row]").length===1 && document.querySelector("[data-company-row]").dataset.companyRow==="MSFT" && document.querySelectorAll("svg circle").length===1');
    await js('document.querySelector("#company-search").value="not-a-company";document.querySelector("#company-search").dispatchEvent(new Event("input",{bubbles:true}))');
    await expect('Empty search is explained without invented companies', 'document.querySelectorAll("[data-company-row]").length===0 && !!document.querySelector(".empty-search")');
    await js('document.querySelector("#company-search").value="";document.querySelector("#company-search").dispatchEvent(new Event("input",{bubbles:true}));document.querySelector("#sector-filter").value="자동차";document.querySelector("#sector-filter").dispatchEvent(new Event("change",{bubbles:true}))');
    await expect('Sector filter uses the coverage classifications', 'document.querySelectorAll("[data-company-row]").length===window.EQUITY_SNAPSHOT.snapshot.companies.filter(c=>c.sector==="자동차").length');
    await js('document.querySelector("#sector-filter").value="ALL";document.querySelector("#sector-filter").dispatchEvent(new Event("change",{bubbles:true}))');
  }
  await click('#candidate-only');
  await expect('Candidate filter uses declared current financial conditions', 'document.querySelectorAll("[data-company-row]").length===window.EQUITY_SNAPSHOT.snapshot.companies.filter(c=>c.assessment.priority==="심층 조사 후보").length');
  await click('#candidate-only');
  await click('[data-company="MU"]');
  await expect('Micron report contains actual dates and currency', 'document.querySelector("h1").textContent==="Micron" && document.querySelector("main").textContent.includes(window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="MU").financials.end) && document.querySelector("main").textContent.includes("십억 달러")');
  if (!publishedSite && await js('!!document.querySelector(".notebook-open")')) {
    await click('.notebook-open');
    await js('window.EquityNotebook.load(window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="MU"))');
    await expect('Local filing corpus opens and verifies without network access', '!document.querySelector(".notebook-editor").hidden && !!document.querySelector("#filing-results article")');
    await js('document.querySelector("#filing-query").value="Sales of DRAM products increased 211%";document.querySelector("#filing-query").dispatchEvent(new Event("input",{bubbles:true}))');
    await expect('Source search finds the exact price and shipment explanation', 'document.querySelectorAll("#filing-results article").length===1 && document.querySelector("#filing-results").textContent.includes("140%") && document.querySelector("#filing-results").textContent.includes("30%")');
    await click('[data-pick-evidence]');
    await js('document.querySelector("#notebook-thesis").value="브라우저 회귀 검사: 가격과 출하량을 분리";document.querySelector("#notebook-countercase").value="제품 믹스 효과가 남음";document.querySelector("#notebook-changes").value="다음 공시의 같은 기간 가격·출하량 확인"');
    await click('[data-notebook="save"]');
    await expect('A research revision preserves its selected filing passage', 'document.querySelector("#notebook-history").textContent.includes("현재 본문과 인용 일치") && JSON.parse(localStorage.getItem("equity-research-notebook-v1"))[0].evidence.length===1');
    await js('(async()=>{window.notebookTestBackup=await window.EquityNotebook.exportText();return true})()');
    await expect('Reimporting an identical notebook does not duplicate records', '(async()=>(await window.EquityNotebook.importText(window.notebookTestBackup))===0)()');
    await expect('Damaged imported notebook is rejected without overwriting history', '(async()=>{const before=localStorage.getItem("equity-research-notebook-v1");const b=JSON.parse(window.notebookTestBackup);b.records[0].thesis="변조";let rejected=false;try{await window.EquityNotebook.importText(JSON.stringify(b))}catch{rejected=true}return rejected&&before===localStorage.getItem("equity-research-notebook-v1")})()');
    const notebookClip=await js('(()=>{const e=document.querySelector(".notebook");const r=e.getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:Math.min(1100,r.height),scale:1}})()');
    const notebookImage=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:notebookClip});
    fs.writeFileSync(path.join(out,'desktop-notebook.png'),Buffer.from(notebookImage.data,'base64'));
    await js('document.querySelector("#notebook-thesis").value="저장 전 초안 복원 검사";document.querySelector("#notebook-thesis").dispatchEvent(new Event("input",{bubbles:true}));location.reload()');await ready();
    await click('.notebook-open');await js('window.EquityNotebook.load(window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="MU"))');
    await expect('In-progress research survives reload without rewriting saved history', 'document.querySelector("#notebook-thesis").value==="저장 전 초안 복원 검사" && JSON.parse(localStorage.getItem("equity-research-notebook-v1"))[0].thesis.includes("브라우저 회귀 검사")');
    await js('localStorage.removeItem("equity-research-notebook-v1");localStorage.removeItem("equity-research-notebook-v1-drafts");location.reload()'); await ready();
    await expect('Ephemeral browser test notes do not enter delivered reports', 'document.querySelector(".notebook-summary").textContent.includes("0개 연구 버전")');
    await expect('Memory analysis separates reporting periods and dividend sensitivity', 'document.querySelector(".industry-research").textContent.includes("9개월과 6개월") && document.querySelectorAll(".memory-cash-comparison tbody tr").length===2 && document.querySelectorAll(".memory-stress tbody tr").length===5');
  }
  await click('[data-evidence="MU"]');
  await expect('Evidence is readable with source period and raw definitions', 'document.querySelector("dialog").open && document.querySelector("#evidence-body").textContent.includes("영업현금") && document.querySelector("#evidence-body a").href.includes("sec.gov")');
  await send('Input.dispatchKeyEvent', { type:'keyDown', key:'Escape', code:'Escape', windowsVirtualKeyCode:27 });
  await send('Input.dispatchKeyEvent', { type:'keyUp', key:'Escape', code:'Escape', windowsVirtualKeyCode:27 });
  await expect('Escape restores evidence trigger focus', '!document.querySelector("dialog").open && document.activeElement.dataset.evidence==="MU"');
  const before=await js('document.querySelector("#scenario").textContent');
  await js('document.querySelector("#cfo-shock").value=-50;document.querySelector("#cfo-shock").dispatchEvent(new Event("input",{bubbles:true}))');
  assert.notEqual(await js('document.querySelector("#scenario").textContent'),before);checks.push('Cash scenario responds to operating-cash changes');
  await js('document.querySelector("#cfo-shock").value=0;document.querySelector("#cfo-shock").dispatchEvent(new Event("input",{bubbles:true}))');
  if (await js('!!window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="MU").dossier')) {
    await expect('Cash bridge reconciles to the reported operating cash flow', 'document.querySelectorAll(".cash-bridge-row").length>5 && document.querySelector("#cash-bridge-body").textContent.includes("미분해")');
    const cashCurrent = await js('document.querySelector("#cash-bridge-body").textContent');
    await click('[data-cash-period="previous"]');
    assert.notEqual(await js('document.querySelector("#cash-bridge-body").textContent'), cashCurrent);
    checks.push('Prior-year cash components are selectable');
    await click('[data-cash-period="current"]');
    if (await js('!!document.querySelector(".receivable-panel")')) {
      await expect('Receivable proxies expose both averaging choices and limits', 'document.querySelectorAll(".ar-bar-row").length===4 && document.querySelector(".receivable-panel").textContent.includes("실제 회수일수나 연체일수가 아니다") && document.querySelector(".ar-reading").textContent.includes("1.7일")');
      await expect('Management attribution is distinct from independent evidence', 'document.querySelector(".ar-notes").textContent.includes("경영진") && document.querySelector(".ar-notes").textContent.includes("독립 증거는 아니다")');
      await click('.ar-source-details summary');
      await expect('Opening balance and comparative period retain their filing identities', 'document.querySelector(".ar-source-details").open && document.querySelector(".ar-source-details").textContent.includes("2025-08-28") && document.querySelector(".ar-source-details").textContent.includes("0000723125-26-000015") && document.querySelectorAll(".ar-archive").length>=5');
      await click('.ar-source-details summary');
    }
    const requirement = await js('document.querySelector("#valuation-result").textContent');
    await js('document.querySelector("#valuation-discount").value=14;document.querySelector("#valuation-discount").dispatchEvent(new Event("input",{bubbles:true}))');
    assert.notEqual(await js('document.querySelector("#valuation-result").textContent'), requirement);
    checks.push('Required equity cash responds to the discount assumption');
    await expect('Historical cash scenarios show source anchors and non-probabilistic cases', 'document.querySelectorAll(".valuation-cases tbody tr").length===3 && !!document.querySelector(".valuation-cash-chart") && document.querySelector(".valuation-workspace").textContent.includes("확률")');
    await js('document.querySelector("#valuation-burden").value=20;document.querySelector("#valuation-burden").dispatchEvent(new Event("input",{bubbles:true}))');
    await expect('Additional compensation and lease burden is an explicit assumption', 'document.querySelector(".valuation-selected").textContent.includes("추가 부담 20%")');
    await click('#valuation-reset');
    await expect('Initial assumptions restore without silently rounding filing ratios', '(()=>{const v=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="MU").valuation;return Math.abs(Number(document.querySelector("#valuation-cfo").value)/100-v.defaults.cfoMargin)<1e-12 && Number(document.querySelector("#valuation-discount").value)===12;})()');
    const impliedBefore=await js('document.querySelector(".valuation-implied").textContent');
    await js('document.querySelector("#valuation-horizon").value=15;document.querySelector("#valuation-horizon").dispatchEvent(new Event("input",{bubbles:true}))');
    assert.notEqual(await js('document.querySelector(".valuation-implied").textContent'),impliedBefore);checks.push('Forecast horizon changes conditional implied growth and terminal dependence');
    await click('#valuation-reset');
    await expect('Three filing observations remain separate from generated causes', 'document.querySelectorAll(".observation-card").length===3 && document.querySelector(".computed-observations").textContent.includes("현금 사용") && document.querySelectorAll(".observation-card .claim-evidence a").length===3');
    await expect('Cross-border comparison exposes unequal reporting periods', 'document.querySelector(".memory-pair").textContent.includes("누적 기간")');
    if (await js('!!window.EQUITY_SNAPSHOT.localReviews?.MU && window.EQUITY_SNAPSHOT.localReviews.MU.status!=="stale"')) {
      await expect('Private model commentary has traceable facts and explicit review limits', 'document.querySelectorAll(".claim-evidence a").length>0 && document.querySelector(".local-review").textContent.includes("독립 승인")');
      if (await js('window.EQUITY_SNAPSHOT.localReviews.MU.schemaVersion===2')) {
        await expect('Every model sentence has its own exact-text review', 'document.querySelectorAll("[data-research-role]").length===4 && document.querySelectorAll(".local-review .sentence-review blockquote").length===4');
        await expect('Synthetic evaluation is labelled separately from real company accuracy', 'document.querySelector(".local-review .evaluation-details").textContent.includes("실제 기업 정확도")');
        await expect('Uncleared notes are collapsed while computed facts stay visible', 'window.EQUITY_SNAPSHOT.localReviews.MU.displayEligible ? !document.querySelector(".local-review .withheld-notes") : !document.querySelector(".local-review .withheld-notes").open');
      }
    }
  }
  if(!publishedSite){
    await expect('Micron recast segment path reconciles tax-aware funding and government support', 'document.querySelectorAll(".operating-segments tbody tr").length===5 && document.querySelector(".operating-model").textContent.includes("5.203bn") && document.querySelector(".operating-model").textContent.includes("정부지원 차감 전") && document.querySelector(".operating-cash-anchors").textContent.includes("자료 미확인")');
    await expect('Micron headline uses the same source-bound business cash assumptions', 'document.querySelector(".operating-price-conditions").textContent.includes("6년차") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="MU").operatingModel.bridge.periods.every(p=>p.residual===0)');
    const micronBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=[...document.querySelectorAll("[data-operating]")].find(x=>x.dataset.operating==="0.marginEnd");e.value=Number(e.value)-10;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),micronBefore);checks.push('Micron cloud-margin downside changes cash without changing all segment margins');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Micron funding assumptions reopen under the exact filing context', 'document.querySelector("#operating-message").textContent.includes("복원") && document.querySelector(".operating-model").textContent.includes("장기 미지급 세금")');
    await js('localStorage.removeItem("equity-operating-path-v1-MU")');await click('#operating-reset');
    await viewport(390);await expect('Micron five-segment cash path fits mobile viewport', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-micron-operating-path.png','.operating-model');await viewport(1440);
    await screenshotRegion('desktop-micron-operating-path.png','.operating-model');
  }
  await screenshot('desktop-micron.png'); await pdf('micron.pdf');
  for(const {id} of companies.filter(c=>c.id!=='MU')){
    await go('company/'+id);
    await expect('Individual real report '+id, 'document.querySelector("main").textContent.includes('+JSON.stringify(id)+') && !!document.querySelector("#scenario") && !/NaN|undefined/.test(document.querySelector("main").textContent)');
    if(!publishedSite)assert.equal(await js('!!document.querySelector(".business-drivers") && !!document.querySelector(".annual-panel") && !!document.querySelector("#analysis-peer")'),true,'Analysis missing for '+id);
    if(!publishedSite)assert.equal(await js('!!document.querySelector(".capital-review") && !!document.querySelector(".capital-balances") && !!document.querySelector(".trailing-year") && !!document.querySelector(".research-case") && !!document.querySelector(".valuation-workspace")'),true,'Capital, cash scenarios or research case missing for '+id);
    if(!publishedSite)await expect('Archived filing corpus identity and hash '+id, '(async()=>{const c=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==='+JSON.stringify(id)+');const b=await window.EquityNotebook.load(c);return b.company===c.id&&b.passages.length===c.narrative.passageCount})()');
  }
  if(!publishedSite){
    await go('company/207940');
    await expect('Discontinued cash is shown by period and blocks price inference', 'document.querySelector(".cash-scope").textContent.includes("중단영업") && document.querySelectorAll(".cash-scope tbody tr").length===3 && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="207940").valuation.priceRequirement===null && document.querySelector(".valuation-security").textContent.includes("계속영업")');
    await expect('Mixed business scope cannot create an automatic relative cash advantage', 'window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="207940").researchCase.peers.every(p=>p.differences.cashMargin===null && p.conclusion.includes("중단영업"))');
    await screenshot('desktop-biologics.png'); await pdf('samsung-biologics.pdf');
    await go('company/009150');
    await expect('Electromechanics source signs remain disputed in all three cash periods', 'document.querySelectorAll(".cash-sign-review > .table-wrap tbody tr").length===3 && document.querySelector(".cash-sign-review").textContent.includes("-2,881,532") && document.querySelector(".cash-sign-review").textContent.includes("+2,881,532") && document.querySelector(".cash-sign-review").textContent.includes("+475,808") && document.querySelector(".cash-sign-review").textContent.includes("-556,263") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="009150").cashScope.signReview.observations.every(r=>r.selectedValue===null)');
    await expect('Sign conflicts cannot create a continuing cash estimate or a price requirement', 'window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="009150").valuation.priceRequirement===null && document.querySelector(".valuation-security").textContent.includes("부호")');
    await js('window.dispatchEvent(new Event("beforeprint"))');
    await expect('Original narrative tables expand for printing without replacing dashes by zero', 'document.querySelector(".cash-sign-review details").open && document.querySelector(".cash-sign-source").textContent.includes("577,306") && document.querySelectorAll(".cash-sign-source").length===2');
    await js('window.dispatchEvent(new Event("afterprint"))');
    await expect('Printing restores the source table disclosure state', '!document.querySelector(".cash-sign-review details").open');
    await viewport(390);await expect('Both conflicting source signs remain visible together on mobile', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".cash-sign-review > .table-wrap td:nth-child(3)").getBoundingClientRect().right<innerWidth');await screenshotRegion('mobile-electromechanics-scope.png','.cash-sign-review');await viewport(1440);
    await screenshotRegion('desktop-electromechanics-scope.png','.cash-sign-review');await pdf('samsung-electromechanics.pdf');
    await go('company/AVGO');
    await expect('Broadcom allocates disclosed costs before comparing segment and consolidated profits', 'window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="AVGO").business.reconciliations.operatingIncome.unexplained===0 && document.querySelector(".segment-period-reconciliations").textContent.includes("16.96")');
    await expect('Thirteen reviewed period bridges retain ten exact reconciliations and three source gaps', 'window.EQUITY_SNAPSHOT.snapshot.companies.filter(c=>c.segmentHistory?.segments).length===13 && window.EQUITY_SNAPSHOT.snapshot.companies.filter(c=>c.segmentHistory?.status==="ready").length===10 && window.EQUITY_SNAPSHOT.snapshot.companies.filter(c=>c.segmentHistory?.status==="ready").every(c=>Object.values(c.segmentHistory.reconciliations).every(r=>r.residual===0 && r.periods.every(p=>p.residual===0)))');
    await go('company/AAPL');
    await expect('Apple distinguishes product revenue from geographic operating profits', 'document.querySelectorAll(".business-products tbody tr").length===5 && document.querySelectorAll(".business-segments tbody tr").length===5 && document.querySelector(".business-segments").textContent.includes("-40.72")');
    await expect('Trailing-year numbers preserve the annual plus current less prior calculation', 'document.querySelector(".trailing-year").textContent.includes("2025-06-29") && document.querySelector(".trailing-year").textContent.includes("전년 누적")');
    await go('company/005930');
    await expect('Samsung segment residual and intercompany basis remain visible', 'document.querySelector(".business-segments").textContent.includes("미대사 차이 0.04") && document.querySelector(".business-segments").textContent.includes("내부거래")');
    await expect('Samsung trailing profit gap is displayed in won instead of rounding to zero', 'document.querySelector(".segment-period-reconciliations").textContent.includes("147,921,000,000 원") && document.querySelector(".segment-period-bridge").textContent.includes("미대사 항목 포함")');
    await screenshotRegion('desktop-korean-period-bridge.png','.segment-period-bridge');
    await go('company/068270');
    await expect('Small source precision gaps remain visible for all three Korean reporting periods', 'document.querySelector(".segment-period-reconciliations").textContent.includes("-600 원") && document.querySelector(".segment-period-bridge details").textContent.includes("-291") && document.querySelector(".segment-period-bridge details a").href.includes("dart.fss.or.kr")');
    await go('company/329180');
    await expect('Shipbuilder merger perimeter is explicit beside the trailing-year segment table', 'document.querySelector(".segment-period-bridge").textContent.includes("2025년 12월 1일") && document.querySelector(".segment-period-bridge").textContent.includes("합병 전후 보고 범위")');
    await go('company/NVDA');
    await expect('Conflicting dividends are shown as a data gap', 'document.querySelector(".capital-balances").textContent.includes("상충 수치")');
    await go('company/MSFT');
    await expect('Authored business reasoning retains filing sources and interpretation limits', 'document.querySelector(".business-insight").textContent.includes("OpenAI") && document.querySelectorAll(".insight-sources a").length===3 && document.querySelector(".business-insight").textContent.includes("로컬 모델 생성문")');
    await click('#insight-to-notebook');
    await js('window.EquityNotebook.load(window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="MSFT"))');
    await expect('Source-backed case becomes an editable local draft without automatic approval', 'document.querySelector("#notebook-thesis").value.includes("회사는") && document.querySelectorAll("#notebook-evidence article").length===3 && document.querySelector("#notebook-opinion").value==="관찰" && document.querySelector(".notebook-summary").textContent.includes("0개 연구 버전")');
    await js('document.querySelector("#notebook-thesis").value="내 기존 연구";document.querySelector("#notebook-thesis").dispatchEvent(new Event("input",{bubbles:true}))');
    await click('#insight-to-notebook');
    await expect('Starting from a source case preserves an existing authored draft', 'document.querySelector("#notebook-thesis").value==="내 기존 연구"');
    await js('localStorage.removeItem("equity-research-notebook-v1-drafts");location.reload()');await ready();
    if(await js('!!window.EQUITY_SNAPSHOT.filingReadings?.MSFT?.draft')) {
      await expect('Filing readings keep original quotes separate from unreviewed meanings', 'document.querySelector(".filing-reading").textContent.includes("원문 직접 연결") && document.querySelectorAll(".reading-observation blockquote").length>0 && [...document.querySelectorAll(".reading-observation blockquote")].every(e=>window.EQUITY_SNAPSHOT.filingReadings.MSFT.input.passages.some(p=>p.text===e.textContent))');
      await js('document.querySelector(".reading-draft").open=true;document.querySelector(".filing-reading").scrollIntoView()');
      await expect('Actual source audit remains tied to the exact model record', 'window.EQUITY_SNAPSHOT.filingReadings.MSFT.editorialReview.status==="revision_required" && document.querySelector(".filing-reading").textContent.includes("수정 필요")');
      await screenshotRegion('desktop-filing-reading.png','.filing-reading');
      await click('#reading-to-notebook');
      await js('window.EquityNotebook.load(window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="MSFT"))');
      await expect('A local source reading imports as an unapproved editable draft', 'document.querySelector("#notebook-thesis").value.startsWith("로컬 모델 미검토 초안") && document.querySelector("#notebook-countercase").value==="" && document.querySelector("#notebook-opinion").value==="관찰" && document.querySelectorAll("#notebook-evidence article").length>0');
      await js('localStorage.removeItem("equity-research-notebook-v1-drafts");location.reload()');await ready();
    }
    await expect('Both sides of a business comparison retain their own current filing sources', 'document.querySelectorAll(".source-pair-grid article").length===2 && [...document.querySelectorAll(".source-pair-grid a")].filter(a=>a.href.startsWith("https://")).length>=2 && document.querySelector(".source-pair").textContent.includes("상대 선호 미확정")');
    await expect('Fresh calculation exports keep all current company model inputs current', 'Object.keys(window.EQUITY_SNAPSHOT.coverageReviews).length===window.EQUITY_SNAPSHOT.snapshot.companies.filter(c=>c.status==="ready").length && Object.values(window.EQUITY_SNAPSHOT.coverageReviews).every(r=>r.recordHash && !["stale","failed"].includes(r.status))');
    await expect('All companies have current source-bound local research selections', 'Object.values(window.EQUITY_SNAPSHOT.questionSelections).length===window.EQUITY_SNAPSHOT.snapshot.companies.filter(c=>c.status==="ready").length && Object.values(window.EQUITY_SNAPSHOT.questionSelections).every(r=>r.status==="selected" && r.choice.primary!==r.choice.secondary)');
    await expect('Two selected designs distinguish authored research plans from factual causes', 'document.querySelectorAll(".question-card").length===2 && document.querySelector(".question-selection").textContent.includes("정해진 연구 설계") && document.querySelector(".question-selection").textContent.includes("원인으로 확인된 사실은 아닙니다") && document.querySelectorAll(".question-card a").length>0');
    await expect('Research view links observations to a frozen follow-up condition', 'document.querySelector(".research-view").textContent.includes("방향 예측 없음") && document.querySelector(".research-view").textContent.includes("가격이 요구하는 조건")');
    await click('[data-nav="tracking/MSFT"]');
    await expect('Company condition history opens without unrelated companies', 'document.querySelectorAll(".record-card").length>0 && [...document.querySelectorAll(".record-card")].every(e=>e.textContent.includes("MSFT"))');
    await go('company/MSFT');
    if(await js('!!window.EQUITY_SNAPSHOT.coverageReviews?.MSFT?.notes')) {
      await expect('Company-wide local notes have four individually reviewed roles', 'document.querySelectorAll("[data-coverage-role]").length===4 && document.querySelector(".coverage-review").textContent.includes("독립 금융 해석 승인")');
      await expect('Coverage development gate is visible even when it fails', 'document.querySelector(".coverage-review .evaluation-details").textContent.includes("합성") && document.querySelector(".coverage-review .evaluation-details").textContent.includes("오류 허용")');
    }
    await expect('Microsoft business segments reconcile to reported consolidated revenue', 'document.querySelectorAll(".business-segments tbody tr").length===3 && document.querySelector(".business-segments").textContent.includes("331.84")');
    await expect('Microsoft separates finance lease principal from noncash additions', 'document.querySelector(".business-leases").textContent.includes("3.10") && document.querySelector(".business-leases").textContent.includes("24.61") && document.querySelector(".business-leases").textContent.includes("다시 빼지 않는다")');
    const priceBefore=await js('document.querySelector("#valuation-result").textContent');
    await js('document.querySelector("#valuation-discount").value=15;document.querySelector("#valuation-discount").dispatchEvent(new Event("input",{bubbles:true}))');
    assert.notEqual(await js('document.querySelector("#valuation-result").textContent'),priceBefore);checks.push('Microsoft price requirements respond to explicit assumptions');
    await click('#valuation-reset');
    if(await js('window.EQUITY_SNAPSHOT.coverageReviews?.MSFT?.reviewRounds?.length>1'))await expect('Original and revised model sentences remain available separately', '!!document.querySelector(".coverage-rounds") && document.querySelectorAll(".coverage-rounds section").length===window.EQUITY_SNAPSHOT.coverageReviews.MSFT.reviewRounds.length');
    if(await js('window.EQUITY_SNAPSHOT.coverageReviews?.MSFT?.editorialFindings?.length>0'))await expect('Extra sentence findings keep an erroneous self-review from adoption', '!window.EQUITY_SNAPSHOT.coverageReviews.MSFT.displayEligible && !!document.querySelector(".coverage-review .editorial-hold")');
    await expect('Company print filename carries its own identity and date', 'document.title.includes("MSFT") && document.title.includes(window.EQUITY_SNAPSHOT.snapshot.asOf)');
    await expect('Research judgment includes named segment changes and peer trade-offs', 'document.querySelectorAll(".research-segment-change tbody tr").length===3 && document.querySelector(".research-tradeoffs").textContent.includes("Alphabet") && !!document.querySelector(".research-peer-chart")');
    await expect('Research journal keeps future conditions separate from prediction scoring', 'document.querySelector(".research-journal").textContent.includes("예측 실패로 채점하지") && document.querySelectorAll(".research-revisions li").length>0');
    await expect('Business cash source bridge reconciles and retains independent segment controls', 'document.querySelectorAll(".operating-segments tbody tr").length===3 && document.querySelectorAll("[data-operating]").length===19 && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="MSFT").operatingModel.bridge.residual===0');
    await expect('Browser business cash calculation matches the independently executed Python output', '(()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="MSFT").operatingModel,r=window.EquityOperatingModel.calculate(m,m.defaults);return Math.abs(r.price-m.initial.price)<1e-8&&Math.abs(r.terminal.cash-m.initial.terminal.cash)<.01&&r.years.every((v,i)=>Math.abs(v.cash-m.initial.years[i].cash)<.01);})()');
    const operatingBefore=await js('document.querySelector("#operating-result").textContent');
    await click('#operating-observed');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),operatingBefore);checks.push('Independent business growth assumptions change the cash path');
    await click('#operating-save');
    await js('location.reload()');await ready();
    await expect('Saved business assumptions reopen under the same source hash', `document.querySelector("#operating-message").textContent.includes("복원") && Number(document.querySelector('[data-operating="1.growthStart"]').value)>20`);
    await click('#operating-note');
    await expect('Operating scenario moves exact assumptions and sources into the research notebook', 'document.querySelector("#notebook-assumptions").value.includes("정확한 가정 JSON") && document.querySelectorAll("#notebook-evidence article").length===6');
    const operatingBundle=await js('window.EquityNotebook.exportText()');
    await js('localStorage.removeItem("equity-research-notebook-v1-drafts");localStorage.removeItem("equity-operating-path-v1-MSFT");location.reload()');await ready();
    await js(`window.EquityNotebook.importText(${JSON.stringify(operatingBundle)})`);
    await click('.notebook-open');
    await click('[data-notebook="restore-operating"]');
    await expect('Exported research notes restore the exact business scenario on a cleared browser', `document.querySelector("#operating-message").textContent.includes("연구 노트") && Number(document.querySelector('[data-operating="1.growthStart"]').value)>20`);
    await js('document.querySelector("#notebook-assumptions").value=document.querySelector("#notebook-assumptions").value.replace(window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="MSFT").operatingModel.evidenceHash,"0".repeat(64))');
    await click('[data-notebook="restore-operating"]');
    await expect('Changed source hashes cannot silently restore an old operating scenario', 'document.querySelector("#notebook-status").textContent.includes("버전이 현재 사업 모델과 다릅니다")');
    await js('localStorage.removeItem("equity-research-notebook-v1-drafts");localStorage.removeItem("equity-operating-path-v1-MSFT");location.reload()');await ready();
    await screenshotRegion('desktop-operating-path.png','.operating-model');
    await screenshot('desktop-microsoft.png');await pdf('microsoft.pdf');
    await js('document.querySelector("#analysis-peer").value="005930";document.querySelector("#analysis-peer").dispatchEvent(new Event("change",{bubbles:true}))');
    await expect('Cross-border comparison changes both facts and comparability cautions', 'document.querySelector("#analysis-peer-body").textContent.includes("삼성전자") && document.querySelector(".comparison-cautions").textContent.includes("회계 기준 차이")');
    await go('company/005380');
    await expect('Hyundai keeps financial services separate and cash residual unexplained', 'document.querySelector(".business-finance").textContent.includes("-3.56") && document.querySelector(".business-unresolved").textContent.includes("-2.76") && document.querySelector(".business-unresolved").textContent.includes("단정하지 않습니다")');
    await expect('Hyundai equity requirements wait for preferred and minority interests', 'document.querySelector(".valuation-security").textContent.includes("우선주") && document.querySelector("#valuation-result").textContent.includes("계산 보류")');
    await screenshot('desktop-hyundai.png');await pdf('hyundai.pdf');
    await go('company/AMZN');
    await expect('Amazon cash path separates six-month growth from trailing-year business amounts', 'document.querySelector(".operating-segments").textContent.includes("최근 반기 전년 대비") && document.querySelector(".operating-heading").textContent.includes("최근 1년") && !document.querySelector(".operating-model").textContent.includes("Azure")');
    await expect('Amazon retains negative cash instead of inventing a positive price', 'document.querySelector("#operating-result").textContent.includes("계산 보류") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="AMZN").operatingModel.initial.price===null && document.querySelector(".operating-source-bridge").textContent.includes("-28.83")');
    await expect('Amazon browser and Python agree on every cash year and inverse price requirement', '(()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="AMZN").operatingModel,r=window.EquityOperatingModel.calculate(m,m.defaults);return r.price===null&&Math.abs(r.requiredTerminalCash-m.initial.requiredTerminalCash)<.01&&r.years.every((v,i)=>Math.abs(v.cash-m.initial.years[i].cash)<.01);})()');
    await expect('Amazon exposes the three original cash periods and facility repayments', 'document.querySelectorAll(".operating-fact-periods").length===14 && document.querySelector(".operating-model").textContent.includes("리스·시설금융 원금")');
    await expect('Amazon keeps unquantified energy periods separate from the known half-year gain', 'document.querySelector(".operating-normalization").textContent.includes("금액 미공시") && document.querySelector(".operating-normalization").textContent.includes("0.599") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="AMZN").operatingModel.energyNormalization.trailingGain===null');
    await click('#operating-known-gain');
    await expect('Known-gain exclusion changes future profit and cash while preserving the reported CFO bridge', '(()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="AMZN").operatingModel,a=structuredClone(m.defaults);a.excludedProfitStart=a.excludedProfitEnd=m.energyNormalization.knownPartRatio;const r=window.EquityOperatingModel.calculate(m,a);return Math.abs(r.years[0].excludedProfit-599000000)<.001 && Math.abs(r.years[0].cash+48053192504.53079)<.001 && m.bridge.reportedCfo===161403000000 && document.querySelector("#operating-result").textContent.includes("제외 후 영업이익");})()');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Amazon normalization assumptions restore at full precision under the current model hash', 'Number(document.querySelector("[data-operating=excludedProfitStart]").dataset.exact)===window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="AMZN").operatingModel.energyNormalization.knownPartRatio && document.querySelector("#operating-message").textContent.includes("복원")');
    await js('localStorage.removeItem("equity-operating-path-v1-AMZN")');await click('#operating-reset');
    await js(`document.querySelector('[data-operating="capexEnd"]').value=5;document.querySelector('[data-operating="capexEnd"]').dispatchEvent(new Event("input",{bubbles:true}))`);
    await expect('A low-investment Amazon assumption exposes replacement-investment caution', 'document.querySelector(".operating-caution").textContent.includes("설비 순현금 취득") && !document.querySelector(".operating-caution").textContent.includes("${")');
    await click('#operating-reset');
    await screenshotRegion('desktop-amazon-operating-path.png','.operating-model');await pdf('amazon.pdf');
    await go('company/000270');
    await expect('Kia single-business model uses Korean currency and preserves all warranty periods', 'document.querySelectorAll(".operating-segments tbody tr").length===1 && document.querySelectorAll(".warranty-ledger tbody tr").length===3 && document.querySelector(".operating-heading").textContent.includes("조 원") && document.querySelector("#operating-result").textContent.includes("KRW") && !document.querySelector(".operating-model").textContent.includes("USD")');
    await expect('Kia separates accrual, cash reversal, and provision use', 'document.querySelector(".warranty-ledger").textContent.includes("4.965") && document.querySelector(".warranty-ledger").textContent.includes("4.054") && document.querySelector(".warranty-ledger").textContent.includes("4.017") && document.querySelector(".operating-model").textContent.includes("유형·무형 현금 취득")');
    await expect('Kia browser and Python agree on every warranty cash amount and price', '(()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="000270").operatingModel,r=window.EquityOperatingModel.calculate(m,m.defaults);return Math.abs(r.price-m.initial.price)<1e-8&&Math.abs(r.requiredTerminalCash-m.initial.requiredTerminalCash)<.05&&r.years.every((v,i)=>Math.abs(v.cash-m.initial.years[i].cash)<.05&&Math.abs(v.warrantyUse-m.initial.years[i].warrantyUse)<.05);})()');
    await expect('Kia inverse price table identifies one business margin while retaining all other cash assumptions', 'document.querySelectorAll(".operating-implied-margins tbody tr").length===1 && !!document.querySelector("[data-implied-margin]") && document.querySelector(".operating-implied-margins").textContent.includes("동시에 적용하지")');
    await click('[data-implied-margin]');
    await expect('Applying the required margin reproduces the observed market proxy and preserves warranty assumptions', '(()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="000270").operatingModel,a=structuredClone(m.defaults);a.segments[0].marginEnd=Number(Array.from(document.querySelectorAll("[data-operating]")).find(e=>e.dataset.operating==="0.marginEnd").dataset.exact);return Math.abs(window.EquityOperatingModel.calculate(m,a).equityValue/m.security.marketCapProxy-1)<1e-9 && Number(document.querySelector("[data-operating=warrantyAccrual]").dataset.exact)===m.defaults.warrantyAccrual && document.querySelector("#operating-message").textContent.includes("마진만 대입");})()');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Inverse-derived business assumptions restore at full precision', 'document.querySelector("#operating-message").textContent.includes("복원") && Math.abs(Number(Array.from(document.querySelectorAll("[data-operating]")).find(e=>e.dataset.operating==="0.marginEnd").dataset.exact)-window.EquityOperatingModel.marginRequirements(window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="000270").operatingModel,window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="000270").operatingModel.defaults).rows[0].requiredMargin)<1e-12');
    await js('localStorage.removeItem("equity-operating-path-v1-000270")');await click('#operating-reset');
    const kiaBefore=await js('document.querySelector("#operating-result").textContent');
    await click('#operating-warranty-stress');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),kiaBefore);checks.push('Warranty and financing stress changes Kia cash without inventing segment profits');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Korean business scenario restores its warranty parameters under the source hash', 'document.querySelector("#operating-message").textContent.includes("복원") && document.querySelector(".operating-selected").textContent.includes("완성차")');
    await js('localStorage.removeItem("equity-operating-path-v1-000270");location.reload()');await ready();
    await send('Emulation.setEmulatedMedia',{media:'print'});
    await js('document.querySelector("main").focus()');
    await expect('Print hides the focused main outline without removing keyboard focus', 'document.activeElement===document.querySelector("main") && getComputedStyle(document.querySelector("main")).outlineStyle==="none"');
    await send('Emulation.setEmulatedMedia',{media:''});
    await expect('A mathematically zero working-capital amount is not displayed as negative zero', '[...document.querySelectorAll(".operating-years td")].every(e=>e.textContent.trim()!=="-0")');
    await screenshotRegion('desktop-kia-operating-path.png','.operating-model');await pdf('kia.pdf');
    await go('company/TSLA');
    await expect('Tesla product gross margins remain distinct from unallocated operating costs', 'document.querySelectorAll(".operating-segments tbody tr").length===5 && document.querySelector(".operating-segments").textContent.includes("매출총이익률") && document.querySelectorAll(".operating-common-costs input").length===7 && document.querySelector(".operating-profit-bridge").textContent.includes("2.44")');
    await expect('Tesla browser matches all Python cash and common-cost years including terminal', '(()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="TSLA").operatingModel,r=window.EquityOperatingModel.calculate(m,m.defaults);return r.price===null && [...r.years,r.terminal].every((y,i)=>["cash","grossProfit","operatingIncome","research","selling","otherOperating","minority"].every(k=>Math.abs(y[k]-[...m.initial.years,m.initial.terminal][i][k])<.001)) && Math.abs(r.requiredTerminalCash-m.initial.requiredTerminalCash)<.01;})()');
    await click('#operating-credit-stress');
    await expect('Credit shutdown preserves common operating costs instead of assuming cost relief', 'Number(document.querySelectorAll(".operating-segment-inputs fieldset")[1].querySelector("input").value)===-100 && document.querySelector("#operating-message").textContent.includes("금액은 유지") && Number(document.querySelector("[data-operating=researchStart]").dataset.exact)>window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="TSLA").operatingModel.defaults.researchStart');
    await click('#operating-investment-stress');
    await expect('Disclosed investment floor stress includes intangible cash without double counting SpaceX', 'document.querySelector(".operating-investment-context").textContent.includes("250억") && document.querySelector(".operating-years").textContent.includes("25.01") && document.querySelector("[data-operating=workingCapital]").value==="0"');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Tesla restores product and common-cost assumptions under the filing hash', 'document.querySelector("#operating-message").textContent.includes("복원") && Number(document.querySelector("[data-operating=capexStart]").value)>24');
    await js('localStorage.removeItem("equity-operating-path-v1-TSLA")');await click('#operating-reset');
    await viewport(360);
    await expect('Tesla common costs and product chart fit the mobile viewport', 'document.documentElement.scrollWidth<=innerWidth+1 && !!document.querySelector(".operating-profit-bridge svg")');
    await viewport(1440);
    await screenshotRegion('desktop-tesla-operating-path.png','.operating-model');await pdf('tesla.pdf');
    await go('company/AAPL');
    await expect('Apple product margins preserve nine-month growth, annual cash anchors and unquantified lease payments', 'document.querySelectorAll(".operating-segments tbody tr").length===2 && document.querySelector(".operating-segments").textContent.includes("최근 9개월") && document.querySelector(".operating-cash-anchors").textContent.includes("0.538") && document.querySelector(".operating-cash-anchors").textContent.includes("0.563") && document.querySelector(".operating-cash-anchors").textContent.includes("자료 미확인")');
    await expect('Apple gross-profit path does not inherit Tesla credit controls or half-year labels', '!document.querySelector("#operating-credit-stress") && document.querySelector(".operating-profit-bridge").textContent.includes("전년 9개월") && [...document.querySelectorAll(".operating-selected")].some(e=>e.textContent.includes("영업외 순손익"))');
    await expect('Apple headline uses the issuer terminal cash path instead of historical generic cash ratios', 'document.querySelector(".operating-price-conditions").textContent.includes("6년차") && document.querySelector(".research-operating-basis").textContent.includes("기업별 사업 현금") && !document.querySelector(".research-brief").textContent.includes("과거 비율 중앙값")');
    const appleBase=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=[...document.querySelectorAll("[data-operating]")].find(x=>x.dataset.operating==="0.marginEnd");e.value=Number(e.value)-1;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),appleBase);checks.push('Apple product margin stress changes the cash path separately from service margins');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Apple exact product assumptions survive reload with source-bound tariff and lease context', 'document.querySelector("#operating-message").textContent.includes("복원") && document.querySelector(".operating-model").textContent.includes("관세 환급")');
    await js('localStorage.removeItem("equity-operating-path-v1-AAPL")');await click('#operating-reset');
    await viewport(390);await expect('Apple cash-anchor table and common-cost controls fit mobile viewport', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-apple-operating-path.png','.operating-model');await viewport(1440);
    await screenshotRegion('desktop-apple-operating-path.png','.operating-model');await pdf('apple.pdf');
    await go('company/GOOGL');
    await expect('Alphabet distinguishes designated shares, rounded outstanding shares and stock-payable dividends', 'document.querySelector(".valuation-capital-contract").textContent.includes("지정 수량") && document.querySelector(".valuation-capital-contract").textContent.includes("$62.50") && document.querySelector(".valuation-capital-contract").textContent.includes("현금·주식·혼합") && document.querySelectorAll("[data-preferred-series]").length===2');
    await js('{const e=document.querySelector("[data-preferred-series=A]");e.value=440;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    await expect('Preferred conversion assumptions affect only the relevant stock class and preserve the equity hold', 'document.querySelector("[data-preferred-result=A]").textContent.includes("2.2727") && document.querySelector("[data-preferred-result=B]").textContent.includes("2.5") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="GOOGL").valuation.security.status==="unresolved"');
    await js('{const e=document.querySelector("[data-preferred-series=A]");e.value=0;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    await expect('Invalid preferred conversion price does not display a fabricated conversion rate', 'document.querySelector("[data-preferred-result=A]").textContent.includes("양수")');
    await js('{const e=document.querySelector("[data-preferred-series=A]");e.value=400;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    await expect('Alphabet keeps loss-making Other Bets and corporate costs in the cash path', 'document.querySelectorAll(".operating-segments tbody tr").length===3 && document.querySelector(".operating-years").textContent.includes("본사") && Number(document.querySelector("[data-operating=\\"2.marginEnd\\"]").dataset.exact)<-5');
    await expect('Alphabet adds only the separately reported lease advance and reconciles every original period', '(()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="GOOGL").operatingModel;return m.facts.leaseCash.value===3361000000 && m.bridge.periods.every(p=>p.residual===0&&p.incomeResidual===0) && m.initial.price===null && document.querySelector(".operating-security-hold").textContent.includes("권리 배분");})()');
    const alphabetBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=corporateEnd]");e.value=Number(e.value)+1;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),alphabetBefore);checks.push('Alphabet corporate-cost scenario changes cash without bypassing security allocation');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Alphabet restores the exact corporate-cost assumption and keeps the source-bound loss segment', 'document.querySelector("#operating-message").textContent.includes("복원") && Number(document.querySelector("[data-operating=corporateEnd]").value)>5 && Number(document.querySelector("[data-operating=\\"2.marginEnd\\"]").dataset.exact)<-5');
    await js('localStorage.removeItem("equity-operating-path-v1-GOOGL")');await click('#operating-reset');
    await viewport(390);await expect('Alphabet corporate controls fit the mobile viewport', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-alphabet-operating-path.png','.operating-model');await viewport(1440);
    await screenshotRegion('desktop-alphabet-operating-path.png','.operating-model');await pdf('alphabet.pdf');
    await go('company/META');
    await expect('Meta reconciles equal cash entitlements without assigning identical voting value', 'document.querySelector(".valuation-rights-evidence").textContent.includes("2,205,128,509") && document.querySelector(".valuation-rights-evidence").textContent.includes("342,377,716") && document.querySelector(".operating-rights-assumption").textContent.includes("의결권") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="META").valuation.security.shares.value===2547506225');
    await expect('Meta retains Reality Labs loss and uses an explicit tax assumption instead of a one-time benefit', '(()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="META").operatingModel;return m.anchors.currentReportedTaxRate<0 && m.defaults.tax===.21 && m.bridge.reportedCfo===130301000000 && m.initial.price===null && m.initial.requiredTerminalCash>0 && Number(document.querySelector("[data-operating=\\"1.marginEnd\\"]").dataset.exact)<-8;})()');
    await js('{const e=document.querySelector("[data-operating=tax]");e.value=16;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Meta tax stress survives reload with the original tax-benefit context', 'Number(document.querySelector("[data-operating=tax]").dataset.exact)===.16 && document.querySelector(".operating-model").textContent.includes("CAMT")');
    await js('localStorage.removeItem("equity-operating-path-v1-META")');await click('#operating-reset');
    await viewport(390);await expect('Meta entitlement table fits the mobile viewport', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await screenshotRegion('desktop-meta-operating-path.png','.operating-model');await pdf('meta.pdf');
    await go('compare/advertising-ai-cash');
    await expect('Advertising pair exposes corporate costs and each loss segment without clipping', 'document.querySelectorAll(".pair-input-side").length===2 && !!document.querySelector("[data-pair-key=corporateEnd]") && document.querySelector(".pair-rights-assumption").textContent.includes("A·B주") && Number(document.querySelector("[data-pair-side=\\"1\\"][data-pair-key=\\"1.marginEnd\\"]").min)===-2000');
    const advertisingBefore=await js('document.querySelector("#pair-result").textContent');
    await js('{const e=document.querySelector("[data-pair-key=corporateEnd]");e.value=Number(e.value)+1;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#pair-result").textContent'),advertisingBefore);checks.push('Paired corporate-cost change alters cash while retaining Alphabet price hold');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Advertising pair preserves the complete corporate-cost assumption in a saved judgment', 'document.querySelector("#pair-message").textContent.includes("복원") && Number(document.querySelector("[data-pair-key=corporateEnd]").value)>5');
    await click('#pair-reset');await viewport(390);await expect('Advertising paired assumptions fit the mobile viewport', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await pdf('comparison-advertising.pdf');
    await js('localStorage.removeItem("equity-paired-research-v1")');
    await go('compare/memory-price-volume');
    await expect('Memory comparison exposes five Micron segments and the single Korean business with different periods', 'document.querySelectorAll(".pair-input-side").length===2 && document.querySelector(".pair-summary").textContent.includes("사업 실적 기간 상이") && document.querySelectorAll(".pair-input-side fieldset").length===6 && document.querySelector(".pair-security-hold").textContent.includes("반기 이후")');
    await expect('Memory cash comparisons do not turn an unresolved Korean share count into a price advantage', '(()=>{const p=window.EQUITY_SNAPSHOT.snapshot.peerStudies.find(x=>x.id==="memory-price-volume").operatingComparison;return p.status==="research_workspace" && p.sides[1].initial.requiredCashMargin===null && p.sides[1].initial.marginGap===null && Number.isFinite(p.sides[1].initial.terminalCashMargin);})()');
    const memoryBefore=await js('document.querySelector("#pair-result").textContent');
    await js('{const e=[...document.querySelectorAll("[data-pair-key]")].find(x=>x.dataset.pairSide==="1"&&x.dataset.pairKey==="0.marginEnd");e.value=Number(e.value)-10;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#pair-result").textContent'),memoryBefore);checks.push('Korean memory margin decline changes cash without creating a current-price requirement');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Memory comparison restores source-bound assumptions and capital-event cautions', 'document.querySelector("#pair-message").textContent.includes("복원") && document.querySelector("#pair-print-note").textContent.includes("유통주식수")');
    await viewport(390);await expect('Cross-border memory comparison fits mobile without merging currencies', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".pair-bases").textContent.includes("KRW") && document.querySelector(".pair-bases").textContent.includes("USD")');await screenshotRegion('mobile-memory-comparison.png','.pair-summary');await viewport(1440);await pdf('comparison-memory.pdf');
    await js('localStorage.removeItem("equity-paired-research-v1")');
    await go('compare/accelerator-contract-cash');
    await expect('Accelerator comparison preserves five distinct segments, different periods and conditional AMD dilution', 'document.querySelectorAll(".pair-input-side fieldset").length===5 && document.querySelector(".pair-summary").textContent.includes("사업 실적 기간 상이") && document.querySelector(".pair-security-hold").textContent.includes("워런트")');
    const acceleratorBefore=await js('document.querySelector("#pair-result").textContent');
    await js('{const e=[...document.querySelectorAll("[data-pair-key]")].find(x=>x.dataset.pairSide==="1"&&x.dataset.pairKey==="capexEnd");e.value=Number(e.value)+2;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#pair-result").textContent'),acceleratorBefore);checks.push('AMD reinvestment stress changes paired cash without inventing a current-price requirement');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Accelerator saved judgment retains source-bound customer contracts and exact assumptions', 'document.querySelector("#pair-message").textContent.includes("복원") && document.querySelector("#pair-print-note").textContent.includes("워런트") && Number([...document.querySelectorAll("[data-pair-key]")].find(x=>x.dataset.pairSide==="1"&&x.dataset.pairKey==="capexEnd").value)>6');
    await viewport(390);await expect('Accelerator contract comparison fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await pdf('comparison-accelerators.pdf');
    await js('localStorage.removeItem("equity-paired-research-v1")');
    await go('compare/electronics-mix');
    await expect('Electronics comparison keeps product gross profits distinct from four Korean segment profits', 'document.querySelectorAll(".pair-input-side fieldset").length===6 && document.querySelector(".pair-summary").textContent.includes("사업 실적 기간 상이") && !!document.querySelector("[data-pair-key=eliminationEnd]") && document.querySelector(".pair-inputs").textContent.includes("내부매출")');
    const electronicsBefore=await js('document.querySelector("#pair-result").textContent');
    await js('{const e=document.querySelector("[data-pair-key=eliminationEnd]");e.value=15;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#pair-result").textContent'),electronicsBefore);checks.push('Consolidation sales removal changes paired cash and working capital');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Paired consolidation assumptions survive source-bound journal reload', 'document.querySelector("#pair-message").textContent.includes("복원") && Number(document.querySelector("[data-pair-key=eliminationEnd]").value)===15 && document.querySelector("#pair-print-note").textContent.includes("내부매출")');
    await viewport(390);await expect('Electronics comparison fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await pdf('comparison-electronics.pdf');
    await js('localStorage.removeItem("equity-paired-research-v1")');
    await go('compare/auto-demand');
    await expect('Paired workspace retains both currencies and source-specific business controls', 'document.querySelectorAll(".pair-input-side").length===2 && document.querySelector(".pair-bases").textContent.includes("USD") && document.querySelector(".pair-bases").textContent.includes("KRW") && document.querySelectorAll("#pair-study-picker option").length===window.EQUITY_SNAPSHOT.snapshot.peerStudies.length && document.title.includes("auto-demand")');
    await expect('Both paired margin requirements match the separately executed Python calculations', '(()=>{const s=window.EQUITY_SNAPSHOT.snapshot,p=s.peerStudies.find(s=>s.id==="auto-demand").operatingComparison;return p.sides.every(c=>{const m=s.companies.find(x=>x.id===c.company).operatingModel,r=window.EquityComparisonWorkspace.summarize(m,m.defaults);return ["terminalCashMargin","requiredCashMargin","marginGap","explicitCoverage","valueToMarket"].every(k=>r[k]===null?c.initial[k]===null:Math.abs(r[k]-c.initial[k])<1e-10);});})()');
    const pairInitial=await js('document.querySelector("#pair-result").textContent');
    await js('document.querySelectorAll(".pair-input-side details").forEach(e=>e.open=true)');
    await js('const w=document.querySelector("[data-pair-side=\\"1\\"][data-pair-key=warrantyUseEnd]");w.value=Number(w.value)+1;w.dispatchEvent(new Event("input",{bubbles:true}))');
    assert.notEqual(await js('document.querySelector("#pair-result").textContent'),pairInitial);checks.push('Kia warranty assumptions change the paired price requirement without converting currencies');
    await js('document.querySelector("#pair-discount").value=14;document.querySelector("#pair-terminal").value=2.5');await click('#pair-apply-common');
    await expect('Common discount assumptions update both issuers and retain separate operating assumptions', '[...document.querySelectorAll("[data-pair-key=discount]")].every(e=>Number(e.dataset.exact)===.14) && [...document.querySelectorAll("[data-pair-key=terminal]")].every(e=>Number(e.dataset.exact)===.025) && document.querySelector("#pair-message").textContent.includes("별도로 유지")');
    const pairValid=await js('localStorage.getItem("equity-paired-research-v1")');
    await js('document.querySelector("#pair-terminal").value=""');await click('#pair-apply-common');
    assert.equal(await js('localStorage.getItem("equity-paired-research-v1")'),pairValid);checks.push('A blank common assumption cannot overwrite the last valid comparison');
    await click('#pair-reset');await click('#pair-use-reading');await click('#pair-save');
    await expect('A saved paired judgment preserves both filings and an explicit countercase', '(()=>{const s=JSON.parse(localStorage.getItem("equity-paired-research-v1")),r=s.records[0];return s.records.length===1 && r.sides.every(v=>v.evidence.length>=3) && r.notes.countercase.length>40 && document.querySelector("#pair-message").textContent.includes("이전 판단");})()');
    const pairBundle=await js('window.EquityComparisonWorkspace.exportText()');
    await js('localStorage.removeItem("equity-paired-research-v1");location.reload()');await ready();
    await js(`window.EquityComparisonWorkspace.importText(${JSON.stringify(pairBundle)})`);
    await js('location.reload()');await ready();
    await expect('A cleared browser restores exact paired assumptions and notes from the exported bundle', 'document.querySelector("#pair-message").textContent.includes("복원") && document.querySelector("#pair-note-countercase").value.length>40 && JSON.parse(localStorage.getItem("equity-paired-research-v1")).records.length===1');
    await js(`window.EquityComparisonWorkspace.importText(${JSON.stringify(pairBundle)})`);
    await expect('Repeated paired imports do not duplicate existing versions', 'JSON.parse(localStorage.getItem("equity-paired-research-v1")).records.length===1');
    await expect('A changed bundle checksum is rejected without changing existing paired history', `(async()=>{const before=localStorage.getItem("equity-paired-research-v1"),v=JSON.parse(${JSON.stringify(pairBundle)});v.records[0].notes.thesis+="tampered";try{await window.EquityComparisonWorkspace.importText(JSON.stringify(v));return false;}catch(e){return e.message.includes("해시")&&localStorage.getItem("equity-paired-research-v1")===before;}})()`);
    await js('const s=JSON.parse(localStorage.getItem("equity-paired-research-v1"));s.drafts["auto-demand"].comparisonHash="0".repeat(64);localStorage.setItem("equity-paired-research-v1",JSON.stringify(s));location.reload()');await ready();
    await expect('An outdated comparison draft remains archived while current assumptions reopen', 'document.querySelector("#pair-message").textContent.includes("이전 초안은 보존") && document.querySelector("#pair-note-thesis").value==="" && JSON.parse(localStorage.getItem("equity-paired-research-v1")).drafts["auto-demand"].comparisonHash==="0".repeat(64)');
    await click('#pair-use-reading');
    await expect('First editing after a source change preserves the stale paired draft as history', 'JSON.parse(localStorage.getItem("equity-paired-research-v1")).records.some(r=>r.id==="stale-"+"0".repeat(64))');
    await js('location.reload()');await ready();await js('document.querySelector(".pair-history").open=true');
    await click('[data-pair-restore="stale-'+ '0'.repeat(64)+'"]');
    await expect('Historical assumptions with another source version cannot replace the current comparison', 'document.querySelector("#pair-message").textContent.includes("자동 적용하지") && document.querySelector("#pair-note-thesis").value.length>40');
    await js('localStorage.setItem("equity-paired-research-v1","corrupt-saved-notes");location.reload()');await ready();await click('#pair-use-reading');
    await expect('Malformed saved comparison notes are preserved instead of being silently reset', 'localStorage.getItem("equity-paired-research-v1")==="corrupt-saved-notes"');
    await js('localStorage.removeItem("equity-paired-research-v1");location.reload()');await ready();
    await viewport(360);await expect('Paired price comparison and judgment inputs fit a narrow mobile screen', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelectorAll(".pair-input-side").length===2');
    await expect('Both paired numeric columns are visible without horizontal panning on mobile', '[...document.querySelectorAll(".pair-values td")].every(e=>e.getBoundingClientRect().right<=innerWidth && e.getBoundingClientRect().left>=0)');
    await screenshotRegion('mobile-paired-auto.png','.comparison-workspace');await viewport(1440);
    await expect('Printing opens selected business assumptions and restores the original screen state', '(()=>{const e=document.querySelector(".pair-selected");window.dispatchEvent(new Event("beforeprint"));const opened=e.open;window.dispatchEvent(new Event("afterprint"));return opened&&!e.open;})()');
    await screenshotRegion('desktop-paired-auto.png','.comparison-workspace');await pdf('comparison-auto.pdf');
    await go('compare/cloud-usage');
    await expect('Cloud pair keeps negative Amazon cash visible and preserves separate business controls', 'document.querySelectorAll(".pair-input-side fieldset").length===6 && document.querySelector(".pair-values").textContent.includes("계산 보류") && document.querySelector(".source-pair").textContent.includes("에너지")');
    await expect('Cloud comparison includes source-bound Amazon profit exclusions as editable assumptions', 'document.querySelectorAll("[data-pair-key=excludedProfitStart]").length===1 && document.querySelectorAll("[data-pair-key=excludedProfitEnd]").length===1 && document.querySelector(".pair-selected").textContent.includes("별도 제외 영업이익")');
    await screenshotRegion('desktop-paired-cloud.png','.comparison-workspace');await pdf('comparison-cloud.pdf');
    await go('compare/semiconductor-equipment');
    await expect('Equipment comparison preserves service scope and unequal filing periods', 'document.querySelector(".source-pair").textContent.includes("9개월") && document.querySelector(".source-pair").textContent.includes("구형 공정용 장비") && document.querySelector(".pair-summary").textContent.includes("사업 실적 기간 상이") && document.querySelectorAll(".pair-input-side fieldset").length===4');
    await expect('Equipment cash controls keep Lam segment gross profit and warranty accrual separate', 'document.querySelector(".pair-inputs").textContent.includes("보증 순발생 되돌림") && document.querySelector(".pair-inputs").textContent.includes("비배분 기타 매출원가") && !!document.querySelector("[data-pair-key=researchEnd]")');
    const equipmentBefore=await js('document.querySelector("#pair-result").textContent');
    await js('{const e=document.querySelector("[data-pair-key=warrantyUseEnd]");e.value=3;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#pair-result").textContent'),equipmentBefore);checks.push('Lam warranty settlement changes paired cash without inventing standalone service profit');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Equipment comparison restores the saved warranty assumption and recast argument', 'document.querySelector("#pair-message").textContent.includes("복원") && Number(document.querySelector("[data-pair-key=warrantyUseEnd]").dataset.exact)===.03 && document.querySelector("#pair-print-note").textContent.includes("재작성")');
    await viewport(390);await expect('Equipment assumption tables fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);
    await pdf('comparison-equipment.pdf');
    await js('localStorage.removeItem("equity-paired-research-v1")');
    await go('company/018260');
    await expect('SDS IT and logistics cash separate retirement cost and net contract assets', 'document.querySelectorAll(".operating-segments tbody tr").length===2 && document.querySelectorAll(".operating-services-evidence tbody tr").length===6 && document.querySelector(".operating-services-evidence").textContent.includes("123.7") && document.querySelector(".operating-services-evidence").textContent.includes("-64.86") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="018260").operatingModel.bridge.reportedCfo===1235571475659');
    const sdsBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=\\"0.growthStart\\"]");e.value=8;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),sdsBefore);checks.push('SDS service growth consumes source-bound working capital and changes cash');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('SDS saved business assumptions retain the issued-convertible price hold', 'Number(document.querySelector("[data-operating=\\"0.growthStart\\"]").dataset.exact)===.08 && document.querySelector("#operating-message").textContent.includes("복원") && !!document.querySelector(".operating-security-hold") && document.querySelector(".valuation-security").textContent.includes("전환사채")');
    await js('localStorage.removeItem("equity-operating-path-v1-018260")');await click('#operating-reset');
    await expect('SDS preserves issued convertible principal, actual common count and source dates', 'document.querySelectorAll(".valuation-capital-claims tbody tr").length===4 && document.querySelector(".valuation-capital-claims").textContent.includes("6,777,777") && document.querySelector(".valuation-capital-claims").textContent.includes("2032-04-30") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="018260").valuation.security.shares.value===77350186');
    await expect('Convertible rights hold SDS prices while cash sensitivity remains editable', 'window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="018260").valuation.priceRequirement===null && document.querySelector(".valuation-security").textContent.includes("전환") && document.querySelector("#valuation-result").textContent.includes("계산 보류")');
    await js('{const e=document.querySelector("#valuation-growth");e.value=20;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    await expect('Changing cash growth cannot bypass SDS unreviewed conversion terms', 'document.querySelector(".valuation-selected").textContent.includes("20%") && document.querySelector(".valuation-cases").textContent.includes("계산 보류")');
    await click('#valuation-reset');
    await viewport(390);await expect('SDS convertible and business tables fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-sds-capital.png','.valuation-capital-claims');await screenshotRegion('mobile-sds-operating.png','.operating-services-evidence');await viewport(1440);await pdf('samsung-sds.pdf');
    await go('company/NOW');
    await expect('ServiceNow gross profit and commission costs preserve their accounting scope', 'document.querySelector(".operating-segments").textContent.includes("매출총이익률") && document.querySelectorAll(".software-commissions tbody tr").length===3 && document.querySelectorAll(".software-coupons tbody tr").length===6 && document.querySelector(".operating-software-evidence").textContent.includes("312.23") && document.querySelector(".operating-software-evidence").textContent.includes("81일") && document.querySelector(".software-coupons").textContent.includes("4.25%") && document.querySelector(".operating-software-evidence").textContent.includes("3.98%") && document.querySelector(".operating-common-costs").textContent.includes("판매·마케팅비")');
    await expect('ServiceNow default acquisition outlay is retained instead of silently normalized away', 'window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="NOW").operatingModel.initial.years[0].cash===-8599172500 && document.querySelector(".operating-software-evidence").textContent.includes("-5.213")');
    await click('#operating-acquisition-sensitivity');
    await expect('Acquisition-only sensitivity preserves commissions and makes its unsupported growth assumption explicit', 'Math.abs(Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)-1580000000/14732000000)<1e-12 && document.querySelector("#operating-result").textContent.includes("인수 없는 성장 지속") && document.querySelector("#operating-message").textContent.includes("부채 이자는 바꾸지")');
    await click('#operating-reset');
    const nowBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{for(const k of ["capexStart","capexEnd"]){const e=document.querySelector("[data-operating="+k+"]");e.value=10;e.dispatchEvent(new Event("input",{bubbles:true}));}}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),nowBefore);checks.push('ServiceNow explicit reinvestment assumption changes cash without rewriting observed CFO');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('ServiceNow saves the selected acquisition intensity and keeps source cash', 'Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===.1 && document.querySelector("#operating-message").textContent.includes("복원") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="NOW").operatingModel.bridge.reportedCfo===5308000000');
    await js('localStorage.removeItem("equity-operating-path-v1-NOW")');await click('#operating-reset');
    await viewport(390);await expect('ServiceNow commission, debt and customer-funding tables fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-servicenow-operating.png','.operating-software-evidence');await viewport(1440);await pdf('servicenow.pdf');
    await go('company/INTC');
    await expect('Intel warrants and escrow rights hold price without adding potential shares to outstanding stock', 'document.querySelector(".valuation-capital-claims").textContent.includes("241,000,000") && document.querySelector(".valuation-capital-claims").textContent.includes("순현금 또는 순주식") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="INTC").valuation.security.marketCapProxy===null && document.querySelector(".valuation-security").textContent.includes("에스크로")');
    await expect('Foundry bridge preserves adverse product contribution and unallocated residual', '[...document.querySelectorAll(".business-driver-chart g[data-value]")].map(e=>Number(e.dataset.value)).join(",")==="-5488,1800,-830,-8,-4526" && document.querySelector(".business-drivers").textContent.includes("원인 미배분")');
    await screenshotRegion('desktop-intel-drivers.png','.business-drivers');await pdf('intel.pdf');
    await go('company/QCOM');
    await expect('Qualcomm separates licensing and chip pretax profit from investment and tax gains', 'document.querySelectorAll(".operating-segments tbody tr").length===3 && document.querySelector(".operating-segments").textContent.includes("세전이익률") && document.querySelectorAll(".licensing-costs tbody tr").length===6 && document.querySelectorAll(".licensing-tax tbody tr").length===3 && document.querySelector(".operating-licensing-evidence").textContent.includes("0.008") && !document.querySelector("[data-operating=netInterest]")');
    const qcomBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=corporateEnd]");e.value=15;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),qcomBefore);checks.push('Qualcomm costs retained outside segment margins change pretax cash once');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Qualcomm saves the source-bound pretax cost assumption without an extra interest input', 'Number(document.querySelector("[data-operating=corporateEnd]").dataset.exact)===.15 && document.querySelector("#operating-message").textContent.includes("복원") && document.querySelector(".operating-years").textContent.includes("세전이익")');
    await js('localStorage.removeItem("equity-operating-path-v1-QCOM")');await click('#operating-reset');
    await click('#operating-observed');
    await expect('Qualcomm out-of-range small nonreportable business growth is not silently clamped', 'document.querySelector("#operating-message").textContent.includes("가정 범위를 벗어") && [...document.querySelectorAll("[data-operating]")].filter(e=>e.dataset.operating.endsWith("growthStart")).every(e=>Number(e.value)===0)');
    await viewport(390);await expect('Qualcomm pretax and cash source tables fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-qualcomm-operating.png','.operating-licensing-evidence');await viewport(1440);
    await expect('QCT automotive growth remains separate from total revenue decline and different periods', 'document.querySelectorAll(".business-driver-chart").length===3 && [...document.querySelectorAll(".business-driver-chart")][0].textContent.includes("-1,242") && [...document.querySelectorAll(".business-driver-chart")][1].textContent.includes("+381") && [...document.querySelectorAll(".business-driver-chart")][2].textContent.includes("+560") && document.querySelector(".business-drivers").textContent.includes("9개월 누적")');
    await viewport(360);
    await expect('Business driver charts retain all source numbers within mobile view', 'document.documentElement.scrollWidth<=innerWidth+1 && [...document.querySelectorAll(".business-driver-chart")].every(e=>e.getBoundingClientRect().right<=innerWidth)');
    await screenshotRegion('mobile-qualcomm-drivers.png','.business-drivers');await viewport(1440);
    await screenshotRegion('desktop-qualcomm-drivers.png','.business-drivers');await pdf('qualcomm.pdf');
    await go('company/COST');
    await expect('Costco membership stays in real segments and uses matched 36-week periods', 'document.querySelectorAll(".warehouse-membership-chart g[data-membership]").length===2 && Number(document.querySelector(".warehouse-membership-chart g").dataset.membership)===4057000000 && document.querySelector(".warehouse-fees").textContent.includes("2025-05-11")');
    await expect('Costco historical renewal and lease proxies remain explicit', 'document.querySelector(".warehouse-renewal-group").textContent.includes("7~18개월") && document.querySelector(".warehouse-working").textContent.includes("-2.352") && document.querySelector(".warehouse-lease-group").textContent.includes("자료 미확인")');
    const costcoBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=capexEnd]");e.value=3;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),costcoBefore);checks.push('Costco warehouse reinvestment changes the business cash path');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Costco restores assumptions without changing observed membership revenue', 'Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===.03 && document.querySelector("#operating-message").textContent.includes("복원") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="COST").operatingModel.retailEvidence.membership.value===5781000000');
    await js('localStorage.removeItem("equity-operating-path-v1-COST")');await click('#operating-reset');
    await viewport(390);await expect('Costco source chart remains usable on mobile', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".warehouse-chart-scroll").scrollWidth>document.querySelector(".warehouse-chart-scroll").clientWidth');await screenshotRegion('mobile-costco-operating.png','.operating-warehouse-evidence');await viewport(1440);
    await screenshotRegion('desktop-costco-operating.png','.operating-warehouse-evidence');await pdf('costco.pdf');
    await go('company/271560');
    await expect('Orion preserves small acquisition arithmetic and exact subsequent capital split', 'document.querySelector(".operating-cash-anchors").textContent.includes("-174,000 KRW") && document.querySelector(".confectionery-investments").textContent.includes("82.5") && document.querySelector(".confectionery-investments").textContent.includes("42.5")');
    await expect('Orion geographic sales use matched half years without independent margins', 'document.querySelectorAll(".confectionery-market-chart g[data-current]").length===3 && [...document.querySelectorAll(".confectionery-market-chart g[data-current]")].reduce((s,e)=>s+Number(e.dataset.current),0)===1823941014000 && document.querySelector(".confectionery-geography-group").textContent.includes("134원")');
    await expect('Orion retains acquisition arithmetic, July capital and price hold', 'document.querySelector(".confectionery-acquisition-scope").textContent.includes("-174,000") && document.querySelector(".confectionery-investments").textContent.includes("2026-07-24") && document.querySelector(".confectionery-post-balance").textContent.includes("주당·역산은 보류") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="271560").operatingModel.initial.price===null');
    const orionBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=capexEnd]");e.value=12;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),orionBefore);checks.push('Orion independent reinvestment assumption recomputes cash');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Orion restores cash assumption and keeps source-bound price hold', 'Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===.12 && document.querySelector("#operating-message").textContent.includes("복원") && document.querySelector("#operating-result").textContent.includes("보류") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="271560").operatingModel.bridge.reportedCfo===667317383300');
    await js('localStorage.removeItem("equity-operating-path-v1-271560")');await click('#operating-reset');
    await viewport(390);await expect('Orion country chart scrolls within mobile width', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".confectionery-chart-scroll").scrollWidth>document.querySelector(".confectionery-chart-scroll").clientWidth');await screenshotRegion('mobile-orion-operating.png','.operating-confectionery-evidence');await viewport(1440);
    await screenshotRegion('desktop-orion-operating.png','.operating-confectionery-evidence');await pdf('orion.pdf');
    await go('company/ADI');
    await expect('ADI has four revenue markets but one real profit segment', 'document.querySelectorAll(".analog-market-chart g[data-current]").length===4 && [...document.querySelectorAll(".analog-market-chart g[data-current]")].reduce((s,e)=>s+Number(e.dataset.current),0)===10805627000 && document.querySelector(".operating-segments").textContent.includes("단일")');
    await expect('ADI retains source disagreement and different interim cash detail', 'document.querySelector(".analog-sale-scope").textContent.includes("24.2") && document.querySelector(".analog-sale-scope").textContent.includes("24.4") && document.querySelector(".analog-scope-group").textContent.includes("1,592.044") && document.querySelector(".analog-cash-periods").textContent.includes("-0.941")');
    const adiBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=capexEnd]");e.value=8;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),adiBefore);checks.push('ADI reinvestment assumptions recompute source-bound cash');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('ADI restores researcher assumptions and preserves reported cash', 'Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===.08 && document.querySelector("#operating-message").textContent.includes("복원") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="ADI").operatingModel.bridge.reportedCfo===5545325000');
    await js('localStorage.removeItem("equity-operating-path-v1-ADI")');await click('#operating-reset');
    await viewport(390);await expect('ADI market chart scrolls without breaking mobile width', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".analog-chart-scroll").scrollWidth>document.querySelector(".analog-chart-scroll").clientWidth');await screenshotRegion('mobile-adi-operating.png','.operating-analog-evidence');await viewport(1440);
    await screenshotRegion('desktop-adi-operating.png','.operating-analog-evidence');await pdf('analog-devices.pdf');
    await go('company/TXN');
    await expect('TI reconciles CFO, separate investment incentives and already-included tax benefits', '[...document.querySelectorAll(".incentive-cash-chart g[data-value]")].map(e=>Number(e.dataset.value)).join(",")==="8667000000,5355000000,6534000000,4922000000" && document.querySelector(".incentive-definition").textContent.includes("이중 계산")');
    await expect('TI preserves three fiscal windows, corporate items and annual depreciation benefit', 'document.querySelector(".incentive-periods").textContent.includes("2025-12-31") && document.querySelector(".incentive-periods").textContent.includes("0.301") && document.querySelector(".incentive-future-scope").textContent.includes("0.353") && document.querySelector(".incentive-working").textContent.includes("6.445")');
    const tiBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=capexEnd]");e.value=10;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),tiBefore);checks.push('TI gross reinvestment assumption changes future cash');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('TI restores exact source-bound assumptions without changing historical incentive cash', 'Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===.1 && document.querySelector("#operating-message").textContent.includes("복원") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="TXN").operatingModel.incentiveEvidence.issuerFreeCash===6534000000');
    await js('localStorage.removeItem("equity-operating-path-v1-TXN")');await click('#operating-reset');
    await viewport(390);await expect('TI incentive evidence scrolls inside its mobile container', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".incentive-chart-scroll").scrollWidth>document.querySelector(".incentive-chart-scroll").clientWidth');await screenshotRegion('mobile-ti-operating.png','.operating-incentive-evidence');await viewport(1440);
    await screenshotRegion('desktop-ti-operating.png','.operating-incentive-evidence');await pdf('texas-instruments.pdf');
    await go('company/CRM');
    await expect('Salesforce removes strategic gains from operating cash and retains contract and ROU costs', '[...document.querySelectorAll(".salesforce-cash-chart g[data-value]")].map(e=>Number(e.dataset.value)).join(",")==="5633000000,-3171000000,1951000000,1173000000,1763000000,621000000,7970000000"');
    await expect('Salesforce financing obligations are not silently narrowed to lease principal', 'document.querySelector(".salesforce-financing-scope").textContent.includes("584") && document.querySelector(".salesforce-financing-scope").textContent.includes("367") && document.querySelector(".salesforce-financing-scope").textContent.includes("217") && document.querySelector(".operating-security-hold").textContent.includes("금융의무") && document.querySelector(".operating-implied-margins").textContent.includes("2.17억")');
    await expect('Salesforce debt table retains current floating rate and undrawn facility without an invented coupon', 'document.querySelectorAll(".salesforce-debt tbody tr").length===16 && document.querySelector(".salesforce-debt").textContent.includes("4.24%") && document.querySelector(".salesforce-debt").textContent.includes("미사용") && document.querySelector(".operating-salesforce-evidence").textContent.includes("1.824275")');
    await js('{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="CRM").operatingModel;for(const key of ["capexStart","capexEnd"]){const el=document.querySelector("[data-operating="+key+"]");el.value=m.salesforceEvidence.reinvestmentExcludingAcquisitionRatio*100;el.dispatchEvent(new Event("input",{bubbles:true}));}}');
    await expect('Salesforce acquisition exclusion can make cash positive but does not release its model scope hold', 'document.querySelector(".operating-years").textContent.includes("배분 가정 현금") && !document.querySelector("#operating-result").textContent.includes("가치를 영으로 확정") && document.querySelector(".operating-security-hold").textContent.includes("2.17억")');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Salesforce preserves editable cash assumptions and the financing scope hold after reload', 'document.querySelector("#operating-message").textContent.includes("복원") && document.querySelector(".operating-security-hold").textContent.includes("금융의무")');
    await js('localStorage.removeItem("equity-operating-path-v1-CRM")');await click('#operating-reset');
    await viewport(390);await expect('Salesforce funding table and graph fit the mobile page', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".salesforce-chart-scroll").scrollWidth>document.querySelector(".salesforce-chart-scroll").clientWidth');await screenshotRegion('mobile-salesforce-operating.png','.salesforce-financing-scope');await viewport(1440);await pdf('salesforce.pdf');
    await go('company/ADBE');
    await expect('Adobe current revenue groups preserve service losses and all shared expenses', '[...document.querySelectorAll(".creative-profit-chart g[data-value]")].map(e=>Number(e.dataset.value)).join(",")==="22904000000,298000000,-23000000,-4694000000,-7147000000,-1918000000,-149000000,9271000000" && document.querySelector(".operating-segments").textContent.includes("단일 보고부문")');
    await expect('Adobe contract amortization stays in selling costs and broader cash accretion is not repeated', 'document.querySelector(".creative-amortization").textContent.includes("282") && document.querySelector(".creative-amortization").textContent.includes("828") && document.querySelector(".creative-amortization").textContent.includes("818") && document.querySelector(".creative-amortization").textContent.includes("-10") && document.querySelector(".creative-working").textContent.includes("2,081") && document.querySelector(".creative-working").textContent.includes("815")');
    await expect('Adobe broad purchases retain incompatible period amounts and hold price despite positive cash', 'document.querySelector(".creative-purchase-scope").textContent.includes("134") && document.querySelector(".creative-purchase-scope").textContent.includes("216") && document.querySelector(".creative-purchase-scope").textContent.includes("지출로 채택 보류") && document.querySelector(".operating-security-hold").textContent.includes("무형·기타") && (()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="ADBE").operatingModel;return m.facts.otherPurchases.value===null && m.facts.otherPurchases.arithmeticValue===-2000000 && m.initial.price===null && m.initial.years[0].cash>0})()');
    const adobeBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=capexEnd]");e.value=12;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),adobeBefore);checks.push('Adobe acquisition intensity changes the future cash path');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Adobe saves exact source-bound acquisition assumptions and preserves historical CFO', 'Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===.12 && document.querySelector("#operating-message").textContent.includes("복원") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="ADBE").operatingModel.bridge.reportedCfo===10806000000');
    await js('localStorage.removeItem("equity-operating-path-v1-ADBE")');await click('#operating-reset');
    await viewport(390);await expect('Adobe costs chart scrolls locally on mobile', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".creative-chart-scroll").scrollWidth>document.querySelector(".creative-chart-scroll").clientWidth');await screenshotRegion('mobile-adobe-operating.png','.operating-creative-evidence');await viewport(1440);
    await screenshotRegion('desktop-adobe-operating.png','.operating-creative-evidence');await pdf('adobe.pdf');
    await go('company/011070');
    await expect('Innotek reconciles profit and cash changes without equating them', 'document.querySelectorAll(".operating-segments tbody tr").length===3 && [...document.querySelectorAll(".manufacturing-cash-chart g[data-value]")].map(e=>Number(e.dataset.value)).join(",")==="878810000000,321874000000,21306000000,-812372000000,-11576000000,398042000000"');
    await expect('Innotek preserves conflicting customer scope and the million-won depreciation difference', 'document.querySelector(".manufacturing-customer-scope").textContent.includes("8,841,475") && document.querySelector(".manufacturing-customer-scope").textContent.includes("8,888,208") && document.querySelector(".manufacturing-customer-scope").textContent.includes("46,733") && document.querySelector(".operating-manufacturing-evidence").textContent.includes("차이는 1백만원") && document.querySelector(".operating-manufacturing-evidence").textContent.includes("27,237")');
    const innotekBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=capexEnd]");e.value=7;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),innotekBefore);checks.push('Innotek separate reinvestment assumption changes the cash path');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Innotek keeps exact assumptions across save and reload without overwriting source cash', 'Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===.07 && document.querySelector("#operating-message").textContent.includes("복원") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="011070").operatingModel.bridge.reportedCfo===850634000000');
    await js('localStorage.removeItem("equity-operating-path-v1-011070")');await click('#operating-reset');
    await viewport(390);await expect('Innotek cash chart scrolls locally without expanding the mobile page', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".manufacturing-chart-scroll").scrollWidth>document.querySelector(".manufacturing-chart-scroll").clientWidth');await screenshotRegion('mobile-innotek-operating.png','.operating-manufacturing-evidence');await viewport(1440);
    await screenshotRegion('desktop-innotek-operating.png','.operating-manufacturing-evidence');await pdf('lg-innotek.pdf');
    await go('company/ORCL');
    await expect('Oracle financing-component customer advances remain separate from recurring cloud earnings', 'document.querySelector(".business-insight").textContent.includes("금융요소") && document.querySelector(".business-insight").textContent.includes("선급금") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="ORCL").valuation.security.status==="unresolved" && document.querySelector("#valuation-result").textContent.includes("계산 보류")');
    await expect('Oracle source periods separate financing cash adjustments from gross receipts', 'document.querySelectorAll(".operating-capacity-evidence > .table-wrap")[0].querySelectorAll("tbody tr").length===3 && document.querySelector(".operating-capacity-evidence").textContent.includes("11.363") && document.querySelector(".operating-capacity-evidence").textContent.includes("11.74") && document.querySelector(".operating-capacity-evidence").textContent.includes("288") && document.querySelector(".operating-model").textContent.includes("원금 대용")');
    await expect('Oracle capex above revenue is preserved in inputs and negative cash is not zero value', 'Number(document.querySelector("[data-operating=capexStart]").dataset.exact)>1 && document.querySelector("[data-operating=capexStart]").max==="200" && (()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="ORCL").operatingModel;return m.initial.equityValue===null && m.initial.years[0].cash<0 && m.initial.years[0].capex===75660000000})()');
    const oracleBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=capexStart]");e.value=150;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),oracleBefore);checks.push('Oracle investment intensity exceeding sales recalculates without clipping');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Oracle expanded investment assumption survives exact save and reload', 'Number(document.querySelector("[data-operating=capexStart]").dataset.exact)===1.5 && document.querySelector("#operating-message").textContent.includes("복원")');
    await js('{const e=document.querySelector("[data-operating=capexStart]");e.value=201;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    await expect('Oracle source-specific investment ceiling is enforced', 'document.querySelector("#operating-result").textContent.includes("가정 범위") && !document.querySelector(".operating-years")');
    await js('localStorage.removeItem("equity-operating-path-v1-ORCL")');await click('#operating-reset');
    await viewport(390);await expect('Oracle financing chart scrolls locally while the page stays within mobile width', 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelector(".capacity-chart-scroll").scrollWidth>document.querySelector(".capacity-chart-scroll").clientWidth');await screenshotRegion('mobile-oracle-capacity.png','.operating-capacity-evidence');await viewport(1440);
    await screenshotRegion('desktop-oracle-capacity.png','.operating-capacity-evidence');
    await pdf('oracle.pdf');
    await go('company/030200');
    await expect('KT retains investment-property acquisition scope and credit-card cash boundary', 'document.querySelector("main").textContent.includes("유형자산·투자부동산 취득") && document.querySelector(".business-insight").textContent.includes("BC카드") && document.querySelector("#valuation-result").textContent.includes("계산 보류")');
    await expect('KT filing draft retains original million-won captions and both period headers', 'document.querySelector(".reading-source-context").textContent.includes("백만원") && document.querySelector(".reading-source-context").textContent.includes("2025.06.30")');
    await pdf('kt.pdf');
    await go('company/NFLX');
    await expect('Netflix source reading distinguishes termination fees and content payment timing', 'document.querySelector(".business-insight").textContent.includes("WBD") && document.querySelector(".business-insight").textContent.includes("콘텐츠 지급과 상각")');
    await expect('Netflix reconciles content payment periods and overlapping obligations independently of capex', 'document.querySelectorAll(".content-payment-periods tbody tr").length===3 && document.querySelectorAll(".content-obligations tbody tr").length===7 && document.querySelector(".operating-content-evidence").textContent.includes("19.608") && document.querySelector(".operating-content-evidence").textContent.includes("4.234") && document.querySelector(".operating-years").textContent.includes("콘텐츠 지급")');
    const netflixBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=contentEnd]");e.value=45;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),netflixBefore);checks.push('Netflix future content payments independently change cash');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Netflix content assumption persists exactly while PPE and acquisitions remain unchanged', 'Number(document.querySelector("[data-operating=contentEnd]").dataset.exact)===.45 && document.querySelector("#operating-message").textContent.includes("복원") && Number(document.querySelector("[data-operating=capexEnd]").dataset.exact)===window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="NFLX").operatingModel.defaults.capexEnd');
    await expect('Netflix research note serialization restores both content fields and rejects omissions', '(()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="NFLX").operatingModel,a=JSON.parse(localStorage.getItem("equity-operating-path-v1-NFLX")).assumptions;const note="사업부 현금 경로 "+m.version+" · 원문/계산 "+m.evidenceHash+String.fromCharCode(10)+"정확한 가정 JSON: "+JSON.stringify(a);const restored=window.EquityOperatingModel.parseNote(m,note);if(restored.contentEnd!==.45||restored.contentStart!==a.contentStart)return false;delete a.contentEnd;try{window.EquityOperatingModel.calculate(m,a);return false;}catch{return true;}})()');
    await js('{const e=document.querySelector("[data-operating=contentEnd]");e.value="";e.dispatchEvent(new Event("input",{bubbles:true}));}');
    await expect('Netflix missing content assumption is not treated as zero', 'document.querySelector("#operating-result").textContent.includes("빈 가정은 영으로")');
    await js('{const e=document.querySelector("[data-operating=contentEnd]");e.value=0;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    await expect('Netflix explicit zero content spending remains a marked scenario with reinvestment caution', '!!document.querySelector(".operating-years") && document.querySelector(".operating-caution").textContent.includes("콘텐츠 지급")');
    await js('localStorage.removeItem("equity-operating-path-v1-NFLX")');await click('#operating-reset');
    await viewport(390);await expect('Netflix content tables and controls fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-netflix-content.png','.operating-content-evidence');await viewport(1440);
    await screenshotRegion('desktop-netflix-content.png','.operating-content-evidence');
    await pdf('netflix.pdf');
    await go('company/251270');
    await expect('Netmarble changed product classifications cannot become unqualified organic growth', 'document.querySelector(".business-insight").textContent.includes("상품 구분 기준이 변경") && document.querySelector(".business-insight").textContent.includes("반기와 이전 연간")');
    await go('company/090430');
    await expect('Amore Pacific quarter-specific management commentary is not relabeled as half-year growth', 'document.querySelector(".business-insight").textContent.includes("2분기이지 반기 전체가 아니다")');
    const pairedIds=await js('window.EQUITY_SNAPSHOT.snapshot.peerStudies.map(p=>p.id)');
    for(const id of pairedIds){
      await go('compare/'+id);
      await expect('Both current original sources open in paired study '+id, 'document.querySelectorAll(".source-pair-grid article").length===2 && [...document.querySelectorAll(".source-pair-grid article")].every(e=>e.querySelector("details blockquote") && [...e.querySelectorAll("a")].some(a=>a.href.startsWith("https://")))');
    }
    await go('compare/analog-manufacturing');
    await expect('TI ADI paired cash preserves government, acquisition and fiscal-window differences', '!!document.querySelector("#pair-result") && document.querySelector(".source-pair").textContent.includes("CHIPS") && document.querySelector(".source-pair").textContent.includes("Empower")');
    const analogBefore=await js('document.querySelector("#pair-result").textContent');
    await js('{const e=document.querySelectorAll("[data-pair-key=capexEnd]")[1];e.value=8;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#pair-result").textContent'),analogBefore);checks.push('Independent ADI reinvestment changes paired cash judgment');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Analog comparison restores exact independent assumptions', 'Number(document.querySelectorAll("[data-pair-key=capexEnd]")[1].dataset.exact)===.08 && document.querySelector("#pair-message").textContent.includes("복원")');
    await viewport(390);await expect('Analog comparison fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await pdf('comparison-analog.pdf');
    await go('compare/software-contracts');
    await expect('CRM Adobe paired cash preserves different contract amortization and financing scopes', 'document.querySelector(".source-pair").textContent.includes("계약 취득비") && document.querySelector(".pair-security-hold").textContent.includes("2.17억") && !!document.querySelector("#pair-result")');
    await js('{const e=document.querySelectorAll("[data-pair-key=capexEnd]")[1];e.value=12;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Software comparison restores exact assumptions without approving held Salesforce price', 'Number(document.querySelectorAll("[data-pair-key=capexEnd]")[1].dataset.exact)===.12 && document.querySelector("#pair-message").textContent.includes("복원") && document.querySelector(".pair-security-hold").textContent.includes("금융의무")');
    await viewport(390);await expect('Software cash comparison fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await pdf('comparison-software.pdf');
    await go('compare/enterprise-delivery');
    await expect('Cross-market enterprise software comparison preserves infrastructure and logistics differences', 'document.querySelector(".source-pair").textContent.includes("삼성SDS") && document.querySelector(".source-pair").textContent.includes("self-hosted") && document.querySelector(".source-pair").textContent.includes("물류") && !!document.querySelector("#pair-result")');
    await expect('Enterprise cash comparison distinguishes gross-profit and consolidated operating-profit paths', 'document.querySelector(".pair-inputs").textContent.includes("매출총이익률") && document.querySelector(".pair-inputs").textContent.includes("내부매출 제거") && document.querySelector(".pair-inputs").textContent.includes("판매수수료 현금")');
    const enterpriseBefore=await js('document.querySelector("#pair-result").textContent');
    await js('{const e=document.querySelector("[data-pair-key=capexEnd]");e.value=10;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    assert.notEqual(await js('document.querySelector("#pair-result").textContent'),enterpriseBefore);checks.push('Enterprise reinvestment edit updates paired cash while SDS share price stays held');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Enterprise paired notes retain acquisition conditions and original capital hold', 'document.querySelector("#pair-message").textContent.includes("복원") && Number(document.querySelector("[data-pair-key=capexEnd]").dataset.exact)===.1 && document.querySelector("#pair-print-note").textContent.includes("전환사채")');
    await viewport(390);await expect('Expanded enterprise comparison fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');
    await screenshotRegion('mobile-enterprise-comparison.png','.source-pair');await viewport(1440);await pdf('comparison-enterprise.pdf');
    await go('compare/cloud-build-operate');
    await expect('Cross-market infrastructure comparison preserves government ownership and private financing obligations', 'document.querySelector(".source-pair").textContent.includes("정부 소유") && !!document.querySelector("#pair-result") && document.querySelector(".pair-inputs").textContent.includes("미배분 비용") && document.querySelector(".pair-inputs").textContent.includes("내부매출 제거")');
    await expect('Both issuers retain share-rights holds while their cash assumptions remain editable', '(()=>{const s=window.EQUITY_SNAPSHOT.snapshot.peerStudies.find(s=>s.id==="cloud-build-operate").operatingComparison;return s.sides.every(x=>x.initial.cashPath.price===null && x.initial.requiredCashMargin===null) && s.sides[0].initial.terminalCashMargin<0})()');
    await js('{const e=document.querySelectorAll("[data-pair-key=capexStart]")[0];e.value=150;e.dispatchEvent(new Event("input",{bubbles:true}));}');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Infrastructure paired record restores investment above revenue and conditional source judgment', 'document.querySelector("#pair-message").textContent.includes("복원") && Number(document.querySelectorAll("[data-pair-key=capexStart]")[0].dataset.exact)===1.5 && document.querySelector("#pair-print-note").textContent.includes("우선주")');
    await viewport(390);await expect('Infrastructure comparison remains usable on mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await pdf('comparison-infrastructure.pdf');
    await go('compare/retail-repeat');
    await expect('A pair lacking reconciled business models retains source research without invented cash results', '!document.querySelector("#pair-result") && document.querySelector("main").textContent.includes("근거 보완") && !!document.querySelector(".source-pair")');
    await go('company/012450');
    await expect('Conflicting share disclosures preserve both original amounts and hold price', 'document.querySelector(".valuation-share-evidence").textContent.includes("51,448,788") && document.querySelector(".valuation-share-evidence").textContent.includes("51,563,401") && document.querySelector("#valuation-result").textContent.includes("계산 보류")');
    await expect('Attachment correction preserves original annual financial source', 'document.querySelector(".correction-note").textContent.includes("20260316001112") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="012450").analysis.annual.length>0');
    await go('company/F');
    await expect('Ford primary filing fills the missing companyfacts quarter explicitly', 'document.querySelector("main").textContent.includes("2026-06-30") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="F").financials.current.cfo.provenance==="primary_filing_supplement"');
    await go('company/LLY');
    await expect('Lilly investment caption is verified against the filing period and amount', 'document.querySelector(".investment-definition").textContent.includes("원 보고서") && document.querySelector(".investment-definition").textContent.includes("5.26")');
    await go('company/373220');
    await expect('Negative cash bars extend left of their zero baseline', 'document.querySelectorAll(".signed-bars .negative").length>0 && [...document.querySelectorAll(".signed-bars .negative")].every(e=>parseFloat(e.style.width)>0 && parseFloat(e.style.left)<parseFloat(e.closest(".signed-bars").style.getPropertyValue("--zero")))');
  }
  if (!publishedSite) {
    await go('company/JNJ');
    await expect('JNJ shows reported pretax segments and broader reinvestment without a second interest charge', 'document.querySelectorAll(".operating-segments tbody tr").length===2 && document.querySelector(".operating-segments").textContent.includes("세전이익률") && document.querySelector(".operating-years").textContent.includes("미배분 비용 차감 후 세전이익") && !document.querySelector("[data-operating=netInterest]") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="JNJ").operatingModel.initial.years[0].cash===17633000000');
    const jnjBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=corporateEnd]");e.value=3;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),jnjBefore);checks.push('JNJ unallocated cost assumption changes pretax cash without a duplicate interest input');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('JNJ exact corporate cost reopens with pretax source evidence', 'Number(document.querySelector("[data-operating=corporateEnd]").dataset.exact)===.03 && document.querySelector("#operating-message").textContent.includes("복원") && document.querySelector(".operating-cash-anchors").textContent.includes("자료 미확인")');
    await js('localStorage.removeItem("equity-operating-path-v1-JNJ")');await click('#operating-reset');
    await viewport(390);await expect('JNJ pretax cash inputs fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-jnj-operating.png','.operating-model');await viewport(1440);await pdf('jnj.pdf');
    await go('company/068270');
    await expect('Celltrion retains three gross-sales segments and separate internal-profit assumptions', 'document.querySelectorAll(".operating-segments tbody tr").length===3 && document.querySelector(".operating-consolidation-controls").textContent.includes("내부거래 조정 전") && Number(document.querySelector("[data-operating=otherProfitEnd]").dataset.exact)===0 && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="068270").operatingModel.bridge.reportedCfo===995898364100');
    await expect('Celltrion interest cash classifications and rounding residuals survive rendering', 'document.querySelectorAll(".pharma-interest tbody tr").length===3 && document.querySelector(".operating-pharma-evidence").textContent.includes("이자 지급은 재무활동") && document.querySelector(".operating-pharma-evidence").textContent.includes("-495원") && document.querySelector(".operating-source-bridge summary").textContent.includes("-796원")');
    await expect('Celltrion development gross stage amounts are separated from impairment and cash purchases', 'document.querySelector(".operating-pharma-evidence svg").getAttribute("aria-label").includes("성공 확률이 아님") && document.querySelectorAll(".operating-pharma-evidence svg rect").length===3 && document.querySelector(".operating-pharma-evidence").textContent.includes("손상누계") && document.querySelector(".operating-pharma-evidence").textContent.includes("다른 범위")');
    await expect('Celltrion supplier financing keeps net cash and the separate payable transfer distinct', 'document.querySelector(".pharma-financing").textContent.includes("-0.031") && document.querySelector(".operating-pharma-evidence").textContent.includes("60일") && document.querySelector(".operating-pharma-evidence").textContent.includes("180일") && document.querySelector(".operating-pharma-evidence").textContent.includes("다시 더하지")');
    const celltrionBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=otherProfitEnd]");e.value=3;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),celltrionBefore);checks.push('Celltrion internal-profit assumption changes the cash path independently of sales removal');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Celltrion exact internal-profit assumption survives reload', 'Number(document.querySelector("[data-operating=otherProfitEnd]").dataset.exact)===.03 && document.querySelector("#operating-message").textContent.includes("복원")');
    await js('localStorage.removeItem("equity-operating-path-v1-068270")');await click('#operating-reset');
    await viewport(390);await expect('Celltrion cash classifications and clinical-stage chart fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-celltrion-operating.png','.operating-model');await viewport(1440);await pdf('celltrion.pdf');
    await go('compare/innovator-biosimilar');
    await expect('Biosimilar comparison preserves different profit bases, periods and currencies', 'document.querySelectorAll(".pair-input-side fieldset").length===5 && document.querySelector(".pair-inputs").textContent.includes("세전이익률") && document.querySelector(".source-pair").textContent.includes("공급자금융") && !!document.querySelector("#pair-result") && ![...document.querySelectorAll("[data-pair-key=netInterest]")].some(e=>e.dataset.pairSide==="0")');
    await expect('Pharma comparison keeps unmatched product sales and reported product geography rounding', 'document.querySelectorAll(".pharma-product-table tbody tr").length===2 && document.querySelector(".pharma-product-table").textContent.includes("자료 미확인") && document.querySelector(".pharma-product-regions").textContent.includes("미국발 수출") && document.querySelector(".pharma-product-regions").textContent.includes("현재 1백만")');
    await expect('JNJ pretax and cash charts reconcile without equating company performance', '[...document.querySelectorAll(".pharma-change-chart")][0].querySelectorAll("g[data-value]").length===4 && [...document.querySelectorAll(".pharma-change-chart")][1].querySelectorAll("g[data-value]").length===7 && [...document.querySelectorAll(".pharma-change-chart")][1].textContent.includes("+3.078") && document.querySelector(".pharma-comparison").textContent.includes("손실 상한") && document.querySelector(".pharma-investment-table").textContent.includes("14.458")');
    await viewport(390);await expect('Pharma source comparison keeps its charts within a readable local scroll area', 'document.documentElement.scrollWidth<=innerWidth+1 && [...document.querySelectorAll(".pharma-chart-scroll")].every(e=>e.scrollWidth>e.clientWidth)');await screenshotRegion('mobile-pharma-comparison.png','.pharma-comparison');await viewport(1440);
    await js('window.dispatchEvent(new Event("beforeprint"))');
    await expect('Printing reveals pharma product rounding and cash reconciliation tables', 'document.querySelector(".pharma-product-regions").open && document.querySelector(".pharma-cash-detail").open');
    await js('window.dispatchEvent(new Event("afterprint"))');
    await expect('Printing restores the prior collapsed pharma evidence state', '!document.querySelector(".pharma-product-regions").open && !document.querySelector(".pharma-cash-detail").open');
    await js('{const e=[...document.querySelectorAll("[data-pair-key=corporateEnd]")].find(e=>e.dataset.pairSide==="0");e.value=3;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('US KR pharma cost assumptions and comparison judgment survive reopening', 'Number([...document.querySelectorAll("[data-pair-key=corporateEnd]")].find(e=>e.dataset.pairSide==="0").value)===3 && document.querySelector("#pair-message").textContent.includes("복원") && document.querySelector("#pair-print-note").textContent.includes("연구개발")');
    await pdf('comparison-biosimilar.pdf');
    await go('company/035420');
    await expect('NAVER keeps one reported business and reconciles the cash-generated bridge', 'document.querySelectorAll(".operating-segments tbody tr").length===1 && document.querySelector(".operating-source-bridge").textContent.includes("창출 현금") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="035420").operatingModel.bridge.reportedCfo===3157421983625');
    await expect('NAVER customer cash restrictions retain dates, currencies and missing interim detail', 'document.querySelectorAll(".operating-customer-funds tbody tr").length===6 && document.querySelector(".operating-customer-funds").textContent.includes("1,392,000,000 JPY") && document.querySelector(".operating-customer-funds").textContent.includes("9,000,000 CAD") && document.querySelector(".operating-customer-funds").textContent.includes("반기 세부 조정은 미확인") && document.querySelector(".operating-model").textContent.includes("2025연간")');
    await expect('NAVER unassessed investments hold the whole-market inverse without hiding the cash component', 'document.querySelector("[data-operating=equityInvestmentValue]").value==="" && document.querySelector(".operating-investment-result").textContent.includes("투자자산 가치 미평가") && !document.querySelector("[data-implied-margin]") && document.querySelector(".operating-investment-evidence").textContent.includes("42.25%") && document.querySelector(".investment-movements").textContent.includes("기타증감")');
    await js('{const e=document.querySelector("[data-operating=equityInvestmentValue]");e.value=12;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    await expect('NAVER explicit investment value restores a separate current-price margin question', '!!document.querySelector("[data-implied-margin]") && !document.querySelector(".operating-investment-result").textContent.includes("투자자산 가치 미평가")');
    const naverBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=minority]");e.value=2;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),naverBefore);checks.push('NAVER minority allocation changes cash independently of consolidated operating margin');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('NAVER minority and separate investment value restore exactly', 'Number(document.querySelector("[data-operating=minority]").dataset.exact)===.02 && Number(document.querySelector("[data-operating=equityInvestmentValue]").dataset.exact)===12e12 && document.querySelector("#operating-message").textContent.includes("복원")');
    await js('{const e=document.querySelector("[data-operating=equityInvestmentValue]");e.value="";e.dispatchEvent(new Event("input",{bubbles:true}))}');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('NAVER empty investment assumption remains unassessed after saving and reloading', 'document.querySelector("[data-operating=equityInvestmentValue]").value==="" && document.querySelector(".operating-investment-result").textContent.includes("투자자산 가치 미평가")');
    await js('localStorage.removeItem("equity-operating-path-v1-035420")');await click('#operating-reset');
    await viewport(390);await expect('NAVER customer funds and cash bridge fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-naver-operating.png','.operating-model');await viewport(1440);await pdf('naver.pdf');
    await go('compare/advertising-platforms');
    await expect('Cross-market platform comparison preserves three versus one business and held Alphabet rights', 'document.querySelectorAll(".pair-input-side fieldset").length===4 && document.querySelector(".source-pair").textContent.includes("고객 선불충전금") && !!document.querySelector(".pair-security-hold")');
    await expect('Unassessed NAVER investment scope also holds the paired price requirement', 'document.querySelector(".pair-investment-scope").textContent.includes("미평가") && document.querySelector("[data-pair-key=equityInvestmentValue]").value===""');
    await js('{const e=document.querySelector("[data-pair-key=equityInvestmentValue]");e.value=12;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    await js('{const e=document.querySelector("[data-pair-key=minority]");e.value=2;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    await click('#pair-use-reading');
    await click('#pair-save');await js('location.reload()');await ready();
    await expect('NAVER paired investment, minority and comparison notes survive reload', 'Number(document.querySelector("[data-pair-key=minority]").value)===2 && Number(document.querySelector("[data-pair-key=equityInvestmentValue]").dataset.exact)===12e12 && document.querySelector("#pair-message").textContent.includes("복원") && document.querySelector("#pair-print-note").textContent.includes("고객 자금")');
    await viewport(390);await expect('US KR platform cash comparison fits mobile','document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await pdf('comparison-platforms.pdf');
    await go('company/012330');
    await expect('Mobis preserves two gross-sales segments and the disclosed internal profit removal', 'document.querySelectorAll(".operating-segments tbody tr").length===2 && document.querySelector(".operating-consolidation-evidence").textContent.includes("공시 내부이익 제거") && !document.querySelector(".operating-consolidation-evidence").textContent.includes("미표시 기타") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="012330").operatingModel.bridge.reportedCfo===4132208000000');
    await expect('Mobis warranty total usage, cash adjustment gap and reimbursement balances remain separate', 'document.querySelectorAll(".operating-warranty-cash-evidence tbody tr").length===6 && document.querySelector(".operating-warranty-cash-evidence").textContent.includes("0.322") && document.querySelector(".operating-warranty-cash-evidence").textContent.includes("0.582") && document.querySelector(".operating-warranty-cash-evidence").textContent.includes("자료 미확인") && !!document.querySelector(".operating-security-hold")');
    const mobisBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=eliminationEnd]");e.value=25;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    await click('#operating-warranty-stress');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),mobisBefore);checks.push('Mobis warranty burden changes cash while preserving the edited internal-sales assumption');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Mobis exact consolidation assumption survives reload while the preferred-share hold remains', 'Number(document.querySelector("[data-operating=eliminationEnd]").dataset.exact)===.25 && document.querySelector("#operating-message").textContent.includes("복원") && !!document.querySelector(".operating-security-hold")');
    await js('localStorage.removeItem("equity-operating-path-v1-012330")');await click('#operating-reset');
    await viewport(390);await expect('Mobis warranty cash reconciliation fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-mobis-operating.png','.operating-model');await viewport(1440);await pdf('mobis.pdf');
    await go('compare/auto-supply-service');
    await expect('Automotive value-chain comparison preserves direct-customer exposure and separate warranty scopes', 'document.querySelectorAll(".pair-input-side fieldset").length===3 && document.querySelector(".pair-summary").textContent.includes("사업 실적 기간 일치") && document.querySelector(".source-pair").textContent.includes("가치사슬") && document.querySelector(".pair-inputs").textContent.includes("현금표 보증 변동 대용") && !!document.querySelector(".pair-security-hold")');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('Value-chain research reopens without treating the two companies as independent demand samples', 'document.querySelector("#pair-message").textContent.includes("복원") && document.querySelector("#pair-print-note").textContent.includes("현금표") && document.querySelector(".source-pair").textContent.includes("독립적인 두 수요")');
    await viewport(390);await expect('Value-chain comparison fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await pdf('comparison-auto-supply.pdf');
    await js('localStorage.removeItem("equity-paired-research-v1")');
    await go('company/AVGO');
    await expect('Broadcom separates two segments, corporate costs and nine contingent loss cases', 'document.querySelectorAll(".operating-segments tbody tr").length===2 && document.querySelectorAll(".operating-contract-stress tbody tr").length===9 && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="AVGO").operatingModel.bridge.reportedCfo===40653000000');
    const supportBefore=await js('document.querySelector(".operating-contract-stress tbody").textContent');
    await js('{const e=document.querySelector("[data-operating=discount]");e.value=15;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector(".operating-contract-stress tbody").textContent'),supportBefore);checks.push('Broadcom one-time support losses recalculate at the selected discount rate');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Broadcom saved stress retains contract scope and timing', 'Number(document.querySelector("[data-operating=discount]").dataset.exact)===.15 && document.querySelector(".operating-contract-stress").textContent.includes("일회") && document.querySelector(".operating-cash-anchors").textContent.includes("42")');
    await js('localStorage.removeItem("equity-operating-path-v1-AVGO")');await click('#operating-reset');
    await viewport(390);await expect('Broadcom contingent financing table fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-broadcom-operating.png','.operating-model');await viewport(1440);await pdf('broadcom.pdf');
    await go('company/LRCX');
    await expect('Lam exposes one gross-profit segment and two separate annual warranty periods', 'document.querySelectorAll(".operating-segments tbody tr").length===1 && document.querySelectorAll(".operating-settlement-evidence tbody tr").length===2 && document.querySelector(".operating-years").textContent.includes("보증 순발생") && !document.querySelector(".operating-controls").textContent.includes("현금표 보증비") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="LRCX").operatingModel.initial.years[0].leasePrincipal===4971000');
    await js('{const e=document.querySelector("[data-operating=researchEnd]");e.value=15;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    const lamBefore=await js('document.querySelector("#operating-result").textContent');
    const lamWorking=await js('document.querySelector("[data-operating=workingCapital]").dataset.exact');
    await click('#operating-warranty-stress');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),lamBefore);
    assert.equal(await js('document.querySelector("[data-operating=workingCapital]").dataset.exact'),lamWorking);
    await expect('Lam settlement-only stress preserves edited research and working-cash assumptions', 'Number(document.querySelector("[data-operating=researchEnd]").dataset.exact)===.15 && document.querySelector("#operating-message").textContent.includes("다른 가정을 유지")');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Lam source-bound assumptions survive reload', 'Number(document.querySelector("[data-operating=researchEnd]").dataset.exact)===.15 && document.querySelector("#operating-message").textContent.includes("복원")');
    await js('localStorage.removeItem("equity-operating-path-v1-LRCX")');await click('#operating-reset');
    await viewport(390);await expect('Lam reserve ledger and cash controls fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-lam-operating.png','.operating-model');await viewport(1440);await pdf('lam.pdf');
    await go('company/AMAT');
    await expect('Applied preserves issuer-recast annual segment revenues and profits', 'document.querySelectorAll(".operating-recast-evidence tbody tr").length===3 && document.querySelector(".operating-recast-evidence").textContent.includes("20.798") && document.querySelector(".operating-recast-evidence").textContent.includes("21.441") && document.querySelector(".operating-recast-evidence").textContent.includes("5.742") && window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="AMAT").operatingModel.bridge.reportedCfo===8396000000');
    await expect('Applied recast evidence links directly to the issuer table and holds unknown current lease cash', 'document.querySelector(".operating-recast-evidence a").href.includes("#page=23") && document.querySelector(".operating-cash-anchors").textContent.includes("자료 미확인")');
    const appliedBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=leaseEnd]");e.value=1;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),appliedBefore);checks.push('Applied lease assumption changes future cash with the reported historical zero still separate');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Applied assumptions reopen with the exact recast evidence', 'Number(document.querySelector("[data-operating=leaseEnd]").dataset.exact)===.01 && document.querySelector(".operating-recast-evidence").textContent.includes("본사 지원비")');
    await js('localStorage.removeItem("equity-operating-path-v1-AMAT")');await click('#operating-reset');
    await viewport(390);await expect('Applied recast table fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-applied-operating.png','.operating-model');await viewport(1440);await pdf('applied.pdf');
    await go('compare/ai-customer-financing');
    await expect('AI financing pair preserves four segments and distinct support obligations', 'document.querySelectorAll(".pair-input-side fieldset").length===4 && document.querySelector(".pair-summary").textContent.includes("사업 실적 기간 상이") && document.querySelector(".pair-inputs").textContent.includes("일회성 순지급") && document.querySelector(".source-pair").textContent.includes("Backstop")');
    await click('#pair-use-reading');await click('#pair-save');await js('location.reload()');await ready();
    await expect('AI financing notes restore with conditional rather than expected loss wording', 'document.querySelector("#pair-message").textContent.includes("복원") && document.querySelector("#pair-print-note").textContent.includes("지급확률")');
    await viewport(390);await expect('AI financing comparison fits mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await viewport(1440);await pdf('comparison-ai-financing.pdf');
    await js('localStorage.removeItem("equity-paired-research-v1")');
    await go('company/005930');
    await expect('Samsung consolidates internal sales and preserves the unexplained profit difference', 'document.querySelectorAll(".operating-segments tbody tr").length===4 && document.querySelectorAll(".operating-consolidation-evidence tbody tr").length===3 && document.querySelector(".operating-consolidation-evidence").textContent.includes("계산 차이") && (()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="005930").operatingModel;return m.bridge.reportedCfo===196729338000000 && m.consolidation.internalRevenue===43140184000000 && m.initial.price===null})()');
    await expect('Unknown Samsung share compensation remains missing instead of observed zero', 'document.querySelector(".operating-model").textContent.includes("자료 미확인") && (()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="005930").operatingModel;return m.bridge.cashAfterInvestmentLeaseSbc===null && m.anchors.actualShareCompensationReplacement===null})()');
    await expect('Held Korean share classes prevent margin inversion without blocking cash editing', 'document.querySelector(".operating-implied-margins").textContent.includes("역산하지 않습니다") && !document.querySelector("[data-implied-margin]")');
    const samsungBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=eliminationEnd]");e.value=15;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),samsungBefore);checks.push('Samsung internal-sales assumption changes consolidated revenue and working cash');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Samsung consolidation assumptions restore while security valuation stays held', 'document.querySelector("#operating-message").textContent.includes("복원") && Number(document.querySelector("[data-operating=eliminationEnd]").dataset.exact)===.15 && !!document.querySelector(".operating-security-hold")');
    await js('localStorage.removeItem("equity-operating-path-v1-005930")');await click('#operating-reset');
    await viewport(390);await expect('Samsung consolidation and cash tables fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-samsung-operating-path.png','.operating-model');await viewport(1440);await pdf('samsung-electronics.pdf');
    await go('company/AMD');
    await expect('AMD separates the three continuing segments and preserves total-versus-continuing cash', 'document.querySelectorAll(".operating-segments tbody tr").length===3 && document.querySelector(".operating-model").textContent.includes("ZT") && document.querySelector(".cash-scope").textContent.includes("중단영업") && (()=>{const m=window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="AMD").operatingModel;return m.bridge.reportedCfo===9413000000 && m.anchors.discontinuedCfo===667000000 && m.initial.price===null})()');
    await expect('Customer warrant maximums remain separate from vested and current outstanding shares', 'document.querySelector(".valuation-customer-warrants").textContent.includes("160,000,000") && document.querySelector(".valuation-customer-warrants").textContent.includes("$0.01") && document.querySelector(".valuation-customer-warrants").textContent.includes("자료 미확인") && !!document.querySelector(".operating-security-hold") && document.querySelector(".valuation-security").textContent.includes("워런트")');
    await expect('AMD lease guarantees and post-balance-sheet commitments keep their separate dates and unknown cash amounts', 'document.querySelector(".operating-cash-anchors").textContent.includes("4.1") && document.querySelector(".operating-cash-anchors").textContent.includes("9.5") && document.querySelector(".operating-cash-anchors").textContent.includes("이후") && document.querySelector(".operating-cash-anchors").textContent.includes("자료 미확인")');
    const amdBefore=await js('document.querySelector("#operating-result").textContent');
    await js('{const e=document.querySelector("[data-operating=leaseEnd]");e.value=1;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),amdBefore);checks.push('AMD assumed finance-lease burden changes cash without treating an unknown payment as reported zero');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('AMD saved lease assumption retains its source and continued price hold', 'document.querySelector("#operating-message").textContent.includes("복원") && Number(document.querySelector("[data-operating=leaseEnd]").dataset.exact)===.01 && !!document.querySelector(".operating-security-hold") && document.querySelector(".valuation-security").textContent.includes("워런트")');
    await js('localStorage.removeItem("equity-operating-path-v1-AMD")');await click('#operating-reset');
    await viewport(390);await expect('AMD continuing-cash and warrant tables fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-amd-operating-path.png','.operating-model');await viewport(1440);await pdf('amd.pdf');
  }

  await go('company/NVDA');
  await expect('NVIDIA broader investment scope remains visible', 'document.querySelector("main").textContent.includes("유형·무형자산 취득")');
  if (!publishedSite) {
    await expect('NVIDIA separates two operating segments from product markets and deducts corporate stock compensation', 'document.querySelectorAll(".operating-segments tbody tr").length===2 && document.querySelector(".operating-years").textContent.includes("주식보상") && document.querySelector(".operating-model").textContent.includes("다른 구분")');
    await expect('NVIDIA exposes future supply and cloud commitments without claiming current cash payments', 'document.querySelector(".operating-cash-anchors").textContent.includes("279") && document.querySelector(".operating-cash-anchors").textContent.includes("36") && document.querySelector(".operating-cash-anchors").textContent.includes("29") && document.querySelector(".operating-cash-anchors").textContent.includes("자료 미확인") && document.querySelector(".operating-model").textContent.includes("분할취득 원금")');
    const nvidiaBase=await js('document.querySelector("#operating-result").textContent');
    await click('#operating-observed');
    await expect('NVIDIA observed triple-digit growth does not overwrite supported assumptions', 'document.querySelector("#operating-message").textContent.includes("가정 범위를 벗어납니다")');
    assert.equal(await js('document.querySelector("#operating-result").textContent'),nvidiaBase);checks.push('NVIDIA preserves the original scenario when observed growth is outside supported bounds');
    await js('{const e=document.querySelector("[data-operating=corporateEnd]");e.value=Number(e.value)+1;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),nvidiaBase);checks.push('NVIDIA corporate-cost stress changes cash after recalculating taxes');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('NVIDIA source-bound corporate assumptions reopen with the contract context', 'document.querySelector("#operating-message").textContent.includes("복원") && document.querySelector(".operating-model").textContent.includes("AI 클라우드")');
    await js('localStorage.removeItem("equity-operating-path-v1-NVDA")');await click('#operating-reset');
    await viewport(390);await expect('NVIDIA commitments and corporate-cost controls fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-nvidia-operating-path.png','.operating-model');await viewport(1440);await pdf('nvidia.pdf');
  }
  await go('company/000660');
  if (!publishedSite) {
    await expect('Hynix separates completed issuance, dated treasury holdings and planned buyback', 'document.querySelector(".valuation-capital-events").textContent.includes("730,492,365") && document.querySelector(".valuation-capital-events").textContent.includes("24,070,000") && document.querySelector(".valuation-capital-events").textContent.includes("2026-11-19") && document.querySelector(".valuation-capital-events").textContent.includes("1,625,769")');
    await expect('Hynix single-business cash path excludes investment dividends and distinguishes purchase commitments', 'document.querySelectorAll(".operating-segments tbody tr").length===1 && document.querySelector(".operating-model").textContent.includes("배당 수취") && document.querySelector(".operating-cash-anchors").textContent.includes("미기표") && document.querySelector(".operating-security-hold").textContent.includes("유통주식수")');
    const hynixBase=await js('document.querySelector("#operating-result").textContent');
    await click('#operating-observed');
    await expect('Out-of-range observed growth keeps the original scenario and explains the boundary', 'document.querySelector("#operating-message").textContent.includes("가정 범위를 벗어납니다")');
    assert.equal(await js('document.querySelector("#operating-result").textContent'),hynixBase);checks.push('Hynix observed growth is not clipped into a fabricated supported forecast');
    await js('{const e=[...document.querySelectorAll("[data-operating]")].find(x=>x.dataset.operating==="0.marginEnd");e.value=Number(e.value)-10;e.dispatchEvent(new Event("input",{bubbles:true}))}');
    assert.notEqual(await js('document.querySelector("#operating-result").textContent'),hynixBase);checks.push('Hynix standalone margin stress changes the operating cash result');
    await click('#operating-save');await js('location.reload()');await ready();
    await expect('Korean memory assumptions restore at the same source hash while the equity hold persists', 'document.querySelector("#operating-message").textContent.includes("복원") && document.querySelector(".operating-security-hold").textContent.includes("유통주식수")');
    await js('localStorage.removeItem("equity-operating-path-v1-000660")');await click('#operating-reset');
    await viewport(390);await expect('Hynix capital-event and cash-anchor tables fit mobile', 'document.documentElement.scrollWidth<=innerWidth+1');await screenshotRegion('mobile-hynix-operating-path.png','.operating-model');await viewport(1440);
  }
  if (await js('!!document.querySelector(".receivable-panel")')) {
    await expect('Opposing average and closing-balance directions remain visible', 'document.querySelector(".ar-reading").textContent.includes("두 기준의 방향이 다릅니다") && document.querySelector(".ar-reading").textContent.includes("-14.0일")');
    await expect('Small allowances are not rounded to zero and balance cash gaps are explicit', 'document.querySelector(".ar-accounting").textContent.includes("0.0053%") && document.querySelector(".ar-accounting").textContent.includes("연결 미완료") && document.querySelector(".ar-notes").textContent.includes("채권 양도")');
  }
  await screenshot('desktop-hynix.png'); await pdf('sk-hynix.pdf');
  await go('lab');
  await expect('Risk and return tests disclose oracle and exploratory limits', 'document.querySelector("main").textContent.includes("완전예지") && document.querySelector("main").textContent.includes("QLIKE") && document.querySelector(".research-image").naturalWidth>0');
  await expect('Financial experiment matches its recorded historical window count', 'document.querySelectorAll("#research-window option").length===window.EQUITY_SNAPSHOT.snapshot.fundamentalExperiments.find(e=>e.market==="US").windowCount && document.querySelector(".fundamental-image").naturalWidth>0');
  await expect('Historical inputs link to the preserved filings', 'document.querySelectorAll("#window-evidence tbody tr").length===4 && document.querySelectorAll(".window-source").length>=4');
  const firstWindow = await js('document.querySelector("#window-evidence").textContent');
  await js('document.querySelector("#research-window").selectedIndex=document.querySelector("#research-window").options.length-1;document.querySelector("#research-window").dispatchEvent(new Event("change",{bubbles:true}))');
  assert.notEqual(await js('document.querySelector("#window-evidence").textContent'), firstWindow);
  checks.push('Changing the historical date changes the reconstructed decisions');
  await expect('Growth-gate ablation contribution matches the recorded experiment', '(()=>{const e=window.EQUITY_SNAPSHOT.snapshot.fundamentalExperiments.find(e=>e.market==="US");return document.querySelector(".fundamental-report").textContent.includes(e.ablationChangedWindows+"/"+e.windowCount)})()');
  await screenshot('desktop-lab-us.png'); await pdf('research-us.pdf');
  await click('[data-lab="KR"]');
  await expect('Korean research uses its own figure and fixed cohort', 'document.querySelector(".research-image").currentSrc.includes("-KR-research.svg") && document.querySelector("main").textContent.includes("000660")');
  await expect('Korean financial study preserves all recorded missing windows', '(()=>{const e=window.EQUITY_SNAPSHOT.snapshot.fundamentalExperiments.find(e=>e.market==="KR");return document.querySelectorAll("#research-window option").length===e.windowCount && document.querySelectorAll(".missing-windows p").length===e.unresolvedWindows.length && document.querySelector(".fundamental-image").currentSrc.includes("-KR-fundamental.svg")})()');
  await screenshot('desktop-lab-kr.png'); await pdf('research-kr.pdf');
  await go('tracking');
  await expect('Actual frozen conditions without fabricated accuracy', 'document.querySelectorAll(".record-card").length===window.EQUITY_SNAPSHOT.ledger.length && document.querySelector("main").textContent.includes("사전 예측 없음") && document.querySelector("main").textContent.includes("외부 시점 인증")');
  await screenshot('desktop-tracking.png'); await pdf('conditions.pdf');
  await expect('Published history needs no local mutation service', '!document.querySelector("[data-operation]")');
  await go('sources');
  await expect('All companies expose primary sources and preserved copies', 'document.querySelectorAll(".source-list>li").length===window.EQUITY_SNAPSHOT.snapshot.companies.length && document.querySelector("main").textContent.includes("SHA-256")');
  if(!publishedSite)await expect('Archived XBRL with an unrecorded collection time keeps its source links visible', '[...document.querySelectorAll(".source-list>li")].some(e=>e.textContent.includes("068270") && e.textContent.includes("수집 시각 미기록") && e.querySelector("a[href$=\\".zip\\"]"))');
  assert.equal(requests.some(r=>r.method==='POST'||/\/api\//.test(new URL(r.url).pathname)),false);
  checks.push('All research views work without backend API calls');
  await screenshot('desktop-sources.png');
  for(const width of [360,390,768]){
    await viewport(width,900);
    for(const view of ['universe','company/000660',...(!publishedSite?['company/MSFT','company/005380']:[]),'lab','tracking','sources']){
      await go(view);
      await expect(`No document overflow ${width}px ${view}`, 'document.documentElement.scrollWidth<=innerWidth+1');
      if(width===390)await screenshot('mobile-'+(['company/MSFT','company/005380'].includes(view)?view.replace('/','-'):view.split('/')[0])+'.png');
    }
  }
  if(!publishedSite){
    await go('lab');
    await expect('Expanded forward study remains separate from old eight-company experiments', 'document.querySelector(".forward-study").textContent.includes("20개 고정 기업") && document.querySelector(".forward-study").textContent.includes("미래 관측 대기") && window.EQUITY_SNAPSHOT.snapshot.researchCohort.members.length===8');
  }
  await expect('No visible undefined values', '!/NaN|undefined/.test(document.querySelector("main").textContent)');
  if(!publishedSite && !process.env.RESEARCH_URL){
    const coverageLabel = await js('"미국 "+window.EQUITY_SNAPSHOT.snapshot.companies.filter(c=>c.market==="US").length+" / 한국 "+window.EQUITY_SNAPSHOT.snapshot.companies.filter(c=>c.market==="KR").length');
    await send('Page.navigate',{url:pathToFileURL(path.join(root,'local.html')).href});
    for(let i=0;i<100;i++){if(await js('!!document.querySelector("#analysis-status") && document.querySelector("#analysis-status").textContent.includes('+JSON.stringify(coverageLabel)+')'))break;await new Promise(r=>setTimeout(r,50));}
    await expect('Local entry page shows saved coverage and separate offline/collection commands', 'document.querySelector("#analysis-status").textContent.includes('+JSON.stringify(coverageLabel)+') && document.body.textContent.includes("python3 start.py offline") && document.body.textContent.includes("python3 start.py collect")');
    assert.equal(await js('document.documentElement.scrollWidth<=innerWidth+1'),true);checks.push('Local entry fits a tablet without overflow');
    await screenshot('local-start.png');
  }
  assert.equal(runtimeErrors.length,0,JSON.stringify(runtimeErrors));checks.push('No browser JavaScript exceptions');
  const snapshotHash=await js('window.EQUITY_SNAPSHOT.snapshot.contentHash');
  const localReviewHashes=await js('Object.fromEntries(Object.entries(window.EQUITY_SNAPSHOT.localReviews||{}).map(([k,r])=>[k,r.recordHash||r.status]))');
  const coverageReviewHashes=await js('Object.fromEntries(Object.entries(window.EQUITY_SNAPSHOT.coverageReviews||{}).map(([k,r])=>[k,r.recordHash||r.status]))');
  const questionSelectionHashes=await js('Object.fromEntries(Object.entries(window.EQUITY_SNAPSHOT.questionSelections||{}).map(([k,r])=>[k,r.recordHash||r.status]))');
  const renderedPayloadHash=process.env.RESEARCH_URL?null:createHash('sha256').update(fs.readFileSync(path.join(root,publishedSite?'site/app/snapshot.js':'app/snapshot.js'))).digest('hex');
  fs.writeFileSync(path.join(out,'browser-verification.json'),JSON.stringify({checkedAt:new Date().toISOString(),status:'passed',snapshotHash,renderedPayloadHash,localReviewHashes,coverageReviewHashes,questionSelectionHashes,mode:publishedSite?'published-static-site':'analysis-files',localFileLinksChecked:checkedLinks.size,checks,runtimeErrors,viewportWidths:[1440,768,390,360],scope:'registered source coverage, frozen exploratory cohort, local condition ledger; no investment-performance certification'},null,2)+'\n');
  console.log(`PASS ${checks.length} live-system browser checks; ${pdfFiles.size} real-data PDFs saved.`);

} catch (error) {
  fs.writeFileSync(path.join(out, 'browser-verification.json'), JSON.stringify({ checkedAt: new Date().toISOString(), status: 'failed', checks, error: String(error), runtimeErrors, stderr }, null, 2) + '\n');
  console.error(error);
  process.exitCode = 1;
} finally {
  if (chrome.exitCode === null) { try { await send('Browser.close', {}, false); } catch {} }
  if (chrome.exitCode === null) await Promise.race([new Promise(resolve => chrome.once('exit', resolve)), new Promise(resolve => setTimeout(resolve, 1500))]);
  if (chrome.exitCode === null) chrome.kill('SIGTERM');
  if (chrome.exitCode !== null) fs.rmSync(profile, { recursive: true, force: true });
}
