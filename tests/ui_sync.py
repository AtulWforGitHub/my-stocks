"""Cloud-sync browser test with TWO devices and a stand-in for GitHub's API (the real GitHub is not contacted).
Run: python -m mis.run --demo --force && python tests/ui_sync.py"""
import base64, json, pathlib, sys
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ghmock import Mock
HTML = (pathlib.Path(__file__).resolve().parent.parent / "demo_output" / "index.html").read_text()
SITE = "https://user.github.io/repo/"
M = Mock(HTML, SITE)
fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

def install(ctx): M.install(ctx)

def banner(pg): return pg.locator(".banner").first.inner_text() if pg.locator(".banner").count() else ""
def wait_banner(pg, text, t=15000):
    try: pg.wait_for_function("t => Array.from(document.querySelectorAll('.banner')).some(b => b.innerText.includes(t))", arg=text, timeout=t); return True
    except Exception: return False
def add_tx(pg, ticker, qty, price):
    pg.goto(SITE + "#/portfolio"); pg.wait_for_timeout(200)
    pg.select_option("#tx-type", "buy"); pg.fill("#tx-t", ticker); pg.fill("#tx-q", str(qty)); pg.fill("#tx-p", str(price)); pg.fill("#tx-d", "2025-01-10")
    pg.click("#txform button[type=submit]"); pg.wait_for_timeout(200)

with sync_playwright() as p:
    b = p.chromium.launch()
    A = b.new_context(); install(A); a = A.new_page(); errs = []; a.on("pageerror", lambda e: errs.append(str(e))); a.on("dialog", lambda d: d.accept())
    a.goto(SITE + "#/sync"); a.wait_for_timeout(500); a.check("input[data-bind=cloudmode][value=private]"); a.wait_for_timeout(500)
    ticker = a.evaluate("localStorage.removeItem('x') || 'TCS'")
    check("device A: no cloud copy yet, no secrets stored", "No cloud copy yet" in a.inner_text("#view") and a.evaluate("localStorage.getItem('mis_cloud_token')") is None)
    a.fill("#dp-pass", "short"); a.fill("#dp-pass2", "short"); a.click("button[data-act=cloud-unlock]")
    check("weak passphrase is refused", wait_banner(a, "at least 14 characters"))
    a.fill("#dp-pass", "blue river seven lamp 42"); a.fill("#dp-pass2", "different words entirely"); a.click("button[data-act=cloud-unlock]")
    check("mismatched passphrases are refused", wait_banner(a, "do not match"))
    a.fill("#dp-pass", "blue river seven lamp 42"); a.fill("#dp-pass2", "blue river seven lamp 42"); a.click("button[data-act=cloud-unlock]")
    check("strong passphrase accepted", wait_banner(a, "Passphrase set"))
    add_tx(a, "SECRETCO", 111, 987.65)
    a.goto(SITE + "#/sync"); a.wait_for_timeout(300)
    a.fill("#dp-token", "tok"); a.click("button[data-act=cloud-token]"); a.wait_for_timeout(200)
    a.click("button[data-act=cloud-save]")
    check("first save creates revision 1", wait_banner(a, "revision 1") and M.puts == 1)
    stored = M.bodies[0][1]
    check("what GitHub received is scrambled: no ticker, quantity or price visible", all(x not in stored for x in ("SECRETCO", "987.65")) and all(x not in base64.b64decode(json.loads(stored)["ct"]) for x in (b"SECRETCO", b"987.65", b"ticker")))
    state_txt = a.evaluate("localStorage.getItem('mis_state_v2')")
    check("token and passphrase are not inside the exported state", "tok" not in json.dumps(json.loads(state_txt).get("cloud")) and "blue river" not in state_txt)
    check("token is kept in its own storage key; passphrase is not stored by default", a.evaluate("localStorage.getItem('mis_cloud_token')") == "tok" and a.evaluate("localStorage.getItem('mis_cloud_pass')") is None)
    check("top bar shows the cloud status", "Cloud: saved" in a.inner_text("#chips"))
    # auto-save
    add_tx(a, "SECOND", 5, 100); a.wait_for_timeout(6500)
    check("a later change is saved automatically (revision 2)", M.puts == 2)
    # device B
    B = b.new_context(); install(B); d = B.new_page(); d.on("pageerror", lambda e: errs.append(str(e))); d.on("dialog", lambda x: x.accept())
    d.goto(SITE + "#/sync"); d.wait_for_timeout(500); d.check("input[data-bind=cloudmode][value=private]"); d.wait_for_timeout(700)
    check("device B sees that an encrypted copy exists, with no token needed", "A cloud copy exists on your site" in d.inner_text("#view"))
    d.fill("#dp-pass", "not the right passphrase"); d.click("button[data-act=cloud-unlock]")
    check("wrong passphrase is rejected and nothing is loaded", wait_banner(d, "Wrong passphrase") and d.evaluate("JSON.parse(localStorage.getItem('mis_state_v2')).tx.length") == 0)
    d.fill("#dp-pass", "blue river seven lamp 42"); d.click("button[data-act=cloud-unlock]")
    check("correct passphrase is accepted on device B", wait_banner(d, "Passphrase accepted"))
    d.click("button[data-act=cloud-load]")
    check("device B loads revision 2", wait_banner(d, "Loaded revision 2") and d.evaluate("JSON.parse(localStorage.getItem('mis_state_v2')).tx.length") == 2)
    d.goto(SITE + "#/portfolio"); d.wait_for_timeout(300)
    check("device B shows the holdings entered on device A", "SECRETCO" in d.inner_text("#view"))
    # conflict: B saves (token), then A (stale) tries to save
    d.goto(SITE + "#/sync"); d.wait_for_timeout(300); d.fill("#dp-token", "tok"); d.click("button[data-act=cloud-token]"); d.wait_for_timeout(200)
    add_tx(d, "FROMB", 7, 70); d.wait_for_timeout(6500)
    check("device B's change is saved (revision 3)", M.puts == 3)
    add_tx(a, "FROMA", 9, 90); a.wait_for_timeout(6500)
    check("device A's stale save is refused as a conflict, nothing overwritten", M.puts == 3 and "Cloud: conflict" in a.inner_text("#chips"))
    a.goto(SITE + "#/sync"); a.wait_for_timeout(300)
    check("a conflict offers an explicit Overwrite choice", a.locator("button[data-act=cloud-overwrite]").count() == 1 and "newer" in a.inner_text("#view"))
    a.click("button[data-act=cloud-overwrite]")
    check("choosing Overwrite saves revision 4", wait_banner(a, "revision 4") and M.puts == 4)
    a.click("button[data-act=cloud-disconnect]"); a.wait_for_timeout(300)
    check("disconnect forgets the token and removes the status chip", a.evaluate("localStorage.getItem('mis_cloud_token')") is None and "Cloud:" not in a.inner_text("#chips"))
    check("no JavaScript errors", not errs)
    if errs: print(errs)
    b.close()
sys.exit(1 if fails else 0)
