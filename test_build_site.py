#!/usr/bin/env python3
"""Tests for tools/build_site.py: the view model (status by day on the list, levels, results in words) and the HTML."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
import build_site as bs  # noqa: E402
import evaluate_signals as ev  # noqa: E402

LAST_BAR = "2026-09-08"


def _signal(ticker, pattern, status, entry, stop, target, score=80, **kw):
    base = {"ticker": ticker, "pattern": pattern, "status": status, "entry": entry, "stop": stop,
            "risk_pct": round((entry - stop) / entry * 100, 2), "target": target, "score": score,
            "last_close": entry, "last_date": LAST_BAR, "bars_since_break": 0 if status == "CONFIRMED" else None,
            "volume_ratio": 1.8 if status == "CONFIRMED" else None,
            "trend": "close above SMA200, SMA50 > SMA200, SMA200 rising/flat",
            "notes": "LS 2026-07-02 @32.44, head 2026-07-30 @30.84, RS 2026-08-26 @32.88",
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
                                                     "Bullish Wolfe Wave": 8},
                     "max_listed_days": {"Cup & Handle": 6, "Inverse Head & Shoulders": 6, "Bullish Wolfe Wave": 5}},
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


def test_grade_and_status_by_day_on_the_list():
    ihs = "Inverse Head & Shoulders"
    assert bs.grade(ihs, 1, 6) == ("enter", "New today")
    assert bs.grade(ihs, 2, 6) == ("enter", "Day 2 of 6")
    assert bs.grade(ihs, 3, 6) == ("late", "Day 3 of 6: late, smaller edge") and bs.grade(ihs, 6, 6)[0] == "late"
    assert bs.grade(ihs, 7, 6) == ("skip", "Day 7: too late to enter")
    assert bs.grade("Bullish Wolfe Wave", 6, 5)[0] == "skip" and bs.grade("Cup & Handle", 4, 6)[0] == "late"
    assert bs.grade("Cup & Handle", None) == ("enter", "First report unknown")
    assert bs.grade(ihs, 2) == ("enter", "Day 2 of 6")                          # limit defaults from NO_ENTRY_FROM
    assert bs.late_note(ihs, "enter", 1) == ""
    assert bs.late_note(ihs, "late", 4).startswith("This signal is on its day 4")
    assert "Do not buy" in bs.late_note("Bullish Wolfe Wave", "skip", 6)
    assert [bs.fg_zone(x) for x in (None, 5, 20, 39.9, 60, 80, 99)] == \
        [None, "extreme fear", "fear", "fear", "greed", "extreme greed", "extreme greed"]


def test_view_model_setups_levels_and_notes():
    vm = bs.view_model(_doc(), _evaluation(), dt.date(2026, 9, 9))
    by = {v["ticker"]: v for v in vm["setups"]}
    assert list(by) == ["HAL", "NEW", "WW"]                                   # score order
    hal = by["HAL"]
    assert (hal["day"], hal["grade"], hal["list_limit"]) == (4, "late", 6)
    assert hal["status"] == "Day 4 of 6: late, smaller edge"
    assert (hal["risk_pct"], hal["reward_pct"], hal["age"], hal["age_limit"]) == (11.3, 14.0, 6, 8)
    assert hal["note"].startswith("This signal is on its day 4") and hal["explained"].startswith("Three lows")
    assert ("Breakout volume 0.90×, below average", "warn") in hal["chips"]
    assert ("Fear and greed 74, greed", "warn") in hal["chips"] and ("Market: bull trend", "good") in hal["chips"]
    assert hal["reference"]["trades"] == 1097
    new = by["NEW"]
    assert (new["day"], new["grade"], new["status"], new["note"]) == (1, "enter", "New today", "")
    ww = by["WW"]
    assert (ww["day"], ww["grade"], ww["status"]) == (6, "skip", "Day 6: too late to enter")
    assert ww["target"] is None and ww["reward_pct"] is None
    assert ("Fear and greed 85, extreme greed", "bad") in ww["chips"]
    (ph,) = vm["watchlist"]
    assert (ph["trigger"], ph["last_close"], ph["to_trigger_pct"], ph["fg_zone"]) == (980.43, 960.0, 2.1, "fear")
    assert vm["closed"][0]["plain"] == "closed below its stop" and vm["scan"]["stale_days"] == 1
    assert vm["market"]["regime"] == "bull" and vm["generated"] == "2026-09-09"


def test_day_on_list_prefers_the_scanner_then_the_track_record():
    sig = _signal("HAL", "Inverse Head & Shoulders", "CONFIRMED", 36.8, 32.64, 41.94)
    rows = _evaluation()["rows"]
    assert bs.day_on_list(sig, rows) == 4
    stale = [{**r, "last_listed": "2026-09-04"} for r in rows]                # track record built before this bar
    assert bs.day_on_list(sig, stale) is None
    assert bs.day_on_list({**sig, "stop": 1.0}, rows) is None                 # unknown structure
    assert bs.day_on_list({**sig, "listed_day": 3}, stale) == 3               # the scanner's own count wins
    assert bs.day_on_list({**sig, "listed_day": None}, rows) == 4


def test_results_in_words_and_the_tally():
    assert bs.result_text(_row("A", "Cup & Handle", "2026-09-03", 90.0, "target", 2.0, exit_=120.0, pnl=20.0)) == \
        ("win", "Took profit at 120.00 on 2026-09-03")
    assert bs.result_text(_row("A", "Cup & Handle", "2026-09-03", 90.0, "stop", -1.0, exit_=88.67, pnl=-1.5)) == \
        ("loss", "Stopped out at 88.67 on 2026-09-03")
    assert bs.result_text(_row("A", "Cup & Handle", "2026-09-03", 90.0, "expired", 0.2, exit_=102.0, pnl=2.0)) == \
        ("win", "Time limit reached: closed at 102.00 on 2026-09-03")
    flat = _row("A", "Cup & Handle", "2026-09-03", 90.0, "expired", 0.0, exit_=100.0, pnl=0.0)
    assert bs.result_text(flat)[0] == "flat"
    assert bs.result_text(_row("A", "Cup & Handle", "2026-09-03", 90.0, "open", 0.1, exit_=101.0, pnl=1.0)) == \
        ("open", "Still open: last close 101.00 on 2026-09-03")
    assert bs.result_text(_row("A", "Cup & Handle", "2026-09-03", 90.0, "gap", None, fill=108.0)) == \
        ("none", "Not bought: it opened at 108.00, above the buy limit")
    assert bs.result_text(_row("A", "Cup & Handle", "2026-09-03", 90.0, "below_stop", None, fill=89.0))[1] == \
        "Not bought: it opened at 89.00, below the stop loss"
    assert bs.result_text(_row("A", "Cup & Handle", "2026-09-03", 90.0, "no_data", None, fill=None)) == \
        ("pending", "Signal from the last scan: the buy happens at the next open")
    res = bs.results_view(_evaluation())
    assert [(r["ticker"], r["label"]) for r in res["rows"]] == [
        ("WW", "open"), ("CL", "loss"), ("HAL", "open"), ("GAP", "none"), ("WIN", "win"), ("NEW", "pending")]
    assert res["summary"] == {"n": 6, "wins": 1, "losses": 1, "flat": 0, "open": 2, "not_bought": 1, "pending": 1,
                              "avg_pnl_pct": 9.2, "since": "2026-09-01"}     # (20.0 - 1.52) / 2 on the closed ones
    assert bs.results_view(None) == {"available": False, "rows": [], "summary": None}
    t = bs.track_view(_evaluation())
    assert t["curve"] == [0.1, -0.9, -1.06, 0.94] and t["rows"][1]["label"] == "Stopped out at 88.67 on 2026-09-02"


def test_render_page_reads_top_to_bottom_and_escapes():
    vm = bs.view_model(_doc(), _evaluation(), dt.date(2026, 9, 9))
    page = bs.render_page(vm)
    assert page.startswith("<!doctype html>") and "<style>" in page and "<script>" in page
    assert "Cup &amp; Handle" in page and "Inverse Head &amp; Shoulders" in page and "S&amp;P 500" in page
    # The three sections in order, the instruction before the first table.
    now, why, results, how = (page.index(x) for x in ('id="now"', 'id="why"', 'id="results"', 'id="how"'))
    assert now < why < results < how
    assert "Today: 3 buy signals · 1 stock watched · past signals: 1 won, 1 lost, 2 still open." in page
    assert "<strong>How to act.</strong> Buy at the next market open" in page
    assert page.index("How to act.") < page.index('<table class="signals">')
    assert 'href="#why-HAL"' in page and 'id="why-HAL"' in page
    assert "<strong>37.68</strong>" in page and "11.3 % below" in page and "+14.0 %" in page
    assert 'class="badge badge-late">Day 4 of 6: late, smaller edge' in page
    assert 'class="badge badge-enter">New today' in page and 'class="badge badge-skip">Day 6: too late to enter' in page
    assert "Three lows with the middle one the deepest" in page and "<strong>Here:</strong> LS 2026-07-02" in page
    assert "Bull trend" in page and "VIX 15.7" in page and "63% of stocks above their 200-day average" in page
    assert "Needs a close above" in page
    assert "Left the page since the previous scan: FIS (closed below its stop)." in page
    assert "<strong>1 took profit</strong>" in page and "<strong>1 stopped out</strong>" in page
    assert "2 still open, 1 not bought, 1 pending." in page and 'class="badge badge-pending">Pending' in page
    assert "The breakout is the last session; the row is dropped after 8." in page
    assert "Stopped out at 88.67 on 2026-09-02" in page and "Took profit at 120.00 on 2026-09-03" in page
    assert "Not bought: it opened at 108.00, above the buy limit" in page
    assert 'class="badge badge-win">Win' in page and 'class="badge badge-loss">Loss' in page
    assert "In units of risk (R), for the curious" in page and 'data-status="open"' in page
    assert "Not investment advice." in page and "How to read this page" in page and "1097" in page
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
    assert "No buy signal today. Nothing to do." in page and "Nothing is being watched right now." in page
    assert "The results are not available in this build" in page and "Today: 0 buy signals · 0 stocks watched." in page
    assert bs.main(["--signals", str(sig), "--out-dir", str(out), "--today", "2026-09-09"]) == 0


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def _series(n=30, base=36.0, end=LAST_BAR):
    dates = [str(d.date()) for d in pd.bdate_range(end=end, periods=n)]
    closes = [round(base + (i % 5) * 0.3 - 0.6, 2) for i in range(n)]
    opens = [round(c - 0.2, 2) for c in closes]
    return {"dates": dates, "open": opens, "high": [round(c + 0.5, 2) for c in closes],
            "low": [round(c - 0.7, 2) for c in closes], "close": closes}


def test_pivots_parse_every_pattern_note():
    cup = ("left rim 2026-05-07 @97.30, bottom 2026-07-08 @74.63 (depth 23%), right rim 2026-08-14 @97.34, "
           "handle low 2026-08-20 @92.01 (depth 5.5%), trigger 95.99")
    assert bs._pivots(cup) == [("left rim", "2026-05-07", 97.3), ("bottom", "2026-07-08", 74.63),
                               ("right rim", "2026-08-14", 97.34), ("handle low", "2026-08-20", 92.01)]
    ihs = "LS 2026-07-02 @32.44, head 2026-07-30 @30.84, RS 2026-08-26 @32.88, neckline 36.03->35.91 (now 35.86)"
    assert bs._pivots(ihs) == [("LS", "2026-07-02", 32.44), ("head", "2026-07-30", 30.84), ("RS", "2026-08-26", 32.88)]
    wolfe = "1 2026-06-02 @100.00, 2 2026-06-16 @108.00, 5 2026-07-28 @91.50, line 1-3 at the ETA 2026-09-01"
    assert bs._pivots(wolfe) == [("1", "2026-06-02", 100.0), ("2", "2026-06-16", 108.0), ("5", "2026-07-28", 91.5)]
    assert bs._pivots("") == [] and bs._pivots(None) == []


def test_chart_svg_draws_candles_levels_and_pivots():
    series = _series(30)
    levels = {"entry": 36.8, "max_buy": 37.68, "stop": 32.64, "target": 41.94}
    svg = bs.chart_svg(series, levels, [("RS", series["dates"][-9], 35.9), ("LS", "2020-01-01", 1.0)], "HAL")
    assert svg.startswith('<svg class="chart"') and 'aria-label="HAL, daily bars' in svg
    assert svg.count('class="wick"') == 30 and svg.count('class="up"') + svg.count('class="down"') == 30
    assert 'class="zone"' in svg and 'class="stop"' in svg and "stop loss 32.64" in svg
    assert 'class="target"' in svg and ">take profit 41.94<" in svg
    assert svg.count('class="pivot"') == 1 and ">RS<" in svg and ">LS<" not in svg     # outside the window: skipped
    assert series["dates"][0] in svg and series["dates"][-1] in svg                    # the date axis
    far = bs.chart_svg(series, {**levels, "target": 90.0}, [], "HAL")
    assert "take profit 90.00, above this chart" in far and 'class="target"' not in far   # scale kept for the bars
    bare = bs.chart_svg(series, {}, [], "X")
    assert 'class="zone"' not in bare and 'class="stop"' not in bare and bare.count('class="wick"') == 30
    one = {"dates": ["2026-09-08"], "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]}
    assert bs.chart_svg(one, levels, [], "X") == ""
    assert bs.chart_svg({**series, "close": series["close"][:-1]}, levels, [], "X") == ""   # ragged input


def test_page_carries_charts_when_the_bars_are_there(tmp_path):
    charts = {"bars": 30, "as_of": LAST_BAR, "symbols": {"HAL": _series(30), "PH": _series(30, base=950.0)}}
    vm = bs.view_model(_doc(), _evaluation(), dt.date(2026, 9, 9), charts)
    hal = next(v for v in vm["setups"] if v["ticker"] == "HAL")
    assert hal["chart"]["dates"][-1] == LAST_BAR and hal["pivots"][2] == ("RS", "2026-08-26", 32.88)
    assert vm["charts_as_of"] == LAST_BAR and next(v for v in vm["setups"] if v["ticker"] == "NEW")["chart"] is None
    page = bs.render_page(vm)
    assert page.count('<svg class="chart"') == 2                     # HAL's why-block and PH's watched entry
    assert 'aria-label="HAL, daily bars' in page and 'aria-label="PH, daily bars' in page
    assert "Their charts and pattern anchors" in page
    without = bs.render_page(bs.view_model(_doc(), _evaluation(), dt.date(2026, 9, 9)))
    assert '<svg class="chart"' not in without
    sig, ch = tmp_path / "signals.json", tmp_path / "charts.json"
    sig.write_text(json.dumps(_doc()))
    ch.write_text(json.dumps(charts))
    assert bs.main(["--signals", str(sig), "--charts", str(ch), "--out-dir", str(tmp_path / "s"),
                    "--today", "2026-09-09"]) == 0
    assert (tmp_path / "s" / "index.html").read_text().count('<svg class="chart"') == 2
