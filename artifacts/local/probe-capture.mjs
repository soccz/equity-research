import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = process.cwd();
const publishedSite = process.argv.includes('--site');
const out = path.join(root, 'artifacts/local');
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
  await js('document.activeElement?.blur();window.scrollTo(0,0);new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  const metrics = await send('Page.getLayoutMetrics');
  const size = metrics.cssContentSize;
  const screenshot = await send('Page.captureScreenshot', {
    format: 'png', captureBeyondViewport: full,
    ...(full ? { clip: { x: 0, y: 0, width: await js('innerWidth'), height: size.height, scale: 1 } } : {})
  });
  fs.writeFileSync(path.join(out, name), Buffer.from(screenshot.data, 'base64'));
}
async function screenshotRegion(name, selector) {
  await js('document.activeElement?.blur();new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  const clip=await js(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:Math.min(r.height,2300),scale:1};})()`);
  const result=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip});
  fs.writeFileSync(path.join(out,name),Buffer.from(result.data,'base64'));
}
async function pdf(name) {
  const result = await send('Page.printToPDF', { printBackground: true, preferCSSPageSize: true, displayHeaderFooter: false });
  fs.writeFileSync(path.join(out, name), Buffer.from(result.data, 'base64'));
}

try {
 const {targetId}=await send('Target.createTarget',{url:'about:blank'},false);
 ({sessionId}=await send('Target.attachToTarget',{targetId,flatten:true},false));
 await send('Page.enable');await send('Runtime.enable');
 await send('Emulation.setDeviceMetricsOverride',{width:360,height:1050,deviceScaleFactor:1,mobile:false});
 await send('Page.navigate',{url:pathToFileURL(path.join(root,'app/index.html')).href+'#compare/auto-demand'});await ready();
 console.log(await js('JSON.stringify({inner:innerWidth,scroll:[scrollX,scrollY],root:document.querySelector(".comparison-workspace").getBoundingClientRect().toJSON(),main:document.querySelector("main").getBoundingClientRect().toJSON(),skip:{rect:document.querySelector(".skip").getBoundingClientRect().toJSON(),top:getComputedStyle(document.querySelector(".skip")).top,focus:document.activeElement.className}})'));
 await screenshot('mobile-capture-width-probe.png'); console.log(await js('JSON.stringify(document.querySelector(".comparison-workspace").getBoundingClientRect().toJSON())')); 
} finally {chrome.kill('SIGTERM');}
