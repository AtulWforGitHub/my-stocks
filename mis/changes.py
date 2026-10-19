"""What changed since the last SUCCESSFUL analysis. Only real differences become items; no activity is invented."""
from __future__ import annotations
import json
from pathlib import Path


def compact(stocks: list[dict]) -> dict:
    return {s["ticker"]: {"status": s["status"], "research": s["research"], "price": s["price"],
                          "pos": (s["zones"] or {}).get("position")} for s in stocks}


def load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return None


def diff(prev: dict | None, cur_stocks: list[dict], names: dict[str, str], asof: str, excluded: dict[str, str] | None = None) -> list[dict]:
    """Each change: kind, ticker, name, title, detail, materiality (0-100), before, after."""
    if not prev:
        return []
    out = []
    excluded = excluded or {}
    was_excluded = prev.get("excluded", {})
    cur = compact(cur_stocks)
    bad = {"AVOID", "DATA UNAVAILABLE"}
    for t, c in cur.items():
        p = prev["stocks"].get(t)
        nm = names.get(t, t)
        if p is None and t in was_excluded:
            continue                       # it was missing last time because of a data problem: not a new discovery
        if p is None:
            out.append(dict(kind="new_candidate", ticker=t, name=nm, materiality=30, title=f"{nm} entered the top-50 research list",
                            detail="New candidate under review. It is NOT part of your approved watchlist until you approve it.", before=None, after=c["status"]))
            continue
        if p["status"] != c["status"]:
            if c["status"] == "ACCUMULATE CANDIDATE":
                out.append(dict(kind="purchase_opportunity", ticker=t, name=nm, materiality=70, title=f"{nm}: now inside its preferred entry range",
                                detail=f"Status changed from {p['status']} to ACCUMULATE CANDIDATE.", before=p["status"], after=c["status"]))
            elif c["status"] == "AVOID":
                out.append(dict(kind="critical", ticker=t, name=nm, materiality=95, title=f"{nm}: marked AVOID",
                                detail="A governance red flag you recorded or a failed safety check applies.", before=p["status"], after=c["status"]))
            elif c["status"] == "DATA UNAVAILABLE":
                out.append(dict(kind="data", ticker=t, name=nm, materiality=35, title=f"{nm}: data became unavailable",
                                detail="Advice for this stock is paused until reliable data returns.", before=p["status"], after=c["status"]))
            elif p["status"] == "ACCUMULATE CANDIDATE":
                out.append(dict(kind="thesis_deterioration", ticker=t, name=nm, materiality=45, title=f"{nm}: no longer an accumulate candidate",
                                detail=f"Moved from ACCUMULATE CANDIDATE to {c['status']} (entry conditions or evidence changed).", before=p["status"], after=c["status"]))
        if p.get("research") is not None and c["research"] is not None and p["status"] not in bad:
            d = c["research"] - p["research"]
            if d <= -6:
                out.append(dict(kind="thesis_deterioration", ticker=t, name=nm, materiality=55, title=f"{nm}: business score fell {abs(d):.1f} points",
                                detail="Fundamental inputs changed. Re-read the latest results before adding.", before=p["research"], after=c["research"]))
            elif d >= 6:
                out.append(dict(kind="improvement", ticker=t, name=nm, materiality=30, title=f"{nm}: business score rose {d:.1f} points",
                                detail="Inputs improved; research it before acting.", before=p["research"], after=c["research"]))
        if p.get("price") and c["price"]:
            mv = (c["price"] / p["price"] - 1) * 100
            if abs(mv) >= 8:
                out.append(dict(kind="price_move", ticker=t, name=nm, materiality=45, title=f"{nm}: moved {mv:+.1f}% since the last analysis",
                                detail="Check for news or results. A price move alone is not a reason to act.", before=p["price"], after=c["price"]))
    for t in prev["stocks"]:
        if t not in cur and excluded.get(t) == "red_flag":
            out.append(dict(kind="critical", ticker=t, name=names.get(t, t), materiality=95, title=f"{names.get(t, t)}: you recorded a governance red flag",
                            detail="It was removed from the research list. If you own it, review the exit decision.", before=prev["stocks"][t]["status"], after="AVOID"))
        elif t not in cur and excluded.get(t) in ("data", "illiquid"):
            why = "no usable market or fundamental data today" if excluded[t] == "data" else "trading volume fell below the liquidity minimum"
            out.append(dict(kind="data", ticker=t, name=names.get(t, t), materiality=35, title=f"{names.get(t, t)}: not analysed today ({why})",
                            detail="This is a data or liquidity problem, not evidence about the business. Advice for it is paused.", before=prev["stocks"][t]["status"], after=None))
        elif t not in cur:
            out.append(dict(kind="dropped", ticker=t, name=names.get(t, t), materiality=25, title=f"{names.get(t, t)} left the top-50 list",
                            detail="It no longer ranks. If you own it, review whether the thesis is intact.", before=prev["stocks"][t]["status"], after=None))
    out.sort(key=lambda x: -x["materiality"])
    for o in out:
        o["asof"] = asof
    return out
