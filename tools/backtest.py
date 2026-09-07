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
* Every summary carries, next to hit rate and mean R: median R, standard
  deviation, total R, the deepest drawdown of the cumulative R curve (1 R per
  trade, in scan order), a 95 % bootstrap interval of the mean R and the
  drawdown exceeded in only 5 % of resamples.  The bootstrap resamples scan
  *months*, not trades: signals cluster in time (33 in one month, 2 in
  another, over 2024-26), so resampling trades as if independent would
  understate the uncertainty.
* ``--split YYYY-MM-DD`` reports the sessions before and from that date as
  separate windows next to the pooled one, so a rule chosen on one window is
  judged on the other -- the out-of-sample check a calibration decision
  should pass (docs/wiki/03).
* ``--grid`` re-scores the same signals under stop / target variants: extra
  ATR below the reported stop (0 / 0.25 / 0.75, i.e. ~0.25 / 0.5 / 1.0 ATR
  under the structural low), intraday vs close-based stops, and three target
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
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan  # noqa: E402
import evaluate_signals as ev  # noqa: E402

log = logging.getLogger("backtest")

SCORE_BUCKETS = ((60, 69), (70, 79), (80, 89), (90, 100))
TARGET_MODES = ("full", "half", "breakout")
GRID = [(extra, basis, mode) for extra in (0.0, 0.25, 0.75) for basis in ("intraday", "close")
        for mode in TARGET_MODES]
TRADED = ("target", "stop", "open")          # outcomes with a position; "gap" / "below_stop" / "no_data" have none
N_BOOT = 2000                                # month-block bootstrap resamples per summary


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


def ablation(data: Dict[str, pd.DataFrame], days: int, horizon: int, bars: Optional[int] = None) -> List[dict]:
    """Leave-one-rule-out over the spec profile.

    Replays the active (spec) profile, then once per key in
    ``RULE_PROFILES["legacy"]`` with only that key set to its legacy value.
    :returns: one summary row per replay: ``{"rule", "value", "delta", **breakdown(...)["overall"]}``.
    """
    base = breakdown(walk_forward(data, days, horizon, bars=bars))["overall"]
    rows = [{"rule": "spec (all rules)", "value": "-", "delta": 0, **base}]
    for key, legacy_value in scan.RULE_PROFILES["legacy"].items():
        saved = getattr(scan, key)
        setattr(scan, key, legacy_value)
        try:
            s = breakdown(walk_forward(data, days, horizon, bars=bars))["overall"]
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


def profile_pass(data: Dict[str, pd.DataFrame], days: int, horizon: int, name: str,
                 bars: Optional[int] = None) -> dict:
    """Second full walk-forward under rule profile ``name`` (the active profile is restored).

    :returns: ``{"profile", "stats", "rows"}`` with the same ``breakdown`` slices as the main report.
    """
    with rule_profile(name):
        rows = walk_forward(data, days, horizon, bars=bars)
    return {"profile": name, "stats": breakdown(rows), "rows": rows}


