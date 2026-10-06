import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';
const p=JSON.parse(fs.readFileSync(new URL('./cash-path-cases.json',import.meta.url))),box={window:{},structuredClone};vm.createContext(box);vm.runInContext(fs.readFileSync(new URL('../../../app/operating-model.js',import.meta.url),'utf8'),box);
function same(a,b,path){if(typeof b==='number'){assert.ok(Number.isFinite(a));assert.ok(Math.abs(a-b)<=1e-9*Math.max(1,Math.abs(b)),path+': '+a+' != '+b);}else if(b&&typeof b==='object'){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),path);for(const k of Object.keys(b))same(a[k],b[k],path+'/'+k);}else assert.equal(a,b,path);}
p.cases.forEach((c,i)=>{same(box.window.EquityOperatingModel.calculate(p.model,c.assumptions),c.calculation,'cash/'+i);same(box.window.EquityOperatingModel.marginRequirements(p.model,c.assumptions),c.inverse,'inverse/'+i);});console.log('PASS '+p.cases.length+' whole Oracle cash and inverse Python/JS paths');

for(const capexLimit of [true,null,0,4,Infinity])assert.throws(()=>box.window.EquityOperatingModel.calculate({...p.model,capexLimit},p.model.defaults));
const unbounded={...p.model};delete unbounded.capexLimit;assert.throws(()=>box.window.EquityOperatingModel.calculate(unbounded,p.model.defaults));
console.log("PASS capex metadata rejects invalid limits and keeps other models bounded");
