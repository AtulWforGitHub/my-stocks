"""Test helpers: run the REAL-mode pipeline against a temp copy of the project with a synthetic provider and fake email."""
import datetime as dt, json, os, shutil, tempfile
from pathlib import Path
from mis.config import ROOT
from mis import discovery


class Sandbox:
    def __init__(self, drop_history=(), email_ok=True, prev_status="WATCH", prev_extra=None, prev=True):
        from mis import run as r
        from mis.synthetic import SyntheticProvider
        self.r, self.old = r, (r.ROOT, r.YahooProvider, r.discovery.load_universe, r.send_email)
        self.tmp = Path(tempfile.mkdtemp()); (self.tmp / "data").mkdir(); (self.tmp / "state").mkdir()
        for f in (ROOT / "data").glob("*.csv"): shutil.copy(f, self.tmp / "data" / f.name)
        drop = set(drop_history)

        class P(SyntheticProvider):
            name = "TEST-PROVIDER (synthetic stand-in for real)"
            def history(self, tickers, period="5y"):
                return {k: v for k, v in SyntheticProvider.history(self, tickers, period).items() if k not in drop}
        r.ROOT, r.YahooProvider = self.tmp, (lambda *a, **k: P())
        self.good = r.YahooProvider
        r.discovery.load_universe = lambda sd, offline=False: (discovery.seed_universe(), "test seed universe")
        self.sent = []
        def fake_send(subject, html, text, to, attachments=None):
            self.sent.append(subject); return (email_ok, "sent" if email_ok else "smtp down")
        r.send_email = fake_send
        os.environ["MIS_EMAIL_TO"], os.environ["GMAIL_APP_PASSWORD"] = "me@example.com", "x"
        if prev:
            stocks = {s["ticker"]: {"status": prev_status, "research": 70.0, "price": 100.0, "pos": "above"} for s in discovery.seed_universe()}
            stocks.update(prev_extra or {})
            (self.tmp / "state" / "last_snapshot.json").write_text(json.dumps({"date": "2026-01-01", "stocks": stocks}))

    def run(self, **kw):
        return self.r.run(today=dt.date.today(), force=True, **kw)

    def close(self):
        self.r.ROOT, self.r.YahooProvider, self.r.discovery.load_universe, self.r.send_email = self.old
        os.environ.pop("MIS_EMAIL_TO", None); os.environ.pop("GMAIL_APP_PASSWORD", None)


def embedded_data(html: str) -> dict:
    return json.loads(html.split('id="mis-data" type="application/json">')[1].split("</script>")[0].replace("<\\/", "</"))
