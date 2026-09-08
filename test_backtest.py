#!/usr/bin/env python3
"""Tests for tools/backtest.py: no look-ahead, first-seen signals, fills, statistics and breakdowns (offline)."""

from __future__ import annotations

import os
import re
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
import backtest as bt  # noqa: E402
import scan  # noqa: E402
from test_scan import make_cup_and_handle  # noqa: E402


def test_walk_forward_finds_the_cup_on_its_breakout_day_without_look_ahead(mini_universe):
    cup = make_cup_and_handle()
    (today,) = scan.detect_cup_and_handle(cup, "CUP")          # breaks out at bar -2 (age 1 today)
    rows = bt.walk_forward(mini_universe, days=5, horizon=10)
    cups = [r for r in rows if r["ticker"] == "CUP"]
    assert len(cups) == 1                                        # one structure, seen once
    r = cups[0]
    assert r["scan_day"] == str(cup.index[-2].date()) == r["last_date"]   # first seen on the breakout day
    assert r["bars_since_break"] == 0 and r["stop"] == today.stop
    assert r["fill"] == round(float(cup["Open"].iloc[-1]), 2)   # filled at the next session's open
    assert r["outcome"] in ("open", "stop", "target") and r["bars"] == 1   # one bar after the fill exists
    for row in rows:
        assert row["last_date"] == row["scan_day"]               # nothing dated after its scan day
    assert {r["ticker"] for r in rows} <= {"CUP", "IHS", "WW"}   # controls never fire


def test_walk_forward_marks_gaps_and_no_data(mini_universe):
    cup = mini_universe["CUP"].copy()
    cup.loc[cup.index[-1], "Open"] = cup["Close"].iloc[-2] * 1.08     # opens 8 % above: no trade
    rows = bt.walk_forward({"CUP": cup}, days=5, horizon=10)
    assert [r["outcome"] for r in rows] == ["gap"] and rows[0]["r"] is None
    rows = bt.walk_forward({"CUP": cup.iloc[:-1]}, days=3, horizon=10)  # breakout on the very last bar
    assert [r["outcome"] for r in rows] == ["no_data"]


def test_walk_forward_does_not_trade_an_open_at_or_below_the_stop(mini_universe):
    """An open already through the stop is no trade (R would be undefined), counted next to the gaps."""
    cup = mini_universe["CUP"].copy()
    (today,) = scan.detect_cup_and_handle(cup, "CUP")          # seen at bar -2, filled at bar -1's open
    cup.loc[cup.index[-1], ["Open", "Low"]] = [today.stop - 0.01, today.stop - 0.5]
    (r,) = bt.walk_forward({"CUP": cup}, days=5, horizon=10)
    assert r["outcome"] == "below_stop" and r["r"] is None and r["fill"] == round(today.stop - 0.01, 2)
    stats = bt.breakdown([r])["overall"]
    assert (stats["below_stop"], stats["gap"], stats["n"], stats["mean_r"]) == (1, 0, 0, None)
    md = bt.render([r], bt.report_sections([r], 5, 10), 5, 10)
    assert "| all | 1 | 1 | 0 | 0 | 0 | - | - |" in md               # "Not traded" counts it


def test_walk_forward_bars_limits_what_each_scan_sees(mini_universe, monkeypatch):
    seen = []
    real = scan.scan_symbol

    def spy(sym, df, detectors=None):
        seen.append(len(df))
        return real(sym, df, detectors)

    monkeypatch.setattr(scan, "scan_symbol", spy)
    bt.walk_forward(mini_universe, days=3, horizon=5, bars=120)
    assert seen and set(seen) == {120}                            # every scan saw exactly the last 120 bars
    seen.clear()
    assert bt.walk_forward(mini_universe, days=3, horizon=5, bars=50) == [] and seen == []   # < 60 bars: skipped


