/* Transaction ledger: FIFO lots, realised P&L, dividends, XIRR, benchmark comparison, CSV validation, tax estimate.
   Runs in the browser; also used by the optional private email review. Holdings never reach the public repo. */
(function (root) {
  'use strict';
  const TYPES = ['buy', 'sell', 'dividend', 'split', 'bonus'];
  const DAY = 86400000;
  const d2 = (s) => new Date(s + 'T00:00:00Z');

  function parseCSV(text) {
    const lines = String(text).split(/\r?\n/).filter(l => l.trim().length);
    const errors = [], rows = [], seen = new Set();
    if (!lines.length) return { rows, errors: ['The file is empty.'] };
    const head = lines[0].split(',').map(h => h.trim().toLowerCase());
    const need = ['date', 'type', 'ticker', 'quantity', 'price'];
    const miss = need.filter(h => head.indexOf(h) < 0);
    if (miss.length) return { rows, errors: ['Missing column(s): ' + miss.join(', ') + '. Expected: date,type,ticker,quantity,price,fees,note'] };
    for (let i = 1; i < lines.length; i++) {
      const c = lines[i].split(','), g = (k) => (c[head.indexOf(k)] || '').trim(), n = i + 1;
      const date = g('date'), type = g('type').toLowerCase(), ticker = g('ticker').toUpperCase();
      const q = parseFloat(g('quantity')), p = parseFloat(g('price')), f = parseFloat(g('fees') || '0');
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || isNaN(d2(date))) { errors.push('Line ' + n + ': bad date "' + date + '" (use YYYY-MM-DD)'); continue; }
      if (TYPES.indexOf(type) < 0) { errors.push('Line ' + n + ': type "' + type + '" must be one of ' + TYPES.join('/')); continue; }
      if (!ticker) { errors.push('Line ' + n + ': empty stock'); continue; }
      if (!(q > 0) || isNaN(p) || p < 0 || isNaN(f) || f < 0) { errors.push('Line ' + n + ': quantity must be > 0; price and fees must be numbers >= 0'); continue; }
      const key = [date, type, ticker, q, p].join('|');
      if (seen.has(key)) { errors.push('Line ' + n + ': duplicate of an earlier row, skipped'); continue; }
      seen.add(key);
      rows.push({ date, type, ticker: normTicker(ticker), qty: q, price: p, fees: f || 0, note: g('note') });
    }
    return { rows, errors };
  }
  function normTicker(t) { t = String(t).trim().toUpperCase(); return t.indexOf('.') > 0 ? t : t + '.NS'; }

  function sorted(txs) {   // stable: by date, then original order; undated rows (migrated positions) first
    return txs.map((t, i) => ({ t, i })).sort((a, b) => ((a.t.date || '0000') < (b.t.date || '0000') ? -1 : (a.t.date || '0000') > (b.t.date || '0000') ? 1 : a.i - b.i)).map(x => x.t);
  }

  function buildLedger(txs) {
    const lots = {}, realized = [], dividends = {}, errors = [];
    for (const t of sorted(txs)) {
      const L = lots[t.ticker] = lots[t.ticker] || [];
      const held = L.reduce((a, l) => a + l.qty, 0);
      if (t.type === 'buy') L.push({ qty: t.qty, unit: (t.qty * t.price + (t.fees || 0)) / t.qty, date: t.date });
      else if (t.type === 'sell') {
        if (t.qty > held + 1e-9) { errors.push((t.date || '') + ' sell ' + t.ticker + ': selling ' + t.qty + ' but only ' + held + ' held; ignored'); continue; }
        let rem = t.qty; const unitNet = (t.qty * t.price - (t.fees || 0)) / t.qty;
        while (rem > 1e-9) {
          const lot = L[0], take = Math.min(lot.qty, rem);
          realized.push({ ticker: t.ticker, sellDate: t.date, buyDate: lot.date, qty: take, pnl: take * (unitNet - lot.unit),
                          days: lot.date && t.date ? Math.floor((d2(t.date) - d2(lot.date)) / DAY) : null });
          lot.qty -= take; rem -= take; if (lot.qty <= 1e-9) L.shift();
        }
      } else if (t.type === 'dividend') dividends[t.ticker] = (dividends[t.ticker] || 0) + held * t.price;
      else if (t.type === 'split') L.forEach(l => { l.qty *= t.qty; l.unit /= t.qty; });
      else if (t.type === 'bonus' && held > 0) {
        const add = held * t.qty, cost = L.reduce((a, l) => a + l.qty * l.unit, 0);
        L.forEach(l => { l.unit = cost / (held + add); }); L.push({ qty: add, unit: cost / (held + add), date: t.date });
      }
    }
    return { lots, realized, dividends, errors };
  }

  function positions(ledger) {
    const out = [];
    for (const tk of Object.keys(ledger.lots)) {
      const L = ledger.lots[tk], qty = L.reduce((a, l) => a + l.qty, 0);
      if (qty <= 1e-9) continue;
      const cost = L.reduce((a, l) => a + l.qty * l.unit, 0);
      const dates = L.map(l => l.date).filter(Boolean).sort();
      out.push({ ticker: tk, qty, avg: cost / qty, date: dates[0] || '' });
    }
    return out;
  }

  function xirr(flows) {
    if (flows.length < 2 || !flows.some(f => f.amt < 0) || !flows.some(f => f.amt > 0)) return null;
    const t0 = Math.min.apply(null, flows.map(f => +f.date));
    const npv = (r) => flows.reduce((a, f) => a + f.amt / Math.pow(1 + r, (f.date - t0) / (365 * DAY)), 0);
    let lo = -0.99, hi = 10, flo = npv(lo), fhi = npv(hi);
    if (flo * fhi > 0) return null;
    for (let i = 0; i < 200; i++) {
      const mid = (lo + hi) / 2, fm = npv(mid);
      if (Math.abs(fm) < 1e-7) return mid;
      if (flo * fm < 0) { hi = mid; } else { lo = mid; flo = fm; }
    }
    return (lo + hi) / 2;
  }

  function flows(txs) {
    const out = [], held = {}; let undated = false;
    for (const t of sorted(txs)) {
      if (!t.date) { if (t.type === 'buy') undated = true; continue; }
      const h = held[t.ticker] || 0, d = d2(t.date);
      if (t.type === 'buy') { out.push({ date: d, amt: -(t.qty * t.price + (t.fees || 0)) }); held[t.ticker] = h + t.qty; }
      else if (t.type === 'sell') { out.push({ date: d, amt: t.qty * t.price - (t.fees || 0) }); held[t.ticker] = h - t.qty; }
      else if (t.type === 'dividend') out.push({ date: d, amt: h * t.price });
      else if (t.type === 'split') held[t.ticker] = h * t.qty;
      else if (t.type === 'bonus') held[t.ticker] = h * (1 + t.qty);
    }
    return { flows: out, undated };
  }

  function portfolioXirr(txs, endValue, endDate, missingPrices) {
    if (missingPrices && missingPrices.length) return { value: null, why: missingPrices.length + ' holding(s) have no price, so the end value is incomplete and XIRR would be wrong. Type the missing prices on the Portfolio page.' };
    const f = flows(txs);
    if (f.undated) return { value: null, why: 'Some positions have no buy date, so XIRR cannot be computed. Add dated transactions.' };
    if (f.flows.length < 1) return { value: null, why: 'No dated transactions.' };
    const first = Math.min.apply(null, f.flows.map(x => +x.date));
    if ((endDate - first) / DAY < 90) return { value: null, why: 'Less than 3 months of history: XIRR would be misleading.' };
    const v = xirr(f.flows.concat([{ date: endDate, amt: endValue }]));
    return { value: v, why: v == null ? 'XIRR did not converge.' : '' };
  }

  // Same cash flows invested in the Nifty 50 price index (excludes dividends: an understatement of the benchmark).
  function benchXirr(txs, bench, endDate) {
    const f = flows(txs);
    if (f.undated || !bench || !bench.length || !f.flows.length) return null;
    const px = (d) => { let p = null; for (const b of bench) { if (d2(b[0]) <= d) p = b[1]; else break; } return p; };
    let units = 0;
    for (const x of f.flows) { const p = px(x.date); if (!p) return null; units += -x.amt / p; }
    const pe = bench[bench.length - 1][1];
    return xirr(f.flows.concat([{ date: endDate, amt: units * pe }]));
  }

  function taxEstimate(realized, fyStart) {
    const inFY = realized.filter(r => r.sellDate && r.sellDate >= fyStart);
    const st = inFY.filter(r => r.days != null && r.days <= 365).reduce((a, r) => a + r.pnl, 0);
    const lt = inFY.filter(r => r.days != null && r.days > 365).reduce((a, r) => a + r.pnl, 0);
    return { stcg: st, ltcg: lt, tax: Math.max(st, 0) * 0.20 + Math.max(lt - 125000, 0) * 0.125 };
  }

  const api = { parseCSV, buildLedger, positions, xirr, portfolioXirr, benchXirr, taxEstimate, normTicker, TYPES };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.LEDGER = api;
})(typeof window !== 'undefined' ? window : globalThis);
