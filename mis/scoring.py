"""Transparent, configurable 0-100 research score. Every component shows its inputs and what was missing.
A high score is NOT a probability of a multibagger outcome."""
from __future__ import annotations


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _lin(x, lo, hi):
    """Map x from [lo,hi] to [0,1]."""
    return _clamp((x - lo) / (hi - lo))


def _comp(frac_list, weight, missing):
    """Average available fractions (0-1); missing items are listed and pull confidence down, not score up."""
    vals = [f for f in frac_list if f is not None]
    if not vals:       # NOT scored: excluded from the total instead of being replaced by a neutral guess
        return {"points": 0.0, "max": weight, "data": False, "coverage": 0.0, "missing": missing, "note": "Insufficient data - excluded from the score"}
    return {"points": round(weight * sum(vals) / len(vals), 2), "max": weight, "data": True, "coverage": len(vals) / len(frac_list), "missing": missing}


def mb_math(fund: dict, exit_pe: float = 25.0) -> dict | None:
    """What earnings growth is REQUIRED for a multibagger outcome, if the P/E settles at exit_pe?
    required CAGR = (multiple * pe_now / exit_pe) ** (1/years) - 1. Ignores dilution and dividends. Not a forecast."""
    pe = fund.get("trailing_pe") if fund.get("available") else None
    if not pe or pe <= 0:
        return None
    return {"x10_15y": round(((10 * pe / exit_pe) ** (1 / 15) - 1) * 100, 1),
            "x5_10y": round(((5 * pe / exit_pe) ** (1 / 10) - 1) * 100, 1), "exit_pe": exit_pe}