def test_row_features_match_hand_computation(mini_universe):
    cup = mini_universe["CUP"]
    (s,) = scan.detect_cup_and_handle(cup, "CUP")
    atr_last = float(scan.atr(cup).iloc[-1])
    f = bt.row_features(cup, s, atr_last)
    assert set(f) == set(bt.FEATURE_KEYS)
    close = cup["Close"]
    s200, s50 = close.rolling(200).mean(), close.rolling(50).mean()
    assert f["close_vs_sma200"] == round(close.iloc[-1] / s200.iloc[-1] - 1, 4)
    assert f["sma50_vs_sma200"] == round(s50.iloc[-1] / s200.iloc[-1] - 1, 4)
    assert f["sma200_slope"] == round(s200.iloc[-1] / s200.iloc[-1 - bt.SLOPE_LOOKBACK] - 1, 4)
    assert f["dist_sma200_atr"] == round((close.iloc[-1] - s200.iloc[-1]) / atr_last, 3)
    assert f["stop_atr"] == round((s.entry - s.stop) / atr_last, 3) > 0
    assert f["target_atr"] == round((s.target - s.entry) / atr_last, 3) > 0
    anchor = cup.index.get_loc(pd.Timestamp(re.search(r"handle low (\S+)", s.notes)[1]))
    assert f["wait_bars"] == len(cup) - 1 - s.bars_since_break - anchor >= 1   # the handle low precedes the break
    # The breakout bar and the cup / handle volumes, recomputed from the frame and the notes.
    b = len(cup) - 1 - s.bars_since_break
    high, low, vol = (cup[c].to_numpy() for c in ("High", "Low", "Volume"))
    assert f["break_close_pos"] == round((close.iloc[b] - low[b]) / (high[b] - low[b]), 3)
    assert 0 <= f["break_close_pos"] <= 1
    assert f["break_over_prior_high"] == (1.0 if close.iloc[b] > high[b - 1] else 0.0)
    base = vol[b - scan.VOLUME_AVG_LEN:b]
    assert f["volume_z"] == round((vol[b] - base.mean()) / base.std(ddof=1), 2) > 1.0   # the fixture's 3x volume bar
    a = cup.index.get_loc(pd.Timestamp(re.search(r"left rim (\S+)", s.notes)[1]))
    rb = cup.index.get_loc(pd.Timestamp(re.search(r"right rim (\S+)", s.notes)[1]))
    assert f["handle_volume_ratio"] == round(vol[rb + 1:b].mean() / vol[a:rb + 1].mean(), 3)
    handle_v = vol[rb + 1:b]
    assert f["handle_volume_slope"] == round(np.polyfit(np.arange(len(handle_v)), handle_v, 1)[0] / handle_v.mean(), 4)
    bottom = float(re.search(r"bottom \S+ @([\d.]+)", s.notes)[1])
    rim_b = float(re.search(r"right rim \S+ @([\d.]+)", s.notes)[1])
    assert f["depth_atr"] == round((rim_b - bottom) / atr_last, 3) > 3
    # Too little history for the averages: those features are None, the ATR-based ones and the wait remain.
    short = bt.row_features(cup.iloc[-150:], s, atr_last)
    assert short["close_vs_sma200"] is None and short["sma200_slope"] is None and short["dist_sma200_atr"] is None
    assert short["sma50_vs_sma200"] is None
    assert short["stop_atr"] == f["stop_atr"] and short["wait_bars"] == f["wait_bars"]
    # No target (a Wolfe whose lines do not converge) and a zero ATR: nothing raises, nothing is invented.
    no_target = scan.Signal("T", "Bullish Wolfe Wave", "CONFIRMED", 100.0, 95.0, 5.0, None, 70, 100.0, "d", 0,
                            None, "", "5 2020-01-01 @95.00")
    g = bt.row_features(cup, no_target, 0.0)
    assert g["target_atr"] is None and g["stop_atr"] is None and g["wait_bars"] is None   # anchor date not in hist
    assert g["depth_atr"] is None and g["handle_volume_ratio"] is None                    # no anchors, not a cup
    assert g["break_close_pos"] is not None and g["volume_z"] is not None                 # the last bar still is a bar


