"""Action centre items (research level). Portfolio-specific items are added in the browser (holdings never reach the repo)
or, for email only, by an optional private secret. Nothing here is invented: no change => 'No material changes detected'."""
from __future__ import annotations

CATEGORIES = {
    "critical_risk": "Critical risk requiring immediate review",
    "thesis_deterioration": "Investment thesis deterioration",
    "purchase_opportunity": "Potential purchase opportunity",
    "concentration": "Portfolio concentration warning",
    "reduction_review": "Potential reduction or exit review",
    "news": "Important news or corporate filing",
    "none": "No action required",
}
LEVEL = {"critical_risk": "CRITICAL", "thesis_deterioration": "HIGH", "concentration": "HIGH", "reduction_review": "HIGH",
         "purchase_opportunity": "MEDIUM", "news": "LOW", "none": "LOW"}
KIND_TO_CAT = {"critical": "critical_risk", "thesis_deterioration": "thesis_deterioration", "purchase_opportunity": "purchase_opportunity",
               "new_candidate": "purchase_opportunity", "improvement": "purchase_opportunity", "price_move": "news",
               "dropped": "thesis_deterioration", "data": "news"}


def link(t: str) -> str:
    return f"#/stock/{t}"


def build_items(changes: list[dict], stocks: list[dict], news_by_t: dict, risk: dict, provider: str, mode: str, have_prev: bool) -> list[dict]:
    by = {s["ticker"]: s for s in stocks}
    items, seen = [], set()
    for c in changes:
        cat = KIND_TO_CAT.get(c["kind"], "news")
        s = by.get(c["ticker"], {})
        lvl = LEVEL[cat]
        if c["kind"] in ("new_candidate", "improvement"):
            lvl = "LOW"
        conf = s.get("confidence", {})
        items.append(dict(id=f"{cat}:{c['ticker']}", category=cat, level=lvl, ticker=c["ticker"], name=c["name"], title=c["title"],
                          reason=c["detail"], changed=f"before: {c['before']} -> now: {c['after']}", new=True,
                          evidence=f"Computed from {provider} data; score components on the stock page.", source=provider, asof=c["asof"],
                          next_step=_next(cat), confidence=conf.get("label", "Low"), limits=conf.get("limits", []), link=link(c["ticker"])))
        seen.add(c["ticker"])
    # standing opportunities (current state, flagged as not new)
    for s in sorted(stocks, key=lambda x: -(x["entry"] or 0)):
        if s["status"] == "ACCUMULATE CANDIDATE" and s["ticker"] not in seen and len([i for i in items if i["new"] is False]) < 5:
            conf = s["confidence"]
            items.append(dict(id=f"purchase_opportunity:{s['ticker']}", category="purchase_opportunity", level="MEDIUM", ticker=s["ticker"], name=s["name"],
                              title=f"{s['name']}: inside its preferred entry range", reason="; ".join(s["why"][:2]),
                              changed="unchanged since the last analysis" if have_prev else "first analysis: no earlier run to compare", new=False,
                              evidence=f"Price {s['price']:.1f} within {s['zones']['ideal_buy_zone'][0]:.0f}-{s['zones']['ideal_buy_zone'][1]:.0f}; business score {s['research']}",
                              source=provider, asof=s["price_asof"], next_step=_next("purchase_opportunity"), confidence=conf["label"],
                              limits=conf["limits"], link=link(s["ticker"])))
    for t, ns in news_by_t.items():
        for n in ns:
            if n.get("risk") and t in by:
                items.append(dict(id=f"news:{t}", category="news", level="LOW", ticker=t, name=by[t]["name"], title=f"{by[t]['name']}: headline mentions a risk term",
                                  reason=n["title"], changed="new headline in the last 3 days", new=True,
                                  evidence=f"{n['source']}, {n['published']} (unverified headline; read the original)", source=n["source"], asof=n["published"],
                                  next_step="Open the source and check whether it is confirmed. Do not act on a headline alone.", confidence="Low",
                                  limits=["headline text only; not verified; may be old, wrong or duplicated"], link=n["url"] or link(t)))
                break
    if risk.get("material"):
        lvl_cat = "critical_risk" if risk["level"] == "high" else "news"
        items.append(dict(id="market_risk", category=lvl_cat, level=LEVEL[lvl_cat], ticker="-", name="Market risk", title="Market risk has risen",
                          reason=risk["reason"], changed="measured today", new=True, evidence="India VIX and Nifty 50 closes", source=provider, asof=None,
                          next_step="Consider staging purchases instead of investing in one go. Review position sizes.", confidence="Medium",
                          limits=["VIX thresholds are rule-of-thumb levels, not predictions"], link="#/markets"))
    if not [i for i in items if i["category"] != "none"]:
        items.append(dict(id="none", category="none", level="LOW", ticker="-", name="", title="No material changes detected", reason="Nothing crossed a threshold since the last successful analysis.",
                          changed="no differences", new=False, evidence="comparison with the previous run", source=provider, asof=None,
                          next_step="No action required.", confidence="n/a", limits=[], link="#/research"))
    if mode == "synthetic":
        for i in items:
            i["title"] = "[DEMO] " + i["title"]
    items.sort(key=lambda i: (["CRITICAL", "HIGH", "MEDIUM", "LOW"].index(i["level"]), not i["new"]))
    return items


def _next(cat: str) -> str:
    return {"critical_risk": "Review today: read the latest filings and your thesis before deciding anything.",
            "thesis_deterioration": "Re-read the latest results and news. Do not sell on price alone; decide whether the business weakened.",
            "purchase_opportunity": "Research the stock page. If you still like it, place a limit order inside the entry range.",
            "concentration": "Check weights on the Portfolio page and decide whether to trim.",
            "reduction_review": "Review the thesis; consider a partial reduction only if the reasons hold.",
            "news": "Read the source and judge whether it changes the thesis."}.get(cat, "")


def to_alerts(items: list[dict]) -> list[dict]:
    """Map items to the de-duplication format: same key + fingerprint => suppressed on later days."""
    out = []
    for i in items:
        if i["category"] == "none" or not i["new"]:
            continue
        out.append(dict(key=i["id"], level=i["level"], ticker=i["ticker"], title=i["title"], body=i["reason"],
                        fingerprint=(i["title"] + "|" + i["changed"])[:160], action=i["category"], item=i))
    return out
