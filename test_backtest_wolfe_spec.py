#!/usr/bin/env python3
"""Tests for tools/backtest_wolfe_spec.py: the 1H Wolfe specification's rules on synthetic hourly bars (offline)."""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
import backtest_wolfe_spec as bws  # noqa: E402
import scan  # noqa: E402

WICK = 0.05                                   # fixed wicks: the fixtures are deterministic, no random intrabar noise
P1, P2, P3, P4, P5 = 220, 230, 242, 252, 266  # bar indices of the fixture's five points
TRIGGER = 270                                 # first close back above line 1-3 from the bar that confirms point 5
END = "2026-09-17 15:30"
WEDGE = [(0, 100.0), (10, 106.0), (22, 97.0), (32, 102.5), (46, 93.0)]   # points 1-5, bars relative to point 1


def hourly_ohlc(path, end: str = END, trigger_bar=None) -> pd.DataFrame:
    """OHLCV from a close path: fixed 5-cent wicks, an open a quarter of the way into each bar's move (so the
    bar after a swing low has a strictly higher low), constant volume doubled on ``trigger_bar``, on seven
    hourly stamps per business day from 09:30 to 15:30, what Yahoo returns for US regular hours."""
    close = np.asarray(path, dtype=float)
    n = len(close)
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1] + 0.25 * (close[1:] - close[:-1])
    high = np.maximum(open_, close) + WICK
    low = np.minimum(open_, close) - WICK
    vol = np.full(n, 1_000_000.0)
    if trigger_bar is not None:
        vol[trigger_bar] = 2_000_000.0
    days = pd.bdate_range(end=pd.Timestamp(end).normalize(), periods=n // 7 + 2)
    stamps = [d + pd.Timedelta(hours=9, minutes=30) + pd.Timedelta(hours=h) for d in days for h in range(7)]
    idx = pd.DatetimeIndex(stamps[-n:])
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


def wedge(points) -> np.ndarray:
    """Linear segments through ``(bar, price)`` points; the last point is included."""
    seg = [np.linspace(v0, v1, b1 - b0, endpoint=False) for (b0, v0), (b1, v1) in zip(points[:-1], points[1:])]
    return np.concatenate(seg + [[points[-1][1]]])


def wolfe_path(reclaim=(93.8, 93.3, 93.25, 94.0), after: str = "rally") -> np.ndarray:
    """A 220-bar drift from 104 to 100.6 with a dip to 92.9 at bar 101 (an earlier low near point 5), the wedge
    100 -> 106 -> 97 -> 102.5 -> 93 (points 1-5 at bars 220, 230, 242, 252, 266), the ``reclaim`` closes after
    point 5 (by default above line 1-3 at bar 267, below it at 268-269, above again at 270), then a rally to
    106 held for 30 bars (``"rally"``) or 100 flat bars at 95 (``"flat"``)."""
    base = np.linspace(104.0, 100.6, 220)
    base[95:106] = np.concatenate([np.linspace(base[95], 92.9, 6, endpoint=False), np.linspace(92.9, base[106], 5)])
    post = (np.concatenate([np.linspace(94.5, 106.0, 24), np.full(30, 106.0)]) if after == "rally"
            else np.full(100, 95.0))
    return np.concatenate([base, wedge(WEDGE), np.asarray(reclaim, dtype=float), post])


@pytest.fixture
def wolfe_1h() -> pd.DataFrame:
    return hourly_ohlc(wolfe_path(), trigger_bar=TRIGGER)


@pytest.fixture
def params() -> bws.Params:
    return bws.Params.for_interval("1h")


# --------------------------------------------------------------------------- #
# Section 2: swing points and the geometry
# --------------------------------------------------------------------------- #
def test_swing_points_are_strict_three_bar_extrema():
    high = np.array([1, 2, 3, 4, 5, 4, 3, 2, 1, 1, 1, 1, 1], dtype=float)
    assert bws.swing_points(high, -high) == ([4], [4])          # the peak / the trough; the flat stretch has none
    plateau = np.array([1, 2, 3, 5, 5, 3, 2, 1, 0, 0], dtype=float)
    assert bws.swing_points(plateau, -plateau) == ([], [])      # a tie is not a swing point (strict)
    late = np.concatenate([np.zeros(5), [9.0], np.zeros(2)])
    assert bws.swing_points(late, -late) == ([], [])            # only two bars after the peak: not confirmable
    assert bws.swing_points(late, -late, right=2) == ([5], [5])


def test_geometry_rules_match_the_specification():
    ok = bws.wolfe_geometry_ok
    assert ok(100, 106, 97, 102.5, 93, 0, 10, 22, 32)
    assert not ok(100, 106, 97, 106.5, 93, 0, 10, 22, 32)      # point 4 above point 2
    assert not ok(100, 106, 97, 99.5, 93, 0, 10, 22, 32)       # point 4 below point 1: no overlap with the 1-2 range
    assert not ok(100, 106, 100.5, 102.5, 93, 0, 10, 22, 32)   # point 3 not below point 1
    assert not ok(100, 106, 97, 102.5, 97.5, 0, 10, 22, 32)    # point 5 not below point 3
    assert not ok(100, 106, 97, 103.5, 93, 0, 10, 22, 32)      # |m24| = 2.5/22 < |m13| = 3/22: the lines diverge
    assert not ok(100, 106, 97, 103.0, 93, 0, 10, 22, 32)      # equal slopes: parallel, never meet


def test_fixture_has_the_intended_structure(wolfe_1h, params):
    high, low, close = (wolfe_1h[c].to_numpy() for c in ("High", "Low", "Close"))
    assert bws.swing_points(high, low) == ([P2, P4], [101, P1, P3, P5])   # the dip at bar 101 is the earlier low
    (s,) = bws.wolfe_setups(high, low, params.window_bars)
    assert (s.p1, s.p2, s.p3, s.p4, s.p5) == (P1, P2, P3, P4, P5)
    assert (s.v1, s.v2, s.v5) == (low[P1], high[P2], low[P5])
    assert s.s24 < s.s13 < 0                                     # converging: the upper line falls faster
    assert low[P5] < s.line13(P5)                                # the sweep
    assert bws.find_trigger(s, close, low, params.window_bars, params.max_reclaim_bars) == (TRIGGER, P5 + 1, "trigger")


# --------------------------------------------------------------------------- #
# Sections 1 and 3: the trade
# --------------------------------------------------------------------------- #
def test_one_trade_with_the_specifications_levels(wolfe_1h, params):
    rows, funnel = bws.replay_symbol("WW", wolfe_1h, params)
    assert funnel == {"symbols": 1, "structures": 1, "no_sweep": 0, "undercut": 0, "no_reclaim": 0, "reclaimed": 1,
                      "no_room": 0, "position_open": 0, "trades": 1}
    (r,) = rows
    h, low, c = (wolfe_1h[k].to_numpy() for k in ("High", "Low", "Close"))
    atr = bws.atr_series(h, low, c)[TRIGGER]
    entry, stop, tp1 = c[TRIGGER], low[P5] - 0.5 * atr, h[P4]
    assert r["symbol"] == "WW" and r["trigger_time"] == str(wolfe_1h.index[TRIGGER])
    assert r["bars_P1_to_P5"] == P5 - P1 and r["reclaim_lag"] == TRIGGER - P5 and r["literal_reclaim_lag"] == 1
    assert (r["p1_price"], r["p2_price"], r["p3_price"], r["p4_price"], r["p5_low"]) == \
        tuple(round(v, 4) for v in (low[P1], h[P2], low[P3], h[P4], low[P5]))
    assert (r["entry_price"], r["stop_loss"], r["tp1_target"]) == (round(entry, 4), round(stop, 4), round(tp1, 4))
    assert r["projected_RR"] == round((tp1 - entry) / (entry - stop), 3) > 2 and r["rr_bucket"] == "> 2.0 R"
    # the rally reaches the point-4 high without a gap: TP1 at the target, realised R = projected R
    k = next(i for i in range(TRIGGER + 1, len(c)) if h[i] >= tp1)
    assert r["exit_reason"] == "TP1" and r["bars_held"] == k - TRIGGER < params.max_hold_bars
    assert r["exit_price"] == round(tp1, 4) and r["realized_R"] == round((tp1 - entry) / (entry - stop), 4)


def test_confirmation_factors_are_read_at_the_trigger(wolfe_1h, params):
    (r,), _ = bws.replay_symbol("WW", wolfe_1h, params)
    o, h, low, c = (wolfe_1h[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    assert r["body_ratio"] == round(abs(c[TRIGGER] - o[TRIGGER]) / (h[TRIGGER] - low[TRIGGER]), 3)
    assert r["volume_ratio"] == 2.0                                  # doubled volume on the trigger bar
    rsi = bws.rsi_series(c)
    assert (r["rsi_p3"], r["rsi_p5"]) == (round(rsi[P3], 2), round(rsi[P5], 2))
    assert r["rsi_divergence"] == (rsi[P5] > rsi[P3])
    ema = bws.ema_series(c, bws.HTF_EMA_LEN * params.htf_factor)
    assert r["htf_ema"] == round(ema[TRIGGER], 4) and r["htf_trend_4h"] == "Bearish"   # the entry sits under the EMA
    assert c[TRIGGER] < ema[TRIGGER]
    assert r["support_touches"] == 1 and r["nearby_support"] is True   # the dip at bar 101, within 0.5 ATR of point 5
    assert r["market_regime_spy"] is None and r["vix"] is None and r["market_date"] is None   # no context given
    assert r["sweep_depth_atr"] > 0 and r["atr14"] == round(bws.atr_series(h, low, c)[TRIGGER], 4)


def test_entry_is_not_anticipated(params):
    """A reclaim close before point 5 is confirmable (three bars after it) is recorded, not traded."""
    df = hourly_ohlc(wolfe_path(reclaim=(93.8, 93.9, 94.0, 94.1)))   # above the line from bar 267 on
    high, low, close = (df[c].to_numpy() for c in ("High", "Low", "Close"))
    (s,) = bws.wolfe_setups(high, low, params.window_bars)
    assert bws.find_trigger(s, close, low, params.window_bars, params.max_reclaim_bars) == (P5 + 3, P5 + 1, "trigger")
    (r,), _ = bws.replay_symbol("WW", df, params)
    assert (r["reclaim_lag"], r["literal_reclaim_lag"], r["entry_price"]) == (3, 1, 94.0)


def test_trigger_reasons(params):
    df = hourly_ohlc(wolfe_path())
    high, low, close = (df[c].to_numpy() for c in ("High", "Low", "Close"))
    (s,) = bws.wolfe_setups(high, low, params.window_bars)
    lifted = low.copy()
    lifted[P5] = s.line13(P5)                                         # point 5 at the line, not below it
    assert bws.find_trigger(s, close, lifted, params.window_bars, params.max_reclaim_bars) == (None, None, "no_sweep")
    # the window covers the entry bar: one ending before bar 270 leaves no reclaim, as does a shorter reclaim limit
    assert bws.find_trigger(s, close, low, TRIGGER - P1 - 1, params.max_reclaim_bars) == (None, P5 + 1, "no_reclaim")
    assert bws.find_trigger(s, close, low, params.window_bars, 3) == (None, P5 + 1, "no_reclaim")
    # a lower low before the reclaim: that low is the structure's point 5, not this one
    df2 = hourly_ohlc(wolfe_path(reclaim=(93.3, 93.2, 93.1, 92.5, 92.4, 94.5, 94.6, 94.7), after="flat"))
    high2, low2, close2 = (df2[c].to_numpy() for c in ("High", "Low", "Close"))
    (s2,) = bws.wolfe_setups(high2, low2, params.window_bars)
    assert bws.find_trigger(s2, close2, low2, params.window_bars, params.max_reclaim_bars) == (None, P5 + 6, "undercut")
    rows, funnel = bws.replay_symbol("WW", df2, params)
    assert rows == [] and (funnel["structures"], funnel["undercut"], funnel["trades"]) == (1, 1, 0)


def test_exit_rules():
    def sim(open_, high, low, close, max_hold):
        arrays = [np.asarray(x, dtype=float) for x in (open_, high, low, close)]
        return bws.simulate(*arrays, 0, 100.0, 95.0, 110.0, max_hold)

    # a bar touching both levels is a stop, at the stop
    assert sim([100, 100], [100, 111], [100, 94], [100, 105], 10) == \
        {"exit_reason": "SL", "bars_held": 1, "exit_price": 95.0, "realized_R": -1.0}
    # a gap below the stop fills at the open; a gap above the target fills at the open
    assert sim([100, 93], [100, 96], [100, 92], [100, 95], 10) == \
        {"exit_reason": "SL", "bars_held": 1, "exit_price": 93.0, "realized_R": -1.4}
    assert sim([100, 112], [100, 113], [100, 111], [100, 112], 10) == \
        {"exit_reason": "TP1", "bars_held": 1, "exit_price": 112.0, "realized_R": 2.4}
    # neither within the holding period: out at the close of its last bar; the history ending first: open
    assert sim([100] * 4, [101] * 4, [99] * 4, [100, 101, 102, 103], 3) == \
        {"exit_reason": "TIME_EXIT", "bars_held": 3, "exit_price": 103.0, "realized_R": 0.6}
    assert sim([100] * 4, [101] * 4, [99] * 4, [100, 101, 102, 103], 10) == \
        {"exit_reason": "OPEN", "bars_held": 3, "exit_price": 103.0, "realized_R": 0.6}


def test_low_reward_trades_are_kept_and_bucketed(params):
    """The specification logs every qualifying trade, whatever its projected R, and buckets it."""
    df = hourly_ohlc(wolfe_path(reclaim=(93.8, 93.3, 93.25, 101.0), after="flat"))   # a huge reclaim candle
    (r,), funnel = bws.replay_symbol("WW", df, params)
    assert funnel["trades"] == 1 and r["entry_price"] == 101.0 and r["projected_RR"] < 1
    assert r["rr_bucket"] == "< 1.0 R"
    assert r["exit_reason"] == "TIME_EXIT" and r["bars_held"] == params.max_hold_bars   # flat at 95 afterwards
    assert r["exit_price"] == 95.0 and r["realized_R"] < 0
    # an entry already above the point-4 high leaves no room for a target
    df = hourly_ohlc(wolfe_path(reclaim=(93.8, 93.3, 93.25, 103.0), after="flat"))
    _, funnel = bws.replay_symbol("WW", df, params)
    assert (funnel["reclaimed"], funnel["no_room"], funnel["trades"]) == (1, 1, 0)


def test_one_position_per_symbol(params):
    """While a trade is open, a second structure's trigger on the same symbol is skipped and counted."""
    first = wolfe_path(after="flat")[:TRIGGER + 1]                     # up to and including the first entry bar
    second = wedge([(0, 96.0), (10, 100.0), (22, 94.5), (32, 98.0), (46, 92.75)])   # its low stays above the stop
    path = np.concatenate([first, np.linspace(94.5, 96.5, 20), second, [93.0, 93.1, 93.2, 93.4],
                           np.linspace(94.0, 106.0, 24), np.full(30, 106.0)])
    df = hourly_ohlc(path)
    rows, funnel = bws.replay_symbol("WW", df, params)
    assert (funnel["structures"], funnel["reclaimed"], funnel["position_open"], funnel["trades"]) == (2, 2, 1, 1)
    (r,) = rows
    assert r["trigger_time"] == str(df.index[TRIGGER]) and r["exit_reason"] == "TIME_EXIT"


def test_random_walks_rarely_trigger():
    """Sanity ceiling on noise: three-bar swings fire more often than scan.py's five-bar ones, but not on every wave."""
    n_series, n_bars, trades = 40, 1500, 0
    for seed in range(n_series):
        rng = np.random.default_rng(seed)
        path = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n_bars)))
        rows, _ = bws.replay_symbol(f"RW{seed}", hourly_ohlc(path), bws.Params.for_interval("1h"))
        trades += len(rows)
    per_1000 = 1000 * trades / (n_series * n_bars)
    print(f"\nrandom walks: {trades} trades over {n_series * n_bars} hourly bars ({per_1000:.2f} per 1,000 bars)")
    assert per_1000 <= 4.0


