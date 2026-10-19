import datetime as dt
import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

from mis import indicators as ind, alerts as al, decision, discovery, actions, changes as chg, nse_calendar as cal, status as stat
from mis.config import load_config, ROOT
from mis.data import freshness, extract_fundamentals, growth_from_fin
from mis.scoring import score_stock, entry_setup_score, mb_math, confidence
from mis.synthetic import synth_history
from mis.audit import Audit
from helpers import Sandbox, embedded_data
from mis.email_report import render as render_email

CFG = load_config()
W = CFG["scoring_weights"]
META = {"ticker": "X.NS", "name": "X", "sector": "IT", "cap": "S", "tailwind": 3}
GOOD_FUND = {"returnOnEquity": .25, "operatingMargins": .3, "revenueGrowth": .25, "earningsGrowth": .3, "debtToEquity": 10,
             "freeCashflow": 1e9, "operatingCashflow": 2e9, "forwardPE": 18, "trailingPE": 20, "marketCap": 8000e7, "heldPercentInsiders": .6}


def fresh_ok(): return {"status": "fresh", "asof": "2026-10-16"}


class TestIndicators(unittest.TestCase):
    def test_rsi_bounds_and_trend(self):
        r = ind.rsi(pd.Series(np.arange(1, 100, dtype=float))).dropna()
        self.assertTrue((r <= 100).all() and (r >= 0).all()); self.assertGreater(r.iloc[-1], 90)

    def test_sma_and_drawdown(self):
        self.assertAlmostEqual(ind.sma(pd.Series([1, 2, 3, 4, 5.0]), 5).iloc[-1], 3.0)
        self.assertAlmostEqual(ind.max_drawdown(pd.Series([100, 120, 60, 90.0])), -0.5)

    def test_snapshot_short_history_not_ok(self):
        self.assertFalse(ind.technical_snapshot(synth_history("a", n=30))["ok"])

    def test_price_anomaly_flagged(self):
        df = synth_history("jump", n=400)
        df.iloc[-1, df.columns.get_loc("Close")] = df["Close"].iloc[-2] * 2.1       # looks like an unadjusted split
        self.assertIn("one-day move", ind.technical_snapshot(df)["anomaly"])
        self.assertIsNone(ind.technical_snapshot(synth_history("calm", n=400, drift=0.0003))["anomaly"])


class TestScoringHonesty(unittest.TestCase):
    def _score(self, gov="ok", fund=None, tech=None):
        fund = fund if fund is not None else extract_fundamentals(GOOD_FUND)
        tech = tech if tech is not None else ind.technical_snapshot(synth_history("up", drift=0.0008), synth_history("n", drift=0.0002)["Close"])
        return score_stock(META, fund, tech, {"status": gov}, W, {"rev_cagr": .2, "ni_cagr": .25, "years": 3}), tech

    def test_missing_data_is_excluded_not_neutral(self):
        res, _ = self._score(fund={"available": False}, tech={"ok": False})
        comps = res["components"]
        self.assertFalse(comps["technical"]["data"]); self.assertIn("Insufficient", comps["technical"]["note"]); self.assertEqual(comps["technical"]["points"], 0.0)
        self.assertIsNone(res["total"])                       # under 50% coverage: no score at all

    def test_score_normalised_over_available_evidence(self):
        full, _ = self._score(); part, _ = self._score(tech={"ok": False})
        self.assertLessEqual(full["total"], 100); self.assertGreater(part["data_confidence_pct"], 50); self.assertLess(part["data_confidence_pct"], full["data_confidence_pct"])
        self.assertTrue(0 <= part["total"] <= 100)

    def test_weights_sum_and_bounds(self):
        res, _ = self._score(); self.assertEqual(sum(c["max"] for c in res["components"].values()), 100)

    def test_confidence_never_high_when_governance_unreviewed(self):
        self.assertNotEqual(confidence(95, "unreviewed")["label"], "High")
        self.assertEqual(confidence(95, "ok")["label"], "High")
        self.assertIn("NOT reviewed", " ".join(confidence(95, "unreviewed")["limits"]))
        self.assertEqual(confidence(50, "ok")["label"], "Low")

    def test_bad_weights_rejected(self):
        d = Path(tempfile.mkdtemp()) / "c.yaml"
        d.write_text("scoring_weights: {growth: 50, business_quality: 20, financial_strength: 15, size_runway: 10, governance: 10, valuation: 10, technical: 5, tailwinds: 5}")
        with self.assertRaises(ValueError): load_config(d)

    def test_growth_and_mb_math(self):
        g = growth_from_fin({"rev": [200, 160, 130, 100], "ni": [30, 20, 15, 10]})
        self.assertAlmostEqual(g["rev_cagr"], 2 ** (1 / 3) - 1, places=4); self.assertIsNone(growth_from_fin({"rev": [100, 90]})["rev_cagr"])
        mb = mb_math({"available": True, "trailing_pe": 25}, 25); self.assertAlmostEqual(mb["x10_15y"], (10 ** (1 / 15) - 1) * 100, places=1)
        self.assertIsNone(mb_math({"available": True, "trailing_pe": -3}))