def test_fear_greed_components_and_score():
    rising = scan.fear_greed(100 * 1.01 ** np.arange(300))          # accelerating rise: everything stretched up
    assert rising["rsi"] == 100.0 and rising["macd_pct"] > 90 and rising["bb_pctb"] > 0.5 and rising["score"] > 80
    falling = scan.fear_greed(100 * 0.99 ** np.arange(300))
    assert falling["rsi"] == 0.0 and falling["macd_pct"] < 10 and falling["bb_pctb"] < 0.5 and falling["score"] < 20
    flat = scan.fear_greed(np.full(300, 50.0))                       # never moved: neutral, and no bands
    assert flat == {"rsi": 50.0, "macd_pct": 50.0, "bb_pctb": None, "score": 50.0}
    short = scan.fear_greed(np.arange(10, dtype=float))              # too short for every component
    assert short == {"rsi": None, "macd_pct": None, "bb_pctb": None, "score": None}
    # RSI by hand on a 15-bar series: gains 1 on ten bars, losses 1 on four -> avg gain 10/14, avg loss 4/14 -> RS 2.5.
    steps = np.array([1, 1, 1, -1, 1, 1, -1, 1, 1, 1, -1, 1, 1, -1], dtype=float)
    assert scan._rsi(np.concatenate([[100.0], 100 + np.cumsum(steps)])) == round(100 - 100 / 3.5, 2)
    # %B is the close's position between the bands: outside them beyond 0 or 1.
    spike = np.concatenate([np.full(19, 100.0), [110.0]])
    fg = scan.fear_greed(np.concatenate([np.full(30, 100.0), spike]))
    assert fg["bb_pctb"] > 1.0 and fg["score"] is not None


def test_row_features_fear_greed_at_scan_day_and_base(mini_universe):
    cup = mini_universe["CUP"]
    (s,) = scan.detect_cup_and_handle(cup, "CUP")
    f = bt.row_features(cup, s, float(scan.atr(cup).iloc[-1]))
    close = cup["Close"].to_numpy()
    fg = scan.fear_greed(close)
    assert (f["fg_score"], f["fg_rsi"], f["fg_macd_pct"], f["fg_bb_pctb"]) == (
        fg["score"], fg["rsi"], fg["macd_pct"], fg["bb_pctb"])
    assert s.fear_greed is None                                       # a detector alone does not set it ...
    (sig,) = scan.scan_symbol("CUP", cup, detectors=(scan.detect_cup_and_handle,))
    assert sig.fear_greed == fg["score"]                              # ... scan_symbol does, once per symbol
    anchor = cup.index.get_loc(pd.Timestamp(re.search(r"handle low (\S+)", s.notes)[1]))
    assert f["fg_base"] == scan.fear_greed(close[:anchor + 1])["score"]
    assert 0 <= f["fg_base"] < f["fg_score"] <= 100                   # the base is fearful, the breakout greedy
    rows = bt.walk_forward(mini_universe, days=5, horizon=10)
    assert all(r["fg_score"] is not None and r["fg_base"] is not None for r in rows)
    assert all(r["fear_greed"] == r["fg_score"] for r in rows)        # the report's reading equals the feature
    md = bt.render(rows, bt.report_sections(rows, 5, 10), 5, 10)
    assert "| fear and greed at the scan day |" in md and "| fear and greed at the pattern's last low |" in md


def test_row_features_per_pattern(mini_universe):
    ihs, ww = mini_universe["IHS"], mini_universe["WW"]
    (si,) = scan.detect_inverse_hs(ihs, "IHS")
    fi = bt.row_features(ihs, si, float(scan.atr(ihs).iloc[-1]))
    anchors = re.search(r"LS \S+ @([\d.]+), head \S+ @([\d.]+), RS \S+ @([\d.]+)", si.notes)
    ls, head, rs = (float(x) for x in anchors.groups())
    assert fi["depth_atr"] == round((min(ls, rs) - head) / float(scan.atr(ihs).iloc[-1]), 3) > 0
    assert fi["handle_volume_ratio"] is None and fi["handle_volume_slope"] is None          # cups only
    (sw,) = scan.detect_bullish_wolfe(ww, "WW")
    fw = bt.row_features(ww, sw, float(scan.atr(ww).iloc[-1]))
    p1 = float(re.search(r"^1 \S+ @([\d.]+)", sw.notes)[1])
    p5 = float(re.search(r", 5 \S+ @([\d.]+);", sw.notes)[1])
    assert fw["depth_atr"] == round((p1 - p5) / float(scan.atr(ww).iloc[-1]), 3) > 0
    assert fw["break_over_prior_high"] in (0.0, 1.0) and fw["volume_z"] is not None


