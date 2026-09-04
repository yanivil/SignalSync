#!/usr/bin/env python3
"""
S&P 500 chart-pattern scanner.

Scans every S&P 500 constituent on DAILY bars for three bullish patterns:

* Cup & Handle                (continuation)
* Inverse Head & Shoulders    (reversal)
* Bullish Wolfe Wave          (reversal, 5-point falling wedge)

and applies four rules taken from the user's trading guide:

1. Don't force a pattern that isn't there  -> strict geometric thresholds and
   a 0-100 quality score; only setups scoring >= MIN_SCORE are reported.
2. Respect the wider trend                  -> a bullish setup is vetoed when the
   stock is in a strong down-trend (see ``trend_context``).
3. Enter only after confirmation            -> a setup is CONFIRMED only when a
   daily *close* has broken the trigger level; setups that are complete but
   still unbroken are reported separately as WATCHLIST so nothing is entered
   early.
4. Manage risk                              -> every alert carries an entry
   price, a stop-loss derived from the pattern structure, and the risk %.

Output: a JSON file (machine readable) and a Markdown report (human readable).

Usage:
    python3 scan.py [--out-dir DIR] [--tickers AAPL,MSFT] [--csv path.csv]
                    [--period 2y] [--min-score 60] [--max-age 3]

Requires: pandas, numpy, yfinance (pip install yfinance pandas numpy).
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import logging
import math
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, asdict, field
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger("sp500scan")

# --------------------------------------------------------------------------- #
# Tunable parameters
#
# Why: every threshold that decides "is this a pattern?" lives here so that the
# rules are auditable in one place and can be tightened/loosened without
# touching detector logic.  Values follow common technical-analysis practice
# (O'Neil for Cup & Handle, Bulkowski for H&S, Bill Wolfe's published rules
# for Wolfe Waves) but they are heuristics, not standards.
# --------------------------------------------------------------------------- #
CONSTITUENTS_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "main/data/constituents.csv"
)
PIVOT_ORDER = 5          # bars on each side needed to call a swing high/low
ATR_LEN = 14
MIN_SCORE = 60           # reporting threshold for the 0-100 quality score
MAX_BREAKOUT_AGE = 3     # a breakout older than this many bars is stale
MAX_RUNAWAY = 0.05       # close more than 5% above trigger = chasing, not an entry
WATCH_PROXIMITY = 0.03   # unbroken setups within 3% of trigger -> watchlist
# Extra breakout age tolerated per pattern, in bars.  The H&S right shoulder
# and Wolfe point 5 are swing lows, which only become visible PIVOT_ORDER bars
# after they print, so a breakout can already be up to PIVOT_ORDER bars old the
# first time the pattern is detectable at all.  The cup's handle low needs no
# right-side confirmation, so the cup gets no extra tolerance.  Keep this table
# and the detectors in sync via ``max_breakout_age()`` so the report can state
# the effective limit per pattern.
BREAKOUT_AGE_LAG = {
    "Cup & Handle": 0,
    "Inverse Head & Shoulders": PIVOT_ORDER,
    "Bullish Wolfe Wave": PIVOT_ORDER,
}
# A trading day only counts as "the" last bar of the scan when at least this
# share of symbols has a complete OHLC bar on (or after) it.  Why: Yahoo
# publishes the previous session's daily row in two steps -- first volume only
# (OHLC null), then the prices some hours later -- so early in the day a
# handful of symbols carry a complete newest bar while the rest do not.
LAST_BAR_MIN_FRACTION = 0.5

# Cup & Handle
CUP_MIN_LEN, CUP_MAX_LEN = 30, 250       # bars from left rim to right rim
CUP_MIN_DEPTH, CUP_MAX_DEPTH = 0.12, 0.50  # cup depth as fraction of left rim
CUP_RIM_TOL = 0.05                       # right rim within 5% of left rim
HANDLE_MIN_LEN, HANDLE_MAX_LEN = 5, 40
HANDLE_MAX_DEPTH = 0.12                  # handle pull-back from right rim (O'Neil: <= 12%)
HANDLE_MAX_FRACTION_OF_CUP = 0.50        # handle depth vs cup depth
CUP_PRIOR_ADVANCE = 0.25                 # >= 25% rise into the left rim (prior uptrend)
CUP_MIN_ROUNDNESS = 0.60                 # R^2 of a U-shaped (convex) quadratic fit to cup lows

# Inverse Head & Shoulders
IHS_MIN_LEN, IHS_MAX_LEN = 20, 200       # bars from left shoulder to right shoulder
IHS_MIN_HEAD_ATR = 1.0                   # head must be >= 1 ATR below both shoulders
IHS_SHOULDER_SYM = 0.50                  # |LS-RS| <= 50% of the shallower shoulder depth
IHS_TIME_SYM = 2.5                       # left/right half duration ratio
IHS_MAX_NECK_SLOPE = 0.15                # neckline rise/fall over pattern, fraction of price
IHS_PRIOR_DECLINE = 0.10                 # >=10% decline into the left shoulder

# Bullish Wolfe Wave
WW_MIN_LEN, WW_MAX_LEN = 15, 200         # bars from point 1 to point 5
WW_MAX_OVERSHOOT_ATR = 2.0               # point 5 may undercut line 1-3 by <= 2 ATR
WW_MAX_BARS_SINCE_P5 = 25                # confirmation must come soon after point 5


def max_breakout_age(pattern: str) -> int:
    """Effective maximum bars since the confirming close for ``pattern``.

    :param pattern: Pattern name as reported in :class:`Signal`.
    :returns: ``MAX_BREAKOUT_AGE`` plus the pattern's pivot lag (see
        ``BREAKOUT_AGE_LAG``).  Reads the module global so ``--max-age`` applies.
    """
    return MAX_BREAKOUT_AGE + BREAKOUT_AGE_LAG.get(pattern, 0)


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #
@dataclass
class Signal:
    """One detected setup on one ticker.

    :param ticker: Yahoo-style symbol (BRK-B etc.).
    :param pattern: Human readable pattern name.
    :param status: ``"CONFIRMED"`` (close broke trigger within
        ``max_breakout_age(pattern)`` bars) or ``"WATCHLIST"`` (pattern complete,
        trigger not yet broken).
    :param entry: Suggested entry price (the trigger level, or the breakout close
        if it is above the trigger).
    :param stop: Stop-loss price derived from the pattern structure.
    :param risk_pct: (entry - stop) / entry * 100.
    :param target: Reference measured-move target (informational).
    :param score: 0-100 quality score (higher = cleaner geometry).
    :param last_close: Most recent close.
    :param last_date: Date of the most recent *complete* bar scanned (ISO).
    :param bars_since_break: Bars since the confirming close (0 = today), or None.
    :param volume_ratio: Breakout-day volume / 50-day average volume, or None.
    :param trend: Short description of the wider-trend context.
    :param notes: Free-text details (pattern anchor dates and levels).
    """

    ticker: str
    pattern: str
    status: str
    entry: float
    stop: float
    risk_pct: float
    target: Optional[float]
    score: int
    last_close: float
    last_date: str
    bars_since_break: Optional[int]
    volume_ratio: Optional[float]
    trend: str
    notes: str = ""


# --------------------------------------------------------------------------- #
# Universe & data loading
# --------------------------------------------------------------------------- #
def load_sp500_symbols(csv_path: Optional[str] = None) -> List[str]:
    """Return the S&P 500 constituent symbols in Yahoo Finance format.

    Source priority: a local CSV (``--csv``), then the public GitHub dataset
    ``datasets/s-and-p-500-companies``.  Dots in class-share tickers are
    replaced with dashes because Yahoo uses ``BRK-B`` where S&P uses ``BRK.B``.

    :param csv_path: Optional local CSV with a ``Symbol`` column.
    :returns: Sorted, de-duplicated list of symbols.
    :raises RuntimeError: if no source could be read.
    """
    text: Optional[str] = None
    if csv_path and os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    else:
        try:
            with urllib.request.urlopen(CONSTITUENTS_URL, timeout=30) as resp:
                text = resp.read().decode("utf-8")
        except Exception as exc:  # network blocked, DNS failure, etc.
            log.warning("Could not download constituents: %s", exc)
    if not text:
        raise RuntimeError("No S&P 500 constituent source available")
    df = pd.read_csv(io.StringIO(text))
    col = "Symbol" if "Symbol" in df.columns else df.columns[0]
    syms = sorted({str(s).strip().replace(".", "-") for s in df[col].dropna()})
    return [s for s in syms if s and s.upper() != "NAN"]


def download_history(symbols: Sequence[str], period: str = "2y",
                     batch: int = 100) -> dict:
    """Download daily OHLCV for many symbols with yfinance, in batches.

    :param symbols: Yahoo symbols.
    :param period: yfinance period string (``"2y"`` gives ~500 daily bars).
    :param batch: Symbols per request; Yahoo tolerates ~100 comfortably.
    :returns: ``{symbol: DataFrame[Open, High, Low, Close, Volume]}`` with only
        symbols that returned usable data.  Rows without a Close are dropped;
        the dates of *trailing* rows dropped this way (Yahoo's not-yet-published
        newest bar, which arrives with volume but null OHLC) are recorded in
        ``df.attrs["partial_bars"]`` so :func:`align_last_bar` can report them.
    :raises ImportError: if yfinance is not installed.
    """
    import yfinance as yf  # imported lazily so tests can run without it

    out: dict = {}
    raw_last: dict = {}     # last index date before cleaning, per symbol (diagnostics)
    for i in range(0, len(symbols), batch):
        chunk = list(symbols[i:i + batch])
        for attempt in range(3):  # Yahoo occasionally throttles; retry with backoff
            try:
                raw = yf.download(chunk, period=period, interval="1d",
                                  group_by="ticker", auto_adjust=True,
                                  progress=False, threads=True)
                break
            except Exception as exc:
                log.warning("batch %d attempt %d failed: %s", i // batch, attempt, exc)
                time.sleep(5 * (attempt + 1))
        else:
            continue
        for sym in chunk:
            try:
                df = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                continue
            if df.empty:
                continue
            raw_last[sym] = df.index[-1]
            has_close = df["Close"].notna().to_numpy()
            if not has_close.any():
                continue
            last_ok = int(np.flatnonzero(has_close)[-1])
            # Trailing rows without a Close: Yahoo's volume-only row for a bar
            # whose prices are not published yet ("partial").  Rows that are
            # NaN in every column are just batch-index padding for a symbol
            # that has no row on that date at all (halted / delisted) and are
            # not reported as partial.
            tail = df.iloc[last_ok + 1:]
            partial = [str(d.date()) for d, row in tail.iterrows() if row.notna().any()]
            df = df[has_close]
            log.debug("%s: last raw bar %s, last complete bar %s%s", sym,
                      raw_last[sym].date(), df.index[-1].date(),
                      f", trailing rows without Close: {partial}" if partial else "")
            if len(df) >= 60:
                clean = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                clean.attrs["partial_bars"] = partial
                out[sym] = clean
    if out:
        hist_raw = _date_histogram(raw_last.values())
        hist_ok = _date_histogram(df.index[-1] for df in out.values())
        log.info("last raw bar per symbol: %s; last complete bar per symbol: %s",
                 hist_raw, hist_ok)
    return out


def _date_histogram(dates: Iterable) -> dict:
    """``{"YYYY-MM-DD": count}`` sorted newest first (for logs and meta)."""
    counts: dict = {}
    for d in dates:
        key = str(pd.Timestamp(d).date())
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), reverse=True))


def align_last_bar(data: dict, min_fraction: float = LAST_BAR_MIN_FRACTION
                   ) -> Tuple[dict, dict]:
    """Pick the bar the scan is "as of" and make sure no symbol runs ahead of it.

    Why: Yahoo publishes the newest daily bar per symbol at different times
    (volume first, prices later).  Scanning each symbol on whatever it has
    gives a report whose ``last_bar`` is the newest date *any* symbol reached,
    while nearly every signal is based on the previous close.  Instead:

    * ``last_bar`` is the newest date on/after which at least ``min_fraction``
      of the symbols have a complete bar.  With the default 0.5 that is the
      majority's newest complete bar.
    * Symbols with bars newer than ``last_bar`` are truncated to it so every
      signal is comparable (the dropped bars are counted as ``skipped``).
    * Symbols whose newest complete bar is *older* than ``last_bar`` are kept
      as they are (halted / late symbols); their signals carry their own
      ``last_date`` and they are counted as ``lagging``.

    :param data: ``{symbol: OHLCV DataFrame}`` as returned by
        :func:`download_history` (rows already have a Close).
    :param min_fraction: Share of symbols required on/after a date.
    :returns: ``(data, info)`` where ``info`` has ``last_bar``,
        ``last_bar_symbols``, ``lagging_symbols``, ``skipped_bar`` (newest date
        seen but not scanned, or ``None``), ``skipped_bar_complete`` (symbols
        that had a complete bar on it), ``skipped_bar_partial`` (symbols that
        had only Yahoo's volume-only row on it) and ``last_bar_histogram``
        (newest complete bar per symbol before alignment).
    """
    if not data:
        return data, {"last_bar": None}
    last = {sym: pd.Timestamp(df.index[-1]).normalize() for sym, df in data.items()}
    hist = _date_histogram(last.values())
    need = min_fraction * len(data)
    cum = 0
    last_bar = None
    for day, count in hist.items():          # newest first
        cum += count
        if cum >= need:
            last_bar = pd.Timestamp(day)
            break
    assert last_bar is not None  # cum reaches len(data) >= need at the oldest date

    aligned: dict = {}
    skipped_complete: dict = {}
    partial: dict = {}
    for sym, df in data.items():
        for day in df.attrs.get("partial_bars", []):
            if pd.Timestamp(day) > last_bar:
                partial[day] = partial.get(day, 0) + 1
        if last[sym] > last_bar:
            for d in df.index[df.index > last_bar]:
                key = str(d.date())
                skipped_complete[key] = skipped_complete.get(key, 0) + 1
            df = df[df.index <= last_bar]
            df.attrs["partial_bars"] = []
            if len(df) < 60:
                continue
        aligned[sym] = df
    newest_seen = max(list(skipped_complete) + list(partial), default=None)
    info = {
        "last_bar": str(last_bar.date()),
        "last_bar_symbols": sum(1 for df in aligned.values()
                                if pd.Timestamp(df.index[-1]).normalize() == last_bar),
        "lagging_symbols": sum(1 for df in aligned.values()
                               if pd.Timestamp(df.index[-1]).normalize() < last_bar),
        "skipped_bar": newest_seen,
        "skipped_bar_complete": skipped_complete.get(newest_seen, 0) if newest_seen else 0,
        "skipped_bar_partial": partial.get(newest_seen, 0) if newest_seen else 0,
        "last_bar_histogram": hist,
    }
    return aligned, info


# --------------------------------------------------------------------------- #
# Indicators & pivots
# --------------------------------------------------------------------------- #
def atr(df: pd.DataFrame, n: int = ATR_LEN) -> pd.Series:
    """Average True Range (simple rolling mean of true range).

    :param df: OHLC DataFrame.
    :param n: Look-back length.
    :returns: ATR series aligned with ``df``.
    """
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


def find_pivots(high: np.ndarray, low: np.ndarray, order: int = PIVOT_ORDER
                ) -> Tuple[List[int], List[int]]:
    """Fractal swing detection.

    Bar *i* is a swing high if ``high[i]`` is the maximum of the window
    ``[i-order, i+order]`` (ties resolved to the first occurrence), and likewise
    for swing lows.  The last ``order`` bars can never be pivots, which is the
    price paid for not repainting.

    :param high: High prices.
    :param low: Low prices.
    :param order: Bars required on each side.
    :returns: ``(swing_high_indices, swing_low_indices)``.
    """
    n = len(high)
    highs, lows = [], []
    for i in range(order, n - order):
        window_h = high[i - order:i + order + 1]
        window_l = low[i - order:i + order + 1]
        if high[i] >= window_h.max() and np.argmax(window_h) == order:
            highs.append(i)
        if low[i] <= window_l.min() and np.argmin(window_l) == order:
            lows.append(i)
    return highs, lows


def trend_context(df: pd.DataFrame) -> Tuple[str, bool, bool]:
    """Describe the wider trend and decide whether bullish setups are allowed.

    Rule 2 of the guide ("ignoring the wider trend") is implemented as:

    * ``strong_downtrend`` = close below a *falling* 200-day SMA by more than
      10 %.  Bullish setups are vetoed in that state.
    * ``uptrend`` = close above the 200-day SMA (required for the Cup & Handle,
      which is a continuation pattern; optional bonus for reversal patterns).

    :param df: OHLCV DataFrame (>= 60 bars).
    :returns: ``(description, uptrend, strong_downtrend)``.
    """
    close = df["Close"]
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    c = float(close.iloc[-1])
    s50 = float(sma50.iloc[-1]) if not math.isnan(sma50.iloc[-1]) else None
    s200 = float(sma200.iloc[-1]) if not math.isnan(sma200.iloc[-1]) else None
    s200_prev = (float(sma200.iloc[-40]) if len(sma200) > 40
                 and not math.isnan(sma200.iloc[-40]) else None)

    if s200 is None:  # not enough history for a 200-day view; fall back to 50
        uptrend = s50 is not None and c > s50
        strong_down = s50 is not None and c < 0.85 * s50
        desc = f"close {'above' if uptrend else 'below'} SMA50 (SMA200 n/a)"
        return desc, uptrend, strong_down

    falling200 = s200_prev is not None and s200 < s200_prev
    uptrend = c > s200
    strong_down = (c < 0.90 * s200) and falling200
    parts = [f"close {'above' if uptrend else 'below'} SMA200"]
    if s50 is not None:
        parts.append(f"SMA50 {'>' if s50 > s200 else '<'} SMA200")
    parts.append("SMA200 " + ("falling" if falling200 else "rising/flat"))
    return ", ".join(parts), uptrend, strong_down


def _volume_ratio(df: pd.DataFrame, idx: int) -> Optional[float]:
    """Volume on bar ``idx`` divided by the trailing 50-bar average (excl. idx)."""
    vol = df["Volume"].to_numpy(dtype=float)
    if idx < 20 or np.isnan(vol[idx]):
        return None
    base = vol[max(0, idx - 50):idx]
    base = base[~np.isnan(base)]
    if len(base) == 0 or base.mean() == 0:
        return None
    return round(float(vol[idx] / base.mean()), 2)


def _status_from_break(close: np.ndarray, trigger: float, start: int,
                       lag: int = 0) -> Tuple[str, Optional[int]]:
    """Classify a setup by whether/when the close broke ``trigger``.

    :param close: Close prices.
    :param trigger: Level a close must exceed to confirm.
    :param start: First bar index at which a break counts (after the pattern
        completed).
    :param lag: Extra bars of breakout age tolerated because the pattern's last
        pivot only becomes visible ``PIVOT_ORDER`` bars after it prints (used
        by the H&S and Wolfe detectors; 0 for the cup, whose handle low needs
        no right-side confirmation).
    :returns: ``("CONFIRMED", bars_since_break)``, ``("WATCHLIST", None)`` or
        ``("STALE", bars_since_break)`` if the break is too old / price already
        ran away (rule 3 + rule 4: no chasing).
    """
    n = len(close)
    first_break = None
    for i in range(max(start, 0), n):
        if close[i] > trigger:
            first_break = i
            break
    if first_break is None:
        # Not broken.  Watchlist only if price is close to the trigger and has
        # not collapsed away from it.
        if close[-1] >= trigger * (1 - WATCH_PROXIMITY):
            return "WATCHLIST", None
        return "STALE", None
    age = n - 1 - first_break
    if age > MAX_BREAKOUT_AGE + lag or close[-1] < trigger:
        # Breakout happened too long ago or failed (closed back below trigger).
        return "STALE", age
    if close[-1] > trigger * (1 + MAX_RUNAWAY):
        return "STALE", age  # price already ran away; entering now is chasing
    return "CONFIRMED", age



def _u_shape_r2(lows: np.ndarray) -> float:
    """R^2 of a convex quadratic fitted to the cup lows (1.0 = perfect U).

    Returns 0 when the best-fit parabola opens downward (an arch, not a cup).

    :param lows: Low prices from left rim to right rim inclusive.
    :returns: Coefficient of determination in [0, 1].
    """
    x = np.arange(len(lows), dtype=float)
    if len(x) < 5:
        return 0.0
    coef = np.polyfit(x, lows, 2)
    if coef[0] <= 0:
        return 0.0
    fit = np.polyval(coef, x)
    ss_res = float(((lows - fit) ** 2).sum())
    ss_tot = float(((lows - lows.mean()) ** 2).sum())
    return max(0.0, 1 - ss_res / ss_tot) if ss_tot > 0 else 0.0


def _find_handle(high: np.ndarray, low: np.ndarray, close: np.ndarray, b: int,
                 n: int) -> Optional[Tuple[int, float, int]]:
    """Locate the handle that follows right rim ``b``.

    The handle runs from ``b+1`` until the bar *before* the first close that
    exceeds the running handle high (the breakout), or until ``HANDLE_MAX_LEN``
    bars / the end of data.  It must contain at least ``HANDLE_MIN_LEN`` bars.

    :returns: ``(handle_low_index, handle_high, handle_end_index)`` or ``None``.
    """
    start = b + 1
    end_max = min(b + HANDLE_MAX_LEN, n - 1)
    if start + HANDLE_MIN_LEN - 1 > end_max:
        return None
    run_high = -np.inf
    end = end_max
    for j in range(start, end_max + 1):
        # A close above the handle high so far ends the handle at j-1 -- but
        # only once the minimum handle length has been reached; before that a
        # close above the running high is just the handle still forming.
        if j - start >= HANDLE_MIN_LEN and close[j] > run_high:
            end = j - 1
            break
        run_high = max(run_high, high[j])
    if end - start + 1 < HANDLE_MIN_LEN:
        return None
    seg = low[start:end + 1]
    h_low_idx = start + int(np.argmin(seg))
    handle_high = float(high[start:end + 1].max())
    return h_low_idx, handle_high, end


# --------------------------------------------------------------------------- #
# Detector: Cup & Handle
# --------------------------------------------------------------------------- #
def detect_cup_and_handle(df: pd.DataFrame, ticker: str) -> List[Signal]:
    """Detect a Cup & Handle on daily bars.

    Geometry (O'Neil style):

    * Left rim ``A`` and right rim ``B`` are swing highs 30-250 bars apart with
      ``B`` within 5 % of ``A``.
    * Cup bottom is the lowest low between them, 12-50 % below ``A`` and located
      in the middle 60 % of the cup (U-shape rather than a V at one edge).
    * Prior advance of >= 25 % into the left rim and a convex-quadratic
      roundness fit (R^2 >= ``CUP_MIN_ROUNDNESS``) of the cup lows.
    * Handle: 5-40 bars after ``B``, its low stays above the cup's mid-point and
      within 12 % of ``B``; handle depth <= half the cup depth.
    * Trigger: close above the handle high (which is <= B).  Stop: handle low
      minus 0.25 ATR.
    * Requires close above the 200-day SMA (continuation pattern needs an uptrend).

    :param df: OHLCV DataFrame.
    :param ticker: Symbol for labelling.
    :returns: Zero or more Signals (best-scoring per rim pair).
    """
    high, low, close = (df[c].to_numpy(dtype=float) for c in ("High", "Low", "Close"))
    n = len(close)
    if n < CUP_MIN_LEN + HANDLE_MIN_LEN + 5:
        return []
    desc, uptrend, strong_down = trend_context(df)
    if not uptrend:
        return []  # rule 2: continuation pattern needs the uptrend
    piv_h, _ = find_pivots(high, low, order=PIVOT_ORDER)
    signals: List[Signal] = []
    a_tr = atr(df).to_numpy(dtype=float)

    for ai, a in enumerate(piv_h):
        for b in piv_h[ai + 1:]:
            width = b - a
            if width < CUP_MIN_LEN:
                continue
            if width > CUP_MAX_LEN:
                break
            rim_a, rim_b = high[a], high[b]
            if abs(rim_b - rim_a) / rim_a > CUP_RIM_TOL:
                continue
            seg_low = low[a:b + 1]
            bottom_rel = int(np.argmin(seg_low))
            bottom = seg_low[bottom_rel]
            depth = (rim_a - bottom) / rim_a
            if not (CUP_MIN_DEPTH <= depth <= CUP_MAX_DEPTH):
                continue
            pos = bottom_rel / width
            if not (0.20 <= pos <= 0.80):
                continue  # bottom hugging one rim -> not a rounded cup
            # Prior up-trend into the left rim: a cup is a *continuation* base,
            # so the stock must have advanced meaningfully before rim A.
            pre_low = float(low[max(0, a - 120):a + 1].min())
            if (rim_a - pre_low) / pre_low < CUP_PRIOR_ADVANCE:
                continue
            # Roundness: fit a convex quadratic to the cup lows; a V or a ragged
            # base scores poorly.  This is the main defence against "seeing"
            # cups in random price movement (rule 1).
            roundness = _u_shape_r2(seg_low)
            if roundness < CUP_MIN_ROUNDNESS:
                continue
            # Handle: the stretch after rim B up to (not including) the first
            # close above the handle's own high.  It must last >= HANDLE_MIN_LEN
            # bars, stay shallow, and hold the upper half of the cup.
            handle = _find_handle(high, low, close, b, n)
            if handle is None:
                continue
            h_low_idx, handle_high, handle_end = handle
            handle_low = low[h_low_idx]
            handle_depth = (rim_b - handle_low) / rim_b
            if handle_depth > HANDLE_MAX_DEPTH:
                continue
            if handle_low < bottom + 0.5 * (rim_b - bottom):
                continue  # handle dipped into lower half of the cup
            if handle_depth > HANDLE_MAX_FRACTION_OF_CUP * depth:
                continue
            trigger = float(handle_high)
            status, age = _status_from_break(close, trigger, start=handle_end + 1)
            if status == "STALE":
                continue
            entry = float(close[-1]) if status == "CONFIRMED" and close[-1] > trigger else float(trigger)
            stop = float(handle_low - 0.25 * a_tr[h_low_idx])
            if stop >= entry:
                continue
            risk = (entry - stop) / entry * 100
            if risk > 15:
                continue  # rule 4: reject setups whose structural stop is too far
            # Quality score: symmetric cup, moderate depth, shallow handle,
            # tight risk, volume on breakout.
            score = 50
            score += 15 * (roundness - CUP_MIN_ROUNDNESS) / (1 - CUP_MIN_ROUNDNESS)
            score += 10 * (1 - min(abs(depth - 0.25) / 0.25, 1))  # depth ~25% ideal
            score += 10 * (1 - min(handle_depth / HANDLE_MAX_DEPTH, 1))
            score += 10 * (1 - min(risk / 15, 1))
            vr = _volume_ratio(df, n - 1 - age) if age is not None else None
            if vr is not None and vr >= 1.3:
                score += 5
            score = int(max(0, min(100, round(score))))
            if score < MIN_SCORE:
                continue
            target = float(entry + (rim_a - bottom))  # measured move
            dates = df.index
            notes = (f"left rim {dates[a].date()} @{rim_a:.2f}, bottom "
                     f"{dates[a + bottom_rel].date()} @{bottom:.2f} (depth {depth*100:.0f}%), "
                     f"right rim {dates[b].date()} @{rim_b:.2f}, handle low "
                     f"{dates[h_low_idx].date()} @{handle_low:.2f} (depth {handle_depth*100:.1f}%), "
                     f"trigger {trigger:.2f}")
            signals.append(Signal(ticker, "Cup & Handle", status, round(entry, 2), round(stop, 2),
                                  round(risk, 2), round(target, 2), score, round(float(close[-1]), 2),
                                  str(dates[-1].date()), age, vr, desc, notes))
    return _dedupe(signals)


# --------------------------------------------------------------------------- #
# Detector: Inverse Head & Shoulders
# --------------------------------------------------------------------------- #
def detect_inverse_hs(df: pd.DataFrame, ticker: str) -> List[Signal]:
    """Detect an Inverse Head & Shoulders (bullish reversal) on daily bars.

    Geometry (Bulkowski style):

    * Three consecutive swing lows LS, H, RS with H at least ``IHS_MIN_HEAD_ATR``
      ATR below both shoulders; shoulders within ``IHS_SHOULDER_SYM`` of each
      other relative to the shallower shoulder depth.
    * Neckline through the swing highs between LS-H and H-RS; slope limited.
    * Left and right halves within a 2.5x duration ratio; total 20-200 bars.
    * A prior decline of >= 10 % into LS (it must be reversing *something*).
    * Trigger: close above the neckline value on that bar.  Stop: below RS.
    * Vetoed in a strong down-trend (rule 2); above-SMA200 adds score.

    :param df: OHLCV DataFrame.
    :param ticker: Symbol for labelling.
    :returns: Zero or more Signals.
    """
    high, low, close = (df[c].to_numpy(dtype=float) for c in ("High", "Low", "Close"))
    n = len(close)
    if n < IHS_MIN_LEN + 20:
        return []
    desc, uptrend, strong_down = trend_context(df)
    if strong_down:
        return []
    a_tr = atr(df).to_numpy(dtype=float)
    piv_h, piv_l = find_pivots(high, low, order=PIVOT_ORDER)
    signals: List[Signal] = []

    for i in range(len(piv_l) - 2):
        ls, h, rs = piv_l[i], piv_l[i + 1], piv_l[i + 2]
        width = rs - ls
        if not (IHS_MIN_LEN <= width <= IHS_MAX_LEN):
            continue
        ls_v, h_v, rs_v = low[ls], low[h], low[rs]
        unit = a_tr[h]
        if not (h_v < ls_v - IHS_MIN_HEAD_ATR * unit and h_v < rs_v - IHS_MIN_HEAD_ATR * unit):
            continue
        d_left, d_right = ls_v - h_v, rs_v - h_v
        if abs(ls_v - rs_v) > IHS_SHOULDER_SYM * min(d_left, d_right):
            continue
        ratio = (h - ls) / max(rs - h, 1)
        if ratio > IHS_TIME_SYM or ratio < 1 / IHS_TIME_SYM:
            continue
        # Neckline anchors: highest high between LS-H and between H-RS.
        n1 = ls + int(np.argmax(high[ls:h + 1]))
        n2 = h + int(np.argmax(high[h:rs + 1]))
        if n2 == n1:
            continue
        slope = (high[n2] - high[n1]) / (n2 - n1)
        if abs(slope * width) / close[h] > IHS_MAX_NECK_SLOPE:
            continue
        # Prior decline into the left shoulder.
        look = high[max(0, ls - 60):ls + 1]
        if (look.max() - ls_v) / look.max() < IHS_PRIOR_DECLINE:
            continue

        def neck_at(idx: int) -> float:
            return float(high[n1] + slope * (idx - n1))

        # Confirmation: first close above the neckline after RS.
        first_break = None
        for j in range(rs + 1, n):
            if close[j] > neck_at(j):
                first_break = j
                break
        trigger_now = neck_at(n - 1)
        if first_break is None:
            if close[-1] >= trigger_now * (1 - WATCH_PROXIMITY) and close[-1] > rs_v:
                status, age, trigger = "WATCHLIST", None, trigger_now
            else:
                continue
        else:
            age = n - 1 - first_break
            trigger = neck_at(first_break)
            if age > max_breakout_age("Inverse Head & Shoulders") or close[-1] < neck_at(n - 1):
                continue  # stale breakout or failed break (RS pivot lags PIVOT_ORDER bars)
            if close[-1] > trigger * (1 + MAX_RUNAWAY):
                continue  # ran away from the breakout level; chasing (rule 4)
            status = "CONFIRMED"
        entry = float(close[-1]) if status == "CONFIRMED" and close[-1] > trigger else float(trigger)
        stop = float(rs_v - 0.25 * a_tr[rs])
        if stop >= entry:
            continue
        risk = (entry - stop) / entry * 100
        if risk > 15:
            continue
        height = trigger - h_v
        score = 50
        score += 15 * (1 - abs(ls_v - rs_v) / max(IHS_SHOULDER_SYM * min(d_left, d_right), 1e-9))
        score += 10 * (1 - abs(math.log(ratio)) / math.log(IHS_TIME_SYM))
        score += 10 * (1 - min(abs(slope * width) / close[h] / IHS_MAX_NECK_SLOPE, 1))
        score += 5 if uptrend else 0
        score += 5 * (1 - min(risk / 15, 1))
        vr = _volume_ratio(df, n - 1 - age) if age is not None else None
        if vr is not None and vr >= 1.3:
            score += 5
        score = int(max(0, min(100, round(score))))
        if score < MIN_SCORE:
            continue
        dates = df.index
        notes = (f"LS {dates[ls].date()} @{ls_v:.2f}, head {dates[h].date()} @{h_v:.2f}, "
                 f"RS {dates[rs].date()} @{rs_v:.2f}, neckline {high[n1]:.2f}->{high[n2]:.2f} "
                 f"(now {trigger_now:.2f})")
        signals.append(Signal(ticker, "Inverse Head & Shoulders", status, round(entry, 2),
                              round(stop, 2), round(risk, 2), round(float(entry + height), 2),
                              score, round(float(close[-1]), 2), str(dates[-1].date()), age, vr,
                              desc, notes))
    return _dedupe(signals)


# --------------------------------------------------------------------------- #
# Detector: Bullish Wolfe Wave
# --------------------------------------------------------------------------- #
def detect_bullish_wolfe(df: pd.DataFrame, ticker: str) -> List[Signal]:
    """Detect a Bullish Wolfe Wave on daily bars.

    Implementation of Bill Wolfe's published rules for the bullish case:

    * Points 1, 3, 5 are swing lows and 2, 4 are swing highs, alternating.
    * Lower lows (3 < 1, 5 < 3) and a lower high (4 < 2): a falling wedge.
    * Point 4 lies between points 1 and 2 in price (``1 < 4 < 2``).
    * Lines 1-3 and 2-4 converge (intersect in the future = the "ETA").
    * Point 5 undercuts the extended 1-3 line (the false breakdown) by no more
      than ``WW_MAX_OVERSHOOT_ATR`` ATR, or touches it.
    * Trigger (rule 3, confirmation): a close back above the 1-3 line after
      point 5.  Stop: below point 5.  Target: the 1-4 line ("EPA") at the ETA
      bar, reported for reference only.

    Because a swing low needs ``PIVOT_ORDER`` bars on its right, point 5 is only
    recognised ``PIVOT_ORDER`` bars after it printed; the trigger check then
    looks at closes after that.

    :param df: OHLCV DataFrame.
    :param ticker: Symbol for labelling.
    :returns: Zero or more Signals.
    """
    high, low, close = (df[c].to_numpy(dtype=float) for c in ("High", "Low", "Close"))
    n = len(close)
    if n < WW_MIN_LEN + 20:
        return []
    desc, uptrend, strong_down = trend_context(df)
    if strong_down:
        return []
    a_tr = atr(df).to_numpy(dtype=float)
    piv_h, piv_l = find_pivots(high, low, order=PIVOT_ORDER)
    piv_h_set = set(piv_h)
    signals: List[Signal] = []

    for i in range(len(piv_l) - 2):
        p1, p3, p5 = piv_l[i], piv_l[i + 1], piv_l[i + 2]
        if not (WW_MIN_LEN <= p5 - p1 <= WW_MAX_LEN):
            continue
        if n - 1 - p5 > WW_MAX_BARS_SINCE_P5:
            continue  # point 5 too old to be actionable
        v1, v3, v5 = low[p1], low[p3], low[p5]
        if not (v3 < v1 and v5 < v3):
            continue
        # Points 2 and 4: highest swing highs inside (1,3) and (3,5).
        c2 = [k for k in range(p1 + 1, p3) if k in piv_h_set]
        c4 = [k for k in range(p3 + 1, p5) if k in piv_h_set]
        if not c2 or not c4:
            continue
        p2 = max(c2, key=lambda k: high[k])
        p4 = max(c4, key=lambda k: high[k])
        v2, v4 = high[p2], high[p4]
        if not (v4 < v2):
            continue
        if not (v1 < v4 < v2):
            continue  # Wolfe's "point 4 between 1 and 2" rule
        s13 = (v3 - v1) / (p3 - p1)   # negative (falling)
        s24 = (v4 - v2) / (p4 - p2)   # negative (falling)
        if not (s24 < s13):
            continue  # upper line must fall faster -> lines converge ahead
        line13_at5 = v1 + s13 * (p5 - p1)
        overshoot = line13_at5 - v5     # positive = undercut below the line
        if overshoot < -0.5 * a_tr[p5]:
            continue  # point 5 clearly failed to reach the line
        if overshoot > WW_MAX_OVERSHOOT_ATR * a_tr[p5]:
            continue  # broke down for real, not a Wolfe false break
        # Confirmation: first close back above line 1-3 after point 5.
        first_break = None
        for j in range(p5 + 1, n):
            if close[j] > v1 + s13 * (j - p1):
                first_break = j
                break
        line_now = v1 + s13 * (n - 1 - p1)
        if first_break is None:
            if close[-1] >= line_now * (1 - WATCH_PROXIMITY) and close[-1] > v5:
                status, age, trigger = "WATCHLIST", None, line_now
            else:
                continue
        else:
            age = n - 1 - first_break
            trigger = v1 + s13 * (first_break - p1)
            if age > max_breakout_age("Bullish Wolfe Wave") or close[-1] < line_now:
                continue  # stale or failed (point-5 pivot lags PIVOT_ORDER bars)
            if close[-1] > trigger * (1 + MAX_RUNAWAY):
                continue  # ran away from the breakout level; chasing (rule 4)
            status = "CONFIRMED"
        entry = float(close[-1]) if status == "CONFIRMED" and close[-1] > trigger else float(trigger)
        stop = float(v5 - 0.25 * a_tr[p5])
        if stop >= entry:
            continue
        risk = (entry - stop) / entry * 100
        if risk > 15:
            continue
        # ETA = intersection of lines 1-3 and 2-4; EPA = line 1-4 at ETA.
        denom = s13 - s24
        eta = (v2 - s24 * p2 - (v1 - s13 * p1)) / denom if denom != 0 else None
        s14 = (v4 - v1) / (p4 - p1)
        target = float(v1 + s14 * (eta - p1)) if eta is not None and eta > p5 else None
        if target is not None and target <= entry:
            target = None
        score = 50
        score += 15 * (1 - min(abs(overshoot) / (WW_MAX_OVERSHOOT_ATR * a_tr[p5]), 1))
        sym = (p3 - p1) / max(p5 - p3, 1)
        score += 10 * (1 - min(abs(math.log(sym)) / math.log(3), 1))
        score += 10 * (1 - min(risk / 15, 1))
        score += 5 if uptrend else 0
        vr = _volume_ratio(df, n - 1 - age) if age is not None else None
        if vr is not None and vr >= 1.3:
            score += 5
        score = int(max(0, min(100, round(score))))
        if score < MIN_SCORE:
            continue
        dates = df.index
        notes = (f"1 {dates[p1].date()} @{v1:.2f}, 2 {dates[p2].date()} @{v2:.2f}, "
                 f"3 {dates[p3].date()} @{v3:.2f}, 4 {dates[p4].date()} @{v4:.2f}, "
                 f"5 {dates[p5].date()} @{v5:.2f}; line 1-3 now {line_now:.2f}"
                 + (f"; ETA ~{dates[min(int(eta), n - 1)].date()}" if eta and eta < n else ""))
        signals.append(Signal(ticker, "Bullish Wolfe Wave", status, round(entry, 2), round(stop, 2),
                              round(risk, 2), round(target, 2) if target else None, score,
                              round(float(close[-1]), 2), str(dates[-1].date()), age, vr, desc, notes))
    return _dedupe(signals)


def _dedupe(signals: List[Signal]) -> List[Signal]:
    """Keep the best-scoring signal per (ticker, pattern, status).

    Overlapping pivot combinations often describe the same structure; reporting
    all of them would be noise (and would look like forcing patterns).
    """
    best: dict = {}
    for s in signals:
        key = (s.ticker, s.pattern, s.status)
        if key not in best or s.score > best[key].score:
            best[key] = s
    return list(best.values())


# --------------------------------------------------------------------------- #
# Orchestration & reporting
# --------------------------------------------------------------------------- #
def scan_symbol(sym: str, df: pd.DataFrame) -> List[Signal]:
    """Run all detectors on one symbol, isolating failures per detector.

    :param sym: Symbol.
    :param df: OHLCV DataFrame.
    :returns: Signals from all detectors.
    """
    out: List[Signal] = []
    for fn in (detect_cup_and_handle, detect_inverse_hs, detect_bullish_wolfe):
        try:
            out.extend(fn(df, sym))
        except Exception as exc:  # one bad ticker must not abort the scan
            log.exception("%s failed on %s: %s", fn.__name__, sym, exc)
    return out


def render_markdown(signals: List[Signal], meta: dict) -> str:
    """Render the Markdown report.

    :param signals: All signals.
    :param meta: Run metadata (date, counts, errors).
    :returns: Markdown text.
    """
    lines = [f"# S&P 500 pattern scan — {meta['run_date']}", ""]
    ages = meta.get("max_breakout_age_by_pattern") or {
        p: max_breakout_age(p) for p in BREAKOUT_AGE_LAG}
    age_text = ", ".join(f"{p} {a}" for p, a in ages.items())
    lines.append(f"Scanned {meta['scanned']} of {meta['universe']} symbols "
                 f"(daily bars, last bar {meta.get('last_bar', 'n/a')}). "
                 f"Min quality score {MIN_SCORE}. Breakouts older than the per-pattern "
                 f"limit are dropped (bars: {age_text}; H&S and Wolfe get "
                 f"{PIVOT_ORDER} extra bars because their last pivot is only visible "
                 f"{PIVOT_ORDER} bars after it prints).")
    if meta.get("skipped_bar"):
        lines.append(f"Newest bar {meta['skipped_bar']} not scanned: complete for "
                     f"{meta.get('skipped_bar_complete', 0)} symbols, still missing OHLC at "
                     f"Yahoo for {meta.get('skipped_bar_partial', 0)}.")
    if meta.get("lagging_symbols"):
        lines.append(f"{meta['lagging_symbols']} symbols have no complete bar on "
                     f"{meta.get('last_bar')} and were scanned on their own last bar.")
    if meta.get("errors"):
        lines.append(f"Data errors: {meta['errors']}")
    lines.append("")
    for status, title in (("CONFIRMED", "Confirmed breakouts (actionable)"),
                          ("WATCHLIST", "Watchlist (pattern complete, waiting for a close above trigger)")):
        rows = sorted([s for s in signals if s.status == status], key=lambda s: -s.score)
        lines.append(f"## {title}: {len(rows)}")
        lines.append("")
        if not rows:
            lines.append("_none_")
            lines.append("")
            continue
        lines.append("| Ticker | Pattern | Entry | Stop | Risk % | Target | Score | Vol× | Trend | Details |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for s in rows:
            lines.append(f"| {s.ticker} | {s.pattern} | {s.entry} | {s.stop} | {s.risk_pct} | "
                         f"{s.target if s.target else '-'} | {s.score} | "
                         f"{s.volume_ratio if s.volume_ratio else '-'} | {s.trend} | {s.notes} |")
        lines.append("")
    lines.append("_Heuristic scan, not advice. Entry = trigger level (or breakout close, capped 3% above trigger). "
                 "Stop = structural level minus 0.25 ATR. Verify on a chart before trading._")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point.

    :param argv: Arguments (defaults to ``sys.argv[1:]``).
    :returns: Process exit code (0 = ok, 2 = no data).
    """
    global MIN_SCORE, MAX_BREAKOUT_AGE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default="output")
    ap.add_argument("--tickers", help="comma separated symbols (overrides S&P 500 list)")
    ap.add_argument("--csv", help="local constituents CSV (Symbol column)")
    ap.add_argument("--period", default="2y")
    ap.add_argument("--min-score", type=int, default=MIN_SCORE)
    ap.add_argument("--max-age", type=int, default=MAX_BREAKOUT_AGE)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    MIN_SCORE, MAX_BREAKOUT_AGE = args.min_score, args.max_age

    symbols = ([s.strip().upper() for s in args.tickers.split(",") if s.strip()]
               if args.tickers else load_sp500_symbols(args.csv))
    log.info("universe: %d symbols", len(symbols))
    t0 = time.time()
    data = download_history(symbols, period=args.period)
    log.info("downloaded %d symbols in %.0fs", len(data), time.time() - t0)
    if not data:
        log.error("no price data downloaded")
        return 2

    data, bar_info = align_last_bar(data)
    log.info("last bar %s (%d symbols; %d lagging); newest complete bar per symbol: %s",
             bar_info["last_bar"], bar_info["last_bar_symbols"], bar_info["lagging_symbols"],
             bar_info["last_bar_histogram"])
    if bar_info.get("skipped_bar"):
        log.info("bar %s not scanned: complete for %d symbols, OHLC missing for %d",
                 bar_info["skipped_bar"], bar_info["skipped_bar_complete"],
                 bar_info["skipped_bar_partial"])

    signals: List[Signal] = []
    for sym, df in data.items():
        signals.extend(scan_symbol(sym, df))
    signals.sort(key=lambda s: (s.status != "CONFIRMED", -s.score))

    meta = {"run_date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "universe": len(symbols),
            "scanned": len(data), "errors": len(symbols) - len(data),
            **bar_info,
            "min_score": MIN_SCORE, "max_breakout_age": MAX_BREAKOUT_AGE,
            "max_breakout_age_by_pattern": {p: max_breakout_age(p) for p in BREAKOUT_AGE_LAG}}
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "signals.json"), "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "signals": [asdict(s) for s in signals]}, fh, indent=2)
    md = render_markdown(signals, meta)
    with open(os.path.join(args.out_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
