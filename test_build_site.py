#!/usr/bin/env python3
"""Tests for tools/build_site.py: the view model (grades by day on the list, levels, track record) and the HTML."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
import build_site as bs  # noqa: E402
import evaluate_signals as ev  # noqa: E402

LAST_BAR = "2026-09-08"


def _signal(ticker, pattern, status, entry, stop, target, score=80, **kw):
    base = {"ticker": ticker, "pattern": pattern, "status": status, "entry": entry, "stop": stop,
            "risk_pct": round((entry - stop) / entry * 100, 2), "target": target, "score": score,
            "last_close": entry, "last_date": LAST_BAR, "bars_since_break": 0 if status == "CONFIRMED" else None,
            "volume_ratio": 1.8 if status == "CONFIRMED" else None,
            "trend": "close above SMA200, SMA50 > SMA200, SMA200 rising/flat", "notes": "LS 2026-07-02 @32.44",
            "max_buy": round(entry * 1.05, 2),
            "reward_risk": round((target - entry) / (entry - stop), 2) if target else None, "fear_greed": 55.0}
    base.update(kw)
    return base


def _doc():
    return {"meta": {"run_date": "2026-09-09 06:00", "last_bar": LAST_BAR, "scanned": 502, "universe": 503,
                     "errors": 1, "profile": "tuned",
                     "market": {"index": "SPY", "index_vs_sma200_pct": 7.82, "regime": "bull", "vix": 15.72,
                                "breadth": 0.6287},
                     "max_breakout_age_by_pattern": {"Cup & Handle": 3, "Inverse Head & Shoulders": 8,
                                                     "Bullish Wolfe Wave": 8}},
            "signals": [
                _signal("HAL", "Inverse Head & Shoulders", "CONFIRMED", 36.8, 32.64, 41.94, 87, bars_since_break=6,
                        volume_ratio=0.9, fear_greed=73.6, max_buy=37.68),
                _signal("NEW", "Inverse Head & Shoulders", "CONFIRMED", 100.0, 90.0, 130.0, 70),
                _signal("WW", "Bullish Wolfe Wave", "CONFIRMED", 50.0, 48.0, None, 65, fear_greed=85.0),
                _signal("PH", "Cup & Handle", "WATCHLIST", 980.43, 921.31, 1168.83, 75, last_close=960.0,
                        fear_greed=20.4)],
            "closed": [{"ticker": "FIS", "pattern": "Inverse Head & Shoulders", "was": "WATCHLIST",
                        "since": "2026-09-04", "entry": 43.12, "stop": 39.59, "target": 49.65, "outcome": "FAILED",
                        "detail": "close 39.42 on 2026-09-08 at or below stop 39.59"}]}


def _row(ticker, pattern, last_date, stop, outcome, r, listed_days=1, last_listed=None, fill=100.0, exit_=None,
         pnl=None, bars=0):
    return {"ticker": ticker, "pattern": pattern, "last_date": last_date, "entry": 100.0, "max_buy": 105.0,
            "stop": stop, "target": 120.0, "score": 80, "first_seen": last_date, "listed_days": listed_days,
            "last_listed": last_listed or last_date, "fill": fill, "fill_date": last_date, "outcome": outcome,
            "bars": bars, "exit": exit_, "exit_date": last_date if exit_ is not None else None, "r": r, "pnl_pct": pnl}


def _evaluation():
    rows = [_row("CL", "Bullish Wolfe Wave", "2026-09-02", 88.67, "stop", -1.0, 2, "2026-09-03", 90.04, 88.67,
                 -1.52, 2),
            _row("HAL", "Inverse Head & Shoulders", "2026-09-02", 32.64, "open", -0.16, 4, LAST_BAR, 37.57, 36.8,
                 -2.05, 3),
            _row("WIN", "Cup & Handle", "2026-09-03", 90.0, "target", 2.0, 1, None, 100.0, 120.0, 20.0, 5),
            _row("GAP", "Cup & Handle", "2026-09-03", 90.0, "gap", None, 1, None, 108.0),
            _row("WW", "Bullish Wolfe Wave", "2026-09-01", 48.0, "open", 0.1, 6, LAST_BAR, 50.2, 50.4, 0.4, 5),
            _row("NEW", "Inverse Head & Shoulders", LAST_BAR, 90.0, "no_data", None, 1, LAST_BAR, None)]
    return {"summary": ev.summarise(rows), "horizon": 60, "rows": rows}


def test_grade_by_day_on_the_list():
    assert bs.grade("Inverse Head & Shoulders", 1) == ("enter", "New today")
    assert bs.grade("Inverse Head & Shoulders", 2) == ("enter", "Day 2 on the list")
    assert bs.grade("Inverse Head & Shoulders", 3)[0] == "late" and bs.grade("Inverse Head & Shoulders", 6)[0] == "late"
    assert bs.grade("Inverse Head & Shoulders", 7) == ("skip", "Day 7 on the list: no entry")
    assert bs.grade("Bullish Wolfe Wave", 6)[0] == "skip" and bs.grade("Cup & Handle", 4)[0] == "late"
    assert bs.grade("Cup & Handle", None) == ("enter", "First report unknown")
    assert [bs.fg_zone(x) for x in (None, 5, 20, 39.9, 60, 80, 99)] == \
        [None, "extreme fear", "fear", "fear", "greed", "extreme greed", "extreme greed"]


def test_view_model_setups_levels_and_actions():
    vm = bs.view_model(_doc(), _evaluation(), dt.date(2026, 9, 9))
    by = {v["ticker"]: v for v in vm["setups"]}
    assert list(by) == ["HAL", "NEW", "WW"]                                   # score order
    hal = by["HAL"]
    assert (hal["day"], hal["grade"], hal["badge"]) == (4, "late", "Day 4 on the list: late")
    assert (hal["risk_pct"], hal["reward_pct"], hal["age"], hal["age_limit"]) == (11.3, 14.0, 6, 8)
    assert "Only at or below 37.68" in hal["action"] and "Stop 32.64" in hal["action"]
    assert ("Volume 0.9×, below average", "warn") in hal["chips"]
    assert ("Fear and greed 74, greed", "warn") in hal["chips"] and ("Market: bull regime", "good") in hal["chips"]
    assert hal["reference"]["trades"] == 1097
    new = by["NEW"]
    assert (new["day"], new["grade"], new["badge"]) == (1, "enter", "New today")
    assert new["action"].startswith("Buy at the next open only if it prints at or below 105.00.")
    ww = by["WW"]
    assert (ww["day"], ww["grade"]) == (6, "skip") and ww["action"].startswith("No entry, day 6")
    assert ww["target"] is None and ww["reward_pct"] is None
    assert ("Fear and greed 85, extreme greed", "bad") in ww["chips"]
    (ph,) = vm["watchlist"]
    assert (ph["trigger"], ph["last_close"], ph["to_trigger_pct"], ph["fg_zone"]) == (980.43, 960.0, 2.1, "fear")
    assert vm["closed"][0]["label"] == "Stop hit" and vm["scan"]["stale_days"] == 1
    assert vm["market"]["regime"] == "bull" and vm["generated"] == "2026-09-09"


def test_day_on_list_needs_the_signals_own_session():
    sig = _signal("HAL", "Inverse Head & Shoulders", "CONFIRMED", 36.8, 32.64, 41.94)
    rows = _evaluation()["rows"]
    assert bs.day_on_list(sig, rows) == 4
    stale = [{**r, "last_listed": "2026-09-04"} for r in rows]                # track record built before this bar
    assert bs.day_on_list(sig, stale) is None
    assert bs.day_on_list({**sig, "stop": 1.0}, rows) is None                 # unknown structure


def test_track_record_rows_statuses_and_curve():
    t = bs.track_view(_evaluation())
    assert t["available"] and t["since"] == "2026-09-01"
    assert [(r["ticker"], r["status"]) for r in t["rows"]] == [
        ("WW", "open"), ("CL", "closed"), ("HAL", "open"), ("GAP", "none"), ("WIN", "closed"), ("NEW", "none")]
    assert t["curve"] == [0.1, -0.9, -1.06, 0.94]                              # gap and no-data rows add nothing
    assert t["rows"][3]["label"] == "Not traded: gap" and t["summary"]["total_r"] == 0.94
    assert bs.track_view(None) == {"available": False, "rows": [], "summary": None, "curve": [], "horizon": None,
                                   "since": None}
    svg = bs.sparkline(t["curve"])
    assert svg.count("<circle") == 4 and "+0.94 R after 4 trades" in svg


def test_render_page_escapes_and_carries_every_section():
    vm = bs.view_model(_doc(), _evaluation(), dt.date(2026, 9, 9))
    page = bs.render_page(vm)
    assert page.startswith("<!doctype html>") and "<style>" in page and "<script>" in page
    assert "Cup &amp; Handle" in page and "Inverse Head &amp; Shoulders" in page and "S&amp;P 500" in page
    assert 'id="setup-HAL"' in page and "36.80 to 37.68" in page and "11.3 % below entry" in page
    assert "+14.0 % from entry · 1.24 R" in page
    assert 'class="badge badge-late">Day 4 on the list: late' in page
    assert 'class="badge badge-enter">New today' in page
    assert 'class="badge badge-skip">Day 6 on the list: no entry' in page
    assert "Bull regime" in page and "VIX 15.7" in page and "63% of stocks above their SMA200" in page
    assert "<td>2026-09-02</td><td><strong>CL</strong></td>" in page and "Stopped" in page and "Target hit" in page
    assert "Hit rate 50% on 2 resolved" in page and "Not traded: gap" in page
    assert 'data-status="open"' in page and 'data-filter="closed"' in page
    assert "Heuristic scan, not investment advice." in page and "Day on the list" in page
    assert "1097" in page and "+0.43" in page                                  # replay reference tables
    frag = bs.render_page(vm, fragment=True)
    assert frag.startswith("<title>SignalSync</title>") and "<!doctype" not in frag and "<body>" not in frag


def test_build_writes_files_and_handles_an_empty_scan(tmp_path):
    sig = tmp_path / "signals.json"
    sig.write_text(json.dumps(_doc()))
    ev_path = tmp_path / "evaluation.json"
    ev_path.write_text(json.dumps(_evaluation()))
    out = tmp_path / "site"
    vm = bs.build(str(sig), str(ev_path), str(out), today=dt.date(2026, 9, 9))
    assert (out / "index.html").exists() and json.loads((out / "data.json").read_text())["setups"][0]["ticker"] == "HAL"
    assert len(vm["setups"]) == 3
    # No evaluation, no signals, a stale last bar: the page still renders and says so.
    sig.write_text(json.dumps({"meta": {"run_date": "2026-09-01 06:00", "last_bar": "2026-08-28"}, "signals": []}))
    vm = bs.build(str(sig), None, str(out), today=dt.date(2026, 9, 9))
    page = (out / "index.html").read_text()
    assert vm["scan"]["stale_days"] == 12 and "12 days old" in page
    assert "No confirmed breakout in the last scan" in page and "Nothing on the watchlist" in page
    assert "The track record is not available in this build" in page
    assert bs.main(["--signals", str(sig), "--out-dir", str(out), "--today", "2026-09-09"]) == 0
