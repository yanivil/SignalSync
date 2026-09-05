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
   daily *close* has broken the trigger level recently; setups that are
   complete but unbroken, or that broke out and pulled back below the
   trigger, are reported separately as WATCHLIST so nothing is entered early.
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
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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
# Constituent list, pinned to a specific commit of the public dataset rather
# than its moving ``main`` branch so a change upstream (or a compromise of that
# repository) cannot silently alter which tickers are scanned.  To pick up new
# index membership, bump the commit here after reviewing the upstream diff.
CONSTITUENTS_COMMIT = "7ee00fbbe71e521f4497250ac8d3b244ca8cba79"  # 2026-08-20
CONSTITUENTS_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    f"{CONSTITUENTS_COMMIT}/data/constituents.csv"
)
CONSTITUENTS_MAX_BYTES = 5 * 1024 * 1024   # the CSV is ~40 KB; anything near this is not the CSV
PIVOT_ORDER = 5          # bars on each side needed to call a swing high/low
ATR_LEN = 14
MIN_SCORE = 60           # reporting threshold for the 0-100 quality score
MAX_BREAKOUT_AGE = 3     # a breakout older than this many bars is stale
MAX_RUNAWAY = 0.05       # close more than 5% above trigger = chasing, not an entry
WATCH_PROXIMITY = 0.05   # setups whose close is within 5% below the trigger -> watchlist (3% until 2026-09-05)
# Trend context (rule 2).  "Strong down-trend" = close this far below a
# *falling* SMA200; the slope is judged against the SMA's value
# TREND_SLOPE_LOOKBACK bars earlier (~2 months: long enough to ignore
# day-to-day wobble, short enough to notice a roll-over).
TREND_STRONG_DOWN = 0.90         # close < 90% of a falling SMA200 -> bullish setups vetoed
TREND_SLOPE_LOOKBACK = 40        # bars back used to decide whether the SMA200 is falling
TREND_STRONG_DOWN_SMA50 = 0.85   # same test against SMA50 when fewer than 200 bars exist
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
FILL_CLOSE_MIN_AGE = dt.timedelta(hours=1)   # last trade must be this old to count as the closing print

# --------------------------------------------------------------------------- #
# Pattern rules.  The values below are the "spec" profile (docs/wiki/02 and the
# engine specification of 2026-09-05); the previous rules are kept as the
# "legacy" profile in RULE_PROFILES so the two can be replayed side by side.
# ``None`` switches an optional rule off.
# --------------------------------------------------------------------------- #
# Cup & Handle
CUP_MIN_LEN, CUP_MAX_LEN = 20, 300       # bars from left rim to right rim (spec: min 20, typically 35-300)
CUP_MIN_DEPTH, CUP_MAX_DEPTH = 0.12, 0.50  # cup depth as fraction of left rim (spec is silent on a minimum)
CUP_MAX_RETRACE = 0.50                   # cup decline <= this share of the preceding advance; None = off
CUP_ADVANCE_LOOKBACK = 250               # bars before rim A in which the "preceding advance" low is sought
CUP_RIM_TOL = 0.05                       # right rim within 5% of left rim (used when CUP_RIM_TOL_OF_DEPTH is None)
CUP_RIM_TOL_OF_DEPTH = 0.15              # spec: |rim B - rim A| <= 15% of the cup depth; None -> CUP_RIM_TOL
CUP_BOTTOM_ZONE = (0.25, 0.75)           # the lowest low must sit in this middle part of the cup span
HANDLE_MIN_LEN, HANDLE_MAX_LEN = 5, 25   # handle bars (spec: typically 5-25)
HANDLE_MAX_LEN_OF_CUP = 1.0              # handle bars <= cup bars x this; None = off
HANDLE_MAX_DEPTH = 0.12                  # handle pull-back from right rim (O'Neil: <= 12%)
HANDLE_MAX_FRACTION_OF_CUP = 0.50        # handle depth vs cup depth
CUP_PRIOR_ADVANCE = 0.20                 # >= 20% rise into the left rim over CUP_PRIOR_LOOKBACK bars ...
CUP_PRIOR_LOOKBACK = 60                  # ... (spec: 30-60 bars) ...
CUP_TREND_SMA_OR = True                  # ... OR SMA50 > SMA200 satisfies the trend filter on its own (spec)
CUP_REQUIRE_CLOSE_ABOVE_SMA200 = False   # legacy gate: close above the SMA200
CUP_MIN_ROUNDNESS = 0.70                 # R^2 of a U-shaped (convex) quadratic fit to cup lows (spec 0.70)
CUP_MAX_V_ADVANTAGE = 0.0                # best V fit may beat the U fit's R^2 by at most this (0 = U must win)
CUP_TARGET_BASE = "right_rim"            # measured move from the bottom to: right_rim (spec) | left_rim | trigger
CUP_TRIGGER = "handle_high"              # breakout level: handle_high (O'Neil's buy point) | rim_b (clear the rim too)

# Inverse Head & Shoulders
IHS_MIN_LEN, IHS_MAX_LEN = 20, 200       # bars from left shoulder to right shoulder
IHS_MIN_HEAD_ATR = 1.0                   # head must be >= 1 ATR below both shoulders
IHS_SHOULDER_SYM = None                  # legacy: |LS-RS| <= this x the shallower shoulder depth; None = off
IHS_SHOULDER_SYM_OF_HEIGHT = 0.30        # spec: |LS-RS| <= this x head height (neckline at the head minus head)
IHS_TIME_SYM = 2.5                       # left/right half duration ratio (loose sanity bound)
IHS_SIDE_SYM_TOL = 0.40                  # spec: |(N1-S1) - (S2-N2)| / max <= this; None = off
IHS_MAX_NECK_SLOPE = 0.15                # neckline rise/fall over pattern, fraction of price
IHS_PRIOR_DECLINE = None                 # legacy: >= this share decline into the left shoulder; None = off
IHS_PRIOR_DECLINE_OF_HEIGHT = 1.0        # spec: prior decline >= this x head height ...
IHS_TREND_SMA_OR = True                  # ... OR SMA50 < SMA200 satisfies the trend filter on its own (spec)
IHS_TARGET_AT_HEAD = True                # target height = neckline at the head bar minus head (spec); else at the break
TREND_VETO_REVERSALS = False             # legacy: reject reversal patterns in a strong down-trend

# Bullish Wolfe Wave
WW_MIN_LEN, WW_MAX_LEN = 15, 200         # bars from point 1 to point 5
WW_SWEET_ZONE = True                     # spec: point 5 below line 1-3 but above the line through 3 parallel to 2-4
WW_MAX_OVERSHOOT_ATR = 2.0               # legacy band: point 5 <= 2 ATR under line 1-3 (also scales the score)
WW_TIME_SYM_TOL = 0.30                   # spec: legs 1-2, 2-3, 3-4 each within this of their mean; None = off
WW_MAX_BARS_SINCE_P5 = 25                # confirmation must come soon after point 5
WW_MAX_ETA_BARS = 250                    # target only if lines 1-3 / 2-4 meet within this many bars after point 5
WW_MAX_TARGET_GAIN = 1.0                 # no target if line 1-4 at the ETA is more than +100% above the entry

# Volume and risk (all patterns)
VOLUME_AVG_LEN = 20                      # breakout volume is compared with this many prior bars (spec 20, legacy 50)
VOLUME_CONFIRM = {                       # a breakout close needs this volume ratio to be CONFIRMED; None = not required
    "Cup & Handle": 1.4,
    "Inverse Head & Shoulders": 1.3,
    "Bullish Wolfe Wave": None,
}
MAX_RISK_PCT = {                         # reject setups whose stop is further than this below the entry
    "Cup & Handle": 12.0,
    "Inverse Head & Shoulders": 15.0,
    "Bullish Wolfe Wave": 15.0,
}