def walk_forward(data: Dict[str, pd.DataFrame], days: int, horizon: int,
                 detectors: Optional[Sequence] = None, bars: Optional[int] = None) -> List[dict]:
    """Replay the scanner over the last ``days`` sessions and score each first-seen signal.

    :param data: ``{symbol: OHLCV frame}`` as returned by ``download_history``.
    :param days: Number of most recent sessions to scan (each as if it were "today").
    :param horizon: Bars after the fill before an unresolved signal counts as ``open``.
    :param detectors: Subset of detectors to run (default: all).
    :param bars: Bars of history each scan sees (default: everything up to the
        day).  500 mimics the nightly job's 2y download in a longer replay.
    :returns: One dict per first-seen CONFIRMED signal with the signal fields plus
        ``fill``, ``outcome``, ``bars``, ``exit``, ``r`` (and for cups the parsed
        ``cup_bottom`` / ``cup_trigger`` for the breakout-level target variant).
        ``outcome`` is ``target`` / ``stop`` / ``open`` for traded rows, ``gap``
        (open above Max buy) or ``below_stop`` (open at or below the stop) for
        rows not traded, ``no_data`` without a bar after the scan day.

    Complexity: O(days * symbols * detector cost); ~2 ms per symbol-day.
    """
    sessions = sorted({d for df in data.values() for d in df.index})
    scan_days = sessions[-days:] if days < len(sessions) else sessions
    seen: Dict[tuple, dict] = {}
    not_traded = dict(exit=None, r=None, mfe=None, mae=None, success5=None)
    for d in scan_days:
        for sym, df in data.items():
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
                if key in seen:
                    continue
                after = df[df.index > d]
                row = {**scan.asdict(s), "scan_day": str(d.date()),
                       "atr": round(float(scan.atr(hist).iloc[-1]), 4), "cup_bottom": None, "cup_trigger": None}
                if s.pattern == "Cup & Handle":
                    m = re.search(r"bottom \S+ @([\d.]+).*trigger ([\d.]+)", s.notes)
                    if m:
                        row["cup_bottom"], row["cup_trigger"] = float(m[1]), float(m[2])
                if after.empty:
                    row.update(fill=None, outcome="no_data", bars=0, **not_traded)
                else:
                    fill = float(after["Open"].iloc[0])
                    max_buy = s.max_buy if s.max_buy is not None else s.entry * (1 + scan.MAX_RUNAWAY)
                    if fill > max_buy:
                        row.update(fill=round(fill, 2), outcome="gap", bars=0, **not_traded)
                    elif fill <= s.stop:
                        # The open is already through the stop: no trade, and R would be undefined.
                        row.update(fill=round(fill, 2), outcome="below_stop", bars=0, **not_traded)
                    else:
                        res = ev.classify(fill, s.stop, s.target, after, horizon)
                        row.update(fill=round(fill, 2), **res, **excursions(fill, s.stop, after, horizon))
                seen[key] = row
    return list(seen.values())


def breakdown(rows: Sequence[dict]) -> dict:
    """Summary overall, per pattern and per score bucket (rows not traded are excluded from the rates).

    Each summary carries the ``evaluate_signals.summarise`` counts plus
    ``signals``, ``gap``, ``below_stop``, ``median_r``, ``std_r``, ``total_r``,
    ``max_dd`` (cumulative R curve in scan order), the month-block bootstrap
    ``ci_low`` / ``ci_high`` / ``dd_p95`` / ``blocks`` (see
    :func:`block_bootstrap`), ``success5``, ``mfe`` and ``mae``.
    """
    def summ(sub):
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
    out = {"overall": summ(rows), "by_pattern": {}, "by_score": {}}
    for p in sorted({r["pattern"] for r in rows}):
        out["by_pattern"][p] = summ([r for r in rows if r["pattern"] == p])
    for lo, hi in SCORE_BUCKETS:
        sub = [r for r in rows if lo <= r["score"] <= hi]
        if sub:
            out["by_score"][f"{lo}-{hi}"] = summ(sub)
    return out


def report_sections(rows: Sequence[dict], days: int, horizon: int, split: Optional[str] = None,
                    data: Optional[Dict[str, pd.DataFrame]] = None, do_grid: bool = False,
                    other_rows: Optional[Sequence[dict]] = None, other_name: Optional[str] = None) -> List[dict]:
    """One section per window (see :func:`split_windows`): its rows, ``breakdown``
    stats, the stop / target ``grid`` (with ``do_grid`` and ``data``) and the other
    profile's stats over the same window (with ``other_rows``)."""
    windows = split_windows(rows, split)
    others = split_windows(other_rows, split) if other_rows is not None else [(None, None)] * len(windows)
    sections = []
    for (label, rws), (_, o_rws) in zip(windows, others):
        sec: Dict[str, Any] = {"label": label, "rows": rws, "stats": breakdown(rws), "grid": None, "other": None}
        if do_grid and data is not None:
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
    return lines