def score_stock(meta: dict, fund: dict, tech: dict, governance: dict, weights: dict, growth: dict | None = None,
                exit_pe: float = 25.0) -> dict:
    f = fund if fund.get("available") else {}
    growth = growth or {}
    miss: list[str] = []

    def need(key, label):
        if f.get(key) is None:
            miss.append(label)
            return None
        return f[key]

    roe = need("roe", "ROE"); opm = need("op_margin", "operating margin")
    rg = f.get("rev_growth"); eg = f.get("earn_growth")
    rc, nc = growth.get("rev_cagr"), growth.get("ni_cagr")
    if rc is None and nc is None and rg is None and eg is None:
        miss.append("growth")
    de = need("debt_to_equity", "debt/equity"); fcf = need("fcf_cr", "free cash flow"); ocf = f.get("ocf_cr")
    pe = f.get("forward_pe") or f.get("trailing_pe")
    if pe is None:
        miss.append("P/E")
    is_fin = f.get("is_financial", False)
    mc = f.get("market_cap_cr")

    quality = _comp([None if roe is None else _lin(roe, 0.08, 0.28),
                     None if (opm is None or is_fin) else _lin(opm, 0.08, 0.30)], weights["business_quality"],
                    [m for m in miss if m in ("ROE", "operating margin")])
    if f.get("roe_derived"):
        quality["note"] = "ROE derived as EPS / book value (the provider supplies none)"
    # growth: prefer multi-year CAGR (less noisy); latest-year YoY is secondary
    g_items = [None if rc is None else _lin(rc, 0.05, 0.30), None if nc is None else _lin(nc, 0.05, 0.35),
               None if rg is None else _lin(rg, 0.0, 0.25), None if eg is None else _lin(eg, 0.0, 0.30)]
    growth_c = _comp(g_items, weights["growth"], ["growth"] if "growth" in miss else [])
    growth_c["note"] = (f"{growth.get('years', 0)}-yr CAGR: revenue {None if rc is None else round(rc*100,1)}%, profit {None if nc is None else round(nc*100,1)}%"
                        if (rc is not None or nc is not None) else "multi-year CAGR unavailable; using latest YoY only")
    fin = _comp([None if (de is None or is_fin) else 1 - _lin(de, 0.1, 1.5),
                 None if fcf is None else (1.0 if fcf > 0 else 0.0),
                 None if (ocf is None or fcf is None) else (1.0 if ocf > 0 else 0.0)],
                weights["financial_strength"], [m for m in miss if m in ("debt/equity", "free cash flow")])

    # S + E of SMILE: still small relative to the opportunity, and the growth required for a multibagger is plausible
    mb = mb_math(f, exit_pe) if f else None
    s_frac = None if mc is None else (1.0 if 3000 <= mc <= 25000 else 0.7 if 1500 <= mc < 3000 or 25000 < mc <= 50000 else 0.35)
    e_frac = None if mb is None else (1.0 if mb["x10_15y"] <= 18 else 0.7 if mb["x10_15y"] <= 24 else 0.4 if mb["x10_15y"] <= 32 else 0.15)
    size = _comp([s_frac, e_frac], weights["size_runway"], [] if (s_frac is not None and e_frac is not None) else ["market cap / P/E"])
    size["note"] = ("market cap Rs %s cr; needs %s%%/yr earnings growth for 10x in 15 yrs if P/E settles at %s" %
                    ("n/a" if mc is None else f"{mc:,.0f}", "n/a" if mb is None else mb["x10_15y"], exit_pe))

    gstat = governance.get("status", "unreviewed")
    ins = f.get("insider_pct")
    if gstat == "unreviewed":
        gfrac = 0.5 if ins is None else (0.7 if ins >= 0.50 else 0.55 if ins >= 0.35 else 0.35)
        gnote = "no manual review; promoter-holding proxy only (pledging not available)"
    else:
        gfrac = {"ok": 1.0, "watch": 0.5, "red_flag": 0.0}.get(gstat, 0.5)
        gnote = governance.get("note", "")
    gov = {"points": round(weights["governance"] * gfrac, 2), "max": weights["governance"], "data": gstat != "unreviewed" or ins is not None,
           "coverage": 1.0 if (gstat != "unreviewed" or ins is not None) else 0.0,
           "missing": ["manual governance review (pledging/auditor/related-party not auto-available)"] if gstat == "unreviewed" else [],
           "status": gstat, "note": gnote}

    val_frac = None
    if pe is not None and pe > 0:
        base = 1 - _lin(pe, 15, 70)                       # cheaper multiple scores higher
        gs = sorted(g for g in (rc, nc, eg) if g is not None and g > 0)
        if gs:
            g_mid = gs[len(gs) // 2] if len(gs) % 2 else (gs[len(gs) // 2 - 1] + gs[len(gs) // 2]) / 2   # median: one noisy quarter cannot dominate
            peg = pe / (min(max(g_mid, 0.05), 0.35) * 100)
            peg_frac = _clamp(1 - (peg - 0.8) / 2.2)       # PEG <= 0.8 -> 1.0, PEG >= 3.0 -> 0.0
        else:
            peg_frac = 0.0                                   # no positive growth evidence: a multiple cannot be justified by growth
        val_frac = _clamp(0.5 * base + 0.5 * peg_frac)
    elif pe is not None and pe <= 0:
        val_frac = 0.0
    val = _comp([val_frac], weights["valuation"], [] if val_frac is not None else ["P/E"])
    val["note"] = "heuristic: P/E vs growth. No historical-range or peer valuation yet (data limitation)."

    if tech.get("ok"):
        t_items = [1.0 if (tech["dma200"] and tech["last"] > tech["dma200"]) else 0.0 if tech["dma200"] else None,
                   1.0 if (tech["dma50"] and tech["dma200"] and tech["dma50"] > tech["dma200"]) else 0.0 if tech["dma50"] else None,
                   None if tech["rs_6m_vs_nifty"] is None else _lin(tech["rs_6m_vs_nifty"], -0.15, 0.20)]
        techc = _comp(t_items, weights["technical"], [] if tech["rs_6m_vs_nifty"] is not None else ["relative strength"])
    else:
        techc = _comp([], weights["technical"], ["price history"])

    tail = {"points": round(weights["tailwinds"] * meta["tailwind"] / 5, 2), "max": weights["tailwinds"], "data": True,
            "missing": [], "note": "analyst opinion by industry (mis/discovery.py, editable)"}

    comps = {"growth": growth_c, "business_quality": quality, "financial_strength": fin, "size_runway": size,
             "governance": gov, "valuation": val, "technical": techc, "tailwinds": tail}
    avail = sum(c["max"] for c in comps.values() if c["data"])
    # confidence = how much of every component's INPUTS exist (a component with 1 of 3 inputs counts as one third, not as 'available')
    confidence_pct = round(100 * sum(c["max"] * c.get("coverage", 1.0 if c["data"] else 0.0) for c in comps.values()) / sum(c["max"] for c in comps.values()))
    # score is normalised over the evidence we actually have; below 50% coverage there is no score at all
    total = round(100 * sum(c["points"] for c in comps.values() if c["data"]) / avail, 1) if confidence_pct >= 50 else None
    smile = {"S": None if mc is None else 1500 <= mc <= 50000,
             "M": None if gstat == "unreviewed" and ins is None else (gstat == "ok" or (gstat == "unreviewed" and (ins or 0) >= 0.40)),
             "I": meta["tailwind"] >= 3,
             "L": None if roe is None else (roe >= 0.15 and (opm is None or opm >= 0.10 or is_fin)),
             "E": None if mb is None else mb["x10_15y"] <= 24}
    return {"total": total, "components": comps, "data_confidence_pct": confidence_pct, "missing": sorted(set(miss)),
            "governance_status": gstat, "smile": smile, "mb": mb,
            "confidence": confidence(confidence_pct, gstat)}


def confidence(pct: int, gov_status: str) -> dict:
    """Never 'High' while governance is unreviewed. Limitations are always listed."""
    limits = ["valuation is a P/E-versus-growth heuristic (no historical-range or peer model)",
              "return on capital, pledging, auditor and related-party data are not available from the provider"]
    if gov_status == "unreviewed":
        limits.insert(0, "governance NOT reviewed by you (promoter-holding proxy only)")
    if pct >= 85 and gov_status in ("ok",):
        label = "High"
    elif pct >= 65:
        label = "Medium"
    else:
        label = "Low"
    if gov_status == "unreviewed" and label == "High":
        label = "Medium"
    return {"label": label, "pct": pct, "limits": limits}


def entry_setup_score(tech: dict) -> dict:
    """0-100 'is the CURRENT price a sensible entry' - separate from business quality."""
    if not tech.get("ok"):
        return {"score": None, "reasons": ["price history unavailable"], "avoid": []}
    pts, reasons, avoid = 0.0, [], []
    last, d50, d100, d200 = tech["last"], tech.get("dma50"), tech.get("dma100"), tech.get("dma200")
    if d200 and last > d200 and tech.get("dma200_rising"):
        pts += 25; reasons.append("above a rising 200-DMA")
    elif d200 and last > d200:
        pts += 12; reasons.append("above 200-DMA (not clearly rising)")
    else:
        avoid.append("below 200-DMA")
    for d, n in ((d50, 50), (d100, 100)):
        if d and abs(last / d - 1) <= 0.04 and last >= d * 0.98:
            pts += 15; reasons.append(f"consolidating near {n}-DMA support"); break
    rs = tech.get("rs_6m_vs_nifty")
    if rs is not None and rs > 0:
        pts += 15; reasons.append(f"outperforming Nifty 50 by {rs*100:.0f}pp over 6m")
    r = tech.get("rsi")
    if r is not None:
        if 40 <= r <= 60:
            pts += 15; reasons.append(f"RSI neutral ({r:.0f})")
        elif r < 40:
            pts += 8; reasons.append(f"RSI weak/oversold ({r:.0f})")
        elif r > 72:
            avoid.append(f"RSI overbought ({r:.0f})")
        else:
            pts += 7
    if tech.get("resistance") and (tech["resistance"] / last - 1) >= 0.07:
        pts += 10; reasons.append("room (>7%) before recent 60-day high")
    ext = tech.get("ext_200_pct")
    if ext is not None and ext > 28:
        avoid.append(f"{ext:.0f}% above 200-DMA without consolidation (stretched)"); pts -= 20
    if tech.get("ret_1y_pct") is not None and tech["ret_1y_pct"] > 200:
        avoid.append(f"up {tech['ret_1y_pct']:.0f}% in a year (parabolic, do not chase)"); pts -= 25
    if tech.get("from_high_pct", 0) < -25:
        avoid.append(f"{tech['from_high_pct']:.0f}% below 52w high - check for fundamental cause")
    if tech.get("macd_hist") is not None and tech["macd_hist"] > 0:
        pts += 10; reasons.append("MACD histogram positive")
    return {"score": round(max(0.0, min(100.0, pts)), 1), "reasons": reasons, "avoid": avoid}