RULE_PROFILES: Dict[str, Dict[str, Any]] = {
    "spec": {},                          # the module defaults above
    "tuned": {                           # spec with the four rules the 2026-09-05 ablation showed remove good signals
        "VOLUME_CONFIRM": {"Cup & Handle": None, "Inverse Head & Shoulders": None, "Bullish Wolfe Wave": None},
        "IHS_SIDE_SYM_TOL": None,        # +-40 % side symmetry removed the best H&S signals (+0.74 R)
        "WW_TIME_SYM_TOL": 0.60,         # +-30 % leg rhythm removed 18 of 22 Wolfe signals; keep it loose
        "CUP_MAX_RETRACE": 0.618,        # the spec's own "absolute maximum"
    },
    "legacy": {                          # the rules in force until 2026-09-05
        "CUP_MIN_LEN": 30, "CUP_MAX_LEN": 250, "CUP_MAX_RETRACE": None, "CUP_RIM_TOL_OF_DEPTH": None,
        "CUP_BOTTOM_ZONE": (0.20, 0.80), "HANDLE_MAX_LEN": 40, "HANDLE_MAX_LEN_OF_CUP": None,
        "CUP_PRIOR_ADVANCE": 0.25, "CUP_PRIOR_LOOKBACK": 120, "CUP_TREND_SMA_OR": False,
        "CUP_REQUIRE_CLOSE_ABOVE_SMA200": True, "CUP_MIN_ROUNDNESS": 0.60, "CUP_TARGET_BASE": "left_rim",
        "IHS_SHOULDER_SYM": 0.50, "IHS_SHOULDER_SYM_OF_HEIGHT": None, "IHS_SIDE_SYM_TOL": None,
        "IHS_PRIOR_DECLINE": 0.10, "IHS_PRIOR_DECLINE_OF_HEIGHT": None, "IHS_TREND_SMA_OR": False,
        "IHS_TARGET_AT_HEAD": False, "TREND_VETO_REVERSALS": True,
        "WW_SWEET_ZONE": False, "WW_TIME_SYM_TOL": None,
        "VOLUME_AVG_LEN": 50,
        "VOLUME_CONFIRM": {"Cup & Handle": None, "Inverse Head & Shoulders": None, "Bullish Wolfe Wave": None},
        "MAX_RISK_PCT": {"Cup & Handle": 15.0, "Inverse Head & Shoulders": 15.0, "Bullish Wolfe Wave": 15.0},
    },
}
ACTIVE_PROFILE = "spec"
_SPEC_VALUES: Dict[str, Any] = {}        # filled by apply_profile on first use


def apply_profile(name: str) -> str:
    """Switch the rule constants to ``RULE_PROFILES[name]``; returns the previous profile.

    "spec" restores the module defaults.  Used by ``--profile`` and by the
    backtest to replay two rule sets on the same data.
    """
    global ACTIVE_PROFILE
    if name not in RULE_PROFILES:
        raise ValueError(f"unknown rule profile {name!r}; choose from {sorted(RULE_PROFILES)}")
    keys = {k for p in RULE_PROFILES.values() for k in p}
    if not _SPEC_VALUES:
        _SPEC_VALUES.update({k: globals()[k] for k in keys})
    previous = ACTIVE_PROFILE
    for k in keys:
        globals()[k] = RULE_PROFILES[name].get(k, _SPEC_VALUES[k])
    ACTIVE_PROFILE = name
    return previous


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
    max_buy: Optional[float] = None      # trigger x (1 + MAX_RUNAWAY): above this at the open, do not chase


# --------------------------------------------------------------------------- #
# Universe & data loading
# --------------------------------------------------------------------------- #
def load_sp500_symbols(csv_path: Optional[str] = None) -> List[str]:
    """Return the S&P 500 constituent symbols in Yahoo Finance format.

    Source priority: a local CSV (``--csv``), then the public GitHub dataset
    ``datasets/s-and-p-500-companies``.  Dots in class-share tickers are
    replaced with dashes because Yahoo uses ``BRK-B`` where S&P uses ``BRK.B``,
    and symbols are upper-cased so a local CSV behaves like ``--tickers``.

    :param csv_path: Optional local CSV with a ``Symbol`` column.
    :returns: Sorted, de-duplicated list of upper-case symbols.
    :raises RuntimeError: if no source could be read, or the download exceeds
        ``CONSTITUENTS_MAX_BYTES``.
    """
    text: Optional[str] = None
    if csv_path and os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    else:
        if csv_path:
            log.warning("--csv %s not found; falling back to the pinned GitHub constituent list",
                        csv_path)
        raw: Optional[bytes] = None
        try:
            with urllib.request.urlopen(CONSTITUENTS_URL, timeout=30) as resp:
                raw = resp.read(CONSTITUENTS_MAX_BYTES + 1)
        except Exception as exc:  # network blocked, DNS failure, etc.
            log.warning("Could not download constituents: %s", exc)
        if raw is not None:
            if len(raw) > CONSTITUENTS_MAX_BYTES:   # not the ~40 KB CSV: refuse rather than parse it
                raise RuntimeError(f"constituent download exceeds {CONSTITUENTS_MAX_BYTES} bytes")
            text = raw.decode("utf-8")
    if not text:
        raise RuntimeError("No S&P 500 constituent source available")
    df = pd.read_csv(io.StringIO(text))
    col = "Symbol" if "Symbol" in df.columns else df.columns[0]
    syms = sorted({str(s).strip().upper().replace(".", "-") for s in df[col].dropna()})
    return [s for s in syms if s and s.upper() != "NAN"]


