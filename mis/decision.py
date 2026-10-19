"""Decision engine: turns scores + technicals into a status, entry zones, scenarios and invalidation conditions.
Everything here is decision SUPPORT. Scenario numbers are mechanical illustrations, not forecasts."""
from __future__ import annotations


def classify(research: dict, entry: dict, fresh: dict, gov_status: str, tech: dict, zones: dict | None) -> tuple[str, list[str]]:
    """Status must agree with the entry range AND the long-term trend: ACCUMULATE CANDIDATE needs the price inside the
    preferred range and not below the 200-day average."""
    why: list[str] = []
    if fresh["status"] != "fresh":
        return "DATA UNAVAILABLE", [f"price data {fresh['status']} (as of {fresh['asof']})"]
    if tech.get("anomaly"):
        return "DATA UNAVAILABLE", ["price check failed: " + tech["anomaly"]]
    if research["total"] is None:
        return "DATA UNAVAILABLE", [f"insufficient data: only {research['data_confidence_pct']}% of score inputs available (research required)"]
    if gov_status == "red_flag":
        return "AVOID", ["manual governance red flag overrides any score"]
    tot, conf = research["total"], research["data_confidence_pct"]
    if conf < 65:
        return "WATCH", [f"research required: only {conf}% of inputs available, so no buy candidacy"]
    if tech.get("ret_1y_pct") and tech["ret_1y_pct"] > 200:
        return "WATCH", [f"up {tech['ret_1y_pct']:.0f}% in a year: parabolic, wait for consolidation"]
    pos = (zones or {}).get("position")
    d200 = tech.get("dma200")
    below200 = bool(d200 and tech["last"] < d200)
    if tot >= 68 and (entry["score"] or 0) >= 55:
        if below200:
            return "WATCH", [f"strong business score ({tot}) but the price is below its 200-day average: wait for the trend to repair"]
        if pos == "in_range":
            return "ACCUMULATE CANDIDATE", [f"research score {tot}, entry score {entry['score']}, price inside preferred entry range"]
        if pos == "below":
            return "WATCH", [f"strong business score ({tot}) and the long-term trend is intact (above the 200-day average), but the price has slipped below its 50/100-day support range: wait for it to stabilise before buying"]
        hi = zones["ideal_buy_zone"][1] if zones else None
        return "WATCH", [f"strong business score ({tot}) but price is above the preferred entry range: WAIT for a pullback to about {hi:,.1f}"]
    if tot >= 60:
        return "WATCH", [f"business score {tot}, but entry score {entry['score']}: wait for a better setup"] + entry["avoid"]
    return "RESEARCH ONLY", [f"score {tot} below the accumulation threshold"]


def entry_zones(tech: dict) -> dict | None:
    if not tech.get("ok"):
        return None
    last = tech["last"]; d50, d100, d200 = tech.get("dma50"), tech.get("dma100"), tech.get("dma200")
    atr = tech.get("atr") or last * 0.02
    anchor = d50 or d100 or last
    # In an uptrend (100-DMA under the 50-DMA) a pullback toward the 100-DMA support is part of the preferred range;
    # otherwise the range is simply around the 50-DMA.
    low_anchor = min(x for x in (d50, d100) if x) if (d50 and d100) else anchor
    ideal = (round(low_anchor * 0.98, 2), round(anchor * 1.02, 2))
    # inside the range, with the same small tolerance everywhere (python and dashboard): 3% under the bottom, 1% over the top
    in_ideal = ideal[0] * 0.97 <= last <= ideal[1] * 1.01
    position = "in_range" if in_ideal else ("above" if last > ideal[1] else "below")
    trading_stop = round(last - 3 * atr, 2)                       # trading risk-control (volatility based)
    # thesis re-check level must sit BELOW the entry range, otherwise a fresh purchase would already be "under water"
    thesis_review = round(min((d200 or last * 0.85) * 0.95, ideal[0] * 0.95), 2)
    return {"ideal_buy_zone": ideal, "price_in_ideal_zone": in_ideal, "position": position,
            "distance_to_zone_pct": round((last / ideal[1] - 1) * 100, 1) if position == "above" else (round((last / ideal[0] - 1) * 100, 1) if position == "below" else 0.0),
            "wait_for_pullback_to": None if last <= ideal[1] else ideal[1],
            "trading_stop_3atr": trading_stop, "thesis_review_level": thesis_review,
            "first_review_zone": round(tech["resistance"], 2) if tech.get("resistance") else None,
            "note": "stop = short-term risk control; thesis_review_level = reassess business, do not sell mechanically"}


