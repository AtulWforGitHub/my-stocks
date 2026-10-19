"""status.json: what the health page and the page banner read. A failed run never overwrites the last good report;
it only records the failure here, and the dashboard labels the old report's age."""
from __future__ import annotations
import json
import datetime as dt
from pathlib import Path


def read(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {}


def build(path: Path, *, outcome: str, run_date: str, mode: str, provider: str = "", price_date: str | None = None, failed_requests: int = 0,
          email: dict | None = None, notes: list | None = None, next_run: str | None = None, runs: list | None = None, error: str | None = None):
    old = read(path)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    st = {"outcome": outcome, "run_date": run_date, "finished_at": now, "mode": mode, "provider": provider, "price_date": price_date,
          "failed_requests": failed_requests, "email": email or {"status": "not attempted", "note": ""}, "notes": notes or [],
          "next_run": next_run, "runs": runs or old.get("runs", []), "error": error,
          "last_success": old.get("last_success")}
    if outcome == "ok":
        st["last_success"] = {"finished_at": now, "run_date": run_date, "price_date": price_date, "mode": mode}
    else:
        st["last_failure"] = {"at": now, "run_date": run_date, "why": error or outcome}
    if outcome == "ok":
        st["last_failure"] = old.get("last_failure")
    else:
        st["last_failure"] = st["last_failure"]
    return st


def dump(path: Path, st: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st, indent=1))


def write(path: Path, **kw):
    st = build(path, **kw)
    dump(path, st)
    return st
