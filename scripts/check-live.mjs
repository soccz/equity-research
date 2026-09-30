import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
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
const pending = new Map(), runtimeErrors = [], checks = [], requests = [], checkedLinks = new Set();
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
  for (const href of await js('[...document.querySelectorAll("a[href]")].map(a=>a.href)')) {
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
  const point = await js(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.scrollIntoView({block:'center',inline:'nearest'});const r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
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
  await js('document.activeElement?.blur();window.scrollTo(0,0);new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  const metrics = await send('Page.getLayoutMetrics');
  const size = metrics.cssContentSize;
  const screenshot = await send('Page.captureScreenshot', {
    format: 'png', captureBeyondViewport: full,
    ...(full ? { clip: { x: 0, y: 0, width: size.width, height: size.height, scale: 1 } } : {})
  });
  fs.writeFileSync(path.join(out, name), Buffer.from(screenshot.data, 'base64'));
}
async function pdf(name) {
  const result = await send('Page.printToPDF', { printBackground: true, preferCSSPageSize: true, displayHeaderFooter: false });
  fs.writeFileSync(path.join(out, name), Buffer.from(result.data, 'base64'));
}

try {
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' }, false);
  ({ sessionId } = await send('Target.attachToTarget', { targetId, flatten: true }, false));
  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1050, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: process.env.RESEARCH_URL || pathToFileURL(path.join(root, publishedSite ? 'site/app/index.html' : 'app/index.html')).href });
  await ready();
  await expect('Eight real companies with a source cutoff', 'document.querySelectorAll("[data-company-row]").length===8 && document.querySelector(".preview-notice").textContent.includes(window.EQUITY_SNAPSHOT.snapshot.asOf)');
  await screenshot('desktop-universe.png'); await pdf('universe.pdf');
  await click('[data-market="US"]');
  await expect('US filter affects table and scatter', 'document.querySelectorAll("[data-company-row]").length===4 && document.querySelectorAll("svg circle").length===4');
  await click('[data-market="KR"]');
  await expect('Korean filter contains real Korean securities', '[...document.querySelectorAll("[data-company-row]")].every(r=>/^[0-9]{6}$/.test(r.dataset.companyRow))');
  await click('[data-market="ALL"]');
  await click('#candidate-only');
  await expect('Candidate filter uses declared current financial conditions', 'document.querySelectorAll("[data-company-row]").length===window.EQUITY_SNAPSHOT.snapshot.companies.filter(c=>c.assessment.priority==="심층 조사 후보").length');
  await click('#candidate-only');
  await click('[data-company="MU"]');
  await expect('Micron report contains actual dates and currency', 'document.querySelector("h1").textContent==="Micron" && document.querySelector("main").textContent.includes(window.EQUITY_SNAPSHOT.snapshot.companies.find(c=>c.id==="MU").financials.end) && document.querySelector("main").textContent.includes("십억 달러")');
  await click('[data-evidence="MU"]');
  await expect('Evidence is readable with source period and raw definitions', 'document.querySelector("dialog").open && document.querySelector("#evidence-body").textContent.includes("영업현금") && document.querySelector("#evidence-body a").href.includes("sec.gov")');
  await send('Input.dispatchKeyEvent', { type:'keyDown', key:'Escape', code:'Escape', windowsVirtualKeyCode:27 });
  await send('Input.dispatchKeyEvent', { type:'keyUp', key:'Escape', code:'Escape', windowsVirtualKeyCode:27 });
  await expect('Escape restores evidence trigger focus', '!document.querySelector("dialog").open && document.activeElement.dataset.evidence==="MU"');
  const before=await js('document.querySelector("#scenario").textContent');
  await js('document.querySelector("#cfo-shock").value=-50;document.querySelector("#cfo-shock").dispatchEvent(new Event("input",{bubbles:true}))');
  assert.notEqual(await js('document.querySelector("#scenario").textContent'),before);checks.push('Cash scenario responds to operating-cash changes');
  await js('document.querySelector("#cfo-shock").value=0;document.querySelector("#cfo-shock").dispatchEvent(new Event("input",{bubbles:true}))');
  await screenshot('desktop-micron.png'); await pdf('micron.pdf');
  for(const id of ['NVDA','GOOGL','AAPL','000660','005930','035420','066570']){
    await go('company/'+id);
    await expect('Individual real report '+id, 'document.querySelector("main").textContent.includes('+JSON.stringify(id)+') && !!document.querySelector("#scenario")');
  }
  await go('company/NVDA');
  await expect('NVIDIA broader investment scope remains visible', 'document.querySelector("main").textContent.includes("유형·무형자산 취득")');
  await go('company/000660'); await screenshot('desktop-hynix.png'); await pdf('sk-hynix.pdf');
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
  await expect('Eight actual frozen conditions without fabricated accuracy', 'document.querySelectorAll(".record-card").length===window.EQUITY_SNAPSHOT.ledger.length && document.querySelector("main").textContent.includes("사전 예측 없음") && document.querySelector("main").textContent.includes("외부 시점 인증")');
  await screenshot('desktop-tracking.png'); await pdf('conditions.pdf');
  await expect('Published history needs no local mutation service', '!document.querySelector("[data-operation]")');
  await go('sources');
  await expect('All companies expose primary sources and preserved copies', 'document.querySelectorAll(".source-list>li").length===8 && document.querySelector("main").textContent.includes("SHA-256")');
  assert.equal(requests.some(r=>r.method==='POST'||/\/api\//.test(new URL(r.url).pathname)),false);
  checks.push('All research views work without backend API calls');
  await screenshot('desktop-sources.png');
  for(const width of [360,390,768]){
    await viewport(width,900);
    for(const view of ['universe','company/000660','lab','tracking','sources']){
      await go(view);
      await expect(`No document overflow ${width}px ${view}`, 'document.documentElement.scrollWidth<=innerWidth+1');
      if(width===390)await screenshot('mobile-'+view.split('/')[0]+'.png');
    }
  }
  await expect('No visible undefined values', '!/NaN|undefined/.test(document.querySelector("main").textContent)');
  assert.equal(runtimeErrors.length,0,JSON.stringify(runtimeErrors));checks.push('No browser JavaScript exceptions');
  const snapshotHash=await js('window.EQUITY_SNAPSHOT.snapshot.contentHash');
  fs.writeFileSync(path.join(out,'browser-verification.json'),JSON.stringify({checkedAt:new Date().toISOString(),status:'passed',snapshotHash,mode:publishedSite?'published-static-site':'analysis-files',localFileLinksChecked:checkedLinks.size,checks,runtimeErrors,viewportWidths:[1440,768,390,360],scope:'real source data, eight companies, exploratory research, published condition ledger; no investment-performance certification'},null,2)+'\n');
  console.log(`PASS ${checks.length} live-system browser checks; 6 real-data PDFs saved.`);

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
