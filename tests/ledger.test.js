const test = require('node:test'); const assert = require('node:assert');
const L = require('../mis/ledger.js');
const T = (date, type, ticker, qty, price, fees = 0) => ({ date, type, ticker, qty, price, fees });

test('FIFO realised gains and remaining lots', () => {
  const led = L.buildLedger([T('2023-01-01', 'buy', 'A.NS', 10, 100), T('2023-06-01', 'buy', 'A.NS', 10, 200), T('2024-03-01', 'sell', 'A.NS', 15, 300)]);
  assert.equal(led.realized.reduce((a, r) => a + r.pnl, 0), 10 * 200 + 5 * 100);
  assert.equal(L.positions(led)[0].qty, 5); assert.ok(led.realized[0].days > 365);
});
test('fees are part of cost and proceeds', () => {
  const led = L.buildLedger([T('2023-01-01', 'buy', 'A.NS', 10, 100, 10), T('2023-02-01', 'sell', 'A.NS', 10, 110, 10)]);
  assert.ok(Math.abs(led.realized[0].pnl - (1100 - 10 - 1010)) < 1e-9);
});
test('selling more than held is rejected, position unchanged', () => {
  const led = L.buildLedger([T('2023-01-01', 'buy', 'A.NS', 1, 100), T('2023-02-01', 'sell', 'A.NS', 5, 100)]);
  assert.ok(led.errors.length === 1); assert.equal(L.positions(led)[0].qty, 1);
});
test('split and bonus keep total cost and scale quantity; dividend uses shares held then', () => {
  const led = L.buildLedger([T('2023-01-01', 'buy', 'A.NS', 10, 100), T('2023-02-01', 'split', 'A.NS', 5, 0), T('2023-03-01', 'bonus', 'A.NS', 1, 0), T('2023-04-01', 'dividend', 'A.NS', 1, 2)]);
  const p = L.positions(led)[0]; assert.equal(p.qty, 100); assert.ok(Math.abs(p.avg * p.qty - 1000) < 1e-6); assert.equal(led.dividends['A.NS'], 200);
});
test('XIRR known value and non-convergence', () => {
  const r = L.xirr([{ date: new Date('2023-01-01'), amt: -1000 }, { date: new Date('2024-01-01'), amt: 1100 }]);
  assert.ok(Math.abs(r - 0.10) < 0.002); assert.equal(L.xirr([{ date: new Date('2023-01-01'), amt: -1 }]), null);
});
test('portfolio XIRR refuses undated positions and short histories', () => {
  assert.equal(L.portfolioXirr([T('', 'buy', 'A.NS', 1, 100)], 110, new Date('2026-10-16')).value, null);
  assert.equal(L.portfolioXirr([T('2026-09-20', 'buy', 'A.NS', 1, 100)], 110, new Date('2026-10-16')).value, null);
  const ok = L.portfolioXirr([T('2025-10-16', 'buy', 'A.NS', 10, 100)], 1100, new Date('2026-10-16')); assert.ok(Math.abs(ok.value - 0.10) < 0.01);
});
test('benchmark: same cash flows in the index', () => {
  const bench = [['2025-10-16', 100], ['2026-10-16', 120]];
  const b = L.benchXirr([T('2025-10-16', 'buy', 'A.NS', 10, 100)], bench, new Date('2026-10-16')); assert.ok(Math.abs(b - 0.20) < 0.01);
  assert.equal(L.benchXirr([T('2020-01-01', 'buy', 'A.NS', 1, 1)], bench, new Date('2026-10-16')), null);   // no index price that early
});
test('CSV validation reports every bad row and keeps good ones; duplicates flagged', () => {
  const r = L.parseCSV('date,type,ticker,quantity,price,fees\n2025-13-01,buy,A,1,1,0\n2025-02-01,hold,A,1,1,0\n2025-02-01,buy,A,-1,1,0\n2025-02-01,buy,A,2,50,0\n2025-02-01,buy,A,2,50,0\n');
  assert.equal(r.rows.length, 1); assert.equal(r.errors.length, 4); assert.ok(r.errors.some(e => /duplicate/.test(e))); assert.equal(r.rows[0].ticker, 'A.NS');
  assert.ok(L.parseCSV('a,b\n1,2').errors[0].includes('Missing column'));
});
test('tax estimate is only an estimate and splits short/long term', () => {
  const t = L.taxEstimate([{ sellDate: '2026-06-01', pnl: 1000, days: 100 }, { sellDate: '2026-06-01', pnl: 200000, days: 500 }, { sellDate: '2025-01-01', pnl: 99999, days: 10 }], '2026-04-01');
  assert.equal(t.stcg, 1000); assert.equal(t.ltcg, 200000); assert.ok(Math.abs(t.tax - (200 + (200000 - 125000) * 0.125)) < 1e-6);
});

test('AUDIT: XIRR is unavailable (not wrong) when any holding has no price', () => {
  const txs = [T('2025-01-02', 'buy', 'A.NS', 10, 1000), T('2025-01-02', 'buy', 'B.NS', 100, 1000)];
  const wrong = L.portfolioXirr(txs, 12000, new Date('2026-10-16'));                    // end value that omits B: the old behaviour
  assert.ok(wrong.value < -0.5, 'demonstrates the old wrong number: ' + wrong.value);
  const r = L.portfolioXirr(txs, 12000, new Date('2026-10-16'), ['B.NS']);
  assert.equal(r.value, null); assert.match(r.why, /no price/);
  assert.ok(L.portfolioXirr(txs, 115000, new Date('2026-10-16'), []).value !== null);   // priced: still computed
});
