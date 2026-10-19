"""Data layer. yfinance is a PROTOTYPING source (unofficial, subject to Yahoo terms, can break).
Every dataset carries source + retrieval timestamp + market-data date. Failures => None (never fabricated)."""
from __future__ import annotations
import time
import datetime as dt
import logging
import pandas as pd

log = logging.getLogger("mis.data")
FUND_SCHEMA = 2     # 2: ROE derived from EPS/book value when the provider has none


class PriceProvider:
    """Interface. Swap this class for a licensed feed without touching the rest of the app."""
    name = "base"
    failed = 0
    rate_limited = 0
    tripped = False
    missing_history: list = []

    def history(self, tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
        raise NotImplementedError

    def info(self, ticker: str) -> dict | None:
        raise NotImplementedError

    def financials(self, ticker: str) -> dict | None:
        """Annual revenue and net income, newest first: {"rev": [...], "ni": [...]}"""
        return None


class YahooProvider(PriceProvider):
    name = "yfinance (Yahoo Finance, unofficial; end-of-day/delayed)"

    def __init__(self, pause: float = 1.0, retries: int = 2, rl_backoff: float = 8.0, trip_after: int = 4, yf_module=None):
        if yf_module is None:
            import yfinance as yf_module  # imported lazily so tests run without it
        self.yf = yf_module
        self.pause, self.retries = pause, retries
        self.rl_backoff, self.trip_after = rl_backoff, trip_after
        self.failed = 0                                   # requests that failed after all retries
        self.rate_limited = 0                             # how many times Yahoo said "too many requests"
        self.consecutive_rl = 0
        self.tripped = False                              # circuit breaker: once open, no more requests this run
        self.missing_history = []                         # tickers asked for but not returned (reported, never silent)

    @staticmethod
    def _is_rate_limit(e: Exception) -> bool:
        m = (type(e).__name__ + " " + str(e)).lower()
        return "ratelimit" in m or "too many requests" in m or "429" in m

    def _retry(self, fn):
        if self.tripped:
            return None
        for attempt in range(self.retries + 1):
            try:
                r = fn()
                self.consecutive_rl = 0
                return r
            except Exception as e:  # noqa: BLE001
                if self._is_rate_limit(e):
                    self.rate_limited += 1; self.consecutive_rl += 1
                    log.warning("Yahoo rate limit (%d in a row)", self.consecutive_rl)
                    if self.consecutive_rl >= self.trip_after:
                        self.tripped = True
                        log.error("Yahoo keeps refusing requests from this connection: stopping all further requests in this run.")
                        self.failed += 1
                        return None
                    time.sleep(self.rl_backoff * (attempt + 1))     # back off instead of hammering
                    continue
                log.warning("data call failed (%s) attempt %d", type(e).__name__, attempt + 1)
                time.sleep(self.pause * (attempt + 1))
        self.failed += 1
        return None

    @staticmethod
    def _extract(df: pd.DataFrame, t: str, n_requested: int):
        """Pull one ticker out of a yfinance download, whatever the column layout (flat, ticker-first or price-first MultiIndex)."""
        cols = df.columns
        if isinstance(cols, pd.MultiIndex):
            if t in set(cols.get_level_values(0)):
                return df[t]
            if t in set(cols.get_level_values(1)):
                return df.xs(t, axis=1, level=1)
            return None
        if n_requested == 1:
            return df
        return df[t] if t in cols else None

    def _clean(self, sub):
        if sub is None or "Close" not in getattr(sub, "columns", []):
            return None
        sub = sub.dropna(subset=["Close"])
        if not len(sub):
            return None
        sub = sub.copy()
        sub.index = pd.to_datetime(sub.index).tz_localize(None)
        return sub

    def history(self, tickers, period="5y"):
        out: dict[str, pd.DataFrame] = {}
        self.missing_history = []
        for i in range(0, len(tickers), 10):          # small batches = gentler on the source
            chunk = tickers[i:i + 10]
            df = self._retry(lambda: self.yf.download(chunk, period=period, auto_adjust=True, group_by="ticker",
                                                      progress=False, threads=False))
            time.sleep(self.pause)
            if df is None or len(df) == 0:
                continue
            for t in chunk:
                try:
                    sub = self._clean(self._extract(df, t, len(chunk)))
                except Exception:  # noqa: BLE001
                    sub = None
                if sub is not None:
                    out[t] = sub
        # second chance, one by one, for anything the batch lost (never drop a ticker silently)
        for t in [t for t in tickers if t not in out][:15]:
            if self.tripped:
                break
            df = self._retry(lambda: self.yf.Ticker(t).history(period=period, auto_adjust=True))
            time.sleep(self.pause)
            sub = self._clean(df) if df is not None else None
            if sub is not None:
                out[t] = sub
        self.missing_history = [t for t in tickers if t not in out]
        if self.missing_history:
            log.warning("no price history returned for %d ticker(s): %s", len(self.missing_history), ", ".join(self.missing_history[:8]))
        return out

    def info(self, ticker):
        def _go():
            return self.yf.Ticker(ticker).info
        r = self._retry(_go)
        time.sleep(self.pause)
        return r if isinstance(r, dict) and r else None

    def financials(self, ticker):
        def _go():
            fin = self.yf.Ticker(ticker).financials
            if fin is None or fin.empty:
                return None
            def row(name):
                for k in fin.index:
                    if str(k).strip().lower() == name:
                        return [float(v) for v in fin.loc[k].dropna().tolist()]   # columns are newest first
                return []
            return {"rev": row("total revenue"), "ni": row("net income")}
        r = self._retry(_go)
        time.sleep(self.pause)
        return r


def freshness(df: pd.DataFrame | None, stale_after_days: int, today: dt.date | None = None) -> dict:
    """Label price data age. Used to block new-buy recommendations on stale data."""
    today = today or dt.date.today()
    if df is None or len(df) == 0:
        return {"status": "unavailable", "asof": None, "age_days": None}
    asof = df.index[-1].date()
    age = (today - asof).days
    return {"status": "stale" if age > stale_after_days else "fresh", "asof": str(asof), "age_days": age}


def extract_fundamentals(info: dict | None) -> dict:
    """Map yfinance .info to the fields we use. Missing => None. Units noted."""
    if not info:
        return {"available": False}
    g = info.get
    de = g("debtToEquity")  # Yahoo reports this in percent (e.g. 45 = 0.45x)
    roe, roe_derived = g("returnOnEquity"), False
    if roe is None:                                   # Yahoo often omits it for Indian companies: derive it, and say so
        eps, bv, pb, pe = g("trailingEps"), g("bookValue"), g("priceToBook"), g("trailingPE")
        if eps is not None and bv and bv > 0:
            roe, roe_derived = eps / bv, True
        elif pb and pe and pe > 0:
            roe, roe_derived = pb / pe, True
        if roe is not None and not (-1.0 <= roe <= 1.5):
            roe, roe_derived = None, False          # absurd value: treat as missing rather than trust it
    return {
        "available": True,
        "market_cap_cr": (g("marketCap") / 1e7) if g("marketCap") else None,
        "roe": roe, "roe_derived": roe_derived,     # fraction
        "op_margin": g("operatingMargins"),         # fraction
        "rev_growth": g("revenueGrowth"),           # fraction, latest quarter YoY (Yahoo definition)
        "earn_growth": g("earningsGrowth"),         # fraction
        "debt_to_equity": (de / 100.0) if de is not None else None,
        "fcf_cr": (g("freeCashflow") / 1e7) if g("freeCashflow") is not None else None,
        "ocf_cr": (g("operatingCashflow") / 1e7) if g("operatingCashflow") is not None else None,
        "trailing_pe": g("trailingPE"), "forward_pe": g("forwardPE"),
        "pb": g("priceToBook"), "ev_ebitda": g("enterpriseToEbitda"),
        "insider_pct": g("heldPercentInsiders"),    # proxy for promoter holding; pledging NOT available
        "is_financial": g("sector") == "Financial Services", "industry": g("industry"),
        "last_fiscal_year_end": g("lastFiscalYearEnd"), "most_recent_quarter": g("mostRecentQuarter"),
        "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "schema": FUND_SCHEMA,                      # bump when extraction changes so saved copies are refreshed
    }


def growth_from_fin(fin: dict | None) -> dict:
    """Multi-year CAGR from annual statements (needs >=3 years). Missing => None (never guessed)."""
    out = {"rev_cagr": None, "ni_cagr": None, "years": 0}
    if not fin:
        return out

    def cagr(v):
        if len(v) < 3:
            return None, 0
        n = min(len(v) - 1, 3)
        a, b = v[0], v[n]
        if a is None or b is None or a <= 0 or b <= 0:
            return None, n
        return (a / b) ** (1 / n) - 1, n
    out["rev_cagr"], n1 = cagr(fin.get("rev", []))
    out["ni_cagr"], n2 = cagr(fin.get("ni", []))
    out["years"] = max(n1, n2)
    return out
