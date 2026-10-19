"""NSE trading calendar. Holidays come from data/nse_holidays.csv (update it each December from the NSE circular).
2026 note: some sources count 15 weekday holidays; only the 13 dates in the file were confirmed. The pipeline therefore ALSO
checks the data itself: if the latest market bar is not today's, the run says 'no new market data' instead of claiming freshness."""
from __future__ import annotations
import csv
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
RUN_HOUR_IST, RUN_MIN_IST = 17, 0


def load_holidays(path: Path) -> dict[dt.date, tuple[str, str]]:
    out = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    out[dt.date.fromisoformat(r["date"].strip())] = (r["type"].strip(), r["description"].strip())
                except Exception:  # noqa: BLE001
                    continue
    return out


def now_ist() -> dt.datetime:
    return dt.datetime.now(IST)


def market_day(d: dt.date, hol: dict) -> tuple[bool, str]:
    """(is a regular full trading day, reason)."""
    kind = hol.get(d)
    if kind and kind[0] == "holiday":
        return False, f"NSE holiday: {kind[1]}"
    if d.weekday() >= 5:
        return (False, "weekend") if not (kind and kind[0] == "special") else (False, f"special session only: {kind[1]}")
    return True, "regular trading day"


def next_trading_day(d: dt.date, hol: dict) -> dt.date:
    n = d + dt.timedelta(days=1)
    while not market_day(n, hol)[0]:
        n += dt.timedelta(days=1)
    return n


def trading_days_between(a: dt.date, b: dt.date, hol: dict) -> int:
    n, d = 0, a + dt.timedelta(days=1)
    while d <= b:
        n += market_day(d, hol)[0]
        d += dt.timedelta(days=1)
    return n


def next_run(now: dt.datetime, hol: dict) -> dt.datetime:
    """Next scheduled analysis (17:00 IST on the next trading day)."""
    d = now.date()
    today_slot = dt.datetime(d.year, d.month, d.day, RUN_HOUR_IST, RUN_MIN_IST, tzinfo=IST)
    if market_day(d, hol)[0] and now < today_slot:
        return today_slot
    nd = next_trading_day(d, hol)
    return dt.datetime(nd.year, nd.month, nd.day, RUN_HOUR_IST, RUN_MIN_IST, tzinfo=IST)


def market_status(now: dt.datetime, hol: dict) -> dict:
    """Open / closed / holiday for the cash segment, 09:15-15:30 IST. Reliable only as far as the holiday file is."""
    ok, why = market_day(now.date(), hol)
    if not ok:
        return {"state": "holiday" if "holiday" in why or "special" in why else "closed", "reason": why}
    t = now.time()
    if dt.time(9, 15) <= t <= dt.time(15, 30):
        return {"state": "open", "reason": "regular session (data here is still end-of-day/delayed)"}
    return {"state": "closed", "reason": "outside 09:15-15:30 IST"}