# --------------------------------------------------------------------------- #
# Section 4: the factors and their helpers
# --------------------------------------------------------------------------- #
def test_indicators_match_scan():
    df = hourly_ohlc(wolfe_path())
    close = df["Close"].to_numpy()
    rsi = bws.rsi_series(close)
    assert np.isnan(rsi[:bws.RSI_LEN]).all() and not np.isnan(rsi[bws.RSI_LEN:]).any()
    assert rsi[-1] == pytest.approx(scan._rsi(close), abs=0.01)             # the Wilder RSI the report's F&G uses
    assert rsi[bws.RSI_LEN + 5] == pytest.approx(scan._rsi(close[:bws.RSI_LEN + 6]), abs=0.01)
    atr = bws.atr_series(df["High"].to_numpy(), df["Low"].to_numpy(), close)
    assert atr == pytest.approx(scan.atr(df).to_numpy())                     # the same simple-mean ATR
    assert bws.rsi_series(np.full(50, 10.0))[-1] == 50.0                     # never moved
    assert bws.rsi_series(np.arange(50, dtype=float))[-1] == 100.0           # never fell
    ema = bws.ema_series(close, 200)
    assert np.isnan(ema[:199]).all() and not np.isnan(ema[199:]).any()


def test_body_volume_and_support_helpers():
    assert bws.body_ratio(100.0, 101.0, 99.0, 100.5) == 0.25 and bws.body_ratio(100.0, 100.0, 100.0, 100.0) is None
    vol = np.concatenate([np.full(20, 1e6), [1.5e6]])
    assert bws.volume_ratio(vol, 20) == 1.5 and bws.volume_ratio(vol, 19) is None    # needs 20 prior bars
    vol[5] = np.nan
    assert bws.volume_ratio(vol, 20) == 1.5                                          # NaN bars leave the mean
    assert bws.volume_ratio(np.zeros(21), 20) is None                                # a dead book has no ratio
    setup = bws.Setup(p1=300, p2=310, p3=320, p4=330, p5=340, v1=100, v2=106, v3=97, v4=102, v5=93.0)
    low = np.full(400, 100.0)
    low[[40, 60, 200, 305]] = [93.2, 92.9, 90.0, 93.1]
    swing_lows = [40, 60, 200, 305]
    assert bws.support_touches(low, swing_lows, setup, tol=0.4) == 1          # bar 60; 40 is outside the 250 bars,
    assert bws.support_touches(low, swing_lows, setup, tol=0.4, lookback=300) == 2   # 200 too far off, 305 after P1


