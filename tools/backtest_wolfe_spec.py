#!/usr/bin/env python3
"""Replay of the 1H Bullish Wolfe Wave specification, with the seven review factors logged per trade.

Why a separate tool
-------------------
The specification under test (2026-09-18) differs from ``scan.detect_bullish_wolfe``
on almost everything around the Wolfe geometry: hourly bars instead of daily, swing
points three bars deep instead of five, a fixed 25-session window, a stop half an ATR
under point 5 instead of a quarter, the point-4 high as the only target instead of
the EPA, a binary exit with a time stop instead of the scanner's listing rules, and
no reward:risk floor.  ``scan.py``'s pipeline (last-bar alignment, the pivot lag, the
evaluator) assumes daily bars, so bending it to the specification would test neither.
This tool implements the specification as written on any yfinance interval, keeps its
own constants block, and records every field of the specification's logging schema
plus the seven factors of the review (volume, RSI divergence, candle body, distance to
TP1, higher-timeframe trend, nearby support, market regime), so their buckets can be
compared the way ``tools/backtest.py`` compares features: a factor earns a rule only
if its buckets separate outcomes.

What it measures
----------------
For every symbol: every triple of consecutive swing lows (1, 3, 5) with the highest
swing highs between them as points 2 and 4, the specification's price and convergence
invariants, point 5 below the extended 1-3 line (the sweep), and the first close back
above that line as the entry, at that bar's close.  Stop = point-5 low minus
``STOP_ATR`` ATR(14) at the entry bar, target = the point-4 high, exit on the first
bar touching either (a bar touching both counts as a stop; gaps fill at the open),
else at the close of the last bar of the holding period.  One position per symbol at
a time.  No reward:risk filter: every trade is logged with its projected R and
reported per R bucket, as the specification asks.

Reading the specification where it is silent
--------------------------------------------
* The entry is never anticipated: the reclaim close counts only from the bar on
  which point 5 is a confirmed swing low (``PIVOT_RIGHT`` bars after it).  A reclaim
  that came earlier is recorded as ``literal_reclaim_lag`` for comparison.
* The reclaim must come within ``MAX_RECLAIM_BARS`` of point 5, and the whole
  structure, point 1 to the entry bar, must fit in the lookback window.
* Point 5 must stay the lowest low until the entry; a deeper low before the reclaim
  is a new point 5 (its own candidate), not this one.
* Nearby support = an earlier swing low, within ``SUPPORT_LOOKBACK`` bars before
  point 1, whose low is within ``SUPPORT_TOL_ATR`` ATR of the point-5 low.
* The 4H trend is read as an EMA of ``HTF_EMA_LEN x HTF_FACTOR`` bars of the base
  interval (an EMA 50 of 4H bars spans 200 hourly bars), which avoids resampling
  hourly bars that do not divide a 6.5-hour session; on daily bars the factor is 5
  (a weekly EMA 50).
* The SPY regime and the VIX are daily readings of the last *completed* session
  before an intraday entry (the session's own close is not known at the time), or
  of the entry day itself on daily bars.
* Yahoo serves intraday bars for the last 730 days only; a longer ``--years`` is
  clamped and the report says so.

Usage::

    python tools/backtest_wolfe_spec.py --interval 1h --years 3 --json out.json --md out.md
    python tools/backtest_wolfe_spec.py --interval 1d --years 3 --tickers AAPL,MSFT

Exit codes: 0 ok, 2 no price data at all.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import scan  # noqa: E402  (the constituent list and its symbol normalisation)

log = logging.getLogger("backtest_wolfe_spec")

# --------------------------------------------------------------------------- #
# Specification parameters (sections 1-3 of the specification), all in one place
# --------------------------------------------------------------------------- #
PIVOT_LEFT = 3                          # a swing high needs this many lower highs before it (strictly) ...
PIVOT_RIGHT = 3                         # ... and after it; swing lows likewise on the lows
WINDOW_BARS = {"1h": 163, "1d": 25}     # 25 sessions: ~163 hourly bars of US regular hours, or 25 daily bars
MAX_HOLD_BARS = {"1h": 78, "1d": 12}    # 12 trading days, the specification's upper bound (~65-80 hourly bars)
MAX_RECLAIM_BARS = 25                   # bars after point 5 in which the reclaim close must come: the specification
#                                         is silent; scan.py's WW_MAX_BARS_SINCE_P5 is the same figure on daily bars
STOP_ATR = 0.5                          # stop = point-5 low minus this many ATR (scan.py: 0.25)
ATR_LEN = 14
RSI_LEN = 14
VOLUME_AVG_LEN = 20                     # the trigger bar's volume against the mean of this many bars before it
HTF_FACTOR = {"1h": 4, "1d": 5}         # base bars per higher-timeframe bar: 4H from 1H, weekly from daily
HTF_EMA_LEN = 50                        # the higher timeframe's EMA length, in higher-timeframe bars
SUPPORT_LOOKBACK = 250                  # bars before point 1 searched for earlier swing lows
SUPPORT_TOL_ATR = 0.5                   # an earlier swing low within this many ATR of the point-5 low is "support"
SPY_SMA_LEN = 50                        # the market regime: SPY's daily close against its SMA of this many sessions
MARKET_INDEX, MARKET_VOL = "SPY", "^VIX"
INTRADAY_MAX_DAYS = 729                 # Yahoo serves intraday bars for the last 730 days only
DAILY_INTERVALS = ("1d", "5d", "1wk", "1mo", "3mo")
MIN_BARS = 60                           # a symbol with fewer bars than this is skipped (indicator warm-up)
EXIT_REASONS = ("TP1", "SL", "TIME_EXIT", "OPEN")
FUNNEL_KEYS = ("symbols", "structures", "no_sweep", "undercut", "no_reclaim", "reclaimed", "no_room",
               "position_open", "trades")
INF = float("inf")
# Report buckets.  Numeric: key -> (label, right-inclusive edges, bucket names); the volume and VIX edges are
# tools/backtest.py's, so the two replays can be read side by side.  Categorical: key -> (label, values).
NUMERIC_FACTORS: Dict[str, Tuple[str, Sequence[float], Sequence[str]]] = {
    "projected_RR": ("4. Distance to TP1: projected reward:risk", (-INF, 1.0, 1.5, 2.0, INF),
                     ("< 1.0 R", "1.0-1.5 R", "1.5-2.0 R", "> 2.0 R")),
    "volume_ratio": ("1. Volume: trigger bar over the 20-bar average", (-INF, 0.8, 1.0, 1.3, 2.0, INF),
                     ("<= 0.8x", "0.8-1.0x", "1.0-1.3x", "1.3-2.0x", "> 2.0x")),
    "body_ratio": ("3. Candle: body over range of the trigger bar", (-INF, 0.3, 0.6, INF),
                   ("<= 0.3", "0.3-0.6", "> 0.6")),
    "vix": ("7. Market volatility: VIX at the last completed session", (-INF, 15.0, 20.0, 25.0, INF),
            ("<= 15", "15-20", "20-25", "> 25")),
}
CATEGORICAL_FACTORS: Dict[str, Tuple[str, Sequence[str]]] = {
    "rsi_divergence": ("2. RSI divergence: RSI 14 at point 5 above RSI 14 at point 3", ("yes", "no")),
    "htf_trend_4h": ("5. Higher timeframe trend: close against the higher-timeframe EMA 50", ("Bullish", "Bearish")),
    "nearby_support": ("6. Nearby support: an earlier swing low within 0.5 ATR of point 5", ("yes", "no")),
    "market_regime_spy": ("7. Market regime: SPY against its daily SMA 50", ("Above_SMA50", "Below_SMA50")),
}


@dataclass
class Params:
    """The replay's tunables for one interval; ``for_interval`` fills the per-interval defaults above."""

    interval: str = "1h"
    window_bars: int = 163
    max_hold_bars: int = 78
    max_reclaim_bars: int = MAX_RECLAIM_BARS
    stop_atr: float = STOP_ATR
    pivot_left: int = PIVOT_LEFT
    pivot_right: int = PIVOT_RIGHT
    htf_factor: int = 4

    @classmethod
    def for_interval(cls, interval: str, **overrides: Any) -> "Params":
        """Defaults for ``interval`` (an unlisted intraday interval takes the 1h family, a daily one the 1d
        family), then every override that is not ``None``."""
        family = "1d" if not is_intraday(interval) else "1h"
        values: Dict[str, Any] = {"interval": interval, "window_bars": WINDOW_BARS.get(interval, WINDOW_BARS[family]),
                                  "max_hold_bars": MAX_HOLD_BARS.get(interval, MAX_HOLD_BARS[family]),
                                  "htf_factor": HTF_FACTOR.get(interval, HTF_FACTOR[family])}
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)


