const test = require('node:test'); const assert = require('node:assert');
const K = require('../mis/cloud.js');
const state = { tx: [{ id: '1', date: '2025-01-02', type: 'buy', ticker: 'SECRETCO.NS', qty: 123, price: 456.78, fees: 0 }], safety: { debt: 'no', emergency: 'ok' } };
const PASS = 'correct horse battery staple 42';

test('round trip with the real 600,000-round key setting', async () => {
  const blob = await K.encryptJSON({ rev: 1, data: state }, PASS);
  assert.equal(blob.iter, 600000); assert.deepEqual((await K.decryptJSON(blob, PASS)).data, state);
});
test('the stored blob contains no readable holdings', async () => {
  const blob = await K.encryptJSON({ rev: 1, data: state }, PASS, { iter: 100000 }), txt = JSON.stringify(blob);
  for (const secret of ['SECRETCO', '456.78']) assert.ok(!txt.includes(secret), 'leaked: ' + secret);
  const raw = Buffer.from(blob.ct, 'base64').toString('latin1');                                   // also not hidden behind mere base64
  for (const secret of ['SECRETCO', '456.78', 'ticker', 'buy']) assert.ok(!raw.includes(secret), 'decodes to readable text: ' + secret);
  assert.deepEqual(Object.keys(blob).sort(), ['ct', 'iter', 'iv', 'kdf', 'salt', 'v']);
});
test('wrong passphrase and tampering are both rejected', async () => {
  const blob = await K.encryptJSON({ rev: 1, data: state }, PASS, { iter: 100000 });
  await assert.rejects(K.decryptJSON(blob, PASS + 'x'), /Wrong passphrase/);
  const t = { ...blob, ct: blob.ct.slice(0, -4) + (blob.ct.slice(-4) === 'AAAA' ? 'BBBB' : 'AAAA') };
  await assert.rejects(K.decryptJSON(t, PASS), /Wrong passphrase|changed/);
  await assert.rejects(K.decryptJSON({ v: 2 }, PASS), /not a valid/);
});
test('every encryption uses a fresh salt and nonce', async () => {
  const a = await K.encryptJSON({ x: 1 }, PASS, { iter: 100000 }), b = await K.encryptJSON({ x: 1 }, PASS, { iter: 100000 });
  assert.notEqual(a.salt, b.salt); assert.notEqual(a.iv, b.iv); assert.notEqual(a.ct, b.ct);
});
test('a file claiming a weak key setting is refused', async () => {
  const blob = await K.encryptJSON({ x: 1 }, PASS, { iter: 100000 });
  await assert.rejects(K.decryptJSON({ ...blob, iter: 1000 }, PASS), /too weak/);
  await assert.rejects(K.decryptJSON({ ...blob, iter: undefined }, PASS), /too weak/);
});
test('passphrase rules', () => {
  for (const bad of ['', 'short', 'password123456789', 'aaaaaaaaaaaaaaaa', 'abcdefghijklmnop']) assert.ok(K.passphraseProblem(bad), bad);
  for (const good of ['correct horse battery staple', 'Tr0ub4dor&3-long-enough', 'blue-river-seven-lamp']) assert.equal(K.passphraseProblem(good), null, good);
});