def test_market_context_uses_the_last_completed_session_intraday():
    days = pd.bdate_range(end="2026-09-17", periods=80)
    spy = pd.DataFrame({"Close": np.linspace(500.0, 579.0, 80)}, index=days.tz_localize("America/New_York"))
    vix = pd.DataFrame({"Close": np.linspace(12.0, 27.8, 80)}, index=days)
    ctx = bws.daily_context(spy, vix)
    assert list(ctx.columns) == ["spy_close", "spy_sma50", "vix"] and ctx.index.tz is None
    assert ctx["spy_sma50"].isna().sum() == 49                                # defined from the 50th session
    intraday = bws.market_at(ctx, pd.Timestamp("2026-09-17 10:30"), intraday=True)
    assert (intraday["market_date"], intraday["spy_close"], intraday["market_regime_spy"]) == \
        ("2026-09-16", 578.0, "Above_SMA50")
    assert intraday["vix"] == round(float(vix["Close"].iloc[-2]), 2)
    daily = bws.market_at(ctx, pd.Timestamp("2026-09-17"), intraday=False)
    assert (daily["market_date"], daily["spy_close"]) == ("2026-09-17", 579.0)
    early = bws.market_at(ctx, ctx.index[10], intraday=False)                 # before the SMA exists
    assert early["spy_close"] is not None and early["spy_sma50"] is None and early["market_regime_spy"] is None
    assert bws.market_at(ctx, pd.Timestamp("2020-01-01"), intraday=False)["vix"] is None
    assert bws.market_at(pd.DataFrame(), pd.Timestamp("2026-09-17"), intraday=False)["vix"] is None
    assert bws.daily_context(None, None).empty