class TestClassificationConsistency(unittest.TestCase):
    def _ctx(self, price):
        tech = {"ok": True, "last": price, "dma50": 100.0, "dma100": 98.0, "dma200": 90.0, "dma200_rising": True, "atr": 2.0, "resistance": 130.0, "ret_1y_pct": 30}
        zones = decision.entry_zones(tech)
        res = {"total": 80.0, "data_confidence_pct": 90}
        return tech, zones, res

    def test_entry_zone_internal_consistency(self):
        tech, z, _ = self._ctx(100.0)
        self.assertLess(z["thesis_review_level"], z["ideal_buy_zone"][0]); self.assertLess(z["ideal_buy_zone"][0], z["ideal_buy_zone"][1])
        self.assertLess(z["trading_stop_3atr"], tech["last"]); self.assertGreater(z["first_review_zone"], tech["last"])

    def test_accumulate_only_when_price_inside_range(self):
        for price, want in ((100.0, "ACCUMULATE CANDIDATE"), (125.0, "WATCH")):
            tech, z, res = self._ctx(price)
            st, why = decision.classify(res, {"score": 80, "avoid": []}, fresh_ok(), "ok", tech, z)
            self.assertEqual(st, want, why)
            if want == "WATCH": self.assertIn("WAIT", " ".join(why))

    def test_stale_data_blocks_fresh_recommendation(self):
        tech, z, res = self._ctx(100.0)
        self.assertEqual(decision.classify(res, {"score": 80, "avoid": []}, {"status": "stale", "asof": "2020-01-01"}, "ok", tech, z)[0], "DATA UNAVAILABLE")

    def test_anomalous_price_blocks_recommendation(self):
        tech, z, res = self._ctx(100.0); tech["anomaly"] = "a 60% one-day move"
        self.assertEqual(decision.classify(res, {"score": 80, "avoid": []}, fresh_ok(), "ok", tech, z)[0], "DATA UNAVAILABLE")

    def test_insufficient_data_and_red_flag(self):
        tech, z, _ = self._ctx(100.0)
        self.assertEqual(decision.classify({"total": None, "data_confidence_pct": 40}, {"score": 80, "avoid": []}, fresh_ok(), "ok", tech, z)[0], "DATA UNAVAILABLE")
        self.assertEqual(decision.classify({"total": 90.0, "data_confidence_pct": 95}, {"score": 90, "avoid": []}, fresh_ok(), "red_flag", tech, z)[0], "AVOID")

    def test_low_coverage_cannot_be_candidate(self):
        tech, z, _ = self._ctx(100.0)
        self.assertEqual(decision.classify({"total": 85.0, "data_confidence_pct": 60}, {"score": 80, "avoid": []}, fresh_ok(), "ok", tech, z)[0], "WATCH")

    def test_entry_avoids_stretched_and_parabolic(self):
        tech = {"ok": True, "last": 150.0, "dma50": 120.0, "dma100": 110.0, "dma200": 100.0, "dma200_rising": True, "rs_6m_vs_nifty": .2, "rsi": 80,
                "resistance": 151.0, "ext_200_pct": 50.0, "from_high_pct": -1, "macd_hist": 1, "ret_1y_pct": 300}
        a = " ".join(entry_setup_score(tech)["avoid"]); self.assertIn("stretched", a); self.assertIn("parabolic", a)


class TestChangeDetection(unittest.TestCase):
    def S(self, t, status, score, price): return {"ticker": t, "status": status, "research": score, "price": price, "zones": {"position": "in_range"}}

    def test_no_previous_run_means_no_comparisons(self):
        self.assertEqual(chg.diff(None, [self.S("A", "HOLD", 70, 100)], {"A": "A"}, "2026-10-16"), [])

    def test_only_real_changes_are_reported(self):
        prev = {"stocks": {"A": {"status": "WATCH", "research": 70, "price": 100, "pos": "above"}, "B": {"status": "WATCH", "research": 70, "price": 100, "pos": "above"}}}
        cur = [self.S("A", "ACCUMULATE CANDIDATE", 71, 101), self.S("B", "WATCH", 71, 101)]
        out = chg.diff(prev, cur, {"A": "A", "B": "B"}, "2026-10-16")
        self.assertEqual([o["ticker"] for o in out], ["A"]); self.assertEqual(out[0]["kind"], "purchase_opportunity")

    def test_score_drop_and_price_move_and_dropped(self):
        prev = {"stocks": {"A": {"status": "WATCH", "research": 80, "price": 100, "pos": "x"}, "Z": {"status": "WATCH", "research": 70, "price": 5, "pos": "x"}}}
        out = chg.diff(prev, [self.S("A", "WATCH", 70, 120)], {"A": "A", "Z": "Z"}, "d")
        kinds = {o["kind"] for o in out}; self.assertTrue({"thesis_deterioration", "price_move", "dropped"} <= kinds)

    def test_quiet_day_says_no_material_changes(self):
        items = actions.build_items([], [], {}, {"material": False}, "prov", "real", True)
        self.assertEqual(len(items), 1); self.assertEqual(items[0]["category"], "none"); self.assertIn("No material changes", items[0]["title"])
        self.assertEqual(actions.to_alerts(items), [])

    def test_demo_items_are_labelled(self):
        items = actions.build_items([], [], {}, {"material": True, "level": "high", "reason": "x"}, "prov", "synthetic", False)
        self.assertTrue(all(i["title"].startswith("[DEMO]") for i in items))


class TestAlerts(unittest.TestCase):
    def test_dedupe_suppresses_unchanged_and_refires_after_clear(self):
        d = Path(tempfile.mkdtemp()) / "s.json"
        a = [dict(key="TRIM:A", level="HIGH", fingerprint="x", title="t", body="b", ticker="A", action="TRIM")]
        fresh, st = al.dedupe(a, d); al.save_state(st, d); self.assertEqual(len(fresh), 1)
        fresh, st = al.dedupe(a, d); al.save_state(st, d); self.assertEqual(len(fresh), 0)
        _, st = al.dedupe([], d); al.save_state(st, d); self.assertEqual(len(al.dedupe(a, d)[0]), 1)

    def test_escalation_refires(self):
        d = Path(tempfile.mkdtemp()) / "s.json"; a = dict(key="K", level="MEDIUM", fingerprint="x", title="t", body="b", ticker="A", action="X")
        _, st = al.dedupe([a], d); al.save_state(st, d); self.assertEqual(len(al.dedupe([dict(a, level="CRITICAL")], d)[0]), 1)

    def test_email_gating_and_urgent_bypass(self):
        cfg = load_config(); mon, fri = dt.date(2026, 10, 12), dt.date(2026, 10, 16)
        self.assertFalse(al.should_email([], cfg, mon)[0]); self.assertEqual(al.should_email([], cfg, fri)[2], "weekly")
        self.assertEqual(al.should_email([dict(level="HIGH")], cfg, mon)[2], "update"); self.assertFalse(al.should_email([dict(level="LOW")], cfg, mon)[0])
        cfg["alerts"]["paused"] = True
        self.assertFalse(al.should_email([dict(level="HIGH")], cfg, fri)[0])
        self.assertEqual(al.should_email([dict(level="CRITICAL")], cfg, fri)[2], "urgent")      # urgent bypasses the pause
        self.assertIn("[URGENT]", al.subject_for([dict(level="CRITICAL")], fri, "urgent"))

    def test_email_refuses_synthetic_data(self):
        with self.assertRaises(ValueError):
            render_email(dict(mode="synthetic", run_date="d", price_date="d", provider="p"), [], "u", "update")

    def test_real_email_renders_both_formats(self):
        items = actions.build_items([], [], {}, {"material": False}, "prov", "real", True)
        html, text = render_email(dict(mode="real", run_date="2026-10-16", price_date="2026-10-16", provider="prov", market_risk={"reason": "VIX 14"}, headlines=[]), items, "https://x.github.io/r/", "weekly")
        self.assertIn("No material changes detected", html); self.assertIn("No material changes detected", text); self.assertIn("not personalised financial advice", text)


