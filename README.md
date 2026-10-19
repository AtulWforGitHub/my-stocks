# MIS: Investment Research Terminal (mid and small-cap multibagger research)

A personal research and decision-support dashboard for Indian mid and small-cap stocks, hosted free on GitHub Pages and updated by a free GitHub Actions job. It never places trades. Scores are not probabilities of returns.

## Quick start (automated: pick ONE)
**A. On the internet, from any device, PC can be off (recommended)**
1. github.com > New repository > name it, **Public**, no README > copy its URL.
2. In PowerShell, in this folder: `py -3.12 scripts\publish_to_github.py https://github.com/YOU/REPO.git`  (needs Git for Windows)
3. Click the three links it prints (or nothing, if the GitHub CLI `gh` is installed and signed in). Open `https://YOU.github.io/REPO/`.

**B. On this PC only**: `py -3.12 scripts\setup_local.py` (creates the environment, schedules a daily update at 17:30, runs the first full update, writes `Open-MIS.bat` to open the dashboard).

Both then update themselves on trading days. `python -m mis.run --fill` repeats itself until every company is screened.

## Holdings on every device: Cloud sync
Two modes (choose on the Cloud sync page, `#/sync`):
- **Public, no passphrase (default).** Your holdings, transactions, plans and decision notes are saved as a plain file `docs/holdings.json` in your repository. Anyone with your link can read them, and old versions stay in git history. Your debt and emergency-fund answers are never saved to the cloud. Any device that opens your site shows your holdings automatically, with no login; the daily job reads the file too, so the email gets a portfolio section with no secrets.
- **Private, encrypted.** The same data, encrypted in your browser with a passphrase (AES-256-GCM, PBKDF2 600,000 rounds) into `docs/holdings.enc.json`. Use 4+ random words: the repository is public, so a weak passphrase can be guessed offline. For the email section add the secret `MIS_PASSPHRASE`.

Saving needs a GitHub token, once per device where you edit (browsers cannot write to a repository without one). Make a fine-grained token for only your MIS repository with **Contents = Read and write** and an expiry. Reading needs nothing. A stolen token can change your repository. Two devices editing at once cause a conflict, and you choose which copy wins (no automatic merge).

## Run it
Free hosting (recommended):
1. Create a **public** repository, upload this folder (including `.github`).
2. Settings > Pages > Deploy from branch `main`, folder `/docs`.
3. Settings > Actions > General > Workflow permissions > Read and write.
4. Actions > "Update dashboard" > Run workflow. The first run takes 10-30 minutes (about 400 companies); later runs are quick.
5. Optional email: add repository secrets `GMAIL_APP_PASSWORD` (Google app password) and `MIS_EMAIL_TO`.
6. Optional private portfolio section in emails: paste a dashboard backup (Portfolio > Download backup) into the secret `MIS_HOLDINGS_JSON`. It is encrypted by GitHub and never published.

Local:
```
py -3.12 -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python -m mis.run --demo --force      # SYNTHETIC data -> demo_output\index.html
python -m mis.run --no-email          # real data -> docs\index.html
python -m pytest -q tests             # 50 Python tests
node --test tests/logic.test.js tests/ledger.test.js   # 36 JS tests
python tests/ui_smoke.py              # 32 browser checks (needs: pip install playwright; playwright install chromium)
```

## Privacy
Your transactions, safety answers, plans and decisions are stored only in your browser (localStorage). The public repo holds research data only. Download a backup regularly.

## Configuration
`config.yaml` (limits, weights, universe size, alerts, crypto toggle), `data/governance_flags.csv` (your governance reviews), `data/disclosures.csv` (mutual-fund/investor disclosures you verified), `data/nse_holidays.csv` (update each December from the NSE circular).

## Change log (this upgrade)
**Financial correctness (priority 1)**
- A "buy candidate" must now be inside its own preferred entry range. Before, 3 of 5 demo candidates sat above their range. Above-range stocks become WATCH with the pullback price stated.
- Missing data is excluded from the score and labelled "Insufficient data" instead of silently scored neutral. Under 50% evidence coverage there is no score.
- Confidence can never be High while governance is unreviewed; limitations are listed everywhere.
- The safety gate has three explicit answers. Unanswered means UNVERIFIED: the planner is a preview and Approve is disabled. Debt of 12%+ closes it; a low emergency fund halves it.
- Price anomaly check (a 35%+ one-day move) blocks recommendations until you verify splits/bonus. Stale prices never create fresh entries.
- Synthetic data is labelled everywhere, uses a separate output folder and state, cannot be emailed, and cannot be approved.
- Recommendation history is immutable (a recorded advice is never rewritten, even by a forced re-run).
- Portfolio P&L no longer counts holdings with no price.

