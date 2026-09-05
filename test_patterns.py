#!/usr/bin/env python3
"""Pattern-precision tests for scan.py.

Three layers, all offline and deterministic:

1. Primitives (pivots, ATR, roundness, breakout state machine, trend context)
   checked against hand-computed values.
2. Detector arithmetic: the entry / stop / target / risk of each textbook
   signal is recomputed independently from the anchor points the detector
   reports in ``notes`` and the documented formulas.
3. Negative controls and boundaries: single-rule mutations of the textbook
   fixtures must be rejected; flat bars, missing bars, zero volume, wick
   spikes and an unadjusted stock split behave as documented.

The random-walk false-positive sweep lives in ``test_scan.py`` and is not
repeated here.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

import scan
from conftest import make_random_walk
from test_scan import _ohlc_from_path, _uptrend_prefix

TOL = 0.011  # two values rounded to 2 dp may differ by one cent


def _loc(df: pd.DataFrame, day: str) -> int:
    return int(df.index.get_loc(pd.Timestamp(day)))


# --------------------------------------------------------------------------- #
# 1. Primitives
# --------------------------------------------------------------------------- #
def test_find_pivots_exact_indices_and_tie_rule():
    high = np.array([1, 2, 3, 2, 1, 1, 1, 2, 5, 2, 1, 1, 1, 1], float)
    low = high - 1
    # Swing high at 2 and 8 (strict window maxima); swing lows at 4 and 10:
    # the flat stretches 4-6 and 10-13 tie, and the tie goes to the *first*
    # bar of the window, so only the bar whose window starts two bars earlier
    # qualifies.  Bars within `order` of either edge are never pivots.
    assert scan.find_pivots(high, low, order=2) == ([2, 8], [4, 10])
    ramp = np.arange(5, dtype=float)
    assert scan.find_pivots(ramp, ramp, order=2) == ([], [])   # extremes sit on the edges


def test_find_pivots_flat_series_has_none(flat_df):
    assert scan.find_pivots(flat_df["High"].to_numpy(), flat_df["Low"].to_numpy()) == ([], [])


def test_atr_matches_hand_computation():
    df = pd.DataFrame({"Open": [10, 11, 12.0], "High": [11, 13, 12.5], "Low": [9, 10.5, 11.0],
                       "Close": [10.5, 12, 11.5], "Volume": [1, 1, 1.0]})
    # TR: bar0 = H-L = 2; bar1 = max(2.5, |13-10.5|, |10.5-10.5|) = 2.5;
    #     bar2 = max(1.5, |12.5-12|, |11-12|) = 1.5.  Rolling mean of 2, min_periods 1.
    assert scan.atr(df, n=2).tolist() == [2.0, 2.25, 2.0]


def test_u_shape_r2_parabola_arch_v_and_degenerate():
    x = np.arange(20, dtype=float)
    assert scan._u_shape_r2((x - 10) ** 2 + 5) == pytest.approx(1.0)
    assert scan._u_shape_r2(-((x - 10) ** 2) + 500) == 0.0          # arch: convexity sign
    assert scan._u_shape_r2(np.ones(20)) == 0.0                     # zero variance
    assert scan._u_shape_r2(np.array([1.0, 2.0, 1.0])) == 0.0       # fewer than 5 points
    # A parabola explains a symmetric V well, so this test alone would pass a
    # V; the detector pairs it with _v_shape_r2 (next test) to reject Vs.
    v = scan._u_shape_r2(np.abs(x - 10) + 5)
    assert 0.90 < v < 0.95 and v >= scan.CUP_MIN_ROUNDNESS


def test_v_shape_r2_separates_rounded_bases_from_sharp_reversals():
    x = np.arange(100, dtype=float)
    shapes = {
        "parabola": (x - 50) ** 2 / 25 + 75,
        "half-sine": 100 - 25 * np.sin(np.linspace(0, np.pi, 100)),
        "flat dish": np.clip(np.abs(x - 50) - 20, 0, None) + 75,
        "asymmetric sine": 100 - 25 * np.sin(np.pi * (x / 100) ** 0.7),
    }
    for label, y in shapes.items():                 # rounded: the U fit wins
        u, v = scan._u_shape_r2(y), scan._v_shape_r2(y, int(np.argmin(y)))
        assert u - v > scan.CUP_MAX_V_ADVANTAGE, (label, u, v)
    v_shape = np.abs(x - 50) / 2 + 75
    u, v = scan._u_shape_r2(v_shape), scan._v_shape_r2(v_shape, 50)
    assert v == pytest.approx(1.0) and v - u > 0.05  # V: the two legs win outright
    noisy_v = v_shape + np.random.default_rng(1).normal(0, 1.5, 100)
    assert scan._v_shape_r2(noisy_v, int(np.argmin(noisy_v))) > scan._u_shape_r2(noisy_v)
    assert scan._v_shape_r2(np.ones(20), 10) == 0.0                  # zero variance
    assert scan._v_shape_r2(-np.abs(x - 50), 50) == 0.0             # legs open downward
    assert scan._v_shape_r2(np.array([1.0, 0.0, 1.0]), 1) == 0.0    # fewer than 5 points


CUP, IHS = "Cup & Handle", "Inverse Head & Shoulders"     # lag 0 and lag PIVOT_ORDER


@pytest.mark.parametrize("close, start, pattern, expected", [
    ([90, 95, 101.0], 0, CUP, ("CONFIRMED", 0)),          # broke on the last bar
    ([90, 101, 101.0], 0, CUP, ("CONFIRMED", 1)),         # broke one bar ago
    ([90, 95, 96.0], 0, CUP, ("WATCHLIST", None)),        # within WATCH_PROXIMITY (5 %)
    ([90, 95, 94.9], 0, CUP, ("STALE", None)),            # just outside 5 %
    ([90, 101, 101, 101, 101, 101.0], 0, CUP, ("STALE", 4)),      # older than MAX_BREAKOUT_AGE
    ([90, 101, 101, 101, 101, 101.0], 0, IHS, ("CONFIRMED", 4)),  # ... unless the pivot lag allows it
    ([90, 101, 106.0], 0, CUP, ("STALE", 1)),             # > MAX_RUNAWAY above trigger: chasing
    ([90, 101, 104.9], 0, CUP, ("CONFIRMED", 1)),         # 4.9 % is still an entry
    ([90, 101, 99.8], 0, CUP, ("WATCHLIST", None)),       # broke out, pulled back: a retest stays listed
    ([90, 101, 94.0], 0, CUP, ("STALE", None)),           # pulled back too far
    ([90, 101, 99, 101.0], 0, CUP, ("CONFIRMED", 2)),     # re-break inside the window: age from the first break
    ([90, 101, 101, 101, 101, 99, 101.0], 0, CUP, ("STALE", 5)),      # re-break after the window: chop, not a breakout
    ([101, 90, 95, 98.0], 1, CUP, ("WATCHLIST", None)),   # breaks before `start` do not count
    ([101, 101, 101.0], 1, CUP, ("CONFIRMED", 1)),        # a run cannot begin before `start`
])
def test_evaluate_breakout_state_table(close, start, pattern, expected):
    status, age, trigger = scan.evaluate_breakout(np.array(close, float), lambda _i: 100.0, start, pattern)
    assert (status, age) == expected and trigger == 100.0


def test_evaluate_breakout_sloping_trigger_and_floor():
    neck = lambda i: 100.0 - 0.5 * i                      # falling neckline: 100, 99.5, 99.0, 98.5  # noqa: E731
    # A flat 99.0 close only clears the line on bar 3 (99.0 is not > 99.0 on bar 2).
    assert scan.evaluate_breakout(np.array([90.0, 99.0, 99.0, 99.0]), neck, 0, IHS) == ("CONFIRMED", 0, 98.5)
    # 99.7 clears the line from bar 1 on: the run is three bars old, trigger = line at the break bar.
    assert scan.evaluate_breakout(np.array([90.0, 99.7, 99.7, 99.7]), neck, 0, IHS) == ("CONFIRMED", 2, 99.5)
    # Pulled back below today's line but within 5 % of it: watchlist at today's level ...
    assert scan.evaluate_breakout(np.array([90.0, 99.7, 99.7, 96.0]), neck, 0, IHS) == ("WATCHLIST", None, 98.5)
    # ... unless it also lost the floor (right-shoulder low / point 5).
    assert scan.evaluate_breakout(np.array([90.0, 99.7, 99.7, 96.0]), neck, 0, IHS, floor=97.5) == ("STALE", None, 98.5)


def test_trend_context_states(cup_df, flat_df):
    desc, up, strong_down = scan.trend_context(cup_df)
    assert up and not strong_down and desc.startswith("close above SMA200")
    # Strong down-trend: close > 10 % below a SMA200 that is lower than 40 bars ago.
    down = _ohlc_from_path(np.linspace(300, 100, 400), seed=1)
    desc, up, strong_down = scan.trend_context(down)
    assert strong_down and not up and "SMA200 falling" in desc
    with pytest.MonkeyPatch.context() as mp:            # the veto reads its constant
        mp.setattr(scan, "TREND_STRONG_DOWN", 0.0)
        assert not scan.trend_context(down)[2]
    # Fewer than 200 bars: falls back to SMA50 and says so.
    desc, up, _ = scan.trend_context(_ohlc_from_path(np.linspace(50, 100, 120), seed=1))
    assert up and "SMA200 n/a" in desc
    # 200-239 bars: SMA200 exists but its slope does not; the veto must not
    # silently switch off, so it falls back to the SMA50 test.
    for n in (200, 220, 238):
        desc, up, strong_down = scan.trend_context(_ohlc_from_path(np.linspace(300, 100, n), seed=1))
        assert strong_down and not up and "SMA200 slope n/a" in desc, n
    # Flat: close equals every average -> neither up nor a strong down-trend.
    assert scan.trend_context(flat_df)[1:] == (False, False)


def test_volume_ratio_edge_cases(cup_df):
    n = len(cup_df)
    assert scan._volume_ratio(cup_df, 10) is None                 # too little history
    zero = cup_df.copy()
    zero["Volume"] = 0.0
    assert scan._volume_ratio(zero, n - 1) is None                # zero base average
    spot = cup_df.copy()
    spot.loc[spot.index[-1], "Volume"] = 0.0
    assert scan._volume_ratio(spot, n - 1) == 0.0                 # zero-volume session
    spot.loc[spot.index[-1], "Volume"] = np.nan
    assert scan._volume_ratio(spot, n - 1) is None
    k = scan.VOLUME_AVG_LEN
    assert scan._volume_ratio(cup_df, n - 1) == pytest.approx(
        cup_df["Volume"].iloc[-1] / cup_df["Volume"].iloc[n - 1 - k:n - 1].mean(), abs=0.006)


def test_max_breakout_age_and_dedupe():
    assert scan.max_breakout_age("Cup & Handle") == scan.MAX_BREAKOUT_AGE
    assert scan.max_breakout_age("Inverse Head & Shoulders") == scan.MAX_BREAKOUT_AGE + scan.PIVOT_ORDER
    assert scan.max_breakout_age("unknown") == scan.MAX_BREAKOUT_AGE

    def sig(status, score):
        return scan.Signal("T", "Cup & Handle", status, 100, 90, 10, None, score, 100, "d", None, None, "", "")
    kept = scan._dedupe([sig("CONFIRMED", 70), sig("CONFIRMED", 85), sig("WATCHLIST", 60)])
    assert sorted((s.status, s.score) for s in kept) == [("CONFIRMED", 85), ("WATCHLIST", 60)]


def test_date_histogram_is_newest_first():
    assert scan._date_histogram(["2026-01-02", "2026-01-05", "2026-01-02"]) == {
        "2026-01-05": 1, "2026-01-02": 2}


def test_as_utc_accepts_every_epoch_representation():
    epoch = 1_717_435_200                       # 2024-06-03 17:20:00 UTC
    want = pd.Timestamp(epoch, unit="s", tz="UTC")
    aware = want.tz_convert("America/New_York")
    for ts in (epoch, float(epoch), str(epoch), np.int64(epoch), np.float64(epoch),
               aware, want.tz_localize(None)):
        assert scan._as_utc(ts) == want, repr(ts)
    with pytest.raises(ValueError):
        scan._as_utc("yesterday")


# --------------------------------------------------------------------------- #
# 2. Detector arithmetic on the textbook fixtures
# --------------------------------------------------------------------------- #
def test_cup_levels_follow_documented_formulas(cup_df):
    (s,) = scan.detect_cup_and_handle(cup_df, "CUP")
    m = re.fullmatch(r"left rim (\S+) @([\d.]+), bottom (\S+) @([\d.]+) \(depth (\d+)%\), "
                     r"right rim (\S+) @([\d.]+), handle low (\S+) @([\d.]+) \(depth ([\d.]+)%\), "
                     r"trigger ([\d.]+)", s.notes)
    assert m, s.notes
    a, b, h = _loc(cup_df, m[1]), _loc(cup_df, m[6]), _loc(cup_df, m[8])
    high, low, close = (cup_df[c].to_numpy() for c in ("High", "Low", "Close"))
    rim_a, rim_b, handle_low = high[a], high[b], low[h]
    bottom = low[a:b + 1].min()
    trigger = float(m[11])
    assert float(m[2]) == round(rim_a, 2) and float(m[7]) == round(rim_b, 2)
    assert float(m[4]) == round(bottom, 2) and float(m[9]) == round(handle_low, 2)
    assert int(m[5]) == round((rim_a - bottom) / rim_a * 100)
    assert float(m[10]) == pytest.approx((rim_b - handle_low) / rim_b * 100, abs=0.06)
    # Geometry bounds actually hold on the reported anchors.
    assert scan.CUP_MIN_LEN <= b - a <= scan.CUP_MAX_LEN
    assert scan.CUP_MIN_DEPTH <= (rim_a - bottom) / rim_a <= scan.CUP_MAX_DEPTH
    assert handle_low < trigger
    # Spec trend filter: SMA50 > SMA200, or a >= 20 % *rise* from the 60-bar low into rim A
    # (a rise from the low, not "low 20 % below the rim").
    s50, s200 = scan._sma_pair(cup_df)
    recent_low = low[max(0, a - scan.CUP_PRIOR_LOOKBACK):a + 1].min()
    assert s50 > s200 or (rim_a - recent_low) / recent_low >= scan.CUP_PRIOR_ADVANCE
    # Spec rollback rule: the cup decline retraces at most half of the preceding advance.
    pre_low = low[max(0, a - scan.CUP_ADVANCE_LOOKBACK):a + 1].min()
    assert (rim_a - bottom) <= scan.CUP_MAX_RETRACE * (rim_a - pre_low)
    assert abs(rim_b - rim_a) <= scan.CUP_RIM_TOL_OF_DEPTH * (rim_a - bottom)
    assert scan.CUP_BOTTOM_ZONE[0] <= (low[a:b + 1].argmin()) / (b - a) <= scan.CUP_BOTTOM_ZONE[1]
    assert h - b <= min(scan.HANDLE_MAX_LEN, b - a)               # handle shorter than the cup
    assert s.volume_ratio >= scan.VOLUME_CONFIRM["Cup & Handle"]  # confirmation needs volume
    # Trigger = handle high; first close above it after the handle is the break.
    assert high[b + 1:h + 1].max() <= trigger + TOL
    first_break = next(i for i in range(h + 1, len(close)) if close[i] > trigger)
    assert s.bars_since_break == len(close) - 1 - first_break == 1
    # Entry = breakout close (above trigger, within MAX_RUNAWAY); stop / target / risk formulas.
    assert s.status == "CONFIRMED" and s.entry == round(close[-1], 2) == s.last_close
    assert trigger < s.entry <= trigger * (1 + scan.MAX_RUNAWAY)
    atr = scan.atr(cup_df).to_numpy()
    assert s.stop == pytest.approx(handle_low - 0.25 * atr[h], abs=TOL)
    assert s.target == pytest.approx(s.entry + (rim_b - bottom), abs=TOL)   # spec: bottom to the right rim
    assert s.risk_pct == pytest.approx((s.entry - s.stop) / s.entry * 100, abs=0.02)
    assert s.risk_pct <= scan.MAX_RISK_PCT["Cup & Handle"]
    assert s.volume_ratio == scan._volume_ratio(cup_df, first_break)


def test_ihs_neckline_ignores_wicks_on_the_anchor_bars(ihs_df):
    """A long upper wick on the LS/head/RS bar must not become a neckline anchor."""
    (base,) = scan.detect_inverse_hs(ihs_df, "IHS")
    m = re.search(r"LS (\S+) @[\d.]+, head (\S+) @[\d.]+, RS (\S+) @", base.notes)
    ls, h, rs = (_loc(ihs_df, m[k]) for k in (1, 2, 3))
    high = ihs_df["High"].to_numpy()
    spiked = ihs_df.copy()
    # A wick on the LS bar just above the left half's rally peak.  The head
    # and RS bars are left alone so ATR[h] (head-depth test) and ATR[rs]
    # (stop) are unchanged and only the anchor choice is exercised.
    spiked.loc[spiked.index[ls], "High"] = high[ls + 1:h].max() * 1.01
    sh = spiked["High"].to_numpy()
    assert np.argmax(sh[ls:h + 1]) == 0                   # the old inclusive slice would anchor on LS
    (s,) = scan.detect_inverse_hs(spiked, "IHS")
    assert s.notes == base.notes                          # neckline, trigger and levels unchanged
    assert (s.entry, s.stop, s.target) == (base.entry, base.stop, base.target)


def test_ihs_levels_follow_documented_formulas(ihs_df):
    (s,) = scan.detect_inverse_hs(ihs_df, "IHS")
    m = re.fullmatch(r"LS (\S+) @([\d.]+), head (\S+) @([\d.]+), RS (\S+) @([\d.]+), "
                     r"neckline ([\d.]+)->([\d.]+) \(now ([\d.]+)\)", s.notes)
    assert m, s.notes
    ls, h, rs = _loc(ihs_df, m[1]), _loc(ihs_df, m[3]), _loc(ihs_df, m[5])
    high, low, close = (ihs_df[c].to_numpy() for c in ("High", "Low", "Close"))
    n = len(close)
    ls_v, h_v, rs_v = low[ls], low[h], low[rs]
    assert (float(m[2]), float(m[4]), float(m[6])) == tuple(round(v, 2) for v in (ls_v, h_v, rs_v))
    # Head depth rule holds on the reported anchors.
    unit = scan.atr(ihs_df).to_numpy()
    assert h_v < ls_v - scan.IHS_MIN_HEAD_ATR * unit[h] and h_v < rs_v - scan.IHS_MIN_HEAD_ATR * unit[h]
    # Neckline through the highest highs strictly between the anchors; slope bounded.
    n1 = ls + 1 + int(np.argmax(high[ls + 1:h]))
    n2 = h + 1 + int(np.argmax(high[h + 1:rs]))
    assert ls < n1 < h < n2 < rs
    slope = (high[n2] - high[n1]) / (n2 - n1)
    assert (float(m[7]), float(m[8])) == (round(high[n1], 2), round(high[n2], 2))
    assert abs(slope * (rs - ls)) / close[h] <= scan.IHS_MAX_NECK_SLOPE
    neck = lambda i: high[n1] + slope * (i - n1)  # noqa: E731
    head_height = neck(h) - h_v
    # Spec trend filter: SMA50 < SMA200, or a decline of at least one head height into LS.
    look = high[max(0, ls - 60):ls + 1]
    s50, s200 = scan._sma_pair(ihs_df)
    assert s50 < s200 or (look.max() - ls_v) >= scan.IHS_PRIOR_DECLINE_OF_HEIGHT * head_height
    # Spec symmetry rules: shoulders within 30 % of the head height; side durations within 40 %.
    assert abs(ls_v - rs_v) <= scan.IHS_SHOULDER_SYM_OF_HEIGHT * head_height
    left_side, right_side = n1 - ls, rs - n2
    assert abs(left_side - right_side) / max(left_side, right_side) <= scan.IHS_SIDE_SYM_TOL
    assert float(m[9]) == pytest.approx(neck(n - 1), abs=TOL)
    first_break = next(j for j in range(rs + 1, n) if close[j] > neck(j))
    trigger = neck(first_break)
    assert s.bars_since_break == n - 1 - first_break
    assert s.status == "CONFIRMED" and s.entry == round(close[-1], 2)
    assert s.volume_ratio >= scan.VOLUME_CONFIRM["Inverse Head & Shoulders"]
    assert s.stop == pytest.approx(rs_v - 0.25 * unit[rs], abs=TOL)
    assert s.target == pytest.approx(s.entry + head_height, abs=TOL)   # spec: neckline at the head bar minus head
    assert trigger > 0                                                   # (break-bar neckline, legacy height)
    assert s.risk_pct == pytest.approx((s.entry - s.stop) / s.entry * 100, abs=0.02)


def test_wolfe_target_is_line_1_4_at_the_eta(wolfe_df):
    (s,) = scan.detect_bullish_wolfe(wolfe_df, "WW")
    m = re.fullmatch(r"1 (\S+) @([\d.]+), 2 (\S+) @([\d.]+), 3 (\S+) @([\d.]+), 4 (\S+) @([\d.]+), "
                     r"5 (\S+) @([\d.]+); line 1-3 now ([\d.]+)(?:; ETA ~(\S+))?", s.notes)
    assert m, s.notes
    p1, p2, p3, p4, p5 = (_loc(wolfe_df, m[k]) for k in (1, 3, 5, 7, 9))
    high, low, close = (wolfe_df[c].to_numpy() for c in ("High", "Low", "Close"))
    n = len(close)
    v1, v3, v5 = low[p1], low[p3], low[p5]
    v2, v4 = high[p2], high[p4]
    assert [float(m[k]) for k in (2, 4, 6, 8, 10)] == [round(v, 2) for v in (v1, v2, v3, v4, v5)]
    # Wolfe geometry on the reported points.
    assert v3 < v1 and v5 < v3 and v4 < v2 and v1 < v4 < v2
    s13, s24 = (v3 - v1) / (p3 - p1), (v4 - v2) / (p4 - p2)
    assert s24 < s13 < 0                                   # both falling, converging
    line13 = lambda x: v1 + s13 * (x - p1)  # noqa: E731
    overshoot = line13(p5) - v5
    atr = scan.atr(wolfe_df).to_numpy()
    assert overshoot >= 0                                       # spec: point 5 penetrates line 1-3 ...
    assert v5 >= v3 + s24 * (p5 - p3)                           # ... but holds the sweet zone (2-4 parallel via 3)
    legs = (p2 - p1, p3 - p2, p4 - p3)
    assert all(abs(leg - sum(legs) / 3) <= scan.WW_TIME_SYM_TOL * sum(legs) / 3 for leg in legs)
    assert float(m[11]) == pytest.approx(line13(n - 1), abs=TOL)
    # ETA: intersection of 1-3 and 2-4; EPA: line 1-4 at the ETA = target.
    eta = ((v2 - s24 * p2) - (v1 - s13 * p1)) / (s13 - s24)
    assert eta > p5
    s14 = (v4 - v1) / (p4 - p1)
    assert s.target == pytest.approx(v1 + s14 * (eta - p1), abs=TOL)
    if m[12]:
        assert wolfe_df.index[min(int(eta), n - 1)].date().isoformat() == m[12]
    # Confirmation: first close back above line 1-3 after point 5.
    first_break = next(j for j in range(p5 + 1, n) if close[j] > line13(j))
    assert s.bars_since_break == n - 1 - first_break
    assert s.bars_since_break <= scan.max_breakout_age("Bullish Wolfe Wave")
    assert s.status == "CONFIRMED" and s.entry == round(close[-1], 2)
    assert s.stop == pytest.approx(v5 - 0.25 * atr[p5], abs=TOL)
    assert s.risk_pct == pytest.approx((s.entry - s.stop) / s.entry * 100, abs=0.02)


def test_signal_scores_are_bounded_and_reported_fields_consistent(mini_universe):
    for sym, df in mini_universe.items():
        for s in scan.scan_symbol(sym, df):
            assert scan.MIN_SCORE <= s.score <= 100
            assert s.stop < s.entry and 0 < s.risk_pct <= 15
            assert s.target is None or s.target > s.entry
            assert (s.bars_since_break is not None) == (s.status == "CONFIRMED")
            assert s.last_date == str(df.index[-1].date())


# --------------------------------------------------------------------------- #
# 3. Negative controls: single-rule mutations must be rejected
# --------------------------------------------------------------------------- #
T = np.linspace(0, np.pi, 100)


def cup_variant(pre=None, cup=None, handle=None, brk=None) -> pd.DataFrame:
    """The textbook cup with one component swapped out."""
    pre = _uptrend_prefix(220, 40, 100) if pre is None else pre
    cup = (100 - 25 * np.sin(T)) if cup is None else cup
    handle = np.concatenate([np.linspace(100, 94, 8), np.linspace(94, 97, 7)]) if handle is None else handle
    brk = np.array([101.5, 102.0]) if brk is None else brk
    df = _ohlc_from_path(np.concatenate([pre, cup, handle, brk]), seed=3)
    df.loc[df.index[-2], "Volume"] *= 3.0
    return df


@pytest.mark.parametrize("label, kwargs", [
    ("no prior advance (flat run-up)", dict(pre=np.full(220, 100.0))),
    ("no handle (breakout straight off the rim)", dict(handle=np.array([100.0]))),
    ("handle too deep (20 % > HANDLE_MAX_DEPTH)",
     dict(handle=np.concatenate([np.linspace(100, 80, 8), np.linspace(80, 90, 7)]))),
    ("cup too shallow (5 % < CUP_MIN_DEPTH)",
     dict(cup=100 - 5 * np.sin(T), handle=np.concatenate([np.linspace(100, 98, 8), np.linspace(98, 99, 7)]))),
    ("right rim 10 % above left rim (> CUP_RIM_TOL)",
     dict(cup=np.linspace(100, 110, 100) - 25 * np.sin(T),
          handle=np.concatenate([np.linspace(110, 104, 8), np.linspace(104, 107, 7)]),
          brk=np.array([111.5, 112.0]))),
    ("breakout ran away (> MAX_RUNAWAY)", dict(brk=np.array([104.0, 108.5]))),
    ("breakout stale (6 bars > MAX_BREAKOUT_AGE)",
     dict(brk=np.array([101.5, 102.0, 102.1, 102.2, 102.3, 102.4, 102.5]))),
    ("below SMA200 (continuation needs an up-trend)", dict(pre=np.linspace(200, 100, 220))),
    ("symmetric V bottom (two legs fit better than a U)",
     dict(cup=100 - 25 * (1 - np.abs(np.linspace(-1, 1, 100))))),
])
def test_cup_single_rule_violations_are_rejected(label, kwargs):
    assert scan.detect_cup_and_handle(cup_variant(**kwargs), "CUP") == [], label


def test_cup_prior_advance_is_a_rise_from_the_low():
    """Legacy rule: a >= 25 % rise from the 120-bar low into rim A (and no SMA alternative).

    A low 20.6 % below the rim (a 25.9 % rise) passes, which a "low must be
    25 % below the rim" reading would reject; a 19.9 % rise fails.  Under the
    spec profile the same cups pass regardless, because SMA50 > SMA200 alone
    satisfies the trend filter and the rollback rule is what limits the depth.
    """
    def prefix(low):
        return np.concatenate([np.full(100, low), np.linspace(low, 100, 120)])
    scan.apply_profile("legacy")
    assert scan.detect_cup_and_handle(cup_variant(pre=prefix(100 / 1.259)), "CUP")
    assert scan.detect_cup_and_handle(cup_variant(pre=prefix(100 / 1.199)), "CUP") == []
    scan.apply_profile("spec")
    shallow = cup_variant(pre=prefix(100 / 1.199))
    assert scan.detect_cup_and_handle(shallow, "CUP") == []      # ... but the rollback rule rejects it:
    with pytest.MonkeyPatch.context() as mp:                     # a 25-point cup after a 17-point advance
        mp.setattr(scan, "CUP_MAX_RETRACE", None)
        assert scan.detect_cup_and_handle(shallow, "CUP")        # SMA50 > SMA200 alone satisfies the trend filter


def test_cup_rollback_rule_limits_depth_to_half_the_advance():
    """Spec: the cup decline may retrace at most 50 % of the preceding advance."""
    ok = cup_variant(pre=_uptrend_prefix(220, 40, 100))          # 25-point cup after a 60-point advance (42 %)
    assert scan.detect_cup_and_handle(ok, "CUP")
    too_deep = cup_variant(pre=_uptrend_prefix(220, 60, 100))    # same cup after a 40-point advance (62 %)
    assert scan.detect_cup_and_handle(too_deep, "CUP") == []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(scan, "CUP_MAX_RETRACE", None)
        assert scan.detect_cup_and_handle(too_deep, "CUP")        # the rollback rule is the only reason


def test_wick_above_rim_b_inside_the_handle_raises_the_trigger(cup_df):
    """The trigger is the handle high, which is not bounded by rim B."""
    (base,) = scan.detect_cup_and_handle(cup_df, "CUP")
    m = re.search(r"right rim (\S+) @([\d.]+)", base.notes)
    rim_b = float(m[2])
    spiked = cup_df.copy()
    i = spiked.index[-8]                                   # inside the handle, close stays low
    spiked.loc[i, "High"] = rim_b * 1.03
    (s,) = scan.detect_cup_and_handle(spiked, "CUP")
    assert base.status == "CONFIRMED" and s.status == "WATCHLIST"   # the 102 close no longer clears it
    assert s.entry == pytest.approx(rim_b * 1.03, abs=TOL) and s.entry > rim_b
    assert f"trigger {s.entry:.2f}" in s.notes


def test_cup_unbroken_within_three_percent_is_watchlisted():
    (s,) = scan.detect_cup_and_handle(cup_variant(brk=np.array([98.0, 98.5])), "CUP")
    assert s.status == "WATCHLIST" and s.bars_since_break is None and s.volume_ratio is None
    assert s.entry > s.last_close                         # entry is the still-unbroken trigger
    assert s.entry * (1 - scan.WATCH_PROXIMITY) <= s.last_close < s.entry


def ihs_variant(head_low=70.0, rs_low=81.0, base=None) -> pd.DataFrame:
    base = np.linspace(112, 120, 160) if base is None else base
    pre = np.linspace(120, 92, 80)
    ls = np.concatenate([np.linspace(92, 80, 12), np.linspace(80, 90, 12)])
    head = np.concatenate([np.linspace(90, head_low, 15), np.linspace(head_low, 90.5, 15)])
    rs = np.concatenate([np.linspace(90.5, rs_low, 12), np.linspace(rs_low, 89, 12)])
    brk = np.array([90.0, 92.5, 93.0])
    df = _ohlc_from_path(np.concatenate([base, pre, ls, head, rs, brk]), seed=5)
    df.loc[df.index[-3:-1], "Volume"] *= 3.0
    return df


@pytest.mark.parametrize("label, kwargs", [
    ("head not >= 1 ATR below the shoulders", dict(head_low=79.5)),
    ("shoulders asymmetric beyond 30 % of the head height", dict(rs_low=74.0)),
])
def test_ihs_single_rule_violations_are_rejected(label, kwargs):
    assert scan.detect_inverse_hs(ihs_variant(**kwargs), "IHS") == [], label


def test_strong_downtrend_veto_is_a_legacy_rule():
    """Spec: reversal patterns are expected in down-trends, so no veto; legacy vetoed them."""
    df = ihs_variant(base=np.linspace(300, 120, 160))
    assert scan.trend_context(df)[2], "fixture must be a strong down-trend"
    assert scan.detect_inverse_hs(df, "IHS")                     # spec profile: allowed
    scan.apply_profile("legacy")
    assert scan.detect_inverse_hs(df, "IHS") == []               # legacy profile: vetoed


def wolfe_variant(points=None, rebound=None) -> pd.DataFrame:
    base = np.linspace(95, 105, 230)
    points = [(0, 100.0), (10, 108.0), (22, 96.0), (32, 103.0), (46, 91.5)] if points is None else points
    seg = [np.linspace(v0, v1, b1 - b0, endpoint=False)
           for (b0, v0), (b1, v1) in zip(points[:-1], points[1:])]
    wedge = np.concatenate(seg + [[points[-1][1]]])
    rebound = np.array([92.0, 92.5, 93.0, 93.5, 94.0, 94.8, 95.5]) if rebound is None else rebound
    return _ohlc_from_path(np.concatenate([base, wedge, rebound]), seed=7, noise=0.002)


@pytest.mark.parametrize("label, kwargs", [
    ("point 4 above point 2 (not between 1 and 2)",
     dict(points=[(0, 100.0), (10, 108.0), (22, 96.0), (32, 109.0), (46, 90.5)])),
    ("point 5 breaks down for real (> WW_MAX_OVERSHOOT_ATR)",
     dict(points=[(0, 100.0), (10, 108.0), (22, 96.0), (32, 103.0), (46, 80.0)],
          rebound=np.array([80.5, 81, 81.5, 82, 82.5, 83, 83.5]))),
    ("no close back above line 1-3", dict(rebound=np.array([90.6, 90.4, 90.7, 90.5, 90.6, 90.4, 90.5]))),
])
def test_wolfe_single_rule_violations_are_rejected(label, kwargs):
    assert scan.detect_bullish_wolfe(wolfe_variant(**kwargs), "WW") == [], label


def test_wolfe_target_is_dropped_when_the_lines_meet_too_far_out(wolfe_df):
    (base,) = scan.detect_bullish_wolfe(wolfe_df, "WW")
    assert base.target is not None
    with pytest.MonkeyPatch.context() as mp:            # fixture ETA is ~160 bars after point 5
        mp.setattr(scan, "WW_MAX_ETA_BARS", 100)
        (s,) = scan.detect_bullish_wolfe(wolfe_df, "WW")
    assert s.target is None and (s.entry, s.stop, s.status) == (base.entry, base.stop, base.status)


def test_wolfe_target_is_dropped_when_absurdly_far(wolfe_df):
    (base,) = scan.detect_bullish_wolfe(wolfe_df, "WW")
    assert base.target is not None and base.target < base.entry * 2
    with pytest.MonkeyPatch.context() as mp:                # fixture target is ~+29 %
        mp.setattr(scan, "WW_MAX_TARGET_GAIN", 0.2)
        (s,) = scan.detect_bullish_wolfe(wolfe_df, "WW")
    assert s.target is None and s.entry == base.entry


def test_rule_profiles_apply_and_restore():
    assert scan.ACTIVE_PROFILE == "spec"
    previous = scan.apply_profile("tuned")
    assert previous == "spec" and scan.ACTIVE_PROFILE == "tuned"
    assert scan.VOLUME_CONFIRM["Cup & Handle"] is None and scan.IHS_SIDE_SYM_TOL is None
    assert scan.WW_TIME_SYM_TOL == 0.60 and scan.CUP_MAX_RETRACE == 0.618
    assert scan.WW_SWEET_ZONE is True and scan.CUP_MIN_ROUNDNESS == 0.70      # the rest stays spec
    scan.apply_profile("legacy")
    assert scan.WW_SWEET_ZONE is False and scan.CUP_MIN_ROUNDNESS == 0.60
    scan.apply_profile("spec")
    assert scan.VOLUME_CONFIRM["Cup & Handle"] == 1.4 and scan.WW_TIME_SYM_TOL == 0.30
    with pytest.raises(ValueError):
        scan.apply_profile("nope")


def test_scan_symbol_detector_subset(cup_df):
    assert scan.scan_symbol("CUP", cup_df, detectors=(scan.detect_inverse_hs,)) == []
    assert [s.pattern for s in scan.scan_symbol("CUP", cup_df)] == ["Cup & Handle"]


def test_fat_tailed_noise_false_positive_rate():
    """Student-t(3) returns (fat tails, spikes) must not inflate the false-positive rate."""
    rng = np.random.default_rng(7)
    fired = 0
    for k in range(200):
        path = 100 * np.exp(np.cumsum(rng.standard_t(3, 500) * 0.015 / np.sqrt(3)))
        if scan.scan_symbol(f"T{k}", _ohlc_from_path(path, seed=k)):
            fired += 1
    assert fired / 200 < 0.05, fired


def test_w_shaped_base_is_not_a_cup_across_its_full_span():
    """Two bowls with a rally to the rim between them: the full span fails roundness.

    The lows of a W are not one parabola (R^2 ~ 0.06 here).  The second bowl
    on its own does qualify as a cup, which is equivalent to O'Neil's
    double-bottom buy point at the middle peak, so a signal may still appear
    anchored on the rally high; what must never appear is a cup spanning both
    bowls.
    """
    pre = _uptrend_prefix(220, 60, 100)
    t = np.linspace(0, np.pi, 50)
    w = np.concatenate([100 - 25 * np.sin(t), 99 - 24 * np.sin(t)])
    handle = np.concatenate([np.linspace(100, 94, 8), np.linspace(94, 97, 7)])
    df = _ohlc_from_path(np.concatenate([pre, w, handle, np.array([101.5, 102.0])]), seed=3)
    assert scan._u_shape_r2(df["Low"].to_numpy()[220:320]) < scan.CUP_MIN_ROUNDNESS
    for s in scan.detect_cup_and_handle(df, "W"):
        left_rim = pd.Timestamp(re.search(r"left rim (\S+)", s.notes)[1])
        # anchored on the middle rally (bar ~269), never on rim A (~220) or the first bottom (~245)
        assert left_rim >= df.index[260], s.notes


def test_zero_price_bars_are_rejected_without_errors(cup_df, caplog):
    """Bad-data zeros never raise: inside the pattern they void it, far before it they do not matter."""
    prices = cup_df.columns.get_indexer(["Open", "High", "Low", "Close"])
    def zeroed(rows):
        df = cup_df.copy()
        df.iloc[rows, prices] = 0.0
        return df

    with caplog.at_level("ERROR", logger="sp500scan"):
        assert len(scan.scan_symbol("Z", zeroed(slice(10, 20)))) == 1      # long before the pattern
        assert scan.scan_symbol("Z", zeroed(slice(-60, -50))) == []        # inside the cup
        assert scan.scan_symbol("Z", zeroed(-1)) == []                     # on the last bar
    assert "failed on" not in caplog.text                     # no detector raised


def test_flat_line_and_random_walk_controls_are_silent(flat_df):
    assert scan.scan_symbol("FLAT", flat_df) == []
    assert scan.atr(flat_df).iloc[-1] == 0.0
    assert scan.scan_symbol("LINE", _ohlc_from_path(np.linspace(50, 150, 400), noise=0.0)) == []
    assert scan.scan_symbol("NOISE", make_random_walk(0)) == []


# --------------------------------------------------------------------------- #
# 3b. Data boundaries
# --------------------------------------------------------------------------- #
def _levels(sig: scan.Signal):
    return sig.status, sig.entry, sig.stop, sig.target


def test_missing_bars_do_not_move_the_levels(cup_df):
    (base,) = scan.detect_cup_and_handle(cup_df, "CUP")
    for gap in ([5, 50, 150], [250, 300], list(range(240, 260))):
        holed = cup_df.drop(cup_df.index[gap])
        (s,) = scan.detect_cup_and_handle(holed, "CUP")
        assert _levels(s) == _levels(base), gap                  # bars are positional, not calendar


def test_breakout_without_volume_is_watchlisted_under_spec_and_bonus_only_under_legacy(cup_df):
    (base,) = scan.detect_cup_and_handle(cup_df, "CUP")
    assert base.status == "CONFIRMED" and base.volume_ratio >= scan.VOLUME_CONFIRM["Cup & Handle"]
    spot = cup_df.copy()
    spot.loc[spot.index[-2], "Volume"] = 0.0                      # zero volume on the breakout bar
    (s,) = scan.detect_cup_and_handle(spot, "CUP")
    assert s.status == "WATCHLIST" and s.bars_since_break is None  # spec: no volume, no confirmation
    assert "breakout without volume (0.0x)" in s.notes and s.entry == base.entry - (base.entry - float(
        re.search(r"trigger ([\d.]+)", base.notes)[1]))           # entry falls back to the trigger
    dead = cup_df.copy()
    dead["Volume"] = 0.0
    (s,) = scan.detect_cup_and_handle(dead, "CUP")
    assert s.status == "WATCHLIST" and "n/a" in s.notes
    scan.apply_profile("legacy")                                   # legacy: volume was only a +5 bonus
    (legacy_base,) = scan.detect_cup_and_handle(cup_df, "CUP")
    (s,) = scan.detect_cup_and_handle(dead, "CUP")
    assert s.status == "CONFIRMED" and s.volume_ratio is None and s.score == legacy_base.score - 5


def test_volatility_spikes_inside_the_pattern_invalidate_it(cup_df):
    (base,) = scan.detect_cup_and_handle(cup_df, "CUP")
    wick = cup_df.copy()
    wick.loc[wick.index[-8], "Low"] *= 0.80                       # -20 % wick inside the handle
    assert scan.detect_cup_and_handle(wick, "CUP") == []          # handle depth rule
    wick = cup_df.copy()
    wick.loc[wick.index[-60], "Low"] *= 0.60                      # -40 % wick in the cup body
    assert scan.detect_cup_and_handle(wick, "CUP") == []          # bottom position / roundness
    wick = cup_df.copy()
    wick.loc[wick.index[100], "High"] *= 1.5                      # spike long before the pattern
    (s,) = scan.detect_cup_and_handle(wick, "CUP")
    assert _levels(s) == _levels(base)


def test_stock_split_is_neutralised_by_adjust_ohlc(cup_df):
    (base,) = scan.detect_cup_and_handle(cup_df, "CUP")
    raw = cup_df.copy()
    raw["Adj Close"] = cup_df["Close"]                            # Yahoo's adjusted series
    prices = raw.columns.get_indexer(["Open", "High", "Low", "Close"])
    raw.iloc[:200, prices] *= 2.0                                 # pre-split prices as traded
    raw.iloc[:200, raw.columns.get_indexer(["Volume"])] /= 2.0
    unadjusted = raw[["Open", "High", "Low", "Close", "Volume"]]
    assert scan.detect_cup_and_handle(unadjusted, "CUP") == []   # the 2x gap breaks the geometry
    adj = scan.adjust_ohlc(raw)
    assert list(adj.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert np.allclose(adj[["Open", "High", "Low", "Close"]].to_numpy(),
                       cup_df[["Open", "High", "Low", "Close"]].to_numpy())
    # Volume is never rescaled: Yahoo's volume is already split-adjusted and the
    # Adj Close / Close ratio also carries dividends, so scaling volume by its
    # inverse would double-adjust splits (yfinance's auto_adjust agrees).
    assert (adj["Volume"] == raw["Volume"]).all()
    (s,) = scan.detect_cup_and_handle(adj, "CUP")
    assert _levels(s) == _levels(base) and s.score == base.score


def test_detectors_are_deterministic(cup_df):
    a = [scan.asdict(s) for s in scan.scan_symbol("X", cup_df)]
    b = [scan.asdict(s) for s in scan.scan_symbol("X", cup_df.copy())]
    assert a == b and a