def adjust_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Apply Yahoo's split/dividend adjustment to OHLC (what ``auto_adjust=True`` does).

    Why not let yfinance do it: yfinance multiplies the row by
    ``Adj Close / Close`` and turns the whole row NaN when Yahoo has not
    published ``adjclose`` yet, which is the case for the newest bar until the
    next pre-market.  Nothing later can have adjusted the newest bar, so a
    missing ratio is 1.0 by definition.

    Volume is deliberately left alone: Yahoo's historical volume is already
    split-adjusted, and ``Adj Close / Close`` also carries dividend
    adjustments, so scaling volume by its inverse would double-adjust splits
    and distort volume on every dividend-paying stock.  yfinance's own
    ``auto_adjust`` makes the same choice.

    :param df: Frame with Open/High/Low/Close/Volume and optionally Adj Close.
    :returns: Frame with Open/High/Low/Close/Volume, prices adjusted.
    """
    out = df.copy()
    if "Adj Close" in out.columns:
        ratio = (out["Adj Close"] / out["Close"]).fillna(1.0)
        for c in ("Open", "High", "Low", "Close"):
            out[c] = out[c] * ratio
        out = out.drop(columns=["Adj Close"])
    return out[["Open", "High", "Low", "Close", "Volume"]]


def _as_utc(ts: Any) -> pd.Timestamp:
    """Yahoo's ``regularMarketTime`` as a UTC Timestamp.

    yfinance >= 1.x converts it to a tz-aware ``pd.Timestamp`` in
    ``get_history_metadata()``; the raw chart meta carries epoch seconds, which
    may arrive as ``int``, a numeric string, or a numpy integer/float.

    :param ts: Epoch seconds, or anything ``pd.Timestamp`` accepts.
    :returns: tz-aware UTC Timestamp.
    :raises ValueError, TypeError, OverflowError: for unparseable input (the
        caller treats these as "no usable quote").
    """
    if isinstance(ts, (int, float, np.integer, np.floating)) or (
            isinstance(ts, str) and ts.strip().lstrip("-").isdigit()):
        return pd.Timestamp(int(ts), unit="s", tz="UTC")
    t = pd.Timestamp(ts)
    return t.tz_convert("UTC") if t.tzinfo is not None else t.tz_localize("UTC")


def fill_missing_close(df: pd.DataFrame, meta: Mapping[str, Any], now: Optional[pd.Timestamp] = None
                       ) -> Tuple[pd.DataFrame, Optional[str]]:
    """Complete the newest bar from Yahoo's last-trade quote when its close is missing.

    Why: after the US close, Yahoo's chart row for that session carries
    open/high/low/volume but a null close (and adjclose) until about 08:00 UTC
    the next day, when US pre-market opens (observed 2026-09-04: 500/502
    symbols still incomplete at 08:05 UTC, complete at 08:10 UTC).  The chart's
    quote fields, however, already hold the closing print:
    ``regularMarketPrice`` stamped ``regularMarketTime`` at 16:00 New York.
    So when the newest row has no close, the last trade falls on that row's
    date, and it happened at least ``FILL_CLOSE_MIN_AGE`` ago (a closing print,
    not a live intraday tick), that price is used as the close.  High/Low are
    widened to include it and a missing Open is set to it.

    :param df: Raw per-symbol frame (may include ``Adj Close``).
    :param meta: ``Ticker.get_history_metadata()`` (Yahoo chart ``meta``).
    :param now: Current time (UTC); injectable for tests.
    :returns: ``(frame, date)`` -- ``date`` is the ISO date filled, or ``None``.
    """
    if df.empty or not pd.isna(df["Close"].iloc[-1]):
        return df, None
    price, ts = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
    if price is None or ts is None:
        return df, None
    try:
        price = float(price)
        traded = _as_utc(ts)
    except (TypeError, ValueError, OverflowError):
        return df, None
    if not price > 0:
        return df, None
    last = pd.Timestamp(df.index[-1])
    tz = last.tz or meta.get("exchangeTimezoneName") or "America/New_York"
    if traded.tz_convert(tz).date() != last.date():
        return df, None
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    if now - traded < FILL_CLOSE_MIN_AGE:
        return df, None
    out = df.copy()
    idx = out.index[-1]
    out.loc[idx, "Close"] = price
    if "Adj Close" in out.columns and pd.isna(out.loc[idx, "Adj Close"]):
        out.loc[idx, "Adj Close"] = price
    out.loc[idx, "High"] = np.nanmax([out.loc[idx, "High"], price])
    out.loc[idx, "Low"] = np.nanmin([out.loc[idx, "Low"], price])
    if pd.isna(out.loc[idx, "Open"]):
        out.loc[idx, "Open"] = price
    return out, str(last.date())


def _fetch_history(sym: str, period: str) -> Optional[Tuple[pd.DataFrame, dict]]:
    """Download one symbol's raw daily history plus Yahoo's chart metadata.

    Transient failures (throttling, HTTP 5xx, timeouts) are retried up to
    three times with a linear back-off of 5 s then 10 s.  A "delisted" /
    "no data" error is final and returns ``None`` immediately, without retry.

    :param sym: Yahoo symbol.
    :param period: yfinance period string.
    :returns: ``(frame, meta)``, or ``None`` if the symbol yielded nothing or
        every attempt failed.
    """
    import yfinance as yf  # imported lazily so tests can run without it

    try:  # make yfinance raise instead of logging + returning an empty frame
        yf.config.debug.hide_exceptions = False
    except Exception:
        pass
    tkr = yf.Ticker(sym)
    for attempt in range(3):  # Yahoo occasionally throttles; retry with backoff
        try:
            df = tkr.history(period=period, interval="1d", auto_adjust=False, actions=False)
            return df, (tkr.get_history_metadata() or {})
        except Exception as exc:
            msg = str(exc)
            if "delisted" in msg.lower() or "no data" in msg.lower() or "Missing" in type(exc).__name__:
                log.warning("%s: no data (%s)", sym, msg.splitlines()[0][:120])
                return None
            log.warning("%s attempt %d failed: %s", sym, attempt, msg.splitlines()[0][:120])
            if attempt < 2:
                time.sleep(5 * (attempt + 1))   # 5 s, then 10 s; no sleep after the last try
    return None


def download_history(symbols: Sequence[str], period: str = "2y", workers: int = 8,
                     now: Optional[pd.Timestamp] = None) -> Dict[str, pd.DataFrame]:
    """Download daily OHLCV for many symbols with yfinance, in parallel.

    Per-symbol ``Ticker.history`` (rather than the batched ``yf.download``)
    so each symbol's chart metadata is available to :func:`fill_missing_close`;
    yfinance issues one chart request per symbol either way.

    :param symbols: Yahoo symbols.
    :param period: yfinance period string (``"2y"`` gives ~500 daily bars).
    :param workers: Parallel downloads.
    :param now: Current time (UTC) for :func:`fill_missing_close`; tests inject it.
    :returns: ``{symbol: DataFrame[Open, High, Low, Close, Volume]}`` with only
        symbols that returned usable data.  Rows without a Close are dropped;
        the dates of *trailing* rows dropped this way are recorded in
        ``df.attrs["partial_bars"]`` so :func:`align_last_bar` can report them,
        and ``df.attrs["filled_close"]`` is the date whose close was taken from
        the quote (or ``None``).
    :raises ImportError: if yfinance is not installed.

    Complexity: one chart request per symbol spread over ``workers`` threads
    (wall time is network-bound), then O(rows) cleaning per symbol.
    """
    from concurrent.futures import ThreadPoolExecutor

    out: Dict[str, pd.DataFrame] = {}
    raw_last: Dict[str, pd.Timestamp] = {}   # last index date before cleaning (diagnostics)
    filled = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(lambda s: (s, _fetch_history(s, period)), symbols))
    for sym, res in results:
        if res is None:
            continue
        df, meta = res
        if df is None or df.empty or "Close" not in df.columns:
            continue
        try:
            cleaned = _clean_history(sym, df, meta, now)
        except Exception as exc:  # a malformed frame must not abort the whole download
            log.exception("%s: unusable history, skipped: %s", sym, exc)
            continue
        if cleaned is None:
            continue
        raw_last[sym], out[sym] = cleaned
        filled += 1 if out[sym].attrs["filled_close"] else 0
    if out:
        hist_raw = _date_histogram(raw_last.values())
        hist_ok = _date_histogram(df.index[-1] for df in out.values())
        log.info("last raw bar per symbol: %s; last complete bar per symbol: %s; "
                 "closes filled from quote: %d", hist_raw, hist_ok, filled)
    return out


def _clean_history(sym: str, df: pd.DataFrame, meta: Mapping[str, Any], now: Optional[pd.Timestamp]
                   ) -> Optional[Tuple[pd.Timestamp, pd.DataFrame]]:
    """Fill, adjust, normalise and trim one symbol's raw history.

    :returns: ``(last_raw_index, clean_frame)`` with ``attrs["partial_bars"]``
        and ``attrs["filled_close"]`` set, or ``None`` if fewer than 60 usable
        bars remain.  Raises on malformed input; the caller logs and skips.
    """
    raw_last = df.index[-1]
    df, filled_day = fill_missing_close(df, meta, now=now)
    df = adjust_ohlc(df)
    if getattr(df.index, "tz", None) is not None:
        # Ticker.history() indexes in exchange time; the rest of the scan
        # (and align_last_bar's date comparisons) work on naive dates.
        df.index = df.index.tz_localize(None).normalize()
    has_close = df["Close"].notna().to_numpy()
    if not has_close.any():
        return None
    last_ok = int(np.flatnonzero(has_close)[-1])
    # Trailing rows without a Close that fill_missing_close could not
    # complete (no quote on that date yet): reported as "partial".
    tail = df.iloc[last_ok + 1:]
    partial = [str(d.date()) for d, row in tail.iterrows() if row.notna().any()]
    df = df[has_close]
    log.debug("%s: last raw bar %s, last complete bar %s%s%s", sym,
              raw_last.date(), df.index[-1].date(),
              f", close filled from quote for {filled_day}" if filled_day else "",
              f", trailing rows without Close: {partial}" if partial else "")
    if len(df) < 60:
        return None
    clean = df.copy()
    clean.attrs["partial_bars"] = partial
    clean.attrs["filled_close"] = filled_day
    return raw_last, clean


def _date_histogram(dates: Iterable) -> Dict[str, int]:
    """``{"YYYY-MM-DD": count}`` sorted newest first (for logs and meta)."""
    counts: Dict[str, int] = {}
    for d in dates:
        key = str(pd.Timestamp(d).date())
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), reverse=True))


def align_last_bar(data: Dict[str, pd.DataFrame], min_fraction: float = LAST_BAR_MIN_FRACTION
                   ) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
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

    Complexity: O(S log S) for the date histogram over S symbols, plus O(rows)
    for the truncation mask of each symbol that runs ahead.
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

    aligned: Dict[str, pd.DataFrame] = {}
    skipped_complete: Dict[str, int] = {}
    partial: Dict[str, int] = {}
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
    :returns: ATR series aligned with ``df``.  The first ``n - 1`` values are
        partial means (``min_periods=1``); bar 0 is simply High - Low.

    Complexity: O(n_bars).
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

    Complexity: O(n * order) -- each of the n bars scans a 2*order+1 window.
    A flat stretch yields no pivots (the tie goes to the window's first bar,
    which is never the centre), so constant prices produce nothing.
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

    * ``strong_downtrend`` = close below ``TREND_STRONG_DOWN`` (90 %) of a
      200-day SMA that is lower than ``TREND_SLOPE_LOOKBACK`` bars ago.
      Bullish setups are vetoed in that state.
    * ``uptrend`` = close above the 200-day SMA (required for the Cup & Handle,
      which is a continuation pattern; optional bonus for reversal patterns).

    :param df: OHLCV DataFrame (>= 60 bars).
    :returns: ``(description, uptrend, strong_downtrend)``.

    Complexity: O(n_bars) for the two rolling means.
    """
    close = df["Close"]
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    c = float(close.iloc[-1])
    s50 = float(sma50.iloc[-1]) if not math.isnan(sma50.iloc[-1]) else None
    s200 = float(sma200.iloc[-1]) if not math.isnan(sma200.iloc[-1]) else None
    k = TREND_SLOPE_LOOKBACK
    s200_prev = (float(sma200.iloc[-k]) if len(sma200) > k
                 and not math.isnan(sma200.iloc[-k]) else None)

    if s200 is None:  # not enough history for a 200-day view; fall back to 50
        uptrend = s50 is not None and c > s50
        strong_down = s50 is not None and c < TREND_STRONG_DOWN_SMA50 * s50
        desc = f"close {'above' if uptrend else 'below'} SMA50 (SMA200 n/a)"
        return desc, uptrend, strong_down

    uptrend = c > s200
    if s200_prev is None:
        # SMA200 exists but did not TREND_SLOPE_LOOKBACK bars ago (200-239 bars
        # of history): its slope is unknowable, so the veto falls back to the
        # SMA50 test used for short histories rather than silently switching off.
        falling200 = False
        strong_down = s50 is not None and c < TREND_STRONG_DOWN_SMA50 * s50
        slope_text = "SMA200 slope n/a"
    else:
        falling200 = s200 < s200_prev
        strong_down = (c < TREND_STRONG_DOWN * s200) and falling200
        slope_text = "SMA200 " + ("falling" if falling200 else "rising/flat")
    parts = [f"close {'above' if uptrend else 'below'} SMA200"]
    if s50 is not None:
        parts.append(f"SMA50 {'>' if s50 > s200 else '<'} SMA200")
    parts.append(slope_text)
    return ", ".join(parts), uptrend, strong_down


