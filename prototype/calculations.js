/* Pure calculations shared by the preview and its numerical checks. */
globalThis.ResearchCalculations = (() => {
  function cashBridge(values) {
    if (!Array.isArray(values) || !values.length || !values.every(Number.isFinite)) {
      throw new TypeError('Cash-flow inputs must be finite numbers.');
    }
    let running = 0;
    const steps = values.map((value, index) => {
      const start = index === 0 ? 0 : running;
      running += value;
      return { start, end: running, value, isTotal: index === 0 };
    });
    steps.push({ start: 0, end: running, value: running, isTotal: true });
    return { steps, total: running };
  }

  function fcffValue({ base = 6, growth = .08, discount = .10, terminalGrowth = .02, years = 5 } = {}) {
    if (![base, growth, discount, terminalGrowth, years].every(Number.isFinite)
      || base <= 0 || growth <= -1 || terminalGrowth <= -1 || discount <= terminalGrowth
      || discount <= -1 || !Number.isInteger(years) || years < 1 || years > 100) {
      throw new RangeError('Invalid cash-flow or discount assumptions.');
    }
    const flows = Array.from({ length: years }, (_, i) => base * (1 + growth) ** (i + 1));
    const explicitPV = flows.reduce((sum, cf, i) => sum + cf / (1 + discount) ** (i + 1), 0);
    const terminalPV = flows.at(-1) * (1 + terminalGrowth) / (discount - terminalGrowth) / (1 + discount) ** years;
    const total = explicitPV + terminalPV;
    return { flows, explicitPV, terminalPV, total, terminalShare: terminalPV / total };
  }

  function impliedGrowth(target, assumptions = {}) {
    if (!Number.isFinite(target) || target <= 0) throw new RangeError('Target value must be positive.');
    let low = -.8, high = 1;
    if (fcffValue({ ...assumptions, growth: low }).total > target
      || fcffValue({ ...assumptions, growth: high }).total < target) return null;
    for (let i = 0; i < 80; i++) {
      const mid = (low + high) / 2;
      if (fcffValue({ ...assumptions, growth: mid }).total < target) low = mid;
      else high = mid;
    }
    return (low + high) / 2;
  }

  function assessCondition({ annual, nineMonth, priorAnnual, priorNineMonth, expected = null, comparable = true }) {
    if (!comparable || ![annual, nineMonth, priorAnnual, priorNineMonth].every(Number.isFinite)) {
      return { status: 'unresolved', observed: null, prior: null, met: null, predictionCorrect: null };
    }
    if (expected !== null && typeof expected !== 'boolean') throw new TypeError('Expected outcome must be boolean or null.');
    const observed = annual - nineMonth, prior = priorAnnual - priorNineMonth;
    const met = observed > prior;
    return { status: met ? 'met' : 'not_met', observed, prior, met,
      predictionCorrect: expected === null ? null : expected === met };
  }
  return Object.freeze({ cashBridge, fcffValue, impliedGrowth, assessCondition });
})();
