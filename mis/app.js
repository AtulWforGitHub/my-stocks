/* MIS dashboard application. Your entries (transactions, safety answers, decisions) are stored ONLY in this browser. */
(function () {
'use strict';
var D = JSON.parse(document.getElementById('mis-data').textContent);
var ORIG = D.stocks, byT = {};
function refreshFreshness() { D.stocks = MIS.markStale(ORIG, D.price_date, D.rules.staleAfterDays, new Date()); byT = {}; D.stocks.forEach(function (s) { byT[s.ticker] = s; }); }
refreshFreshness();
function safeUrl(u) { return /^https?:\/\//i.test(String(u || '')) ? u : '#'; }   // untrusted links: http(s) only, never javascript:
var KEY = 'mis_state_v2', OLD = 'mis_state_v1';
var S = { cloud: null, tx: [], manualPrices: {}, safety: { debt: null, emergency: null }, amount: '', selected: [], method: 'risk', staged: false, overrides: {},
          review: {}, baseline: {}, journal: [], plans: [], pfHistory: {}, filter: 'all' };
try { var raw = localStorage.getItem(KEY); if (raw) S = Object.assign(S, JSON.parse(raw));
  else { var o = JSON.parse(localStorage.getItem(OLD) || 'null');   // migrate positions from the first version
    if (o && o.holdings) { S.tx = o.holdings.map(function (h, i) { return { id: 'm' + i, date: h.date || '', type: 'buy', ticker: LEDGER.normTicker(h.ticker), qty: h.qty, price: h.avg, fees: 0, note: 'migrated position' }; });
      S.amount = o.amount || ''; if (o.safety) S.safety = { debt: o.safety.debt ? 'yes' : null, emergency: o.safety.emergency ? 'low' : null }; } } } catch (e) {}
var statusLive = null;       // status.json fetched at load (shows a failed run even though the report is old)
function cloudDefaults() { return { mode: 'public', owner: '', repo: '', branch: 'main', rev: 0, sha: null, lastSync: null, auto: true, dirty: false, sig: '', enabled: false, device: '' }; }
S.cloud = Object.assign(cloudDefaults(), S.cloud || {}); if (!S.cloud.device) S.cloud.device = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
var applyingRemote = false;
function persist() { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) {} }
function save() { persist(); if (!applyingRemote) noteChange(); }

/* ---------- formatting ---------- */
function esc(x) { return String(x == null ? '' : x).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
function inr(x, d) { return x == null || isNaN(x) ? 'n/a' : '\u20B9' + Number(x).toLocaleString('en-IN', { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 }); }
function inrS(x) { if (x == null || isNaN(x)) return 'n/a'; var a = Math.abs(x), s = x < 0 ? '-' : ''; return a >= 1e7 ? s + '\u20B9' + (a / 1e7).toFixed(2) + ' cr' : a >= 1e5 ? s + '\u20B9' + (a / 1e5).toFixed(2) + ' L' : s + inr(a); }
function pc(x, d) { return x == null || isNaN(x) ? 'n/a' : (x > 0 ? '+' : '') + Number(x).toFixed(d == null ? 1 : d) + '%'; }
function pp(x) { return x == null ? 'n/a' : (x * 100).toFixed(0) + '%'; }
function num(x, d) { return x == null || isNaN(x) ? 'n/a' : Number(x).toFixed(d == null ? 1 : d); }
function fd(iso) { if (!iso) return 'n/a'; var d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso); return isNaN(d) ? esc(iso) : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }); }
function ft(iso) { if (!iso) return 'n/a'; var d = new Date(iso); return isNaN(d) ? esc(iso) : d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) + ' IST'; }
function ageDays(iso) { return iso ? Math.floor((Date.now() - new Date(iso).getTime()) / 86400000) : null; }
function tip(label, text) { return '<span data-tip="' + esc(text) + '" tabindex="0">' + label + '</span>'; }
function tone(s) { return { 'ACCUMULATE CANDIDATE': 'pos', 'HOLD': '', 'WATCH': 'amb', 'REDUCE CANDIDATE': 'amb', 'EXIT REVIEW': 'neg', 'AVOID': 'neg', 'DATA UNAVAILABLE': '', 'RESEARCH ONLY': '' }[s] || ''; }
function tag(s) { return '<span class="tag ' + tone(s) + '">' + esc(s) + '</span>'; }
function srcTag(t) { return '<span class="src" title="' + (t === 'you' ? 'Calculated from transactions you entered' : 'Depends on external market data') + '">' + (t === 'you' ? 'your entries' : 'market data') + '</span>'; }
function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
var DEMO = D.mode !== 'real';

/* ---------- derived state ---------- */
function isApproved(t) { return S.review[t] === 'approved' || (S.baseline[t] && S.review[t] !== 'ignored'); }
function isNew(t) { return !S.baseline[t] && !S.review[t]; }
if (!Object.keys(S.baseline).length) { D.stocks.forEach(function (s) { S.baseline[s.ticker] = true; }); save(); }
function inRange(s) { return !!(s.zones && s.fresh && s.price != null && MIS.rangePos(s) === 'in_range' && s.status !== 'DATA UNAVAILABLE'); }
function ctx() {
  var ledger = LEDGER.buildLedger(S.tx), pos = LEDGER.positions(ledger).map(function (p) { return Object.assign({}, p, { manualPrice: S.manualPrices[p.ticker] }); });
  var port = MIS.portfolio(pos, byT), acts = MIS.holdingActions(port, byT, D.rules, new Date()), breaches = MIS.concentrationBreaches(port, D.rules);
  var appr = D.stocks.filter(function (s) { return isApproved(s.ticker); });
  var amt = parseFloat(String(S.amount).replace(/,/g, '')) || 0;
  var plan = MIS.monthlyPlan(amt, S.safety, appr, port, D.rules, { selected: S.selected.length ? S.selected : null, method: S.method, overrides: S.overrides, staged: S.staged, mode: D.mode });
  var end = D.price_date ? new Date(D.price_date + 'T00:00:00') : new Date(), x = LEDGER.portfolioXirr(S.tx, port.total, end, port.missingPrices);
  var realized = ledger.realized.reduce(function (a, r) { return a + r.pnl; }, 0), divs = Object.keys(ledger.dividends).reduce(function (a, k) { return a + ledger.dividends[k]; }, 0);
  var fy = (end.getMonth() >= 3 ? end.getFullYear() : end.getFullYear() - 1) + '-04-01';
  var monthChg = null, mc = port.rows.filter(function (r) { var s = byT[r.ticker]; return r.value != null && r.priceSource === 'market' && s && s.chg1m != null; });
  if (mc.length) monthChg = mc.reduce(function (a, r) { return a + r.value - r.value / (1 + byT[r.ticker].chg1m / 100); }, 0);
  return { ledger: ledger, port: port, acts: acts, breaches: breaches, plan: plan, amt: amt, xirr: x, bench: port.missingPrices.length ? null : LEDGER.benchXirr(S.tx, D.bench, end), realized: realized, divs: divs,
           tax: LEDGER.taxEstimate(ledger.realized, fy), monthChg: monthChg };
}
function portItems(c) {
  var out = [], cat = { 'EXIT REVIEW': 'critical_risk', 'REDUCE CANDIDATE': 'reduction_review', 'ACCUMULATE CANDIDATE': 'purchase_opportunity' }, lv = { critical_risk: 'CRITICAL', reduction_review: 'HIGH', purchase_opportunity: 'MEDIUM', thesis_deterioration: 'HIGH', concentration: 'HIGH' };
  c.acts.forEach(function (a) { var k = cat[a.action]; if (a.action === 'WATCH' && a.reasons.join(' ').indexOf('re-checked') >= 0) k = 'thesis_deterioration'; if (!k) return;
    var s = byT[a.ticker] || {};
    out.push({ id: 'pf:' + k + ':' + a.ticker, category: k, level: lv[k], ticker: a.ticker, name: a.name, title: a.name + ' (your holding): ' + a.action, reason: a.reasons.slice(0, 2).join(' ') + (a.priceNote ? ' ' + a.priceNote : ''),
      changed: 'current state of your holding', evidence: 'your entries + research as of ' + fd(s.asof), source: D.provider, asof: s.asof, next_step: k === 'critical_risk' ? 'Review today before deciding anything.' : 'Review the stock page, then decide.', confidence: a.confidence, limits: a.limits, link: '#/stock/' + a.ticker, mine: true, proposed: a.action, qty: a.qty }); });
  c.breaches.forEach(function (b) { out.push({ id: 'pf:conc:' + b.subject, category: 'concentration', level: 'HIGH', ticker: b.ticker || '-', name: b.subject, title: 'Concentration: ' + b.subject + ' is ' + b.value.toFixed(1) + '% (limit ' + b.limit + '%)',
    reason: 'A position/sector/small-cap limit from your settings is exceeded.', changed: 'current weights', evidence: 'your entries + market prices', source: 'your entries', asof: D.price_date, next_step: 'Decide whether to trim, on the Portfolio page.', confidence: 'High', limits: [], link: '#/portfolio', mine: true, proposed: 'REBALANCE' }); });
  return out;
}
var CATNAMES = { critical_risk: 'Critical risk, review now', thesis_deterioration: 'Thesis deterioration', purchase_opportunity: 'Potential purchase', concentration: 'Concentration warning', reduction_review: 'Reduction / exit review', news: 'News or filing', none: 'No action required' };

/* ---------- tables with sort, search and pagination ---------- */
var TBL = {};
function table(id, cols, rows, o) {
  o = o || {}; var t = TBL[id] = Object.assign({ sort: null, dir: 1, page: 0, q: '' }, TBL[id] || {}, { cols: cols, rows: rows, size: o.size || 15, search: o.search !== false, empty: o.empty || 'Nothing to show.' });
  return '<div id="tb-' + id + '">' + (t.search ? '<div class="tbar"><input type="search" data-tq="' + id + '" id="q-' + id + '" placeholder="Search" aria-label="Search table" value="' + esc(t.q) + '"></div>' : '') + '<div id="tbb-' + id + '">' + tbody(id) + '</div></div>';
}
function tbody(id) {
  var t = TBL[id], rows = t.rows.slice();
  if (t.q) { var q = t.q.toLowerCase(); rows = rows.filter(function (r) { return t.cols.some(function (c) { return String(c.v ? c.v(r) : '').toLowerCase().indexOf(q) >= 0 || (c.f && String(c.f(r)).replace(/<[^>]+>/g, '').toLowerCase().indexOf(q) >= 0); }); }); }
  if (t.sort != null) { var c = t.cols[t.sort]; rows.sort(function (a, b) { var x = c.v(a), y = c.v(b); if (x == null) return 1; if (y == null) return -1; return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))) * t.dir; }); }
  var pages = Math.max(1, Math.ceil(rows.length / t.size)); t.page = Math.min(t.page, pages - 1);
  var h = '<div class="wrap"><table><thead><tr>' + t.cols.map(function (c, i) { return '<th class="' + (c.n ? 'n' : '') + '"' + (c.v ? ' data-sort="' + id + ':' + i + '" tabindex="0" aria-sort="' + (t.sort === i ? (t.dir > 0 ? 'ascending' : 'descending') : 'none') + '"' : '') + '>' + c.h + '</th>'; }).join('') + '</tr></thead><tbody>';
  rows.slice(t.page * t.size, (t.page + 1) * t.size).forEach(function (r) { h += '<tr>' + t.cols.map(function (c) { return '<td class="' + (c.n ? 'n ' : '') + (c.w ? 'w' : '') + '">' + c.f(r) + '</td>'; }).join('') + '</tr>'; });
  if (!rows.length) h += '<tr><td colspan="' + t.cols.length + '" class="mute">' + t.empty + '</td></tr>';
  h += '</tbody></table></div>';
  if (pages > 1) h += '<div class="pager"><button class="ghost sm" data-pg="' + id + ':-1"' + (t.page === 0 ? ' disabled' : '') + '>Previous</button><span>Page ' + (t.page + 1) + ' of ' + pages + ' (' + rows.length + ' rows)</span><button class="ghost sm" data-pg="' + id + ':1"' + (t.page >= pages - 1 ? ' disabled' : '') + '>Next</button></div>';
  return h;
}