# --------------------------------------------------------------------------- #
# Statistics, the report and the JSON
# --------------------------------------------------------------------------- #
def test_bucket_tables():
    rows = [{"exit_reason": "TP1", "realized_R": 2.0, "volume_ratio": 0.5, "rsi_divergence": True, "year": 2025},
            {"exit_reason": "SL", "realized_R": -1.0, "volume_ratio": 1.0, "rsi_divergence": False, "year": 2025},
            {"exit_reason": "TIME_EXIT", "realized_R": 0.2, "volume_ratio": None, "rsi_divergence": None, "year": 2026},
            {"exit_reason": "OPEN", "realized_R": 0.5, "volume_ratio": 3.0, "rsi_divergence": True, "year": 2026}]
    s = bws.summarise(rows)
    assert (s["trades"], s["TP1"], s["SL"], s["TIME_EXIT"], s["OPEN"], s["closed"]) == (4, 1, 1, 1, 1, 3)
    assert (s["win_rate"], s["hit_rate"], s["mean_r"], s["median_r"], s["total_r"]) == (0.3333, 0.5, 0.4, 0.2, 1.2)
    assert bws.summarise([])["win_rate"] is None
    _, edges, names = bws.NUMERIC_FACTORS["volume_ratio"]
    t = bws.numeric_buckets(rows, "volume_ratio", edges, names)
    assert [(b["bucket"], b["trades"]) for b in t] == \
        [("<= 0.8x", 1), ("0.8-1.0x", 1), ("1.0-1.3x", 0), ("1.3-2.0x", 0), ("> 2.0x", 1), ("n/a", 1)]
    c = bws.categorical_buckets(rows, "rsi_divergence", ("yes", "no"))
    assert [(b["bucket"], b["trades"]) for b in c] == [("yes", 2), ("no", 1), ("n/a", 1)]
    assert [(b["bucket"], b["trades"]) for b in bws.by_year(rows)] == [("2025", 2), ("2026", 2)]
    assert (bws.rr_bucket(0.5), bws.rr_bucket(1.2), bws.rr_bucket(1.7), bws.rr_bucket(9)) == \
        ("< 1.0 R", "1.0-1.5 R", "1.5-2.0 R", "> 2.0 R")