// ---- GitHub contents API with a stand-in server ----
function server() {
  const st = { file: null, sha: 0, puts: [] };
  const f = async (u, o = {}) => {
    const method = o.method || 'GET', ok = (j, s = 200) => ({ ok: s < 300, status: s, json: async () => j });
    if (!/Bearer tok/.test((o.headers || {}).Authorization || '')) return ok({}, 401);
    if (/\/repos\/[^/]+\/[^/]+$/.test(u)) return ok(st.repoMissing ? {} : { full_name: 'u/r' }, st.repoMissing ? 404 : 200);
    if (method === 'GET') return st.file ? ok({ sha: 'sha' + st.sha, content: st.file }) : ok({ message: 'Not Found' }, 404);
    const b = JSON.parse(o.body);
    if (st.file && b.sha !== 'sha' + st.sha) return ok({}, 409);
    if (!st.file && b.sha) return ok({}, 422);
    st.file = b.content; st.sha++; st.puts.push(b); return ok({ content: { sha: 'sha' + st.sha } }, st.file ? 200 : 201);
  };
  return { st, f };
}
const cfg = { owner: 'u', repo: 'r', branch: 'main', token: 'tok' };
test('GitHub: create, read back, update, and a stale update is a conflict', async () => {
  const { st, f } = server();
  assert.equal(await K.ghGet(cfg, f), null);
  const blob = await K.encryptJSON({ rev: 1, data: state }, PASS, { iter: 100000 });
  const sha1 = await K.ghPut(cfg, blob, null, f); assert.equal(sha1, 'sha1');
  const got = await K.ghGet(cfg, f); assert.deepEqual(got.blob, blob); assert.deepEqual((await K.decryptJSON(got.blob, PASS)).data, state);
  const sha2 = await K.ghPut(cfg, await K.encryptJSON({ rev: 2, data: state }, PASS, { iter: 100000 }), got.sha, f); assert.equal(sha2, 'sha2');
  await assert.rejects(K.ghPut(cfg, blob, got.sha, f), (e) => e.conflict === true);                       // stale sha: another device saved in between
  assert.ok(!JSON.stringify(st.puts).includes('SECRETCO'));
});
test('GitHub: bad token and missing permission give plain messages', async () => {
  const { f } = server();
  await assert.rejects(K.ghGet({ ...cfg, token: 'bad' }, f), /rejected the token/);
  await assert.rejects(K.ghGet(cfg, async () => ({ ok: false, status: 403, json: async () => ({}) })), /Contents: Read and write/);
  await assert.rejects(K.ghPut(cfg, {}, null, async () => ({ ok: false, status: 404, json: async () => ({}) })), /not found/);
});
test('GitHub: a wrong repository name is an error, not "no cloud copy yet"', async () => {
  const { st, f } = server(); st.repoMissing = true;
  await assert.rejects(K.ghGet(cfg, f), /not found/);
  st.repoMissing = false; assert.equal(await K.ghGet(cfg, f), null);                                      // repo fine, file absent -> null
});
test('public read (no token) returns the blob or null', async () => {
  const blob = await K.encryptJSON({ rev: 1 }, PASS, { iter: 100000 });
  assert.deepEqual((await K.readPublic('https://u.github.io/r/', async () => ({ ok: true, status: 200, json: async () => blob }))).blob, blob);
  assert.equal(await K.readPublic('https://u.github.io/r/', async () => ({ ok: false, status: 404 })), null);
});

test('the daily job can read the encrypted holdings with the passphrase secret (and says so plainly when it cannot)', async () => {
  const fs = require('fs'), os = require('os'), path = require('path'), { spawnSync } = require('child_process');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mis-')), snap = path.join(dir, 'snap.json'), encf = path.join(dir, 'holdings.enc.json');
  const stock = { ticker: 'AAA.NS', name: 'AAA', sector: 'IT', cap: 'M', price: 100, fresh: true, status: 'HOLD', research: 70, confidence: { label: 'Medium', limits: [] }, gov: 'ok', atr: 2, chg1d: 1, zones: { ideal: [90, 110], thesis_review: 80, trading_stop: 90 } };
  fs.writeFileSync(snap, JSON.stringify({ rules: { minPositions: 10, maxSingle: 8, maxSector: 30, maxSmall: 50, concCapBuilding: 20 }, stocks: [stock] }));
  fs.writeFileSync(encf, JSON.stringify(await K.encryptJSON({ rev: 1, data: { tx: [{ date: '2025-01-02', type: 'buy', ticker: 'AAA', qty: 10, price: 50, fees: 0 }] } }, PASS)));
  const run = (pw) => spawnSync('node', ['mis/review_cli.js', snap, '--enc', encf], { env: { ...process.env, MIS_PASSPHRASE: pw }, encoding: 'utf8', cwd: require('path').resolve(__dirname, '..') });
  const ok = JSON.parse(run(PASS).stdout); assert.equal(ok.count, 1); assert.equal(ok.value, 1000); assert.equal(ok.invested, 500);
  const bad = JSON.parse(run('wrong passphrase here').stdout); assert.match(bad.error, /could not be read/); assert.ok(!('value' in bad));
});

test('public read can fetch a differently named (plain) file', async () => {
  let seen = null;
  const r = await K.readPublic('https://u.github.io/r/', async (u) => { seen = u; return { ok: true, status: 200, json: async () => ({ rev: 1, data: {} }) }; }, 'holdings.json');
  assert.match(seen, /^https:\/\/u\.github\.io\/r\/holdings\.json\?t=/); assert.equal(r.blob.rev, 1);
});
