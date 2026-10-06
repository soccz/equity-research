import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const context = {};
vm.runInNewContext(fs.readFileSync(path.join(root, 'prototype/calculations.js'), 'utf8'), context);
const c = context.ResearchCalculations;
let checks = 0;
const check = (name, fn) => { fn(); checks++; console.log(`PASS ${name}`); };
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} differs from ${b}`);

check('FCFF with constant perpetual growth equals the closed-form value at 1, 5 and 20 years', () => {
  for (const years of [1, 5, 20]) close(c.fcffValue({ growth: .02, discount: .10, years }).total, 6 * 1.02 / .08);
});
check('Higher discount rates lower value; higher cash-flow growth raises value', () => {
  const base = c.fcffValue().total;
  assert.ok(c.fcffValue({ discount: .12 }).total < base);
  assert.ok(c.fcffValue({ growth: .12 }).total > base);
});
check('Reverse valuation recovers the target independently of displayed rounding', () => {
  for (const discount of [.08, .10, .14]) {
    const growth = c.impliedGrowth(100, { discount });
    close(c.fcffValue({ growth, discount }).total, 100);
  }
});
check('Terminal assumptions reject undefined or economically invalid denominators', () => {
  for (const assumptions of [{ discount: .02 }, { discount: .01 }, { growth: NaN }, { years: 2.5 }]) assert.throws(() => c.fcffValue(assumptions));
});
check('Signed cash adjustments reconcile and preserve negative cash flows', () => {
  close(c.cashBridge([120, 30, -20, -15, 10, 5]).total, 130);
  close(c.cashBridge([-20, 30, -15]).total, -5);
  assert.throws(() => c.cashBridge([120, NaN]));
});
const base = { annual: 500, nineMonth: 370, priorAnnual: 480, priorNineMonth: 360 };
check('Standalone Q4 uses annual minus nine-month values', () => {
  const result = c.assessCondition(base);
  assert.equal(result.observed, 130); assert.equal(result.prior, 120); assert.equal(result.met, true);
});
check('A condition without a prediction cannot be scored as a prediction failure', () => {
  const result = c.assessCondition({ ...base, annual: 480 });
  assert.equal(result.met, false); assert.equal(result.predictionCorrect, null);
});
check('Missing or incomparable data are unresolved rather than negative outcomes', () => {
  assert.equal(c.assessCondition({ ...base, annual: null }).status, 'unresolved');
  assert.equal(c.assessCondition({ ...base, comparable: false }).status, 'unresolved');
});
check('An explicitly registered prediction is scored separately; equality is not growth', () => {
  assert.equal(c.assessCondition({ ...base, annual: 490, expected: true }).predictionCorrect, false);
  assert.equal(c.assessCondition({ ...base, expected: true }).predictionCorrect, true);
});
console.log(`${checks} calculation and judgment-contract checks passed.`);