def test_report_tables_and_json(wolfe_1h, params):
    rows, funnel = bws.replay_symbol("WW", wolfe_1h, params)
    meta = {"first_bar": str(wolfe_1h.index[0]), "last_bar": str(wolfe_1h.index[-1]), "symbols_requested": 1,
            "bars_median": len(wolfe_1h), "start_effective": "2024-09-19", "start_requested": "2023-09-18",
            "clamped": True}
    md = bws.render(rows, funnel, params, meta)
    assert "**TP1 was hit 1 times in 1 closed trades: win rate 100.0 %.**" in md
    assert "| all | 1 | 1 | 0 | 0 | 0 | 100.0 % | 100.0 % |" in md
    assert "Yahoo serves intraday bars for the last 730 days only" in md
    assert "| 1 | 1 | 1 | 1 | 0 | 1 |" in md                                    # the funnel
    assert "| > 2.0 R | 1 | 1 |" in md and "| Bearish | 1 | 1 |" in md and "| yes | 1 | 1 |" in md
    assert "| n/a | 1 | 1 |" in md                                             # the market regime without context
    tb = bws.tables(rows)
    assert tb["factors"]["projected_RR"]["rows"][3]["bucket"] == "> 2.0 R"
    assert tb["years"] == [{"bucket": str(wolfe_1h.index[TRIGGER].year), **bws.summarise(rows)}]
    (r,) = rows
    for key in ("symbol", "trigger_time", "bars_P1_to_P5", "p1_price", "p2_price", "p3_price", "p4_price", "p5_low",
                "entry_price", "stop_loss", "tp1_target", "projected_RR", "body_ratio", "volume_ratio",
                "rsi_divergence", "htf_trend_4h", "market_regime_spy", "exit_reason", "bars_held", "realized_R"):
        assert key in r, key                                                   # the specification's field names
    assert "NaN" not in json.dumps(rows)                                       # JSON-safe: plain types, no NaN
    assert bws.render([], dict.fromkeys(bws.FUNNEL_KEYS, 0), params, {}).count("**No closed trade.**") == 1


