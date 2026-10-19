/* Decision logic shared by the browser dashboard and the optional private email review. Decision support only. */
(function (root) {
  'use strict';
  const r2 = (x) => Math.round(x * 100) / 100;
  const tick = (x) => Math.round(x * 20) / 20;           // NSE tick size 0.05
  const STATES = ['HOLD', 'ACCUMULATE CANDIDATE', 'WATCH', 'REDUCE CANDIDATE', 'EXIT REVIEW', 'DATA UNAVAILABLE'];

  // How old is the report? Evaluated when the page is OPENED, not when the report was built.
  function reportAgeDays(priceDate, now) { return priceDate ? Math.floor((now - new Date(priceDate + 'T00:00:00')) / 86400000) : null; }
  function markStale(stocks, priceDate, limit, now) {
    const age = reportAgeDays(priceDate, now);
    if (age == null || age <= limit) return stocks;
    return stocks.map(s => ({ ...s, fresh: false, stale: true, staleDays: age }));
  }
  // Same tolerance as the Python side: 3% under the bottom of the range, 1% over the top.
  function rangePos(s) {
    if (!s || !s.zones || s.price == null) return 'unknown';
    const z = s.zones.ideal;
    return s.price > z[1] * 1.01 ? 'above' : s.price < z[0] * 0.97 ? 'below' : 'in_range';
  }

  function priceOf(h, byT) {
    const s = byT[h.ticker];
    if (s && s.fresh && s.price != null && s.status !== 'DATA UNAVAILABLE') return { price: s.price, source: 'market', asof: s.asof };
    if (s && s.stale && s.price != null) return { price: s.price, source: 'stale', asof: s.asof };      // shown for value only; never used for advice
    if (h.manualPrice > 0) return { price: h.manualPrice, source: 'manual', asof: null };
    return { price: null, source: 'none', asof: null };
  }

  function portfolio(holdings, byT) {
    const rows = holdings.filter(h => h.qty > 0).map(h => {
      const s = byT[h.ticker] || {}, p = priceOf(h, byT), invested = h.qty * h.avg;
      const value = p.price == null ? null : h.qty * p.price;
      const dayChg = value != null && s.chg1d != null && p.source === 'market' ? value - value / (1 + s.chg1d / 100) : null;
      return { ...h, name: s.name || h.ticker, sector: s.sector || 'Other', cap: s.cap || '?', price: p.price, priceSource: p.source,
               invested, value, pnl: value == null ? null : value - invested, pnlPct: value == null ? null : (value / invested - 1) * 100, dayChg };
    });
    const total = rows.reduce((a, r) => a + (r.value || 0), 0);
    const invested = rows.reduce((a, r) => a + r.invested, 0);
    rows.forEach(r => { r.weight = total > 0 && r.value != null ? r.value / total * 100 : null; });
    const sectors = {};
    rows.forEach(r => { sectors[r.sector] = (sectors[r.sector] || 0) + (r.weight || 0); });
    const dc = rows.filter(r => r.dayChg != null);
    const pricedInvested = rows.filter(r => r.price != null).reduce((a, r) => a + r.invested, 0);
    return { rows, total, invested, pnl: total - pricedInvested, sectors, dayChange: dc.length ? dc.reduce((a, r) => a + r.dayChg, 0) : null,
             missingPrices: rows.filter(r => r.price == null).map(r => r.ticker) };
  }

  /* Gate answers: debt 'yes'|'no'|null, emergency 'ok'|'low'|null. Unanswered = UNVERIFIED = never approvable. */
  function safetyGate(amount, safety) {
    const s = safety || {}, notes = [];
    let status = 'OPEN', budget = amount;
    if (s.debt === 'yes') { status = 'CLOSED'; budget = 0; notes.push('You have debt costing 12% a year or more. Repaying it is a certain saving; stock returns are not. No stock purchase is recommended.'); }
    else if (s.debt == null || s.emergency == null) { status = 'UNVERIFIED'; notes.push('Answer the two safety questions to unlock an approvable plan. Until then this plan is a preview only.'); }
    else if (s.emergency === 'low') { status = 'REDUCED'; budget = amount * 0.5; notes.push('Your emergency fund is under 6 months of expenses, so only half of this month\'s amount is used.'); }
    return { status, budget, notes, approvable: status === 'OPEN' || status === 'REDUCED' };
  }

  function limitsContext(port, rules) {
    const heldW = {}; port.rows.forEach(r => { heldW[r.ticker] = r.weight || 0; });
    const smallW = port.rows.reduce((a, r) => a + (r.cap === 'S' ? (r.weight || 0) : 0), 0);
    return { building: port.rows.length < rules.minPositions, heldW, smallW };
  }

  function monthlyPlan(amount, safety, stocks, port, rules, opts) {
    opts = opts || {};
    const gate = safetyGate(amount, safety), mode = opts.mode || 'real';
    const plan = { gate, mode, budget: gate.budget, rows: [], skipped: [], cashLeft: gate.budget, totalSpend: 0, verdict: '', approvable: false, notes: [] };
    if (!(amount > 0)) { plan.verdict = 'Enter an amount to see your plan.'; plan.cashLeft = 0; return plan; }
    if (gate.budget <= 0) { plan.verdict = 'NO PURCHASE RECOMMENDED this month (safety check).'; return plan; }
    if (stocks.length && stocks.every(s => s.stale)) {
      plan.verdict = 'NO PURCHASE RECOMMENDED: the prices in this report are ' + stocks[0].staleDays + ' days old. Wait for the next successful update.';
      plan.cashLeft = plan.budget; return plan;
    }
    const { building, heldW, smallW } = limitsContext(port, rules), by = {};
    stocks.forEach(s => { by[s.ticker] = s; });
    const user = Array.isArray(opts.selected) && opts.selected.length;
    const pool = user ? opts.selected.slice(0, 10).map(t => by[t]).filter(Boolean) : stocks.filter(s => s.status === 'ACCUMULATE CANDIDATE');
    const elig = [];
    for (const s of pool) {
      const why = (m) => plan.skipped.push({ ticker: s.ticker, reason: m });
      if (!s.fresh || s.price == null || s.status === 'DATA UNAVAILABLE' || !s.zones) { why('price/data unavailable or stale: no purchase on unreliable data'); continue; }
      if (s.status === 'AVOID' || s.gov === 'red_flag') { why('flagged AVOID / governance red flag'); continue; }
      if (rangePos(s) === 'below') { why('price is well below the preferred range, which signals a weak trend: not a candidate even if you selected it (a buy limit above the market would simply fill now)'); continue; }
      if (!user && rangePos(s) !== 'in_range') { why('not inside its preferred range'); continue; }
      if (!building && (heldW[s.ticker] || 0) >= rules.maxSingle) { why('already at your max single-stock weight'); continue; }
      if (!building && (port.sectors[s.sector] || 0) >= rules.maxSector) { why(s.sector + ' already at the sector limit'); continue; }
      if (!building && s.cap === 'S' && smallW >= rules.maxSmall) { why('small-cap share already at ' + rules.maxSmall + '%'); continue; }
      let fit = s.research * 0.45 + (s.entry || 0) * 0.35;
      if ((port.sectors[s.sector] || 0) >= rules.maxSector * 0.85) fit -= 25;
      elig.push({ s, fit });
    }
    if (!user) elig.sort((a, b) => b.fit - a.fit);
    const nAuto = Math.max(1, Math.min(rules.maxStocks, Math.floor(plan.budget / rules.minPerPosition)));
    const n = user ? elig.length : Math.min(nAuto, elig.length);
    const slice = n ? plan.budget / n : 0, k = 1 + rules.buyCostPct / 100, chosen = [];
    for (const c of elig) {
      if (chosen.length >= n) break;
      const z = c.s.zones.ideal, inRange = rangePos(c.s) === 'in_range';
      const limit = tick(inRange ? c.s.price : z[1]);
      if (limit * k > slice) { plan.skipped.push({ ticker: c.s.ticker, reason: 'one share (Rs ' + Math.round(limit) + ') is bigger than its slice (Rs ' + Math.round(slice) + ') of this month\'s amount' }); continue; }
      chosen.push({ ...c, limit, inRange });
    }
    if (!chosen.length) { plan.verdict = 'NO PURCHASE RECOMMENDED this month: nothing meets entry, data and affordability checks. Keeping the cash is a valid decision.'; return plan; }
    let w;
    const ov = opts.overrides || {}, hasOv = chosen.some(c => ov[c.s.ticker] > 0);
    if (hasOv) {
      const given = chosen.reduce((a, c) => a + (ov[c.s.ticker] > 0 ? ov[c.s.ticker] : 0), 0), others = chosen.filter(c => !(ov[c.s.ticker] > 0)).length;
      w = chosen.map(c => ov[c.s.ticker] > 0 ? ov[c.s.ticker] : (others ? Math.max(100 - given, 0) / others : 0));
      if (Math.abs(given - 100) > 0.5 && !others) plan.notes.push('Your edited percentages added up to ' + r2(given) + '%; they were scaled to 100%.');
    } else if (opts.method === 'equal') w = chosen.map(() => 1);
    else w = chosen.map(c => Math.max(c.s.research, 1) / Math.max(c.s.atrPct || 3, 1.5));    // risk-adjusted: score per unit of volatility
    const tw = w.reduce((a, b) => a + b, 0) || 1; w = w.map(x => x / tw);
    let rows = chosen.map((c, i) => ({ ticker: c.s.ticker, name: c.s.name, sector: c.s.sector, cap: c.s.cap, current: c.s.price, limit: c.limit, inRange: c.inRange,
      distancePct: c.s.zones.distance_pct || 0, zone: c.s.zones.ideal, review: c.s.zones.thesis_review, research: c.s.research, entry: c.s.entry, conf: c.s.confidence,
      gov: c.s.gov, reason: (c.s.why || []).slice(0, 2).join('; '), weightPlanned: w[i] * 100,
      risks: [c.s.bear != null ? 'Bear-case illustration: ' + c.s.bear + '% over 12 months' : null, c.s.invalidation && c.s.invalidation[0] ? 'Thesis breaks if: ' + c.s.invalidation[0] : null,
              c.s.atrPct ? 'Typical daily swing about ' + c.s.atrPct.toFixed(1) + '%' : null].filter(Boolean),
      shares: Math.floor(plan.budget * w[i] / (c.limit * k)), cost: 0, amount: 0 }));
    let left = plan.budget - rows.reduce((a, r) => a + r.shares * r.limit * k, 0);
    for (const r of [...rows].sort((a, b) => a.limit - b.limit)) { const u = r.limit * k; if (left >= u) { const m = Math.floor(left / u); r.shares += m; left -= m * u; } }
    rows = rows.filter(r => r.shares > 0);
    if (!rows.length) { plan.verdict = 'NO PURCHASE RECOMMENDED: the amount is too small for one share of any candidate.'; return plan; }
    rows.forEach(r => { r.amount = r2(r.shares * r.limit); r.cost = r2(r.amount * rules.buyCostPct / 100); });
    const tot = rows.reduce((a, r) => a + r.amount + r.cost, 0);
    rows.forEach(r => { r.pctOfMonth = r2((r.amount + r.cost) / tot * 100);
      const held = (heldW[r.ticker] || 0) / 100 * port.total; r.weightAfter = r2((held + r.amount) / (port.total + tot) * 100);
      r.stage = opts.staged ? stageRow(r) : null; });
    plan.rows = rows; plan.totalSpend = r2(tot); plan.cashLeft = r2(amount - tot);
    plan.approvable = gate.approvable && mode === 'real' && rows.some(r => r.inRange);
    plan.verdict = gate.status === 'UNVERIFIED' ? 'PREVIEW ONLY: not approvable until you answer the safety questions.'
      : mode !== 'real' ? 'DEMO plan on made-up prices: not approvable.'
      : rows.some(r => r.inRange) ? 'Suggested plan for this month: limit orders, placed and approved by you.'
      : 'Nothing is inside its entry range today: these are pending limit orders that may not fill.';
    return plan;
  }

  // Staged entry: three tranches at the top, middle and bottom of the preferred range (whole shares).
  function stageRow(r) {
    const z = r.zone, pr = [tick(z[1]), tick((z[0] + z[1]) / 2), tick(z[0])], sh = [Math.ceil(r.shares * 0.4), Math.ceil(r.shares * 0.3), 0];
    sh[0] = Math.min(sh[0], r.shares); sh[1] = Math.min(sh[1], r.shares - sh[0]); sh[2] = r.shares - sh[0] - sh[1];
    const tr = sh.map((s, i) => ({ price: pr[i], shares: s })).filter(t => t.shares > 0);
    const cost = tr.reduce((a, t) => a + t.price * t.shares, 0);
    return { tranches: tr, avg: r2(cost / r.shares), vsImmediate: r2(cost / r.shares - r.limit),
             note: 'Tranches fill only if the price reaches each level; if it never dips you own less than planned.' };
  }

  function concentrationBreaches(port, rules) {
    const out = [], { building } = limitsContext(port, rules);
    if (building) return out;
    port.rows.forEach(r => { if (r.weight > rules.maxSingle) out.push({ kind: 'position', subject: r.name, ticker: r.ticker, value: r.weight, limit: rules.maxSingle }); });
    Object.keys(port.sectors).forEach(k => { if (port.sectors[k] > rules.maxSector) out.push({ kind: 'sector', subject: k, value: port.sectors[k], limit: rules.maxSector }); });
    const sm = port.rows.reduce((a, r) => a + (r.cap === 'S' ? (r.weight || 0) : 0), 0);
    if (sm > rules.maxSmall) out.push({ kind: 'smallcap', subject: 'small-cap total', value: sm, limit: rules.maxSmall });
    return out;
  }

  function holdingActions(port, byT, rules, today) {
    const { building } = limitsContext(port, rules), cap = building ? rules.concCapBuilding : rules.maxSingle, out = [];
    for (const r of port.rows) {
      const s = byT[r.ticker];
      const a = { ticker: r.ticker, name: r.name, action: 'HOLD', tone: 'mute', qty: 0, reasons: [], priceNote: '', notes: [], confidence: 'Low', limits: [] };
      if (r.price == null) { a.action = 'DATA UNAVAILABLE'; a.reasons.push('No reliable market price. Type a price in the portfolio table to include it.'); out.push(a); continue; }
      if (r.priceSource === 'stale') { a.action = 'DATA UNAVAILABLE'; a.reasons.push('This report\'s prices are ' + ((byT[r.ticker] || {}).staleDays || 'several') + ' days old, so no advice is given. Value is shown at the last known price only.'); out.push(a); continue; }
      if (!s) { a.action = 'DATA UNAVAILABLE'; a.reasons.push('This stock is not covered by the research screen, so no automatic view is possible. Treat as research required.'); out.push(a); continue; }
      if (s.status === 'DATA UNAVAILABLE') { a.action = 'DATA UNAVAILABLE'; a.reasons.push(s.why.join('; ')); out.push(a); continue; }
      const z = s.zones, atr = s.atr || r.price * 0.02, w = r.weight || 0;
      a.confidence = (s.confidence && s.confidence.label) || 'Low'; a.limits = (s.confidence && s.confidence.limits) || [];
      const range = 'indicative limit order between Rs ' + r2(r.price).toFixed(2) + ' and Rs ' + r2(r.price + 0.3 * atr).toFixed(2);
      if (s.gov === 'red_flag' || s.status === 'AVOID') {
        a.action = 'EXIT REVIEW'; a.tone = 'neg'; a.qty = r.qty;
        a.reasons.push(s.gov === 'red_flag' ? 'You recorded a governance red flag for this company. Review whether the thesis can survive it.' : s.why.join('; '));
        a.priceNote = 'If you decide to exit all ' + r.qty + ' shares: ' + range;
      } else if (z && r.price < z.thesis_review) {
        a.action = 'WATCH'; a.tone = 'amb';
        a.reasons.push('Price is below Rs ' + z.thesis_review + ', the level where the investment case must be re-checked. This is a review trigger, not a sell signal.');
        a.reasons.push('Read the latest results, filings and news. Sell only if the business got weaker.');
      } else if (w > cap) {
        const target = (building ? cap * 0.85 : rules.maxSingle * 0.9) / 100;
        let q = Math.ceil((r.value - target * port.total) / r.price);
        q = Math.max(1, Math.min(q, Math.floor(r.qty * 0.5) || 1, r.qty));
        a.action = 'REDUCE CANDIDATE'; a.tone = 'amb'; a.qty = q;
        a.reasons.push('This is ' + w.toFixed(1) + '% of your portfolio, above the ' + cap + '% limit. A portfolio-balance rule, not a view that the business is bad.');
        a.priceNote = 'If you reduce by ' + q + ' of ' + r.qty + ' shares: ' + range;
      } else if (s.ext200 != null && s.ext200 > 40 && r.pnlPct > 50 && r.qty >= 2) {
        const q = Math.max(1, Math.floor(r.qty * 0.25));
        a.action = 'REDUCE CANDIDATE'; a.tone = 'amb'; a.qty = q;
        a.reasons.push('Price is ' + s.ext200.toFixed(0) + '% above its 200-day average and you are up ' + r.pnlPct.toFixed(0) + '%. Booking about a quarter locks in gains and keeps the rest.');
        a.priceNote = 'If you reduce by ' + q + ' of ' + r.qty + ' shares: ' + range;
      } else if (s.status === 'ACCUMULATE CANDIDATE' && z && rangePos(s) === 'in_range' && w < cap * 0.8) {
        a.action = 'ACCUMULATE CANDIDATE'; a.tone = 'pos';
        a.reasons.push('Business score ' + s.research + ' and the price is inside the preferred entry range.');
        a.priceNote = 'Add via limit order at or below Rs ' + z.ideal[1].toFixed(2) + ' (range ' + z.ideal[0].toFixed(2) + ' to ' + z.ideal[1].toFixed(2) + ')';
      } else if (s.status === 'WATCH') {
        a.action = 'WATCH'; a.tone = 'amb'; a.reasons.push((s.why || []).slice(0, 2).join('; '));
      } else a.reasons.push('Nothing material changed. Price moves alone are not a reason to sell.');
      a.notes.push('Long-term view: this status reflects business and portfolio evidence. Short-term trading level, kept separate and not an instruction: volatility stop near Rs ' + (z ? z.trading_stop : 'n/a') + '.');
      if (z) a.notes.push('Thesis re-check level: Rs ' + z.thesis_review + '.');
      if (a.qty && r.date) {
        const held = Math.floor((today - new Date(r.date)) / 86400000);
        if (held < 365) a.notes.push('Held ' + held + ' days. Selling before 1 year is short-term tax (20%); after 1 year it is 12.5% above Rs 1.25 lakh a year. Estimate: check with a CA.');
      }
      out.push(a);
    }
    const order = { 'EXIT REVIEW': 0, 'REDUCE CANDIDATE': 1, 'WATCH': 2, 'ACCUMULATE CANDIDATE': 3, 'DATA UNAVAILABLE': 4 };
    out.sort((x, y) => (order[x.action] ?? 9) - (order[y.action] ?? 9));
    return out;
  }

  const api = { STATES, reportAgeDays, markStale, rangePos, priceOf, portfolio, safetyGate, monthlyPlan, stageRow, holdingActions, concentrationBreaches, limitsContext, tick };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.MIS = api;
})(typeof window !== 'undefined' ? window : globalThis);
