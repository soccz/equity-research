import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const publishedSite = process.argv.includes('--site');
const out = path.join(root, 'artifacts/local/print-layout-check');
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
  for (const [id, name] of [['GOOGL','alphabet'],['005380','hyundai'],['030200','kt'],['ORCL','oracle'],['207940','samsung-biologics']]) {
    await go('company/' + id); await pdf(name + '.pdf');
  }
  console.log('Five candidate layouts rendered; no final snapshot approval');

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