class TestCalendarStatusAudit(unittest.TestCase):
    HOL = cal.load_holidays(ROOT / "data" / "nse_holidays.csv")

    def test_holiday_weekend_and_next_run(self):
        self.assertFalse(cal.market_day(dt.date(2026, 10, 20), self.HOL)[0])          # Dussehra
        self.assertFalse(cal.market_day(dt.date(2026, 10, 17), self.HOL)[0])          # Saturday
        self.assertTrue(cal.market_day(dt.date(2026, 10, 16), self.HOL)[0])
        self.assertEqual(cal.next_trading_day(dt.date(2026, 10, 16), self.HOL), dt.date(2026, 10, 19))
        n = cal.next_run(dt.datetime(2026, 10, 19, 18, 0, tzinfo=cal.IST), self.HOL)
        self.assertEqual(n.date(), dt.date(2026, 10, 21)); self.assertEqual(n.hour, 17)    # skips the 20th
        self.assertEqual(cal.trading_days_between(dt.date(2026, 10, 16), dt.date(2026, 10, 21), self.HOL), 2)

    def test_failed_run_preserves_last_success(self):
        p = Path(tempfile.mkdtemp()) / "status.json"
        stat.write(p, outcome="ok", run_date="2026-10-15", mode="real", price_date="2026-10-15")
        st = stat.write(p, outcome="failed", run_date="2026-10-16", mode="real", error="boom")
        self.assertEqual(st["outcome"], "failed"); self.assertEqual(st["last_success"]["run_date"], "2026-10-15"); self.assertEqual(st["last_failure"]["why"], "boom")

    def test_recommendation_history_is_immutable(self):
        a = Audit(Path(tempfile.mkdtemp()) / "a.db")
        a.log_rec("2026-10-15", "A", "WATCH", "first", {"research": 70}, "Medium", [], 100.0, "2026-10-15", "p")
        a.log_rec("2026-10-15", "A", "WATCH", "REWRITTEN with hindsight", {"research": 99}, "High", [], 999.0, "2026-10-15", "p")
        a.commit()
        row = a.con.execute("SELECT reason, price FROM recommendations").fetchall()
        self.assertEqual(row, [("first", 100.0)])
        a.log_rec("2026-10-16", "A", "ACCUMULATE CANDIDATE", "r", {"research": 75}, "Medium", [], 105.0, "d", "p")
        ev = a.history_events()["A"]; self.assertEqual([e[1] for e in ev], ["WATCH", "ACCUMULATE CANDIDATE"])


class TestDiscovery(unittest.TestCase):
    CSV = "Company Name,Industry,Symbol,Series,ISIN Code\nAlpha Ltd,Capital Goods,ALPHA,EQ,INE1\nBeta Ltd,Healthcare,BETA,EQ,INE2\nGamma Ltd,Chemicals,GAMMA,BE,INE3\n"

    def test_parse_and_seed(self):
        r = discovery.parse_constituents(self.CSV, "S"); self.assertEqual([x["ticker"] for x in r], ["ALPHA.NS", "BETA.NS"])
        u, note = discovery.load_universe(Path(tempfile.mkdtemp()), offline=True); self.assertGreater(len(u), 40); self.assertEqual(len({x["ticker"] for x in u}), len(u))

    def test_prefilter_rules(self):
        uni = [dict(ticker=t, name=t, sector="X", cap="S", tailwind=3) for t in ("OK", "BIG", "TINY", "LOWROE", "DEBT", "NODATA")]
        base = dict(available=True, market_cap_cr=5000, roe=0.2, debt_to_equity=0.3, rev_growth=0.15, earn_growth=0.2, is_financial=False)
        funds = {"OK": base, "BIG": {**base, "market_cap_cr": 500000}, "TINY": {**base, "market_cap_cr": 300}, "LOWROE": {**base, "roe": 0.04}, "DEBT": {**base, "debt_to_equity": 3.0}, "NODATA": {"available": False}}
        self.assertEqual([x["ticker"] for x in discovery.prefilter(uni, funds, CFG["universe"])], ["OK"])


class TestPipeline(unittest.TestCase):
    def _sandbox(self):
        """Run the pipeline against a temporary copy of the project so tests never touch your real docs/ or state/."""
        from mis import run as r
        tmp = Path(tempfile.mkdtemp()); (tmp / "data").mkdir()
        for f in (ROOT / "data").glob("*.csv"): shutil.copy(f, tmp / "data" / f.name)
        old = r.ROOT; r.ROOT = tmp
        return r, tmp, old

    def test_demo_run_end_to_end_idempotent_and_no_personal_data(self):
        r, tmp, old = self._sandbox()
        try:
            ctx = r.run(demo=True, force=True)
            html = (tmp / "demo_output" / "index.html").read_text(); st = json.loads((tmp / "demo_output" / "status.json").read_text())
            self.assertEqual(ctx["mode"], "synthetic"); self.assertEqual(st["mode"], "synthetic"); self.assertEqual(st["email"]["status"], "not attempted")
            self.assertIn("Synthetic demonstration data", html); self.assertIn("MIS", html); self.assertNotIn("NaN", html.split('id="mis-data"')[1].split("</script>")[0])
            data = json.loads(html.split('id="mis-data" type="application/json">')[1].split("</script>")[0].replace("<\\/", "</"))
            self.assertEqual(data["mode"], "synthetic"); blob = json.dumps(data); self.assertTrue('"holdings":' not in blob and '"transactions":' not in blob and '"tx":' not in blob, "personal holdings keys must never be embedded"); self.assertLessEqual(len(data["stocks"]), CFG["universe"]["target_size"])
            self.assertTrue(r.run(demo=True).get("skipped"))
        finally:
            r.ROOT = old

    def test_market_holiday_run_is_skipped_and_report_preserved(self):
        r, tmp, old = self._sandbox()
        try:
            (tmp / "docs").mkdir(); (tmp / "docs" / "index.html").write_text("LAST GOOD REPORT")
            out = r.run(today=dt.date(2026, 10, 20))
            self.assertTrue(out["skipped"]); self.assertEqual((tmp / "docs" / "index.html").read_text(), "LAST GOOD REPORT")
            self.assertEqual(json.loads((tmp / "docs" / "status.json").read_text())["outcome"], "skipped")
        finally:
            r.ROOT = old

    def test_failed_data_refresh_cannot_create_recommendations_or_overwrite_report(self):
        r, tmp, old = self._sandbox()
        class Dead:
            name = "dead"; failed = 3
            def __init__(self, *a, **k): pass
            def info(self, t): return None
            def financials(self, t): return None
            def history(self, t, p): return {}
        saved_provider, saved_uni = r.YahooProvider, r.discovery.load_universe
        r.YahooProvider = Dead; r.discovery.load_universe = lambda sd, offline=False: (discovery.seed_universe(), "test seed")
        try:
            (tmp / "docs").mkdir(); (tmp / "docs" / "index.html").write_text("LAST GOOD REPORT")
            with self.assertRaises(RuntimeError): r.run(today=dt.date(2026, 10, 16), force=True)
            self.assertEqual((tmp / "docs" / "index.html").read_text(), "LAST GOOD REPORT")
            self.assertFalse((tmp / "state" / "last_snapshot.json").exists())            # a failed run does not become the comparison baseline
        finally:
            r.YahooProvider, r.discovery.load_universe, r.ROOT = saved_provider, saved_uni, old