# --------------------------------------------------------------------------- #
# Data and the CLI, offline
# --------------------------------------------------------------------------- #
def test_history_start_clamps_intraday_to_yahoos_limit():
    today = pd.Timestamp("2026-09-18")
    requested, effective = bws.history_start(3, "1h", today)
    assert requested == pd.Timestamp("2023-09-18") and effective == today - pd.Timedelta(days=729)
    assert bws.history_start(3, "1d", today) == (requested, requested)
    assert bws.history_start(1, "1h", today)[1] == pd.Timestamp("2025-09-18")     # within the limit: untouched
    assert bws.is_intraday("1h") and bws.is_intraday("30m") and not bws.is_intraday("1d")
    assert bws.Params.for_interval("30m").window_bars == 163 and bws.Params.for_interval("1wk").max_hold_bars == 12
    assert bws.Params.for_interval("1h", stop_atr=0.25, max_hold_bars=None).stop_atr == 0.25


def test_clean_frame_normalises_yahoo_frames():
    idx = pd.date_range("2026-09-01 09:30", periods=70, freq="h", tz="America/New_York")
    raw = pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10.0, "Dividends": 0.0},
                       index=idx)
    raw.loc[raw.index[3], "Close"] = np.nan
    raw = pd.concat([raw, raw.iloc[[10]]])                                    # a duplicated stamp
    out = bws.clean_frame(raw, "1h")
    assert out.index.tz is None and len(out) == 69 and list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert out.index.is_monotonic_increasing and out.index.is_unique
    assert out.index[0] == pd.Timestamp("2026-09-01 09:30")
    days = pd.bdate_range("2026-01-01", periods=70).tz_localize("America/New_York")
    daily = bws.clean_frame(pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5}, index=days), "1d")
    assert daily.index[0] == pd.Timestamp("2026-01-01") and len(daily) == 70 and "Volume" not in daily.columns
    assert bws.clean_frame(raw.iloc[:30], "1h") is None and bws.clean_frame(None, "1h") is None
    assert bws.clean_frame(pd.DataFrame({"Close": [1.0] * 70}), "1d") is None    # no OHLC


