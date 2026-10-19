const test = require('node:test'); const assert = require('node:assert');
const M = require('../mis/dashboard_logic.js');
const rules = { maxSingle: 8, maxSector: 30, maxSmall: 50, buyCostPct: 0.15, maxStocks: 4, minPositions: 10, minPerPosition: 4000, concCapBuilding: 20 };
const OK = { debt: 'no', emergency: 'ok' };
const mk = (t, o = {}) => ({ ticker: t, name: t, sector: 'IT', cap: 'M', price: 500, asof: '2026-10-15', fresh: true, research: 75, entry: 70, status: 'ACCUMULATE CANDIDATE',
  why: ['ok'], confidence: { label: 'Medium', pct: 90, limits: ['x'] }, gov: 'ok', atr: 10, atrPct: 2, ext200: 5, chg1d: 1, chg1m: 4, bear: -20, invalidation: ['governance event'],
  zones: { ideal: [480, 520], thesis_review: 400, trading_stop: 470, distance_pct: 0, position: 'in_range' }, ...o });
const stocks = ['A', 'B', 'C', 'D', 'E'].map((t, i) => mk(t, { price: 400 + i * 100, research: 80 - i, sector: ['IT', 'Auto', 'Health', 'IT', 'Auto'][i],
  zones: { ideal: [(400 + i * 100) * .97, (400 + i * 100) * 1.03], thesis_review: 300, trading_stop: 280, distance_pct: 0, position: 'in_range' } }));
const byT = Object.fromEntries(stocks.map(s => [s.ticker, s]));
const empty = M.portfolio([], byT);