def _volume_ratio(df: pd.DataFrame, idx: int) -> Optional[float]:
    """Volume on bar ``idx`` divided by the trailing ``VOLUME_AVG_LEN``-bar average (excl. idx).

    :returns: The ratio rounded to 2 dp, or ``None`` when ``idx < 20``, the
        bar's volume is NaN, or the trailing average is zero/NaN (a zero-volume
        session on ``idx`` itself yields ``0.0``).
    """
    vol = df["Volume"].to_numpy(dtype=float)
    if idx < 20 or np.isnan(vol[idx]):
        return None
    base = vol[max(0, idx - VOLUME_AVG_LEN):idx]
    base = base[~np.isnan(base)]
    if len(base) == 0 or base.mean() == 0:
        return None
    return round(float(vol[idx] / base.mean()), 2)


def _sma_pair(df: pd.DataFrame) -> Tuple[Optional[float], Optional[float]]:
    """Last SMA50 and SMA200 of the close (``None`` when there is not enough history)."""
    close = df["Close"]
    out = []
    for n in (50, 200):
        v = close.rolling(n).mean().iloc[-1] if len(close) >= n else float("nan")
        out.append(None if math.isnan(v) else float(v))
    return out[0], out[1]


def _volume_confirmed(pattern: str, vr: Optional[float]) -> bool:
    """Spec rule: a breakout close is CONFIRMED only with ``VOLUME_CONFIRM[pattern]`` x average volume."""
    need = VOLUME_CONFIRM.get(pattern)
    return need is None or (vr is not None and vr >= need)


def evaluate_breakout(close: np.ndarray, trigger_at: Callable[[int], float], start: int,
                      pattern: str, floor: Optional[float] = None
                      ) -> Tuple[str, Optional[int], float]:
    """Classify a completed setup by the *current* run of closes above its trigger.

    Shared by all three detectors; the trigger is a function of the bar index
    so a constant level (cup: handle high) and sloping ones (H&S neckline,
    Wolfe line 1-3) use the same state machine.

    * Last close **above** today's trigger: ``age`` = bars since the *first*
      close above the trigger from ``start`` on.  CONFIRMED if
      ``age <= max_breakout_age(pattern)`` and the close is not more than
      ``MAX_RUNAWAY`` above the trigger at that first break; otherwise STALE.
      The clock deliberately does not restart on a re-break after a
      pull-back: on synthetic noise, treating each re-cross as a fresh
      breakout raised the confirmed false-positive rate from about 1 % to
      5 % of series, because choppy prices cross a level repeatedly.  A
      re-break inside the age window is still CONFIRMED (age from the first
      break); beyond it the setup is STALE.
    * Last close **at or below** today's trigger: WATCHLIST if it is within
      ``WATCH_PROXIMITY`` of the trigger and above ``floor`` (the level whose
      loss would void the pattern: right-shoulder low, point 5); otherwise
      STALE.  This covers both "never broke out" and "broke out and pulled
      back" -- a retest keeps the setup on the watchlist instead of vanishing.

    :param close: Close prices.
    :param trigger_at: ``bar index -> trigger level``.
    :param start: First bar at which a break counts (the bar after the
        pattern completed); a run cannot begin before it.
    :param pattern: Pattern name, for :func:`max_breakout_age`.
    :param floor: Watchlist rows need the close above this; ``None`` = no floor.
    :returns: ``(status, age, trigger)`` -- ``age`` is ``None`` unless the close
        is above the trigger; ``trigger`` is the level at the first break bar
        when the close is above it, else today's level.

    Complexity: O(n - start).
    """
    n = len(close)
    start = max(start, 0)
    trigger_now = float(trigger_at(n - 1))
    if not close[-1] > trigger_now:
        near = close[-1] >= trigger_now * (1 - WATCH_PROXIMITY)
        if near and (floor is None or close[-1] > floor):
            return "WATCHLIST", None, trigger_now
        return "STALE", None, trigger_now
    first_break = next(i for i in range(start, n) if close[i] > trigger_at(i))   # exists: today qualifies
    age = n - 1 - first_break
    trigger = float(trigger_at(first_break))
    if age > max_breakout_age(pattern):
        return "STALE", age, trigger        # breakout too old (rule 3)
    if close[-1] > trigger * (1 + MAX_RUNAWAY):
        return "STALE", age, trigger        # price already ran away; entering now is chasing (rule 4)
    return "CONFIRMED", age, trigger



