"""PUBLIC-mode cloud sync (no passphrase), two devices, stand-in GitHub. Run: python -m mis.run --demo --force && python tests/ui_sync_public.py"""
import json, pathlib, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ghmock import Mock

HTML = (pathlib.Path(__file__).resolve().parent.parent / "demo_output" / "index.html").read_text()
SITE = "https://user.github.io/repo/"; M = Mock(HTML, SITE); fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)
def wait_banner(pg, text, t=15000):
    try: pg.wait_for_function("t => Array.from(document.querySelectorAll('.banner')).some(b => b.innerText.includes(t))", arg=text, timeout=t); return True
    except Exception: return False
def add_tx(pg, ticker, qty, price):
    pg.goto(SITE + "#/portfolio"); pg.wait_for_timeout(250)
    pg.select_option("#tx-type", "buy"); pg.fill("#tx-t", ticker); pg.fill("#tx-q", str(qty)); pg.fill("#tx-p", str(price)); pg.fill("#tx-d", "2025-01-10")
    pg.click("#txform button[type=submit]"); pg.wait_for_timeout(250)
def state(pg): return json.loads(pg.evaluate("localStorage.getItem('mis_state_v2')"))

with sync_playwright() as p:
    b = p.chromium.launch(); errs = []
    A = b.new_context(); M.install(A); a = A.new_page(); a.on("pageerror", lambda e: errs.append(str(e))); a.on("dialog", lambda d: d.accept())
    a.goto(SITE + "#/sync"); a.wait_for_timeout(600)
    check("public mode is the default and needs no passphrase", "Anyone with your link can read" in a.inner_text("#view") and a.locator("#dp-pass").count() == 0)
    a.evaluate("()=>{var S=JSON.parse(localStorage.getItem('mis_state_v2')||'{}');S.safety={debt:'no',emergency:'ok'};localStorage.setItem('mis_state_v2',JSON.stringify(S))}")
    add_tx(a, "PUBLICCO", 111, 987.65)
    a.goto(SITE + "#/sync"); a.wait_for_timeout(300); a.fill("#dp-token", "tok"); a.click("button[data-act=cloud-token]"); a.wait_for_timeout(200)
    a.click("button[data-act=cloud-save]")
    check("first save creates revision 1 as docs/holdings.json", wait_banner(a, "revision 1") and M.puts == 1 and M.bodies[0][0] == "holdings.json")
    saved = json.loads(M.bodies[0][1])
    check("the saved file is plain, readable JSON with the holdings", saved["rev"] == 1 and saved["data"]["tx"][0]["ticker"].startswith("PUBLICCO") and saved["data"]["tx"][0]["qty"] == 111)
    check("debt and emergency-fund answers are NOT published", "safety" not in saved["data"] and "emergency" not in M.bodies[0][1])
    # device B: never configured, no token
    B = b.new_context(); M.install(B); d = B.new_page(); d.on("pageerror", lambda e: errs.append(str(e)))
    d.goto(SITE + "#/portfolio"); d.wait_for_timeout(1500)
    check("a brand-new device shows the holdings automatically (no click, no token, no passphrase)", "PUBLICCO" in d.inner_text("#view") and len(state(d)["tx"]) == 1)
    check("that device is read-only until a token is added", "read-only here" in d.inner_text("#chips"))
    d.goto(SITE + "#/sync"); d.wait_for_timeout(400)
    check("Save is disabled without a token", d.locator("button[data-act=cloud-save]").is_disabled())
    check("device B's own safety answers were not touched", state(d)["safety"] == {"debt": None, "emergency": None})
    # a change on A reaches B
    add_tx(a, "SECONDCO", 5, 100); a.wait_for_timeout(6500)
    check("A's later change is auto-saved (revision 2)", M.puts == 2)
    d.goto(SITE + "#/portfolio"); d.reload(); d.wait_for_timeout(1500)
    check("device B shows the new holding after reopening", "SECONDCO" in d.inner_text("#view"))
    # conflict
    d.goto(SITE + "#/sync"); d.wait_for_timeout(300); d.fill("#dp-token", "tok"); d.click("button[data-act=cloud-token]"); d.wait_for_timeout(200)
    add_tx(a, "FROMA", 9, 90); a.wait_for_timeout(6500)
    check("A saves revision 3", M.puts == 3)
    add_tx(d, "FROMB", 7, 70); d.wait_for_timeout(6500)
    check("B's stale save is a conflict, nothing overwritten", M.puts == 3 and "Cloud: conflict" in d.inner_text("#chips"))
    # switching to private mode shows the passphrase fields and does not touch the public file
    d.goto(SITE + "#/sync"); d.wait_for_timeout(300); d.check("input[data-bind=cloudmode][value=private]"); d.wait_for_timeout(400)
    check("switching to private mode asks for a passphrase", d.locator("#dp-pass").count() == 1 and M.puts == 3)
    check("no JavaScript errors", not errs)
    if errs: print(errs)
    b.close()
sys.exit(1 if fails else 0)