/* ---------- charts (inline SVG, no dependencies) ---------- */
function sma(a, n) { return a.map(function (_, i) { if (i < n - 1) return null; var s = 0; for (var j = i - n + 1; j <= i; j++) s += a[j]; return s / n; }); }
function lineChart(o) {
  var W = 640, H = o.h || 220, L = 46, R = 8, T = 10, B = 22, all = [];
  o.series.forEach(function (s) { s.data.forEach(function (v) { if (v != null) all.push(v); }); }); (o.bands || []).forEach(function (b) { all.push(b.lo, b.hi); }); (o.lines || []).forEach(function (l) { all.push(l.y); });
  if (!all.length) return '<p class="mute">No data to chart.</p>';
  var mn = Math.min.apply(null, all), mx = Math.max.apply(null, all), pad = (mx - mn) * 0.06 || 1; mn -= pad; mx += pad;
  var n = Math.max.apply(null, o.series.map(function (s) { return s.data.length; })), X = function (i) { return L + (W - L - R) * i / Math.max(n - 1, 1); }, Y = function (v) { return T + (H - T - B) * (1 - (v - mn) / (mx - mn)); };
  var g = '';
  for (var k = 0; k <= 4; k++) { var v = mn + (mx - mn) * k / 4, y = Y(v); g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y + '" y2="' + y + '" stroke="var(--line)"/><text x="' + (L - 4) + '" y="' + (y + 4) + '" text-anchor="end">' + (v >= 1000 ? Math.round(v).toLocaleString('en-IN') : v.toFixed(v < 100 ? 1 : 0)) + '</text>'; }
  (o.bands || []).forEach(function (b) { g += '<rect x="' + L + '" y="' + Y(b.hi) + '" width="' + (W - L - R) + '" height="' + Math.max(Y(b.lo) - Y(b.hi), 1) + '" fill="var(--pos)" opacity=".13"/><text x="' + (L + 4) + '" y="' + (Y(b.hi) + 11) + '" style="fill:var(--pos)">' + esc(b.label) + '</text>'; });
  (o.lines || []).forEach(function (l) { g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(l.y) + '" y2="' + Y(l.y) + '" stroke="var(--neg)" stroke-dasharray="4 3"/><text x="' + (W - R - 2) + '" y="' + (Y(l.y) - 3) + '" text-anchor="end" style="fill:var(--neg)">' + esc(l.label) + '</text>'; });
  o.series.forEach(function (s) { var d = '', pen = false; s.data.forEach(function (v, i) { if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1); pen = true; });
    g += '<path d="' + d + '" fill="none" stroke="' + s.color + '" stroke-width="' + (s.w || 1.6) + '"' + (s.dash ? ' stroke-dasharray="5 3"' : '') + '/>'; });
  var leg = o.series.map(function (s, i) { return '<text x="' + (L + 6 + i * 120) + '" y="' + (H - 6) + '" style="fill:' + s.color + '">' + esc(s.name) + '</text>'; }).join('');
  var xl = o.xl ? '<text x="' + L + '" y="' + (H - 6 + 0) + '" style="display:none"></text>' : '';
  return '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(o.label || 'chart') + '">' + g + leg + xl + '</svg>';
}
function bars(items, limit) {
  return items.map(function (it) { var w = Math.min(it.v, 100); return '<div class="bar"><span class="lab" title="' + esc(it.l) + '">' + esc(it.l) + '</span><span class="t"><span class="f" style="display:block;width:' + w + '%;' + (limit && it.v > limit ? 'background:var(--neg)' : '') + '"></span>' + (limit ? '<span class="lim" style="left:' + Math.min(limit, 100) + '%"></span>' : '') + '</span><b>' + it.v.toFixed(0) + '%</b></div>'; }).join('');
}
function spark(a) { if (!a || a.length < 5) return ''; var mn = Math.min.apply(null, a), mx = Math.max.apply(null, a), p = a.map(function (v, i) { return (i / (a.length - 1) * 80).toFixed(1) + ',' + (20 - (v - mn) / ((mx - mn) || 1) * 18).toFixed(1); }).join(' ');
  return '<svg width="80" height="22" viewBox="0 0 80 22" aria-hidden="true"><polyline points="' + p + '" fill="none" stroke="var(--acc)" stroke-width="1.4"/></svg>'; }

/* ---------- market status in the browser (uses the holiday list embedded at the last analysis) ---------- */
function marketNow() {
  var parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false, weekday: 'short' }).formatToParts(new Date()), m = {};
  parts.forEach(function (p) { m[p.type] = p.value; }); var iso = m.year + '-' + m.month + '-' + m.day, mins = (+m.hour) * 60 + (+m.minute), wk = m.weekday === 'Sat' || m.weekday === 'Sun';
  if ((D.holidays || []).indexOf(iso) >= 0) return { s: 'holiday', t: 'Market holiday' };
  if (wk) return { s: 'closed', t: 'Market closed (weekend)' };
  return mins >= 555 && mins <= 930 ? { s: 'open', t: 'Market session (data is still delayed)' } : { s: 'closed', t: 'Market closed' };
}
function dataState() {   // never "live": real data is delayed/end-of-day by construction
  if (DEMO) return { k: 'neg', t: 'SYNTHETIC DEMO DATA' };
  var a = ageDays(D.price_date); if (a != null && a > 4) return { k: 'amb', t: 'STALE: prices ' + a + ' days old' };
  return { k: '', t: 'End-of-day data as of ' + fd(D.price_date) };
}