def _u_shape_r2(lows: np.ndarray) -> float:
    """R^2 of a convex quadratic fitted to the cup lows (1.0 = perfect U).

    Returns 0 when the best-fit parabola opens downward (an arch, not a cup).
    Note what this does and does not reject: it measures how much of the lows'
    variance *one parabola* explains, so a ragged, multi-legged or lopsided
    base scores poorly, but a clean symmetric V still scores about 0.93 (a
    parabola fits ``|x|`` well).  V-shaped cups are rejected separately by
    comparing this value with :func:`_v_shape_r2`.

    :param lows: Low prices from left rim to right rim inclusive.
    :returns: Coefficient of determination in [0, 1].

    Complexity: O(m) for m lows (one least-squares fit of degree 2).
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


def _v_shape_r2(lows: np.ndarray, bottom_rel: int) -> float:
    """Best R^2 of a two-legged V (``a + b*|x - c|``, ``b > 0``) fitted to the cup lows.

    The vertex ``c`` is searched within +-10 % of the cup width around the
    lowest low.  Compared with :func:`_u_shape_r2`: a rounded or flat-bottomed
    base is explained better by the parabola, a sharp reversal better by the V.
    On reference shapes the margin is about +0.04 for a half-sine, +0.37 for a
    flat dish and -0.06 for a clean V, so ``CUP_MAX_V_ADVANTAGE = 0`` separates
    them.

    :param lows: Low prices from left rim to right rim inclusive.
    :param bottom_rel: Index of the lowest low within ``lows``.
    :returns: Best coefficient of determination in [0, 1]; 0 for degenerate input.

    Complexity: O(m * k) for m lows and k ~ m/5 vertex candidates (closed-form
    least squares per candidate, no polyfit).
    """
    m = len(lows)
    if m < 5:
        return 0.0
    y = lows.astype(float)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    if ss_tot == 0:
        return 0.0
    x = np.arange(m, dtype=float)
    half = max(3, m // 10)
    best = 0.0
    for c in range(max(1, bottom_rel - half), min(m - 2, bottom_rel + half) + 1):
        d = np.abs(x - c)
        var_d = float(((d - d.mean()) ** 2).sum())
        if var_d == 0:
            continue
        b = float(((d - d.mean()) * (y - y.mean())).sum()) / var_d
        if b <= 0:
            continue  # legs would open downward: not a V
        fit = y.mean() + b * (d - d.mean())
        best = max(best, 1 - float(((y - fit) ** 2).sum()) / ss_tot)
    return best


def _find_handle(high: np.ndarray, low: np.ndarray, close: np.ndarray, b: int,
                 n: int, max_len: Optional[int] = None) -> Optional[Tuple[int, float, int]]:
    """Locate the handle that follows right rim ``b``.

    The handle runs from ``b+1`` until the bar *before* the first close that
    exceeds the running handle high (the breakout), or until ``max_len``
    (default ``HANDLE_MAX_LEN``) bars / the end of data.  It must contain at
    least ``HANDLE_MIN_LEN`` bars.

    :returns: ``(handle_low_index, handle_high, handle_end_index)`` or ``None``.
    """
    start = b + 1
    end_max = min(b + (max_len if max_len is not None else HANDLE_MAX_LEN), n - 1)
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
      roundness fit (R^2 >= ``CUP_MIN_ROUNDNESS``) of the cup lows, which must
      also explain the lows at least as well as the best two-legged V fit
      (``CUP_MAX_V_ADVANTAGE``): sharp V reversals are not bases.
    * Handle: 5-40 bars after ``B``, its low stays above the cup's mid-point and
      within 12 % of ``B``; handle depth <= half the cup depth.
    * Trigger: close above the handle's highest high -- O'Neil's buy point is
      the handle peak, not the cup rim.  Rim B is a swing high,
      so nothing within ``PIVOT_ORDER`` bars of it can exceed it, but a wick
      above B later in the handle raises the trigger above the rim (the setup
      then needs a close above that wick: conservative).  Stop: handle low
      minus 0.25 ATR.
    * Requires close above the 200-day SMA (continuation pattern needs an uptrend).

    :param df: OHLCV DataFrame.
    :param ticker: Symbol for labelling.
    :returns: Zero or more Signals (best-scoring per rim pair).

    Complexity: O(P^2 * W) worst case for P swing highs and cup width W --
    each candidate rim pair costs O(W) for the bottom search and the quadratic
    fit.  The ``break`` on ``CUP_MAX_LEN`` bounds the pairs per left rim.
    """
    high, low, close = (df[c].to_numpy(dtype=float) for c in ("High", "Low", "Close"))
    n = len(close)
    if n < CUP_MIN_LEN + HANDLE_MIN_LEN + 5:
        return []
    desc, uptrend, strong_down = trend_context(df)
    if CUP_REQUIRE_CLOSE_ABOVE_SMA200 and not uptrend:
        return []  # legacy rule 2 gate: continuation pattern needs the uptrend
    s50, s200 = _sma_pair(df)
    sma_trend_ok = CUP_TREND_SMA_OR and s50 is not None and s200 is not None and s50 > s200
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
            seg_low = low[a:b + 1]
            bottom_rel = int(np.argmin(seg_low))
            bottom = seg_low[bottom_rel]
            depth = (rim_a - bottom) / rim_a
            if not (CUP_MIN_DEPTH <= depth <= CUP_MAX_DEPTH):
                continue
            # Rim alignment: spec measures the rim mismatch against the cup
            # depth (<= 15 % of it); legacy against the price (<= 5 %).
            rim_tol = (CUP_RIM_TOL_OF_DEPTH * (rim_a - bottom) if CUP_RIM_TOL_OF_DEPTH is not None
                       else CUP_RIM_TOL * rim_a)
            if abs(rim_b - rim_a) > rim_tol:
                continue
            pos = bottom_rel / width
            if not (CUP_BOTTOM_ZONE[0] <= pos <= CUP_BOTTOM_ZONE[1]):
                continue  # bottom hugging one rim -> not a rounded cup
            # Prior up-trend into the left rim: a cup is a *continuation* base.
            # Spec: SMA50 > SMA200, OR a >= 20 % *rise* from the low of the
            # CUP_PRIOR_LOOKBACK bars before rim A (legacy: 25 % over 120 bars,
            # no SMA alternative).  Note it is a rise from the low, not the
            # low's distance below the rim (which would be a 33 % rise).
            recent_low = float(low[max(0, a - CUP_PRIOR_LOOKBACK):a + 1].min())
            if not sma_trend_ok and (rim_a - recent_low) / recent_low < CUP_PRIOR_ADVANCE:
                continue
            # Cup rollback: the decline from rim A may not retrace more than
            # CUP_MAX_RETRACE of the preceding advance (the rise from the
            # CUP_ADVANCE_LOOKBACK-bar low to rim A).
            if CUP_MAX_RETRACE is not None:
                pre_low = float(low[max(0, a - CUP_ADVANCE_LOOKBACK):a + 1].min())
                if (rim_a - bottom) > CUP_MAX_RETRACE * (rim_a - pre_low):
                    continue
            # Roundness: fit a convex quadratic to the cup lows; a ragged or
            # lopsided base scores poorly.  This is the main defence against
            # "seeing" cups in random price movement (rule 1).
            roundness = _u_shape_r2(seg_low)
            if roundness < CUP_MIN_ROUNDNESS:
                continue
            # A sharp V is explained better by two straight legs than by a
            # parabola.  Require the U fit to be at least as good as the best V
            # fit (vertex near the bottom); otherwise this is a spike reversal,
            # not a base (O'Neil: V-shaped cups fail far more often).
            if _v_shape_r2(seg_low, bottom_rel) - roundness > CUP_MAX_V_ADVANTAGE:
                continue
            # Handle: the stretch after rim B up to (not including) the first
            # close above the handle's own high.  It must last >= HANDLE_MIN_LEN
            # bars, stay shallow, and hold the upper half of the cup.
            max_handle = (HANDLE_MAX_LEN if HANDLE_MAX_LEN_OF_CUP is None
                          else min(HANDLE_MAX_LEN, int(width * HANDLE_MAX_LEN_OF_CUP)))
            handle = _find_handle(high, low, close, b, n, max_handle)
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
            # Trigger: the handle peak (O'Neil's buy point) or, if configured, the
            # higher of the handle peak and rim B so the close must clear the rim too.
            level = float(max(handle_high, rim_b)) if CUP_TRIGGER == "rim_b" else float(handle_high)
            status, age, trigger = evaluate_breakout(close, lambda _i: level,
                                                     start=handle_end + 1, pattern="Cup & Handle")
            if status == "STALE":
                continue
            vr = _volume_ratio(df, n - 1 - age) if age is not None else None
            volume_note = ""
            if status == "CONFIRMED" and not _volume_confirmed("Cup & Handle", vr):
                # Spec: a breakout close without volume is not a confirmation;
                # keep it visible on the watchlist rather than dropping it.
                status, age = "WATCHLIST", None
                volume_note = f"; breakout without volume ({vr if vr is not None else 'n/a'}x)"
            entry = float(close[-1]) if status == "CONFIRMED" and close[-1] > trigger else float(trigger)
            stop = float(handle_low - 0.25 * a_tr[h_low_idx])
            if stop >= entry:
                continue
            risk = (entry - stop) / entry * 100
            max_risk = MAX_RISK_PCT["Cup & Handle"]
            if risk > max_risk:
                continue  # rule 4: reject setups whose structural stop is too far
            # Quality score (0-100): 50 base
            #   +15 roundness         (0 at CUP_MIN_ROUNDNESS, 15 at R^2 = 1)
            #   +10 depth near 25 %   (0 at 0 % or 50 %, linear)
            #   +10 shallow handle    (0 at HANDLE_MAX_DEPTH)
            #   +10 tight risk        (0 at the MAX_RISK_PCT limit)
            #   +5  breakout volume >= 1.3x the VOLUME_AVG_LEN-day average
            score = 50
            score += 15 * (roundness - CUP_MIN_ROUNDNESS) / (1 - CUP_MIN_ROUNDNESS)
            score += 10 * (1 - min(abs(depth - 0.25) / 0.25, 1))  # depth ~25% ideal
            score += 10 * (1 - min(handle_depth / HANDLE_MAX_DEPTH, 1))
            score += 10 * (1 - min(risk / max_risk, 1))
            if vr is not None and vr >= 1.3:
                score += 5
            score = int(max(0, min(100, round(score))))
            if score < MIN_SCORE:
                continue
            # Measured move: cup bottom to the right rim (spec), the left rim
            # (legacy) or the handle breakout level (Investopedia).
            base_level = {"right_rim": rim_b, "left_rim": rim_a, "trigger": trigger}[CUP_TARGET_BASE]
            target = float(entry + (base_level - bottom))
            dates = df.index
            notes = (f"left rim {dates[a].date()} @{rim_a:.2f}, bottom "
                     f"{dates[a + bottom_rel].date()} @{bottom:.2f} (depth {depth*100:.0f}%), "
                     f"right rim {dates[b].date()} @{rim_b:.2f}, handle low "
                     f"{dates[h_low_idx].date()} @{handle_low:.2f} (depth {handle_depth*100:.1f}%), "
                     f"trigger {trigger:.2f}{volume_note}")
            signals.append(Signal(ticker, "Cup & Handle", status, round(entry, 2), round(stop, 2),
                                  round(risk, 2), round(target, 2), score, round(float(close[-1]), 2),
                                  str(dates[-1].date()), age, vr, desc, notes,
                                  max_buy=round(float(trigger) * (1 + MAX_RUNAWAY), 2)))
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

    Complexity: O(L * (W + n)) for L swing lows: each consecutive triple costs
    O(W) for the neckline anchors and O(n) for the confirmation scan.
    """
    high, low, close = (df[c].to_numpy(dtype=float) for c in ("High", "Low", "Close"))
    n = len(close)
    if n < IHS_MIN_LEN + 20:
        return []
    desc, uptrend, strong_down = trend_context(df)
    if TREND_VETO_REVERSALS and strong_down:
        return []
    s50, s200 = _sma_pair(df)
    sma_trend_ok = IHS_TREND_SMA_OR and s50 is not None and s200 is not None and s50 < s200
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
        if IHS_SHOULDER_SYM is not None and abs(ls_v - rs_v) > IHS_SHOULDER_SYM * min(d_left, d_right):
            continue
        ratio = (h - ls) / max(rs - h, 1)
        if ratio > IHS_TIME_SYM or ratio < 1 / IHS_TIME_SYM:
            continue
        # Neckline anchors: highest high strictly *between* LS-H and H-RS.
        # The anchor bars themselves are excluded: a long upper wick on a
        # shoulder or head bar is not a rally peak.  Consecutive swing lows
        # are always > PIVOT_ORDER bars apart, so both interiors are non-empty
        # and n1 < h < n2 holds by construction.
        n1 = ls + 1 + int(np.argmax(high[ls + 1:h]))
        n2 = h + 1 + int(np.argmax(high[h + 1:rs]))
        slope = (high[n2] - high[n1]) / (n2 - n1)
        # Neckline tilt = its total rise/fall over the pattern width, as a
        # fraction of the head price.  Beyond IHS_MAX_NECK_SLOPE (15 %) it is a
        # trend line rather than a neckline.
        if abs(slope * width) / close[h] > IHS_MAX_NECK_SLOPE:
            continue
        head_height = float(high[n1] + slope * (h - n1)) - h_v   # spec: neckline at the head bar minus head
        # Shoulder symmetry (spec): |S2 - S1| <= 30 % of the head height.
        if IHS_SHOULDER_SYM_OF_HEIGHT is not None and abs(ls_v - rs_v) > IHS_SHOULDER_SYM_OF_HEIGHT * head_height:
            continue
        # Side-duration symmetry (spec): S1->N1 and N2->S2 within +-40 % of each other.
        if IHS_SIDE_SYM_TOL is not None:
            left_side, right_side = n1 - ls, rs - n2
            if abs(left_side - right_side) / max(left_side, right_side) > IHS_SIDE_SYM_TOL:
                continue
        # Prior decline into the left shoulder.  Spec: SMA50 < SMA200 OR a
        # decline of at least one head height from the 60-bar high; legacy: a
        # 10 % decline measured as a share of that high.
        look = high[max(0, ls - 60):ls + 1]
        decline = float(look.max()) - ls_v
        decline_ok = ((IHS_PRIOR_DECLINE is not None and decline / float(look.max()) >= IHS_PRIOR_DECLINE)
                      or (IHS_PRIOR_DECLINE_OF_HEIGHT is not None
                          and decline >= IHS_PRIOR_DECLINE_OF_HEIGHT * head_height))
        if not (sma_trend_ok or decline_ok):
            continue

        def neck_at(idx: int) -> float:
            return float(high[n1] + slope * (idx - n1))

        # Confirmation: closes above the (sloping) neckline after RS; a watch-
        # list row must also hold above the right-shoulder low.
        trigger_now = neck_at(n - 1)
        status, age, trigger = evaluate_breakout(close, neck_at, start=rs + 1,
                                                 pattern="Inverse Head & Shoulders", floor=rs_v)
        if status == "STALE":
            continue
        vr = _volume_ratio(df, n - 1 - age) if age is not None else None
        volume_note = ""
        if status == "CONFIRMED" and not _volume_confirmed("Inverse Head & Shoulders", vr):
            status, age, trigger = "WATCHLIST", None, trigger_now
            volume_note = f"; breakout without volume ({vr if vr is not None else 'n/a'}x)"
        entry = float(close[-1]) if status == "CONFIRMED" and close[-1] > trigger else float(trigger)
        stop = float(rs_v - 0.25 * a_tr[rs])
        if stop >= entry:
            continue
        risk = (entry - stop) / entry * 100
        max_risk = MAX_RISK_PCT["Inverse Head & Shoulders"]
        if risk > max_risk:
            continue
        # Measured move: neckline minus head, with the neckline read at the
        # head bar (spec) or at the breakout bar (legacy).
        height = head_height if IHS_TARGET_AT_HEAD else trigger - h_v
        # Quality score (0-100): 50 base
        #   +15 shoulder price symmetry (0 at the symmetry limit in force)
        #   +10 shoulder time symmetry  (log-scaled, 0 at the IHS_TIME_SYM limit)
        #   +10 flat neckline           (0 at the IHS_MAX_NECK_SLOPE limit)
        #   +5  close above SMA200
        #   +5  tight risk              (0 at the MAX_RISK_PCT limit)
        #   +5  breakout volume >= 1.3x the VOLUME_AVG_LEN-day average
        score = 50
        sym_limit = (IHS_SHOULDER_SYM * min(d_left, d_right) if IHS_SHOULDER_SYM is not None
                     else (IHS_SHOULDER_SYM_OF_HEIGHT or 0) * head_height)
        score += 15 * (1 - min(abs(ls_v - rs_v) / max(sym_limit, 1e-9), 1))
        score += 10 * (1 - abs(math.log(ratio)) / math.log(IHS_TIME_SYM))
        score += 10 * (1 - min(abs(slope * width) / close[h] / IHS_MAX_NECK_SLOPE, 1))
        score += 5 if uptrend else 0
        score += 5 * (1 - min(risk / max_risk, 1))
        if vr is not None and vr >= 1.3:
            score += 5
        score = int(max(0, min(100, round(score))))
        if score < MIN_SCORE:
            continue
        dates = df.index
        notes = (f"LS {dates[ls].date()} @{ls_v:.2f}, head {dates[h].date()} @{h_v:.2f}, "
                 f"RS {dates[rs].date()} @{rs_v:.2f}, neckline {high[n1]:.2f}->{high[n2]:.2f} "
                 f"(now {trigger_now:.2f}){volume_note}")
        signals.append(Signal(ticker, "Inverse Head & Shoulders", status, round(entry, 2),
                              round(stop, 2), round(risk, 2), round(float(entry + height), 2),
                              score, round(float(close[-1]), 2), str(dates[-1].date()), age, vr,
                              desc, notes, max_buy=round(float(trigger) * (1 + MAX_RUNAWAY), 2)))
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

    Complexity: O(L * (W + n)) for L swing lows: each consecutive triple costs
    O(W) to pick points 2 and 4 and O(n) for the confirmation scan.
    """
    high, low, close = (df[c].to_numpy(dtype=float) for c in ("High", "Low", "Close"))
    n = len(close)
    if n < WW_MIN_LEN + 20:
        return []
    desc, uptrend, strong_down = trend_context(df)
    if TREND_VETO_REVERSALS and strong_down:
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
        if WW_SWEET_ZONE:
            # Spec: point 5 must penetrate below line 1-3 and stop inside the
            # "sweet zone", i.e. above the line through point 3 parallel to 2-4.
            if overshoot < 0:
                continue  # point 5 did not break below line 1-3
            if v5 < v3 + s24 * (p5 - p3):
                continue  # broke below the sweet zone: a real breakdown, not a false one
        else:
            if overshoot < -0.5 * a_tr[p5]:
                continue  # point 5 clearly failed to reach the line
            if overshoot > WW_MAX_OVERSHOOT_ATR * a_tr[p5]:
                continue  # broke down for real, not a Wolfe false break
        if WW_TIME_SYM_TOL is not None:
            # Spec: legs 1->2, 2->3 and 3->4 keep a consistent rhythm (each
            # within WW_TIME_SYM_TOL of their mean).
            legs = (p2 - p1, p3 - p2, p4 - p3)
            mean_leg = sum(legs) / 3
            if any(abs(leg - mean_leg) > WW_TIME_SYM_TOL * mean_leg for leg in legs):
                continue
        # Confirmation: closes back above line 1-3 after point 5; a watchlist
        # row must also hold above point 5.
        def line13(idx: int) -> float:
            return float(v1 + s13 * (idx - p1))

        line_now = line13(n - 1)
        status, age, trigger = evaluate_breakout(close, line13, start=p5 + 1,
                                                 pattern="Bullish Wolfe Wave", floor=v5)
        if status == "STALE":
            continue
        vr = _volume_ratio(df, n - 1 - age) if age is not None else None
        volume_note = ""
        if status == "CONFIRMED" and not _volume_confirmed("Bullish Wolfe Wave", vr):
            status, age, trigger = "WATCHLIST", None, line_now
            volume_note = f"; breakout without volume ({vr if vr is not None else 'n/a'}x)"
        entry = float(close[-1]) if status == "CONFIRMED" and close[-1] > trigger else float(trigger)
        stop = float(v5 - 0.25 * a_tr[p5])
        if stop >= entry:
            continue
        risk = (entry - stop) / entry * 100
        max_risk = MAX_RISK_PCT["Bullish Wolfe Wave"]
        if risk > max_risk:
            continue
        # ETA = the bar where lines 1-3 and 2-4 meet.  Solving
        #   v1 + s13 (x - p1) = v2 + s24 (x - p2)
        # for x gives  x = [(v2 - s24 p2) - (v1 - s13 p1)] / (s13 - s24);
        # s24 < s13 (both negative) so the denominator is positive.
        # EPA = line 1-4 evaluated at the ETA bar (Wolfe's price target).
        # Near-parallel lines push the ETA (and the target on line 1-4) towards
        # infinity, so the target is only reported when the lines meet within
        # WW_MAX_ETA_BARS after point 5.
        denom = s13 - s24
        eta = (v2 - s24 * p2 - (v1 - s13 * p1)) / denom if denom != 0 else None
        s14 = (v4 - v1) / (p4 - p1)
        target = (float(v1 + s14 * (eta - p1))
                  if eta is not None and p5 < eta <= p5 + WW_MAX_ETA_BARS else None)
        # A steep line 1-4 can still project a multiple of the price (replay
        # found +590 % and +120 % targets): not a trading target, drop it.
        if target is not None and target > close[-1] * (1 + WW_MAX_TARGET_GAIN):
            target = None
        if target is not None and target <= entry:
            target = None
        # Quality score (0-100): 50 base
        #   +15 point 5 close to line 1-3 (0 at the WW_MAX_OVERSHOOT_ATR limit)
        #   +10 time symmetry of legs 1-3 vs 3-5 (log-scaled, 0 at a 3x ratio)
        #   +10 tight risk (0 at the MAX_RISK_PCT limit)
        #   +5  close above SMA200
        #   +5  breakout volume >= 1.3x the VOLUME_AVG_LEN-day average
        score = 50
        score += 15 * (1 - min(abs(overshoot) / (WW_MAX_OVERSHOOT_ATR * a_tr[p5]), 1))
        sym = (p3 - p1) / max(p5 - p3, 1)
        score += 10 * (1 - min(abs(math.log(sym)) / math.log(3), 1))
        score += 10 * (1 - min(risk / max_risk, 1))
        score += 5 if uptrend else 0
        if vr is not None and vr >= 1.3:
            score += 5
        score = int(max(0, min(100, round(score))))
        if score < MIN_SCORE:
            continue
        dates = df.index
        notes = (f"1 {dates[p1].date()} @{v1:.2f}, 2 {dates[p2].date()} @{v2:.2f}, "
                 f"3 {dates[p3].date()} @{v3:.2f}, 4 {dates[p4].date()} @{v4:.2f}, "
                 f"5 {dates[p5].date()} @{v5:.2f}; line 1-3 now {line_now:.2f}"
                 + (f"; ETA ~{dates[min(int(eta), n - 1)].date()}" if eta and eta < n else "")
                 + volume_note)
        signals.append(Signal(ticker, "Bullish Wolfe Wave", status, round(entry, 2), round(stop, 2),
                              round(risk, 2), round(target, 2) if target else None, score,
                              round(float(close[-1]), 2), str(dates[-1].date()), age, vr, desc, notes,
                                  max_buy=round(float(trigger) * (1 + MAX_RUNAWAY), 2)))
    return _dedupe(signals)