def render(rows: Sequence[dict], sections: Sequence[dict], days: int, horizon: int) -> str:
    """Markdown report (readable as a GitHub step summary): one block per window, then every signal."""
    lines = [f"# Walk-forward backtest: last {days} sessions, horizon {horizon} bars "
             f"(rule profile: {scan.ACTIVE_PROFILE})", "",
             "Hit rate = target / (target + stop). Mean R over traded signals (open ones marked to the last close). "
             "Fill = next session's open; not traded = the open was above the row's Max buy (gap) or at or below "
             "the stop. 95% CI = bootstrap interval of the mean R that resamples scan months, not trades (signals "
             "cluster in time). Max DD = deepest fall of the cumulative R curve, 1 R per trade in scan order; "
             "DD p95 = the drawdown exceeded in 5 % of the month resamples. "
             "+5% first = share of signals whose high reached +5 % above the fill before any close below the stop "
             "(the chart-book success definition). MFE / MAE = mean best / worst excursion from the fill "
             "within the horizon."]
    if len(sections) > 1:
        lines += ["", "The windows below report the sessions before and from the split date separately: a rule "
                  "chosen on one window is judged on the other."]
    for sec in sections:
        lines += ["", f"## {sec['label'].capitalize()}", ""] + _summary_table(sec["stats"])
        if sec["grid"]:
            lines += ["", f"### Stop / target variants (same signals, {sec['label']})", "",
                      "Extra ATR = distance added below the reported stop (which already sits 0.25 ATR under the "
                      "structural low). Target: full = reported measured move; half = halfway to it; breakout = "
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
    symbols = ([s.strip().upper() for s in args.tickers.split(",") if s.strip()]
               if args.tickers else scan.load_sp500_symbols(args.csv))
    t0 = time.time()
    data = scan.download_history(symbols, period=args.period)
    if not data:
        print("no price data")
        return 2
    log.info("downloaded %d symbols in %.0fs; replaying %d sessions%s", len(data), time.time() - t0, args.days,
             f", each scan sees {args.bars} bars" if args.bars else "")
    if args.ablate:
        scan.apply_profile("spec")
        table = ablation(data, args.days, args.horizon, args.bars)
        log.info("ablation done in %.0fs: %d replays", time.time() - t0, len(table))
        print(render_ablation(table, args.days, args.horizon))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump({"days": args.days, "horizon": args.horizon, "bars": args.bars, "ablation": table},
                          fh, indent=2)
        return 0
    rows = walk_forward(data, args.days, args.horizon, bars=args.bars)
    log.info("replay done in %.0fs: %d first-seen confirmed signals", time.time() - t0, len(rows))
    other_rows = other_name = None
    if args.grid:
        other_name = "legacy" if scan.ACTIVE_PROFILE == "spec" else "spec"
        other_rows = profile_pass(data, args.days, args.horizon, other_name, args.bars)["rows"]
        log.info("%s-profile pass done in %.0fs: %d first-seen confirmed signals",
                 other_name, time.time() - t0, len(other_rows))
    sections = report_sections(rows, args.days, args.horizon, args.split, data, args.grid, other_rows, other_name)
    print(render(rows, sections, args.days, args.horizon))
    if args.json:
        pooled = sections[0]
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"days": args.days, "horizon": args.horizon, "profile": scan.ACTIVE_PROFILE,
                       "min_score": scan.MIN_SCORE, "bars": args.bars, "split": args.split,
                       "stats": pooled["stats"], "grid": pooled["grid"],
                       "other_profile": ({"profile": other_name, "stats": pooled["other"]["stats"], "rows": other_rows}
                                         if other_rows is not None else None),
                       "windows": [{k: s[k] for k in ("label", "stats", "grid", "other")} for s in sections[1:]],
                       "rows": rows}, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
