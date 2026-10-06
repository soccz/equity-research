import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const publishedSite = process.argv.includes('--site');
const out = path.join(root, 'artifacts/homepage');
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
  await send('Page.enable'); await send('Runtime.enable');
  await send('Network.enable');
  await send('Network.setBlockedURLs', {urls:['*api.github.com*']});
  await send('Page.navigate', {url:pathToFileURL(path.join(root,'deploy/homepage/index.html')).href});
  for(let i=0;i<100;i++) {
    if(await js('document.readyState==="complete" && typeof renderPosts==="function"')) break;
    await new Promise(r=>setTimeout(r,50));
  }
  await js('allRepos=mergeStaticProjects([]);currentCat="project";showPage("blog");true');
  assert.equal(await js('getCat("equity-research")'),'project');
  assert.equal(await js('allRepos.filter(r=>r.name==="equity-research").length'),1);
  assert.equal(await js(`[...document.querySelectorAll('.post-card')].some(e=>e.dataset.url==='/equity-research/')`),true);
  for (const width of [1440,390]) {
    await send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:width<600});
    await new Promise(r=>setTimeout(r,150));
    assert.equal(await js('document.documentElement.scrollWidth<=innerWidth+1'),true);
    await screenshot('homepage-'+width+'.png');
  }
  assert.equal(runtimeErrors.length,0,JSON.stringify(runtimeErrors));
  fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify({status:'passed',checks:['static fallback','category','project link','desktop 1440','mobile 390','no JS exceptions']},null,2));
  console.log('Homepage: category, fallback, link, desktop/mobile, JS passed.');
} finally {
  try { await send('Browser.close',{},false); } catch {}
  chrome.kill();
  fs.rmSync(profile,{recursive:true,force:true});
}
