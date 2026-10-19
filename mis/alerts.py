"""Alert engine: levels, de-duplication by state change, and email gating."""
from __future__ import annotations
import json
import datetime as dt
from pathlib import Path

LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def lvl(x: str) -> int:
    return LEVELS.index(x)


def dedupe(alerts: list[dict], state_path: str | Path, today: dt.date | None = None) -> tuple[list[dict], dict]:
    """Return (new_or_changed_alerts, new_state). Same key+fingerprint => suppressed. Resolved alerts are cleared
    so that they can re-fire if the condition returns."""
    p = Path(state_path)
    old = json.loads(p.read_text()) if p.exists() else {}
    today = (today or dt.date.today()).isoformat()
    new_state, fresh = {}, []
    for a in alerts:
        prev = old.get(a["key"])
        if prev is None or prev["fingerprint"] != a["fingerprint"] or lvl(prev["level"]) < lvl(a["level"]):
            fresh.append(a)
            new_state[a["key"]] = dict(fingerprint=a["fingerprint"], level=a["level"], first_seen=today, last_sent=today)
        else:
            new_state[a["key"]] = prev
    return fresh, new_state


def save_state(state: dict, path: str | Path):
    Path(path).write_text(json.dumps(state, indent=1))


def should_email(fresh: list[dict], cfg: dict, today: dt.date, force_weekly: bool = False) -> tuple[bool, str, str]:
    """Returns (send, reason, kind) with kind in urgent|update|weekly. Urgent (CRITICAL) alerts bypass the pause switch."""
    a = cfg["alerts"]
    if not a.get("send_email", True):
        return False, "email disabled in config", ""
    if any(x["level"] == "CRITICAL" for x in fresh):
        return True, "critical alert", "urgent"
    if a.get("paused"):
        return False, "alerts paused in config", ""
    minl = lvl(a.get("min_level_to_email", "MEDIUM"))
    urgent = [x for x in fresh if lvl(x["level"]) >= minl]
    weekly = a.get("weekly_summary_enabled", True) and today.strftime("%A") == a.get("weekly_summary_day", "Friday")
    if urgent:
        return True, f"{len(urgent)} new/changed alert(s)", "update"
    if weekly or force_weekly:
        return True, "weekly summary", "weekly"
    return False, "no new material change", ""


def subject_for(fresh: list[dict], today: dt.date, kind: str) -> str:
    if kind == "urgent":
        return f"[URGENT] MIS: critical risk to review - {today.isoformat()}"
    top = max([lvl(a["level"]) for a in fresh], default=-1)
    if kind == "weekly" and top < 2:
        return f"[WEEKLY] MIS portfolio and research summary - {today.isoformat()}"
    return f"[{'ACTION REQUIRED' if top >= 2 else 'MONITOR'}] MIS update - {today.isoformat()}"
