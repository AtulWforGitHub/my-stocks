"""SQLite audit log: every recommendation with its evidence, confidence, data source and later outcome."""
from __future__ import annotations
import json
import sqlite3
import datetime as dt
from pathlib import Path

SCHEMA = """CREATE TABLE IF NOT EXISTS recommendations(
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_date TEXT, ticker TEXT, action TEXT, reason TEXT,
 evidence TEXT, confidence TEXT, invalidation TEXT, price REAL, price_asof TEXT, source TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS runs(run_date TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS approvals(
 id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, ticker TEXT, action TEXT, detail TEXT, status TEXT DEFAULT 'PENDING', decided_on TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_rec ON recommendations(run_date, ticker, action);"""


class Audit:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(path))
        self.con.executescript(SCHEMA)

    def run_done(self, run_date: str) -> bool:
        """Idempotency: a completed run for the same date is not repeated."""
        r = self.con.execute("SELECT status FROM runs WHERE run_date=?", (run_date,)).fetchone()
        return bool(r and r[0] == "OK")

    def start_run(self, run_date: str):
        self.con.execute("INSERT OR REPLACE INTO runs(run_date,started_at,status) VALUES(?,?,'RUNNING')",
                         (run_date, dt.datetime.now().isoformat(timespec="seconds")))
        self.con.commit()

    def finish_run(self, run_date: str, status: str, notes: str = ""):
        self.con.execute("UPDATE runs SET finished_at=?, status=?, notes=? WHERE run_date=?",
                         (dt.datetime.now().isoformat(timespec="seconds"), status, notes, run_date))
        self.con.commit()

    def last_ok_run(self) -> str | None:
        r = self.con.execute("SELECT MAX(run_date) FROM runs WHERE status='OK'").fetchone()
        return r[0] if r and r[0] else None

    def log_rec(self, run_date, ticker, action, reason, evidence, confidence, invalidation, price, price_asof, source):
        # INSERT OR IGNORE: a recommendation, once recorded, is never rewritten (even by a forced re-run the same day)
        self.con.execute("""INSERT OR IGNORE INTO recommendations(run_date,ticker,action,reason,evidence,confidence,invalidation,price,price_asof,source)
                            VALUES(?,?,?,?,?,?,?,?,?,?)""",
                         (run_date, ticker, action, reason, json.dumps(evidence, default=str), confidence,
                          json.dumps(invalidation), price, price_asof, source))

    def queue_approval(self, ticker: str, action: str, detail: dict):
        """Human-approval queue. Skips if an identical PENDING item exists."""
        d = json.dumps(detail, default=str)
        ex = self.con.execute("SELECT id FROM approvals WHERE ticker=? AND action=? AND status='PENDING'", (ticker, action)).fetchone()
        if ex:
            self.con.execute("UPDATE approvals SET detail=? WHERE id=?", (d, ex[0]))
        else:
            self.con.execute("INSERT INTO approvals(created,ticker,action,detail) VALUES(?,?,?,?)",
                             (dt.date.today().isoformat(), ticker, action, d))
        self.con.commit()

    def pending(self) -> list[dict]:
        cur = self.con.execute("SELECT id,created,ticker,action,detail FROM approvals WHERE status='PENDING' ORDER BY id")
        return [dict(id=i, created=c, ticker=t, action=a, detail=json.loads(d)) for i, c, t, a, d in cur]

    def decide(self, approval_id: int, status: str):
        assert status in ("APPROVED", "REJECTED")
        self.con.execute("UPDATE approvals SET status=?, decided_on=? WHERE id=?", (status, dt.date.today().isoformat(), approval_id))
        self.con.commit()

    def commit(self):
        self.con.commit()

    def history_events(self, per_ticker: int = 40) -> dict:
        """Status-change events per ticker (date, status, price, score). Built only from what was recorded at the time."""
        out: dict[str, list] = {}
        last: dict[str, str] = {}
        cur = self.con.execute("SELECT run_date,ticker,action,price,evidence FROM recommendations ORDER BY run_date, id")
        for d, t, a, pr, ev in cur:
            if last.get(t) != a:
                try:
                    sc = json.loads(ev).get("research")
                except Exception:  # noqa: BLE001
                    sc = None
                out.setdefault(t, []).append([d, a, pr, sc]); last[t] = a
        return {t: v[-per_ticker:] for t, v in out.items()}

    def recent_runs(self, n: int = 14) -> list[dict]:
        cur = self.con.execute("SELECT run_date,status,notes FROM runs ORDER BY run_date DESC LIMIT ?", (n,))
        return [dict(date=d, status=s, notes=nt) for d, s, nt in cur]
