"""Pure-pandas technical indicators. Input: pandas Series/DataFrame with columns Close/High/Low/Volume."""
from __future__ import annotations
import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0)


def macd(s: pd.Series, fast=12, slow=26, signal=9):
    line = ema(s, fast) - ema(s, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def max_drawdown(s: pd.Series) -> float:
    """Return max drawdown as a negative fraction."""
    peak = s.cummax()
    return float((s / peak - 1).min())


def relative_strength(stock: pd.Series, bench: pd.Series, lookback: int = 126) -> float | None:
    """Stock return minus benchmark return over `lookback` trading days (aligned by date)."""
    j = pd.concat([stock, bench], axis=1, join="inner").dropna()
    if len(j) <= lookback:
        return None
    r = j.iloc[-1] / j.iloc[-1 - lookback] - 1
    return float(r.iloc[0] - r.iloc[1])


def support_resistance(df: pd.DataFrame, window: int = 60):
    """Simple zones: lowest low / highest high of the recent window (not predictions)."""
    w = df.tail(window)
    return float(w["Low"].min()), float(w["High"].max())


def technical_snapshot(df: pd.DataFrame, bench_close: pd.Series | None = None) -> dict:
    """All technical facts for one stock. Missing pieces are None, never guessed."""
    out: dict = {"ok": False}
    if df is None or len(df) < 60:
        return out
    c = df["Close"].astype(float)
    last = float(c.iloc[-1])
    snap = {"ok": True, "last": last, "asof": str(df.index[-1])[:10]}
    for n in (20, 50, 100, 200):
        v = sma(c, n).iloc[-1]
        snap[f"dma{n}"] = None if pd.isna(v) else float(v)
    r = rsi(c).iloc[-1]
    snap["rsi"] = None if pd.isna(r) else float(r)
    m, sg, h = macd(c)
    snap["macd_hist"] = None if pd.isna(h.iloc[-1]) else float(h.iloc[-1])
    a = atr(df).iloc[-1]
    snap["atr"] = None if pd.isna(a) else float(a)
    snap["atr_pct"] = None if snap["atr"] is None else snap["atr"] / last * 100
    hi = float(c.tail(252).max()); lo = float(c.tail(252).min())
    snap["high_52w"], snap["low_52w"] = hi, lo
    moves = c.pct_change().tail(5).abs()
    snap["max_move_5d_pct"] = float(moves.max() * 100) if len(moves.dropna()) else 0.0
    snap["anomaly"] = None
    if last <= 0 or pd.isna(last):
        snap["anomaly"] = "non-positive price"
    elif snap["max_move_5d_pct"] > 35:
        snap["anomaly"] = f"a {snap['max_move_5d_pct']:.0f}% one-day move in the last 5 sessions (possible split/bonus/data error: verify)"
    snap["ret_1d_pct"] = float((c.iloc[-1] / c.iloc[-2] - 1) * 100) if len(c) > 1 else None
    snap["ret_1m_pct"] = float((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) > 22 else None
    snap["ret_1y_pct"] = (last / float(c.iloc[-253]) - 1) * 100 if len(c) > 253 else None
    snap["from_high_pct"] = (last / hi - 1) * 100
    snap["above_low_pct"] = (last / lo - 1) * 100
    snap["ext_200_pct"] = None if snap["dma200"] is None else (last / snap["dma200"] - 1) * 100
    snap["dma200_rising"] = None
    d200 = sma(c, 200)
    if d200.dropna().shape[0] > 21:
        snap["dma200_rising"] = bool(d200.iloc[-1] > d200.iloc[-21])
    snap["support"], snap["resistance"] = support_resistance(df)
    if "Volume" in df and df["Volume"].tail(50).sum() > 0:
        v20 = float(df["Volume"].tail(20).mean()); v50 = float(df["Volume"].tail(50).mean())
        snap["vol_ratio_20_50"] = v20 / v50 if v50 else None
        snap["avg_traded_value_cr"] = float((df["Volume"].tail(50) * c.tail(50)).mean() / 1e7)
    else:
        snap["vol_ratio_20_50"] = None; snap["avg_traded_value_cr"] = None
    snap["rs_6m_vs_nifty"] = relative_strength(c, bench_close, 126) if bench_close is not None else None
    ret = c.pct_change().dropna()
    snap["vol_ann_pct"] = float(ret.tail(252).std() * np.sqrt(252) * 100)
    snap["max_gap_1y_pct"] = float((df["Open"].tail(252) / df["Close"].shift(1).tail(252) - 1).abs().max() * 100) if "Open" in df else None
    snap["drawdown_1y_pct"] = max_drawdown(c.tail(252)) * 100
    return snap