def scenarios(fund: dict, tech: dict) -> dict | None:
    """Mechanical 12-month illustration: constant P/E, earnings growth clamped to [0, 20]% (base), x1.5 (bull);
    bear = repeat of the worst 1-year drawdown seen (min 20%). NOT a forecast."""
    if not tech.get("ok"):
        return None
    last = tech["last"]
    g = fund.get("earn_growth") if fund.get("available") else None
    g = 0.08 if g is None else max(0.0, min(0.20, g))
    bear = -max(abs(tech.get("drawdown_1y_pct", -20)), 20)
    return {"base_12m_pct": round(g * 100, 1), "bull_12m_pct": round(min(g * 1.5, 0.30) * 100, 1),
            "bear_12m_pct": round(bear, 1),
            "base_price": round(last * (1 + g), 2), "bear_price": round(last * (1 + bear / 100), 2),
            "assumption": "constant P/E; earnings growth proxy " + ("unavailable -> 8% placeholder" if fund.get("earn_growth") is None else "from latest reported YoY")}


def invalidation(meta: dict, fund: dict) -> list[str]:
    inv = ["Governance event: auditor resignation/qualification, fraud allegation, sharp pledge rise",
           "ROE/ROCE declining for several consecutive quarters without a clear reason",
           "Loss of pricing power or competitive position in " + meta["sector"]]
    if meta["sector"] != "Financials":
        inv.append("Debt rising sharply without matching growth; free cash flow persistently negative")
    else:
        inv.append("Asset-quality deterioration (rising NPAs/credit costs) beyond sector trend")
    return inv


def holding_status(pos: dict, tech: dict, rec_status: str, gov_status: str, cfg: dict, building: bool = False) -> tuple[str, list[str]]:
    """Daily keep/buy/reduce/sell review for an existing holding. Distinguishes price noise from deterioration."""
    why = []
    r = cfg["risk"]
    if rec_status == "DATA UNAVAILABLE":
        return "DATA UNAVAILABLE", ["no reliable price data today"]
    if gov_status == "red_flag":
        return "EXIT REVIEW", ["manual governance red flag recorded"]
    w = pos.get("weight_pct") or 0
    if w > r["oversize_alert_pct"] and not building:
        return "REDUCE CANDIDATE", [f"weight {w:.1f}% > {r['oversize_alert_pct']}% concentration alert (rule-based, not a view on the business)"]
    if tech.get("ok"):
        if tech["from_high_pct"] <= -r["fall_from_high_alert_pct"]:
            why.append(f"{tech['from_high_pct']:.0f}% below 52w high")
            if tech["dma200"] and tech["last"] < tech["dma200"]:
                why.append("below 200-DMA: technical breakdown - check results/news for a fundamental cause before acting")
                return "WATCH", why
        if tech["dma200"] and tech["last"] > tech["dma200"] and (tech.get("ext_200_pct") or 0) > 40 and w > r["max_single_stock_pct"] and not building:
            return "REDUCE CANDIDATE", ["stretched above 200-DMA and overweight"]
    if rec_status == "ACCUMULATE CANDIDATE" and w < r["max_single_stock_pct"] * 0.8:
        return "ACCUMULATE CANDIDATE", ["thesis intact, entry conditions favourable, room under position limit"]
    return "HOLD", why or ["no material change; price moves alone are not a reason to sell"]
