#!/usr/bin/env python3
"""Walk-forward replay: run the scanner as it would have run on each past session.

Why: waiting for the nightly reports to accumulate takes months.  The data is
already there -- for every session D in the look-back window, truncate each
symbol's history at D, run ``scan.scan_symbol`` on exactly what the nightly
job would have seen, and score every CONFIRMED signal against the bars that
followed.  This is the calibration data for ``MIN_SCORE`` and the per-pattern
thresholds.

Usage (prices need network -- run via the ``backtest`` workflow on a GitHub
runner, or locally where Yahoo is reachable):

    python tools/backtest.py [--days 63] [--horizon 40] [--tickers A,B] [--json out.json]
                             [--period 5y --days 500 --bars 500 --split 2025-09-09]

Method:

* Signals are taken on the session they **first** appear (keyed on ticker,
  pattern and stop, like ``evaluate_signals``), which is the day the report
  would have alerted.
* The fill is the **next session's open** (the e-mail arrives before the US
  open).  An open above the row's ``max_buy`` (trigger + ``MAX_RUNAWAY``, or
  where the risk at the fill reaches ``MAX_BUY_RISK_MULT`` x the planned risk)
  is a ``gap``; an open at or below the stop is ``below_stop`` (nobody buys an
  open that is already through the stop, and R would be undefined).  Neither
  is traded; both are counted separately.
* Outcomes use ``evaluate_signals.classify``: ``target`` / ``stop`` / ``open``
  within ``horizon`` bars after the fill bar, gaps filled at the open, R
  multiple = (exit - fill) / (fill - stop).
* No look-ahead: each scan only sees bars <= D; asserted per signal.
  ``--bars N`` further limits what each scan sees to its last N bars, so a
  long download replays what the nightly job sees (its 2y download is about
  500 bars).
* Per signal it also records the maximum favourable / adverse excursion over
  the horizon and the chart-book style ``success5``: did the high reach +5 %
  above the fill before any *close* below the stop (no target, no intraday
  stop), which is what published "pattern success rates" measure.
* Per signal it records **features at the scan day**, computed from the
  history the scan saw (``row_features``): close vs SMA200, SMA50 vs SMA200,
  the SMA200's change over 40 bars, the distance from the SMA200 in ATR, the
  stop and target distances in ATR, the bars from the pattern's last anchor
  (handle low, right shoulder, point 5) to the breakout, the pattern's depth
  in ATR, and on the breakout bar its close's position within the bar's range,
  whether that close cleared the prior bar's high, and its volume z-score
  against the prior 20 bars; for cups also the handle's volume against the
  cup's and the handle's volume slope.  Nothing is added to ``scan.Signal`` or
  the nightly report; the features exist to be tested against outcomes.
* Per signal it records the **per-ticker fear-and-greed reading**
  (``scan.fear_greed``, the same composite the report's F&G column shows):
  the equal-weight 0-100 composite of RSI 14, the MACD histogram's percentile
  within the trailing year and Bollinger %B that the TradingView community
  indicators of that name share, read at the scan day and at the pattern's
  last low, with the components alongside.  Nothing gates on it.
* Per signal it also records the **market context at the scan day** from
  ``scan.market_series``: the SPY regime (close and SMA50 against the SMA200),
  the VIX and the breadth of the universe.  The summaries add a per-regime
  slice; VIX and breadth join the feature buckets.  No rule reads any of it.
* Every **later listing** of an already-seen signal (the same structure still
  CONFIRMED on a following scan day, which the nightly report shows again) is
  recorded too, with ``listed_day`` = sessions since the first report (1 = the
  first report) and filled at the next open under the same rules, so the
  late-entry table can say what a reader gets who buys a row on its Nth day
  on the list against the same signals bought on day 1.
* Every summary carries, next to hit rate and mean R: median R, standard
  deviation, total R, the deepest drawdown of the cumulative R curve (1 R per
  trade, in scan order), a 95 % bootstrap interval of the mean R and the
  drawdown exceeded in only 5 % of resamples.  The bootstrap resamples scan
  *months*, not trades: signals cluster in time (33 in one month, 2 in
  another, over 2024-26), so resampling trades as if independent would
  understate the uncertainty.
* Two more tables per window: **excursions by horizon** (median MFE and MAE
  in percent and in ATR at 5 / 10 / 20 / 40 / 60 bars, with the share of
  signals that had reached the target, hit the stop or neither by then) and
  **outcome by feature** (hit rate, mean R and interval per bucket of each
  feature above plus volume ratio, risk %, reward:risk and breakout age).  A
  feature is worth a rule only if its buckets separate outcomes by more than
  their intervals, on both windows of a split.
* ``--split YYYY-MM-DD`` reports the sessions before and from that date as
  separate windows next to the pooled one, so a rule chosen on one window is
  judged on the other -- the out-of-sample check a calibration decision
  should pass (docs/wiki/03).
* ``--end YYYY-MM-DD`` replays the last ``--days`` sessions on or before that
  date instead of today, so one past year can be replayed on its own (the
  outcomes still use the bars that followed it).
* ``--constituents-asof`` replays the index as it was: the membership as of
  each scan day comes from the git history of the constituent dataset
  (``universe_history``), the union over the window is downloaded, and a
  symbol is scanned only on the days it was a member.  A coverage table
  states how many members each year had no Yahoo history (delisted or
  renamed symbols), which is the survivorship bias that remains.  Needs a
  ``--period`` long enough to reach the window (``10y`` for 2016 onwards).
* ``--grid`` re-scores the same signals under stop / target variants: extra
  ATR below the reported stop (0 / 0.25 / 0.75 / 1.0, i.e. ~0.25 / 0.5 / 1.0
  / 1.25 ATR under the structural low), intraday vs close-based stops, and three target
  sizes: the reported measured move, half of it, and (cups only) the
  Investopedia measure -- cup bottom to the handle breakout level instead of
  bottom to the left rim.
* ``--grid`` also runs a second full walk-forward under the *other* rule
  profile (``spec`` vs ``legacy``, see ``scan.RULE_PROFILES``) so the two rule
  sets can be compared on the same data, per pattern.
* ``--ablate`` replays the spec profile once per rule with that single rule
  set to its legacy value (leave-one-rule-out), so the cost of each spec rule
  in signals and outcomes can be attributed.  One full replay per rule, so
  use a short window (63 sessions is about 1.5 minutes per rule on a runner).

Caveats: the universe is today's constituents (survivorship bias: symbols
that left the index are missing), and the last ``horizon`` sessions of the
window are still ``open``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import re
import sys
import time
from typing import Any, Callable, Container, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan  # noqa: E402
import evaluate_signals as ev  # noqa: E402
import universe_history as uh  # noqa: E402

log = logging.getLogger("backtest")

SCORE_BUCKETS = ((60, 69), (70, 79), (80, 89), (90, 100))
TARGET_MODES = ("full", "half", "breakout")
GRID = [(extra, basis, mode) for extra in (0.0, 0.25, 0.75, 1.0) for basis in ("intraday", "close")
        for mode in TARGET_MODES]
TRADED = ("target", "stop", "open")          # outcomes with a position; "gap" / "below_stop" / "no_data" have none
N_BOOT = 2000                                # month-block bootstrap resamples per summary
HORIZONS = (5, 10, 20, 40, 60)               # bars after the fill for the excursion table
SLOPE_LOOKBACK = 40                          # bars between the two SMA200 readings of the slope feature
INF = float("inf")
# Feature buckets for the outcome-by-feature table: key -> (label, right-inclusive edges, bucket names).
# Fixed edges, so two replays (or the two windows of a split) are comparable bucket by bucket.
FEATURE_BUCKETS: Dict[str, Tuple[str, Sequence[float], Sequence[str]]] = {
    "volume_ratio": ("breakout volume / 20-bar average", (-INF, 0.8, 1.0, 1.3, 2.0, INF),
                     ("<= 0.8x", "0.8-1.0x", "1.0-1.3x", "1.3-2.0x", "> 2.0x")),
    "close_vs_sma200": ("close vs SMA200", (-INF, -0.05, 0.0, 0.10, 0.25, INF),
                        ("> 5% below", "0-5% below", "0-10% above", "10-25% above", "> 25% above")),
    "sma50_vs_sma200": ("SMA50 vs SMA200", (-INF, -0.05, 0.0, 0.05, INF),
                        ("> 5% below", "0-5% below", "0-5% above", "> 5% above")),
    "sma200_slope": (f"SMA200 change over {SLOPE_LOOKBACK} bars", (-INF, -0.02, 0.0, 0.02, 0.05, INF),
                     ("falling > 2%", "falling 0-2%", "rising 0-2%", "rising 2-5%", "rising > 5%")),
    "dist_sma200_atr": ("close minus SMA200, in ATR", (-INF, -2.0, 0.0, 3.0, 6.0, INF),
                        ("< -2 ATR", "-2..0 ATR", "0..3 ATR", "3..6 ATR", "> 6 ATR")),
    "stop_atr": ("entry minus stop, in ATR", (-INF, 1.5, 3.0, 5.0, INF),
                 ("<= 1.5 ATR", "1.5-3 ATR", "3-5 ATR", "> 5 ATR")),
    "risk_pct": ("risk %", (-INF, 4.0, 8.0, 12.0, INF), ("<= 4%", "4-8%", "8-12%", "> 12%")),
    "reward_risk": ("reward:risk at entry", (-INF, 1.5, 2.5, 4.0, INF), ("<= 1.5", "1.5-2.5", "2.5-4", "> 4")),
    "wait_bars": ("bars from the last anchor to the breakout", (-INF, 10, 20, 40, 60, INF),
                  ("<= 10", "11-20", "21-40", "41-60", "> 60")),
    "bars_since_break": ("breakout age when first reported", (-INF, 0, 1, 3, 8, INF),
                         ("0", "1", "2-3", "4-8", "> 8")),
    "vix": ("VIX at the scan day", (-INF, 15.0, 20.0, 25.0, INF), ("<= 15", "15-20", "20-25", "> 25")),
    "breadth": ("share of the universe above its SMA200", (-INF, 0.4, 0.55, 0.7, INF),
                ("<= 40%", "40-55%", "55-70%", "> 70%")),
    "depth_atr": ("pattern depth in ATR", (-INF, 3.0, 6.0, 10.0, INF), ("<= 3 ATR", "3-6 ATR", "6-10 ATR", "> 10 ATR")),
    "break_close_pos": ("breakout bar close within its range", (-INF, 0.5, 0.8, INF), ("<= 50%", "50-80%", "> 80%")),
    "break_over_prior_high": ("breakout close above the prior bar's high", (-INF, 0.5, INF), ("no", "yes")),
    "volume_z": ("breakout volume z-score, 20 bars", (-INF, 0.0, 1.5, 3.0, INF), ("<= 0", "0-1.5", "1.5-3", "> 3")),
    "handle_volume_ratio": ("handle volume / cup volume (cups)", (-INF, 0.7, 1.0, INF), ("<= 0.7", "0.7-1.0", "> 1.0")),
    "handle_volume_slope": ("handle volume slope (cups)", (-INF, 0.0, INF), ("falling", "rising or flat")),
    "fg_score": ("fear and greed at the scan day", (-INF, 20.0, 40.0, 60.0, 80.0, INF),
                 ("extreme fear", "fear", "neutral", "greed", "extreme greed")),
    "fg_base": ("fear and greed at the pattern's last low", (-INF, 20.0, 40.0, 60.0, 80.0, INF),
                ("extreme fear", "fear", "neutral", "greed", "extreme greed")),
    "fg_rsi": ("RSI 14 at the scan day", (-INF, 30.0, 50.0, 70.0, INF), ("<= 30", "30-50", "50-70", "> 70")),
    "fg_bb_pctb": ("Bollinger %B at the scan day", (-INF, 0.0, 0.5, 1.0, INF),
                   ("below the lower band", "lower half", "upper half", "above the upper band")),
    "fg_macd_pct": ("MACD histogram percentile, 250 bars", (-INF, 20.0, 50.0, 80.0, INF),
                    ("<= 20", "20-50", "50-80", "> 80")),
}
FEATURE_KEYS = ("close_vs_sma200", "sma50_vs_sma200", "sma200_slope", "dist_sma200_atr", "stop_atr",
                "target_atr", "wait_bars", "depth_atr", "break_close_pos", "break_over_prior_high", "volume_z",
                "handle_volume_ratio", "handle_volume_slope", "fg_score", "fg_rsi", "fg_macd_pct", "fg_bb_pctb",
                "fg_base")  # what row_features adds to a row
MARKET_KEYS = ("regime", "vix", "breadth", "index_vs_sma200_pct")  # what the market context adds to a row
REGIMES = ("bull", "neutral", "bear")


def variant_target(row: dict, mode: str) -> Optional[float]:
    """Target under a grid mode: reported (``full``), halfway (``half``), or the
    Investopedia cup measure (``breakout``: bottom-to-handle-high added at the fill;
    non-cup patterns keep their reported target)."""
    t, fill = row["target"], row["fill"]
    if t is None:
        return None
    if mode == "half":
        return fill + 0.5 * (t - fill)
    if mode == "breakout" and row["pattern"] == "Cup & Handle":
        bottom, trigger = row.get("cup_bottom"), row.get("cup_trigger")
        return fill + (trigger - bottom) if bottom is not None and trigger is not None else t
    return t


@contextlib.contextmanager
def rule_profile(name: str):
    """Run the body under ``scan.RULE_PROFILES[name]``; the previous profile is restored on exit."""
    previous = scan.apply_profile(name)
    try:
        yield
    finally:
        scan.apply_profile(previous)


def excursions(fill: float, stop: float, bars: pd.DataFrame, horizon: int) -> dict:
    """MFE / MAE over the horizon and the chart-book ``success5`` flag.

    :returns: ``{"mfe", "mae", "success5"}``; ``success5`` is True when the high
        reached +5 % above the fill before any close below the stop, False when
        a close below the stop came first, ``None`` when neither happened.
    """
    w = bars.iloc[:horizon]
    out = {"mfe": round(float(w["High"].max() / fill - 1), 4),
           "mae": round(float(w["Low"].min() / fill - 1), 4), "success5": None}
    for hi, cl in zip(w["High"], w["Close"]):
        if hi >= fill * 1.05:
            out["success5"] = True
            break
        if cl < stop:
            out["success5"] = False
            break
    return out


def classify_variant(fill: float, stop: float, target: Optional[float], bars: pd.DataFrame,
                     horizon: int, basis: str = "intraday") -> dict:
    """Like :func:`evaluate_signals.classify`, with a close-based stop option.

    ``basis="close"`` exits at the first close at or below the stop (at that
    close); ``"intraday"`` exits when the low touches it (gap-downs fill at the
    open).  Targets are always intraday.
    """
    risk = fill - stop
    w = bars.iloc[:horizon]
    if w.empty:
        return {"outcome": "no_data", "bars": 0, "exit": None, "r": None}
    for i, (op, hi, lo, cl) in enumerate(zip(w["Open"], w["High"], w["Low"], w["Close"]), start=1):
        hit = lo <= stop if basis == "intraday" else cl <= stop
        if hit:
            exit_ = min(float(op), stop) if basis == "intraday" else float(cl)
            return {"outcome": "stop", "bars": i, "exit": exit_, "r": (exit_ - fill) / risk if risk > 0 else None}
        if target is not None and hi >= target:
            exit_ = max(float(op), target)
            return {"outcome": "target", "bars": i, "exit": exit_, "r": (exit_ - fill) / risk if risk > 0 else None}
    last = float(w["Close"].iloc[-1])
    return {"outcome": "open", "bars": len(w), "exit": last, "r": (last - fill) / risk if risk > 0 else None}


def row_features(hist: pd.DataFrame, s: scan.Signal, atr_last: float) -> Dict[str, Optional[float]]:
    """Features of one signal at its scan day, from the history the scan saw.

    * ``close_vs_sma200``, ``sma50_vs_sma200``: ratios minus one (``None`` with
      fewer than 200 / 50 bars).
    * ``sma200_slope``: the SMA200 against its value ``SLOPE_LOOKBACK`` bars
      earlier, minus one (``None`` with fewer than 240 bars).
    * ``dist_sma200_atr``, ``stop_atr``, ``target_atr``: close minus SMA200,
      entry minus stop and target minus entry, each in units of the last ATR.
    * ``wait_bars``: bars from the pattern's last anchor (handle low, right
      shoulder, point 5, read from ``notes`` like ``scan._drop_reason`` does) to
      the breakout bar.
    * ``depth_atr``: the pattern's height in ATR -- cup bottom to right rim,
      the shallower shoulder to the head, Wolfe point 1 to point 5.
    * ``break_close_pos``: where the breakout bar closed within its own range
      (0 = at the low, 1 = at the high); ``break_over_prior_high``: 1.0 when
      that close cleared the previous bar's high; ``volume_z``: the breakout
      bar's volume as a z-score against the ``scan.VOLUME_AVG_LEN`` bars before
      it (``None`` when those have no spread).
    * ``handle_volume_ratio`` and ``handle_volume_slope`` (cups only): the
      handle bars' mean volume over the cup bars' mean volume, and the slope of
      a line through the handle's volume as a fraction of its mean per bar
      (negative = drying up).
    * ``fg_score``, ``fg_rsi``, ``fg_macd_pct``, ``fg_bb_pctb``: the
      ``scan.fear_greed`` reading and its components at the scan day;
      ``fg_base``: the composite at the pattern's last anchor bar (handle low,
      right shoulder, point 5), how fearful the stock was when the base formed.

    Complexity: O(bars) for the means, the oscillators and the anchor look-ups.
    """
    close = hist["Close"].to_numpy(dtype=float)
    n = len(close)
    c = close[-1]
    s200 = float(close[-200:].mean()) if n >= 200 else None
    s50 = float(close[-50:].mean()) if n >= 50 else None
    s200_prev = (float(close[-200 - SLOPE_LOOKBACK:-SLOPE_LOOKBACK].mean())
                 if n >= 200 + SLOPE_LOOKBACK else None)

    def rel(a: Optional[float], b: Optional[float]) -> Optional[float]:
        return round(a / b - 1, 4) if a is not None and b else None

    def in_atr(x: Optional[float]) -> Optional[float]:
        return round(x / atr_last, 3) if x is not None and atr_last else None

    out: Dict[str, Optional[float]] = {
        "close_vs_sma200": rel(c, s200), "sma50_vs_sma200": rel(s50, s200), "sma200_slope": rel(s200, s200_prev),
        "dist_sma200_atr": in_atr(c - s200) if s200 is not None else None,
        "stop_atr": in_atr(s.entry - s.stop),
        "target_atr": in_atr(s.target - s.entry) if s.target is not None else None,
        "wait_bars": None, "depth_atr": None, "break_close_pos": None, "break_over_prior_high": None,
        "volume_z": None, "handle_volume_ratio": None, "handle_volume_slope": None,
        "fg_score": None, "fg_rsi": None, "fg_macd_pct": None, "fg_bb_pctb": None, "fg_base": None}
    notes = s.notes or ""
    fg = scan.fear_greed(close)
    out.update({"fg_score": fg["score"], "fg_rsi": fg["rsi"], "fg_macd_pct": fg["macd_pct"],
                "fg_bb_pctb": fg["bb_pctb"]})

    def loc(day: str) -> int:
        return int(hist.index.get_indexer([pd.Timestamp(day)])[0])

    m = scan._ANCHOR_RE.search(notes)
    b = n - 1 - int(s.bars_since_break) if s.bars_since_break is not None else None
    if m and b is not None:
        anchor = loc(m[2])
        if anchor >= 0:
            out["wait_bars"] = b - anchor
            out["fg_base"] = scan.fear_greed(close[:anchor + 1])["score"]
    # Pattern depth from the anchors in the notes.
    depth = None
    if s.pattern == "Cup & Handle":
        m = re.search(r"bottom \S+ @([\d.]+).*right rim \S+ @([\d.]+)", notes)
        depth = float(m[2]) - float(m[1]) if m else None
    elif s.pattern == "Inverse Head & Shoulders":
        m = re.search(r"LS \S+ @([\d.]+), head \S+ @([\d.]+), RS \S+ @([\d.]+)", notes)
        depth = min(float(m[1]), float(m[3])) - float(m[2]) if m else None
    elif s.pattern == "Bullish Wolfe Wave":
        m1, m5 = re.search(r"^1 \S+ @([\d.]+)", notes), re.search(r", 5 \S+ @([\d.]+);", notes)
        depth = float(m1[1]) - float(m5[1]) if m1 and m5 else None
    out["depth_atr"] = in_atr(depth)
    # The breakout bar: close position, prior-high clearance, volume z-score.
    if b is not None and b >= 1:
        high, low = hist["High"].to_numpy(dtype=float), hist["Low"].to_numpy(dtype=float)
        rng = high[b] - low[b]
        out["break_close_pos"] = round((close[b] - low[b]) / rng, 3) if rng > 0 else None
        out["break_over_prior_high"] = 1.0 if close[b] > high[b - 1] else 0.0
        if "Volume" in hist.columns:
            vol = hist["Volume"].to_numpy(dtype=float)
            base = vol[max(0, b - scan.VOLUME_AVG_LEN):b]
            base = base[~np.isnan(base)]
            if len(base) > 1 and not np.isnan(vol[b]):
                sd = float(base.std(ddof=1))
                out["volume_z"] = round((vol[b] - float(base.mean())) / sd, 2) if sd > 0 else None
            # Cups: does the handle's volume dry up against the cup's?
            if s.pattern == "Cup & Handle":
                m = re.search(r"left rim (\S+) @.*right rim (\S+) @", notes)
                a, rb = (loc(m[1]), loc(m[2])) if m else (-1, -1)
                if 0 <= a < rb and b - 1 >= rb + 1:
                    cup_v, handle_v = vol[a:rb + 1], vol[rb + 1:b]
                    cup_mean, handle_mean = float(np.nanmean(cup_v)), float(np.nanmean(handle_v))
                    if cup_mean > 0 and not np.isnan(handle_mean):
                        out["handle_volume_ratio"] = round(handle_mean / cup_mean, 3)
                    if len(handle_v) >= 3 and handle_mean > 0 and not np.isnan(handle_v).any():
                        slope = float(np.polyfit(np.arange(len(handle_v)), handle_v, 1)[0])
                        out["handle_volume_slope"] = round(slope / handle_mean, 4)
    return out


def _market_at(market: Optional[Mapping[str, pd.Series]], day: Any) -> Dict[str, Any]:
    """The ``MARKET_KEYS`` of a row at ``day`` from ``scan.market_series`` output; all ``None`` without it."""
    if not market:
        return {k: None for k in MARKET_KEYS}
    ctx = scan.market_context(market, day)
    return {k: ctx.get(k) for k in MARKET_KEYS}


# --------------------------------------------------------------------------- #
# Statistics: drawdown, month-block bootstrap, windows
# --------------------------------------------------------------------------- #
def max_drawdown(rs: Sequence[float]) -> Optional[float]:
    """Deepest fall of the cumulative R curve from its running peak, 1 R risked per trade, in the given order.

    The curve starts at 0, so a losing first trade already counts as a drawdown.

    :returns: A number <= 0 rounded to 3 dp, or ``None`` without trades.
    """
    if len(rs) == 0:
        return None
    cum = np.cumsum(np.asarray(rs, dtype=float))
    peak = np.maximum(np.maximum.accumulate(cum), 0.0)
    return round(float((cum - peak).min()), 3)


def block_bootstrap(traded: Sequence[dict], n_boot: int = N_BOOT, seed: int = 0) -> Dict[str, Any]:
    """Bootstrap the mean R and the drawdown by resampling scan *months* with replacement.

    Why months: signals arrive in clusters (a correction ends and twenty bases
    break out in the same fortnight), so their outcomes are not independent
    draws and a per-trade bootstrap is too narrow.  Each resample picks as many
    months as the window has, concatenates their trades in the picked order,
    and records the mean R and the max drawdown of that sequence.

    :param traded: Rows with ``scan_day`` and ``r`` (rows without ``r`` are
        ignored), in scan order.
    :param n_boot: Resamples; ``seed`` makes the result reproducible.
    :returns: ``ci_low`` / ``ci_high`` (95 % percentile interval of the mean R),
        ``dd_p95`` (the drawdown exceeded in only 5 % of resamples, <= 0) and
        ``blocks`` (months with trades); the first three are ``None`` with fewer
        than 2 months or 5 trades, where an interval would mean nothing.

    Complexity: O(n_boot * trades).
    """
    months: Dict[str, List[float]] = {}
    for r in traded:
        if r.get("r") is not None:
            months.setdefault(str(r["scan_day"])[:7], []).append(float(r["r"]))
    blocks = [np.asarray(months[m]) for m in sorted(months)]
    if len(blocks) < 2 or sum(len(b) for b in blocks) < 5:
        return {"ci_low": None, "ci_high": None, "dd_p95": None, "blocks": len(blocks)}
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    dds = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, len(blocks), len(blocks))
        seq = np.concatenate([blocks[j] for j in pick])
        means[i] = seq.mean()
        dds[i] = max_drawdown(seq)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"ci_low": round(float(lo), 3), "ci_high": round(float(hi), 3),
            "dd_p95": round(float(np.percentile(dds, 5)), 3), "blocks": len(blocks)}


def split_windows(rows: Sequence[dict], split: Optional[str]) -> List[Tuple[str, List[dict]]]:
    """``[(label, rows)]``: the pooled rows and, with ``split``, the rows before and from that ISO date.

    ``scan_day`` is an ISO string, so the comparison is lexical.
    """
    out = [("all sessions", list(rows))]
    if split:
        out.append((f"before {split}", [r for r in rows if r["scan_day"] < split]))
        out.append((f"from {split}", [r for r in rows if r["scan_day"] >= split]))
    return out


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #
def grid(rows: Sequence[dict], data: Dict[str, pd.DataFrame], horizon: int) -> List[dict]:
    """Re-score the traded signals under every stop / target variant in ``GRID``."""
    out = []
    traded = [r for r in rows if r["outcome"] in TRADED]
    for extra, basis, mode in GRID:
        scored = []
        for r in traded:
            bars = data[r["ticker"]]
            after = bars[bars.index > pd.Timestamp(r["scan_day"])]
            stop = r["stop"] - extra * r["atr"]
            scored.append(classify_variant(r["fill"], stop, variant_target(r, mode), after, horizon, basis))
        s = ev.summarise(scored)
        out.append({"stop_extra_atr": extra, "stop_basis": basis, "target_mode": mode, **s})
    return out


def ablation(data: Dict[str, pd.DataFrame], days: int, horizon: int, **replay: Any) -> List[dict]:
    """Leave-one-rule-out over the spec profile.

    Replays the active (spec) profile, then once per key in
    ``RULE_PROFILES["legacy"]`` with only that key set to its legacy value.
    ``replay`` holds the :func:`walk_forward` keyword options (bars, market,
    members, end).
    :returns: one summary row per replay: ``{"rule", "value", "delta", **breakdown(...)["overall"]}``.
    """
    base = breakdown(walk_forward(data, days, horizon, **replay))["overall"]
    rows = [{"rule": "spec (all rules)", "value": "-", "delta": 0, **base}]
    for key, legacy_value in scan.RULE_PROFILES["legacy"].items():
        saved = getattr(scan, key)
        setattr(scan, key, legacy_value)
        try:
            s = breakdown(walk_forward(data, days, horizon, **replay))["overall"]
        finally:
            setattr(scan, key, saved)
        rows.append({"rule": key, "value": str(legacy_value), "delta": s["signals"] - base["signals"], **s})
    return rows


def render_ablation(rows: Sequence[dict], days: int, horizon: int) -> str:
    """Markdown table: what each spec rule costs when relaxed to its legacy value on its own."""
    lines = [f"# Rule ablation: spec profile, each rule relaxed alone (last {days} sessions, horizon {horizon})", "",
             "Each row replays the spec profile with one rule set to its legacy value. "
             "delta = confirmed signals gained (+) or lost (-) versus the full spec profile.", "",
             "| Rule relaxed to legacy | Legacy value | Signals | delta | Target | Stop | Open | Hit rate | "
             "Mean R | +5% first |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: -abs(r["delta"])):
        lines.append(f"| {r['rule']} | {r['value']} | {r['signals']} | {r['delta']:+d} | {r['target']} | {r['stop']} | "
                     f"{r['open']} | {_pct(r['hit_rate'])} | {_r(r['mean_r'])} | {_pct(r['success5'])} |")
    return "\n".join(lines)


def apply_override(item: str) -> Tuple[str, Any]:
    """Apply one ``KEY=VALUE`` override to ``scan``; the value is parsed as a Python literal, else kept as text."""
    import ast
    if "=" not in item:
        raise ValueError(f"--set expects KEY=VALUE, got {item!r}")
    key, raw = item.split("=", 1)
    key = key.strip()
    if not hasattr(scan, key) or key.startswith("_"):
        raise ValueError(f"unknown scan constant {key!r}")
    try:
        value: Any = ast.literal_eval(raw.strip())
    except (ValueError, SyntaxError):
        value = raw.strip()
    setattr(scan, key, value)
    return key, value


def profile_pass(data: Dict[str, pd.DataFrame], days: int, horizon: int, name: str, **replay: Any) -> dict:
    """Second full walk-forward under rule profile ``name`` (the active profile is restored).

    ``replay`` holds the :func:`walk_forward` keyword options (bars, market, members, end).
    :returns: ``{"profile", "stats", "rows"}`` with the same ``breakdown`` slices as the main report.
    """
    with rule_profile(name):
        rows = walk_forward(data, days, horizon, **replay)
    return {"profile": name, "stats": breakdown(rows), "rows": rows}


def scan_sessions(data: Dict[str, pd.DataFrame], days: int, end: Optional[str] = None) -> List[pd.Timestamp]:
    """The sessions a replay scans: the last ``days`` trading days across ``data`` on or before ``end``."""
    sessions = sorted({d for df in data.values() for d in df.index})
    if end is not None:
        cutoff = pd.Timestamp(end)
        sessions = [s for s in sessions if s <= cutoff]
    return sessions[-days:] if days < len(sessions) else sessions


def _fill_outcome(s: scan.Signal, after: pd.DataFrame, horizon: int) -> dict:
    """Fill a signal at the next open and score it: ``fill``, ``outcome``, ``bars``, ``exit``, ``r``, excursions.

    An open above the row's Max buy is a ``gap``, one at or below the stop is
    ``below_stop``; neither is traded.  Shared by the first report of a signal
    and its later listings so both are judged by the same rules.
    """
    not_traded = dict(exit=None, r=None, mfe=None, mae=None, success5=None)
    if after.empty:
        return dict(fill=None, outcome="no_data", bars=0, **not_traded)
    fill = float(after["Open"].iloc[0])
    max_buy = s.max_buy if s.max_buy is not None else s.entry * (1 + scan.MAX_RUNAWAY)
    if fill > max_buy:
        return dict(fill=round(fill, 2), outcome="gap", bars=0, **not_traded)
    if fill <= s.stop:
        # The open is already through the stop: no trade, and R would be undefined.
        return dict(fill=round(fill, 2), outcome="below_stop", bars=0, **not_traded)
    res = ev.classify(fill, s.stop, s.target, after, horizon)
    return dict(fill=round(fill, 2), **res, **excursions(fill, s.stop, after, horizon))


def walk_forward(data: Dict[str, pd.DataFrame], days: int, horizon: int,
                 detectors: Optional[Sequence] = None, bars: Optional[int] = None,
                 market: Optional[Mapping[str, pd.Series]] = None,
                 members: Optional[Callable[[Any], Container[str]]] = None,
                 end: Optional[str] = None, repeats: Optional[List[dict]] = None) -> List[dict]:
    """Replay the scanner over the last ``days`` sessions and score each first-seen signal.

    :param data: ``{symbol: OHLCV frame}`` as returned by ``download_history``.
    :param days: Number of most recent sessions to scan (each as if it were "today").
    :param horizon: Bars after the fill before an unresolved signal counts as ``open``.
    :param detectors: Subset of detectors to run (default: all).
    :param bars: Bars of history each scan sees (default: everything up to the
        day).  500 mimics the nightly job's 2y download in a longer replay.
    :param market: ``scan.market_series`` output; puts the ``MARKET_KEYS`` (regime,
        VIX, breadth, index vs SMA200) at the scan day on every row, ``None`` without it.
    :param members: ``scan day -> symbols that were index members``; a symbol
        is scanned only on days it is in that set (``universe_history.Membership.members``).
    :param end: Last scan day (ISO); the window is the ``days`` sessions on or
        before it, so a past year can be replayed on its own.
    :param repeats: When given, every later CONFIRMED listing of an already-seen
        signal is appended to it: the day's signal fields plus ``first_day``,
        ``listed_day`` (sessions since the first report, 1 = that report) and the
        fill / outcome of buying it at the next open (:func:`_fill_outcome`).
        First-seen rows carry ``first_day`` = ``scan_day`` and ``listed_day`` 1.
    :returns: One dict per first-seen CONFIRMED signal with the signal fields plus
        ``fill``, ``outcome``, ``bars``, ``exit``, ``r``, the :func:`row_features`,
        the market context (and for cups the parsed ``cup_bottom`` / ``cup_trigger``
        for the breakout-level target variant).  ``outcome`` is ``target`` / ``stop`` /
        ``open`` for traded rows, ``gap`` (open above Max buy) or ``below_stop``
        (open at or below the stop) for rows not traded, ``no_data`` without a
        bar after the scan day.

    Complexity: O(days * symbols * detector cost); ~2 ms per symbol-day.
    """
    scan_days = scan_sessions(data, days, end)
    seen: Dict[tuple, dict] = {}
    first_no: Dict[tuple, int] = {}               # key -> position of its first report among the scan days
    for no, d in enumerate(scan_days):
        ctx = _market_at(market, d)
        today = members(d) if members is not None else None
        for sym, df in data.items():
            if today is not None and sym not in today:
                continue                      # not an index member on d (point-in-time universe)
            hist = df[df.index <= d]
            if bars is not None:
                hist = hist.iloc[-bars:]
            if len(hist) < 60 or hist.index[-1] != d:
                continue                      # symbol had no bar on d (halted, listed later)
            for s in scan.scan_symbol(sym, hist, detectors):
                if s.status != "CONFIRMED":
                    continue
                assert s.last_date == str(d.date()), "look-ahead: signal dated after the scan day"
                key = (sym, s.pattern, round(s.stop, 2))
                after = df[df.index > d]
                if key in seen:
                    if repeats is not None:       # the report shows the row again: a late entry
                        repeats.append({**scan.asdict(s), "scan_day": str(d.date()),
                                        "first_day": seen[key]["scan_day"], "listed_day": no - first_no[key] + 1,
                                        **_fill_outcome(s, after, horizon)})
                    continue
                first_no[key] = no
                atr_last = round(float(scan.atr(hist).iloc[-1]), 4)
                row = {**scan.asdict(s), "scan_day": str(d.date()), "first_day": str(d.date()), "listed_day": 1,
                       "atr": atr_last, "cup_bottom": None, "cup_trigger": None,
                       **row_features(hist, s, atr_last), **ctx}
                if s.pattern == "Cup & Handle":
                    m = re.search(r"bottom \S+ @([\d.]+).*trigger ([\d.]+)", s.notes)
                    if m:
                        row["cup_bottom"], row["cup_trigger"] = float(m[1]), float(m[2])
                row.update(_fill_outcome(s, after, horizon))
                seen[key] = row
    return list(seen.values())


def summarise_rows(sub: Sequence[dict]) -> dict:
    """One summary of a set of rows (rows not traded are excluded from the rates).

    The ``evaluate_signals.summarise`` counts plus ``signals``, ``gap``,
    ``below_stop``, ``median_r``, ``std_r``, ``total_r``, ``max_dd`` (cumulative R
    curve in scan order), the month-block bootstrap ``ci_low`` / ``ci_high`` /
    ``dd_p95`` / ``blocks`` (see :func:`block_bootstrap`), ``success5``, ``mfe``
    and ``mae``.
    """
    traded = sorted((r for r in sub if r["outcome"] in TRADED), key=lambda r: (r["scan_day"], r["ticker"]))
    rs = [float(r["r"]) for r in traded if r["r"] is not None]
    decided = [r["success5"] for r in traded if r.get("success5") is not None]
    boot = block_bootstrap(traded)
    return {**ev.summarise(traded), "signals": len(sub),
            "gap": sum(1 for r in sub if r["outcome"] == "gap"),
            "below_stop": sum(1 for r in sub if r["outcome"] == "below_stop"),
            "median_r": round(float(np.median(rs)), 3) if rs else None,
            "std_r": round(float(np.std(rs, ddof=1)), 3) if len(rs) > 1 else None,
            "total_r": round(float(np.sum(rs)), 2) if rs else None,
            "max_dd": max_drawdown(rs),
            "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
            "dd_p95": boot["dd_p95"], "blocks": boot["blocks"],
            "success5": round(sum(decided) / len(decided), 3) if decided else None,
            "mfe": round(sum(r["mfe"] for r in traded) / len(traded), 4) if traded else None,
            "mae": round(sum(r["mae"] for r in traded) / len(traded), 4) if traded else None}


def breakdown(rows: Sequence[dict]) -> dict:
    """:func:`summarise_rows` overall, per pattern, per score bucket and per market regime at the scan day."""
    out = {"overall": summarise_rows(rows), "by_pattern": {}, "by_score": {}, "by_regime": {}}
    for p in sorted({r["pattern"] for r in rows}):
        out["by_pattern"][p] = summarise_rows([r for r in rows if r["pattern"] == p])
    for lo, hi in SCORE_BUCKETS:
        sub = [r for r in rows if lo <= r["score"] <= hi]
        if sub:
            out["by_score"][f"{lo}-{hi}"] = summarise_rows(sub)
    for regime in REGIMES:
        sub = [r for r in rows if r.get("regime") == regime]
        if sub:
            out["by_regime"][regime] = summarise_rows(sub)
    return out


def horizon_table(rows: Sequence[dict], data: Dict[str, pd.DataFrame],
                  horizons: Sequence[int] = HORIZONS) -> List[dict]:
    """Excursions and outcome shares of the traded rows at several horizons, overall and per pattern.

    For each horizon ``h``: the median MFE and MAE over the first ``h`` bars
    after the fill (as a fraction of the fill and in ATR) and the share of
    rows that ``evaluate_signals.classify`` calls ``target``, ``stop`` or
    ``open`` within ``h`` bars.  Medians, because a few runaway winners
    dominate the means.

    :returns: One dict per (slice, horizon): ``slice``, ``horizon``, ``n``,
        ``median_mfe``, ``median_mae``, ``median_mfe_atr``, ``median_mae_atr``,
        ``target``, ``stop``, ``open`` (shares).  Slices without rows are omitted.

    Complexity: O(rows * horizons * horizon).
    """
    traded = [r for r in rows if r["outcome"] in TRADED]
    groups = [("all", traded)] + [(p, [r for r in traded if r["pattern"] == p])
                                  for p in sorted({r["pattern"] for r in traded})]
    out = []
    for name, sub in groups:
        for h in horizons:
            mfe, mae, mfe_atr, mae_atr, outcomes = [], [], [], [], []
            for r in sub:
                bars = data[r["ticker"]]
                after = bars[bars.index > pd.Timestamp(r["scan_day"])]
                w = after.iloc[:h]
                if w.empty:
                    continue
                fill, hi, lo = r["fill"], float(w["High"].max()), float(w["Low"].min())
                mfe.append(hi / fill - 1)
                mae.append(lo / fill - 1)
                if r.get("atr"):
                    mfe_atr.append((hi - fill) / r["atr"])
                    mae_atr.append((lo - fill) / r["atr"])
                outcomes.append(ev.classify(fill, r["stop"], r["target"], after, h)["outcome"])
            n = len(outcomes)
            if n == 0:
                continue
            out.append({"slice": name, "horizon": h, "n": n,
                        "median_mfe": round(float(np.median(mfe)), 4), "median_mae": round(float(np.median(mae)), 4),
                        "median_mfe_atr": round(float(np.median(mfe_atr)), 2) if mfe_atr else None,
                        "median_mae_atr": round(float(np.median(mae_atr)), 2) if mae_atr else None,
                        "target": round(outcomes.count("target") / n, 3),
                        "stop": round(outcomes.count("stop") / n, 3),
                        "open": round(outcomes.count("open") / n, 3)})
    return out


def feature_buckets(rows: Sequence[dict]) -> List[dict]:
    """Outcome of the traded rows per bucket of every feature in ``FEATURE_BUCKETS``.

    Buckets are right-inclusive intervals between the fixed edges; rows
    without a value for a feature (e.g. reward:risk without a target) are left
    out of that feature's buckets and counted in ``missing``.  Empty buckets
    are omitted.

    :returns: One dict per (feature, bucket): ``key``, ``feature``, ``bucket``,
        ``missing`` and the :func:`summarise_rows` fields.
    """
    traded = [r for r in rows if r["outcome"] in TRADED]
    out = []
    for key, (label, edges, names) in FEATURE_BUCKETS.items():
        valued = [r for r in traded if r.get(key) is not None]
        for i, name in enumerate(names):
            sub = [r for r in valued if edges[i] < float(r[key]) <= edges[i + 1]]
            if sub:
                out.append({"key": key, "feature": label, "bucket": name, "missing": len(traded) - len(valued),
                            **summarise_rows(sub)})
    return out


def _mean(xs: Sequence[float]) -> Optional[float]:
    return round(sum(xs) / len(xs), 3) if xs else None


def late_entry_table(rows: Sequence[dict], repeats: Sequence[dict]) -> List[dict]:
    """Outcome of buying a signal on its Nth day on the list, against the same signals bought on day 1.

    Day 1 is the first report (``rows``); a later listing (``repeats``, see
    :func:`walk_forward`) belongs to the table when its first report is in
    ``rows``, so a split window keeps a signal and its repeats together.  Each
    day's row summarises the listings filled that day and pairs every traded
    one with its own first report: ``pairs``, ``pair_day1_mean_r``,
    ``pair_mean_r``, ``diff_mean_r`` (day N minus day 1 over the pairs) and the
    month-block interval of that difference (``diff_ci_low`` / ``diff_ci_high``,
    months of the first report).

    :returns: One dict per day on the list with listings, in day order.
    """
    def key(r: dict) -> tuple:
        return (r["ticker"], r["pattern"], round(float(r["stop"]), 2), r["first_day"])

    first = {key(r): r for r in rows}
    later = [r for r in repeats if key(r) in first]
    out = []
    for day in sorted({1} | {int(r["listed_day"]) for r in later}):
        sub = list(rows) if day == 1 else [r for r in later if int(r["listed_day"]) == day]
        s = summarise_rows(sub)
        entry: Dict[str, Any] = {"listed_day": day, "listed": len(sub), "pairs": None, "pair_day1_mean_r": None,
                                 "pair_mean_r": None, "diff_mean_r": None, "diff_ci_low": None, "diff_ci_high": None,
                                 **{k: s[k] for k in ("n", "gap", "below_stop", "target", "stop", "open", "hit_rate",
                                                       "mean_r", "median_r", "ci_low", "ci_high")}}
        if day > 1:
            pairs = [(first[key(r)], r) for r in sub
                     if r["outcome"] in TRADED and r["r"] is not None
                     and first[key(r)]["outcome"] in TRADED and first[key(r)]["r"] is not None]
            diffs = [{"scan_day": a["scan_day"], "r": float(b["r"]) - float(a["r"])} for a, b in pairs]
            boot = block_bootstrap(diffs)
            entry.update(pairs=len(pairs), pair_day1_mean_r=_mean([float(a["r"]) for a, _ in pairs]),
                         pair_mean_r=_mean([float(b["r"]) for _, b in pairs]),
                         diff_mean_r=_mean([x["r"] for x in diffs]),
                         diff_ci_low=boot["ci_low"], diff_ci_high=boot["ci_high"])
        out.append(entry)
    return out


def report_sections(rows: Sequence[dict], days: int, horizon: int, split: Optional[str] = None,
                    data: Optional[Dict[str, pd.DataFrame]] = None, do_grid: bool = False,
                    other_rows: Optional[Sequence[dict]] = None, other_name: Optional[str] = None,
                    repeats: Optional[Sequence[dict]] = None) -> List[dict]:
    """One section per window (see :func:`split_windows`): its rows, ``breakdown``
    stats, the ``feature_buckets``, the ``horizon_table`` (with ``data``), the stop /
    target ``grid`` (with ``do_grid`` and ``data``), the other profile's stats
    over the same window (with ``other_rows``) and the ``late_entry_table`` (with
    ``repeats``)."""
    windows = split_windows(rows, split)
    others = split_windows(other_rows, split) if other_rows is not None else [(None, None)] * len(windows)
    sections = []
    for (label, rws), (_, o_rws) in zip(windows, others):
        sec: Dict[str, Any] = {"label": label, "rows": rws, "stats": breakdown(rws),
                               "features": feature_buckets(rws), "horizons": None, "grid": None, "other": None,
                               "late": late_entry_table(rws, repeats) if repeats is not None else None}
        if data is not None:
            sec["horizons"] = horizon_table(rws, data)
            if do_grid:
                sec["grid"] = grid(rws, data, horizon)
        if o_rws is not None:
            sec["other"] = {"profile": other_name, "stats": breakdown(o_rws)}
        sections.append(sec)
    return sections


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _pct(x, signed=False):
    return "-" if x is None else (f"{x:+.1%}" if signed else f"{x:.0%}")


def _r(x):
    return "-" if x is None else f"{x:+.2f}"


def _ci(s: dict) -> str:
    return "-" if s.get("ci_low") is None else f"[{s['ci_low']:+.2f}, {s['ci_high']:+.2f}]"


SUMMARY_HEADER = ("| Slice | Signals | Not traded | Target | Stop | Open | Hit rate | Mean R | Median R | Total R | "
                  "95% CI | Max DD | DD p95 | +5% first | MFE | MAE |\n"
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def _line(name: str, s: dict) -> str:
    return (f"| {name} | {s['signals']} | {s['gap'] + s['below_stop']} | {s['target']} | {s['stop']} | {s['open']} | "
            f"{_pct(s['hit_rate'])} | {_r(s['mean_r'])} | {_r(s['median_r'])} | {_r(s['total_r'])} | {_ci(s)} | "
            f"{_r(s['max_dd'])} | {_r(s['dd_p95'])} | {_pct(s['success5'])} | {_pct(s['mfe'], True)} | "
            f"{_pct(s['mae'], True)} |")


def _summary_table(stats: dict, prefix: str = "") -> List[str]:
    lines = [SUMMARY_HEADER, _line(f"{prefix}all", stats["overall"])]
    lines += [_line(f"{prefix}{p}", s) for p, s in stats["by_pattern"].items()]
    lines += [_line(f"{prefix}score {b}", s) for b, s in stats["by_score"].items()]
    lines += [_line(f"{prefix}regime {g}", s) for g, s in stats.get("by_regime", {}).items()]
    return lines


def _horizon_lines(table: Sequence[dict], label: str) -> List[str]:
    lines = ["", f"### Excursions by horizon ({label})", "",
             "Median best and worst excursion from the fill within the first N bars, in percent and in ATR, and "
             "the share of signals that had reached the target, hit the stop or done neither by then.", "",
             "| Slice | Bars | N | Median MFE | Median MAE | MFE / ATR | MAE / ATR | Target | Stop | Neither |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for t in table:
        lines.append(f"| {t['slice']} | {t['horizon']} | {t['n']} | {_pct(t['median_mfe'], True)} | "
                     f"{_pct(t['median_mae'], True)} | {_r(t['median_mfe_atr'])} | {_r(t['median_mae_atr'])} | "
                     f"{_pct(t['target'])} | {_pct(t['stop'])} | {_pct(t['open'])} |")
    return lines


def _feature_lines(buckets: Sequence[dict], label: str) -> List[str]:
    lines = ["", f"### Outcome by feature ({label})", "",
             "Traded signals bucketed by a feature measured at the scan day. A feature earns a rule only if its "
             "buckets separate outcomes by more than their intervals, on both windows of a split.", "",
             "| Feature | Bucket | N | Hit rate | Mean R | Median R | 95% CI |", "|---|---|---|---|---|---|---|"]
    for b in buckets:
        lines.append(f"| {b['feature']} | {b['bucket']} | {b['n']} | {_pct(b['hit_rate'])} | {_r(b['mean_r'])} | "
                     f"{_r(b['median_r'])} | {_ci(b)} |")
    missing = {b["feature"]: b["missing"] for b in buckets if b["missing"]}
    if missing:
        lines += ["", "_Signals without a value: " + ", ".join(f"{k} {v}" for k, v in missing.items()) + "._"]
    return lines


def _late_lines(table: Sequence[dict], label: str) -> List[str]:
    lines = ["", f"### Late entry: buying a signal on its Nth day on the list ({label})", "",
             "Day 1 = the first report (the rows above). A signal stays listed while it is still CONFIRMED on later "
             "scan days, and the report shows it again; each later listing is filled at the next open under the "
             "same rules. Pairs = listings traded on both that day and day 1; the difference is day N minus day 1 "
             "over those pairs, with its month-block interval.", "",
             "| Day on the list | Listed | Traded | Hit rate | Mean R | Median R | 95% CI | Pairs | Day 1 mean R | "
             "Day N mean R | Difference | 95% CI |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in table:
        diff_ci = "-" if t["diff_ci_low"] is None else f"[{t['diff_ci_low']:+.2f}, {t['diff_ci_high']:+.2f}]"
        lines.append(f"| {t['listed_day']} | {t['listed']} | {t['n']} | {_pct(t['hit_rate'])} | {_r(t['mean_r'])} | "
                     f"{_r(t['median_r'])} | {_ci(t)} | {t['pairs'] if t['pairs'] is not None else '-'} | "
                     f"{_r(t['pair_day1_mean_r'])} | {_r(t['pair_mean_r'])} | {_r(t['diff_mean_r'])} | {diff_ci} |")
    return lines


def render(rows: Sequence[dict], sections: Sequence[dict], days: int, horizon: int,
           universe: Optional[Mapping[str, Any]] = None, end: Optional[str] = None) -> str:
    """Markdown report (readable as a GitHub step summary): the universe, one block per window, every signal."""
    lines = [f"# Walk-forward backtest: last {days} sessions{f' to {end}' if end else ''}, horizon {horizon} bars "
             f"(rule profile: {scan.ACTIVE_PROFILE})", "",
             "Hit rate = target / (target + stop). Mean R over traded signals (open ones marked to the last close). "
             "Fill = next session's open; not traded = the open was above the row's Max buy (gap) or at or below "
             "the stop. 95% CI = bootstrap interval of the mean R that resamples scan months, not trades (signals "
             "cluster in time). Max DD = deepest fall of the cumulative R curve, 1 R per trade in scan order; "
             "DD p95 = the drawdown exceeded in 5 % of the month resamples. "
             "+5% first = share of signals whose high reached +5 % above the fill before any close below the stop "
             "(the chart-book success definition). MFE / MAE = mean best / worst excursion from the fill "
             "within the horizon."]
    if universe:
        lines += ["", "## Universe", "",
                  f"Point-in-time membership from the constituent dataset's git history: {universe['symbols']} "
                  f"symbols were members at some point in the window, {universe['with_data']} of them have Yahoo "
                  f"history; a symbol is scanned only on the days it was a member. Members without history "
                  f"(delisted or renamed since) are the survivorship bias that remains.", "",
                  "| Year | Members | With price data | Share |", "|---|---|---|---|"]
        lines += [f"| {c['year']} | {c['members']} | {c['with_data']} | {_pct(c['share'])} |"
                  for c in universe["coverage"]]
    if len(sections) > 1:
        lines += ["", "The windows below report the sessions before and from the split date separately: a rule "
                  "chosen on one window is judged on the other."]
    for sec in sections:
        lines += ["", f"## {sec['label'].capitalize()}", ""] + _summary_table(sec["stats"])
        if sec.get("horizons"):
            lines += _horizon_lines(sec["horizons"], sec["label"])
        if sec.get("features"):
            lines += _feature_lines(sec["features"], sec["label"])
        if sec.get("late"):
            lines += _late_lines(sec["late"], sec["label"])
        if sec["grid"]:
            lines += ["", f"### Stop / target variants (same signals, {sec['label']})", "",
                      "Extra ATR = distance added below the reported stop (which already sits 0.25 ATR under the "
                      "structural low; 1.0 extra is 1.25 ATR under it). Target: full = reported measured move; "
                      "half = halfway to it; breakout = "
                      "cups measured from the bottom to the handle breakout level (Investopedia), others "
                      "unchanged.", "",
                      "| Extra ATR | Stop basis | Target | Target | Stop | Open | Hit rate | Mean R |",
                      "|---|---|---|---|---|---|---|---|"]
            for g in sec["grid"]:
                lines.append(f"| {g['stop_extra_atr']} | {g['stop_basis']} | {g['target_mode']} | "
                             f"{g['target']} | {g['stop']} | {g['open']} | {_pct(g['hit_rate'])} | {_r(g['mean_r'])} |")
        if sec["other"]:
            o = sec["other"]
            lines += ["", f"### Rule profile comparison: {scan.ACTIVE_PROFILE} (above) vs {o['profile']} (below), "
                      f"{sec['label']}", "",
                      "A second full walk-forward on the same data under the other rule profile "
                      "(see scan.RULE_PROFILES).", ""] + _summary_table(o["stats"], prefix=f"{o['profile']}: ")
    lines += ["", "## Signals", "",
              "| Day | Ticker | Pattern | Score | Entry | Fill | Stop | Target | Outcome | Bars | R |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["scan_day"], r["ticker"])):
        lines.append(f"| {r['scan_day']} | {r['ticker']} | {r['pattern']} | {r['score']} | {r['entry']} | "
                     f"{r['fill'] if r['fill'] is not None else '-'} | {r['stop']} | "
                     f"{r['target'] if r['target'] is not None else '-'} | {r['outcome']} | {r['bars']} | "
                     f"{'-' if r['r'] is None else round(r['r'], 2)} |")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=63, help="sessions to replay (default: ~3 months)")
    ap.add_argument("--horizon", type=int, default=40, help="bars after the fill before a signal is 'open'")
    ap.add_argument("--tickers", help="comma separated symbols (default: full S&P 500)")
    ap.add_argument("--csv", help="local constituents CSV")
    ap.add_argument("--period", default="2y", help="yfinance history period (default 2y, what the nightly downloads)")
    ap.add_argument("--bars", type=int, default=None,
                    help="bars of history each scan sees (default: all); 500 mimics the nightly 2y window "
                         "in a long replay")
    ap.add_argument("--split", metavar="YYYY-MM-DD",
                    help="also report the sessions before and from this date as separate windows (out-of-sample check)")
    ap.add_argument("--end", metavar="YYYY-MM-DD",
                    help="last scan day: replay the --days sessions on or before it (default: the newest bar)")
    ap.add_argument("--constituents-asof", action="store_true",
                    help="scan each day's index members from the constituent dataset's git history instead of "
                         "today's list (needs a --period reaching the window, e.g. 10y)")
    ap.add_argument("--cache-dir", default=os.path.join(ROOT, ".cache"),
                    help="where the constituent history clone is kept (default: .cache in the repository)")
    ap.add_argument("--min-score", type=int, default=None, help="override MIN_SCORE for the replay")
    ap.add_argument("--json", help="also write rows and stats here")
    ap.add_argument("--grid", action="store_true",
                    help="also re-score under stop / target variants and replay the other rule profile")
    ap.add_argument("--profile", choices=sorted(scan.RULE_PROFILES), default=scan.ACTIVE_PROFILE,
                    help="rule profile to replay (default: the scanner's active profile)")
    ap.add_argument("--ablate", action="store_true",
                    help="leave-one-rule-out over the spec profile (one full replay per rule; use a short window)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override a scan constant for this replay after the profile is applied, e.g. "
                         "--set CUP_TRIGGER=rim_b or --set WW_TIME_SYM_TOL=0.45 (values parsed as Python literals)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    scan.apply_profile(args.profile)
    for item in args.set:
        key, value = apply_override(item)
        log.info("override %s = %r", key, value)
    if args.min_score is not None:
        scan.MIN_SCORE = args.min_score
    membership: Optional[uh.Membership] = None
    if args.tickers:
        symbols = [s.strip().upper() for s in args.tickers.split(",") if s.strip()]
        if args.constituents_asof:
            log.warning("--constituents-asof ignored: --tickers names the universe")
    elif args.constituents_asof:
        clone = uh.clone_history(args.cache_dir)
        membership = uh.Membership(uh.history(clone), lambda sha: uh.file_at(clone, sha))
        # The window's calendar span is not known before the download; take monthly snapshots over a
        # generous span (sessions to calendar days x1.5 plus a margin) and download their union.
        last = pd.Timestamp(args.end) if args.end else pd.Timestamp.today().normalize()
        first = last - pd.Timedelta(days=int(args.days * 1.5) + 45)
        symbols = sorted(membership.union(list(pd.date_range(first, last, freq="MS")) + [last]))
        log.info("point-in-time universe: %d symbols were members between %s and %s (%d dataset snapshots)",
                 len(symbols), first.date(), last.date(), len(membership.entries))
    else:
        symbols = scan.load_sp500_symbols(args.csv)
    t0 = time.time()
    data = scan.download_history(symbols, period=args.period)
    if not data:
        print("no price data")
        return 2
    log.info("downloaded %d symbols in %.0fs; replaying %d sessions%s%s", len(data), time.time() - t0, args.days,
             f" to {args.end}" if args.end else "", f", each scan sees {args.bars} bars" if args.bars else "")
    market_frames: Dict[str, pd.DataFrame] = {}
    try:  # informational context: a failure leaves the market fields empty, never stops the replay
        market_frames = scan.download_history([scan.MARKET_INDEX, scan.MARKET_VOL], period=args.period)
    except Exception as exc:
        log.warning("market context unavailable: %s", exc)
    market = scan.market_series(data, market_frames.get(scan.MARKET_INDEX), market_frames.get(scan.MARKET_VOL))
    log.info("market context: %s", ", ".join(sorted(market_frames)) or "no index / volatility data (breadth only)")
    replay = {"bars": args.bars, "market": market, "end": args.end,
              "members": membership.members if membership is not None else None}
    universe: Optional[Dict[str, Any]] = None
    if membership is not None:
        universe = {"mode": "point-in-time", "symbols": len(symbols), "with_data": len(data),
                    "coverage": membership.coverage(scan_sessions(data, args.days, args.end), set(data)),
                    "before_history": membership.before_history}
        for c in universe["coverage"]:
            log.info("members with price data in %d: %d of %d", c["year"], c["with_data"], c["members"])
    if args.ablate:
        scan.apply_profile("spec")
        table = ablation(data, args.days, args.horizon, **replay)
        log.info("ablation done in %.0fs: %d replays", time.time() - t0, len(table))
        print(render_ablation(table, args.days, args.horizon))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump({"days": args.days, "horizon": args.horizon, "bars": args.bars, "end": args.end,
                           "universe": universe, "ablation": table}, fh, indent=2)
        return 0
    repeats: List[dict] = []
    rows = walk_forward(data, args.days, args.horizon, repeats=repeats, **replay)
    log.info("replay done in %.0fs: %d first-seen confirmed signals, %d later listings",
             time.time() - t0, len(rows), len(repeats))
    other_rows = other_name = None
    if args.grid:
        other_name = "legacy" if scan.ACTIVE_PROFILE == "spec" else "spec"
        other_rows = profile_pass(data, args.days, args.horizon, other_name, **replay)["rows"]
        log.info("%s-profile pass done in %.0fs: %d first-seen confirmed signals",
                 other_name, time.time() - t0, len(other_rows))
    sections = report_sections(rows, args.days, args.horizon, args.split, data, args.grid, other_rows, other_name,
                               repeats)
    print(render(rows, sections, args.days, args.horizon, universe, args.end))
    if args.json:
        pooled = sections[0]
        keep = ("label", "stats", "features", "horizons", "grid", "other", "late")
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"days": args.days, "horizon": args.horizon, "profile": scan.ACTIVE_PROFILE,
                       "min_score": scan.MIN_SCORE, "bars": args.bars, "split": args.split, "end": args.end,
                       "universe": universe, "market_symbols": sorted(market_frames),
                       "stats": pooled["stats"], "features": pooled["features"], "horizons": pooled["horizons"],
                       "grid": pooled["grid"], "late": pooled["late"],
                       "other_profile": ({"profile": other_name, "stats": pooled["other"]["stats"], "rows": other_rows}
                                         if other_rows is not None else None),
                       "windows": [{k: s[k] for k in keep} for s in sections[1:]],
                       "rows": rows, "repeats": repeats}, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
