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


@pytest.mark.parametrize("close, start, lag, expected", [
    ([90, 95, 101.0], 0, 0, ("CONFIRMED", 0)),          # broke on the last bar
    ([90, 101, 101.0], 0, 0, ("CONFIRMED", 1)),         # broke one bar ago
    ([90, 95, 98.0], 0, 0, ("WATCHLIST", None)),        # within WATCH_PROXIMITY (3 %)
    ([90, 95, 96.9], 0, 0, ("STALE", None)),            # just outside 3 %
    ([90, 101, 101, 101, 101, 101.0], 0, 0, ("STALE", 4)),      # older than MAX_BREAKOUT_AGE
    ([90, 101, 101, 101, 101, 101.0], 0, 5, ("CONFIRMED", 4)),  # ... unless the pivot lag allows it
    ([90, 101, 106.0], 0, 0, ("STALE", 1)),             # > MAX_RUNAWAY above trigger: chasing
    ([90, 101, 104.9], 0, 0, ("CONFIRMED", 1)),         # 4.9 % is still an entry
    ([90, 101, 99.0], 0, 0, ("STALE", 1)),              # failed break (closed back below)
    ([101, 90, 95, 98.0], 1, 0, ("WATCHLIST", None)),   # breaks before `start` do not count
])
def test_status_from_break_state_table(close, start, lag, expected):
    assert scan._status_from_break(np.array(close, float), 100.0, start, lag=lag) == expected


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
    assert scan._volume_ratio(cup_df, n - 1) == pytest.approx(
        cup_df["Volume"].iloc[-1] / cup_df["Volume"].iloc[n - 51:n - 1].mean(), abs=0.006)


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
    assert abs(rim_b - rim_a) / rim_a <= scan.CUP_RIM_TOL
    assert scan.CUP_MIN_DEPTH <= (rim_a - bottom) / rim_a <= scan.CUP_MAX_DEPTH
    assert handle_low < trigger
    # Prior advance is a *rise* from the 120-bar low to rim A (not "low 25 % below rim").
    pre_low = low[max(0, a - 120):a + 1].min()
    assert (rim_a - pre_low) / pre_low >= scan.CUP_PRIOR_ADVANCE
    # Trigger = handle high; first close above it after the handle is the break.
    assert high[b + 1:h + 1].max() <= trigger + TOL
    first_break = next(i for i in range(h + 1, len(close)) if close[i] > trigger)
    assert s.bars_since_break == len(close) - 1 - first_break == 1
    # Entry = breakout close (above trigger, within MAX_RUNAWAY); stop / target / risk formulas.
    assert s.status == "CONFIRMED" and s.entry == round(close[-1], 2) == s.last_close
    assert trigger < s.entry <= trigger * (1 + scan.MAX_RUNAWAY)
    atr = scan.atr(cup_df).to_numpy()
    assert s.stop == pytest.approx(handle_low - 0.25 * atr[h], abs=TOL)
    assert s.target == pytest.approx(s.entry + (rim_a - bottom), abs=TOL)
    assert s.risk_pct == pytest.approx((s.entry - s.stop) / s.entry * 100, abs=0.02)
    assert s.volume_ratio == scan._volume_ratio(cup_df, first_break)


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
    # Head depth and shoulder symmetry rules hold on the reported anchors.
    unit = scan.atr(ihs_df).to_numpy()
    assert h_v < ls_v - scan.IHS_MIN_HEAD_ATR * unit[h] and h_v < rs_v - scan.IHS_MIN_HEAD_ATR * unit[h]
    assert abs(ls_v - rs_v) <= scan.IHS_SHOULDER_SYM * min(ls_v - h_v, rs_v - h_v)
    # Neckline through the highest highs of each half; slope bounded.
    n1 = ls + int(np.argmax(high[ls:h + 1]))
    n2 = h + int(np.argmax(high[h:rs + 1]))
    slope = (high[n2] - high[n1]) / (n2 - n1)
    assert (float(m[7]), float(m[8])) == (round(high[n1], 2), round(high[n2], 2))
    assert abs(slope * (rs - ls)) / close[h] <= scan.IHS_MAX_NECK_SLOPE
    # Prior decline is measured as a share of the 60-bar high before LS.
    look = high[max(0, ls - 60):ls + 1]
    assert (look.max() - ls_v) / look.max() >= scan.IHS_PRIOR_DECLINE
    neck = lambda i: high[n1] + slope * (i - n1)  # noqa: E731
    assert float(m[9]) == pytest.approx(neck(n - 1), abs=TOL)
    first_break = next(j for j in range(rs + 1, n) if close[j] > neck(j))
    trigger = neck(first_break)
    assert s.bars_since_break == n - 1 - first_break
    assert s.status == "CONFIRMED" and s.entry == round(close[-1], 2)
    assert s.stop == pytest.approx(rs_v - 0.25 * unit[rs], abs=TOL)
    assert s.target == pytest.approx(s.entry + (trigger - h_v), abs=TOL)   # neckline-to-head height
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
    assert -0.5 * atr[p5] <= overshoot <= scan.WW_MAX_OVERSHOOT_ATR * atr[p5]
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
    pre = _uptrend_prefix(220, 60, 100) if pre is None else pre
    cup = (100 - 25 * np.sin(T)) if cup is None else cup
    handle = np.concatenate([np.linspace(100, 94, 8), np.linspace(94, 97, 7)]) if handle is None else handle
    brk = np.array([101.5, 102.0]) if brk is None else brk
    df = _ohlc_from_path(np.concatenate([pre, cup, handle, brk]), seed=3)
    df.loc[df.index[-2], "Volume"] *= 2.0
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
    """The rule is a >= 25 % rise from the 120-bar low into rim A.

    A low 20.6 % below the rim (a 25.9 % rise) passes, which a "low must be
    25 % below the rim" reading would reject; a 19.9 % rise fails.  The low
    sits inside the 120-bar look-back window before the rim.
    """
    def prefix(low):
        return np.concatenate([np.full(100, low), np.linspace(low, 100, 120)])
    assert scan.detect_cup_and_handle(cup_variant(pre=prefix(100 / 1.259)), "CUP")
    assert scan.detect_cup_and_handle(cup_variant(pre=prefix(100 / 1.199)), "CUP") == []


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
    return _ohlc_from_path(np.concatenate([base, pre, ls, head, rs, brk]), seed=5)