class TestAuditRegressions(unittest.TestCase):
    """Each test here reproduces a defect found in the independent audit (all failed before the fix)."""

    def _tech(self, last, d50=100.0, d200=90.0):
        return {"ok": True, "last": last, "dma50": d50, "dma100": d50 - 2, "dma200": d200, "dma200_rising": True, "atr": 2.0, "resistance": 130.0, "ret_1y_pct": 5}

    def test_below_200dma_is_never_a_buy_candidate_and_thesis_level_is_below_the_range(self):
        t = self._tech(80.0, d50=90.0, d200=100.0); z = decision.entry_zones(t)
        st, why = decision.classify({"total": 85.0, "data_confidence_pct": 95}, {"score": 85, "avoid": []}, fresh_ok(), "ok", t, z)
        self.assertEqual(st, "WATCH"); self.assertIn("200-day", " ".join(why))
        self.assertLess(z["thesis_review_level"], z["ideal_buy_zone"][0])
        z2 = decision.entry_zones(self._tech(100.0)); self.assertEqual(z2["position"], "in_range"); self.assertLess(z2["thesis_review_level"], 100.0)   # for an in-range price the re-check level is always below it

    def test_price_far_below_range_is_not_in_range_but_small_dip_is(self):
        z = decision.entry_zones(self._tech(100.0))
        self.assertEqual(decision.entry_zones(self._tech(80.0))["position"], "below")
        self.assertEqual(decision.entry_zones(self._tech(96.5))["position"], "in_range")      # inside the 3% tolerance under 98
        self.assertEqual(decision.entry_zones(self._tech(103.5))["position"], "above")
        st, _ = decision.classify({"total": 85.0, "data_confidence_pct": 95}, {"score": 85, "avoid": []}, fresh_ok(), "ok", self._tech(88.0, d50=100.0, d200=70.0), decision.entry_zones(self._tech(88.0, d50=100.0, d200=70.0)))
        self.assertEqual(st, "WATCH")

    def test_every_accumulate_candidate_in_a_full_run_is_in_range_above_200dma_with_consistent_levels(self):
        sb = Sandbox(prev=False)
        try:
            ctx = sb.run()
            for s in ctx["stocks"]:
                z = s["zones"]
                if z: self.assertLess(z["thesis_review_level"], z["ideal_buy_zone"][0], s["ticker"])
                if s["status"] == "ACCUMULATE CANDIDATE":
                    self.assertEqual(z["position"], "in_range"); self.assertGreaterEqual(s["price"], s["tech"]["dma200"], s["ticker"])
        finally:
            sb.close()

    def test_failed_email_does_not_mark_alerts_as_delivered(self):
        sb = Sandbox(email_ok=False)
        try:
            sb.run(); self.assertTrue(sb.sent)
            self.assertFalse((sb.tmp / "state" / "alert_state.json").exists(), "alerts must stay pending when the email failed")
        finally:
            sb.close()

    def test_successful_email_marks_alerts_delivered_and_unconfigured_email_does_not(self):
        sb = Sandbox(email_ok=True)
        try:
            sb.run(); st = json.loads((sb.tmp / "state" / "alert_state.json").read_text()); self.assertGreater(len(st), 0)
        finally:
            sb.close()
        sb = Sandbox(email_ok=True); os.environ.pop("GMAIL_APP_PASSWORD", None)
        try:
            sb.run(); self.assertFalse((sb.tmp / "state" / "alert_state.json").exists()); self.assertEqual(sb.sent, [])
        finally:
            sb.close()

    def test_data_failure_is_a_data_notice_not_a_thesis_alert(self):
        sb = Sandbox(drop_history=["KAYNES.NS"], prev_extra={"KAYNES.NS": {"status": "WATCH", "research": 61.0, "price": 100.0, "pos": "above"}})
        try:
            ctx = sb.run()
            ch = [c for c in ctx["changes"] if c["ticker"] == "KAYNES.NS"]; self.assertEqual([c["kind"] for c in ch], ["data"])
            it = [i for i in ctx["items"] if i["ticker"] == "KAYNES.NS"]; self.assertTrue(all(i["category"] == "news" and i["level"] == "LOW" for i in it))
        finally:
            sb.close()

    def test_governance_red_flag_is_reported_as_critical_and_a_returning_ticker_is_not_new(self):
        sb = Sandbox(prev_extra={"KAYNES.NS": {"status": "WATCH", "research": 61.0, "price": 100.0, "pos": "above"}})
        try:
            (sb.tmp / "data" / "governance_flags.csv").write_text("ticker,status,note,reviewed_on\nKAYNES.NS,red_flag,test,2026-10-01\n")
            ctx = sb.run(); it = [i for i in ctx["items"] if i["ticker"] == "KAYNES.NS"]
            self.assertTrue(any(i["category"] == "critical_risk" and i["level"] == "CRITICAL" for i in it))
        finally:
            sb.close()
        sb = Sandbox()
        try:
            snap = json.loads((sb.tmp / "state" / "last_snapshot.json").read_text()); snap["stocks"].pop("AFFLE.NS"); snap["excluded"] = {"AFFLE.NS": "data"}
            (sb.tmp / "state" / "last_snapshot.json").write_text(json.dumps(snap))
            ctx = sb.run(); self.assertFalse([c for c in ctx["changes"] if c["ticker"] == "AFFLE.NS" and c["kind"] == "new_candidate"])
        finally:
            sb.close()

    def test_stale_saved_fundamentals_are_not_silently_reused(self):
        from mis import run as rr
        old = lambda days: {"X.NS": {"available": True, "roe": .3, "retrieved_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()}}
        class NoInfo:
            def info(self, t): return None
        self.assertFalse(rr.fundamentals_cached(NoInfo(), "X.NS", old(200)).get("available"))
        ok = rr.fundamentals_cached(NoInfo(), "X.NS", old(12)); self.assertTrue(ok["available"] and ok["refresh_failed"])

    def test_failed_run_is_recorded_as_failed_and_can_be_retried_the_same_day(self):
        class Dead:
            name = "dead"; failed = 3
            def __init__(self, *a, **k): pass
            def info(self, t): return None
            def financials(self, t): return None
            def history(self, t, p): return {}
        sb = Sandbox(prev=False); sb.r.YahooProvider = Dead
        try:
            with self.assertRaises(RuntimeError): sb.run()
            import sqlite3
            self.assertEqual(sqlite3.connect(str(sb.tmp / "state" / "audit.db")).execute("select status from runs").fetchall(), [("FAILED",)])
            sb.r.YahooProvider = sb.good
            ctx = sb.run(); self.assertNotIn("skipped", ctx)                                   # a FAILED day is retried, not skipped
        finally:
            sb.close()

    def test_health_page_never_shows_the_current_successful_run_as_running(self):
        sb = Sandbox(prev=False)
        try:
            sb.run(); st = json.loads((sb.tmp / "docs" / "status.json").read_text()); html = (sb.tmp / "docs" / "index.html").read_text()
            self.assertEqual(st["runs"][0]["status"], "OK"); self.assertEqual(embedded_data(html)["status"]["runs"][0]["status"], "OK")
            self.assertEqual(st["outcome"], "ok")
        finally:
            sb.close()

    def test_untrusted_links_are_http_only(self):
        from mis import news
        for bad in ("javascript:alert(1)", "data:text/html,x", "  JaVaScRiPt:1", "file:///etc/passwd", "", None):
            self.assertIsNone(news.safe_url(bad), bad)
        self.assertEqual(news.safe_url("https://example.com/a"), "https://example.com/a")
        html, text = render_email(dict(mode="real", run_date="d", price_date="d", provider="p", market_risk={"reason": "r"},
                                       headlines=[dict(title="x", url="javascript:alert(1)", source="s", published="p")]), [], "https://u/", "weekly")
        self.assertNotIn("javascript:", html)



class TestRateLimitResilience(unittest.TestCase):
    """Found when the first real run on a user's PC was rejected by Yahoo (YFRateLimitError) and kept retrying all ~400 companies."""

    class YFRateLimitError(Exception):
        pass

    def _fake_yf(self, exc, msg="Too Many Requests. Rate limited. Try after a while."):
        calls = {"n": 0}
        class T:
            def __init__(self, t): pass
            @property
            def info(self_inner):
                calls["n"] += 1; raise exc(msg)
        class YF:
            Ticker = T
        return YF, calls

    def test_circuit_breaker_stops_asking_after_repeated_rate_limits(self):
        from mis.data import YahooProvider
        yf, calls = self._fake_yf(self.YFRateLimitError)
        p = YahooProvider(pause=0, retries=2, rl_backoff=0, trip_after=4, yf_module=yf)
        for _ in range(50): p.info("A.NS")
        self.assertTrue(p.tripped); self.assertLessEqual(calls["n"], 4, "after the breaker opens, Yahoo must not be called again")
        self.assertGreaterEqual(p.rate_limited, 4)

    def test_ordinary_errors_do_not_trip_the_breaker(self):
        from mis.data import YahooProvider
        yf, calls = self._fake_yf(ValueError, "symbol delisted")
        p = YahooProvider(pause=0, retries=1, rl_backoff=0, trip_after=2, yf_module=yf)
        for _ in range(5): p.info("A.NS")
        self.assertFalse(p.tripped); self.assertEqual(calls["n"], 10)

    def test_per_run_budget_limits_requests_and_cached_data_is_still_used(self):
        from mis import run as rr
        n = {"c": 0}
        class P:
            tripped = False
            def info(self, t): n["c"] += 1; return {"marketCap": 5e10, "returnOnEquity": .2}
        from mis.data import FUND_SCHEMA
        cache = {"CACHED.NS": {"available": True, "roe": .3, "schema": FUND_SCHEMA, "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat()}}
        budget = {"left": 2}
        out = {t: rr.fundamentals_cached(P(), t, cache, budget=budget) for t in ["CACHED.NS", "A.NS", "B.NS", "C.NS", "D.NS"]}
        self.assertEqual(n["c"], 2); self.assertTrue(out["CACHED.NS"]["available"] and out["A.NS"]["available"] and out["B.NS"]["available"])
        self.assertFalse(out["C.NS"]["available"]); self.assertEqual(budget["deferred"], 2)
        self.assertIn("A.NS", cache)                                   # progress is saved for the next run

    def test_tripped_provider_makes_no_further_requests(self):
        from mis import run as rr
        n = {"c": 0}
        class P:
            tripped = True
            def info(self, t): n["c"] += 1
        rr.fundamentals_cached(P(), "A.NS", {}); self.assertEqual(n["c"], 0)

    def test_rate_limited_run_fails_clearly_and_keeps_the_last_report(self):
        class Limited:
            name = "limited"; failed = 9; tripped = True; rate_limited = 9
            def __init__(self, *a, **k): pass
            def info(self, t): return None
            def financials(self, t): return None
            def history(self, t, p): return {}
        sb = Sandbox(prev=False); sb.r.YahooProvider = Limited
        try:
            (sb.tmp / "docs").mkdir(); (sb.tmp / "docs" / "index.html").write_text("LAST GOOD REPORT")
            with self.assertRaises(RuntimeError) as cm: sb.run()
            self.assertIn("rate-limiting", str(cm.exception)); self.assertIn("last good dashboard is kept", str(cm.exception))
            self.assertEqual((sb.tmp / "docs" / "index.html").read_text(), "LAST GOOD REPORT")
        finally:
            sb.close()




class TestHistoryExtraction(unittest.TestCase):
    """Found on a real run: the Nifty 50 benchmark was alone in the last batch and was silently dropped."""
    IDX = pd.bdate_range("2026-01-01", periods=40)

    def _frame(self, tickers, layout):
        cols = {}
        for t in tickers:
            for f in ("Open", "High", "Low", "Close", "Volume"):
                cols[(t, f)] = np.linspace(100, 120, len(self.IDX)) if f != "Volume" else np.full(len(self.IDX), 1e6)
        df = pd.DataFrame(cols, index=self.IDX)
        if layout == "flat":
            df.columns = [f for (_, f) in df.columns]; return df
        df.columns = pd.MultiIndex.from_tuples(df.columns, names=["Ticker", "Price"])
        return df.swaplevel(axis=1).sort_index(axis=1) if layout == "price_first" else df

    def _provider(self, layout, lost=()):
        outer = self
        class YF:
            @staticmethod
            def download(tickers, **kw):
                keep = [t for t in tickers if t not in lost]
                return outer._frame(keep, layout) if keep else pd.DataFrame()
            class Ticker:
                def __init__(self, t): self.t = t
                def history(self, **kw): return outer._frame([self.t], "flat") if self.t not in lost else pd.DataFrame()
        from mis.data import YahooProvider
        return YahooProvider(pause=0, yf_module=YF)

    def test_every_column_layout_and_batch_size_returns_every_ticker(self):
        for layout in ("ticker_first", "price_first", "flat"):
            for n in ((1,) if layout == "flat" else (1, 2, 10, 11, 21)):       # yfinance returns a flat frame only for a single ticker
                t = [f"S{i}.NS" for i in range(n)]
                got = self._provider(layout).history(t, "5y")
                self.assertEqual(sorted(got), sorted(t), f"{layout} n={n}")
                self.assertTrue(all("Close" in d.columns and len(d) == 40 for d in got.values()))

    def test_benchmark_alone_in_the_last_batch_is_kept(self):
        t = [f"S{i}.NS" for i in range(120)] + ["^NSEI"]
        self.assertIn("^NSEI", self._provider("ticker_first").history(t, "5y"))

    def test_a_ticker_lost_by_the_batch_is_retried_singly_and_still_missing_ones_are_reported(self):
        class YF2:
            calls = []
            @staticmethod
            def download(tickers, **kw):
                keep = [t for t in tickers if t != "LOST.NS"]; return TestHistoryExtraction._frame(TestHistoryExtraction(), keep, "ticker_first")
            class Ticker:
                def __init__(self, t): YF2.calls.append(t); self.t = t
                def history(self, **kw): return TestHistoryExtraction._frame(TestHistoryExtraction(), [self.t], "flat")
        from mis.data import YahooProvider
        p = YahooProvider(pause=0, yf_module=YF2); got = p.history(["A.NS", "LOST.NS"], "5y")
        self.assertIn("LOST.NS", got); self.assertEqual(YF2.calls, ["LOST.NS"]); self.assertEqual(p.missing_history, [])
        p2 = self._provider("ticker_first", lost=("GONE.NS",)); got2 = p2.history(["A.NS", "GONE.NS"], "5y")
        self.assertEqual(list(got2), ["A.NS"]); self.assertEqual(p2.missing_history, ["GONE.NS"])         # reported, not silent

    def test_missing_benchmark_counts_as_a_failed_request_and_is_noted(self):
        sb = Sandbox(prev=False)
        from mis.synthetic import SyntheticProvider
        class P(SyntheticProvider):
            name = "TEST"
            def history(self, tickers, period="5y"):
                return {k: v for k, v in SyntheticProvider.history(self, tickers, period).items() if k != "^NSEI"}
        sb.r.YahooProvider = lambda *a, **k: P()
        try:
            ctx = sb.run(); st = json.loads((sb.tmp / "docs" / "status.json").read_text())
            self.assertGreaterEqual(st["failed_requests"], 1)
            self.assertTrue(any("Nifty 50 data was unavailable" in n for n in st["notes"]))
        finally:
            sb.close()

    def test_nse_dummy_placeholder_symbols_are_ignored(self):
        csv_text = "Company Name,Industry,Symbol,Series,ISIN Code\nReal Ltd,Capital Goods,REAL,EQ,INE1\nDummy Co,Healthcare,DUMMYHEG,EQ,INE2\n"
        self.assertEqual([x["ticker"] for x in discovery.parse_constituents(csv_text, "S")], ["REAL.NS"])



class TestRealPageRegressions(unittest.TestCase):
    """From a real run: Ajanta Pharma showed 100% confidence with ROE and free cash flow missing, a 9.6/10 valuation,
    a 'weak trend' label above a rising 200-DMA, and an unrelated company's headline."""
    META = {"ticker": "AJANTPHARM.NS", "name": "Ajanta Pharmaceuticals Ltd.", "sector": "Healthcare", "cap": "M", "tailwind": 4}
    INFO = {"marketCap": 415988580352, "debtToEquity": 5.874, "operatingMargins": .25, "revenueGrowth": .25, "earningsGrowth": .31, "trailingPE": 36.7,
            "forwardPE": 28.6, "priceToBook": 9.2, "heldPercentInsiders": .54, "trailingEps": 90.7, "bookValue": 361.9}
    TECH = {"ok": True, "last": 3329.0, "dma20": 3500., "dma50": 3531., "dma100": 3378., "dma200": 3120., "dma200_rising": True, "rsi": 38., "macd_hist": -24.,
            "rs_6m_vs_nifty": .23, "resistance": 3796., "support": 3200., "atr": 70., "atr_pct": 2.1, "ext_200_pct": 6.7, "from_high_pct": -10.5, "ret_1y_pct": 20,
            "anomaly": None, "avg_traded_value_cr": 30}
    GROWTH = {"rev_cagr": .134, "ni_cagr": .216, "years": 3}

    def _score(self, info=None):
        return score_stock(self.META, extract_fundamentals(info or self.INFO), self.TECH, {"status": "unreviewed"}, W, self.GROWTH)

    def test_unit_conversions_match_the_real_yahoo_values(self):
        f = extract_fundamentals(self.INFO)
        self.assertAlmostEqual(f["market_cap_cr"], 41598.86, places=1)      # 415,988,580,352 rupees = Rs 41,599 crore (verified against the live page)
        self.assertAlmostEqual(f["debt_to_equity"], 0.05874, places=5)      # Yahoo gives percent: 5.874 -> 0.0587x

    def test_confidence_reflects_missing_inputs_inside_components(self):
        no_roe = dict(self.INFO); [no_roe.pop(k) for k in ("trailingEps", "bookValue", "priceToBook")]
        a = self._score(); b = self._score(no_roe)
        self.assertLess(a["data_confidence_pct"], 100, "free cash flow is missing, so confidence cannot be 100%")
        self.assertLess(b["data_confidence_pct"], a["data_confidence_pct"])
        self.assertIn("ROE", b["missing"]); self.assertIn("free cash flow", a["missing"])

    def test_roe_is_derived_when_the_provider_has_none_and_flagged_as_derived(self):
        f = extract_fundamentals(self.INFO); self.assertTrue(f["roe_derived"]); self.assertAlmostEqual(f["roe"], 90.7 / 361.9, places=4)
        pb_pe = {k: v for k, v in self.INFO.items() if k not in ("trailingEps", "bookValue")}
        self.assertAlmostEqual(extract_fundamentals(pb_pe)["roe"], 9.2 / 36.7, places=4)
        self.assertIsNone(extract_fundamentals({"trailingEps": 500, "bookValue": 10})["roe"])         # absurd 5000% ROE is treated as missing
        self.assertFalse(extract_fundamentals({"returnOnEquity": .2})["roe_derived"])

    def test_valuation_is_not_a_flat_bonus(self):
        mid = self._score()["components"]["valuation"]["points"]
        self.assertLess(mid, 8.5)                                                                    # was 9.57 for a P/E of 28.6
        dear = dict(self.INFO, forwardPE=70.0, trailingPE=75.0); cheap = dict(self.INFO, forwardPE=14.0, trailingPE=15.0)
        self.assertLess(self._score(dear)["components"]["valuation"]["points"], mid); self.assertGreater(self._score(cheap)["components"]["valuation"]["points"], mid)
        nogrowth = score_stock(self.META, extract_fundamentals(dict(self.INFO, earningsGrowth=-.1, revenueGrowth=-.05)), self.TECH, {"status": "ok"}, W, {"rev_cagr": -.02, "ni_cagr": -.05, "years": 3})
        self.assertLess(nogrowth["components"]["valuation"]["points"], 5)                            # growth cannot justify the multiple

    def test_pullback_toward_100dma_inside_an_uptrend_is_in_range_not_a_weak_trend(self):
        z = decision.entry_zones(self.TECH)
        self.assertEqual(z["position"], "in_range"); self.assertLess(z["ideal_buy_zone"][0], 3378.0)  # the range reaches down to the 100-DMA support
        st, why = decision.classify({"total": 80.0, "data_confidence_pct": 90}, {"score": 60, "avoid": []}, fresh_ok(), "unreviewed", self.TECH, z)
        self.assertEqual(st, "ACCUMULATE CANDIDATE"); self.assertNotIn("weak trend", " ".join(why))

    def test_slipping_below_support_while_above_200dma_is_watch_with_accurate_wording(self):
        t = dict(self.TECH, last=3000.0, dma200=2700.0)                      # 11% under the 100-DMA but still above a rising 200-DMA
        z = decision.entry_zones(t); self.assertEqual(z["position"], "below")
        st, why = decision.classify({"total": 80.0, "data_confidence_pct": 90}, {"score": 60, "avoid": []}, fresh_ok(), "ok", t, z)
        self.assertEqual(st, "WATCH"); self.assertNotIn("weak trend", " ".join(why)); self.assertIn("support", " ".join(why))

    def test_downtrend_zone_is_still_around_the_50dma_only(self):
        z = decision.entry_zones(dict(self.TECH, dma50=90.0, dma100=95.0, dma200=100.0, last=88.0, resistance=120.0, atr=2.0))
        self.assertAlmostEqual(z["ideal_buy_zone"][0], 90.0 * 0.98, places=1); self.assertAlmostEqual(z["ideal_buy_zone"][1], 90.0 * 1.02, places=1)

    def test_old_format_cache_entries_are_refreshed_so_new_fields_take_effect(self):
        from mis import run as rr
        calls = {"n": 0}
        class P:
            tripped = False
            def info(self, t): calls["n"] += 1; return dict(TestRealPageRegressions.INFO)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        cache = {"A.NS": {"available": True, "roe": None, "retrieved_at": now}}                      # saved by the previous version, 0 days old
        out = rr.fundamentals_cached(P(), "A.NS", cache)
        self.assertEqual(calls["n"], 1); self.assertTrue(out["roe_derived"])                         # refreshed despite being recent
        rr.fundamentals_cached(P(), "A.NS", cache); self.assertEqual(calls["n"], 1)                  # the new-format copy is then reused

    def test_headlines_must_name_the_company(self):
        from mis import news
        name = "Ajanta Pharmaceuticals Ltd."
        self.assertEqual(news.key_word(name), "ajanta")
        self.assertTrue(news.relevant("Pharma Q1 FY27: Ajanta Revenue Up 25%, Ipca Profit Up 72% - Kalkine India", name))
        self.assertFalse(news.relevant("Is Venus Remedies the Best Stock in Its Sector? A Look at the Numbers - Univest", name))
        self.assertFalse(news.relevant("Top 14 Pharma Stocks To Buy In India October 2026 - Samco", name))
        self.assertEqual(news.key_word("Bharat Electronics Ltd."), "electronics")     # generic first words are skipped
        self.assertFalse(news.relevant("anything", ""))



class TestAutomation(unittest.TestCase):
    def test_fill_repeats_until_every_company_is_screened_then_stops(self):
        from mis.run import fill_until_complete
        seq = [{"health": {"notes": ["Screening is filling in gradually: 150 of 394 companies have data"]}},
               {"health": {"notes": ["Screening is filling in gradually: 300 of 394"]}},
               {"health": {"notes": ["Screened 394 companies"]}}, {"health": {"notes": []}}]
        forces = []
        def fake(force): forces.append(force); return seq[len(forces) - 1]
        ctx, n = fill_until_complete(fake)
        self.assertEqual(n, 3); self.assertEqual(forces, [False, True, True])                # later passes must bypass "already done today"

    def test_fill_stops_on_rate_limit_holiday_skip_and_pass_limit(self):
        from mis.run import fill_until_complete
        self.assertEqual(fill_until_complete(lambda force: {"health": {"notes": ["Screening is filling in gradually", "Yahoo Finance rate-limited this connection"]}})[1], 1)
        self.assertEqual(fill_until_complete(lambda force: {"skipped": True})[1], 1)
        self.assertEqual(fill_until_complete(lambda force: {"health": {"notes": ["Screening is filling in gradually"]}}, max_passes=4)[1], 4)

    def test_no_email_is_sent_while_screening_is_incomplete(self):
        sb = Sandbox(email_ok=True)
        real_load = sb.r.load_config
        def small():
            c = real_load(); c["universe"]["max_new_fetches_per_run"] = 45; return c       # 60 companies, 45 fetched -> 15 deferred
        sb.r.load_config = small
        try:
            ctx = sb.run()
            self.assertTrue(any("filling in gradually" in n for n in ctx["health"]["notes"]))
            self.assertEqual(sb.sent, [], "must not email on partial screening")
            self.assertFalse((sb.tmp / "state" / "alert_state.json").exists(), "alerts stay pending until a complete run")
            self.assertEqual(json.loads((sb.tmp / "docs" / "status.json").read_text())["email"]["status"], "deferred")
        finally:
            sb.r.load_config = real_load; sb.close()

    def test_setup_script_dry_run_writes_correct_launchers_and_changes_nothing_else(self):
        import subprocess, sys as _sys
        tmp = Path(tempfile.mkdtemp()); (tmp / "scripts").mkdir(); shutil.copy(ROOT / "scripts" / "setup_local.py", tmp / "scripts" / "setup_local.py")
        venv = tmp / "somewhere" / "mis-venv"
        r = subprocess.run([_sys.executable, str(tmp / "scripts" / "setup_local.py"), "--dry-run", "--venv", str(venv), "--time", "18:15", "--port", "8123"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        run_bat = (tmp / "run-mis.bat").read_text(); open_bat = (tmp / "Open-MIS.bat").read_text()
        self.assertIn("-m mis.run --fill", run_bat); self.assertIn("logs\\mis.log", run_bat); self.assertIn(str(venv), run_bat)
        self.assertIn("http.server 8123", open_bat); self.assertIn("--directory docs", open_bat)
        self.assertFalse(venv.exists(), "dry run must not create the environment"); self.assertIn("dry run", r.stdout)



@unittest.skipUnless(shutil.which("node"), "node needed")
class TestEncryptedHoldingsForEmail(unittest.TestCase):
    def test_pipeline_reads_encrypted_holdings_with_passphrase_secret_only(self):
        import subprocess
        from mis import run as rr
        tmp = Path(tempfile.mkdtemp()); (tmp / "docs").mkdir(); (tmp / "mis").mkdir()
        for f in ("review_cli.js", "cloud.js", "ledger.js", "dashboard_logic.js"): shutil.copy(ROOT / "mis" / f, tmp / "mis" / f)
        js = ("const K=require('./mis/cloud.js');(async()=>{process.stdout.write(JSON.stringify(await K.encryptJSON({rev:1,data:{tx:[{date:'2025-01-02',type:'buy',ticker:'AAA',qty:10,price:50,fees:0}]}},'my long secret phrase 99')))})()")
        enc = subprocess.run(["node", "-e", js], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        (tmp / "docs" / "holdings.enc.json").write_text(enc)
        stock = {"ticker": "AAA.NS", "name": "AAA", "sector": "IT", "cap": "M", "price": 100, "fresh": True, "status": "HOLD", "research": 70, "confidence": {"label": "Medium", "limits": []},
                 "gov": "ok", "atr": 2, "chg1d": 1, "zones": {"ideal": [90, 110], "thesis_review": 80, "trading_stop": 90}}
        snap = {"rules": {"minPositions": 10, "maxSingle": 8, "maxSector": 30, "maxSmall": 50, "concCapBuilding": 20}, "stocks": [stock]}
        old_root = rr.ROOT; rr.ROOT = tmp
        try:
            os.environ.pop("MIS_HOLDINGS_JSON", None); os.environ.pop("MIS_PASSPHRASE", None)
            self.assertIsNone(rr.private_portfolio(snap), "without the passphrase secret nothing may be read")
            os.environ["MIS_PASSPHRASE"] = "my long secret phrase 99"; out = rr.private_portfolio(snap)
            self.assertEqual((out["count"], out["value"], out["invested"]), (1, 1000, 500))
            os.environ["MIS_PASSPHRASE"] = "the wrong phrase entirely"; self.assertIn("could not be read", rr.private_portfolio(snap)["error"])
        finally:
            rr.ROOT = old_root; os.environ.pop("MIS_PASSPHRASE", None)



@unittest.skipUnless(shutil.which("node"), "node needed")
class TestPublicHoldingsForEmail(unittest.TestCase):
    def test_plain_public_holdings_file_needs_no_secret(self):
        from mis import run as rr
        tmp = Path(tempfile.mkdtemp()); (tmp / "docs").mkdir(); (tmp / "mis").mkdir()
        for f in ("review_cli.js", "cloud.js", "ledger.js", "dashboard_logic.js"): shutil.copy(ROOT / "mis" / f, tmp / "mis" / f)
        stock = {"ticker": "AAA.NS", "name": "AAA", "sector": "IT", "cap": "M", "price": 100, "fresh": True, "status": "HOLD", "research": 70, "confidence": {"label": "Medium", "limits": []},
                 "gov": "ok", "atr": 2, "chg1d": 1, "zones": {"ideal": [90, 110], "thesis_review": 80, "trading_stop": 90}}
        snap = {"rules": {"minPositions": 10, "maxSingle": 8, "maxSector": 30, "maxSmall": 50, "concCapBuilding": 20}, "stocks": [stock]}
        old_root = rr.ROOT; rr.ROOT = tmp
        for k in ("MIS_HOLDINGS_JSON", "MIS_PASSPHRASE"): os.environ.pop(k, None)
        try:
            self.assertIsNone(rr.private_portfolio(snap), "no file, no secret: nothing to read")
            (tmp / "docs" / "holdings.json").write_text(json.dumps({"v": 1, "rev": 3, "data": {"tx": [{"date": "2025-01-02", "type": "buy", "ticker": "AAA", "qty": 10, "price": 50, "fees": 0}]}}))
            out = rr.private_portfolio(snap); self.assertEqual((out["count"], out["value"], out["invested"]), (1, 1000, 500))
            (tmp / "docs" / "holdings.json").write_text("{not json"); self.assertIn("unreadable", rr.private_portfolio(snap)["error"])
        finally:
            rr.ROOT = old_root


class TestPackaging(unittest.TestCase):
    def test_requirements_lists_every_third_party_package_the_code_imports(self):
        req = (ROOT / "requirements.txt").read_text().lower()
        self.assertGreater(len(req.strip()), 20, "requirements.txt must never ship empty")
        import re
        third_party = set()
        for f in (ROOT / "mis").glob("*.py"):
            for m in re.finditer(r"^\s*(?:import|from)\s+([a-zA-Z_][\w]*)", f.read_text(), re.M):
                third_party.add(m.group(1).lower())
        mapping = {"yaml": "pyyaml", "pandas": "pandas", "numpy": "numpy", "yfinance": "yfinance", "requests": "requests"}
        for mod, pkg in mapping.items():
            if mod in third_party or mod == "yfinance":
                self.assertIn(pkg, req, f"{pkg} is imported by the code but missing from requirements.txt")


if __name__ == "__main__":
    unittest.main()