/* ---------- shared view pieces ---------- */
function banners() {
  var h = '', st = statusLive || D.status || {};
  if (DEMO) h += '<div class="banner neg" role="alert"><b>Synthetic demonstration data.</b> Every price, score and holding value below is randomly generated to preview the layout. It is not real, was not used for any alert or email, and must not be used for decisions.</div>';
  var pa = MIS.reportAgeDays(D.price_date, new Date());
  if (!DEMO && pa != null && pa > D.rules.staleAfterDays) h += '<div class="banner neg" role="alert"><b>These prices are ' + pa + ' days old.</b> Purchase suggestions and holding advice are paused until the next successful update. Values are shown at the last known price only.</div>';
  var a = ageDays(D.generated_at);
  if (!DEMO && a != null && a >= 1 && !(st.last_failure && st.outcome === 'failed')) h += '<div class="banner">This report was generated ' + ft(D.generated_at) + ' (' + a + ' day' + (a === 1 ? '' : 's') + ' ago). It is not today\'s analysis.</div>';
  if (st.outcome === 'failed') h += '<div class="banner neg" role="alert"><b>The latest update failed</b> (' + fd(st.run_date) + '). You are looking at the last good report from ' + ft(D.generated_at) + '. Do not treat it as today\'s completed analysis. ' + esc(st.error || '') + '</div>';
  else if (st.outcome === 'skipped') h += '<div class="banner">' + esc((st.notes || [])[0] || 'The last run was skipped (market closed).') + '</div>';
  (D.notes || []).forEach(function (n) { if (/No new market bar|missed|fewer|unavailable|failed|Could not/i.test(n)) h += '<div class="banner">' + esc(n) + '</div>'; });
  return h;
}
function kpi(l, v, s, src, cls) { return '<div class="panel kpi"><div class="l">' + l + (src ? srcTag(src) : '') + '</div><div class="v ' + (cls || '') + '">' + v + '</div><div class="s">' + (s || '') + '</div></div>'; }
function itemCard(i, withDecide) {
  var dec = withDecide && i.category !== 'none' ? '<p class="row"><span class="meta">Record my decision:</span><button class="ghost sm" data-act="decide" data-id="' + esc(i.id) + '" data-d="approved">Approve</button><button class="ghost sm" data-act="decide" data-id="' + esc(i.id) + '" data-d="rejected">Reject</button><button class="ghost sm" data-act="decide" data-id="' + esc(i.id) + '" data-d="deferred">Decide later</button></p>' : '';
  var link = String(i.link || '').charAt(0) === '#' ? '<a href="' + esc(i.link) + '">Open detailed analysis</a>' : '<a href="' + esc(safeUrl(i.link)) + '" rel="noopener noreferrer">Open source</a>';
  return '<div class="item ' + i.level + '"><h4>' + esc(i.title) + ' <span class="tag ' + (i.level === 'CRITICAL' ? 'neg' : i.level === 'HIGH' ? 'amb' : '') + '">' + i.level + '</span>' + (i.new === false ? ' <span class="meta">(standing, not new)</span>' : '') + '</h4>'
    + '<p>' + esc(i.reason) + '</p><p class="meta"><b>What changed:</b> ' + esc(i.changed) + ' &middot; <b>Evidence:</b> ' + esc(i.evidence) + ' &middot; <b>Data:</b> ' + fd(i.asof) + ' &middot; <b>Confidence:</b> ' + esc(i.confidence) + '</p>'
    + (i.limits && i.limits.length ? '<p class="meta"><b>Limitations:</b> ' + esc(i.limits.join('; ')) + '</p>' : '') + '<p><b>Next step:</b> ' + esc(i.next_step) + ' ' + link + '</p>' + dec + '</div>';
}
function allItems(c) { var it = D.items.filter(function (i) { return i.category !== 'none'; }).concat(portItems(c)); if (!it.length) it = D.items.filter(function (i) { return i.category === 'none'; }); var ord = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']; it.sort(function (a, b) { return ord.indexOf(a.level) - ord.indexOf(b.level); }); return it; }
function safetyForm() {
  function radio(name, val, label, cur) { return '<label><input type="radio" name="' + name + '" data-bind="safety.' + name + '" value="' + val + '"' + (cur === val ? ' checked' : '') + '> ' + label + '</label> '; }
  return '<div class="grid" style="margin-top:8px"><div><b>Do you have debt costing 12% a year or more?</b><br>' + radio('debt', 'no', 'No', S.safety.debt) + radio('debt', 'yes', 'Yes', S.safety.debt) + (S.safety.debt == null ? '<span class="amb">not answered</span>' : '') + '</div>'
    + '<div><b>Is your emergency fund at least 6 months of expenses?</b><br>' + radio('emergency', 'ok', 'Yes', S.safety.emergency) + radio('emergency', 'low', 'No', S.safety.emergency) + (S.safety.emergency == null ? '<span class="amb">not answered</span>' : '') + '</div></div>';
}
function gateLine(plan, amt) {
  var g = plan.gate, cls = g.status === 'OPEN' ? 'pos' : g.status === 'CLOSED' ? 'neg' : 'amb';
  var txt = !(amt > 0) ? 'Enter this month\'s amount.' : g.status === 'CLOSED' ? 'Safe amount this month: ' + inr(0) + '.' : g.status === 'UNVERIFIED' ? 'Preview only: ' + inr(g.budget) + ' would be used, but the plan cannot be approved until you answer both safety questions.'
    : 'Safe to invest up to ' + inr(g.budget) + (g.status === 'REDUCED' ? ' (half of ' + inr(amt) + ')' : '') + '.';
  return '<p class="' + cls + '"><b>' + esc(txt) + '</b></p>' + g.notes.map(function (n) { return '<p class="mute">' + esc(n) + '</p>'; }).join('');
}
function logDecision(o, decision) {
  var s = byT[o.ticker] || {}, day = new Date().toISOString().slice(0, 10);
  if (S.journal.some(function (j) { return j.key === o.key && j.date === day; })) return false;
  S.journal.unshift({ id: uid(), key: o.key, date: day, ticker: o.ticker, name: o.name, proposed: o.proposed, decision: decision, decidedAt: decision === 'deferred' ? null : new Date().toISOString(),
    evidence: { status: s.status || null, research: s.research == null ? null : s.research, entry: s.entry == null ? null : s.entry, price: s.price == null ? null : s.price, asof: s.asof || null,
      conf: s.confidence ? s.confidence.label : null, why: (o.why || s.why || []).slice(0, 3), zone: s.zones ? s.zones.ideal : null, qty: o.qty || null, limit: o.limit || null, source: D.provider, mode: D.mode }, note: '' });
  save(); return true;
}

/* ---------- views ---------- */
var VIEWS = {};
VIEWS.overview = function () {
  var c = ctx(), p = c.port, items = allItems(c), ds = dataState(), opp = D.stocks.filter(function (s) { return isApproved(s.ticker) && s.status === 'ACCUMULATE CANDIDATE'; }).sort(function (a, b) { return (b.entry || 0) - (a.entry || 0); }).slice(0, 5);
  var has = p.rows.length > 0, h = banners();
  h += '<h2 style="margin-top:0">Your portfolio ' + srcTag('you') + '</h2>';
  if (!has) h += '<div class="panel"><p>No holdings entered yet. <a href="#/portfolio">Add your transactions</a> to see value, profit, XIRR and personal advice. Everything on this page that does not need your holdings is already live below.</p></div>';
  else {
    var x = c.xirr, dc = p.dayChange, mc = c.monthChg;
    h += '<div class="grid g4">' + kpi('Portfolio value', inrS(p.total), p.missingPrices.length ? p.missingPrices.length + ' holding(s) lack a price' : 'as of ' + fd(D.price_date), 'market') + kpi('Invested capital', inrS(p.invested), 'from your transactions', 'you')
      + kpi('Unrealised P&L', inrS(p.pnl), p.invested ? pc(p.pnl / p.invested * 100) : '', 'market', p.pnl >= 0 ? 'pos' : 'neg') + kpi('Realised P&L', inrS(c.realized), 'dividends ' + inrS(c.divs), 'you', c.realized >= 0 ? 'pos' : 'neg')
      + kpi('Day change', dc == null ? 'n/a' : inrS(dc), dc == null ? 'needs market prices' : pc(dc / (p.total - dc) * 100) + ' (approx.)', 'market', dc >= 0 ? 'pos' : 'neg') + kpi('Month change', mc == null ? 'n/a' : inrS(mc), 'approx.: assumes today\'s holdings all month', 'market', mc >= 0 ? 'pos' : 'neg')
      + kpi('XIRR', x.value == null ? 'n/a' : pc(x.value * 100), x.value == null ? esc(x.why) : (c.bench != null ? 'Nifty 50 price index, same cash flows: ' + pc(c.bench * 100) : 'benchmark unavailable'), 'you')
      + kpi('Cash available', 'not tracked', 'enter it in your own notes; not used in advice', '') + '</div>';
    h += '<div class="grid g2" style="margin-top:10px"><div class="panel"><h3>Sector allocation (red mark = your ' + D.rules.maxSector + '% limit)</h3>' + bars(Object.keys(p.sectors).sort(function (a, b) { return p.sectors[b] - p.sectors[a]; }).map(function (k) { return { l: k, v: p.sectors[k] }; }), D.rules.maxSector) + '</div>'
      + '<div class="panel"><h3>Risk and concentration</h3>' + (c.breaches.length ? c.breaches.map(function (b) { return '<p class="amb">' + esc(b.subject) + ' is ' + b.value.toFixed(1) + '% (limit ' + b.limit + '%)</p>'; }).join('') : '<p class="pos">No limit is breached.</p>')
      + (MIS.limitsContext(p, D.rules).building ? '<p class="mute">With fewer than ' + D.rules.minPositions + ' holdings the ' + D.rules.maxSingle + '% single-stock limit cannot hold, so a softer ' + D.rules.concCapBuilding + '% cap applies.</p>' : '') + maxDd() + '</div></div>';
  }
  h += '<div class="grid g2" style="margin-top:14px"><div class="panel"><h2>Safe to invest this month</h2><div class="row"><label class="field">Amount (\u20B9)<input class="bigin" id="amount" inputmode="numeric" data-bind="amount" value="' + esc(S.amount) + '" placeholder="20000"></label></div>' + gateLine(c.plan, c.amt) + safetyForm()
    + '<p><a href="#/planner">' + (c.plan.rows.length ? 'Open the planner: ' + c.plan.rows.length + ' stock(s) proposed' : 'Open the planner') + '</a></p></div>'
    + '<div class="panel"><h2>Today\'s action centre</h2>' + items.slice(0, 4).map(function (i) { return itemCard(i, false); }).join('') + '<p><a href="#/actions">See all ' + items.filter(function (i) { return i.category !== 'none'; }).length + ' items</a></p></div></div>';
  h += '<div class="grid g2" style="margin-top:14px"><div class="panel"><h2>New opportunities worth researching</h2>' + (opp.length ? opp.map(function (s) { return '<p><a href="#/stock/' + esc(s.ticker) + '"><b>' + esc(s.name) + '</b></a> ' + inr(s.price, 1) + ' (' + fd(s.asof) + '), range ' + inr(s.zones.ideal[0]) + ' to ' + inr(s.zones.ideal[1]) + '<br><span class="mute">business score ' + s.research + ', ' + esc(s.confidence.label) + ' confidence. Research, not a buy order.</span></p>'; }).join('') : '<p class="mute">No approved stock is inside its entry range today. Waiting is a valid decision.</p>') + '</div>'
    + '<div class="panel"><h2>What changed since the last analysis</h2>' + (D.changes.length ? D.changes.slice(0, 6).map(function (c2) { return '<p><b>' + esc(c2.title) + '</b><br><span class="mute">' + esc(c2.detail) + '</span></p>'; }).join('') : '<p>' + (D.status && D.status.runs && D.status.runs.length > 1 ? 'No material changes detected.' : 'Baseline established: comparisons start from the next successful run.') + '</p>') + '</div></div>';
  return h;
};
function maxDd() {
  var keys = Object.keys(S.pfHistory).sort(); if (keys.length < 20) return '<p class="mute">Max drawdown: needs about 20 days of saved portfolio values (' + keys.length + ' so far, saved each time you open this page with real data).</p>';
  var peak = 0, dd = 0; keys.forEach(function (k) { var v = S.pfHistory[k]; peak = Math.max(peak, v); dd = Math.min(dd, v / peak - 1); }); return '<p>Max drawdown since you started saving: <b>' + pc(dd * 100) + '</b> ' + srcTag('you') + '</p>';
}
VIEWS.actions = function () {
  var c = ctx(), items = allItems(c), f = S.filter, h = banners();
  h += '<div class="row">' + ['all'].concat(Object.keys(CATNAMES)).map(function (k) { var n = k === 'all' ? items.length : items.filter(function (i) { return i.category === k; }).length; return n || k === 'all' ? '<button class="' + (f === k ? '' : 'ghost') + ' sm" data-act="filter" data-k="' + k + '">' + (k === 'all' ? 'All' : CATNAMES[k]) + ' (' + n + ')</button>' : ''; }).join('') + '</div>';
  var shown = items.filter(function (i) { return f === 'all' || i.category === f; });
  h += shown.map(function (i) { return itemCard(i, true); }).join('') || '<p>No material changes detected.</p>';
  h += '<p class="mute">Every item states why it appeared, what changed, the evidence and its date, a next step, and its confidence and limitations. Items are only generated from real differences or current rule breaches. Nothing is invented on quiet days.</p>';
  return h;
};
VIEWS.planner = function () {
  var c = ctx(), plan = c.plan, h = banners(), appr = D.stocks.filter(function (s) { return isApproved(s.ticker) && s.status !== 'DATA UNAVAILABLE' && s.status !== 'AVOID'; }).sort(function (a, b) { return (b.research || 0) - (a.research || 0); });
  h += '<div class="grid g2"><div class="panel"><h2 style="margin-top:0">1. Budget and safety</h2><label class="field">How much are you investing this month? (\u20B9)<input class="bigin" id="amount" inputmode="numeric" data-bind="amount" value="' + esc(S.amount) + '" placeholder="20000"></label>' + gateLine(plan, c.amt) + safetyForm() + '</div>'
    + '<div class="panel"><h2 style="margin-top:0">2. Method</h2><div class="row"><label><input type="radio" name="method" data-bind="method" value="risk"' + (S.method === 'risk' ? ' checked' : '') + '> Risk-adjusted (score per unit of volatility)</label><label><input type="radio" name="method" data-bind="method" value="equal"' + (S.method === 'equal' ? ' checked' : '') + '> Equal-weighted</label></div>'
    + '<p><label><input type="checkbox" data-bind="staged"' + (S.staged ? ' checked' : '') + '> Show staged entry (three tranches inside the range)</label></p>'
    + '<h3>Stocks to consider (up to 10; none ticked = automatic picks inside their entry range)</h3><div style="max-height:190px;overflow:auto;border:1px solid var(--line);padding:4px 8px">'
    + appr.slice(0, 60).map(function (s) { return '<label style="display:block"><input type="checkbox" data-bind="sel:' + esc(s.ticker) + '"' + (S.selected.indexOf(s.ticker) >= 0 ? ' checked' : '') + '> ' + esc(s.name) + ' <span class="mute">' + s.research + ', ' + (inRange(s) ? '<span class="pos">in range</span>' : 'above range') + '</span></label>'; }).join('') + '</div>'
    + '<p><button class="ghost sm" data-act="autopick">Back to automatic picks</button></p></div></div>';
  h += '<h2>3. Proposed plan</h2><div class="panel"><p><b>' + esc(plan.verdict) + '</b></p>' + plan.notes.map(function (n) { return '<p class="amb">' + esc(n) + '</p>'; }).join('');
  if (plan.rows.length) {
    h += '<p>Total about <b>' + inr(plan.totalSpend) + '</b> including estimated costs; cash left <b>' + inr(plan.cashLeft) + '</b> of ' + inr(c.amt) + '. You are not required to invest the full amount.</p>';
    plan.rows.forEach(function (r) {
      var st = MIS.stageRow(r), s = byT[r.ticker];
      h += '<div class="item ' + (r.inRange ? 'MEDIUM' : 'HIGH') + '"><h4><a href="#/stock/' + esc(r.ticker) + '">' + esc(r.name) + '</a> <span class="mute">' + esc(r.ticker) + ' &middot; ' + esc(r.sector) + '</span> ' + (r.inRange ? '<span class="tag pos">inside entry range</span>' : '<span class="tag amb">above range: pending order</span>') + '</h4>'
        + '<div class="grid g4"><div>Latest price<br><b>' + inr(r.current, 2) + '</b> <span class="meta">' + fd(s.asof) + ', end-of-day</span></div><div>Preferred range<br><b>' + inr(r.zone[0], 1) + ' to ' + inr(r.zone[1], 1) + '</b></div>'
        + '<div>Limit order<br><b>' + inr(r.limit, 2) + '</b></div><div>Shares affordable<br><b>' + r.shares + '</b> (' + inr(r.amount) + ' + ' + inr(r.cost) + ' costs)</div>'
        + '<div>Share of this month<br><input type="number" min="0" max="100" step="1" style="width:80px" id="ov-' + esc(r.ticker) + '" data-bind="ov:' + esc(r.ticker) + '" value="' + (S.overrides[r.ticker] != null ? S.overrides[r.ticker] : r.pctOfMonth.toFixed(0)) + '"> %</div><div>Weight after purchase<br><b>' + r.weightAfter.toFixed(1) + '%</b> of portfolio</div></div>'
        + (!r.inRange ? '<p class="amb"><b>Why it is not a buy today:</b> the price is ' + Math.abs(r.distancePct).toFixed(1) + '% above the top of the preferred range. The system recommends WAITING for a pullback to about ' + inr(r.zone[1], 1) + '. This limit order only fills if that happens.</p>' : '')
        + '<p><b>Why included:</b> ' + esc(r.reason) + ' &middot; business score ' + r.research + ' (' + esc(r.conf.label) + ' confidence)' + (r.gov === 'unreviewed' ? ' &middot; <span class="amb">governance not reviewed by you</span>' : '') + '</p>'
        + '<p class="meta"><b>Downside risks:</b> ' + esc(r.risks.join(' | ') || 'n/a') + ' &middot; re-check the business below ' + inr(r.review, 1) + '</p>'
        + '<p class="meta"><b>Staged vs immediate:</b> ' + (S.staged ? st.tranches.map(function (t) { return t.shares + ' @ ' + inr(t.price, 2); }).join(', ') + '. ' : '') + 'Staged average ' + inr(st.avg, 2) + ' vs immediate ' + inr(r.limit, 2) + ' (' + pc((st.avg / r.limit - 1) * 100) + '). ' + esc(st.note) + '</p></div>';
    });
    var secAfter = {}; plan.rows.forEach(function (r) { secAfter[r.sector] = (secAfter[r.sector] || 0) + r.amount; });
    var tot = c.port.total + plan.totalSpend, ks = {}; Object.keys(c.port.sectors).concat(Object.keys(secAfter)).forEach(function (k) { ks[k] = ((c.port.sectors[k] || 0) / 100 * c.port.total + (secAfter[k] || 0)) / tot * 100; });
    h += '<h3>Sector allocation after these purchases</h3>' + bars(Object.keys(ks).sort(function (a, b) { return ks[b] - ks[a]; }).map(function (k) { return { l: k, v: ks[k] }; }), D.rules.maxSector);
    h += '<div class="row" style="margin-top:10px"><button data-act="plan-save">Save plan</button><button data-act="plan-approve"' + (plan.approvable ? '' : ' disabled') + '>Approve plan</button><button class="ghost" data-act="plan-dismiss">Dismiss plan</button></div>'
      + (plan.approvable ? '<p class="mute">Approve records your intention in the decision journal. This tool never places orders; you place them in your broker.</p>' : '<p class="amb">Approval is disabled: ' + esc(DEMO ? 'demo data' : plan.gate.status === 'UNVERIFIED' ? 'safety questions unanswered' : plan.gate.status === 'CLOSED' ? 'safety gate closed' : 'nothing is inside its entry range today') + '.</p>');
  }
  if (plan.skipped.length) h += '<details><summary>Why other stocks were skipped (' + plan.skipped.length + ')</summary><ul>' + plan.skipped.slice(0, 40).map(function (s) { return '<li>' + esc((byT[s.ticker] || {}).name || s.ticker) + ': ' + esc(s.reason) + '</li>'; }).join('') + '</ul></details>';
  h += '</div><h2>Saved plans</h2>' + (S.plans.length ? S.plans.slice(0, 10).map(function (p) { return '<div class="item"><b>' + fd(p.date) + '</b> ' + inr(p.amount) + ' &middot; ' + p.rows.length + ' stock(s) &middot; <span class="tag ' + (p.status === 'approved' ? 'pos' : '') + '">' + esc(p.status) + '</span> <span class="meta">' + p.rows.map(function (r) { return esc(r.name) + ' ' + r.shares + '@' + r.limit; }).join(', ') + '</span> <button class="ghost sm" data-act="plan-del" data-id="' + p.id + '">Delete</button></div>'; }).join('') : '<p class="mute">None yet.</p>');
  return h;
};

/* ---------- portfolio ---------- */
var importPreview = null, csvDraft = '';
VIEWS.portfolio = function () {
  var c = ctx(), p = c.port, h = banners(), actBy = {}; c.acts.forEach(function (a) { actBy[a.ticker] = a; });
  h += '<div class="grid g4">' + kpi('Value', inrS(p.total), 'market prices', 'market') + kpi('Invested', inrS(p.invested), '', 'you') + kpi('Unrealised P&L', inrS(p.pnl), p.invested ? pc(p.pnl / p.invested * 100) : '', 'market', p.pnl >= 0 ? 'pos' : 'neg')
    + kpi('Realised P&L', inrS(c.realized), 'FIFO, after fees', 'you') + kpi('Dividends', inrS(c.divs), 'from your entries', 'you')
    + kpi('XIRR', c.xirr.value == null ? 'n/a' : pc(c.xirr.value * 100), c.xirr.value == null ? esc(c.xirr.why) : 'vs Nifty 50 price index ' + (c.bench == null ? 'n/a' : pc(c.bench * 100)), 'you')
    + kpi('Est. tax this FY', inrS(c.tax.tax), 'STCG ' + inrS(c.tax.stcg) + ', LTCG ' + inrS(c.tax.ltcg) + '. Estimate only.', 'you') + '</div>';
  h += '<h2>Holdings</h2>' + table('pos', [
    { h: 'Stock', f: function (r) { return '<a href="#/stock/' + esc(r.ticker) + '"><b>' + esc(r.name) + '</b></a><br><span class="mute">' + esc(r.ticker) + '</span>'; }, v: function (r) { return r.name; } },
    { h: 'Qty', n: 1, f: function (r) { return num(r.qty, 0); }, v: function (r) { return r.qty; } }, { h: 'Avg cost', n: 1, f: function (r) { return inr(r.avg, 2); }, v: function (r) { return r.avg; } },
    { h: 'Price', n: 1, f: function (r) { return r.price == null ? '<input type="number" step="any" style="width:90px" id="mp-' + esc(r.ticker) + '" data-bind="mp:' + esc(r.ticker) + '" placeholder="price" aria-label="Price for ' + esc(r.ticker) + '">' : inr(r.price, 2) + (r.priceSource === 'manual' ? '<br><span class="mute">typed by you</span>' : r.priceSource === 'stale' ? '<br><span class="amb">stale</span>' : ''); }, v: function (r) { return r.price; } },
    { h: 'Value', n: 1, f: function (r) { return inr(r.value); }, v: function (r) { return r.value; } }, { h: 'P&L', n: 1, f: function (r) { return r.pnl == null ? 'n/a' : '<span class="' + (r.pnl >= 0 ? 'pos' : 'neg') + '">' + inr(r.pnl) + '<br>' + pc(r.pnlPct) + '</span>'; }, v: function (r) { return r.pnl; } },
    { h: 'Weight', n: 1, f: function (r) { return r.weight == null ? 'n/a' : r.weight.toFixed(1) + '%'; }, v: function (r) { return r.weight; } },
    { h: 'Status', f: function (r) { var a = actBy[r.ticker]; return a ? tag(a.action) : ''; }, v: function (r) { return (actBy[r.ticker] || {}).action; } }], p.rows, { search: p.rows.length > 8, empty: 'No holdings yet. Add a transaction below.' });
  if (c.acts.length) { h += '<h2>Review of each holding</h2><p class="mute">Long-term decisions here use business, valuation, news and portfolio evidence. A price fall alone never produces a sell recommendation.</p>';
    c.acts.forEach(function (a) { h += '<div class="item ' + (a.action === 'EXIT REVIEW' ? 'CRITICAL' : a.action === 'REDUCE CANDIDATE' || a.action === 'WATCH' ? 'HIGH' : a.action === 'ACCUMULATE CANDIDATE' ? 'MEDIUM' : '') + '"><h4>' + esc(a.name) + ' ' + tag(a.action) + ' <span class="meta">confidence ' + esc(a.confidence) + '</span></h4>'
      + a.reasons.map(function (r) { return '<p>' + esc(r) + '</p>'; }).join('') + (a.priceNote ? '<p><b>' + esc(a.priceNote) + '</b></p>' : '') + a.notes.map(function (r) { return '<p class="meta">' + esc(r) + '</p>'; }).join('')
      + (a.limits.length ? '<p class="meta">Limitations: ' + esc(a.limits.join('; ')) + '</p>' : '') + '</div>'; }); }
  var hist = Object.keys(S.pfHistory).sort();
  if (hist.length > 1) h += '<h2>Portfolio value history ' + srcTag('you') + '</h2><div class="panel">' + lineChart({ series: [{ name: 'Value', color: 'var(--acc)', data: hist.map(function (k) { return S.pfHistory[k]; }) }], label: 'Portfolio value over time' }) + '<p class="mute">' + fd(hist[0]) + ' to ' + fd(hist[hist.length - 1]) + '. One point is saved each day you open this page with real data.</p></div>';
  h += '<h2>Add a transaction</h2><form class="panel" id="txform"><div class="row"><label class="field">Type<select id="tx-type"><option>buy</option><option>sell</option><option>dividend</option><option>split</option><option>bonus</option></select></label>'
    + '<label class="field">Stock<input id="tx-t" list="tl" required placeholder="TCS" autocomplete="off"></label><label class="field">Quantity<input id="tx-q" type="number" step="any" min="0" required style="width:100px"></label>'
    + '<label class="field">Price per share (\u20B9)<input id="tx-p" type="number" step="any" min="0" required style="width:120px"></label><label class="field">Date<input id="tx-d" type="date" required></label><label class="field">Fees (\u20B9)<input id="tx-f" type="number" step="any" min="0" style="width:90px" value="0"></label>'
    + '<label class="field">&nbsp;<button type="submit">Add</button></label></div><p class="mute">Dividend: price = dividend per share. Split: quantity = new shares per old share (1:5 split = 5). Bonus: quantity = bonus shares per share held (1:1 = 1).</p></form>'
    + '<datalist id="tl">' + D.stocks.map(function (s) { return '<option value="' + esc(s.ticker.replace('.NS', '')) + '">' + esc(s.name) + '</option>'; }).join('') + '</datalist>';
  h += '<details' + (importPreview || csvDraft ? ' open' : '') + '><summary>Import transactions from CSV (checked before saving)</summary><p class="mute">Columns: date,type,ticker,quantity,price,fees,note. Dates as YYYY-MM-DD.</p><textarea id="csvtext" rows="5" style="width:100%" placeholder="date,type,ticker,quantity,price,fees,note&#10;2025-04-10,buy,TCS,3,3500,20,">' + esc(csvDraft) + '</textarea><div class="row"><input type="file" id="csvfile" accept=".csv,text/csv"><button class="ghost" data-act="csv-check">Check rows</button></div>';
  if (importPreview) h += '<p><b>' + importPreview.rows.length + ' valid row(s)</b>, ' + importPreview.errors.length + ' problem(s).</p>' + (importPreview.errors.length ? '<ul class="neg">' + importPreview.errors.map(function (e) { return '<li>' + esc(e) + '</li>'; }).join('') + '</ul>' : '') + (importPreview.rows.length ? '<button data-act="csv-import">Import the valid rows</button>' : '');
  h += '</details>';
  if (c.ledger.errors.length) h += c.ledger.errors.map(function (e) { return '<div class="banner">' + esc(e) + '</div>'; }).join('');
  h += '<h2>Transactions ' + srcTag('you') + '</h2>' + table('tx', [{ h: 'Date', f: function (t) { return t.date ? fd(t.date) : '<span class="mute">undated</span>'; }, v: function (t) { return t.date; } }, { h: 'Type', f: function (t) { return esc(t.type); }, v: function (t) { return t.type; } },
    { h: 'Stock', f: function (t) { return esc((byT[t.ticker] || {}).name || t.ticker); }, v: function (t) { return t.ticker; } }, { h: 'Qty', n: 1, f: function (t) { return num(t.qty, 2); }, v: function (t) { return t.qty; } }, { h: 'Price', n: 1, f: function (t) { return inr(t.price, 2); }, v: function (t) { return t.price; } },
    { h: 'Fees', n: 1, f: function (t) { return inr(t.fees, 2); }, v: function (t) { return t.fees; } }, { h: '', f: function (t) { return '<button class="danger sm" data-act="tx-del" data-id="' + esc(t.id) + '">Delete</button>'; } }], S.tx.slice().reverse(), { empty: 'No transactions yet.' });
  if (c.ledger.realized.length) h += '<h2>Realised gains (FIFO)</h2>' + table('real', [{ h: 'Sold', f: function (r) { return fd(r.sellDate); }, v: function (r) { return r.sellDate; } }, { h: 'Stock', f: function (r) { return esc(r.ticker); }, v: function (r) { return r.ticker; } }, { h: 'Qty', n: 1, f: function (r) { return num(r.qty, 2); }, v: function (r) { return r.qty; } },
    { h: 'P&L', n: 1, f: function (r) { return '<span class="' + (r.pnl >= 0 ? 'pos' : 'neg') + '">' + inr(r.pnl) + '</span>'; }, v: function (r) { return r.pnl; } }, { h: 'Held (days)', n: 1, f: function (r) { return r.days == null ? 'n/a' : r.days; }, v: function (r) { return r.days; } }], c.ledger.realized.slice().reverse(), { size: 8 });
  h += '<h2>Backup</h2><div class="row"><button class="ghost" data-act="export">Download backup</button><button class="ghost" data-act="restore">Restore backup</button><input type="file" id="restorefile" accept="application/json" hidden><button class="danger" data-act="wipe">Erase everything on this device</button></div><p class="mute">All entries live only in this browser. Download a backup regularly. To use the same holdings on every device, turn on <a href="#/sync">Cloud sync</a> (encrypted).</p>';
  return h;
};

/* ---------- research ---------- */
var THEMES = [['Infrastructure and construction', /construct|infra|cement|road|engineering|building/i], ['Railways', /rail|wagon|loco|titagarh|rvnl|irctc/i], ['Energy transition and power', /power|electric|solar|renewable|transmission|cable|battery|energy/i],
  ['Industrial expansion', /capital goods|industrial|machinery|pump|bearing|forging|automation/i], ['Electronics manufacturing', /electronic|semicon|ems\b|kaynes|dixon|amber/i], ['AI and digital infrastructure', /information technology|software|data|digital|cloud|analytics|telecom/i], ['Logistics', /logistic|transport|shipping|port|warehouse|container/i]];
function themesOf(s) { var t = s.name + ' ' + s.sector + ' ' + ((s.fund || {}).industry || ''); return THEMES.filter(function (x) { return x[1].test(t); }).map(function (x) { return x[0]; }); }
function stockCols(extra) {
  return [{ h: 'Stock', f: function (s) { return '<a href="#/stock/' + esc(s.ticker) + '"><b>' + esc(s.name) + '</b></a> ' + (isNew(s.ticker) ? '<span class="tag amb">NEW</span>' : '') + '<br><span class="mute">' + esc(s.sector) + ' &middot; ' + (s.cap === 'S' ? 'small' : 'mid') + '-cap</span>'; }, v: function (s) { return s.name; } },
    { h: tip('Score', 'Business score out of 100 over the evidence available. Not a probability of returns.'), n: 1, f: function (s) { return s.research == null ? 'Insufficient data' : s.research; }, v: function (s) { return s.research; } },
    { h: tip('Entry', 'Is today\'s chart a sensible time to buy? Separate from business quality.'), n: 1, f: function (s) { return s.entry == null ? 'n/a' : s.entry; }, v: function (s) { return s.entry; } },
    { h: 'Status', f: function (s) { return tag(s.status); }, v: function (s) { return s.status; } },
    { h: 'Price', n: 1, f: function (s) { return s.price == null ? 'n/a' : inr(s.price, 1) + '<br><span class="mute">' + fd(s.asof) + '</span>'; }, v: function (s) { return s.price; } },
    { h: 'Entry range', f: function (s) { return s.zones ? inr(s.zones.ideal[0]) + ' to ' + inr(s.zones.ideal[1]) + '<br>' + (inRange(s) ? '<span class="pos">inside</span>' : '<span class="mute">wait</span>') : 'n/a'; }, v: function (s) { return s.zones ? s.zones.distance_pct : null; } },
    { h: 'Confidence', f: function (s) { return esc(s.confidence.label); }, v: function (s) { return s.confidence.pct; } }].concat(extra || []);
}
VIEWS.research = function () {
  var c = ctx(), h = banners(), tab = S.rtab || 'rank';
  h += '<div class="row">' + [['rank', 'Three rankings'], ['all', 'All candidates'], ['new', 'New: under review (' + D.stocks.filter(function (s) { return isNew(s.ticker); }).length + ')'], ['themes', 'Research themes']].map(function (t) { return '<button class="' + (tab === t[0] ? '' : 'ghost') + ' sm" data-act="rtab" data-k="' + t[0] + '">' + t[1] + '</button>'; }).join('') + '</div>';
  var ok = D.stocks.filter(function (s) { return isApproved(s.ticker) && s.research != null && s.status !== 'AVOID' && s.status !== 'DATA UNAVAILABLE'; });
  if (tab === 'rank') {
    h += '<p class="mute">Three separate questions, three separate lists. A great business can be overvalued today, and a good chart can sit on a weak business.</p>';
    h += '<h2>1. Best long-term businesses</h2>' + table('r1', stockCols(), ok.slice().sort(function (a, b) { return b.research - a.research; }).slice(0, 12), { search: false });
    h += '<h2>2. Best current entry opportunities</h2>' + table('r2', stockCols(), ok.filter(function (s) { return s.research >= 55 && s.entry != null; }).sort(function (a, b) { return (inRange(b) - inRange(a)) || (b.entry - a.entry); }).slice(0, 12), { search: false });
    h += '<h2>3. Best risk-adjusted additions to my portfolio</h2>';
    if (!c.port.rows.length) h += '<div class="panel">Add your holdings to get this list: it depends on what you already own (position, sector and small-cap room).</div>';
    else { var lc = MIS.limitsContext(c.port, D.rules), cap = lc.building ? D.rules.concCapBuilding : D.rules.maxSingle;
      var fit = ok.filter(function (s) { return (lc.heldW[s.ticker] || 0) < cap * 0.8 && !((c.port.sectors[s.sector] || 0) >= D.rules.maxSector) && !(s.cap === 'S' && lc.smallW >= D.rules.maxSmall && !lc.building); })
        .map(function (s) { var pen = 0; if ((c.port.sectors[s.sector] || 0) >= D.rules.maxSector * 0.85) pen += 25; var f = s.research * 0.45 + (s.entry || 0) * 0.35 + 20 - pen - (s.atrPct ? Math.min(s.atrPct, 8) : 3); return { s: s, f: f }; }).sort(function (a, b) { return b.f - a.f; }).slice(0, 12).map(function (x) { return x.s; });
      h += table('r3', stockCols([{ h: 'In your portfolio', f: function (s) { return lc.heldW[s.ticker] ? lc.heldW[s.ticker].toFixed(1) + '%' : '-'; } }]), fit, { search: false }); }
  } else if (tab === 'all') {
    h += '<h2>All candidates (' + D.stocks.length + ')</h2><p class="mute">' + D.universe_size + ' mid and small companies screened; large caps are excluded on purpose.</p>' + table('all', stockCols([{ h: 'Trend', f: function (s) { return spark((s.series || []).slice(-120)); } }, { h: 'Watchlist', f: function (s) { return isApproved(s.ticker) ? 'approved' : S.review[s.ticker] === 'ignored' ? 'ignored' : 'review'; }, v: function (s) { return isApproved(s.ticker) ? 1 : 0; } }]), D.stocks, { size: 15 });
  } else if (tab === 'new') {
    var nw = D.stocks.filter(function (s) { return isNew(s.ticker); });
    h += '<h2>New candidates under review</h2><p class="mute">New names are discovered automatically but are NOT added to your approved watchlist, and the planner ignores them, until you approve them.</p>' + (nw.length ? table('new', stockCols([{ h: 'Decision', f: function (s) { return '<button class="sm" data-act="approve-stock" data-t="' + esc(s.ticker) + '">Approve</button> <button class="ghost sm" data-act="ignore-stock" data-t="' + esc(s.ticker) + '">Ignore</button>'; } }]), nw) : '<div class="panel">No new candidates since you first opened the dashboard.</div>');
  } else {
    h += '<h2>Research themes</h2><p class="mute">Themes to research, not automatic buy recommendations. Matching is by industry and company name, so check the business yourself.</p>';
    THEMES.forEach(function (t) { var m = ok.filter(function (s) { return themesOf(s).indexOf(t[0]) >= 0; }).sort(function (a, b) { return b.research - a.research; }).slice(0, 6);
      h += '<div class="panel" style="margin:8px 0"><h3>' + t[0] + ' (' + m.length + ' shown)</h3>' + (m.length ? m.map(function (s) { return '<a href="#/stock/' + esc(s.ticker) + '">' + esc(s.name) + '</a> <span class="mute">' + s.research + '</span>'; }).join(' &middot; ') : '<span class="mute">no match among screened candidates</span>') + '</div>'; });
  }
  return h;
};
var COMPNAMES = { growth: 'Growth', business_quality: 'Business quality (ROE, margins)', financial_strength: 'Financial strength (debt, cash flow)', size_runway: 'Size and runway (S and E of SMILE)', governance: 'Governance (M of SMILE)', valuation: 'Valuation', technical: 'Technical trend', tailwinds: 'Industry tailwind (I of SMILE)' };
function row2(l, v, note) { return '<tr><td>' + l + '</td><td class="n"><b>' + v + '</b></td><td class="w mute">' + (note || '') + '</td></tr>'; }
VIEWS.stock = function (tk) {
  var s = byT[tk]; if (!s) return banners() + '<p>Stock not found in today\'s research list. <a href="#/research">Back to research</a></p>';
  var h = banners(), f = s.fund, g = s.growth, t = s.tech, z = s.zones, sc = s.scenarios, ser = s.series || [];
  h += '<p><a href="#/research">&larr; Research</a></p><div class="panel"><div class="row"><div><h2 style="margin:0">' + esc(s.name) + ' <span class="mute">' + esc(s.ticker) + '</span></h2><span class="mute">' + esc(s.sector) + (f.industry ? ' &middot; ' + esc(f.industry) : '') + ' &middot; ' + (s.cap === 'S' ? 'small' : 'mid') + '-cap' + (f.mcap ? ' &middot; market cap \u20B9' + Math.round(f.mcap).toLocaleString('en-IN') + ' crore' : '') + '</span></div><div style="flex:1"></div>'
    + '<div><b style="font-size:20px">' + (s.price == null ? 'n/a' : inr(s.price, 2)) + '</b> <span class="mute">end-of-day, ' + fd(s.asof) + '</span> ' + tag(s.status) + '</div></div>'
    + '<p>' + esc(s.why.join('; ')) + '</p><div class="row"><button class="sm" data-act="approve-stock" data-t="' + esc(s.ticker) + '"' + (isApproved(s.ticker) ? ' disabled' : '') + '>' + (isApproved(s.ticker) ? 'On your watchlist' : 'Approve for watchlist') + '</button> <button class="ghost sm" data-act="addsel" data-t="' + esc(s.ticker) + '">Add to planner</button> '
    + themesOf(s).map(function (x) { return '<span class="chip">' + x + '</span>'; }).join('') + '</div></div>';
  if (ser.length > 30) { var d50 = sma(ser, 50), d200 = sma(ser, 200); h += '<h3>Price, 50 and 200-day averages, preferred entry range and thesis re-check level</h3><div class="panel">' + lineChart({ series: [{ name: 'Close', color: 'var(--ink)', data: ser, w: 1.5 }, { name: '50-DMA', color: 'var(--acc)', data: d50 }, { name: '200-DMA', color: 'var(--amb)', data: d200, dash: 1 }],
    bands: z ? [{ lo: z.ideal[0], hi: z.ideal[1], label: 'preferred entry range' }] : [], lines: z ? [{ y: z.thesis_review, label: 'thesis re-check ' + Math.round(z.thesis_review) }] : [], label: 'Price chart for ' + s.name }) + '<p class="mute">Last ' + ser.length + ' trading days to ' + fd(s.asof) + '. Adjusted prices.</p></div>'; }
  h += '<div class="grid g2"><div class="panel"><h3>Why this score (' + (s.research == null ? 'insufficient data' : s.research + '/100') + ')</h3><div class="wrap"><table><tbody>' + Object.keys(s.components).map(function (k) { var c = s.components[k]; return row2(COMPNAMES[k] || k, c.data ? c.points + ' / ' + c.max : 'Insufficient data', esc((c.note || '') + (c.missing && c.missing.length ? ' Missing: ' + c.missing.join(', ') : ''))); }).join('') + '</tbody></table></div>'
    + '<p class="mute">The score weights the evidence that exists. Components without data are excluded, not guessed. It is NOT a probability of a multibagger outcome. Data confidence: ' + s.confidence.pct + '% of inputs (' + esc(s.confidence.label) + ').</p><p class="meta"><b>Limitations:</b> ' + esc(s.confidence.limits.join('; ')) + '</p></div>'
    + '<div class="panel"><h3>SMILE checks</h3>' + ['S|Small: still small relative to the opportunity (Rs 1,500 to 50,000 crore)', 'M|Management and governance (your review, or promoter holding of at least 40%)', 'I|Industry tailwind (analyst opinion)', 'L|Leadership: ROE of at least 15% and healthy margins', 'E|Extra-large runway: 10x in 15 years needs 24% a year or less'].map(function (x) { var k = x.split('|')[0], v = s.smile[k]; return '<p><span class="tag ' + (v === true ? 'pos' : v === false ? 'neg' : '') + '">' + k + ' ' + (v === true ? 'yes' : v === false ? 'no' : 'unknown') + '</span> ' + esc(x.split('|')[1]) + '</p>'; }).join('')
    + (s.mb ? '<p>For a 10x in 15 years the earnings must grow about <b>' + s.mb.x10_15y + '% a year</b> if the P/E settles at ' + D.exit_pe + ' (5x in 10 years: ' + s.mb.x5_10y + '%). Arithmetic, not a forecast.</p>' : '<p class="mute">Growth-required maths needs a positive P/E.</p>') + '</div></div>';
  h += '<div class="grid g2"><div class="panel"><h3>Growth, quality and balance sheet</h3><div class="wrap"><table><tbody>'
    + row2('Revenue growth (' + (g.years || 0) + '-yr CAGR)', g.rev3 == null ? 'Insufficient data' : pp(g.rev3), 'annual statements') + row2('Profit growth (' + (g.years || 0) + '-yr CAGR)', g.ni3 == null ? 'Insufficient data' : pp(g.ni3), 'used as the EPS growth proxy; share-count changes not adjusted') + row2('Latest YoY revenue / earnings growth', pp(f.revG) + ' / ' + pp(f.earnG), 'single period, noisy')
    + row2('ROE', pp(f.roe), f.roeDerived ? 'derived as EPS / book value because the provider supplies none' : '') + row2('ROCE', 'Not available', 'the data provider does not supply it') + row2('Operating margin', pp(f.opm), '') + row2('Debt to equity', f.de == null ? 'n/a' : num(f.de, 2), '') + row2('Free cash flow / operating cash flow', (f.fcf == null ? 'n/a' : inr(f.fcf * 1e7)) + ' / ' + (f.ocf == null ? 'n/a' : inr(f.ocf * 1e7)), '')
    + row2('Working capital efficiency', 'Not available', 'no free source') + '</tbody></table></div></div>'
    + '<div class="panel"><h3>Valuation</h3><div class="wrap"><table><tbody>' + row2('P/E (trailing / forward)', num(f.pe) + ' / ' + num(f.fpe), '') + row2('Sector median P/E', s.peers ? s.peers.pe_med : 'Insufficient data', s.peers ? 'median of ' + s.peers.n + ' screened companies in ' + esc(s.peers.sector) + ' (NSE group, a rough peer set)' : 'too few peers')
    + row2('Price to book / EV to EBITDA', num(f.pb) + ' / ' + num(f.evEbitda), '') + row2('Historical valuation range', 'Not available', 'needs a paid history feed') + '</tbody></table></div><p class="mute">Valuation score is a P/E-versus-growth heuristic. It does not know the stock\'s own history.</p>'
    + '<h3>Governance</h3><p>Your review: <b>' + (s.gov === 'unreviewed' ? '<span class="amb">unreviewed</span>' : esc(s.gov)) + '</b> ' + esc(s.govNote || '') + '</p><p class="meta">' + (f.refreshFailed ? '<span class="amb">Fundamentals could not be refreshed today; the saved copy from ' + fd(f.retrieved) + ' is used.</span> ' : '') + 'Promoter/insider holding (proxy): ' + pp(f.insider) + '. Pledging, dilution, auditor changes and related-party deals: not available from free data. Record your own review in data/governance_flags.csv.</p></div></div>';
  h += '<div class="grid g2"><div class="panel"><h3>Entry plan</h3>' + (z ? '<p>Preferred range <b>' + inr(z.ideal[0], 1) + ' to ' + inr(z.ideal[1], 1) + '</b>. Price is <b>' + (z.position === 'in_range' ? 'inside the range' : z.position === 'above' ? z.distance_pct.toFixed(1) + '% above it' : Math.abs(z.distance_pct).toFixed(1) + '% below it') + '</b>.</p>'
    + (z.position === 'above' ? '<p class="amb">Recommendation: wait for a pullback to about ' + inr(z.wait_to, 1) + '. A good business can still be a poor purchase today.</p>' : '') + '<p>Thesis re-check level: ' + inr(z.thesis_review, 1) + ' (review the business, not an automatic sell). Short-term volatility stop (trading only, separate): ' + inr(z.trading_stop, 1) + '. First review zone: ' + inr(z.first_review, 1) + '.</p>'
    + '<p class="meta">Entry factors: ' + esc(s.entryReasons.join('; ') || 'none') + (s.entryAvoid.length ? '. Cautions: ' + esc(s.entryAvoid.join('; ')) : '') + '</p><p class="meta">Suggested horizon: long (10 to 15 years) if the thesis holds. Review every quarter after results.</p>' : '<p class="mute">Entry range unavailable (no price history).</p>') + '</div>'
    + '<div class="panel"><h3>Scenarios (mechanical illustration, not a forecast)</h3>' + (sc ? '<div class="wrap"><table><tbody>' + row2('Bear (repeat of the worst past year)', pc(sc.bear_12m_pct), '12 months, about ' + inr(sc.bear_price)) + row2('Base (earnings growth proxy, constant P/E)', pc(sc.base_12m_pct), 'about ' + inr(sc.base_price)) + row2('Bull (1.5x the growth proxy)', pc(sc.bull_12m_pct), '') + '</tbody></table></div><p class="mute">' + esc(sc.assumption) + '</p>' : '<p class="mute">Insufficient data.</p>')
    + '<h3>What would break the thesis</h3><ul>' + s.invalidation.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></div></div>';
  h += '<div class="grid g2"><div class="panel"><h3>Technicals</h3><div class="wrap"><table><tbody>' + row2('RSI / MACD histogram', num(t.rsi, 0) + ' / ' + num(t.macd_hist, 2), '') + row2('50 / 100 / 200-day average', num(t.dma50, 0) + ' / ' + num(t.dma100, 0) + ' / ' + num(t.dma200, 0), '') + row2('Relative strength vs Nifty 50 (6m)', t.rs_6m_vs_nifty == null ? 'n/a' : pc(t.rs_6m_vs_nifty * 100), '')
    + row2('From 52-week high', pc(t.from_high_pct), 'range ' + num(t.low_52w, 0) + ' to ' + num(t.high_52w, 0)) + row2('Annual volatility / largest gap', num(t.vol_ann_pct, 0) + '% / ' + num(t.max_gap_1y_pct, 1) + '%', '') + row2('Average daily traded value', t.avg_traded_value_cr == null ? 'n/a' : '\u20B9' + num(t.avg_traded_value_cr, 1) + ' cr', 'liquidity') + '</tbody></table></div></div>'
    + '<div class="panel"><h3>News (unverified headlines)</h3>' + ((s.news || []).length ? '<ul>' + s.news.map(function (n) { return '<li><a href="' + esc(safeUrl(n.url)) + '" rel="noopener noreferrer">' + esc(n.title) + '</a><br><span class="meta">' + esc(n.source) + ', ' + ft(n.published) + (n.risk ? ' &middot; <span class="amb">mentions a risk term</span>' : '') + '</span></li>'; }).join('') + '</ul>' : '<p class="mute">No headlines retrieved' + (DEMO ? ' (demo)' : '') + '. Exchange filings are not integrated: check NSE/BSE announcements yourself.</p>') + '</div></div>';
  var ev = (D.history || {})[s.ticker] || [];
  h += '<div class="panel" style="margin-top:10px"><h3>What the system said before, and what happened</h3>' + (ev.length ? table('hist-' + tk, [{ h: 'Date', f: function (e) { return fd(e[0]); }, v: function (e) { return e[0]; } }, { h: 'Status then', f: function (e) { return tag(e[1]); } }, { h: 'Score then', n: 1, f: function (e) { return e[3] == null ? 'n/a' : e[3]; } }, { h: 'Price then', n: 1, f: function (e) { return inr(e[2], 1); } },
    { h: 'Price now', n: 1, f: function () { return inr(s.price, 1); } }, { h: 'Change', n: 1, f: function (e) { return e[2] && s.price ? pc((s.price / e[2] - 1) * 100) : 'n/a'; } }], ev.slice().reverse(), { search: false, size: 8 }) + '<p class="mute">Recorded when each status changed. Past entries are never rewritten.</p>' : '<p class="mute">History starts with the first successful run.</p>') + '</div>';
  h += '<p class="mute">Sources: ' + esc(D.provider) + '; fundamentals retrieved ' + fd(f.retrieved) + '; reporting period: latest annual statements (exact period not supplied by the provider). Generated ' + ft(D.generated_at) + '.</p>';
  return h;
};

/* ---------- markets, journal, health ---------- */
VIEWS.markets = function () {
  var m = D.market, h = banners(), r = m.risk || {};
  h += '<div class="panel"><h2 style="margin-top:0">Market risk</h2><p><span class="tag ' + (r.material ? 'amb' : '') + '">' + esc((r.level || 'unknown')) + '</span> ' + esc(r.reason || 'unavailable') + '</p><p class="mute">India VIX levels are rule-of-thumb thresholds (under 15 calm, 15-20 normal, 20-25 elevated, above 25 high), not predictions.</p></div>';
  function mrow(a) { return a.ok ? '<tr><td><b>' + esc(a.name) + '</b></td><td class="n">' + num(a.last, 2) + '</td><td class="n ' + (a.d1 >= 0 ? 'pos' : 'neg') + '">' + pc(a.d1) + '</td><td class="n">' + pc(a.m1) + '</td><td class="n">' + num(a.rsi, 0) + '</td><td>' + esc(a.trend) + '</td><td>' + fd(a.asof) + '</td><td class="w mute">' + esc(a.instrument || '') + '</td></tr>' : '<tr><td><b>' + esc(a.name) + '</b></td><td colspan="7" class="mute">Data unavailable (not guessed)</td></tr>'; }
  var head = '<thead><tr><th>Asset</th><th class="n">Last</th><th class="n">1 day</th><th class="n">1 month</th><th class="n">RSI</th><th>Trend</th><th>Data date</th><th>How an Indian investor can hold it</th></tr></thead>';
  h += '<h2>Macro</h2><div class="wrap"><table>' + head + '<tbody>' + m.macro.map(mrow).join('') + '</tbody></table></div>';
  h += '<h2>Gold, silver, commodities, currencies' + (m.assets.some(function (a) { return /Bitcoin|Ethereum/.test(a.name); }) ? ', crypto' : '') + '</h2><div class="wrap"><table>' + head + '<tbody>' + m.assets.map(mrow).join('') + '</tbody></table></div><p class="mute">Trend facts only, no price forecasts. Global prices are not what you pay locally (rupee conversion, duties, fund tracking error). Volatile and unpredictable. No leveraged ideas are generated. Crypto stays off unless you enable it in config.yaml.</p>';
  h += '<h2>Headlines (unverified)</h2>' + ((D.news || []).length ? '<ul>' + D.news.map(function (n) { return '<li><a href="' + esc(safeUrl(n.url)) + '" rel="noopener noreferrer">' + esc(n.title) + '</a><br><span class="meta">' + esc(n.source) + ', ' + ft(n.published) + '</span></li>'; }).join('') + '</ul>' : '<p class="mute">No headlines retrieved' + (DEMO ? ' (demo)' : '') + '.</p>');
  h += '<h2>Mutual fund and public investor disclosures</h2><p class="mute">Disclosures are periodic and delayed. The date shown is the DISCLOSURE date, never a trade date. This tool cannot know real-time fund-manager or private-investor trades.</p>'
    + ((D.disclosures || []).length ? table('disc', [{ h: 'Disclosed on', f: function (d) { return fd(d.disclosure_date); }, v: function (d) { return d.disclosure_date; } }, { h: 'Type', f: function (d) { return esc(d.source_type); }, v: function (d) { return d.source_type; } }, { h: 'Entity', f: function (d) { return esc(d.entity); }, v: function (d) { return d.entity; } },
      { h: 'Stock', f: function (d) { return esc(d.ticker); }, v: function (d) { return d.ticker; } }, { h: 'Change', f: function (d) { return esc(d.change); } }, { h: 'Detail', w: 1, f: function (d) { return esc(d.detail); } }, { h: 'Source', f: function (d) { return d.source_url ? '<a href="' + esc(safeUrl(d.source_url)) + '" rel="noopener noreferrer">link</a>' : ''; } }], D.disclosures) : '<div class="panel">None entered. Add rows you verified from AMC or exchange filings to data/disclosures.csv. Nothing is scraped or guessed.</div>');
  h += '<h2>Integrations: what is real</h2>' + table('integ', [{ h: 'Integration', f: function (i) { return esc(i.name); }, v: function (i) { return i.name; } }, { h: 'State', f: function (i) { var bad = /NOT|needs|paid|off|fallback/i.test(i.state); return '<span class="tag ' + (bad ? 'amb' : 'pos') + '">' + esc(i.state) + '</span>'; }, v: function (i) { return i.state; } }, { h: 'Note', w: 1, f: function (i) { return esc(i.note); } }], D.integrations, { search: false, size: 20 });
  return h;
};
function outcome(j) {
  var s = byT[j.ticker], e = j.evidence; if (!s || s.price == null || e.price == null) return { chg: null, verdict: 'Insufficient data to compare' };
  if (s.stale) return { chg: null, verdict: 'Insufficient data: this report\'s prices are stale' };
  var chg = (s.price / e.price - 1) * 100, d = s.research != null && e.research != null ? s.research - e.research : null, v;
  if (s.status === 'AVOID') v = 'Thesis broken: now AVOID'; else if (d != null && d <= -6) v = 'Review: business score fell ' + Math.abs(d).toFixed(1); else if (e.status === 'ACCUMULATE CANDIDATE' && s.status !== 'ACCUMULATE CANDIDATE') v = 'Entry conditions changed: now ' + s.status; else v = 'No evidence of deterioration';
  return { chg: chg, verdict: v, d: d };
}
VIEWS.journal = function () {
  var h = banners();
  h += '<p class="mute">Each entry freezes the evidence available on the day (status, score, price and its date, confidence, reasons). Entries are never edited afterwards; only your decision on a deferred item and added notes can change. Performance is measured against the price then.</p>';
  h += table('jr', [{ h: 'Date', f: function (j) { return fd(j.date); }, v: function (j) { return j.date; } }, { h: 'Stock', f: function (j) { return '<a href="#/stock/' + esc(j.ticker) + '">' + esc(j.name) + '</a>'; }, v: function (j) { return j.name; } },
    { h: 'Proposed action', w: 1, f: function (j) { return esc(j.proposed) + (j.evidence.limit ? '<br><span class="meta">' + j.evidence.qty + ' sh at limit ' + inr(j.evidence.limit, 2) + '</span>' : ''); }, v: function (j) { return j.proposed; } },
    { h: 'Evidence then', w: 1, f: function (j) { var e = j.evidence; return esc((e.status || 'n/a') + ', score ' + (e.research == null ? 'n/a' : e.research) + ', price ' + (e.price == null ? 'n/a' : inr(e.price, 1)) + ' (' + fd(e.asof) + '), ' + (e.conf || 'n/a') + ' confidence') + (e.why.length ? '<br><span class="meta">' + esc(e.why.join('; ')) + '</span>' : '') + (e.mode !== 'real' ? '<br><span class="tag neg">synthetic</span>' : ''); } },
    { h: 'My decision', f: function (j) { return '<span class="tag ' + (j.decision === 'approved' ? 'pos' : j.decision === 'rejected' ? 'neg' : 'amb') + '">' + esc(j.decision) + '</span>' + (j.decision === 'deferred' ? '<br><button class="ghost sm" data-act="jr" data-id="' + j.id + '" data-d="approved">Approve</button> <button class="ghost sm" data-act="jr" data-id="' + j.id + '" data-d="rejected">Reject</button>' : ''); }, v: function (j) { return j.decision; } },
    { h: 'Since then', n: 1, f: function (j) { var o = outcome(j); return o.chg == null ? 'n/a' : '<span class="' + (o.chg >= 0 ? 'pos' : 'neg') + '">' + pc(o.chg) + '</span>'; }, v: function (j) { return outcome(j).chg; } },
    { h: 'Thesis still valid?', w: 1, f: function (j) { return esc(outcome(j).verdict); } },
    { h: 'Notes', w: 1, f: function (j) { return (j.note ? esc(j.note) + '<br>' : '') + '<button class="ghost sm" data-act="jr-note" data-id="' + j.id + '">Add note</button>'; } }], S.journal, { empty: 'No decisions recorded yet. Use the Approve / Reject buttons in the action centre or the planner.' });
  return h;
};
VIEWS.health = function () {
  var st = statusLive || D.status || {}, ms = marketNow(), h = banners(), ds = dataState();
  var gh = /\.github\.io$/.test(location.hostname) ? 'https://github.com/' + location.hostname.split('.')[0] + '/' + (location.pathname.split('/')[1] || '') + '/actions/workflows/daily.yml' : null;
  h += '<div class="panel"><h2 style="margin-top:0">System status</h2><div class="wrap"><table><tbody>'
    + row2('Data mode', DEMO ? '<span class="neg">SYNTHETIC DEMO</span>' : 'Real market data', DEMO ? 'Never mixed with real data; never used for alerts or email.' : 'Delayed, end-of-day, unofficial. Never shown as "live".')
    + row2('Market data date', fd(D.price_date), esc(ds.t)) + row2('This report generated', ft(D.generated_at), ageDays(D.generated_at) >= 1 ? 'This is not today\'s analysis.' : '')
    + row2('Last successful analysis', st.last_success ? ft(st.last_success.finished_at) : 'n/a', st.last_success ? 'for run date ' + fd(st.last_success.run_date) : '')
    + row2('Latest attempt', esc(st.outcome || 'n/a'), st.error ? esc(st.error) : esc((st.notes || []).slice(0, 1).join(' ')))
    + row2('Next scheduled analysis', ft(st.next_run), '17:00 IST on the next trading day (NSE holiday list in data/nse_holidays.csv; 2026 file lists 13 confirmed holidays).')
    + row2('Market now', esc(ms.t), 'from the holiday file; verify on nseindia.com') + row2('Data provider', esc(D.provider), '') + row2('Failed data requests', st.failed_requests == null ? 'n/a' : st.failed_requests, 'requests that failed after retries')
    + row2('Email notifications', esc((st.email || {}).status || 'n/a'), esc((st.email || {}).note || '')) + '</tbody></table></div>'
    + '<p>' + (gh ? '<a href="' + esc(gh) + '" rel="noopener noreferrer">Open GitHub Actions to refresh now</a> (choose Run workflow).' : 'Manual refresh: open your repository on GitHub, Actions, "Update dashboard", Run workflow.') + '</p></div>';
  h += '<h2>Recent runs</h2>' + table('runs', [{ h: 'Run date', f: function (r) { return fd(r.date); }, v: function (r) { return r.date; } }, { h: 'Result', f: function (r) { return '<span class="tag ' + (r.status === 'OK' ? 'pos' : 'neg') + '">' + esc(r.status) + '</span>'; }, v: function (r) { return r.status; } }, { h: 'Note', w: 1, f: function (r) { return esc(r.notes || ''); } }], st.runs || [], { search: false, size: 10, empty: 'No run history yet.' });
  h += '<h2>Pipeline notes</h2><ul>' + (D.notes || []).map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>';
  return h;
};

/* ---------- router, events, init ---------- */

/* ---------- cloud sync: PUBLIC mode (plain file, no passphrase) or PRIVATE mode (encrypted in this browser) ---------- */
var SYNC_KEYS = ['tx', 'manualPrices', 'safety', 'amount', 'review', 'baseline', 'journal', 'plans', 'pfHistory'];
function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} }
var TOKEN = lsGet('mis_cloud_token'), CP = lsGet('mis_cloud_pass');          // the passphrase (private mode) stays in memory unless "remember" was ticked
var DRAFT = { pass: '', pass2: '', token: '', remember: false }, CMSG = null, CREMOTE = null, ctimer = null;
function isPublic() { return S.cloud.mode !== 'private'; }
function syncKeys() { return isPublic() ? SYNC_KEYS.filter(function (k) { return k !== 'safety'; }) : SYNC_KEYS; }   // public mode never publishes the debt / emergency-fund answers
function pickSync() { var o = {}; syncKeys().forEach(function (k) { o[k] = S[k]; }); return JSON.parse(JSON.stringify(o)); }
function syncSig() { return JSON.stringify(pickSync()); }
function guessOwner() { return /\.github\.io$/.test(location.hostname) ? location.hostname.split('.')[0] : ''; }
function guessRepo() { return /\.github\.io$/.test(location.hostname) ? (location.pathname.split('/')[1] || '') : ''; }
function fileName() { return isPublic() ? 'holdings.json' : 'holdings.enc.json'; }
function cloudCfg() {
  var c = S.cloud, cfg = { owner: c.owner || guessOwner(), repo: c.repo || guessRepo(), branch: c.branch || 'main', token: TOKEN, path: 'docs/' + fileName() };
  if (!cfg.owner || !cfg.repo) throw new Error('Enter your GitHub user name and repository name first.');
  return cfg;
}
function friendly(e) { return e && e.message === 'Failed to fetch' ? 'Could not reach GitHub or the site. Check your connection, and open this page from your https GitHub address.' : (e && e.message) || String(e); }
function fetchRemote() { return TOKEN ? CLOUD.ghGet(cloudCfg()) : CLOUD.readPublic(location.href, null, fileName()); }
async function decodeRemote(blob) {
  if (isPublic()) { if (!blob || typeof blob.rev !== 'number' || !blob.data) throw new Error('The cloud file is not a valid holdings file.'); return blob; }
  return CLOUD.decryptJSON(blob, CP);
}
async function encodeRemote(payload) { return isPublic() ? payload : CLOUD.encryptJSON(payload, CP); }
function ready() { return isPublic() || !!CP; }
function noteChange() {
  if (!S.cloud.enabled) return;
  if (syncSig() !== S.cloud.sig) { if (!S.cloud.dirty) { S.cloud.dirty = true; persist(); } scheduleCloud(); }
}
function refreshChips() { var el = document.getElementById('chips'); if (el) el.innerHTML = chips(); }
function scheduleCloud() {
  if (!S.cloud.auto || !ready() || !TOKEN) return;
  clearTimeout(ctimer);
  ctimer = setTimeout(function () {
    pushCloud(false).then(function () { CMSG = { kind: 'ok', text: 'Saved to the cloud automatically.' }; })
      .catch(function (e) { CMSG = { kind: 'err', text: friendly(e), conflict: !!e.conflict }; })
      .then(function () { refreshChips(); if (route().name === 'sync') render(); });
  }, 4000);
}
async function pushCloud(force) {
  if (!ready()) throw new Error('Unlock with your passphrase first.');
  if (!TOKEN) throw new Error('Saving needs a GitHub token. Without one this device can only read.');
  var cfg = cloudCfg(), remote = await CLOUD.ghGet(cfg), rp = null;
  if (remote) {
    try { rp = await decodeRemote(remote.blob); } catch (e) { throw new Error(isPublic() ? e.message : 'The cloud copy uses a different passphrase. Nothing was overwritten.'); }
    if (rp.rev > S.cloud.rev && !force) { var err = new Error('The cloud copy is newer (revision ' + rp.rev + ') than this device (revision ' + S.cloud.rev + '). Load it first, or choose Overwrite.'); err.conflict = true; throw err; }
  }
  var payload = { rev: Math.max(S.cloud.rev, rp ? rp.rev : 0) + 1, savedAt: new Date().toISOString(), device: S.cloud.device, data: pickSync() };
  var sha = await CLOUD.ghPut(cfg, await encodeRemote(payload), remote ? remote.sha : null);
  S.cloud.rev = payload.rev; S.cloud.sha = sha; S.cloud.lastSync = payload.savedAt; S.cloud.sig = syncSig(); S.cloud.dirty = false; S.cloud.enabled = true; persist();
}
async function applyRemote(remote) {
  var p = await decodeRemote(remote.blob);
  applyingRemote = true;
  try { syncKeys().forEach(function (k) { if (p.data && p.data[k] !== undefined) S[k] = p.data[k]; }); S.cloud.rev = p.rev; S.cloud.lastSync = p.savedAt; S.cloud.sig = syncSig(); S.cloud.dirty = false; S.cloud.enabled = true; save(); }
  finally { applyingRemote = false; }
  return p;
}
async function checkRemote() {
  CREMOTE = { checking: true };
  try { var r = await fetchRemote(); CREMOTE = r ? { exists: true } : { exists: false }; }
  catch (e) { CREMOTE = { exists: null, error: friendly(e) }; }
  if (route().name === 'sync') render();
}
async function cloudAction(fn) {
  CMSG = { kind: 'info', text: 'Working...' }; render();
  try { CMSG = await fn(); } catch (e) { CMSG = { kind: 'err', text: friendly(e), conflict: !!e.conflict }; }
  refreshChips(); render();
}
function actUnlock() {                       // private mode only
  return cloudAction(async function () {
    var pass = DRAFT.pass || '', remote = await fetchRemote();
    if (remote) {
      var p = await CLOUD.decryptJSON(remote.blob, pass);
      CP = pass; if (DRAFT.remember) lsSet('mis_cloud_pass', pass); CREMOTE = { exists: true, rev: p.rev };
      return { kind: 'ok', text: 'Passphrase accepted. The cloud copy is revision ' + p.rev + ' (saved ' + ft(p.savedAt) + '). Press "Load from cloud" to use it on this device.' };
    }
    var prob = CLOUD.passphraseProblem(pass); if (prob) throw new Error(prob);
    if (pass !== DRAFT.pass2) throw new Error('The two passphrases do not match.');
    CP = pass; if (DRAFT.remember) lsSet('mis_cloud_pass', pass); CREMOTE = { exists: false };
    return { kind: 'ok', text: 'Passphrase set. Add your token below, then press "Save to cloud now" to create the encrypted copy.' };
  });
}
function actSaveToken() {
  var t = (DRAFT.token || '').trim();
  if (!t) { CMSG = { kind: 'err', text: 'Paste your token first.' }; render(); return; }
  TOKEN = t; lsSet('mis_cloud_token', t); DRAFT.token = ''; CMSG = { kind: 'ok', text: 'Token saved on this device only.' }; render();
}
function actLoad() {
  if (S.tx.length && !confirm('This replaces the holdings, decisions and plans on THIS device with the cloud copy. Continue?')) return;
  return cloudAction(async function () {
    if (!ready()) throw new Error('Unlock with your passphrase first.');
    var remote = await fetchRemote(); if (!remote) throw new Error('There is no cloud copy yet.');
    var p = await applyRemote(remote); CREMOTE = { exists: true, rev: p.rev };
    return { kind: 'ok', text: 'Loaded revision ' + p.rev + ' from the cloud.' };
  });
}
function actSave(force) { return cloudAction(async function () { await pushCloud(force); CREMOTE = { exists: true }; return { kind: 'ok', text: 'Saved to the cloud (revision ' + S.cloud.rev + ').' }; }); }
function actDisconnect() {
  if (!confirm('Forget the token and passphrase on this device? Your cloud copy is not deleted.')) return;
  TOKEN = null; CP = null; lsSet('mis_cloud_token', null); lsSet('mis_cloud_pass', null); S.cloud.enabled = false; S.cloud.dirty = false; persist();
  CMSG = { kind: 'ok', text: 'This device is disconnected.' }; refreshChips(); render();
}
function cloudChip() {
  var c = S.cloud; if (!c.enabled) return '';
  if (!ready()) return '<span class="chip amb">Cloud: locked</span>';
  if (!TOKEN) return '<span class="chip">Cloud: read-only here</span>';
  if (CMSG && CMSG.kind === 'err') return '<span class="chip neg">Cloud: ' + (CMSG.conflict ? 'conflict' : 'error') + '</span>';
  if (c.dirty) return '<span class="chip amb">Cloud: unsaved changes</span>';
  return '<span class="chip pos">Cloud: saved ' + ft(c.lastSync) + '</span>';
}
async function autoPull() {
  try {
    if (!S.cloud.enabled && !(isPublic())) return;
    if (!ready()) return;
    var remote = await fetchRemote(); if (!remote) return;
    var p = await decodeRemote(remote.blob);
    if (!S.cloud.enabled) {                                   // public mode, a device that has never synced
      if (!S.tx.length) { await applyRemote(remote); CMSG = { kind: 'ok', text: 'Loaded your holdings from your site (revision ' + p.rev + ').' }; }
      else CMSG = { kind: 'info', text: 'Your site has saved holdings (revision ' + p.rev + '), but this device already has its own. Open Cloud sync to load them or to save this device\'s data.' };
    } else if (p.rev > S.cloud.rev) {
      if (S.cloud.dirty) CMSG = { kind: 'err', conflict: true, text: 'The cloud copy is newer than the unsaved changes on this device. Open Cloud sync to load it or overwrite it.' };
      else { await applyRemote(remote); CMSG = { kind: 'ok', text: 'Loaded newer data from the cloud (revision ' + p.rev + ').' }; }
    }
  } catch (e) { CMSG = { kind: 'err', text: friendly(e) }; }
  refreshChips(); render();
}
VIEWS.sync = function () {
  var c = S.cloud, h = banners(), pub = isPublic(), exists = CREMOTE && CREMOTE.exists, unlocked = ready();
  if (CREMOTE === null && (pub || !CP)) { CREMOTE = { checking: true }; checkRemote(); }
  var msg = CMSG ? '<div class="banner ' + (CMSG.kind === 'err' ? 'neg' : '') + '" role="' + (CMSG.kind === 'err' ? 'alert' : 'status') + '">' + esc(CMSG.text) + '</div>' : '';
  h += '<div class="panel"><h2 style="margin-top:0">Cloud sync: holdings on every device</h2>'
    + '<p>Keep your holdings, decisions and plans in your GitHub repository so every device shows the same data.</p>'
    + '<div class="row"><label><input type="radio" name="cmode" data-bind="cloudmode" value="public"' + (pub ? ' checked' : '') + '> <b>Public, no passphrase</b></label><label><input type="radio" name="cmode" data-bind="cloudmode" value="private"' + (pub ? '' : ' checked') + '> <b>Private, encrypted with a passphrase</b></label></div>'
    + (pub ? '<ul><li><b>Anyone with your link can read your holdings, transactions, plans and decision notes</b> (and old versions stay in git history for ever).</li>'
        + '<li>Your debt and emergency-fund answers are <b>not</b> saved to the cloud: they stay on each device.</li>'
        + '<li>Opening your site on any device shows your holdings automatically. A token is needed only on a device where you want to <i>save</i> changes.</li></ul>'
      : '<ul><li>Saved <b>encrypted in this browser</b> first (AES-256, key from your passphrase). The repository is public, so anyone can download the scrambled file and guess passphrases offline: <b>use 4 or more random words.</b></li>'
        + '<li>Anyone can see <i>when</i> it changes. A forgotten passphrase cannot be recovered.</li></ul>')
    + '<p class="mute">Saving from a web page needs a GitHub token (one-time per device): GitHub does not allow websites to write to a repository without one. The token can change your repository: make a <b>fine-grained</b> token for this one repository, <b>Contents: Read and write</b>, with an expiry date.</p></div>' + msg;
  h += '<div class="grid g2"><div class="panel"><h3>1. Repository</h3><div class="row"><label class="field">GitHub user name<input data-cfg="owner" value="' + esc(c.owner || guessOwner()) + '" autocomplete="off"></label>'
    + '<label class="field">Repository name<input data-cfg="repo" value="' + esc(c.repo || guessRepo()) + '" autocomplete="off"></label><label class="field">Branch<input data-cfg="branch" value="' + esc(c.branch) + '" style="width:90px"></label></div>'
    + '<p class="mute">' + (CREMOTE && CREMOTE.checking ? 'Checking for a cloud copy...' : CREMOTE && CREMOTE.error ? esc(CREMOTE.error) : exists ? 'A cloud copy exists on your site.' : exists === false ? 'No cloud copy yet.' : '') + '</p>'
    + (pub ? '' : '<h3>2. Passphrase</h3><label class="field">' + (exists ? 'Your passphrase' : 'Choose a passphrase') + '<input type="password" id="dp-pass" data-draft="pass" autocomplete="new-password" value="' + esc(DRAFT.pass) + '"></label>'
      + (exists ? '' : '<label class="field">Repeat it<input type="password" id="dp-pass2" data-draft="pass2" autocomplete="new-password" value="' + esc(DRAFT.pass2) + '"></label>')
      + '<p><label><input type="checkbox" data-draft="remember"' + (DRAFT.remember ? ' checked' : '') + '> Remember the passphrase on this device (less safe)</label></p>'
      + '<p><button data-act="cloud-unlock">' + (exists ? 'Unlock' : 'Set passphrase') + '</button> ' + (unlocked ? '<span class="pos">unlocked on this device</span>' : '<span class="mute">locked</span>') + '</p>')
    + '</div><div class="panel"><h3>' + (pub ? '2' : '3') + '. Token (needed to save; not needed to read)</h3><p class="mute">GitHub &gt; Settings &gt; Developer settings &gt; Personal access tokens &gt; Fine-grained tokens &gt; Generate. Repository access: only this repository. Permissions: Contents = Read and write.</p>'
    + '<label class="field">' + (TOKEN ? 'A token is saved on this device. Paste a new one to replace it' : 'Paste token') + '<input type="password" id="dp-token" data-draft="token" autocomplete="off" value="' + esc(DRAFT.token) + '"></label>'
    + '<p><button class="ghost" data-act="cloud-token">Save token on this device</button></p>'
    + '<h3>' + (pub ? '3' : '4') + '. Sync</h3><div class="row"><button data-act="cloud-load"' + (unlocked && exists ? '' : ' disabled') + '>Load from cloud</button><button data-act="cloud-save"' + (unlocked && TOKEN ? '' : ' disabled') + '>Save to cloud now</button>'
    + (CMSG && CMSG.conflict ? '<button class="danger" data-act="cloud-overwrite">Overwrite the cloud copy with this device</button>' : '') + '</div>'
    + '<p><label><input type="checkbox" data-bind="cloudauto"' + (c.auto ? ' checked' : '') + '> Save automatically a few seconds after every change</label></p>'
    + '<p class="mute">This device: revision ' + c.rev + (c.lastSync ? ', last synced ' + ft(c.lastSync) : ', never synced') + (c.dirty ? ' <b class="amb">(unsaved changes)</b>' : '') + '</p>'
    + '<p><button class="danger sm" data-act="cloud-disconnect">Disconnect this device</button></p></div></div>';
  return h;
};