def test_main_runs_offline_through_the_yfinance_stand_in(wolfe_1h, fake_yfinance, monkeypatch, tmp_path):
    days = pd.bdate_range(end="2026-09-17", periods=90)
    spy = pd.DataFrame({"Open": 500.0, "High": 501.0, "Low": 499.0, "Close": np.linspace(500.0, 589.0, 90),
                        "Volume": 1e6}, index=days)
    vix = pd.DataFrame({"Open": 15.0, "High": 16.0, "Low": 14.0, "Close": 18.0, "Volume": 0.0}, index=days)
    rec = fake_yfinance({"WW": wolfe_1h, "SPY": spy, "^VIX": vix})
    monkeypatch.setattr(bws.time, "sleep", lambda s: None)
    out_json, out_md = tmp_path / "w.json", tmp_path / "w.md"
    assert bws.main(["--interval", "1h", "--years", "3", "--tickers", "WW", "--json", str(out_json),
                     "--md", str(out_md)]) == 0
    calls = {sym: kwargs for sym, kwargs in rec.calls}
    assert set(calls) == {"WW", "SPY", "^VIX"}
    assert calls["WW"]["interval"] == "1h" and calls["SPY"]["interval"] == calls["^VIX"]["interval"] == "1d"
    assert calls["WW"]["auto_adjust"] is True and calls["WW"]["prepost"] is False
    data = json.loads(out_json.read_text())
    assert data["summary"]["TP1"] == 1 and data["funnel"]["trades"] == 1 and data["meta"]["clamped"] is True
    assert data["params"]["interval"] == "1h" and data["tables"]["years"][0]["trades"] == 1
    (r,) = data["rows"]
    assert r["market_regime_spy"] == "Above_SMA50" and r["vix"] == 18.0 and r["market_date"] < r["trigger_date"]
    assert "TP1 was hit 1 times" in out_md.read_text()
    # a delisted-only universe: no data, exit code 2
    fake_yfinance({})
    assert bws.main(["--tickers", "NONE", "--no-market"]) == 2
