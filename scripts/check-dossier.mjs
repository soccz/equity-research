import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const sandbox={window:{},structuredClone};
vm.runInNewContext(fs.readFileSync(new URL('../app/dossier.js',import.meta.url),'utf8'),sandbox);
const value=sandbox.window.EquityDossier.pricing;
assert.ok(Math.abs(value(1000,0,.1,0).requiredBaseCash-100)<1e-10);
assert.ok(value(1000,.1,.14).requiredBaseCash>value(1000,.1,.08).requiredBaseCash);
assert.ok(value(1000,.2,.11).requiredBaseCash<value(1000,0,.11).requiredBaseCash);
assert.throws(()=>value(1000,.1,.02,.02));
const pointer=JSON.parse(fs.readFileSync(new URL('../data/latest.json',import.meta.url),'utf8'));
const snapshot=JSON.parse(fs.readFileSync(new URL('../'+pointer.snapshot,import.meta.url),'utf8'));
let comparisons=0;
for(const c of snapshot.companies)for(const p of [c.dossier?.pricing,c.business?.pricing].filter(Boolean))for(const row of p.sensitivity){
  const r=value(p.marketCapProxy,row.growth,row.discount);
  assert.ok(Math.abs(r.requiredBaseCash/row.requiredBaseCash-1)<1e-12);
  assert.ok(Math.abs(r.terminalShare-row.terminalShare)<1e-12);
  comparisons++;
}
assert.equal(comparisons,snapshot.companies.reduce((n,c)=>n+[c.dossier?.pricing,c.business?.pricing].filter(Boolean).length*9,0));
console.log('PASS equity cash scenario: analytical identity, directional sensitivity, invalid assumptions, '+comparisons+' Python/JS comparisons.');

vm.runInNewContext(fs.readFileSync(new URL('../app/valuation.js',import.meta.url),'utf8'),sandbox);
let cashCases=0;
for(const c of snapshot.companies){
  const v=c.valuation;if(v?.status!=='workspace')continue;
  for(const p of v.cases){
    const shares=v.security.status==='available'?v.security.shares.value:null;
    const r=sandbox.window.EquityValuation.calculate(v.revenueBase,p.cfoMargin,p.investmentMargin,v.defaults.burdenMargin,v.defaults.growth,v.defaults.discount,shares);
    assert.ok(Math.abs(r.cash-p.cash)<Math.max(1,Math.abs(p.cash)*1e-12));
    if(p.price===null)assert.equal(r.price,null);else assert.ok(Math.abs(r.price/p.price-1)<1e-12);
    cashCases++;
  }
}
assert.equal(cashCases,snapshot.companies.filter(c=>c.valuation?.status==='workspace').length*3);
console.log('PASS '+cashCases+' historical cash/price Python/JS comparisons, including held securities and negative cash.');

let reverseCases=0;
for(const horizon of [5,10,15,20])for(const growth of [-.2,0,.15,.7]){
  const cash=value(1000,growth,.12,.03,horizon).requiredBaseCash;
  const result=sandbox.window.EquityValuation.impliedGrowth(1000,cash,.12,.03,horizon);
  assert.equal(result.status,'solved');assert.ok(Math.abs(result.growth-growth)<1e-11);reverseCases++;
}
console.log('PASS '+reverseCases+' implied-growth roots across explicit forecast horizons.');