test('plan: budget, whole shares, max stocks, cash left', () => {
  const p = M.monthlyPlan(20000, OK, stocks, empty, rules);
  assert.ok(p.rows.length >= 1 && p.rows.length <= 4);
  assert.ok(p.rows.reduce((a, r) => a + r.amount + r.cost, 0) <= 20000 + 1e-6);
  p.rows.forEach(r => assert.ok(Number.isInteger(r.shares) && r.shares > 0)); assert.ok(p.cashLeft >= 0);
});
test('safety gate: unverified is a preview and NEVER approvable', () => {
  const p = M.monthlyPlan(20000, { debt: null, emergency: null }, stocks, empty, rules);
  assert.equal(p.gate.status, 'UNVERIFIED'); assert.equal(p.approvable, false); assert.match(p.verdict, /PREVIEW ONLY/);
  assert.equal(M.monthlyPlan(20000, { debt: 'no', emergency: null }, stocks, empty, rules).approvable, false);
});
test('safety gate: verified plan is approvable only with real data', () => {
  assert.equal(M.monthlyPlan(20000, OK, stocks, empty, rules, { mode: 'real' }).approvable, true);
  assert.equal(M.monthlyPlan(20000, OK, stocks, empty, rules, { mode: 'synthetic' }).approvable, false);
});
test('safety gate: expensive debt closes; low emergency halves', () => {
  const p = M.monthlyPlan(20000, { debt: 'yes', emergency: 'ok' }, stocks, empty, rules);
  assert.equal(p.rows.length, 0); assert.equal(p.approvable, false); assert.match(p.verdict, /NO PURCHASE/);
  assert.equal(M.safetyGate(20000, { debt: 'no', emergency: 'low' }).budget, 10000);
});
test('zero-purchase plan is available (nothing in range)', () => {
  const none = stocks.map(s => ({ ...s, status: 'WATCH' }));
  const p = M.monthlyPlan(20000, OK, none, empty, rules); assert.equal(p.rows.length, 0); assert.match(p.verdict, /NO PURCHASE/);
});
test('stale or unavailable data never produces a purchase, even if the user selects it', () => {
  assert.equal(M.monthlyPlan(20000, OK, stocks.map(s => ({ ...s, fresh: false })), empty, rules).rows.length, 0);
  const sel = M.monthlyPlan(20000, OK, stocks.map(s => ({ ...s, status: 'DATA UNAVAILABLE' })), empty, rules, { selected: ['A', 'B'] });
  assert.equal(sel.rows.length, 0); assert.ok(sel.skipped.length >= 2);
});
test('AVOID / governance red flag is excluded even when selected', () => {
  const p = M.monthlyPlan(20000, OK, [mk('X', { gov: 'red_flag' }), mk('Y')], empty, rules, { selected: ['X', 'Y'] });
  assert.ok(!p.rows.some(r => r.ticker === 'X'));
});
test('entry range consistency: out-of-range pick is flagged pending and explained, never shown as inside the range', () => {
  const s = [mk('Z', { price: 600, zones: { ideal: [480, 520], thesis_review: 400, trading_stop: 450, distance_pct: 15.4, position: 'above' } })];
  const p = M.monthlyPlan(20000, OK, s, empty, rules, { selected: ['Z'] });
  assert.equal(p.rows[0].inRange, false); assert.equal(p.rows[0].limit, 520); assert.equal(p.approvable, false);       // nothing in range => not approvable
  assert.match(p.verdict, /pending limit orders/);
});
test('automatic picks only include stocks inside their entry range', () => {
  const mixed = [mk('IN'), mk('OUT', { status: 'WATCH', price: 700 })];
  assert.deepEqual(M.monthlyPlan(20000, OK, mixed, empty, rules).rows.map(r => r.ticker), ['IN']);
});
test('methods: equal vs risk-adjusted differ; overrides respected; staged tranches add up', () => {
  const two = [mk('L', { price: 300, atrPct: 1.5, research: 70, zones: { ideal: [290, 310], thesis_review: 250, trading_stop: 260, distance_pct: 0, position: 'in_range' } }),
               mk('H', { price: 300, atrPct: 4, research: 70, zones: { ideal: [290, 310], thesis_review: 250, trading_stop: 260, distance_pct: 0, position: 'in_range' } })];
  const eq = M.monthlyPlan(24000, OK, two, empty, rules, { method: 'equal' }), rk = M.monthlyPlan(24000, OK, two, empty, rules, { method: 'risk' });
  const w = (p, t) => p.rows.find(r => r.ticker === t).weightPlanned;
  assert.ok(Math.abs(w(eq, 'L') - w(eq, 'H')) < 1e-6); assert.ok(w(rk, 'L') > w(rk, 'H'));
  const ov = M.monthlyPlan(24000, OK, two, empty, rules, { method: 'equal', overrides: { L: 80, H: 20 } });
  assert.ok(Math.abs(w(ov, 'L') - 80) < 1e-6);
  const st = M.stageRow(rk.rows[0]); assert.equal(st.tranches.reduce((a, t) => a + t.shares, 0), rk.rows[0].shares);
});
test('unaffordable share is skipped with a reason', () => {
  const big = [mk('BIG', { price: 50000, zones: { ideal: [49000, 51000], thesis_review: 40000, trading_stop: 1, distance_pct: 0, position: 'in_range' } })];
  const p = M.monthlyPlan(10000, OK, big, empty, rules); assert.equal(p.rows.length, 0); assert.ok(p.skipped[0].reason.includes('bigger than its slice'));
});
test('limits: sector, single-stock and small-cap caps apply from 10 holdings', () => {
  const hold = []; for (let i = 0; i < 10; i++) hold.push({ ticker: 'H' + i, qty: 10, avg: 100, manualPrice: 100 });
  const meta = {}; hold.forEach((h, i) => { meta[h.ticker] = mk(h.ticker, { cap: i < 7 ? 'S' : 'M', sector: 'S' + i, price: 100 }); });
  const port = M.portfolio(hold, { ...byT, ...meta });
  const small = stocks.map(s => ({ ...s, cap: 'S' }));
  const p = M.monthlyPlan(20000, OK, small, port, rules); assert.equal(p.rows.length, 0); assert.ok(p.skipped.some(x => /small-cap/.test(x.reason)));
  const same = Array.from({ length: 10 }, (_, i) => ({ ticker: 'T' + i, qty: 10, avg: 100, manualPrice: 100 }));
  const sm = {}; same.forEach(h => { sm[h.ticker] = mk(h.ticker, { sector: 'IT', cap: 'M', price: 100 }); });
  const p2 = M.monthlyPlan(20000, OK, stocks.map(s => ({ ...s, sector: 'IT' })), M.portfolio(same, { ...byT, ...sm }), rules);
  assert.equal(p2.rows.length, 0); assert.ok(M.concentrationBreaches(M.portfolio(same, { ...byT, ...sm }), rules).some(b => b.kind === 'sector'));
});
test('limits are not alarmed while building (fewer than 10 holdings)', () => {
  const port = M.portfolio([{ ticker: 'A', qty: 10, avg: 100 }, { ticker: 'B', qty: 1, avg: 100 }], byT);
  assert.equal(M.concentrationBreaches(port, rules).length, 0);
});
test('holding states: only the six allowed states appear', () => {
  const hold = [{ ticker: 'A', qty: 100, avg: 300 }, { ticker: 'B', qty: 2, avg: 500 }, { ticker: 'ZZ.NS', qty: 1, avg: 5 }, { ticker: 'QQ.NS', qty: 1, avg: 5, manualPrice: 6 }];
  const acts = M.holdingActions(M.portfolio(hold, byT), byT, rules, new Date('2026-10-16'));
  acts.forEach(a => assert.ok(M.STATES.includes(a.action), a.action));
});
test('red flag -> EXIT REVIEW (a review, with indicative price), not an instruction', () => {
  const s = { ...byT.A, gov: 'red_flag' }, port = M.portfolio([{ ticker: 'A', qty: 10, avg: 300 }], { A: s });
  const a = M.holdingActions(port, { A: s }, rules, new Date('2026-10-16'))[0];
  assert.equal(a.action, 'EXIT REVIEW'); assert.match(a.priceNote, /If you decide/);
});
test('a falling price alone never produces a sell/reduce: it is a WATCH with thesis review', () => {
  const s = { ...byT.A, price: 250 }, mapT = { ...byT, A: s };
  const port = M.portfolio([{ ticker: 'A', qty: 5, avg: 300 }, { ticker: 'B', qty: 5, avg: 500 }, { ticker: 'C', qty: 5, avg: 600 }], mapT);
  const a = M.holdingActions(port, mapT, rules, new Date('2026-10-16')).find(x => x.ticker === 'A');
  assert.equal(a.action, 'WATCH'); assert.match(a.reasons.join(' '), /not a sell signal/);
});
test('oversized holding -> REDUCE CANDIDATE (partial); long-term vs trading level kept separate', () => {
  const port = M.portfolio([{ ticker: 'A', qty: 100, avg: 300 }, { ticker: 'B', qty: 2, avg: 500 }], byT);
  const a = M.holdingActions(port, byT, rules, new Date('2026-10-16')).find(x => x.ticker === 'A');
  assert.equal(a.action, 'REDUCE CANDIDATE'); assert.ok(a.qty >= 1 && a.qty <= 50); assert.match(a.notes.join(' '), /Short-term trading level, kept separate/);
});
test('stale/missing price -> DATA UNAVAILABLE; manual price accepted', () => {
  const port = M.portfolio([{ ticker: 'XYZ.NS', qty: 10, avg: 100, manualPrice: 120 }, { ticker: 'QQQ.NS', qty: 1, avg: 10 }], byT);
  assert.equal(port.rows[0].value, 1200); assert.equal(port.rows[1].price, null);
  assert.equal(port.pnl, 200);                                  // missing-price holdings do not distort P&L
  assert.ok(M.holdingActions(port, byT, rules, new Date()).every(a => a.action === 'DATA UNAVAILABLE'));
  const stale = M.portfolio([{ ticker: 'A', qty: 1, avg: 1 }], { A: { ...byT.A, fresh: false } });
  assert.equal(stale.rows[0].price, null);
});
test('short holding gets tax note on reduce', () => {
  const port = M.portfolio([{ ticker: 'A', qty: 100, avg: 300, date: '2026-08-01' }, { ticker: 'B', qty: 1, avg: 500 }], byT);
  const a = M.holdingActions(port, byT, rules, new Date('2026-10-16')).find(x => x.ticker === 'A');
  assert.ok(a.notes.some(n => /short-term tax/.test(n)));
});
test('day change uses market prices only', () => {
  const port = M.portfolio([{ ticker: 'A', qty: 10, avg: 300 }, { ticker: 'M.NS', qty: 1, avg: 5, manualPrice: 6 }], byT);
  assert.ok(port.dayChange > 0);
});

