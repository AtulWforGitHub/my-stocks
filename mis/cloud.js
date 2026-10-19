/* Encrypted cloud copy of your holdings.
   Encryption happens in YOUR browser (AES-256-GCM, key from your passphrase via PBKDF2-SHA256, 600,000 rounds).
   Only the scrambled blob is stored in the repository. The passphrase never leaves your device (unless you tick "remember"). */
(function (root) {
  'use strict';
  const AAD = 'mis-holdings-v1', DEFAULT_ITER = 600000, MIN_ITER = 100000;
  const enc = new TextEncoder(), dec = new TextDecoder();
  const C = () => { if (!root.crypto || !root.crypto.subtle) throw new Error('This browser/page cannot use encryption (it needs https or localhost).'); return root.crypto; };
  const b64e = (u8) => { let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s); };
  const b64d = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

  async function deriveKey(pass, salt, iter) {
    const base = await C().subtle.importKey('raw', enc.encode(pass), 'PBKDF2', false, ['deriveKey']);
    return C().subtle.deriveKey({ name: 'PBKDF2', salt, iterations: iter, hash: 'SHA-256' }, base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
  }
  async function encryptJSON(obj, pass, opts) {
    const iter = (opts && opts.iter) || DEFAULT_ITER, salt = C().getRandomValues(new Uint8Array(16)), iv = C().getRandomValues(new Uint8Array(12));
    const key = await deriveKey(pass, salt, iter);
    const ct = await C().subtle.encrypt({ name: 'AES-GCM', iv, additionalData: enc.encode(AAD) }, key, enc.encode(JSON.stringify(obj)));
    return { v: 1, kdf: 'PBKDF2-SHA256', iter, salt: b64e(salt), iv: b64e(iv), ct: b64e(new Uint8Array(ct)) };
  }
  async function decryptJSON(blob, pass) {
    if (!blob || blob.v !== 1 || !blob.salt || !blob.iv || !blob.ct) throw new Error('This is not a valid encrypted holdings file.');
    if (!(blob.iter >= MIN_ITER)) throw new Error('The encrypted file uses too weak a key setting and was refused.');
    try {
      const key = await deriveKey(pass, b64d(blob.salt), blob.iter);
      const pt = await C().subtle.decrypt({ name: 'AES-GCM', iv: b64d(blob.iv), additionalData: enc.encode(AAD) }, key, b64d(blob.ct));
      return JSON.parse(dec.decode(pt));
    } catch (e) { throw new Error('Wrong passphrase, or the data was changed.'); }
  }
  function passphraseProblem(p) {
    p = String(p || '');
    if (p.length < 14) return 'Use at least 14 characters (a phrase of 4 or more random words is best).';
    if (['password', '12345678', 'qwerty', 'iloveyou', 'letmein'].some((b) => p.toLowerCase().includes(b))) return 'That contains a very common password.';
    if (/^(.)\1+$/.test(p)) return 'Do not repeat one character.';
    const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(p)).length;
    const words = p.split(/[\s\-_.]+/).filter((w) => w.length >= 3).length;
    if (classes < 2 && words < 4) return 'Mix letters with numbers or symbols, or use 4 or more words.';
    return null;
  }

  // ---- GitHub contents API (the browser talks to GitHub directly; the token stays on this device) ----
  const url = (cfg) => `https://api.github.com/repos/${cfg.owner}/${cfg.repo}/contents/${cfg.path || 'docs/holdings.enc.json'}`;
  const headers = (cfg) => ({ Authorization: 'Bearer ' + cfg.token, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' });
  function httpError(r) {
    const e = new Error(r.status === 401 ? 'GitHub rejected the token (wrong, or expired).' :
      r.status === 403 ? 'The token lacks permission. It needs "Contents: Read and write" on this repository (or you hit a rate limit).' :
      r.status === 404 ? 'Repository or file not found. Check the owner and repository name.' : 'GitHub returned an error (' + r.status + ').');
    e.status = r.status; return e;
  }
  async function ghGet(cfg, f) {
    const r = await (f || root.fetch)(url(cfg) + '?ref=' + encodeURIComponent(cfg.branch || 'main') + '&t=' + Date.now(), { headers: headers(cfg), cache: 'no-store' });
    if (r.status === 404) {          // "not found" means two different things: no file yet, or a wrong repo/token. Tell them apart.
      const rr = await (f || root.fetch)(`https://api.github.com/repos/${cfg.owner}/${cfg.repo}`, { headers: headers(cfg), cache: 'no-store' });
      if (!rr.ok) throw httpError(rr);
      return null;
    }
    if (!r.ok) throw httpError(r);
    const j = await r.json();
    return { sha: j.sha, blob: JSON.parse(dec.decode(b64d(String(j.content).replace(/\s/g, '')))) };
  }
  async function ghPut(cfg, blob, sha, f) {
    const body = { message: 'Update encrypted holdings', content: b64e(enc.encode(JSON.stringify(blob))), branch: cfg.branch || 'main' };
    if (sha) body.sha = sha;
    const r = await (f || root.fetch)(url(cfg), { method: 'PUT', headers: { ...headers(cfg), 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (r.status === 409 || r.status === 422) { const e = new Error('The cloud copy changed on another device.'); e.conflict = true; throw e; }
    if (!r.ok) throw httpError(r);
    return (await r.json()).content.sha;
  }
  async function readPublic(base, f, name) {   // no token needed: the Pages site serves the same file
    const r = await (f || root.fetch)(new URL(name || 'holdings.enc.json', base).href + '?t=' + Date.now(), { cache: 'no-store' });
    if (r.status === 404) return null;
    if (!r.ok) throw new Error('Could not read the site copy (' + r.status + ').');
    return { sha: null, blob: await r.json() };
  }

  const api = { encryptJSON, decryptJSON, passphraseProblem, ghGet, ghPut, readPublic, b64e, b64d, DEFAULT_ITER };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.CLOUD = api;
})(typeof window !== 'undefined' ? window : globalThis);