def test_walk_forward_rows_carry_replay_features(mini_universe):
    rows = bt.walk_forward(mini_universe, days=5, horizon=10)
    assert rows
    for r in rows:
        assert set(bt.FEATURE_KEYS) <= set(r)
        assert r["stop_atr"] > 0 and r["wait_bars"] >= 1 and r["close_vs_sma200"] is not None


def test_walk_forward_members_and_end(mini_universe):
    sessions = sorted({d for df in mini_universe.values() for d in df.index})
    assert bt.scan_sessions(mini_universe, 5) == sessions[-5:]
    end = str(sessions[-3].date())
    assert bt.scan_sessions(mini_universe, 5, end) == sessions[-7:-2]      # the five sessions on or before end
    assert bt.scan_sessions(mini_universe, 10_000) == sessions             # more days than sessions: all of them
    rows = bt.walk_forward(mini_universe, days=5, horizon=10, members=lambda d: {"CUP"})
    assert rows and {r["ticker"] for r in rows} == {"CUP"}                 # non-members are never scanned
    assert bt.walk_forward(mini_universe, days=5, horizon=10, members=lambda d: set()) == []
    calls = []

    def members(d):
        calls.append(d)
        return {"CUP", "IHS", "WW"}

    full = bt.walk_forward(mini_universe, days=5, horizon=10, members=members)
    assert len(calls) == 5 and calls == sessions[-5:]                      # one membership lookup per scan day
    assert {r["ticker"] for r in full} == {r["ticker"] for r in bt.walk_forward(mini_universe, days=5, horizon=10)}
    early = bt.walk_forward(mini_universe, days=5, horizon=10, end=end)
    assert all(r["scan_day"] <= end for r in early)
    md = bt.render(early, bt.report_sections(early, 5, 10), 5, 10, end=end)
    assert f"last 5 sessions to {end}" in md
    universe = {"symbols": 6, "with_data": 5,
                "coverage": [{"year": 2025, "members": 6, "with_data": 5, "share": 0.833}]}
    md = bt.render(early, bt.report_sections(early, 5, 10), 5, 10, universe=universe)
    assert "## Universe" in md and "| 2025 | 6 | 5 | 83% |" in md


def test_walk_forward_rows_carry_market_context_and_breakdown_by_regime(mini_universe):
    from conftest import make_flat
    from test_scan import _ohlc_from_path
    index = _ohlc_from_path(np.linspace(300, 400, 400), seed=11)              # up-trend: bull regime
    series = scan.market_series(mini_universe, index, make_flat(400, 17.0))
    rows = bt.walk_forward(mini_universe, days=5, horizon=10, market=series)
    assert rows and set(bt.MARKET_KEYS) <= set(rows[0])
    assert all(r["regime"] == "bull" and r["vix"] == 17.0 and 0 <= r["breadth"] <= 1 for r in rows)
    assert all(r["index_vs_sma200_pct"] > 0 for r in rows)
    stats = bt.breakdown(rows)
    assert set(stats["by_regime"]) == {"bull"} and stats["by_regime"]["bull"]["signals"] == len(rows)
    md = bt.render(rows, bt.report_sections(rows, 5, 10), 5, 10)
    assert "| regime bull |" in md and "| VIX at the scan day | 15-20 |" in md
    assert "| share of the universe above its SMA200 |" in md
    plain = bt.walk_forward(mini_universe, days=5, horizon=10)                # no market series
    assert all(r[k] is None for r in plain for k in bt.MARKET_KEYS)
    assert bt.breakdown(plain)["by_regime"] == {}
    assert "| regime " not in bt.render(plain, bt.report_sections(plain, 5, 10), 5, 10)


