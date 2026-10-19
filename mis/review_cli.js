// Optional PRIVATE review used only inside the scheduled job to write the portfolio section of the email.
// Input: argv[2] = path to snapshot JSON; then EITHER stdin = your exported state JSON (secret MIS_HOLDINGS_JSON)
//        OR  --enc <file> = the encrypted holdings file from Cloud sync, decrypted with the secret MIS_PASSPHRASE.
// Output: JSON on stdout. Nothing is written to disk and nothing reaches the public dashboard.
const fs = require('fs');
const L = require('./ledger.js'), M = require('./dashboard_logic.js');
const snap = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const encIdx = process.argv.indexOf('--enc');
async function loadState() {
  if (encIdx > 0) {
    const K = require('./cloud.js');
    try { return (await K.decryptJSON(JSON.parse(fs.readFileSync(process.argv[encIdx + 1], 'utf8')), process.env.MIS_PASSPHRASE || '')).data; }
    catch (e) { console.log(JSON.stringify({ error: 'encrypted holdings could not be read: ' + e.message })); process.exit(0); }
  }
  try { return JSON.parse(fs.readFileSync(0, 'utf8')); } catch (e) { console.log(JSON.stringify({ error: 'holdings JSON unreadable' })); process.exit(0); }
}
loadState().then(main);
function main(state) {
const byT = {}; snap.stocks.forEach(s => { byT[s.ticker] = s; });
const txs = (state.tx || []).map(t => ({ ...t, ticker: L.normTicker(t.ticker) }));
const ledger = L.buildLedger(txs);
const pos = L.positions(ledger).map(p => ({ ...p, manualPrice: (state.manualPrices || {})[p.ticker] }));
const port = M.portfolio(pos, byT);
const actions = M.holdingActions(port, byT, snap.rules, new Date());
const breaches = M.concentrationBreaches(port, snap.rules);
console.log(JSON.stringify({ value: port.total, invested: port.invested, pnl: port.pnl, dayChange: port.dayChange, missing: port.missingPrices,
  actions: actions.filter(a => a.action !== 'HOLD').map(a => ({ ticker: a.ticker, name: a.name, action: a.action, qty: a.qty, priceNote: a.priceNote, reasons: a.reasons, confidence: a.confidence })),
  breaches, count: port.rows.length }));
}
