import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = path.join(root, 'artifacts');
const tempRoot = '/home/soccz/22tb/tmp';
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
const pending = new Map(), runtimeErrors = [], checks = [];
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
    } else if (message.method === 'Runtime.exceptionThrown') runtimeErrors.push(message.params.exceptionDetails);
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
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1050, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: pathToFileURL(path.join(root, 'prototype/index.html')).href });
  await ready();
  await expect('Initial screen has six explicitly synthetic companies', 'document.querySelectorAll("[data-company-row]").length===6 && document.querySelector(".preview-notice").textContent.includes("가상")');
  await screenshot('desktop-screen.png');
  await pdf('comparison-preview.pdf');
  await click('[data-market="US"]');
  await expect('US filter applies to all visible companies and chart dots', '[...document.querySelectorAll("[data-company-row]")].every(r=>r.dataset.companyRow.startsWith("US")) && document.querySelectorAll("[data-company-row]").length===3 && document.querySelectorAll("svg circle").length===3');
  await click('[data-market="KR"]');
  await expect('KR filter applies to the same comparison view', '[...document.querySelectorAll("[data-company-row]")].every(r=>r.dataset.companyRow.startsWith("KR")) && document.querySelectorAll("[data-company-row]").length===3');
  await click('[data-market="ALL"]');
  await click('[data-company="KR-A"]');
  await expect('Company navigation opens the selected company and cash bridge', 'document.querySelector("h1").textContent==="정밀제조 A" && document.querySelector(".cash-panel").textContent.includes("130")');
  await click('[data-source="cash"]');
  await expect('Evidence opens with the accounting limitation', 'document.querySelector("dialog").open && document.querySelector("#evidence-body").textContent.includes("현금 유입")');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await new Promise(resolve => setTimeout(resolve, 70));
  await expect('Escape closes evidence and returns keyboard focus', '!document.querySelector("dialog").open && document.activeElement.dataset.source==="cash"');
  const before = await js('Number(document.querySelector("#valuation-total").textContent)');
  await js('document.querySelector("#growth").value=16;document.querySelector("#growth").dispatchEvent(new Event("input",{bubbles:true}))');
  assert.ok(await js('Number(document.querySelector("#valuation-total").textContent)') > before); checks.push('Growth slider recalculates enterprise value');
  const highGrowth = await js('Number(document.querySelector("#valuation-total").textContent)');
  await js('document.querySelector("#discount").value=14;document.querySelector("#discount").dispatchEvent(new Event("input",{bubbles:true}))');
  assert.ok(await js('Number(document.querySelector("#valuation-total").textContent)') < highGrowth); checks.push('Discount slider recalculates enterprise value');
  await js('document.querySelector("#growth").value=8;document.querySelector("#growth").dispatchEvent(new Event("input",{bubbles:true}));document.querySelector("#discount").value=10;document.querySelector("#discount").dispatchEvent(new Event("input",{bubbles:true}))');
  for (const id of ['KR-B', 'KR-C', 'US-A', 'US-B', 'US-C', 'KR-A']) {
    await js(`document.querySelector('#company-select').value=${JSON.stringify(id)};document.querySelector('#company-select').dispatchEvent(new Event('change',{bubbles:true}))`); await ready();
    await expect(`Company ${id} has its own identity and evidence`, `document.querySelector('#company-select').value===${JSON.stringify(id)} && document.querySelector('.metadata').textContent.includes(${JSON.stringify(id)})`);
  }
  await screenshot('desktop-company.png'); await pdf('company-preview.pdf');
  await js('window.scrollTo(0,document.body.scrollHeight)');
  await click('[data-view="research"]');
  await expect('Report navigation restores the top and focuses the report', 'scrollY===0 && document.activeElement===document.querySelector("main")');
  await expect('Research graphics load and disclose the portfolio analysis unit', 'document.querySelector(".research-image").naturalWidth>0 && document.querySelector("main").textContent.includes("분석 단위: WML 포트폴리오")');
  await screenshot('desktop-research-loss.png');
  await click('[data-metric="performance"]');
  await expect('Performance view uses confidence intervals instead of forecast loss', 'document.querySelector(".research-image").currentSrc.includes("performance") && document.querySelector("#research-chart-title").textContent.includes("95%")');
  await screenshot('desktop-research-performance.png'); await pdf('research-note.pdf');
  await click('[data-source="research"]');
  await expect('Research evidence links to a portable source snapshot', 'document.querySelector("#evidence-body a").getAttribute("href")==="../evidence/wml-variance-20260929.html"');
  await click('[data-action="close-dialog"]');
  await go('followup');
  await expect('Missing observation is unresolved', 'document.querySelector("#condition-status").textContent==="자료 미확인"');
  await click('[data-ledger="met"]');
  await expect('Annual minus nine-month calculation fulfills the growth condition', 'document.querySelector("#condition-status").textContent==="조건 충족" && document.querySelector(".ledger-outcome").textContent.includes("500 − 370 = 130")');
  await click('[data-ledger="not_met"]');
  await expect('Unfulfilled condition without a forecast is not a forecast failure', 'document.querySelector("#condition-status").textContent==="조건 미충족" && document.querySelector(".ledger-outcome").textContent.includes("채점 대상 없음")');
  await screenshot('desktop-followup.png'); await pdf('followup-preview.pdf');
  for (const width of [360, 390, 768]) {
    await viewport(width, 900);
    for (const view of ['screen', 'company/KR-A', 'research', 'followup']) {
      await go(view);
      await expect(`No document overflow at ${width}px on ${view}`, 'document.documentElement.scrollWidth<=innerWidth+1');
      if (view==='research' && width<600) await expect(`Mobile research figure at ${width}px`, 'document.querySelector(".research-image").currentSrc.includes("-mobile.svg")');
      if (view==='company/KR-A' && width<600) await expect(`Readable cash bridge at ${width}px`, 'getComputedStyle(document.querySelector(".cash-chart-narrow")).display!=="none" && getComputedStyle(document.querySelector(".cash-chart-wide")).display==="none"');
      if (width===390) await screenshot(`mobile-${view.split('/')[0]}.png`);
    }
  }
  await expect('No unresolved image loads', '[...document.images].every(i=>i.complete&&i.naturalWidth>0)');
  assert.equal(runtimeErrors.length, 0, JSON.stringify(runtimeErrors));
  checks.push('No browser JavaScript exceptions');
  fs.writeFileSync(path.join(out, 'browser-verification.json'), JSON.stringify({ checkedAt: new Date().toISOString(), status: 'passed', checks, runtimeErrors, viewportWidths: [1440, 768, 390, 360], browser: 'isolated headless Google Chrome', dataScope: 'synthetic companies; attributed historical WML research excerpt; no live recommendations' }, null, 2) + '\n');
  console.log(`PASS ${checks.length} browser checks; screenshots and 4 PDF previews saved.`);
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