def _dedupe(signals: List[Signal]) -> List[Signal]:
    """Keep the best-scoring signal per (ticker, pattern, status).

    Overlapping pivot combinations often describe the same structure; reporting
    all of them would be noise (and would look like forcing patterns).
    """
    best: Dict[Tuple[str, str, str], Signal] = {}
    for s in signals:
        key = (s.ticker, s.pattern, s.status)
        if key not in best or s.score > best[key].score:
            best[key] = s
    return list(best.values())


# --------------------------------------------------------------------------- #
# Orchestration & reporting
# --------------------------------------------------------------------------- #
DETECTORS = (detect_cup_and_handle, detect_inverse_hs, detect_bullish_wolfe)


def scan_symbol(sym: str, df: pd.DataFrame, detectors: Optional[Sequence[Callable]] = None) -> List[Signal]:
    """Run all detectors on one symbol, isolating failures per detector.

    :param sym: Symbol.
    :param df: OHLCV DataFrame.
    :param detectors: Subset of :data:`DETECTORS` to run (default: all); used
        by the backtest's detector-variant passes.
    :returns: Signals from the detectors run.
    """
    out: List[Signal] = []
    for fn in (detectors if detectors is not None else DETECTORS):
        try:
            out.extend(fn(df, sym))
        except Exception as exc:  # one bad ticker must not abort the scan
            log.exception("%s failed on %s: %s", fn.__name__, sym, exc)
    return out


