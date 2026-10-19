# How to verify this application on your own computer

Each step says what you do and what you must see. If something differs, stop and treat it as a defect.
Commands are for Windows PowerShell. You need Python 3.12, and (for step 2b) Node.js 20+ and git.

## 1. Install
```
cd path\to\my-stock-dashboard\mis-tool
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Automated tests (no internet needed)
a. `python -m pytest -q tests`  -> must end with **50 passed**.
b. `node --test tests/logic.test.js tests/ledger.test.js`  -> must show **# pass 36** and **# fail 0**.
c. Optional browser checks: `pip install playwright` then `playwright install chromium`, then
   `python -m mis.run --demo --force` and `python tests/ui_smoke.py`  -> **32 PASS lines, no FAIL line**.

## 3. See the demo and confirm it is labelled
`python -m mis.run --demo --force`, then open `demo_output\index.html` in your browser.
- Red banner "Synthetic demonstration data" and a red "SYNTHETIC DEMO DATA" chip at the top. No chip may say "Live".
- Monthly planner: type 20000. Without answering the two safety questions the plan says **PREVIEW ONLY** and the Approve button is **disabled**. Answer "No" and "Yes": Approve stays **disabled** (demo data can never be approved).
- Answer "Yes" to the debt question: the plan says **NO PURCHASE RECOMMENDED**.

## 4. Verify the stale-report protection by hand (the audit's most important browser fix)
1. Open `demo_output\index.html` in a text editor. Change `"mode":"synthetic"` to `"mode":"real"` and `"demo":true` to `"demo":false` (this only pretends the file is real, for the test). Save as `real-test.html`.
2. Open it, go to Monthly planner, type 20000, answer No / Yes. Expected: plan rows appear and **Approve is enabled** (control case).
3. Edit `real-test.html` again: change `"price_date":"..."` to a date 10 days earlier than today. Reload. Expected: red banner "These prices are 10 days old", plan says **NO PURCHASE RECOMMENDED: the prices in this report are 10 days old**, no rows, Approve disabled.
4. On the Portfolio page add a buy of a stock that is not on the list (for example `NOPRICE`) plus one listed stock, both dated at least 4 months ago. Expected: the XIRR tile shows **n/a** with an explanation, never a percentage.

## 5. First real data run (needs internet, 10-30 minutes the first time)
```
python -m mis.run --no-email --force
```
Then open `docs\index.html`.
- Open **System health**. "Data mode" must say Real. The Integrations table must show the NSE Midcap/Smallcap row as **active**. If it says "fallback", the NSE list address failed: tell me.
- **Spot-check 3 stocks** against your broker or nseindia.com: price and date, and on the stock page ROE and market cap against screener.in. If ROE or debt/equity are off by a factor of 100, the Yahoo units assumption is wrong: tell me.
- Check that no "buy candidate" (Research > Three rankings, list 2) sits below its 200-day average or outside its entry range.
- Today's date: confirm "Market now" matches the real market state.

### If step 5 shows `YFRateLimitError` (Yahoo says "too many requests")
1. Press Ctrl+C. Progress is saved and the old dashboard is untouched.
2. Upgrade the Yahoo library (older versions are blocked more often): `.\.venv\Scripts\python.exe -m pip install --upgrade yfinance`
3. Wait 30-60 minutes, or switch network (home Wi-Fi or a phone hotspot; shared office networks are throttled hardest).
4. Run again. The run now stops after a few refusals instead of retrying hundreds of times, fetches at most 150 companies per run, and picks up where it left off, so 3-4 runs may be needed to cover everything. The health page says how many companies are covered.
5. Quick diagnostic: `.\.venv\Scripts\python.exe -c "import yfinance as yf; print(yf.__version__); print(yf.Ticker('TCS.NS').history(period='5d'))"`

## 6. Email (optional)
In PowerShell: `$env:GMAIL_APP_PASSWORD="your-16-char-app-password"; $env:MIS_EMAIL_TO="you@gmail.com"` then `python -m mis.run --force`.
- Expected: an email arrives (HTML, readable on phone) and System health shows Email: sent.
- Failure test: use a WRONG app password and run with `--force` again after deleting `state\alert_state.json`. Expected: Email: **FAILED** on the health page and **no `state\alert_state.json` file is created** (alerts stay pending and will be retried on the next run).

## 7. GitHub Actions and Pages
1. Create a public repository, upload the folder, enable Pages (branch main, folder /docs) and Actions write permission (README steps 1-4).
2. Actions > "Update dashboard" > Run workflow. Expected: green; the **Publish** step log ends with "Published on attempt 1" (or "Nothing new to publish").
3. Open your Pages link. Health page: last successful analysis is today.
4. **Moved-remote test**: while a run is in progress, edit any file on github.com and commit. When the run ends, open the Pages link: it must still show the new report (the earlier version silently dropped it).
5. Holiday check: on a day listed in `data\nse_holidays.csv`, the run must end green with "Skipped: NSE holiday" and the old dashboard stays.

## 8. Cloud sync (holdings on every device)
Do this only after step 7 works. Follow README > "Holdings on every device". Public mode:
- Cloud sync page > paste token > Save token > Save to cloud now. On github.com open `docs/holdings.json`: you will see your holdings in plain text (that is what public mode means). It must NOT contain your debt or emergency-fund answers.
- Open your site on a second device or a private window: your holdings appear by themselves, and the top bar says "Cloud: read-only here" until you add a token there.
- Change something on device 1, wait 10 seconds, reopen device 2: the change appears.
- Edit on both devices without reopening in between: the second save shows "Cloud: conflict" and offers Overwrite, never silently replaces.
- After the next daily run, the email has a "Your portfolio" section (with email configured; no extra secret needed).
Private mode: `docs/holdings.enc.json` must be unreadable scrambled text (if you can read a ticker or quantity, stop and tell me); a wrong passphrase must say "Wrong passphrase" and load nothing.

## What I could not test for you
Live Yahoo data and its field units, the NSE list download, Gmail delivery, a real GitHub Actions/Pages run, the real GitHub contents API used by Cloud sync (tested only against a stand-in), Safari/Firefox, and a real phone. Steps 5-7 exist to cover exactly those.