// ---------- audit regressions ----------
test('AUDIT: a stale report (opened days after it was built) can never produce a plan, even with safety answered', () => {
  const old = M.markStale(stocks, '2026-10-01', 4, new Date('2026-10-11T12:00:00'));         // 10 days old
  assert.ok(old.every(s => s.stale && !s.fresh && s.staleDays === 10));
  const p = M.monthlyPlan(20000, OK, old, empty, rules);
  assert.equal(p.rows.length, 0); assert.equal(p.approvable, false); assert.match(p.verdict, /10 days old/);
  const sel = M.monthlyPlan(20000, OK, old, empty, rules, { selected: ['A', 'B'] }); assert.equal(sel.rows.length, 0);
});
test('AUDIT: within the stale limit nothing changes; the limit is inclusive', () => {
  assert.equal(M.markStale(stocks, '2026-10-12', 4, new Date('2026-10-16T09:00:00')), stocks);     // 4 days: still fine (long weekend)
  assert.ok(M.markStale(stocks, '2026-10-11', 4, new Date('2026-10-16T09:00:00')).every(s => s.stale)); // 5 days: stale
});
test('AUDIT: holdings on a stale report get DATA UNAVAILABLE (value shown, no advice); P&L still computed', () => {
  const old = M.markStale(stocks, '2026-10-01', 4, new Date('2026-10-11T12:00:00')), mapT = Object.fromEntries(old.map(s => [s.ticker, s]));
  const port = M.portfolio([{ ticker: 'A', qty: 10, avg: 300 }], mapT);
  assert.equal(port.rows[0].priceSource, 'stale'); assert.ok(port.total > 0); assert.equal(port.dayChange, null);
  assert.equal(M.holdingActions(port, mapT, rules, new Date('2026-10-11'))[0].action, 'DATA UNAVAILABLE');
});
test('AUDIT: a stock far below its range is excluded even when the user selects it; a small dip is allowed', () => {
  const below = mk('LOW', { price: 400, zones: { ideal: [480, 520], thesis_review: 380, trading_stop: 360, distance_pct: -16, position: 'below' } });
  assert.equal(M.rangePos(below), 'below');
  const p = M.monthlyPlan(20000, OK, [below, mk('OK2')], empty, rules, { selected: ['LOW', 'OK2'] });
  assert.ok(!p.rows.some(r => r.ticker === 'LOW')); assert.ok(p.skipped.some(x => x.ticker === 'LOW' && /weak trend/.test(x.reason)));
  assert.equal(M.rangePos(mk('NEAR', { price: 470 })), 'in_range');          // 2% under 480 is inside the 3% tolerance
  assert.equal(M.rangePos(mk('ABOVE', { price: 530 })), 'above');
});
test('AUDIT: an ACCUMULATE-status stock whose price has left its range is not auto-picked', () => {
  const drifted = mk('D', { price: 600 });                                        // status ACCUMULATE but 15% above its range
  assert.equal(M.monthlyPlan(20000, OK, [drifted], empty, rules).rows.length, 0);
});
test('AUDIT: holding in ACCUMULATE state needs an in-range price', () => {
  const s = mk('H', { price: 600 }), mapT = { H: s }, port = M.portfolio([{ ticker: 'H', qty: 5, avg: 500 }, { ticker: 'Z', qty: 1, avg: 1, manualPrice: 1 }], mapT);
  assert.notEqual(M.holdingActions(port, mapT, rules, new Date('2026-10-16')).find(a => a.ticker === 'H').action, 'ACCUMULATE CANDIDATE');
});