def close_out(previous: Sequence[Mapping[str, Any]], current: Sequence[Signal],
              data: Mapping[str, pd.DataFrame]) -> List[Dict[str, Any]]:
    """Explain every setup listed in the previous report that is absent from this one.

    The spec's lifecycle has ``FAILED`` and ``TARGET_REACHED`` states; a stateless
    daily scan only knows what qualifies *today*, so this compares the previous
    committed ``signals.json`` with today's signals and classifies each row that
    disappeared using the bars since its ``last_date``:

    * ``FAILED``          -- a close at or below the stop (the spec's invalidation)
    * ``TARGET_REACHED``  -- a high at or above the target
    * ``EXPIRED``         -- a confirmed breakout aged past ``max_breakout_age``
    * ``FADED``           -- the close fell more than ``WATCH_PROXIMITY`` below the entry
    * ``DROPPED``         -- none of the above: the pattern itself no longer qualifies
                             (or there is no price data)

    A bar that touches both levels counts as ``FAILED`` (conservative, like the
    backtest).  Presence is keyed on ``(ticker, pattern)`` so a structure that is
    re-anchored a bar later is not reported as closed.

    :param previous: ``signals`` list from the previous ``signals.json``.
    :param current: Today's signals.
    :param data: ``{symbol: OHLCV frame}`` through today.
    :returns: One dict per closed setup: ticker, pattern, was, since, entry, stop,
        target, outcome, detail.

    Complexity: O(previous * bars since).
    """
    still = {(s.ticker, s.pattern) for s in current}
    out: List[Dict[str, Any]] = []
    for p in previous:
        if (p["ticker"], p["pattern"]) in still:
            continue
        row: Dict[str, Any] = {"ticker": p["ticker"], "pattern": p["pattern"], "was": p["status"],
                               "since": p["last_date"], "entry": p["entry"], "stop": p["stop"],
                               "target": p.get("target"), "outcome": "DROPPED", "detail": ""}
        df = data.get(p["ticker"])
        bars = df[df.index > pd.Timestamp(p["last_date"])] if df is not None else None
        if bars is None or bars.empty:
            row["detail"] = "no bars since the last report" if df is not None else "no price data"
            out.append(row)
            continue
        for d, hi, cl in zip(bars.index, bars["High"], bars["Close"]):
            if cl <= p["stop"]:
                row.update(outcome="FAILED", detail=f"close {cl:.2f} on {d.date()} at or below stop {p['stop']}")
                break
            if p.get("target") is not None and hi >= p["target"]:
                row.update(outcome="TARGET_REACHED", detail=f"high {hi:.2f} on {d.date()} reached target {p['target']}")
                break
        else:
            age = p.get("bars_since_break")
            limit = max_breakout_age(p["pattern"])
            last_close = float(bars["Close"].iloc[-1])
            if p["status"] == "CONFIRMED" and age is not None and age + len(bars) > limit:
                row.update(outcome="EXPIRED", detail=f"breakout {age + len(bars)} bars old, limit {limit}")
            elif last_close < p["entry"] * (1 - WATCH_PROXIMITY):
                row.update(outcome="FADED",
                           detail=f"close {last_close:.2f} more than {WATCH_PROXIMITY:.0%} below entry {p['entry']}")
            else:
                row["detail"] = "pattern no longer qualifies"
        out.append(row)
    return out


