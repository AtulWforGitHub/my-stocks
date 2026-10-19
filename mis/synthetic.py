"""SYNTHETIC data provider for demo/tests ONLY. Never mixed with real data: demo writes to demo_output/ with a banner."""
from __future__ import annotations
import hashlib
import numpy as np
import pandas as pd
from .data import PriceProvider


def synth_history(seed_key: str, n: int = 1300, drift: float | None = None, base: float | None = None) -> pd.DataFrame:
    seed = int(hashlib.md5(seed_key.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    mu = drift if drift is not None else rng.uniform(0.0001, 0.0009)
    rets = rng.normal(mu, rng.uniform(0.011, 0.022), n)
    start = base if base is not None else rng.uniform(200, 4000)
    close = start * np.exp(np.cumsum(rets))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize() - pd.Timedelta(days=0), periods=n)
    opn = close * (1 + rng.normal(0, 0.004, n))
    hi = np.maximum(opn, close) * (1 + rng.uniform(0, 0.012, n)); lo = np.minimum(opn, close) * (1 - rng.uniform(0, 0.012, n))
    vol = rng.integers(2e5, 5e6, n).astype(float)
    return pd.DataFrame({"Open": opn, "High": hi, "Low": lo, "Close": close, "Volume": vol}, index=idx)


class SyntheticProvider(PriceProvider):
    name = "SYNTHETIC (demo only - not real prices)"

    def history(self, tickers, period="5y"):
        out = {}
        for t in tickers:
            if t == "^INDIAVIX":
                v = synth_history(t, drift=0.0, base=15.0)             # plausible, calm level so the demo shows no false market-risk alarm
                sd = float(v["Close"].std()) or 1.0
                for col in ("Open", "High", "Low", "Close"):
                    v[col] = 14.5 + (v[col] - float(v["Close"].mean())) / sd * 1.2
                out[t] = v
            elif t == "^NSEI":
                out[t] = synth_history(t, drift=0.0004, base=22000)
            else:
                out[t] = synth_history(t)
        return out

    def info(self, ticker):
        rng = np.random.default_rng(int(hashlib.md5(("i" + ticker).encode()).hexdigest()[:8], 16))
        return {"marketCap": float(rng.uniform(1.2e10, 9e11)), "returnOnEquity": float(rng.uniform(0.06, 0.28)),
                "operatingMargins": float(rng.uniform(0.08, 0.32)), "revenueGrowth": float(rng.uniform(-0.02, 0.28)),
                "earningsGrowth": float(rng.uniform(-0.05, 0.35)), "debtToEquity": float(rng.uniform(5, 160)),
                "freeCashflow": float(rng.uniform(-1e9, 5e10)), "operatingCashflow": float(rng.uniform(1e9, 8e10)),
                "trailingPE": float(rng.uniform(14, 80)), "forwardPE": float(rng.uniform(12, 65)),
                "priceToBook": float(rng.uniform(1, 12)), "heldPercentInsiders": float(rng.uniform(0.2, 0.75)),
                "sector": "Industrials"}

    def financials(self, ticker):
        rng = np.random.default_rng(int(hashlib.md5(("f" + ticker).encode()).hexdigest()[:8], 16))
        g = rng.uniform(0.0, 0.30); base = rng.uniform(2e9, 3e10)
        rev = [base * (1 + g) ** (3 - i) for i in range(4)]
        ni = [r * rng.uniform(0.05, 0.18) for r in rev]
        return {"rev": rev, "ni": ni}