@pytest.mark.parametrize("label, kwargs", [
    ("head not >= 1 ATR below the shoulders", dict(head_low=79.5)),
    ("shoulders asymmetric beyond IHS_SHOULDER_SYM", dict(rs_low=74.0)),
    ("strong down-trend veto (rule 2)", dict(base=np.linspace(300, 120, 160))),
])
def test_ihs_single_rule_violations_are_rejected(label, kwargs):
    df = ihs_variant(**kwargs)
    if "veto" in label:
        assert scan.trend_context(df)[2], "fixture must be a strong down-trend"
    assert scan.detect_inverse_hs(df, "IHS") == [], label


def wolfe_variant(points=None, rebound=None) -> pd.DataFrame:
    base = np.linspace(95, 105, 230)
    points = [(0, 100.0), (10, 108.0), (22, 96.0), (32, 103.0), (46, 90.5)] if points is None else points
    seg = [np.linspace(v0, v1, b1 - b0, endpoint=False)
           for (b0, v0), (b1, v1) in zip(points[:-1], points[1:])]
    wedge = np.concatenate(seg + [[points[-1][1]]])
    rebound = np.array([91.0, 92.0, 92.8, 93.5, 94.0, 94.8, 95.5]) if rebound is None else rebound
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


def test_zero_volume_sessions_only_cost_the_volume_bonus(cup_df):
    (base,) = scan.detect_cup_and_handle(cup_df, "CUP")
    assert base.volume_ratio >= 1.3                               # fixture has breakout volume
    dead = cup_df.copy()
    dead["Volume"] = 0.0
    (s,) = scan.detect_cup_and_handle(dead, "CUP")
    assert s.volume_ratio is None and s.score == base.score - 5 and _levels(s) == _levels(base)
    spot = cup_df.copy()
    spot.loc[spot.index[-2], "Volume"] = 0.0                      # zero volume on the breakout bar
    (s,) = scan.detect_cup_and_handle(spot, "CUP")
    assert s.volume_ratio == 0.0 and s.score == base.score - 5


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
    assert (adj["Volume"] == raw["Volume"]).all()                 # volume is never rescaled
    (s,) = scan.detect_cup_and_handle(adj, "CUP")
    assert _levels(s) == _levels(base) and s.score == base.score


def test_detectors_are_deterministic(cup_df):
    a = [scan.asdict(s) for s in scan.scan_symbol("X", cup_df)]
    b = [scan.asdict(s) for s in scan.scan_symbol("X", cup_df.copy())]
    assert a == b and a