def is_intraday(interval: str) -> bool:
    """Whether a yfinance interval is shorter than a session (Yahoo limits those to the last 730 days)."""
    return interval not in DAILY_INTERVALS


# --------------------------------------------------------------------------- #
# Indicators (positional, one value per bar)
# --------------------------------------------------------------------------- #
def atr_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = ATR_LEN) -> np.ndarray:
    """Average True Range as a simple rolling mean of the true range (``min_periods=1``, like ``scan.atr``).

    :returns: One value per bar; bar 0 is High - Low.  Complexity: O(bars).
    """
    prev = np.concatenate([[np.nan], close[:-1]])
    tr = np.nanmax(np.vstack([high - low, np.abs(high - prev), np.abs(low - prev)]), axis=0)
    return pd.Series(tr).rolling(n, min_periods=1).mean().to_numpy(dtype=float)


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    """RSI from the smoothed averages: 50 on a series that never moved, 100 without losses."""
    if avg_gain == 0 and avg_loss == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def rsi_series(close: np.ndarray, n: int = RSI_LEN) -> np.ndarray:
    """Wilder's RSI per bar: an ``n``-bar simple seed, then ``(n - 1) / n`` smoothing.

    The last value equals ``scan._rsi`` (before its rounding), so the review's RSI reads the same
    oscillator the report's F&G column does.

    :returns: NaN for the first ``n`` bars, then 0-100.  Complexity: O(bars).
    """
    out = np.full(len(close), np.nan)
    if len(close) < n + 1:
        return out
    delta = np.diff(np.asarray(close, dtype=float))
    gains, losses = np.clip(delta, 0.0, None), np.clip(-delta, 0.0, None)
    avg_gain, avg_loss = float(gains[:n].mean()), float(losses[:n].mean())
    out[n] = _rsi_value(avg_gain, avg_loss)
    for i in range(n, len(delta)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
        out[i + 1] = _rsi_value(avg_gain, avg_loss)
    return out


def ema_series(close: np.ndarray, span: int) -> np.ndarray:
    """Exponential moving average (``adjust=False``), NaN until ``span`` bars exist, where it is still settling."""
    ema = np.array(pd.Series(np.asarray(close, dtype=float)).ewm(span=span, adjust=False).mean(), dtype=float)
    ema[:min(span - 1, len(ema))] = np.nan     # a copy: pandas 3 hands out read-only views
    return ema


# --------------------------------------------------------------------------- #
# Section 2: swing points and the five-point structure
# --------------------------------------------------------------------------- #
def _strict_extrema(x: np.ndarray, left: int, right: int, better: Callable[..., np.ndarray]) -> List[int]:
    """Bars strictly ``better`` than each of the ``left`` bars before and the ``right`` bars after them."""
    n = len(x)
    ok = np.ones(n, dtype=bool)
    for k in range(1, left + 1):
        ok[k:] &= better(x[k:], x[:-k])
        ok[:k] = False
    for k in range(1, right + 1):
        ok[:-k] &= better(x[:-k], x[k:])
        ok[n - k:] = False
    return [int(i) for i in np.flatnonzero(ok)]


def swing_points(high: np.ndarray, low: np.ndarray, left: int = PIVOT_LEFT, right: int = PIVOT_RIGHT
                 ) -> Tuple[List[int], List[int]]:
    """Swing highs and lows under the specification's rule: ``left`` lower highs before and ``right`` after
    (higher lows for a swing low), strictly.

    Strict, because that is what the specification's prose says; its code sketch (a rolling-max
    equality) would also mark every bar of a flat stretch.  The last ``right`` bars can never be
    swing points, which is what keeps the rule from repainting.

    :returns: ``(swing_high_indices, swing_low_indices)``.  Complexity: O(bars x (left + right)), vectorised.
    """
    high, low = np.asarray(high, dtype=float), np.asarray(low, dtype=float)
    return _strict_extrema(high, left, right, np.greater), _strict_extrema(low, left, right, np.less)


@dataclass
class Setup:
    """A five-point structure that passes the specification's invariants: bar indices and the prices at them
    (lows at 1, 3, 5; highs at 2, 4)."""

    p1: int
    p2: int
    p3: int
    p4: int
    p5: int
    v1: float
    v2: float
    v3: float
    v4: float
    v5: float

    @property
    def s13(self) -> float:
        """Slope of line 1-3 per bar (negative)."""
        return (self.v3 - self.v1) / (self.p3 - self.p1)

    @property
    def s24(self) -> float:
        """Slope of line 2-4 per bar (negative, steeper than :attr:`s13`)."""
        return (self.v4 - self.v2) / (self.p4 - self.p2)

    def line13(self, idx: int) -> float:
        """The extended 1-3 line at bar ``idx``."""
        return self.v1 + self.s13 * (idx - self.p1)


def wolfe_geometry_ok(v1: float, v2: float, v3: float, v4: float, v5: float,
                      p1: int, p2: int, p3: int, p4: int) -> bool:
    """Section 2's price and convergence invariants.

    ``High(P2) > High(P4) > Low(P1) > Low(P3) > Low(P5)`` (point 4 overlaps the 1-2 range, the lows
    step down); both lines fall (``m24 < 0``, ``m13 < 0``) and the upper one faster (``|m24| > |m13|``),
    so they converge ahead.
    """
    if not (v2 > v4 > v1 > v3 > v5):
        return False
    m24 = (v4 - v2) / (p4 - p2)
    m13 = (v3 - v1) / (p3 - p1)
    return m24 < 0 and m13 < 0 and abs(m24) > abs(m13)


def _setups_from_pivots(high: np.ndarray, low: np.ndarray, piv_h: Sequence[int], piv_l: Sequence[int],
                        window_bars: int) -> List[Setup]:
    highs = np.asarray(piv_h, dtype=int)
    out: List[Setup] = []
    for i in range(len(piv_l) - 2):
        p1, p3, p5 = piv_l[i], piv_l[i + 1], piv_l[i + 2]
        if p5 - p1 > window_bars:
            continue
        c2 = highs[(highs > p1) & (highs < p3)]
        c4 = highs[(highs > p3) & (highs < p5)]
        if len(c2) == 0 or len(c4) == 0:
            continue
        p2 = int(c2[np.argmax(high[c2])])
        p4 = int(c4[np.argmax(high[c4])])
        v = (float(low[p1]), float(high[p2]), float(low[p3]), float(high[p4]), float(low[p5]))
        if not wolfe_geometry_ok(*v, p1, p2, p3, p4):
            continue
        out.append(Setup(p1, p2, p3, p4, p5, *v))
    return out


def wolfe_setups(high: np.ndarray, low: np.ndarray, window_bars: int, left: int = PIVOT_LEFT,
                 right: int = PIVOT_RIGHT) -> List[Setup]:
    """Every structure of three consecutive swing lows (1, 3, 5) with the highest swing highs strictly between
    them (2, 4) that passes :func:`wolfe_geometry_ok` and spans at most ``window_bars`` from point 1 to point 5.

    Consecutive, because the five points of a Wolfe Wave are consecutive alternating swings (the
    reading ``scan.detect_bullish_wolfe`` takes too); the window is checked again, up to the entry bar,
    by :func:`find_trigger`.  Complexity: O(swing lows x swing highs) with numpy masks.
    """
    piv_h, piv_l = swing_points(high, low, left, right)
    return _setups_from_pivots(np.asarray(high, dtype=float), np.asarray(low, dtype=float), piv_h, piv_l, window_bars)


# --------------------------------------------------------------------------- #
# Section 3: the sweep, the reclaim, the levels and the exit
# --------------------------------------------------------------------------- #
def find_trigger(setup: Setup, close: np.ndarray, low: np.ndarray, window_bars: int, max_reclaim: int,
                 right: int = PIVOT_RIGHT) -> Tuple[Optional[int], Optional[int], str]:
    """The sweep (point 5's low below the 1-3 line) and the reclaim (the first close back above it).

    :returns: ``(entry_bar, literal_reclaim_bar, reason)``.  ``entry_bar`` is the first bar, no earlier
        than the one that confirms point 5 as a swing low (``right`` bars after it), whose close is above
        the 1-3 line, within ``max_reclaim`` bars of point 5 and with the structure inside ``window_bars``
        from point 1; ``None`` with the reason ``no_sweep`` (point 5 never broke the line), ``undercut``
        (a lower low before the reclaim, which makes that low the structure's point 5) or ``no_reclaim``.
        ``literal_reclaim_bar`` is the first close above the line after point 5 regardless of confirmation,
        the specification's literal trigger, kept for comparison.  Complexity: O(max_reclaim).
    """
    p5, n = setup.p5, len(close)
    if not low[p5] < setup.line13(p5):
        return None, None, "no_sweep"
    last = min(p5 + max_reclaim, setup.p1 + window_bars, n - 1)
    literal = next((t for t in range(p5 + 1, last + 1) if close[t] > setup.line13(t)), None)
    for t in range(p5 + 1, last + 1):
        if low[t] < low[p5]:
            return None, literal, "undercut"
        if t >= p5 + right and close[t] > setup.line13(t):
            return t, literal, "trigger"
    return None, literal, "no_reclaim"


def _exit(reason: str, bars: int, price: float, entry: float, risk: float) -> Dict[str, Any]:
    return {"exit_reason": reason, "bars_held": bars, "exit_price": round(price, 4),
            "realized_R": round((price - entry) / risk, 4) if risk > 0 else None}


def simulate(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, entry_bar: int,
             entry: float, stop: float, tp1: float, max_hold: int) -> Dict[str, Any]:
    """Section 1's trade management from the bar after the entry: the first bar whose low touches the stop
    exits at the stop (or at the open, when it gapped below), else the first bar whose high reaches TP1
    exits at TP1 (or at a higher open); a bar touching both is a stop, the conservative reading; with
    neither by ``max_hold`` bars the trade exits at that bar's close (``TIME_EXIT``), and ``OPEN`` marks
    a trade the history ends on, at the last close.

    :returns: ``exit_reason``, ``bars_held``, ``exit_price``, ``realized_R`` (``(exit - entry) / (entry - stop)``).
        Complexity: O(max_hold).
    """
    n = len(close)
    risk = entry - stop
    last = entry_bar + max_hold
    for k in range(entry_bar + 1, min(last, n - 1) + 1):
        if low[k] <= stop:
            return _exit("SL", k - entry_bar, min(float(open_[k]), stop), entry, risk)
        if high[k] >= tp1:
            return _exit("TP1", k - entry_bar, max(float(open_[k]), tp1), entry, risk)
    if last <= n - 1:
        return _exit("TIME_EXIT", max_hold, float(close[last]), entry, risk)
    return _exit("OPEN", n - 1 - entry_bar, float(close[-1]), entry, risk)


# --------------------------------------------------------------------------- #
# Section 4: the logging schema and the review's seven factors
# --------------------------------------------------------------------------- #
def _num(x: Any, nd: int = 4) -> Optional[float]:
    """A JSON-safe rounded float, ``None`` for NaN / None."""
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else round(x, nd)


def body_ratio(open_: float, high: float, low: float, close: float) -> Optional[float]:
    """``|Close - Open| / (High - Low)`` of a bar; ``None`` when the bar has no range."""
    rng = high - low
    return None if not rng > 0 else _num(abs(close - open_) / rng, 3)


def volume_ratio(vol: np.ndarray, idx: int, n: int = VOLUME_AVG_LEN) -> Optional[float]:
    """Volume on bar ``idx`` over the mean of the ``n`` bars before it (NaN-free), ``None`` without ``n`` prior bars."""
    if idx < n or np.isnan(vol[idx]):
        return None
    base = vol[idx - n:idx]
    base = base[~np.isnan(base)]
    if len(base) == 0 or base.mean() <= 0:
        return None
    return _num(vol[idx] / base.mean(), 3)


def support_touches(low: np.ndarray, swing_lows: Sequence[int], setup: Setup, tol: float,
                    lookback: int = SUPPORT_LOOKBACK) -> int:
    """Earlier swing lows, within ``lookback`` bars before point 1, whose low is within ``tol`` of the point-5 low."""
    lo = setup.p1 - lookback
    return sum(1 for q in swing_lows if lo <= q < setup.p1 and abs(float(low[q]) - setup.v5) <= tol)


def daily_context(spy: Optional[pd.DataFrame], vix: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Per-session SPY close, its SMA ``SPY_SMA_LEN`` and the VIX close on naive dates, for :func:`market_at`."""
    parts: Dict[str, pd.Series] = {}
    if spy is not None and len(spy):
        c = _naive_daily(spy)["Close"]
        parts["spy_close"] = c
        parts["spy_sma50"] = c.rolling(SPY_SMA_LEN, min_periods=SPY_SMA_LEN).mean()
    if vix is not None and len(vix):
        parts["vix"] = _naive_daily(vix)["Close"]
    return pd.DataFrame(parts).sort_index() if parts else pd.DataFrame()


def _naive_daily(df: pd.DataFrame) -> pd.DataFrame:
    """A daily frame indexed by naive, normalised dates (Yahoo's daily index is tz-aware in recent yfinance)."""
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    out = df.copy()
    out.index = idx.normalize()
    return out[~out.index.duplicated(keep="last")].sort_index()


def market_at(ctx: Optional[pd.DataFrame], ts: Any, intraday: bool) -> Dict[str, Any]:
    """The market fields of a trade entered at ``ts``: the last completed session before the entry's day on an
    intraday interval (that day's close is not known at the entry), the entry day itself on daily bars.

    :returns: ``market_regime_spy`` (``Above_SMA50`` / ``Below_SMA50``), ``spy_close``, ``spy_sma50``, ``vix``,
        ``market_date``; all ``None`` without context.
    """
    out: Dict[str, Any] = {"market_regime_spy": None, "spy_close": None, "spy_sma50": None, "vix": None,
                           "market_date": None}
    if ctx is None or ctx.empty:
        return out
    day = pd.Timestamp(ts).normalize()
    cutoff = day - pd.Timedelta(days=1) if intraday else day
    sub = ctx[ctx.index <= cutoff]
    if sub.empty:
        return out
    row = sub.iloc[-1]
    out["market_date"] = str(sub.index[-1].date())
    for k in ("spy_close", "spy_sma50", "vix"):
        out[k] = _num(row.get(k), 2) if k in row.index else None
    if out["spy_close"] is not None and out["spy_sma50"] is not None:
        out["market_regime_spy"] = "Above_SMA50" if out["spy_close"] > out["spy_sma50"] else "Below_SMA50"
    return out


def rr_bucket(rr: float) -> str:
    """The specification's projected-R buckets: ``< 1.0 R``, ``1.0-1.5 R``, ``1.5-2.0 R``, ``> 2.0 R``."""
    _, edges, names = NUMERIC_FACTORS["projected_RR"]
    for lo, hi, name in zip(edges[:-1], edges[1:], names):
        if lo < rr <= hi:
            return name
    return names[-1]


# --------------------------------------------------------------------------- #
# The replay: one symbol, then the universe
# --------------------------------------------------------------------------- #
def replay_symbol(sym: str, df: pd.DataFrame, p: Params, ctx: Optional[pd.DataFrame] = None
                  ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Every trade the specification takes on one symbol's bars, with the logging schema filled in.

    Candidates are ordered by entry bar; while a position is open the later triggers on the same
    symbol are skipped and counted (``position_open``).

    :param sym: Symbol, for the rows.
    :param df: OHLCV bars, oldest first, naive timestamps.
    :param p: The interval's parameters.
    :param ctx: :func:`daily_context` output for the market fields (optional).
    :returns: ``(rows, funnel)``: the trades, and the counts of every stage a structure can stop at.
        Complexity: O(bars x pivot depth) for the swing points plus O(structures x reclaim window).
    """
    funnel = dict.fromkeys(FUNNEL_KEYS, 0)
    n = len(df)
    if n < MIN_BARS:
        return [], funnel
    funnel["symbols"] = 1
    open_, high, low, close = (df[c].to_numpy(dtype=float) for c in ("Open", "High", "Low", "Close"))
    vol = df["Volume"].to_numpy(dtype=float) if "Volume" in df.columns else np.full(n, np.nan)
    atr = atr_series(high, low, close)
    rsi = rsi_series(close)
    ema = ema_series(close, HTF_EMA_LEN * p.htf_factor)
    piv_h, piv_l = swing_points(high, low, p.pivot_left, p.pivot_right)
    setups = _setups_from_pivots(high, low, piv_h, piv_l, p.window_bars)
    funnel["structures"] = len(setups)
    candidates: List[Tuple[int, Setup, float, float, float, float, Optional[int]]] = []
    for s in setups:
        t, literal, reason = find_trigger(s, close, low, p.window_bars, p.max_reclaim_bars, p.pivot_right)
        if t is None:
            funnel[reason] += 1
            continue
        funnel["reclaimed"] += 1
        entry, a = float(close[t]), float(atr[t])
        stop, tp1 = s.v5 - p.stop_atr * a, s.v4
        if not (stop < entry < tp1):        # an entry already at or above TP1, or a stop at or above the entry: no R
            funnel["no_room"] += 1
            continue
        candidates.append((t, s, entry, stop, tp1, a, literal))
    candidates.sort(key=lambda c: (c[0], c[1].p5))
    rows: List[Dict[str, Any]] = []
    busy_until = -1
    intraday = is_intraday(p.interval)
    for t, s, entry, stop, tp1, a, literal in candidates:
        if t <= busy_until:
            funnel["position_open"] += 1
            continue
        res = simulate(open_, high, low, close, t, entry, stop, tp1, p.max_hold_bars)
        busy_until = t + res["bars_held"]
        ts = pd.Timestamp(df.index[t])
        rsi3, rsi5 = float(rsi[s.p3]), float(rsi[s.p5])
        ema_t = float(ema[t])
        touches = support_touches(low, piv_l, s, SUPPORT_TOL_ATR * a) if a > 0 else 0
        row: Dict[str, Any] = {
            # setup metadata
            "symbol": sym, "trigger_time": str(ts), "trigger_date": str(ts.date()), "year": int(ts.year),
            "bars_P1_to_P5": s.p5 - s.p1, "reclaim_lag": t - s.p5,
            "literal_reclaim_lag": None if literal is None else literal - s.p5,
            # price points
            "p1_price": _num(s.v1), "p2_price": _num(s.v2), "p3_price": _num(s.v3), "p4_price": _num(s.v4),
            "p5_low": _num(s.v5), "sweep_depth_atr": _num((s.line13(s.p5) - s.v5) / a, 3) if a > 0 else None,
            # trade boundaries
            "entry_price": _num(entry), "stop_loss": _num(stop), "tp1_target": _num(tp1), "atr14": _num(a),
            "projected_RR": _num((tp1 - entry) / (entry - stop), 3),
            # confirmations
            "body_ratio": body_ratio(float(open_[t]), float(high[t]), float(low[t]), float(close[t])),
            "volume_ratio": volume_ratio(vol, t),
            "rsi_p3": _num(rsi3, 2), "rsi_p5": _num(rsi5, 2),
            "rsi_divergence": None if math.isnan(rsi3) or math.isnan(rsi5) else bool(rsi5 > rsi3),
            # market regime
            "htf_trend_4h": None if math.isnan(ema_t) else ("Bullish" if entry > ema_t else "Bearish"),
            "htf_ema": _num(ema_t),
            "support_touches": touches, "nearby_support": touches >= 1,
            **market_at(ctx, ts, intraday),
            # trade outcome
            **res,
        }
        row["rr_bucket"] = rr_bucket(row["projected_RR"])
        rows.append(row)
        funnel["trades"] += 1
    return rows, funnel


def replay(data: Mapping[str, pd.DataFrame], p: Params, ctx: Optional[pd.DataFrame] = None
           ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """:func:`replay_symbol` over a universe; rows ordered by entry time, funnel counts summed."""
    rows: List[Dict[str, Any]] = []
    funnel = dict.fromkeys(FUNNEL_KEYS, 0)
    for sym in sorted(data):
        r, f = replay_symbol(sym, data[sym], p, ctx)
        rows.extend(r)
        for k, v in f.items():
            funnel[k] += v
    rows.sort(key=lambda r: (r["trigger_time"], r["symbol"]))
    return rows, funnel


# --------------------------------------------------------------------------- #
# Statistics and tables
# --------------------------------------------------------------------------- #
def summarise(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Counts per exit reason, the win rate (TP1 over closed trades), the hit rate (TP1 against SL only) and
    the R statistics over closed trades (open ones are neither wins nor losses yet).

    :returns: ``trades``, ``TP1``, ``SL``, ``TIME_EXIT``, ``OPEN``, ``closed``, ``win_rate``, ``hit_rate``,
        ``mean_r``, ``median_r``, ``total_r`` (rates and R ``None`` when undefined).
    """
    counts = {k: sum(1 for r in rows if r["exit_reason"] == k) for k in EXIT_REASONS}
    closed = counts["TP1"] + counts["SL"] + counts["TIME_EXIT"]
    resolved = counts["TP1"] + counts["SL"]
    rs = [float(r["realized_R"]) for r in rows if r["exit_reason"] != "OPEN" and r["realized_R"] is not None]
    return {"trades": len(rows), **counts, "closed": closed,
            "win_rate": round(counts["TP1"] / closed, 4) if closed else None,
            "hit_rate": round(counts["TP1"] / resolved, 4) if resolved else None,
            "mean_r": round(sum(rs) / len(rs), 3) if rs else None,
            "median_r": round(float(np.median(rs)), 3) if rs else None,
            "total_r": round(sum(rs), 2) if rs else None}


def numeric_buckets(rows: Sequence[Mapping[str, Any]], key: str, edges: Sequence[float], names: Sequence[str]
                    ) -> List[Dict[str, Any]]:
    """:func:`summarise` per right-inclusive bucket of a numeric field, plus an ``n/a`` row for missing values."""
    out = []
    for lo, hi, name in zip(edges[:-1], edges[1:], names):
        sub = [r for r in rows if r.get(key) is not None and lo < float(r[key]) <= hi]
        out.append({"bucket": name, **summarise(sub)})
    missing = [r for r in rows if r.get(key) is None]
    if missing:
        out.append({"bucket": "n/a", **summarise(missing)})
    return out


def categorical_buckets(rows: Sequence[Mapping[str, Any]], key: str, values: Sequence[str]) -> List[Dict[str, Any]]:
    """:func:`summarise` per value of a categorical field (booleans read as ``yes`` / ``no``), plus ``n/a``."""
    def label(v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, (bool, np.bool_)):
            return "yes" if v else "no"
        return str(v)

    out = [{"bucket": name, **summarise([r for r in rows if label(r.get(key)) == name])} for name in values]
    missing = [r for r in rows if label(r.get(key)) is None]
    if missing:
        out.append({"bucket": "n/a", **summarise(missing)})
    return out


def by_year(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """:func:`summarise` per calendar year of the entry."""
    years = sorted({int(r["year"]) for r in rows})
    return [{"bucket": str(y), **summarise([r for r in rows if int(r["year"]) == y])} for y in years]


def tables(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Every table of the report: the R buckets, one per review factor, the years."""
    factors: Dict[str, Any] = {}
    for key, (label, edges, names) in NUMERIC_FACTORS.items():
        factors[key] = {"label": label, "rows": numeric_buckets(rows, key, edges, names)}
    for key, (label, values) in CATEGORICAL_FACTORS.items():
        factors[key] = {"label": label, "rows": categorical_buckets(rows, key, values)}
    return {"factors": factors, "years": by_year(rows)}


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #
def _pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{100 * x:.1f} %"


def _r(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:+.2f}"


OUTCOME_COLUMNS = "| Trades | TP1 | SL | Time exit | Open | Win rate | TP1 vs SL | Mean R | Median R | Total R |"


def _outcome_line(name: str, s: Mapping[str, Any]) -> str:
    return (f"| {name} | {s['trades']} | {s['TP1']} | {s['SL']} | {s['TIME_EXIT']} | {s['OPEN']} | "
            f"{_pct(s['win_rate'])} | {_pct(s['hit_rate'])} | {_r(s['mean_r'])} | {_r(s['median_r'])} | "
            f"{_r(s['total_r'])} |")


def _table(label: str, table_rows: Sequence[Mapping[str, Any]]) -> List[str]:
    return [f"### {label}", "", "| Bucket " + OUTCOME_COLUMNS,
            "|---|---|---|---|---|---|---|---|---|---|---|"] + \
           [_outcome_line(t["bucket"], t) for t in table_rows] + [""]


def rules_line(p: Params) -> str:
    """One sentence stating the rules as replayed, so a report is self-describing."""
    return (f"Rules: swing points {p.pivot_left} bars before and {p.pivot_right} after, strictly; the structure "
            f"within {p.window_bars} bars from point 1 to the entry; "
            f"High(P2) > High(P4) > Low(P1) > Low(P3) > Low(P5); both lines falling, 2-4 faster; point 5's low "
            f"below line 1-3; entry at the first close back above line 1-3, no earlier than the bar that confirms "
            f"point 5 and within {p.max_reclaim_bars} bars of it; stop at the point-5 low minus {p.stop_atr} "
            f"ATR {ATR_LEN}; target the point-4 high; exit at the stop or the target (a bar touching both is a "
            f"stop; gaps fill at the open), else at the close {p.max_hold_bars} bars after the entry; one position "
            f"per symbol; no reward:risk filter.")


def render(rows: Sequence[Mapping[str, Any]], funnel: Mapping[str, int], p: Params, meta: Mapping[str, Any]) -> str:
    """The Markdown report: coverage, rules, the funnel, the headline win rate, then the tables."""
    s = summarise(rows)
    tb = tables(rows)
    lines = [f"# Bullish Wolfe Wave specification replay: {p.interval} bars, {meta.get('first_bar', '?')} to "
             f"{meta.get('last_bar', '?')}", "",
             f"Universe: {meta.get('symbols_requested', '?')} symbols requested, {funnel['symbols']} replayed "
             f"(at least {MIN_BARS} bars); {meta.get('bars_median', '?')} bars per symbol (median). Data from "
             f"{meta.get('start_effective', '?')}" + (
                 f" ({meta['start_requested']} requested: Yahoo serves intraday bars for the last "
                 f"{INTRADAY_MAX_DAYS + 1} days only)." if meta.get("clamped") else "."), "",
             rules_line(p), "", "## Funnel", "",
             "| Structures (geometry) | Point 5 below line 1-3 | Reclaimed in time | Room for a trade | "
             "Skipped, position open | Trades |", "|---|---|---|---|---|---|",
             f"| {funnel['structures']} | {funnel['structures'] - funnel['no_sweep']} | {funnel['reclaimed']} | "
             f"{funnel['reclaimed'] - funnel['no_room']} | {funnel['position_open']} | {funnel['trades']} |", "",
             f"Of the structures that swept the line, {funnel['undercut']} made a lower low before any reclaim and "
             f"{funnel['no_reclaim']} never closed back above it in time.", "", "## Outcome", ""]
    if s["closed"]:
        lines.append(f"**TP1 was hit {s['TP1']} times in {s['closed']} closed trades: win rate "
                     f"{_pct(s['win_rate'])}.** {s['SL']} stopped out, {s['TIME_EXIT']} timed out after "
                     f"{p.max_hold_bars} bars, {s['OPEN']} still open when the data ends. Mean R {_r(s['mean_r'])} "
                     f"per closed trade, {_r(s['total_r'])} R in total.")
    else:
        lines.append("**No closed trade.**")
    lines += ["", "| Slice " + OUTCOME_COLUMNS, "|---|---|---|---|---|---|---|---|---|---|---|",
              _outcome_line("all", s), "", "## By review factor", "",
              "Trades bucketed by each factor measured at the entry; a factor earns a rule only if its buckets "
              "separate outcomes by more than chance would, on both halves of a split.", ""]
    for key in list(NUMERIC_FACTORS) + list(CATEGORICAL_FACTORS):
        lines += _table(tb["factors"][key]["label"], tb["factors"][key]["rows"])
    lines += ["## By year", ""] + _table("Entries per calendar year", tb["years"])[2:]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def history_start(years: float, interval: str, today: Optional[pd.Timestamp] = None
                  ) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """``(requested_start, effective_start)`` for ``years`` of history: the effective start is clamped to
    ``INTRADAY_MAX_DAYS`` before today on an intraday interval."""
    today = (pd.Timestamp.today() if today is None else pd.Timestamp(today)).normalize()
    requested = today - pd.Timedelta(days=round(365.25 * years))
    limit = today - pd.Timedelta(days=INTRADAY_MAX_DAYS)
    return requested, (max(requested, limit) if is_intraday(interval) else requested)


def clean_frame(df: Optional[pd.DataFrame], interval: str) -> Optional[pd.DataFrame]:
    """OHLC(V) rows with a complete bar, on naive New York timestamps (dates on a daily interval), de-duplicated
    and sorted; ``None`` when the frame is unusable or shorter than ``MIN_BARS``."""
    if df is None or df.empty or not {"Open", "High", "Low", "Close"} <= set(df.columns):
        return None
    cols = ["Open", "High", "Low", "Close"] + (["Volume"] if "Volume" in df.columns else [])
    out = df[cols].dropna(subset=["Open", "High", "Low", "Close"]).copy()
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    out.index = idx if is_intraday(interval) else idx.normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out if len(out) >= MIN_BARS else None


def _fetch_one(sym: str, interval: str, start: pd.Timestamp, retries: int = 3) -> Optional[pd.DataFrame]:
    """One symbol's raw history from yfinance, retried on transient errors (5 s, then 10 s, like ``scan``);
    a "delisted" / "no data" answer is final."""
    import yfinance as yf  # imported lazily so tests can run without it

    try:  # make yfinance raise instead of logging + returning an empty frame
        yf.config.debug.hide_exceptions = False
    except Exception:
        pass
    tkr = yf.Ticker(sym)
    for attempt in range(retries):
        try:
            return tkr.history(start=start.strftime("%Y-%m-%d"), interval=interval, auto_adjust=True,
                               actions=False, prepost=False)
        except Exception as exc:
            msg = str(exc)
            if "delisted" in msg.lower() or "no data" in msg.lower() or "Missing" in type(exc).__name__:
                log.warning("%s: no data (%s)", sym, msg.splitlines()[0][:120])
                return None
            log.warning("%s attempt %d failed: %s", sym, attempt, msg.splitlines()[0][:120])
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
    return None


def fetch_history(symbols: Sequence[str], interval: str, start: pd.Timestamp, workers: int = 8,
                  cache_dir: Optional[str] = None) -> Dict[str, pd.DataFrame]:
    """Cleaned bars per symbol, downloaded in parallel; with ``cache_dir`` each symbol's frame is kept as a
    pickle keyed by interval and start date, so a re-run with the same window is offline."""
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)

    def one(sym: str) -> Tuple[str, Optional[pd.DataFrame]]:
        path = os.path.join(cache_dir, f"{sym.replace('^', '_')}_{interval}_{start.date()}.pkl") if cache_dir else None
        if path and os.path.exists(path):
            return sym, pd.read_pickle(path)
        df = clean_frame(_fetch_one(sym, interval, start), interval)
        if df is not None and path:
            df.to_pickle(path)
        return sym, df

    out: Dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for sym, df in pool.map(one, symbols):
            if df is not None:
                out[sym] = df
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay the 1H Bullish Wolfe Wave specification and report its win rate.")
    ap.add_argument("--interval", default="1h", help="yfinance interval (default 1h; 1d for the daily variant)")
    ap.add_argument("--years", type=float, default=3.0, help="years of history (intraday: at most 730 days)")
    ap.add_argument("--tickers", help="comma separated symbols (default: the S&P 500 constituents)")
    ap.add_argument("--csv", help="local constituents CSV with a Symbol column")
    ap.add_argument("--limit", type=int, help="replay only the first N symbols (smoke tests)")
    ap.add_argument("--workers", type=int, default=8, help="parallel downloads (default 8)")
    ap.add_argument("--cache-dir", help="keep each symbol's bars as a pickle here and reuse them")
    ap.add_argument("--no-market", action="store_true", help="skip the SPY / VIX context download")
    ap.add_argument("--window-bars", type=int, help=f"override the lookback window (default {WINDOW_BARS})")
    ap.add_argument("--max-hold-bars", type=int, help=f"override the holding period (default {MAX_HOLD_BARS})")
    ap.add_argument("--max-reclaim-bars", type=int, help=f"override the reclaim window (default {MAX_RECLAIM_BARS})")
    ap.add_argument("--stop-atr", type=float, help=f"override the stop's ATR cushion (default {STOP_ATR})")
    ap.add_argument("--json", help="also write the rows, funnel, summary and tables here")
    ap.add_argument("--md", help="also write the Markdown report here")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.tickers:
        symbols = [s.strip().upper() for s in args.tickers.split(",") if s.strip()]
    else:
        symbols = scan.load_sp500_symbols(args.csv)
    if args.limit:
        symbols = symbols[:args.limit]
    requested, start = history_start(args.years, args.interval)
    clamped = start != requested
    if clamped:
        log.warning("intraday history is limited to the last %d days: %s requested, %s used",
                    INTRADAY_MAX_DAYS + 1, requested.date(), start.date())
    p = Params.for_interval(args.interval, window_bars=args.window_bars, max_hold_bars=args.max_hold_bars,
                            max_reclaim_bars=args.max_reclaim_bars, stop_atr=args.stop_atr)
    t0 = time.time()
    data = fetch_history(symbols, args.interval, start, args.workers, args.cache_dir)
    if not data:
        print("no price data")
        return 2
    log.info("downloaded %d of %d symbols in %.0fs", len(data), len(symbols), time.time() - t0)
    ctx = pd.DataFrame()
    if not args.no_market:
        try:  # informational context: a failure leaves the market fields empty, never stops the replay
            frames = fetch_history([MARKET_INDEX, MARKET_VOL], "1d", start - pd.Timedelta(days=120), 2, args.cache_dir)
            ctx = daily_context(frames.get(MARKET_INDEX), frames.get(MARKET_VOL))
        except Exception as exc:
            log.warning("market context unavailable: %s", exc)
    rows, funnel = replay(data, p, ctx)
    first = min(df.index[0] for df in data.values())
    last = max(df.index[-1] for df in data.values())
    meta = {"interval": args.interval, "years": args.years, "start_requested": str(requested.date()),
            "start_effective": str(start.date()), "clamped": clamped, "symbols_requested": len(symbols),
            "symbols_with_data": len(data), "first_bar": str(first), "last_bar": str(last),
            "bars_median": int(np.median([len(df) for df in data.values()])), "market_context": not ctx.empty,
            "run_date": str(pd.Timestamp.today().normalize().date())}
    log.info("replayed %d symbols: %d trades", funnel["symbols"], funnel["trades"])
    report = render(rows, funnel, p, meta)
    print(report)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"meta": meta, "params": asdict(p), "funnel": funnel, "summary": summarise(rows),
                       "tables": tables(rows), "rows": list(rows)}, fh, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
