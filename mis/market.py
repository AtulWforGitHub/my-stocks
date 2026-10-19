"""Cross-asset and market-risk facts. Trend FACTS (price vs 200-DMA, 1m change, RSI) and conditions; no price forecasts.
Global prices are not what an Indian investor pays (INR, duties, ETF tracking error)."""
from __future__ import annotations
from .indicators import sma, rsi

# name: (yahoo ticker, how an Indian investor can hold it, enabled-by config key or None)
ASSETS = {
    "Gold": ("GC=F", "Gold ETF (for example GOLDBEES) or Sovereign Gold Bonds on the secondary market", None),
    "Silver": ("SI=F", "Silver ETF (for example SILVERBEES)", None),
    "Crude oil": ("CL=F", "No simple retail route (mostly MCX futures: not recommended here)", None),
    "USD/INR": ("INR=X", "Currency exposure is derivatives-based for retail: not recommended here", None),
    "EUR/INR": ("EURINR=X", "Derivatives-based for retail: not recommended here", None),
    "Bitcoin": ("BTC-USD", "Exchange-hosted crypto: very volatile, special tax/TDS rules, platform risk", "crypto"),
    "Ethereum": ("ETH-USD", "Exchange-hosted crypto: very volatile, special tax/TDS rules, platform risk", "crypto"),
}
MACRO = {"Nifty 50": "^NSEI", "India VIX": "^INDIAVIX", "US 10Y yield": "^TNX", "Dollar index": "DX-Y.NYB", "Brent crude": "BZ=F"}


def facts(df, name: str) -> dict:
    if df is None or len(df) < 30:
        return {"name": name, "ok": False}
    c = df["Close"].astype(float)
    last = float(c.iloc[-1])
    d200 = sma(c, 200).iloc[-1] if len(c) >= 200 else None
    d200 = None if d200 is None or d200 != d200 else float(d200)
    r = rsi(c).iloc[-1]
    trend = "n/a" if d200 is None else ("above 200-DMA" if last > d200 else "below 200-DMA")
    return {"name": name, "ok": True, "last": last, "asof": str(df.index[-1])[:10],
            "d1": float((c.iloc[-1] / c.iloc[-2] - 1) * 100), "m1": float((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) > 22 else None,
            "rsi": None if r != r else float(r), "trend": trend, "dma200": d200}


def market_risk(vix: dict | None, nifty: dict | None) -> dict:
    """Opinion thresholds (labelled): VIX < 15 calm, 15-20 normal, 20-25 elevated, > 25 high."""
    if not vix or not vix.get("ok"):
        return {"level": "unknown", "reason": "India VIX unavailable", "material": False}
    v = vix["last"]; lvl = "calm" if v < 15 else "normal" if v < 20 else "elevated" if v < 25 else "high"
    jump = vix["d1"] > 15
    why = f"India VIX {v:.1f} ({lvl}); one-day change {vix['d1']:+.1f}%"
    if nifty and nifty.get("ok") and nifty["d1"] <= -2:
        why += f"; Nifty 50 fell {abs(nifty['d1']):.1f}% today"
    return {"level": lvl, "reason": why, "material": lvl in ("elevated", "high") or jump or bool(nifty and nifty.get("ok") and nifty["d1"] <= -2)}