def _bars(*rows):
    """rows: (open, high, low, close) per day."""
    idx = pd.bdate_range("2026-01-05", periods=len(rows))
    return pd.DataFrame({"Open": [r[0] for r in rows], "High": [r[1] for r in rows],
                         "Low": [r[2] for r in rows], "Close": [r[3] for r in rows]}, index=idx)


def test_horizon_table_medians_and_shares():
    # One signal filled at 100 with stop 95 and target 110; the high rises one point a day (101, 102, ...),
    # the low never reaches the stop: open at 5 bars (high 105), target at 10 bars (high 110).
    bars = _bars(*[(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(12)])
    row = {"ticker": "T", "pattern": "Cup & Handle", "scan_day": "2026-01-02", "fill": 100.0, "stop": 95.0,
           "target": 110.0, "atr": 2.0, "outcome": "open", "r": 0.1}
    t = {(x["slice"], x["horizon"]): x for x in bt.horizon_table([row], {"T": bars}, horizons=(5, 10))}
    assert set(t) == {("all", 5), ("all", 10), ("Cup & Handle", 5), ("Cup & Handle", 10)}
    h5, h10 = t[("all", 5)], t[("all", 10)]
    assert (h5["n"], h5["median_mfe"], h5["median_mae"]) == (1, 0.05, -0.01)
    assert (h5["median_mfe_atr"], h5["median_mae_atr"]) == (2.5, -0.5)
    assert (h5["target"], h5["stop"], h5["open"]) == (0.0, 0.0, 1.0)
    assert (h10["median_mfe"], h10["target"], h10["open"]) == (0.1, 1.0, 0.0)
    assert bt.horizon_table([{**row, "outcome": "gap"}], {"T": bars}) == []       # rows not traded are skipped
    assert bt.horizon_table([row], {"T": bars.iloc[:0]}) == []                    # no bars after the scan day


def test_feature_buckets_use_fixed_right_inclusive_edges_and_count_missing():
    def row(vr, r):
        return {"ticker": "T", "pattern": "P", "scan_day": "2026-01-05", "outcome": "target" if r > 0 else "stop",
                "r": r, "volume_ratio": vr, "score": 70, "mfe": 0.0, "mae": 0.0, "success5": None}
    rows = [row(0.5, 1.0), row(0.8, -1.0), row(1.2, 2.0), row(None, 1.0), {**row(9.0, 1.0), "outcome": "gap"}]
    fb = {(b["key"], b["bucket"]): b for b in bt.feature_buckets(rows)}
    vol = {k[1]: v for k, v in fb.items() if k[0] == "volume_ratio"}
    assert set(vol) == {"<= 0.8x", "1.0-1.3x"}                                  # empty buckets are omitted
    assert vol["<= 0.8x"]["n"] == 2 and vol["<= 0.8x"]["mean_r"] == 0.0          # 0.8 falls in the closed upper edge
    assert vol["1.0-1.3x"]["n"] == 1 and vol["1.0-1.3x"]["mean_r"] == 2.0 and vol["1.0-1.3x"]["hit_rate"] == 1.0
    assert all(b["missing"] == 1 for b in vol.values())                          # the row without a ratio
    assert all(b["feature"] == bt.FEATURE_BUCKETS["volume_ratio"][0] for b in vol.values())
    assert not any(k[0] == "close_vs_sma200" for k in fb)                        # no row has that feature
    assert not any(k[0] == "bars_since_break" for k in fb)                       # key absent entirely: no rows


def test_excursions_and_chart_book_success():
    fill, stop = 100.0, 95.0
    # +5 % reached on bar 2 before any close below the stop -> success, even though bar 3 later closes below.
    b = _bars((100, 101, 99, 100), (101, 105.5, 100, 104), (104, 104, 90, 92))
    assert bt.excursions(fill, stop, b, 10) == {"mfe": 0.055, "mae": -0.1, "success5": True}
    # A close below the stop first -> failure, although an intraday low would not have mattered.
    b = _bars((100, 101, 94, 94.5), (95, 106, 94, 105))
    assert bt.excursions(fill, stop, b, 10)["success5"] is False
    # Intraday touch of the stop without a close below it is NOT a failure under this definition.
    b = _bars((100, 101, 94, 99), (99, 106, 98, 105))
    assert bt.excursions(fill, stop, b, 10)["success5"] is True
    assert bt.excursions(fill, stop, _bars((100, 102, 99, 101)), 10)["success5"] is None   # undecided


def test_classify_variant_close_vs_intraday_stops():
    fill, stop, target = 100.0, 95.0, 110.0
    wick = _bars((100, 101, 94, 99), (99, 111, 98, 110))          # bar 1 wicks through the stop, closes above
    assert bt.classify_variant(fill, stop, target, wick, 10, "intraday")["outcome"] == "stop"
    close = bt.classify_variant(fill, stop, target, wick, 10, "close")
    assert close["outcome"] == "target" and close["bars"] == 2 and close["r"] == 2.0
    dive = _bars((100, 101, 93, 93.5),)                           # closes below: exit at the close, not the stop
    assert bt.classify_variant(fill, stop, target, dive, 10, "close") == {
        "outcome": "stop", "bars": 1, "exit": 93.5, "r": -1.3}


# --------------------------------------------------------------------------- #
# Statistics: drawdown, month-block bootstrap, windows
# --------------------------------------------------------------------------- #
def _trade(day, r, ticker="T"):
    return {"scan_day": day, "ticker": ticker, "r": r}


def test_max_drawdown():
    assert bt.max_drawdown([]) is None
    assert bt.max_drawdown([1.0, 1.0]) == 0.0
    assert bt.max_drawdown([-1.0, 2.0]) == -1.0                  # the curve starts at 0: a losing first trade counts
    assert bt.max_drawdown([2.0, -1.0, -1.0, 0.5]) == -2.0       # peak 2 -> trough 0
    assert bt.max_drawdown([0.5, -1.0, -1.0, 3.0, -0.5]) == -2.0  # 0.5 -> -1.5 is a fall of 2; -0.5 later is less


def test_block_bootstrap_resamples_months():
    flat = [_trade(f"2026-{m:02d}-10", 1.0) for m in (1, 1, 2, 2, 3, 3)]
    assert bt.block_bootstrap(flat, n_boot=50) == {"ci_low": 1.0, "ci_high": 1.0, "dd_p95": 0.0, "blocks": 3}
    # Fewer than two months, or fewer than five trades: an interval would mean nothing.
    assert bt.block_bootstrap(flat[:2], n_boot=10)["ci_low"] is None
    assert bt.block_bootstrap(flat[:4], n_boot=10) == {"ci_low": None, "ci_high": None, "dd_p95": None, "blocks": 2}
    # A mixed sample: the interval brackets the mean, the worst-case drawdown is at least the observed one,
    # rows without r are ignored, and the result is reproducible.
    rs = (2.0, -1.0, -1.0, 2.0, -1.0, 2.0, -1.0, -1.0)
    mixed = [_trade(f"2026-{m:02d}-10", r) for m, r in zip((1, 1, 2, 2, 3, 3, 4, 4), rs)] + [_trade("2026-05-10", None)]
    b = bt.block_bootstrap(mixed, n_boot=500, seed=1)
    assert b["blocks"] == 4 and b["ci_low"] < sum(rs) / len(rs) < b["ci_high"]
    assert b["dd_p95"] <= bt.max_drawdown(rs) <= 0
    assert bt.block_bootstrap(mixed, n_boot=200) == bt.block_bootstrap(mixed, n_boot=200)


def test_split_windows_and_report_sections(mini_universe):
    rows = bt.walk_forward(mini_universe, days=5, horizon=10)
    assert bt.split_windows(rows, None) == [("all sessions", rows)]
    split = max(r["scan_day"] for r in rows)
    wins = bt.split_windows(rows, split)
    assert [w[0] for w in wins] == ["all sessions", f"before {split}", f"from {split}"]
    assert len(wins[1][1]) + len(wins[2][1]) == len(rows) and wins[2][1]
    assert all(r["scan_day"] < split for r in wins[1][1]) and all(r["scan_day"] >= split for r in wins[2][1])
    sections = bt.report_sections(rows, 5, 10, split=split, data=mini_universe, do_grid=True)
    assert [s["label"] for s in sections] == [w[0] for w in wins]
    assert sections[0]["stats"]["overall"]["signals"] == len(rows) and len(sections[0]["grid"]) == len(bt.GRID)
    assert sections[2]["stats"]["overall"]["signals"] == len(wins[2][1])
    traded = [r for r in rows if r["outcome"] in bt.TRADED]
    assert sections[0]["horizons"] and sections[0]["horizons"][0]["slice"] == "all"
    assert {b["key"] for b in sections[0]["features"]} <= set(bt.FEATURE_BUCKETS)
    assert sum(b["n"] for b in sections[0]["features"] if b["key"] == "stop_atr") == len(traded)
    md = bt.render(rows, sections, 5, 10)
    assert "## All sessions" in md and f"## Before {split}" in md and f"## From {split}" in md
    assert md.count("### Stop / target variants") == 3 and "judged on the other" in md
    assert "### Excursions by horizon (all sessions)" in md and "### Outcome by feature (all sessions)" in md
    assert "| entry minus stop, in ATR |" in md and "| breakout bar close within its range |" in md
    assert "| handle volume / cup volume (cups) |" in md and "| pattern depth in ATR |" in md
    assert "## Signals" in md


def test_grid_rescores_the_same_signals(mini_universe):
    rows = bt.walk_forward(mini_universe, days=5, horizon=10)
    g = bt.grid(rows, mini_universe, 10)
    assert len(g) == len(bt.GRID) == 24
    assert {(x["stop_extra_atr"], x["stop_basis"], x["target_mode"]) for x in g} == set(bt.GRID)
    traded = sum(1 for r in rows if r["outcome"] in ("target", "stop", "open"))
    assert all(x["n"] == traded for x in g)
    md = bt.render(rows, bt.report_sections(rows, 5, 10, data=mini_universe, do_grid=True), 5, 10)
    assert "### Stop / target variants" in md and "| 0.75 | close | breakout |" in md
    assert "| 1.0 | intraday | full |" in md and "1.25 ATR under it" in md


def test_breakout_level_target_applies_to_cups_only(mini_universe):
    rows = bt.walk_forward(mini_universe, days=5, horizon=10)
    cup = next(r for r in rows if r["pattern"] == "Cup & Handle")
    assert cup["cup_bottom"] is not None and cup["cup_trigger"] > cup["cup_bottom"]
    bo = bt.variant_target(cup, "breakout")
    assert bo == cup["fill"] + (cup["cup_trigger"] - cup["cup_bottom"]) and bo < cup["target"]  # below rim-based
    assert bt.variant_target(cup, "half") == cup["fill"] + 0.5 * (cup["target"] - cup["fill"])
    other = next(r for r in rows if r["pattern"] != "Cup & Handle")
    assert bt.variant_target(other, "breakout") == other["target"]
    assert bt.variant_target({**cup, "target": None}, "breakout") is None


def test_ablation_relaxes_one_rule_at_a_time_and_restores_it(mini_universe):
    table = bt.ablation(mini_universe, days=3, horizon=5)
    assert len(table) == 1 + len(scan.RULE_PROFILES["legacy"])
    assert table[0]["rule"] == "spec (all rules)" and table[0]["delta"] == 0
    assert {r["rule"] for r in table[1:]} == set(scan.RULE_PROFILES["legacy"])
    assert scan.ACTIVE_PROFILE == "spec" and scan.VOLUME_CONFIRM["Cup & Handle"] == 1.4   # every override undone
    assert all(r["signals"] >= 0 and r["delta"] == r["signals"] - table[0]["signals"] for r in table)
    md = bt.render_ablation(table, 3, 5)
    assert "# Rule ablation" in md and "| spec (all rules) | - |" in md


def test_apply_override_parses_literals_and_rejects_unknown_keys(monkeypatch):
    monkeypatch.setattr(scan, "WW_TIME_SYM_TOL", scan.WW_TIME_SYM_TOL)
    monkeypatch.setattr(scan, "CUP_TRIGGER", scan.CUP_TRIGGER)
    assert bt.apply_override("WW_TIME_SYM_TOL=0.45") == ("WW_TIME_SYM_TOL", 0.45) and scan.WW_TIME_SYM_TOL == 0.45
    assert bt.apply_override("CUP_TRIGGER=rim_b") == ("CUP_TRIGGER", "rim_b") and scan.CUP_TRIGGER == "rim_b"
    assert bt.apply_override("WW_TIME_SYM_TOL=None")[1] is None
    for bad in ("NOPE=1", "_SPEC_VALUES={}", "no-equals"):
        with pytest.raises(ValueError):
            bt.apply_override(bad)


def test_profile_pass_replays_the_other_rule_set_and_restores_the_active_one(mini_universe):
    rows = bt.walk_forward(mini_universe, days=5, horizon=10)
    assert scan.ACTIVE_PROFILE == "spec"
    other = bt.profile_pass(mini_universe, 5, 10, "legacy")
    assert scan.ACTIVE_PROFILE == "spec" and scan.CUP_MAX_RETRACE == 0.5          # restored
    assert other["profile"] == "legacy" and other["stats"]["overall"]["signals"] >= 1
    legacy_targets = {r["ticker"]: r["target"] for r in other["rows"] if r["pattern"] == "Cup & Handle"}
    spec_targets = {r["ticker"]: r["target"] for r in rows if r["pattern"] == "Cup & Handle"}
    assert spec_targets and legacy_targets and spec_targets != legacy_targets      # left-rim vs right-rim measure
    sections = bt.report_sections(rows, 5, 10, other_rows=other["rows"], other_name="legacy")
    assert sections[0]["other"]["stats"]["overall"]["signals"] == other["stats"]["overall"]["signals"]
    md = bt.render(rows, sections, 5, 10)
    assert "### Rule profile comparison: spec (above) vs legacy (below), all sessions" in md
    assert "| legacy: all |" in md


def test_breakdown_and_render():
    def row(pattern, score, outcome, r):
        return {"ticker": "T", "pattern": pattern, "score": score, "outcome": outcome, "r": r,
                "scan_day": "2026-01-05", "entry": 100.0, "fill": 100.5, "stop": 95.0, "target": 110.0,
                "bars": 0 if outcome == "gap" else 3, "atr": 1.0,
                "mfe": 0.08 if outcome != "gap" else None, "mae": -0.02 if outcome != "gap" else None,
                "success5": {"target": True, "stop": False, "open": None}.get(outcome)}
    rows = [row("Cup & Handle", 65, "target", 2.0), row("Cup & Handle", 72, "stop", -1.0),
            row("Bullish Wolfe Wave", 85, "open", 0.4), row("Cup & Handle", 91, "gap", None)]
    stats = bt.breakdown(rows)
    o = stats["overall"]
    assert (o["signals"], o["gap"], o["below_stop"]) == (4, 1, 0)
    assert (o["target"], o["stop"], o["open"]) == (1, 1, 1)
    assert o["hit_rate"] == 0.5 and o["mean_r"] == round((2.0 - 1.0 + 0.4) / 3, 3)
    assert o["median_r"] == 0.4 and o["total_r"] == 1.4
    assert o["std_r"] == round(float(np.std([2.0, -1.0, 0.4], ddof=1)), 3)
    assert o["max_dd"] == -1.0                                   # 2 -> 1 in scan order
    assert o["ci_low"] is None and o["dd_p95"] is None and o["blocks"] == 1   # one month: no interval
    assert set(stats["by_score"]) == {"60-69", "70-79", "80-89", "90-100"}
    assert stats["by_pattern"]["Bullish Wolfe Wave"]["hit_rate"] is None    # nothing resolved
    assert o["success5"] == 0.5 and o["mfe"] == 0.08
    md = bt.render(rows, bt.report_sections(rows, 63, 40), 63, 40)
    assert "| all | 4 | 1 | 1 | 1 | 1 | 50% | +0.47 | +0.40 | +1.40 | - | -1.00 | - | 50% | +8.0% | -2.0% |" in md
    assert "| 2026-01-05 | T | Cup & Handle | 91 | 100.0 | 100.5 | 95.0 | 110.0 | gap | 0 | - |" in md
    assert isinstance(pd.DataFrame(rows), pd.DataFrame)