var NAV = [['overview', 'Overview'], ['actions', 'Action centre'], ['planner', 'Monthly planner'], ['portfolio', 'Portfolio'], ['research', 'Research'], ['markets', 'Markets'], ['journal', 'Decision journal'], ['sync', 'Cloud sync'], ['health', 'System health']];
function route() { var p = location.hash.replace(/^#\/?/, '').split('/'); var n = decodeURIComponent(p[0] || 'overview'); if (n === 'stock') return { name: 'stock', arg: decodeURIComponent(p[1] || '') }; return { name: VIEWS[n] ? n : 'overview' }; }
function chips() {
  var ds = dataState(), ms = marketNow(), st = statusLive || D.status || {}, em = (st.email || {}).status || 'n/a';
  return cloudChip() + '<span class="chip ' + ds.k + '">' + esc(ds.t) + '</span><span class="chip ' + (ms.s === 'open' ? '' : '') + '">' + esc(ms.t) + '</span><span class="chip">Last analysis ' + ft(D.generated_at) + '</span><span class="chip">Next ' + ft(st.next_run) + '</span>'
    + '<span class="chip ' + ((st.failed_requests || 0) > 5 ? 'amb' : '') + '">Failed requests: ' + (st.failed_requests == null ? 'n/a' : st.failed_requests) + '</span><span class="chip ' + (/FAIL/.test(em) ? 'neg' : '') + '">Email: ' + esc(em) + '</span>';
}
function render() {
  refreshFreshness();
  var a = document.activeElement, id = a && a.id, ss = a && a.selectionStart, se = a && a.selectionEnd, r = route(), html;
  try { html = r.name === 'stock' ? VIEWS.stock(r.arg) : VIEWS[r.name](); } catch (e) { html = '<div class="banner neg" role="alert">Something went wrong building this page (' + esc(e.message) + '). Your saved entries are untouched. Try another page or restore from a backup.</div>'; if (window.console) console.error(e); }
  document.getElementById('view').innerHTML = html;
  document.getElementById('nav').innerHTML = NAV.map(function (n) { return '<a href="#/' + n[0] + '"' + ((r.name === n[0] || (r.name === 'stock' && n[0] === 'research')) ? ' aria-current="page"' : '') + '>' + n[1] + '</a>'; }).join('');
  document.getElementById('pagetitle').textContent = r.name === 'stock' ? ((byT[r.arg] || {}).name || 'Stock') : (NAV.filter(function (n) { return n[0] === r.name; })[0] || NAV[0])[1];
  document.getElementById('chips').innerHTML = chips();
  if (id) { var el = document.getElementById(id); if (el) { el.focus(); try { if (ss != null) el.setSelectionRange(ss, se); } catch (e) {} } }
}
var timer = null; function later() { clearTimeout(timer); timer = setTimeout(render, 250); }
function bindEl(el) {
  var k = el.getAttribute('data-bind'), v = el.type === 'checkbox' ? el.checked : el.value, t;
  if (k === 'cloudauto') { S.cloud.auto = v; persist(); if (v) scheduleCloud(); return true; }
  if (k === 'cloudmode') { S.cloud.mode = v; S.cloud.enabled = false; S.cloud.rev = 0; S.cloud.sig = ''; S.cloud.dirty = false; S.cloud.sha = null; CREMOTE = null; CMSG = null; persist(); return true; }
  if (k === 'amount') S.amount = v; else if (k.indexOf('safety.') === 0) S.safety[k.slice(7)] = v; else if (k === 'method') S.method = v; else if (k === 'staged') S.staged = v;
  else if (k.indexOf('sel:') === 0) { t = k.slice(4); var i = S.selected.indexOf(t); if (v && i < 0) { if (S.selected.length >= 10) { alert('You can consider at most 10 stocks.'); render(); return; } S.selected.push(t); } else if (!v && i >= 0) S.selected.splice(i, 1); S.overrides = {}; }
  else if (k.indexOf('ov:') === 0) { t = k.slice(3); var n = parseFloat(v); if (isNaN(n)) delete S.overrides[t]; else S.overrides[t] = n; }
  else if (k.indexOf('mp:') === 0) { t = k.slice(3); var p = parseFloat(v); if (p > 0) S.manualPrices[t] = p; else delete S.manualPrices[t]; }
  save(); return true;
}
document.addEventListener('input', function (e) { var el = e.target;
  if (el.getAttribute && el.getAttribute('data-draft')) { DRAFT[el.getAttribute('data-draft')] = el.type === 'checkbox' ? el.checked : el.value; return; }
  if (el.getAttribute && el.getAttribute('data-cfg')) { S.cloud[el.getAttribute('data-cfg')] = el.value.trim(); persist(); return; }
  if (el.getAttribute && el.getAttribute('data-tq')) { var id = el.getAttribute('data-tq'); TBL[id].q = el.value; TBL[id].page = 0; document.getElementById('tbb-' + id).innerHTML = tbody(id); return; }
  if (el.getAttribute && el.getAttribute('data-bind') && el.type !== 'radio' && el.type !== 'checkbox') { if (bindEl(el)) later(); } });
document.addEventListener('change', function (e) { var el = e.target;
  if (el.getAttribute && el.getAttribute('data-draft') && el.type === 'checkbox') { DRAFT[el.getAttribute('data-draft')] = el.checked; return; }
  if (el.getAttribute && el.getAttribute('data-bind') && (el.type === 'radio' || el.type === 'checkbox')) { if (bindEl(el)) render(); }
  else if (el.id === 'csvfile' && el.files[0]) { var r = new FileReader(); r.onload = function () { csvDraft = r.result; importPreview = LEDGER.parseCSV(r.result); render(); }; r.readAsText(el.files[0]); }
  else if (el.id === 'restorefile' && el.files[0]) { var r2 = new FileReader(); r2.onload = function () { try { var o = JSON.parse(r2.result); if (!Array.isArray(o.tx)) throw 0; var keepCloud = S.cloud; S = Object.assign(S, o); S.cloud = keepCloud; save(); render(); } catch (x) { alert('That file is not a valid backup.'); } }; r2.readAsText(el.files[0]); } });
document.addEventListener('keydown', function (e) { if ((e.key === 'Enter' || e.key === ' ') && e.target.getAttribute && e.target.getAttribute('data-sort')) { e.preventDefault(); e.target.click(); } });
document.addEventListener('submit', function (e) {
  if (e.target.id !== 'txform') return; e.preventDefault();
  var g = function (i) { return document.getElementById(i).value; }, line = 'date,type,ticker,quantity,price,fees\n' + [g('tx-d'), g('tx-type'), g('tx-t'), g('tx-q'), g('tx-p'), g('tx-f') || 0].join(','), pr = LEDGER.parseCSV(line);
  if (pr.errors.length) return alert(pr.errors.join('\n'));
  var t = Object.assign({ id: uid() }, pr.rows[0]); S.tx.push(t);
  var L = LEDGER.buildLedger(S.tx); if (L.errors.length) { S.tx.pop(); return alert('Not saved: ' + L.errors[L.errors.length - 1]); }
  save(); render();
});
var ACT = {
  'cloud-unlock': function () { actUnlock(); return 'none'; }, 'cloud-token': function () { actSaveToken(); return 'none'; }, 'cloud-load': function () { actLoad(); return 'none'; },
  'cloud-save': function () { actSave(false); return 'none'; }, 'cloud-overwrite': function () { if (confirm('Replace the cloud copy with the data on THIS device? The other device\'s newer changes will be lost.')) actSave(true); return 'none'; },
  'cloud-disconnect': function () { actDisconnect(); return 'none'; },
  filter: function (el) { S.filter = el.dataset.k; }, rtab: function (el) { S.rtab = el.dataset.k; },
  'approve-stock': function (el) { S.review[el.dataset.t] = 'approved'; }, 'ignore-stock': function (el) { S.review[el.dataset.t] = 'ignored'; },
  addsel: function (el) { var t = el.dataset.t; if (S.selected.indexOf(t) < 0 && S.selected.length < 10) S.selected.push(t); S.overrides = {}; save(); location.hash = '#/planner'; return 'nav'; },
  autopick: function () { S.selected = []; S.overrides = {}; },
  'plan-save': function () { var c = ctx(); S.plans.unshift({ id: uid(), date: new Date().toISOString().slice(0, 10), amount: c.amt, status: 'saved', rows: c.plan.rows.map(function (r) { return { ticker: r.ticker, name: r.name, shares: r.shares, limit: r.limit }; }) }); },
  'plan-approve': function () { var c = ctx(); if (!c.plan.approvable) return alert('This plan cannot be approved: ' + (DEMO ? 'demo data.' : 'check the safety questions and entry ranges.'));
    S.plans.unshift({ id: uid(), date: new Date().toISOString().slice(0, 10), amount: c.amt, status: 'approved', rows: c.plan.rows.map(function (r) { return { ticker: r.ticker, name: r.name, shares: r.shares, limit: r.limit }; }) });
    c.plan.rows.forEach(function (r) { logDecision({ key: 'plan:' + r.ticker + ':' + Date.now(), ticker: r.ticker, name: r.name, proposed: 'BUY candidate via monthly plan', qty: r.shares, limit: r.limit, why: [r.reason] }, 'approved'); }); },
  'plan-dismiss': function () { var c = ctx(); c.plan.rows.forEach(function (r) { logDecision({ key: 'plan:' + r.ticker + ':' + Date.now(), ticker: r.ticker, name: r.name, proposed: 'BUY candidate via monthly plan', qty: r.shares, limit: r.limit, why: [r.reason] }, 'rejected'); }); S.plans.unshift({ id: uid(), date: new Date().toISOString().slice(0, 10), amount: c.amt, status: 'dismissed', rows: [] }); },
  'plan-del': function (el) { S.plans = S.plans.filter(function (p) { return p.id !== el.dataset.id; }); },
  decide: function (el) { var c = ctx(), i = allItems(c).filter(function (x) { return x.id === el.dataset.id; })[0]; if (i) logDecision({ key: 'item:' + i.id, ticker: i.ticker, name: i.name, proposed: i.title, why: [i.reason], qty: i.qty }, el.dataset.d); },
  jr: function (el) { S.journal.forEach(function (j) { if (j.id === el.dataset.id && j.decision === 'deferred') { j.decision = el.dataset.d; j.decidedAt = new Date().toISOString(); } }); },
  'jr-note': function (el) { var n = prompt('Add a note (it is appended and dated):'); if (n) S.journal.forEach(function (j) { if (j.id === el.dataset.id) j.note = (j.note ? j.note + ' | ' : '') + new Date().toISOString().slice(0, 10) + ': ' + n; }); },
  'csv-check': function () { csvDraft = document.getElementById('csvtext').value; importPreview = LEDGER.parseCSV(csvDraft); },
  'csv-import': function () { if (!importPreview) return; var add = importPreview.rows.map(function (r) { return Object.assign({ id: uid() }, r); }), prev = S.tx.slice(); S.tx = S.tx.concat(add);
    var L = LEDGER.buildLedger(S.tx); if (L.errors.length) { S.tx = prev; return alert('Nothing imported: ' + L.errors[0]); } importPreview = null; csvDraft = ''; },
  'tx-del': function (el) { if (confirm('Delete this transaction?')) S.tx = S.tx.filter(function (t) { return t.id !== el.dataset.id; }); },
  export: function () { var b = new Blob([JSON.stringify(S, null, 1)], { type: 'application/json' }), a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = 'mis-backup.json'; a.click(); return 'none'; },
  restore: function () { document.getElementById('restorefile').click(); return 'none'; },
  wipe: function () { if (confirm('Erase all transactions, decisions and plans on this device? Download a backup first.')) { try { localStorage.removeItem(KEY); localStorage.removeItem('mis_cloud_token'); localStorage.removeItem('mis_cloud_pass'); } catch (e) {} location.reload(); return 'none'; } return 'none'; }
};
document.addEventListener('click', function (e) {
  var el = e.target.closest ? e.target.closest('[data-act],[data-sort],[data-pg]') : null; if (!el) return;
  if (el.hasAttribute('data-sort')) { var p = el.getAttribute('data-sort').split(':'), t = TBL[p[0]], i = +p[1]; if (t.sort === i) t.dir = -t.dir; else { t.sort = i; t.dir = 1; } document.getElementById('tbb-' + p[0]).innerHTML = tbody(p[0]); return; }
  if (el.hasAttribute('data-pg')) { var q = el.getAttribute('data-pg').split(':'); TBL[q[0]].page += +q[1]; document.getElementById('tbb-' + q[0]).innerHTML = tbody(q[0]); return; }
  var fn = ACT[el.getAttribute('data-act')]; if (!fn) return; var r = fn(el); if (r === 'nav' || r === 'none') return; save(); render();
});
document.getElementById('themebtn').addEventListener('click', function () {
  var cur = document.documentElement.getAttribute('data-theme') || (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'), nx = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', nx); try { localStorage.setItem('mis_theme', nx); } catch (e) {} });
window.addEventListener('hashchange', function () { render(); window.scrollTo(0, 0); var v = document.getElementById('view'); if (v) v.focus({ preventScroll: true }); });
(function init() {
  if (!DEMO && D.price_date) { var c = ctx(); if (c.port.total > 0 && !c.port.missingPrices.length) { S.pfHistory[D.price_date] = Math.round(c.port.total); save(); } }
  render();
  autoPull();
  setInterval(function () { var before = D.stocks.length && D.stocks[0].stale; refreshFreshness(); if ((D.stocks.length && D.stocks[0].stale) !== before) render(); }, 600000);   // a tab left open past the stale limit updates itself
  if (/^https?:/.test(location.protocol)) fetch('status.json?t=' + Date.now(), { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) { if (j && !DEMO) { statusLive = j; render(); } }).catch(function () {});
})();
})();
