"""Daily pipeline. Run:  python -m mis.run [--demo] [--force] [--no-email]
A failed run NEVER overwrites the last good dashboard; it records the failure in status.json and (optionally) emails you."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import logging
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
import pandas as pd

from .config import load_config, ROOT, secret
from .universe import BENCHMARK
from .data import YahooProvider, freshness, extract_fundamentals, growth_from_fin, FUND_SCHEMA
from .indicators import technical_snapshot
from .scoring import score_stock, entry_setup_score
from . import decision, discovery, alerts as al, actions, changes as chg, news as newsmod, market, nse_calendar as cal, status as stat
from .audit import Audit
from .emailer import send_email
from .email_report import render as render_email
from .dashboard import render_dashboard

log = logging.getLogger("mis")


def read_governance(path: Path) -> dict:
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str).fillna("")
    return {r.ticker.strip().upper(): {"status": r.status.strip().lower() or "unreviewed", "note": r.note} for r in df.itertuples()}


def read_disclosures(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return pd.read_csv(path, dtype=str).fillna("").to_dict("records")


MAX_FALLBACK_FUND_DAYS = 30      # a failed refresh may fall back to saved fundamentals only this long
MAX_FALLBACK_GROWTH_DAYS = 120


def _age_days(c: dict) -> int | None:
    try:
        return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(c["retrieved_at"])).days
    except Exception:  # noqa: BLE001
        return None


def _may_fetch(provider, budget: dict | None) -> bool:
    """Per-run request budget + circuit breaker: never keep asking a source that is refusing us."""
    if getattr(provider, "tripped", False):
        return False
    if budget is not None:
        if budget["left"] <= 0:
            budget["deferred"] = budget.get("deferred", 0) + 1
            return False
        budget["left"] -= 1
    return True


def fundamentals_cached(provider, ticker: str, cache: dict, max_age_days: int = 7, budget: dict | None = None) -> dict:
    c = cache.get(ticker)
    if c and c.get("schema") == FUND_SCHEMA:             # an older-format copy is refreshed even if recent
        age = _age_days(c)
        if age is not None and age < max_age_days:
            return c
    f = extract_fundamentals(provider.info(ticker)) if _may_fetch(provider, budget) else {"available": False, "deferred": True}
    if f.get("available"):
        cache[ticker] = f
        return f
    if c:
        age = _age_days(c)
        if age is not None and age <= MAX_FALLBACK_FUND_DAYS:
            return {**c, "refresh_failed": True}          # still shown with its true retrieval date, and counted in a pipeline note
        return {"available": False, "stale_cache_days": age}   # too old to trust: treated as missing, never silently reused
    return f


def growth_cached(provider, ticker: str, cache: dict, max_age_days: int = 30, budget: dict | None = None) -> dict:
    c = cache.get(ticker)
    if c:
        age = _age_days(c)
        if age is not None and age < max_age_days:
            return c
    fin = provider.financials(ticker) if _may_fetch(provider, budget) else None
    if fin:
        g = growth_from_fin(fin)
        g["retrieved_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        cache[ticker] = g
        return g
    if c and (_age_days(c) or 10**6) <= MAX_FALLBACK_GROWTH_DAYS:
        return c
    return {"rev_cagr": None, "ni_cagr": None, "years": 0}


def peer_stats(universe: list[dict], funds: dict) -> dict:
    by: dict[str, dict] = {}
    for u in universe:
        f = funds.get(u["ticker"]) or {}
        if not f.get("available"):
            continue
        d = by.setdefault(u["sector"], {"pe": [], "roe": []})
        if f.get("trailing_pe") and 0 < f["trailing_pe"] < 300:
            d["pe"].append(f["trailing_pe"])
        if f.get("roe") is not None:
            d["roe"].append(f["roe"])
    out = {}
    for sec, d in by.items():
        if len(d["pe"]) >= 5:
            out[sec] = {"sector": sec, "pe_med": round(statistics.median(d["pe"]), 1), "roe_med": round(statistics.median(d["roe"]), 3) if d["roe"] else None,
                        "n": len(d["pe"])}
    return out


def integrations(mode: str, cfg: dict, universe_note: str, have_news: bool) -> list[dict]:
    have_mail = bool(secret("GMAIL_APP_PASSWORD"))
    return [
        {"name": "Prices and fundamentals (Yahoo Finance via yfinance)", "state": "active" if mode == "real" else "demo (synthetic)", "note": "Free, unofficial, delayed/end-of-day. Can be wrong or missing."},
        {"name": "NSE Midcap 150 + Smallcap 250 lists", "state": "active" if "Could not" not in universe_note and mode == "real" else "fallback/demo", "note": universe_note},
        {"name": "Headlines (Google News RSS)", "state": "active" if have_news else "inactive", "note": "Unverified headlines with source links. Not a filings feed."},
        {"name": "Gold, silver, crude, USD/INR, EUR/INR", "state": "active" if mode == "real" else "demo (synthetic)", "note": "Yahoo futures/FX proxies, not what an Indian investor pays."},
        {"name": "Bitcoin and Ethereum", "state": "enabled" if cfg.get("integrations", {}).get("crypto") else "off (config)", "note": "Set integrations.crypto: true in config.yaml."},
        {"name": "Email (Gmail SMTP)", "state": "configured" if have_mail else "needs GMAIL_APP_PASSWORD secret", "note": "Free. Needs a Google app password."},
        {"name": "Private portfolio section in emails", "state": "enabled" if (secret("MIS_HOLDINGS_JSON") or (ROOT / "docs" / "holdings.json").exists() or (secret("MIS_PASSPHRASE") and (ROOT / "docs" / "holdings.enc.json").exists())) else "off (turn on Cloud sync)", "note": "Read from your Cloud-sync file (public file, or encrypted file + MIS_PASSPHRASE secret)."},
        {"name": "NSE/BSE announcements and company filings", "state": "NOT IMPLEMENTED", "note": "Exchange feeds need session handling that was not built. Check exchange sites for filings."},
        {"name": "Mutual fund portfolio disclosures (AMFI/AMC)", "state": "NOT IMPLEMENTED (manual file)", "note": "Add rows you verified to data/disclosures.csv. They are shown with their disclosure date."},
        {"name": "Public investor holdings (for example Vijay Kedia)", "state": "NOT IMPLEMENTED (manual file)", "note": "Same file. Delayed filings only; never real-time trades."},
        {"name": "Governance data: pledging, auditor changes, related-party deals", "state": "NOT AVAILABLE", "note": "No free reliable feed. Record your own review in data/governance_flags.csv."},
        {"name": "Licensed market-data API", "state": "paid / not configured", "note": "Would replace Yahoo for reliability. Needs a paid subscription."},
    ]


def private_portfolio(snap_for_cli: dict) -> dict | None:
    """Review your holdings with the SAME JS logic as the dashboard. Output is used for the email only.
    Sources, in order: the secret MIS_HOLDINGS_JSON; the PUBLIC Cloud-sync file docs/holdings.json (no secret needed);
    the ENCRYPTED file docs/holdings.enc.json + the secret MIS_PASSPHRASE."""
    raw, pw = secret("MIS_HOLDINGS_JSON"), secret("MIS_PASSPHRASE")
    plain, enc = ROOT / "docs" / "holdings.json", ROOT / "docs" / "holdings.enc.json"
    use_enc = False
    if not raw and plain.exists():
        try:
            raw = json.dumps(json.loads(plain.read_text(encoding="utf-8"))["data"])
        except Exception:  # noqa: BLE001
            return {"error": "holdings file unreadable"}
    if not raw and pw and enc.exists():
        use_enc = True
    if not raw and not use_enc:
        return None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(snap_for_cli, f); path = f.name
        cmd = ["node", str(ROOT / "mis" / "review_cli.js"), path] + (["--enc", str(enc)] if use_enc else [])
        out = subprocess.run(cmd, input=None if use_enc else raw, capture_output=True, text=True, timeout=90)
        os.unlink(path)
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout else {"error": "review failed"}
    except Exception:  # noqa: BLE001
        return {"error": "review failed"}


def portfolio_items(p: dict, asof: str, provider: str) -> list[dict]:
    items = []
    cat = {"EXIT REVIEW": "critical_risk", "REDUCE CANDIDATE": "reduction_review", "WATCH": "thesis_deterioration", "ACCUMULATE CANDIDATE": "purchase_opportunity"}
    for a in p.get("actions", []):
        c = cat.get(a["action"])
        if not c or (a["action"] == "WATCH" and not any("thesis" in r.lower() or "re-check" in r.lower() for r in a["reasons"])):
            continue
        items.append(dict(id=f"pf-{c}:{a['ticker']}", category=c, level=actions.LEVEL[c], ticker=a["ticker"], name=a["name"],
                          title=f"{a['name']} (your holding): {a['action']}", reason=" ".join(a["reasons"][:2]) + (" " + a["priceNote"] if a.get("priceNote") else ""),
                          changed="current state of your holding", new=True, evidence="your holdings secret + today's research", source=provider, asof=asof,
                          next_step=actions._next(c), confidence=a["confidence"], limits=[], link="#/portfolio"))
    for b in p.get("breaches", []):
        items.append(dict(id=f"pf-conc:{b['kind']}:{b['subject']}", category="concentration", level="HIGH", ticker=b["subject"], name=b["subject"],
                          title=f"Concentration: {b['subject']} is {b['value']:.1f}% (limit {b['limit']}%)", reason="Position/sector/small-cap limit exceeded.",
                          changed="current state", new=True, evidence="your holdings secret", source=provider, asof=asof, next_step=actions._next("concentration"),
                          confidence="High", limits=[], link="#/portfolio"))
    return items


def run(demo: bool = False, force: bool = False, no_email: bool = False, today: dt.date | None = None) -> dict:
    holder: dict = {}
    try:
        return _run(holder, demo, force, no_email, today)
    except Exception as e:  # noqa: BLE001
        if holder.get("started"):       # never leave a failed run marked RUNNING
            holder["audit"].finish_run(holder["rd"], "FAILED", f"{type(e).__name__}: {e}"[:300])
        raise


def _run(holder: dict, demo: bool, force: bool, no_email: bool, today: dt.date | None) -> dict:
    cfg = load_config()
    ucfg = cfg["universe"]
    now_i = cal.now_ist()
    today = today or now_i.date()
    mode = "synthetic" if demo else "real"
    out_dir = ROOT / "demo_output" if demo else ROOT / "docs"
    state_dir = ROOT / ("demo_state" if demo else "state")
    out_dir.mkdir(exist_ok=True); state_dir.mkdir(exist_ok=True)
    status_path = out_dir / "status.json"
    audit = Audit(state_dir / "audit.db")
    rd = today.isoformat()
    holder["audit"], holder["rd"] = audit, rd
    hol = cal.load_holidays(ROOT / "data" / "nse_holidays.csv")
    health = {"notes": [], "failures": []}
    nxt = cal.next_run(now_i, hol).isoformat(timespec="minutes")

    is_day, day_why = cal.market_day(today, hol)
    if not is_day and not demo and not force:
        stat.write(status_path, outcome="skipped", run_date=rd, mode=mode, notes=[f"Skipped: {day_why}. The last good report is kept."], next_run=nxt, runs=audit.recent_runs())
        print(f"Skipped {rd}: {day_why}")
        return {"skipped": True, "reason": day_why}
    if audit.run_done(rd) and not force:
        print(f"Run for {rd} already completed (idempotent). Use --force to re-run.")
        return {"skipped": True}
    last = audit.last_ok_run()
    if last:
        missed = cal.trading_days_between(dt.date.fromisoformat(last), today, hol) - 1
        if missed > 0:
            health["notes"].append(f"Recovered after {missed} missed trading day(s): last good update was {last}. Price history covers the gap.")
    audit.start_run(rd)
    holder["started"] = True

    if demo:
        from .synthetic import SyntheticProvider
        provider = SyntheticProvider()
    else:
        provider = YahooProvider(cfg["data"]["request_pause_seconds"], cfg["data"]["max_retries"],
                                 cfg["data"].get("rate_limit_backoff_seconds", 8), cfg["data"].get("rate_limit_trip_after", 4))

    universe, unote = discovery.load_universe(state_dir, offline=demo)
    health["notes"].append("Universe: " + unote)
    meta = {u["ticker"]: u for u in universe}
    gov = read_governance(ROOT / "data" / "governance_flags.csv")

    cache_path = state_dir / "fundamentals_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    funds = {}
    fbudget = {"left": ucfg.get("max_new_fetches_per_run", 150)}
    try:
        for i, u in enumerate(universe):
            funds[u["ticker"]] = fundamentals_cached(provider, u["ticker"], cache, budget=fbudget)
            if i % 50 == 49:
                log.info("stage 1: %d/%d", i + 1, len(universe))
    finally:
        if not demo:
            cache_path.write_text(json.dumps(cache, indent=1))
    excluded: dict[str, str] = {}
    for u in universe:
        if not (funds.get(u["ticker"]) or {}).get("available"):
            excluded[u["ticker"]] = "data"
    n_ok = sum(1 for f in funds.values() if f.get("available"))
    if getattr(provider, "tripped", False):
        health["notes"].append(f"Yahoo Finance rate-limited this connection, so requests were stopped early. {n_ok} of {len(universe)} companies have data; saved progress will be reused on the next run.")
    elif fbudget.get("deferred"):
        health["notes"].append(f"Screening is filling in gradually: {n_ok} of {len(universe)} companies have data; {fbudget['deferred']} are deferred to the next run by the per-run request limit.")
    n_old = sum(1 for f in funds.values() if f.get("refresh_failed"))
    if n_old:
        health["notes"].append(f"{n_old} companies use saved fundamentals older than 7 days because the refresh failed (still under 30 days old; they are dated on each stock page).")
    shortlist = discovery.prefilter(universe, funds, ucfg)
    peers = peer_stats(universe, funds)
    health["notes"].append(f"Screened {len(universe)} companies; {len(shortlist)} passed the first quality screen.")

    gpath = state_dir / "growth_cache.json"
    gcache = json.loads(gpath.read_text()) if gpath.exists() else {}
    growth = {}
    gbudget = {"left": ucfg.get("max_new_growth_per_run", 80)}
    try:
        for u in shortlist:
            growth[u["ticker"]] = growth_cached(provider, u["ticker"], gcache, budget=gbudget)
    finally:
        if not demo:
            gpath.write_text(json.dumps(gcache, indent=1))
    tickers = [u["ticker"] for u in shortlist]
    hist = provider.history(tickers + [BENCHMARK], cfg["data"]["history_period"])
    bench = hist.get(BENCHMARK)
    bench_close = bench["Close"] if bench is not None else None
    if bench is None:
        health["notes"].append("Nifty 50 data was unavailable today, so relative-strength scores and the benchmark comparison were skipped.")
    else:
        bl = bench.index[-1].date()
        expected = today if ((is_day and now_i.hour >= 16) or demo) else today - dt.timedelta(days=1)
        while not cal.market_day(expected, hol)[0]:
            expected -= dt.timedelta(days=1)
        if bl < expected and not demo:
            health["notes"].append(f"No new market bar: latest Nifty 50 data is {bl}, expected {expected}. Possible unlisted holiday or provider delay. "
                                   "Advice uses the older data and is labelled with its date.")
    miss = [t for t in getattr(provider, "missing_history", []) if t != BENCHMARK]
    if miss:
        health["notes"].append(f"No price history came back for {len(miss)} shortlisted ticker(s) (for example {', '.join(miss[:4])}); they are skipped, not guessed.")

    stocks, illiquid, closes = [], 0, {}
    for t in tickers:
        m = meta[t]
        df = hist.get(t)
        fr = freshness(df, cfg["data"]["stale_after_days"], today)
        if df is None:
            health["failures"].append(t); excluded[t] = "data"; continue
        tech = technical_snapshot(df, bench_close)
        tv = tech.get("avg_traded_value_cr")
        if tv is not None and tv < ucfg["min_traded_value_cr"]:
            illiquid += 1; excluded[t] = "illiquid"; continue
        fund = funds[t]
        g = gov.get(t, {"status": "unreviewed", "note": ""})
        res = score_stock(m, fund, tech, g, cfg["scoring_weights"], growth.get(t), ucfg["exit_pe"])
        ent = entry_setup_score(tech)
        zones = decision.entry_zones(tech)
        status, why = decision.classify(res, ent, fr, g["status"], tech, zones)
        closes[t] = [float(x) for x in df["Close"].tail(330).tolist()]
        stocks.append(dict(ticker=t, name=m["name"], sector=m["sector"], cap=m["cap"], price=tech.get("last"),
                           price_asof=fr["asof"], fresh=fr, price_fresh=fr["status"] == "fresh", tech=tech, fund=fund,
                           growth=growth.get(t, {}), research=res["total"], components=res["components"], missing=res["missing"],
                           confidence_pct=res["data_confidence_pct"], confidence=res["confidence"], gov=g, entry=ent["score"],
                           entry_reasons=ent["reasons"], entry_avoid=ent["avoid"], status=status, why=why, zones=zones, smile=res["smile"], mb=res["mb"],
                           scenarios=decision.scenarios(fund, tech), invalidation=decision.invalidation(m, fund)))
    if illiquid:
        health["notes"].append(f"{illiquid} shortlisted companies were dropped for thin trading (under Rs {ucfg['min_traded_value_cr']} crore a day).")
    for s in stocks:
        if s["gov"]["status"] == "red_flag":
            excluded[s["ticker"]] = "red_flag"
    stocks = [s for s in stocks if s["gov"]["status"] != "red_flag"]
    stocks.sort(key=lambda s: (s["research"] is not None, s["research"] or 0), reverse=True)
    stocks = stocks[: ucfg["target_size"]]

    n_fresh = sum(1 for s in stocks if s["price_fresh"] and s["status"] != "DATA UNAVAILABLE")
    failed_requests = int(getattr(provider, "failed", 0)) + len(health["failures"]) + (1 if bench is None else 0)
    if not demo and n_fresh < 10 and getattr(provider, "tripped", False):
        raise RuntimeError("Yahoo Finance is rate-limiting this connection (too many requests). Nothing was changed; the last good dashboard is kept. "
                           "Try again in an hour, upgrade yfinance (pip install --upgrade yfinance), or use a different network. Progress is saved.")
    if not demo and n_fresh < 10:
        raise RuntimeError(f"Only {n_fresh} stocks have fresh, valid data; the existing dashboard was left untouched.")
    n_bad = len(stocks) - n_fresh
    if n_bad > len(stocks) * 0.3:
        health["notes"].append(f"{n_bad} of {len(stocks)} stocks have no fresh, valid data today; advice for them is paused.")

    # ---- market intelligence
    mkt_assets, mkt_macro = [], []
    amap = {k: v for k, v in market.ASSETS.items() if v[2] is None or cfg.get("integrations", {}).get(v[2])}
    mh = provider.history([v[0] for v in amap.values()] + list(market.MACRO.values()), "2y")
    for name, (tk, inst, _) in amap.items():
        f = market.facts(mh.get(tk), name); f["instrument"] = inst; mkt_assets.append(f)
    for name, tk in market.MACRO.items():
        mkt_macro.append(market.facts(mh.get(tk), name))
    vix = next((m for m in mkt_macro if m["name"] == "India VIX"), None)
    nif = next((m for m in mkt_macro if m["name"] == "Nifty 50"), None)
    risk = market.market_risk(vix, nif)
    ms = cal.market_status(now_i, hol)

    # ---- news (headlines only; unverified)
    news_by_t, news_market = {}, []
    if not demo:
        top = sorted([s for s in stocks if s["research"] is not None], key=lambda s: -s["research"])[:15]
        for s in top:
            items = [i for i in newsmod.dedupe(newsmod.fetch(f"{s['name']} share", 6)) if newsmod.relevant(i["title"], s["name"])][:3]
            if items:
                news_by_t[s["ticker"]] = items
        news_market = newsmod.dedupe(newsmod.fetch("Nifty Sensex RBI India market", 7))[:7]

    # ---- what changed since the last SUCCESSFUL run
    snap_path = state_dir / "last_snapshot.json"
    prev = chg.load(snap_path)
    names = {u["ticker"]: u["name"] for u in universe}
    asof = max([s["price_asof"] for s in stocks if s["price_asof"]] or [rd])
    changes = chg.diff(prev, stocks, names, asof, excluded)
    items = actions.build_items(changes, stocks, news_by_t, risk, provider.name, mode, bool(prev))

    # ---- audit trail: every stock, every run; recorded as known at the time and never rewritten
    for s in stocks:
        audit.log_rec(rd, s["ticker"], s["status"], "; ".join(s["why"]),
                      {"research": s["research"], "entry": s["entry"], "components": {k: v["points"] for k, v in s["components"].items()},
                       "missing": s["missing"], "smile": s["smile"], "mb": s["mb"], "confidence": s["confidence"]["label"]},
                      f"{s['confidence']['label']} ({s['confidence']['pct']}% of inputs)", s["invalidation"], s["price"], s["price_asof"], provider.name)
    audit.commit()
    history = audit.history_events()

    bench_weekly = []
    if bench is not None:
        w = bench["Close"].resample("W").last().dropna()
        bench_weekly = [[str(i.date()), round(float(v), 2)] for i, v in w.items()]

    # ---- optional private portfolio review (email only)
    pf = None
    snap_ctx = dict(today=today, cfg=cfg, mode=mode, generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), stocks=stocks,
                    peers=peers, news_by_t=news_by_t, closes=closes, items=items, changes=changes, bench=bench_weekly,
                    market={"assets": mkt_assets, "macro": mkt_macro, "risk": risk, "status": ms}, news_market=news_market, history=history,
                    integrations=integrations(mode, cfg, unote, bool(news_market or news_by_t)), disclosures=read_disclosures(ROOT / "data" / "disclosures.csv"),
                    health=health, provider=provider.name, universe_size=len(universe), status={}, holidays=sorted(str(d) for d, v in hol.items() if v[0] == "holiday"))
    from .dashboard import snapshot
    private_items: list[dict] = []
    if not demo:
        pf = private_portfolio(snapshot(snap_ctx))
        if pf and not pf.get("error"):
            private_items = portfolio_items(pf, asof, provider.name)

    # ---- alerts, de-duplicated by state change
    all_alerts = actions.to_alerts(items + private_items)
    fresh_alerts, new_state = al.dedupe(all_alerts, state_dir / "alert_state.json", today)
    email_state = {"status": "not attempted", "note": "demo mode" if demo else ""}
    to_addr = secret("MIS_EMAIL_TO") or cfg.get("owner_email")
    partial = bool(fbudget.get("deferred")) or getattr(provider, "tripped", False)
    if not no_email and not demo:
        go, why, kind = al.should_email(fresh_alerts, cfg, today)
        if partial:
            email_state = {"status": "deferred", "note": "screening is still incomplete; no email until every company has been screened"}
        elif not to_addr or not secret("GMAIL_APP_PASSWORD"):
            email_state = {"status": "not configured", "note": "Add GMAIL_APP_PASSWORD and MIS_EMAIL_TO secrets to enable email."}
        elif go:
            repo = os.environ.get("GITHUB_REPOSITORY", "")
            url = f"https://{repo.split('/')[0].lower()}.github.io/{repo.split('/')[1]}/" if "/" in repo else "(your dashboard link)"
            summary = dict(mode=mode, run_date=rd, price_date=asof, provider=provider.name, market_risk=risk, headlines=news_market,
                           stale_note=(health["notes"][-1] if any("No new market bar" in n for n in health["notes"]) else None))
            send_items = [a["item"] for a in fresh_alerts] if kind != "weekly" else (private_items + items)
            send_items.sort(key=lambda i: ["CRITICAL", "HIGH", "MEDIUM", "LOW"].index(i["level"]))
            html_b, text_b = render_email(summary, send_items, url, kind, pf if pf and not pf.get("error") else None)
            ok_sent, msg = send_email(al.subject_for(fresh_alerts, today, kind), html_b, text_b, to_addr)
            email_state = {"status": "sent" if ok_sent else "FAILED", "note": f"{why}: {msg}", "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")}
            if not ok_sent:
                health["notes"].append("Email failed: " + msg)
        else:
            email_state = {"status": "not needed", "note": why}
        if email_state["status"] in ("sent", "not needed"):
            al.save_state(new_state, state_dir / "alert_state.json")     # a failed or unconfigured email must NOT mark alerts as delivered

    runs_disp = [dict(r, status="OK") if r["date"] == rd else r for r in audit.recent_runs()]
    status = stat.build(status_path, outcome="ok", run_date=rd, mode=mode, provider=provider.name, price_date=asof, failed_requests=failed_requests,
                        email=email_state, notes=health["notes"], next_run=nxt, runs=runs_disp)
    snap_ctx["status"] = {**status, "market_status": ms}
    (out_dir / "index.html").write_text(render_dashboard(snap_ctx), encoding="utf-8")
    snap_path.write_text(json.dumps({"date": rd, "stocks": chg.compact(stocks), "excluded": excluded}))
    audit.finish_run(rd, "OK", email_state.get("note", ""))                  # only after the dashboard exists
    stat.dump(status_path, {**status, "runs": audit.recent_runs()})
    print(f"Done {rd} ({mode}). {len(universe)} screened, {len(stocks)} on watchlist, "
          f"{sum(1 for s in stocks if s['status']=='ACCUMULATE CANDIDATE')} in entry range, {len(changes)} changes. Email: {email_state['status']}")
    return snap_ctx | {"changes": changes}


def fill_until_complete(run_fn, max_passes: int = 5, force: bool = False):
    """Run again (re-using saved progress) until every company is screened. Stops early on a holiday skip or a rate limit."""
    ctx, passes = None, 0
    for i in range(max_passes):
        passes = i + 1
        ctx = run_fn(force=(force or i > 0))
        if not isinstance(ctx, dict) or ctx.get("skipped"):
            break
        notes = ctx.get("health", {}).get("notes", [])
        if not any("filling in gradually" in n for n in notes) or any("rate-limited" in n for n in notes):
            break
    return ctx, passes


def main():
    ap = argparse.ArgumentParser(description="MIS daily run")
    ap.add_argument("--fill", action="store_true", help="repeat (up to 5 passes) until every company has been screened")
    ap.add_argument("--demo", action="store_true", help="synthetic data, writes to demo_output/ (no email)")
    ap.add_argument("--force", action="store_true", help="re-run even if today's run completed or the market is closed")
    ap.add_argument("--no-email", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        if a.fill:
            _, n = fill_until_complete(lambda **k: run(demo=a.demo, no_email=a.no_email, **k), force=a.force)
            print(f"Finished after {n} pass(es).")
        else:
            run(demo=a.demo, force=a.force, no_email=a.no_email)
    except Exception as e:  # noqa: BLE001
        logging.exception("run failed")
        out_dir = ROOT / ("demo_output" if a.demo else "docs"); out_dir.mkdir(exist_ok=True)
        try:
            cfg = load_config()
            today = cal.now_ist().date().isoformat()
            stat.write(out_dir / "status.json", outcome="failed", run_date=today, mode="synthetic" if a.demo else "real",
                       notes=["The last good report is kept below and labelled with its date."], error=f"{type(e).__name__}: {e}"[:300])
            to_addr = secret("MIS_EMAIL_TO") or cfg.get("owner_email")
            if not a.demo and to_addr and secret("GMAIL_APP_PASSWORD"):
                send_email(f"[MIS FAILED] Daily update failed - {today}",
                           f"<p>The daily update failed: {type(e).__name__}. Your dashboard still shows the last good report, labelled with its date.</p>",
                           f"The daily update failed: {type(e).__name__}. Your dashboard still shows the last good report, labelled with its date.", to_addr)
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