def render_markdown(signals: List[Signal], meta: Mapping[str, Any],
                    closed: Optional[Sequence[Mapping[str, Any]]] = None) -> str:
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
        lines.append("| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | Score | Age | Vol× | "
                     "Trend | Details |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s in rows:
            # Age = bars since the breakout close / the pattern's limit, so a reader
            # can see whether a confirmed row is fresh (0/3) or about to expire (3/3).
            age = (f"{s.bars_since_break}/{max_breakout_age(s.pattern)}"
                   if s.bars_since_break is not None else "-")
            lines.append(f"| {s.ticker} | {s.pattern} | {s.entry} | {s.max_buy if s.max_buy else '-'} | {s.stop} | "
                         f"{s.risk_pct} | {s.target if s.target else '-'} | {s.score} | {age} | "
                         f"{s.volume_ratio if s.volume_ratio else '-'} | {s.trend} | {s.notes} |")
        lines.append("")
    if closed is not None:
        since = meta.get("previous_run") or "the last report"
        lines.append(f"## Closed since the last report ({since}): {len(closed)}")
        lines.append("")
        if not closed:
            lines.append("_none_")
            lines.append("")
        else:
            lines.append("| Ticker | Pattern | Was | Outcome | Entry | Stop | Target | Detail |")
            lines.append("|---|---|---|---|---|---|---|---|")
            order = {"TARGET_REACHED": 0, "FAILED": 1, "EXPIRED": 2, "FADED": 3, "DROPPED": 4}
            for c in sorted(closed, key=lambda c: (order[c["outcome"]], c["ticker"])):
                lines.append(f"| {c['ticker']} | {c['pattern']} | {c['was']} | {c['outcome']} | {c['entry']} | "
                             f"{c['stop']} | {c['target'] if c['target'] is not None else '-'} | {c['detail']} |")
            lines.append("")
    lines.append(f"_Max buy = trigger + {MAX_RUNAWAY:.0%}: if the open is above it the setup no longer qualifies. "
                 f"Age = bars since the breakout close / the limit after which the row is dropped "
                 f"(0 = broke out on the last bar). Heuristic scan, not advice. "
                 f"Entry = trigger level, or the breakout close when it "
                 f"is above the trigger (closes more than {MAX_RUNAWAY:.0%} above the trigger are dropped "
                 f"as chasing). Stop = structural level minus 0.25 ATR. Entry is the last close: a trade "
                 f"happens at the next open, so re-check that the open is still within {MAX_RUNAWAY:.0%} "
                 f"of the trigger and recompute risk from the fill. Verify on a chart before trading._")
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
    ap.add_argument("--profile", choices=sorted(RULE_PROFILES), default=ACTIVE_PROFILE,
                    help="rule profile: spec (default) or legacy (rules in force until 2026-09-05)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    apply_profile(args.profile)
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

    filled_close = sum(1 for df in data.values() if df.attrs.get("filled_close"))
    data, bar_info = align_last_bar(data)
    bar_info["filled_close_symbols"] = filled_close
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

    meta: Dict[str, Any] = {"run_date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "universe": len(symbols),
            "scanned": len(data), "errors": len(symbols) - len(data),
            **bar_info,
            "profile": ACTIVE_PROFILE, "min_score": MIN_SCORE, "max_breakout_age": MAX_BREAKOUT_AGE,
            "max_breakout_age_by_pattern": {p: max_breakout_age(p) for p in BREAKOUT_AGE_LAG}}
    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "signals.json")
    previous: List[Dict[str, Any]] = []
    if os.path.exists(out_path):
        try:
            with open(out_path, encoding="utf-8") as fh:
                prev_doc = json.load(fh)
            previous = list(prev_doc.get("signals", []))
            meta["previous_run"] = prev_doc.get("meta", {}).get("run_date")
        except (OSError, ValueError) as exc:  # a corrupt previous file must not stop today's report
            log.warning("previous signals.json unreadable, no close-out: %s", exc)
    closed = close_out(previous, signals, data)
    log.info("closed since the last report: %d (%s)", len(closed),
             ", ".join(f"{c['ticker']} {c['outcome']}" for c in closed) or "none")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "signals": [asdict(s) for s in signals], "closed": closed}, fh, indent=2)
    md = render_markdown(signals, meta, closed)
    with open(os.path.join(args.out_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