// Run both implementations against the same explicit business assumptions.
vm.runInNewContext(fs.readFileSync(new URL('../app/operating-model.js',import.meta.url),'utf8'),sandbox);
const paths=[];
for(const c of snapshot.companies){
  const m=c.operatingModel;if(m?.status!=='research_workspace')continue;
  const changes=[{}, {discount:.15}, {capexEnd:.05}, {workingCapital:.1}];
  if(m.unallocatedPath)changes.push({corporateStart:m.defaults.corporateStart+.01,corporateEnd:m.defaults.corporateEnd+.01});
  if(m.consolidationPath)changes.push({eliminationEnd:.15},{otherProfitStart:-.01,otherProfitEnd:.02},{minority:.04},{eliminationStart:.99,eliminationEnd:.99,workingCapital:-.3,tax:0,terminal:.03});
  if(m.normalizationPath)changes.push({excludedProfitStart:.002,excludedProfitEnd:.003});
  if(m.minorityPath)changes.push({minority:.02});
  if(m.capexLimit>1)changes.push({capexStart:1.5,capexEnd:1.2},{capexStart:2,capexEnd:.15});
  if(m.equityInvestmentPath)changes.push({equityInvestmentValue:0},{equityInvestmentValue:12e12},{equityInvestmentValue:m.security.marketCapProxy});
  if(m.contentPath)changes.push({contentStart:0,contentEnd:0},{contentStart:.3,contentEnd:.5});
  if(m.reservePath)changes.push({warrantyUseEnd:.06});
  if(m.grossProfitPath)changes.push({researchEnd:.1});
  for(const change of changes)paths.push({company:c.id,model:m,assumptions:{...structuredClone(m.defaults),...change}});
}
const python=spawnSync('python3',['-c','import json,sys; from equitylab.operating_model import calculate; print(json.dumps([calculate(x["model"],x["assumptions"]) for x in json.load(sys.stdin)]))'],{cwd:fileURLToPath(new URL('..',import.meta.url)),input:JSON.stringify(paths),encoding:'utf8',timeout:120000,maxBuffer:8*1024*1024});
assert.equal(python.status,0,python.error?.message||python.stderr);
const expected=JSON.parse(python.stdout);
function same(actual,wanted,path){
  if(typeof wanted==='number'){assert.ok(Number.isFinite(actual)&&Math.abs(actual-wanted)<=Math.max(1e-9,Math.abs(wanted)*1e-12),path);return;}
  if(wanted===null||typeof wanted!=='object'){assert.equal(actual,wanted,path);return;}
  assert.deepEqual(Object.keys(actual).sort(),Object.keys(wanted).sort(),path);
  for(const k of Object.keys(wanted))same(actual[k],wanted[k],path+'.'+k);
}
paths.forEach((x,i)=>same(sandbox.window.EquityOperatingModel.calculate(x.model,x.assumptions),expected[i],x.company+'/'+i));
console.log('PASS '+paths.length+' complete business-cash Python/JS paths, including every year, taxes, corporate costs and held rights.');

const capital=snapshot.companies.find(c=>c.id==='GOOGL').valuation.security.capitalReview;
assert.ok(capital);
const conversionCases=capital.terms.flatMap(term=>[150,term.initialPrice-.01,term.initialPrice,term.initialPrice+.01,400,440,term.thresholdPrice-.01,term.thresholdPrice,term.thresholdPrice+.01,700].map(price=>({term,price})));
const capitalPython=spawnSync('python3',['-c','import json,sys; from equitylab.alphabet_capital import conversion; print(json.dumps([conversion(x["term"],x["price"]) for x in json.load(sys.stdin)]))'],{cwd:fileURLToPath(new URL('..',import.meta.url)),input:JSON.stringify(conversionCases),encoding:'utf8',timeout:30000});
assert.equal(capitalPython.status,0,capitalPython.error?.message||capitalPython.stderr);
const capitalExpected=JSON.parse(capitalPython.stdout);
conversionCases.forEach((x,i)=>assert.equal(sandbox.window.EquityValuation.preferredConversion(x.term,x.price),capitalExpected[i]));
console.log('PASS '+conversionCases.length+' preferred conversion contract Python/JS boundaries; full security allocation remains held.');

const inversePaths=snapshot.companies.filter(c=>c.operatingModel?.status==='research_workspace').flatMap(c=>[{}, {discount:.15}, {tax:0,capexEnd:.02}].map(change=>({company:c.id,model:c.operatingModel,assumptions:{...structuredClone(c.operatingModel.defaults),...change}})));
for(const c of snapshot.companies.filter(c=>c.operatingModel?.equityInvestmentPath))for(const value of [0,12e12,c.operatingModel.security.marketCapProxy])inversePaths.push({company:c.id,model:c.operatingModel,assumptions:{...structuredClone(c.operatingModel.defaults),equityInvestmentValue:value}});
const inversePython=spawnSync('python3',['-c','import json,sys; from equitylab.operating_inverse import margins; print(json.dumps([margins(x["model"],x["assumptions"]) for x in json.load(sys.stdin)]))'],{cwd:fileURLToPath(new URL('..',import.meta.url)),input:JSON.stringify(inversePaths),encoding:'utf8',timeout:120000,maxBuffer:8*1024*1024});
assert.equal(inversePython.status,0,inversePython.error?.message||inversePython.stderr);
const inverseExpected=JSON.parse(inversePython.stdout);
inversePaths.forEach((x,i)=>same(sandbox.window.EquityOperatingModel.marginRequirements(x.model,x.assumptions),inverseExpected[i],x.company+'/inverse/'+i));
console.log('PASS '+inversePaths.length+' complete business-margin inverse Python/JS scenarios; bounds, residuals and held securities retained.');
