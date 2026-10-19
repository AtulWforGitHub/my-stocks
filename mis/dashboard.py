"""Build the single-file dashboard: today's research snapshot + decision logic + app. Holdings are never embedded:
they live in the viewer's browser (localStorage)."""
from __future__ import annotations
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else round(o, 4)
    if hasattr(o, "item"):
        return _clean(o.item())
    return o


def stock_json(s: dict, peers: dict, news: list, closes: list[float]) -> dict:
    z, t, f, g = s["zones"], s["tech"], s["fund"], s["growth"]
    sc = s["scenarios"]
    price = s["price"]
    return {
        "ticker": s["ticker"], "name": s["name"], "sector": s["sector"], "cap": s["cap"], "price": price, "asof": s["price_asof"],
        "fresh": bool(s["price_fresh"]), "research": s["research"], "entry": s["entry"], "status": s["status"], "why": s["why"][:4],
        "confidence": s["confidence"], "gov": s["gov"]["status"], "govNote": s["gov"].get("note", ""),
        "atr": t.get("atr"), "atrPct": t.get("atr_pct"), "ext200": t.get("ext_200_pct"), "ret1y": t.get("ret_1y_pct"),
        "chg1d": t.get("ret_1d_pct"), "chg1m": t.get("ret_1m_pct"),
        "tech": {k: t.get(k) for k in ("rsi", "dma20", "dma50", "dma100", "dma200", "macd_hist", "vol_ann_pct", "from_high_pct", "high_52w", "low_52w",
                                      "support", "resistance", "rs_6m_vs_nifty", "avg_traded_value_cr", "max_gap_1y_pct", "drawdown_1y_pct", "vol_ratio_20_50")},
        "fund": {"mcap": f.get("market_cap_cr"), "pe": f.get("trailing_pe"), "fpe": f.get("forward_pe"), "pb": f.get("pb"), "evEbitda": f.get("ev_ebitda"),
                 "roe": f.get("roe"), "roeDerived": bool(f.get("roe_derived")), "opm": f.get("op_margin"), "de": f.get("debt_to_equity"), "fcf": f.get("fcf_cr"), "ocf": f.get("ocf_cr"),
                 "insider": f.get("insider_pct"), "revG": f.get("rev_growth"), "earnG": f.get("earn_growth"), "industry": f.get("industry"),
                 "retrieved": f.get("retrieved_at"), "refreshFailed": bool(f.get("refresh_failed"))},
        "growth": {"rev3": g.get("rev_cagr"), "ni3": g.get("ni_cagr"), "years": g.get("years")},
        "components": s["components"], "missing": s["missing"], "smile": s["smile"], "mb": s["mb"],
        "zones": None if not z else {"ideal": list(z["ideal_buy_zone"]), "thesis_review": z["thesis_review_level"], "trading_stop": z["trading_stop_3atr"],
                                     "first_review": z["first_review_zone"], "distance_pct": z["distance_to_zone_pct"], "position": z["position"],
                                     "wait_to": z["wait_for_pullback_to"]},
        "scenarios": sc, "bear": None if not sc else sc["bear_12m_pct"], "invalidation": s["invalidation"],
        "entryReasons": s["entry_reasons"], "entryAvoid": s["entry_avoid"], "peers": peers.get(s["sector"]), "news": news,
        "series": [round(x, 2) for x in closes],
    }


def snapshot(ctx: dict) -> dict:
    cfg, r = ctx["cfg"], ctx["cfg"]["risk"]
    stocks = [stock_json(s, ctx["peers"], ctx["news_by_t"].get(s["ticker"], []), ctx["closes"].get(s["ticker"], [])) for s in ctx["stocks"]]
    dates = sorted({s["asof"] for s in stocks if s["asof"]})
    return _clean({
        "mode": ctx["mode"], "demo": ctx["mode"] != "real", "generated_at": ctx["generated_at"], "generated_date": ctx["today"].isoformat(),
        "price_date": dates[-1] if dates else None, "provider": ctx["provider"], "notes": ctx["health"]["notes"], "status": ctx["status"],
        "stocks": stocks, "items": ctx["items"], "changes": ctx["changes"], "bench": ctx["bench"], "market": ctx["market"],
        "news": ctx["news_market"], "history": ctx["history"], "integrations": ctx["integrations"], "disclosures": ctx["disclosures"],
        "universe_size": ctx.get("universe_size"), "holidays": ctx.get("holidays", []), "exit_pe": cfg["universe"]["exit_pe"],
        "rules": {"maxSingle": r["max_single_stock_pct"], "maxSector": r["max_sector_pct"], "maxSmall": r["max_smallcap_pct"],
                  "buyCostPct": cfg["costs"]["est_buy_cost_pct"], "sellCostPct": cfg["costs"].get("est_sell_cost_pct", 0.25),
                  "maxStocks": cfg["capital"]["max_stocks_per_month"], "staleAfterDays": cfg["data"]["stale_after_days"], "minPositions": 10, "minPerPosition": 4000, "concCapBuilding": 20}})


def render_dashboard(ctx: dict) -> str:
    tpl = (HERE / "dashboard_template.html").read_text(encoding="utf-8")
    parts = {k: (HERE / f).read_text(encoding="utf-8").replace("</", "<\\/") for k, f in
             (("__LOGIC__", "dashboard_logic.js"), ("__LEDGER__", "ledger.js"), ("__CLOUD__", "cloud.js"), ("__APP__", "app.js"))}
    data = json.dumps(snapshot(ctx), separators=(",", ":")).replace("</", "<\\/")
    out = tpl
    for k, v in parts.items():
        out = out.replace(k, v)
    return out.replace("__DATA__", data)