**Interface (priority 2)**: terminal layout with sidebar, dark/light (saved), status chips (data mode, market status, last/next analysis, failed requests, email), SVG charts, sortable/searchable/paged tables, tooltips, keyboard focus, mobile layout, INR formatting.

**Research and planner (priority 3)**: three separate rankings, per-stock research pages (growth, ROE, debt, cash flow, valuation vs sector median, governance, technicals, SMILE, bull/base/bear illustration, invalidation, news, advice history), themes, new candidates held in a review queue until you approve them, planner with up to 10 chosen stocks, equal vs risk-adjusted weights, editable shares of the month, staged vs immediate comparison, costs, weight after purchase, save/approve/dismiss, decision journal with later performance.

**Operations (priority 4)**: NSE holiday calendar, backup run, 3 retries, missed-run recovery, idempotent runs, last-good-report preserved on failure (status.json drives a banner), failure email, change detection against the last successful run ("No material changes detected" on quiet days), alert de-duplication, urgent vs update vs weekly emails (HTML + plain text, ranked by materiality), health page with run history.

**Market intelligence (priority 5)**: gold, silver, crude, USD/INR, EUR/INR, India VIX/macro (Bitcoin/Ethereum if enabled), headlines, manual disclosure file. See the Markets > Integrations table for what is real.

## Independent audit (second pass) and test results
An independent audit reproduced nine defects, each fixed and covered by a regression test (see VERIFY.md for how to check them yourself):
1. **Publishing could silently fail**: if the repository changed during a run (for example you edited a file on GitHub), the new report was dropped while the job showed green. Now `scripts/publish.sh` commits first, rebases, retries, and fails loudly. Tested against real local git repositories.
2. **Stale reports could still be approved**: freshness was fixed when the report was built. Opened 10 days later, the planner still allowed Approve. Staleness is now evaluated when the page opens (and every 10 minutes).
3. **Inconsistent recommendation**: a stock below its 200-day average and well under its entry range could be a "buy candidate", with the thesis re-check level above the price. Candidates now need to be inside the range and not below the 200-day average, and the re-check level always sits below the range.
4. **Lost alerts**: a failed or unconfigured email still marked every alert as delivered. State is now saved only after a successful send.
5. **Fabricated inference**: a data failure was reported as a HIGH "thesis deterioration" (left the top-50). It is now a LOW data notice; a governance red flag is reported as critical.
6. **Wrong XIRR** when a holding had no price (showed -61.6% in the reproduction). Now n/a with a reason, and valued as of the price date.
7. **Unsafe link**: a `javascript:` headline URL from the news feed was rendered as a clickable link. Only http(s) links are kept (page and email).
8. **Stale fundamentals**: a failed refresh could reuse a 200-day-old saved copy as if current. Fallback is limited to 30 days, dated, and counted in a pipeline note.
9. **Run bookkeeping**: failed runs stayed "RUNNING"; the successful run itself was shown as RUNNING on the health page; a failed day is now retried.
Checked and found NOT to be a defect: tickers containing `&` (for example `M&M.NS`) route correctly (now a regression check).

Results in the build environment: **50 Python tests, 36 JavaScript tests, 32 browser checks pass**.

## Known limitations (honest)
- **Not implemented**: NSE/BSE announcements and filings, automatic mutual-fund and investor-holding feeds (manual CSV only), backtesting, ROCE, pledging/auditor/related-party data, historical valuation ranges, working-capital analysis, exact reporting periods.
- Data is Yahoo Finance via `yfinance` (unofficial, delayed). Verify prices in your broker before ordering. **Yahoo rate-limits heavy use**, especially from shared or cloud IP addresses (GitHub's runners included). The pipeline now stops after repeated refusals, limits requests per run, saves progress, and keeps the last good dashboard, but a persistently blocked connection means no fresh data. A paid or licensed feed is the real fix.
- NSE index-list addresses and ticker symbols in the fallback list could not be verified from the build environment (no internet). The first real run reports which source was used on the Health page.
- The 2026 holiday file has 13 confirmed dates; some sources count 15. The pipeline also checks that the latest market bar is current and says so if not.
- The holdings-based email section needs the optional secret; otherwise emails are research-level only.
- Month/day portfolio changes assume today's holdings; max drawdown needs about 20 saved days.
- Scenarios, VIX thresholds, industry tailwinds and SMILE thresholds are rules of thumb, not forecasts.
- The UI is one large HTML file; it is tested but would benefit from splitting if it grows.
- Nothing here has been validated as a predictor of returns.

## Next steps (recommended order)
1. Run it for real, check Health > Integrations and the universe note.
2. Fill `data/governance_flags.csv` for the stocks you actually consider.
3. Add NSE announcements via a licensed or official feed.
4. Add a paid, point-in-time fundamentals source, then build an honest backtest.
5. Automate AMC portfolio-disclosure ingestion.
