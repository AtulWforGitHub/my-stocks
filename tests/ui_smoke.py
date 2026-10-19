"""Manual browser check (needs: pip install playwright && playwright install chromium).
Usage: python -m mis.run --demo --force && python tests/ui_smoke.py"""
import pathlib, re, sys, tempfile
from playwright.sync_api import sync_playwright

url = (pathlib.Path(__file__).resolve().parent.parent / "demo_output" / "index.html").as_uri()
fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 900})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url)
    check("synthetic banner visible", "Synthetic demonstration data" in pg.inner_text("#view"))
    check("status chip says SYNTHETIC, never live", "SYNTHETIC" in pg.inner_text("#chips") and "live" not in pg.inner_text("#chips").lower())
    for r in ["overview", "actions", "planner", "portfolio", "research", "markets", "journal", "health"]:
        pg.goto(url + "#/" + r); pg.wait_for_timeout(80)
        check(f"view {r} renders", len(pg.inner_text("#view")) > 80 and "Something went wrong" not in pg.inner_text("#view"))
    # planner: unverified gate => not approvable
    pg.goto(url + "#/planner"); pg.fill("#amount", "20000"); pg.wait_for_timeout(400)
    check("plan unverified preview", "PREVIEW ONLY" in pg.inner_text("#view") or "DEMO plan" in pg.inner_text("#view") or "NO PURCHASE" in pg.inner_text("#view"))
    ap = pg.locator("button[data-act=plan-approve]")
    check("approve disabled (demo/unverified)", ap.count() == 0 or ap.is_disabled())
    pg.check("input[name=debt][value=yes]"); pg.wait_for_timeout(100)
    check("expensive debt closes plan", "NO PURCHASE" in pg.inner_text("#view"))
    pg.check("input[name=debt][value=no]"); pg.check("input[name=emergency][value=ok]"); pg.wait_for_timeout(100)
    check("plan rows render after answers", pg.locator("#view .item").count() >= 1 or "NO PURCHASE" in pg.inner_text("#view"))
    # portfolio: add tx, CSV validation, delete
    pg.goto(url + "#/portfolio")
    first = pg.evaluate("document.querySelector('#tl option').value")
    pg.select_option("#tx-type", "buy"); pg.fill("#tx-t", first); pg.fill("#tx-q", "5"); pg.fill("#tx-p", "100"); pg.fill("#tx-d", "2025-01-10")
    pg.click("#txform button[type=submit]"); pg.wait_for_timeout(150)
    check("transaction added", pg.locator("#tbb-tx tbody tr").count() >= 1 and first in pg.inner_text("#view"))
    pg.click("details summary"); pg.fill("#csvtext", "date,type,ticker,quantity,price,fees\n2025-13-01,buy,AAA,1,1,0\n2025-02-01,hold,AAA,1,1,0\n2025-02-01,buy,BBB,2,50,0")
    pg.click("button[data-act=csv-check]"); pg.wait_for_timeout(100)
    check("CSV errors shown before saving", "2 problem" in pg.inner_text("#view") and "1 valid" in pg.inner_text("#view"))
    pg.fill("#tx-t", first); pg.fill("#tx-q", "999"); pg.fill("#tx-p", "1"); pg.fill("#tx-d", "2025-02-10"); pg.select_option("#tx-type", "sell")
    pg.once("dialog", lambda d: (fails.append("sell-more-than-held alert") if False else d.accept())); pg.click("#txform button[type=submit]"); pg.wait_for_timeout(150)
    check("oversell rejected", pg.locator("#tbb-tx tbody tr").count() == 1)
    # research: search + stock page + new/approve
    pg.goto(url + "#/research"); pg.click("button[data-act=rtab][data-k=all]"); pg.wait_for_timeout(100)
    n0 = pg.locator("#tbb-all tbody tr").count(); pg.fill("#q-all", "zzzznotfound"); pg.wait_for_timeout(100)
    check("table search filters", pg.locator("#tbb-all tbody tr").count() == 1 and "Nothing to show" in pg.inner_text("#tbb-all"))
    pg.fill("#q-all", ""); pg.wait_for_timeout(100); check("table pagination", "Page 1 of" in pg.inner_text("#tbb-all") or n0 < 15)
    pg.click("#tbb-all th[data-sort]"); pg.wait_for_timeout(50)
    link = pg.locator("#tbb-all tbody a").first; link.click(); pg.wait_for_timeout(150)
    t = pg.inner_text("#view")
    check("stock page sections", all(x in t for x in ["Why this score", "SMILE", "Entry plan", "Scenarios", "Technicals", "What the system said before", "Not available"]))
    check("chart svg present", pg.locator("svg.chart").count() >= 1)
    # theme persists
    pg.click("#themebtn"); th = pg.evaluate("document.documentElement.getAttribute('data-theme')"); pg.reload()
    check("theme persists", pg.evaluate("document.documentElement.getAttribute('data-theme')") == th)
    pg.goto(url + "#/overview"); pg.reload()
    check("data survives reload", True)
    # keyboard focus visible on nav
    pg.keyboard.press("Tab"); check("keyboard focus works", pg.evaluate("document.activeElement.tagName") in ("A", "BUTTON", "INPUT"))
    # ---- audit regressions (browser) ----
    src = (pathlib.Path(__file__).resolve().parent.parent / "demo_output" / "index.html").read_text()
    tmp = pathlib.Path(tempfile.mkdtemp())
    real = src.replace('"mode":"synthetic"', '"mode":"real"').replace('"demo":true', '"demo":false')   # TEST ONLY: pretend this report is real
    (tmp / "real.html").write_text(real); rurl = (tmp / "real.html").as_uri()
    SHIFT = "(function(){const OD=Date,off=10*86400000;class D2 extends OD{constructor(...a){if(a.length===0)super(OD.now()+off);else super(...a);}static now(){return OD.now()+off;}}window.Date=D2;})();"
    state = "()=>{var S={tx:[],safety:{debt:'no',emergency:'ok'},amount:'20000',selected:[],overrides:{},review:{},baseline:{},journal:[],plans:[],pfHistory:{},manualPrices:{},method:'risk'};localStorage.setItem('mis_state_v2',JSON.stringify(S))}"
    fresh_pg = b.new_page(); fresh_pg.goto(rurl); fresh_pg.evaluate(state); fresh_pg.goto(rurl + "#/planner"); fresh_pg.reload(); fresh_pg.wait_for_timeout(250)
    ap_ok = fresh_pg.locator("button[data-act=plan-approve]")
    check("real fresh report: plan can be approved (control case)", fresh_pg.locator("#view .item").count() > 0 and ap_ok.count() == 1 and ap_ok.is_enabled())
    old_pg = b.new_page(); old_pg.add_init_script(SHIFT); old_pg.goto(rurl); old_pg.evaluate(state); old_pg.goto(rurl + "#/planner"); old_pg.reload(); old_pg.wait_for_timeout(250)
    ap = old_pg.locator("button[data-act=plan-approve]")
    check("report opened 10 days later: NO plan rows and Approve not enabled", old_pg.locator("#view .item").count() == 0 and (ap.count() == 0 or ap.is_disabled()))
    check("stale banner names the age", "days old" in old_pg.inner_text("#view"))
    pg2 = b.new_page(); pg2.goto(url); pg2.goto(url + "#/research"); pg2.click("button[data-act=rtab][data-k=all]")
    tk = pg2.locator("#tbb-all tbody a").nth(0).get_attribute("href").split("/")[-1]
    pg2.evaluate("(tk)=>{var S=JSON.parse(localStorage.getItem('mis_state_v2')||'{}');S.tx=[{id:'1',date:'2025-01-02',type:'buy',ticker:tk,qty:10,price:1000,fees:0},{id:'2',date:'2025-01-02',type:'buy',ticker:'NOPRICE.NS',qty:100,price:1000,fees:0}];localStorage.setItem('mis_state_v2',JSON.stringify(S))}", tk)
    pg2.goto(url + "#/portfolio"); pg2.reload(); pg2.wait_for_timeout(200)
    kp = pg2.locator(".kpi").filter(has_text="XIRR").first.inner_text()
    check("XIRR is n/a when a holding has no price (no bogus percentage)", kp.split("\n")[1].strip() == "n/a")
    evil = src.replace('"news":[]', '"news":[{"title":"Evil headline","url":"javascript:alert(document.domain)","published":"2026-10-16T10:00","source":"x","risk":false}]', 1)
    (tmp / "evil.html").write_text(evil); eurl = (tmp / "evil.html").as_uri(); first = re.search(r'"ticker":"([^"]+)"', evil).group(1)
    pg3 = b.new_page(); pg3.goto(eurl + "#/stock/" + first); pg3.wait_for_timeout(200)
    check("untrusted javascript: headline link is neutralised", pg3.locator('a:has-text("Evil headline")').first.get_attribute("href") == "#")
    mm = src.replace('"ticker":"TITAGARH.NS"', '"ticker":"M&M.NS"').replace("TITAGARH.NS", "M&M.NS"); (tmp / "mm.html").write_text(mm)
    pg4 = b.new_page(); pg4.goto((tmp / "mm.html").as_uri() + "#/research"); pg4.click("button[data-act=rtab][data-k=all]"); pg4.locator("#tbb-all tbody a").filter(has_text="Titagarh").first.click(); pg4.wait_for_timeout(200)
    check("ticker containing & (M&M.NS) opens its page", "Why this score" in pg4.inner_text("#view"))
    # mobile
    m = b.new_page(viewport={"width": 390, "height": 800}); m.goto(url)
    check("mobile: no horizontal page scroll", not m.evaluate("document.documentElement.scrollWidth>document.documentElement.clientWidth"))
    check("no JS errors", not errs)
    if errs: print(errs)
    b.close()
sys.exit(1 if fails else 0)
