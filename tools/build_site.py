#!/usr/bin/env python3
"""Build the SignalSync web page: buy signals now, why each stock was triggered, and how past signals turned out.

Why: the nightly scan commits ``output/signals.json`` and a Markdown report;
an e-mail relayed the tables, which was fragile.  A static page rebuilt after
every scan needs no server, no database and no mail: GitHub Pages serves it
for free.

Usage:

    python tools/build_site.py --signals output/signals.json [--evaluation evaluation.json] [--charts charts.json]
                               --out-dir _site

``--evaluation`` is the JSON written by ``tools/evaluate_signals.py --json``
(the live track record, scored with the backtest's accounting); without it
the page says the results are not available yet.  ``--charts`` is the JSON
written by ``tools/site_charts.py`` (the recent bars of every ticker on the
page); with it every stock's "why" block and every watched stock carries a
candlestick chart with the buy zone, stop, target and the pattern's pivots
drawn on it.  ``--fragment`` writes the page without the document wrapper,
for a preview host that supplies its own.  The stylesheet and the script in
``site/`` are inlined, so the output is one self-contained ``index.html``
plus ``data.json`` (the view model).

The page is written for a reader who has never seen the scanner, in the order
they need it:

1. **Buy signals now**: the confirmed rows with the buy limit, the stop loss
   and the take-profit price, one instruction on how to act, and a status
   (new today, day N of the limit, late).  Rows leave when the scanner drops
   them: the stock closed below the stop, the pattern failed, the breakout
   got too old, or the row was listed past ``MAX_LISTED_DAYS`` (#115).
2. **Why these stocks**: per row, the pattern in plain words, the chart with
   the levels and the pivots, the context (trend, volume, fear and greed),
   how the pattern has done over eleven years, and the stocks being watched
   that are not signals yet.
3. **Open trades**: every signal bought and not yet resolved, with the last
   close, the gain or loss so far, the days held and a bar showing where the
   price stands between the stop loss and the take profit.
4. **Closed trades, were we right?**: every resolved signal, counted once at
   its first report and filled at the next open, with the result in price
   terms (took profit at, stopped out at, not bought) and the gain or loss
   in percent.

Every number on the page is the scanner's or the evaluator's; the day on the
list is the scanner's own count.  Nothing here is a new rule or a probability.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SITE_DIR = os.path.join(ROOT, "site")
REPO_URL = "https://github.com/yanivil/SignalSync"

LATE_FROM = 3                                             # day on the list from which an entry is "late"
NO_ENTRY_FROM = {"Bullish Wolfe Wave": 6, "default": 7}   # ... and from which the replay found no edge left
FG_ZONES = ((20.0, "extreme fear"), (40.0, "fear"), (60.0, "neutral"), (80.0, "greed"), (float("inf"), "extreme greed"))
OUTCOME_STATUS = {"target": "closed", "stop": "closed", "expired": "closed", "open": "open",
                  "gap": "none", "below_stop": "none", "no_data": "none"}
CLOSED_PLAIN = {"TARGET_REACHED": "reached its target", "FAILED": "closed below its stop",
                "EXPIRED": "too old to enter", "RETIRED": "listed for the limit of sessions",
                "FADED": "fell away from its trigger", "DROPPED": "pattern no longer valid"}
RESULT_WORDS = {"win": "Win", "loss": "Loss", "flat": "Flat", "open": "Open", "none": "Not bought",
                "pending": "Pending"}
PATTERN_EXPLAINED = {
    "Cup & Handle": "The stock fell and recovered in a rounded curve over weeks or months (the cup), then dipped a "
                    "little (the handle). A daily close above the handle's high is the trigger: the sellers who "
                    "sold into the recovery have been absorbed.",
    "Inverse Head & Shoulders": "Three lows with the middle one the deepest (the head), and the line through the two "
                                "highs between them is the neckline. A daily close above the neckline is the "
                                "trigger: the sellers of the downtrend have run out.",
    "Bullish Wolfe Wave": "Five swings inside a narrowing, falling channel, the fifth briefly undershooting the "
                          "channel's lower line. A daily close back above the line through points 1 and 3 is the "
                          "trigger; the target is where the line through points 1 and 4 will be.",
    "Double Bottom": "Two lows at about the same level with a rally of at least 10 % between them: the second test "
                     "of the low held. A daily close above that rally's peak is the trigger. The stop sits under the "
                     "second low, so the reward is about one pattern height for a similar risk: more wins, smaller "
                     "ones.",
}
# The tuning page's figures the page quotes next to the live numbers (docs/wiki/03-Configuration-and-Tuning.md).
REPLAY_REFERENCE: Dict[str, Any] = {
    "source": "eleven yearly replays on the index as it was, 2016 to 2026, tuned profile, runs 34323013559 to "
              "34323039560 (2026-09-09)",
    "overall": {"trades": 1632, "hit": 0.35, "mean_r": 0.22,
                "note": "positive in ten of eleven years; drawdowns of 36 to 41 R inside four of them"},
    "patterns": {"Inverse Head & Shoulders": {"trades": 1097, "hit": 0.39, "mean_r": 0.23},
                 "Cup & Handle": {"trades": 305, "hit": 0.18, "mean_r": 0.03},
                 "Bullish Wolfe Wave": {"trades": 230, "hit": 0.36, "mean_r": 0.43},
                 "Double Bottom": {"trades": 215, "hit": 0.58, "mean_r": 0.13}},
    "late_entry": [{"day": "1", "trades": 1632, "mean_r": 0.22, "vs_day1": None},
                   {"day": "2", "trades": 1111, "mean_r": 0.28, "vs_day1": -0.01},
                   {"day": "3", "trades": 952, "mean_r": 0.22, "vs_day1": -0.09},
                   {"day": "4 to 5", "trades": 1479, "mean_r": 0.19, "vs_day1": -0.12},
                   {"day": "6 to 9", "trades": 1169, "mean_r": 0.14, "vs_day1": -0.12}],
}
GLOSSARY = (
    ("Buy at the open, up to", "The trade happens at the next market open. The upper number is the most you should "
                               "pay: the lower of trigger + 5 % and the price at which the risk to the stop reaches "
                               "1.5 times the planned one. If the stock opens above it, the signal no longer applies."),
    ("Stop loss", "The pattern's structural low (handle low, right-shoulder low, point 5) minus a quarter of the "
                  "average daily range. Selling on a daily close at or below it did better in the replay than "
                  "selling the moment it is touched."),
    ("Take profit", "The pattern's measured move: the height of the pattern added to the trigger."),
    ("Score", "0 to 100, how clean the geometry is. Rows below 60 are not reported."),
    ("Day on the list", "Sessions since the row was first reported. In eleven years of history a row on its second "
                        "day was as good as new; from the third day the same signals paid about 0.1 R less than on "
                        "day 1; from day 7 (a Wolfe from day 6) nothing was left, so the scanner retires a row "
                        "after its sixth session, a Wolfe after its fifth."),
    ("Fear and greed", "The stock's own reading at the last close, 0 to 100, averaging RSI 14, the MACD histogram's "
                       "percentile over the past year and Bollinger %B. Above 80 the stock is stretched, and such "
                       "breakouts did worst in the replay; below 20 it is washed out. Information, not a rule."),
    ("Watch-only pattern", "A pattern the scanner detects and lists but never turns into a buy signal, because its "
                           "breakouts did not pay over ten years of history: the cup and handle, 18 % of whose "
                           "breakouts reached their target for +0.03 R per signal (#109)."),
    ("R", "One unit of risk: the distance from the buy price to the stop loss. A stop-out is −1 R; a take-profit at "
          "twice that distance is +2 R. It lets signals with different prices be added up."),
    ("Result", "Every signal is counted once, at its first report, bought at the next open. Not bought when that "
               "open was above the buy limit or below the stop. Take profit and stop loss count as touched "
               "during the day (a day touching both counts as a stop). After 60 sessions a position still open is "
               "closed at that day's close (time limit)."),
)


# --------------------------------------------------------------------------- #
# View model
# --------------------------------------------------------------------------- #
def fg_zone(score: Optional[float]) -> Optional[str]:
    """The fear-and-greed zone of a 0-100 reading (``None`` without one)."""
    if score is None:
        return None
    return next(name for edge, name in FG_ZONES if float(score) < edge)


def _key(row: Mapping[str, Any]) -> tuple:
    return (row["ticker"], row["pattern"], round(float(row["stop"]), 2))


def day_on_list(signal: Mapping[str, Any], evaluation_rows: Sequence[Mapping[str, Any]]) -> Optional[int]:
    """Sessions since the signal was first reported.

    The scanner's own ``listed_day`` when the file carries it (the count the
    listing rule retires rows by, from 2026-09-15); before that, the track
    record's ``listed_days``.  ``None`` when neither knows the row, or the
    track record was built before the signal's own session (its
    ``last_listed`` is older than ``last_date``).
    """
    if signal.get("listed_day") is not None:
        return int(signal["listed_day"])
    for r in evaluation_rows:
        if _key(r) == _key(signal):
            return int(r["listed_days"]) if r.get("last_listed") == signal["last_date"] else None
    return None


def grade(pattern: str, day: Optional[int], limit: Optional[int] = None) -> Tuple[str, str]:
    """``(grade, status)``: ``enter`` / ``late`` / ``skip`` by the day on the list (see #115), with the words the
    status cell shows; ``limit`` is the pattern's ``MAX_LISTED_DAYS``."""
    no_entry = NO_ENTRY_FROM.get(pattern, NO_ENTRY_FROM["default"])
    limit = limit or no_entry - 1
    if day is None:
        return "enter", "First report unknown"
    if day == 1:
        return "enter", "New today"
    if day < LATE_FROM:
        return "enter", f"Day {day} of {limit}"
    if day >= no_entry:
        return "skip", f"Day {day}: too late to enter"
    return "late", f"Day {day} of {limit}: late, smaller edge"


def late_note(pattern: str, grade_: str, day: Optional[int]) -> str:
    """The sentence a late or too-late row carries; empty for a fresh one."""
    if grade_ == "late":
        return (f"This signal is on its day {day}. In eleven years of history, buying this late earned about 0.1 R "
                f"less than buying on day 1, still positive on average. Only inside the buy range.")
    if grade_ == "skip":
        no_entry = NO_ENTRY_FROM.get(pattern, NO_ENTRY_FROM["default"])
        return (f"Day {day} on the list: from day {no_entry} the history shows no edge left for late buyers of this "
                f"pattern. Do not buy; the row stays only until it expires.")
    return ""


def _pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 1)


def _pivots(notes: str) -> List[Tuple[str, str, float]]:
    """``(label, date, price)`` of every anchor a signal's notes name, e.g. ``RS 2026-08-26 @32.88``."""
    return [(m.group(1).strip(" ,"), m.group(2), float(m.group(3)))
            for m in re.finditer(r"([A-Za-z0-9 ]+?) (\d{4}-\d{2}-\d{2}) @([\d.]+)", notes or "")]


def setup_view(signal: Mapping[str, Any], meta: Mapping[str, Any],
               evaluation_rows: Sequence[Mapping[str, Any]],
               charts: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """One confirmed row as the page shows it (``charts``: ``symbols`` of the charts JSON)."""
    day = day_on_list(signal, evaluation_rows)
    limit = (meta.get("max_listed_days") or {}).get(signal["pattern"])
    g, status = grade(signal["pattern"], day, limit)
    entry, stop, target = float(signal["entry"]), float(signal["stop"]), signal.get("target")
    limits = meta.get("max_breakout_age_by_pattern") or {}
    vr = signal.get("volume_ratio")
    chips: List[Tuple[str, str]] = []
    market = meta.get("market") or {}
    if market.get("regime"):
        chips.append((f"Market: {market['regime']} trend", {"bull": "good", "bear": "bad"}.get(market["regime"], "")))
    for part in (signal.get("trend") or "").split(", "):
        if part:
            chips.append((part[0].upper() + part[1:], "warn" if "below SMA200" in part or "falling" in part else ""))
    if vr is not None:
        chips.append((f"Breakout volume {vr:.2f}× the average" if vr >= 1.0
                      else f"Breakout volume {vr:.2f}×, below average", "" if vr >= 1.0 else "warn"))
    fg = signal.get("fear_greed")
    zone = fg_zone(fg)
    if fg is not None:
        chips.append((f"Fear and greed {fg:.0f}, {zone}", "bad" if fg >= 80 else ("warn" if fg >= 60 else "")))
    ref = REPLAY_REFERENCE["patterns"].get(signal["pattern"])
    return {"ticker": signal["ticker"], "pattern": signal["pattern"], "score": signal["score"], "day": day,
            "list_limit": limit, "grade": g, "status": status, "note": late_note(signal["pattern"], g, day),
            "entry": entry, "max_buy": signal.get("max_buy"), "stop": stop, "target": target,
            "risk_pct": round(-_pct(stop, entry), 1),
            "reward_pct": _pct(float(target), entry) if target else None, "reward_risk": signal.get("reward_risk"),
            "last_close": signal.get("last_close"), "age": signal.get("bars_since_break"),
            "age_limit": limits.get(signal["pattern"]), "volume_ratio": vr, "fear_greed": fg, "fg_zone": zone,
            "trend": signal.get("trend"), "notes": signal.get("notes"), "chips": chips,
            "explained": PATTERN_EXPLAINED.get(signal["pattern"], ""), "reference": ref,
            "pivots": _pivots(signal.get("notes") or ""), "chart": (charts or {}).get(signal["ticker"])}


def watch_view(signal: Mapping[str, Any], charts: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """One watched row as the page shows it."""
    entry, last = float(signal["entry"]), signal.get("last_close")
    return {"ticker": signal["ticker"], "pattern": signal["pattern"], "score": signal["score"], "trigger": entry,
            "max_buy": signal.get("max_buy"), "last_close": last,
            "to_trigger_pct": _pct(entry, float(last)) if last else None, "stop": float(signal["stop"]),
            "target": signal.get("target"), "reward_risk": signal.get("reward_risk"),
            "fear_greed": signal.get("fear_greed"), "fg_zone": fg_zone(signal.get("fear_greed")),
            "trend": signal.get("trend"), "notes": signal.get("notes"),
            "watch_only": bool(signal.get("watch_only")), "broke_out": signal.get("bars_since_break"),
            "pivots": _pivots(signal.get("notes") or ""), "chart": (charts or {}).get(signal["ticker"])}


def result_text(row: Mapping[str, Any]) -> Tuple[str, str]:
    """``(label, sentence)`` of one past signal in price terms: ``win`` / ``loss`` / ``flat`` / ``open`` /
    ``none`` (not bought) / ``pending`` (no bar after the signal yet)."""
    o, exit_, date, fill = row["outcome"], row.get("exit"), row.get("exit_date"), row.get("fill")
    if o == "target":
        return "win", f"Took profit at {float(exit_):.2f} on {date}"
    if o == "stop":
        return "loss", f"Stopped out at {float(exit_):.2f} on {date}"
    if o == "expired":
        pnl = row.get("pnl_pct") or 0.0
        label = "win" if pnl > 0 else ("loss" if pnl < 0 else "flat")
        return label, f"Time limit reached: closed at {float(exit_):.2f} on {date}"
    if o == "open":
        return "open", f"Still open: last close {float(exit_):.2f} on {date}"
    if o == "gap":
        return "none", f"Not bought: it opened at {float(fill):.2f}, above the buy limit"
    if o == "below_stop":
        return "none", f"Not bought: it opened at {float(fill):.2f}, below the stop loss"
    return "pending", "Signal from the last scan: the buy happens at the next open"


def results_view(evaluation: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Past signals in the order they were reported, each with its result in words, plus the tally."""
    if not evaluation:
        return {"available": False, "rows": [], "open": [], "closed": [], "summary": None}
    rows = sorted(evaluation.get("rows", []), key=lambda r: (r["last_date"], r["ticker"]))
    out = []
    for r in rows:
        label, text = result_text(r)
        out.append({"date": r["last_date"], "ticker": r["ticker"], "pattern": r["pattern"], "bought": r.get("fill"),
                    "stop": r["stop"], "target": r.get("target"), "outcome": r["outcome"], "label": label,
                    "text": text, "pnl_pct": r.get("pnl_pct"), "r": r.get("r"), "listed_days": r.get("listed_days"),
                    "exit": r.get("exit"), "exit_date": r.get("exit_date"), "fill_date": r.get("fill_date"),
                    "bars": r.get("bars")})
    closed = [x for x in out if x["outcome"] in ("target", "stop", "expired") and x["pnl_pct"] is not None]
    open_ = [x for x in out if x["label"] in ("open", "pending")]
    done = [x for x in out if x["label"] not in ("open", "pending")]
    summary = {"n": len(out), "wins": sum(1 for x in out if x["label"] == "win"),
               "losses": sum(1 for x in out if x["label"] == "loss"),
               "flat": sum(1 for x in out if x["label"] == "flat"),
               "open": sum(1 for x in out if x["label"] == "open"),
               "not_bought": sum(1 for x in out if x["label"] == "none"),
               "pending": sum(1 for x in out if x["label"] == "pending"),
               "avg_pnl_pct": round(sum(x["pnl_pct"] for x in closed) / len(closed), 1) if closed else None,
               "since": out[0]["date"] if out else None}
    return {"available": True, "rows": out, "open": open_, "closed": done, "summary": summary}


def track_view(evaluation: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The technical track record: rows in signal order with a status, the summary and the cumulative-R curve."""
    if not evaluation:
        return {"available": False, "rows": [], "summary": None, "curve": [], "horizon": None, "since": None}
    rows = sorted(evaluation.get("rows", []), key=lambda r: (r["last_date"], r["ticker"]))
    curve, total = [], 0.0
    out = []
    for r in rows:
        status = OUTCOME_STATUS.get(r["outcome"], "none")
        if status != "none" and r.get("r") is not None:
            total += float(r["r"])
            curve.append(round(total, 2))
        out.append({**r, "status": status, "label": result_text(r)[1]})
    return {"available": True, "rows": out, "summary": evaluation.get("summary"), "curve": curve,
            "horizon": evaluation.get("horizon"), "since": rows[0]["last_date"] if rows else None}


def view_model(doc: Mapping[str, Any], evaluation: Optional[Mapping[str, Any]],
               today: Optional[dt.date] = None, charts: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Everything the page shows, as plain data (also written as ``data.json``)."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    meta = doc.get("meta", {})
    ev_rows = (evaluation or {}).get("rows", [])
    symbols = (charts or {}).get("symbols") or {}
    signals = doc.get("signals", [])
    last_bar = meta.get("last_bar")
    stale_days = (today - dt.date.fromisoformat(last_bar)).days if last_bar else None
    setups = sorted((setup_view(s, meta, ev_rows, symbols) for s in signals if s.get("status") == "CONFIRMED"),
                    key=lambda v: (-v["score"]))
    watch = sorted((watch_view(s, symbols) for s in signals if s.get("status") == "WATCHLIST"),
                   key=lambda v: -v["score"])
    return {"generated": today.isoformat(),
            "scan": {k: meta.get(k) for k in ("run_date", "last_bar", "scanned", "universe", "errors", "profile",
                                               "previous_run", "skipped_bar", "lagging_symbols", "min_score",
                                               "watch_only_patterns")}
            | {"stale_days": stale_days},
            "market": meta.get("market"), "setups": setups, "watchlist": watch,
            "charts_as_of": (charts or {}).get("as_of"),
            "closed": [{**c, "plain": CLOSED_PLAIN.get(c.get("outcome"), str(c.get("outcome")).lower())}
                       for c in doc.get("closed") or []],
            "results": results_view(evaluation), "track": track_view(evaluation), "reference": REPLAY_REFERENCE}


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def _e(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _num(x: Optional[float], digits: int = 2) -> str:
    return "–" if x is None else f"{float(x):.{digits}f}"


def _signed(x: Optional[float], digits: int = 2, suffix: str = "") -> str:
    return "–" if x is None else f"{float(x):+.{digits}f}{suffix}"


def _chip(text: str, kind: str = "") -> str:
    return f'<span class="chip {kind}">{_e(text)}</span>' if kind else f'<span class="chip">{_e(text)}</span>'


def _rcls(x: Optional[float]) -> str:
    return "" if x is None else (" pos" if float(x) > 0 else (" neg" if float(x) < 0 else ""))


def sparkline(curve: Sequence[float], width: int = 600, height: int = 120) -> str:
    """Inline SVG of the cumulative R curve (one point per traded signal, starting at 0)."""
    pts = [0.0] + [float(v) for v in curve]
    lo, hi = min(pts + [0.0]), max(pts + [0.0])
    span = (hi - lo) or 1.0
    pad = 12
    xs = [pad + i * (width - 2 * pad) / max(len(pts) - 1, 1) for i in range(len(pts))]
    ys = [height - pad - (p - lo) / span * (height - 2 * pad) for p in pts]
    zero = height - pad - (0.0 - lo) / span * (height - 2 * pad)
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    dots = "".join(f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="3"/>' for x, y in zip(xs[1:], ys[1:]))
    return (f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="Cumulative R after each signal: {pts[-1]:+.2f} R after {len(curve)} trades">'
            f'<line class="zero" x1="{pad}" y1="{zero:.1f}" x2="{width - pad}" y2="{zero:.1f}"/>'
            f'<polyline class="line" points="{line}"/>{dots}'
            f'<text class="spark-label" x="{width - pad}" y="{ys[-1] - 6:.1f}" text-anchor="end">'
            f'{pts[-1]:+.2f} R</text></svg>')


def chart_svg(series: Mapping[str, Sequence[Any]], levels: Mapping[str, Optional[float]],
              pivots: Sequence[Tuple[str, str, float]], ticker: str, width: int = 640, height: int = 260) -> str:
    """Inline SVG candlestick chart of ``series`` (dates, open, high, low, close) with the levels drawn on it.

    The buy zone (entry to Max buy) is a band, the stop and the target dashed
    lines with labels; a target more than 20 % above the highest bar is not
    drawn but named at the top, so the bars keep their scale.  Pivots whose
    date falls inside the window are marked and labelled.  Empty below two bars.
    """
    dates = list(series.get("dates") or [])
    opens, highs, lows, closes = (list(map(float, series.get(k) or [])) for k in ("open", "high", "low", "close"))
    n = len(closes)
    if n < 2 or not (len(dates) == len(opens) == len(highs) == len(lows) == n):
        return ""
    left, right, top, bottom = 8, 64, 14, 24
    pw, ph = width - left - right, height - top - bottom
    entry, max_buy, stop, target = (levels.get(k) for k in ("entry", "max_buy", "stop", "target"))
    lo = min(lows + ([float(stop)] if stop is not None else []))
    hi = max(highs + ([float(max_buy or entry)] if (max_buy or entry) is not None else []))
    clipped = target is not None and float(target) > hi * 1.2
    if target is not None and not clipped:
        hi = max(hi, float(target))
    pad = (hi - lo) * 0.04 or 1.0
    lo, hi = lo - pad, hi + pad

    def y(v: float) -> float:
        return top + (hi - v) / (hi - lo) * ph

    step = pw / n

    def x(i: int) -> float:
        return left + (i + 0.5) * step

    bw = max(1.5, step * 0.6)
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{_e(ticker)}, daily bars '
             f'{_e(dates[0])} to {_e(dates[-1])} with the buy zone, stop and target">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        parts.append(f'<line class="grid" x1="{left}" y1="{y(v):.1f}" x2="{left + pw}" y2="{y(v):.1f}"/>'
                     f'<text class="axis" x="{left + pw + 6}" y="{y(v) + 4:.1f}">{v:.2f}</text>')
    if entry is not None:
        z_top, z_bot = y(max(float(max_buy or entry), float(entry))), y(float(entry))
        parts.append(f'<rect class="zone" x="{left}" y="{z_top:.1f}" width="{pw}" '
                     f'height="{max(z_bot - z_top, 1):.1f}"/>')
    for i in range(n):
        o, h, low_, c = opens[i], highs[i], lows[i], closes[i]
        cx, body_top, body_bot = x(i), y(max(o, c)), y(min(o, c))
        parts.append(f'<line class="wick" x1="{cx:.1f}" y1="{y(h):.1f}" x2="{cx:.1f}" y2="{y(low_):.1f}"/>'
                     f'<rect class="{"up" if c >= o else "down"}" x="{cx - bw / 2:.1f}" y="{body_top:.1f}" '
                     f'width="{bw:.1f}" height="{max(body_bot - body_top, 1):.1f}"/>')
    if stop is not None:
        parts.append(f'<line class="stop" x1="{left}" y1="{y(float(stop)):.1f}" x2="{left + pw}" '
                     f'y2="{y(float(stop)):.1f}"/><text class="lvl stop-l" x="{left + 4}" '
                     f'y="{y(float(stop)) - 4:.1f}">stop loss {float(stop):.2f}</text>')
    if target is not None:
        if clipped:
            parts.append(f'<text class="lvl target-l" x="{left + 4}" y="{top + 10}">take profit {float(target):.2f}, '
                         f'above this chart</text>')
        else:
            parts.append(f'<line class="target" x1="{left}" y1="{y(float(target)):.1f}" x2="{left + pw}" '
                         f'y2="{y(float(target)):.1f}"/><text class="lvl target-l" x="{left + 4}" '
                         f'y="{y(float(target)) - 4:.1f}">take profit {float(target):.2f}</text>')
    index = {d: i for i, d in enumerate(dates)}
    for label, day, price in pivots:
        if day in index:
            px, py = x(index[day]), y(float(price))
            parts.append(f'<circle class="pivot" cx="{px:.1f}" cy="{py:.1f}" r="4"/>'
                         f'<text class="pivot-l" x="{px + 6:.1f}" y="{py + 4:.1f}">{_e(label)}</text>')
    for i, anchor in ((0, "start"), (n // 2, "middle"), (n - 1, "end")):
        parts.append(f'<text class="axis" x="{x(i):.1f}" y="{height - 6}" text-anchor="{anchor}">{_e(dates[i])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def progress_svg(stop: float, target: Optional[float], bought: float, last: float, width: int = 260) -> str:
    """Inline SVG bar from the stop loss (left) to the take profit (right) with the buy price and the last close.

    Without a target the bar runs from the stop to twice the buy price's distance above it.  Empty when
    the stop is not below the buy price."""
    stop, bought, last = float(stop), float(bought), float(last)
    if bought <= stop:
        return ""
    top = float(target) if target is not None else bought + (bought - stop)
    span = top - stop
    left, right, h = 8, width - 8, 34

    def x(v: float) -> float:
        return left + max(0.0, min(1.0, (v - stop) / span)) * (right - left)

    return (f'<svg class="progress" viewBox="0 0 {width} {h}" role="img" aria-label="Last close {last:.2f} between '
            f'the stop loss {stop:.2f} and the take profit {top:.2f}">'
            f'<line class="rail" x1="{left}" y1="12" x2="{right}" y2="12"/>'
            f'<circle class="p-stop" cx="{left}" cy="12" r="4"/><circle class="p-target" cx="{right}" cy="12" r="4"/>'
            f'<line class="p-buy" x1="{x(bought):.1f}" y1="5" x2="{x(bought):.1f}" y2="19"/>'
            f'<circle class="p-last" cx="{x(last):.1f}" cy="12" r="5"/>'
            f'<text class="p-l" x="{left}" y="30" text-anchor="start">{stop:.2f}</text>'
            f'<text class="p-l" x="{right}" y="30" text-anchor="end">{top:.2f}</text></svg>')


def _levels(v: Mapping[str, Any], entry: Optional[float]) -> Dict[str, Optional[float]]:
    return {"entry": entry, "max_buy": v.get("max_buy"), "stop": v.get("stop"), "target": v.get("target")}


def _header(vm: Mapping[str, Any]) -> str:
    scan, market = vm["scan"], vm.get("market") or {}
    bits = [f"Scan {scan['run_date']} UTC" if scan.get("run_date") else "No scan yet",
            f"prices through {scan['last_bar']}" if scan.get("last_bar") else "",
            f"{scan['scanned']} of {scan['universe']} S&P 500 stocks" if scan.get("scanned") else ""]
    meta_line = " · ".join(b for b in bits if b)
    notes = []
    if scan.get("stale_days") is not None and scan["stale_days"] > 4:
        notes.append(f"The last price is {scan['stale_days']} days old: the scan may not have run.")
    if scan.get("skipped_bar"):
        notes.append(f"Newest day {scan['skipped_bar']} not scanned (incomplete at the data source).")
    if scan.get("errors"):
        notes.append(f"{scan['errors']} stock(s) without data.")
    strip = []
    if market:
        strip.append(_chip(f"{market['regime'].capitalize()} trend",
                           {"bull": "good", "bear": "bad", "neutral": "info"}.get(market["regime"], "")))
        strip.append(_chip(f"{market.get('index', 'SPY')} {market['index_vs_sma200_pct']:+.1f} % vs its "
                           f"200-day average"))
        if market.get("vix") is not None:
            strip.append(_chip(f"VIX {market['vix']:.1f}", "warn" if market["vix"] >= 25 else ""))
        if market.get("breadth") is not None:
            strip.append(_chip(f"{market['breadth']:.0%} of stocks above their 200-day average"))
    return (f'<header class="top"><div><h1>SignalSync <small>S&amp;P 500 chart-pattern signals</small></h1>'
            f'<div class="meta">{_e(meta_line)}</div></div>'
            f'<nav class="sections"><a href="#now">1. Buy signals</a><a href="#why">2. Why</a>'
            f'<a href="#open">3. Open trades</a><a href="#results">4. Closed trades</a>'
            f'<a href="#how">How to read</a></nav></header>'
            + (f'<p class="callout">{_e(" ".join(notes))}</p>' if notes else "")
            + (f'<div class="strip">{"".join(strip)}</div>' if strip else ""))


def _glance(vm: Mapping[str, Any]) -> str:
    res = vm["results"]
    n_now, n_watch = len(vm["setups"]), len(vm["watchlist"])
    bits = [f"{n_now} buy signal{'s' if n_now != 1 else ''}", f"{n_watch} stock{'s' if n_watch != 1 else ''} watched"]
    if res["available"] and res["summary"]:
        s = res["summary"]
        n_open = len(res["open"])
        bits.append(f"{n_open} open trade{'s' if n_open != 1 else ''}")
        bits.append(f"closed trades: {s['wins']} won, {s['losses']} lost")
    return f'<p class="glance">Today: {_e(" · ".join(bits))}.</p>'


def _status_badge(v: Mapping[str, Any]) -> str:
    return f'<span class="badge badge-{v["grade"]}">{_e(v["status"])}</span>'


def _signal_row(v: Mapping[str, Any]) -> str:
    note = f'<div class="sub">{_e(v["note"])}</div>' if v["note"] else ""
    gain = _signed(v["reward_pct"], 1, " %") if v.get("target") else "no target"
    return (f'<tr><td><a href="#why-{_e(v["ticker"])}"><strong>{_e(v["ticker"])}</strong></a></td>'
            f'<td>{_e(v["pattern"])}</td>'
            f'<td class="num"><strong>{_num(v["max_buy"] or v["entry"])}</strong>'
            f'<div class="sub">last close {_num(v["last_close"])}</div></td>'
            f'<td class="num neg"><strong>{_num(v["stop"])}</strong>'
            f'<div class="sub">{_num(v["risk_pct"], 1)} % below</div></td>'
            f'<td class="num pos"><strong>{_num(v["target"])}</strong><div class="sub">{gain}</div></td>'
            f'<td>{_status_badge(v)}{note}</td></tr>')


def _signals_now(vm: Mapping[str, Any]) -> str:
    head = f'<h2 id="now"><span class="num">1</span>Buy signals now<span class="count">{len(vm["setups"])}</span></h2>'
    if not vm["setups"]:
        return head + ('<p class="empty">No buy signal today. Nothing to do. The stocks being watched are in '
                       'section 2; one becomes a signal only after a daily close above its trigger.</p>')
    rows = "".join(_signal_row(v) for v in vm["setups"])
    return (head
            + '<div class="instruction"><strong>How to act.</strong> Buy at the next market open, only if the stock '
              'opens at or below the "buy up to" price. Sell if a day closes at or below the stop loss. Sell at the '
              'take-profit price. A signal stays here while it is still valid and leaves when the stock closes below '
              'its stop, the pattern fails, or the row is too old to enter. Once you are in, follow the trade in '
              '<a href="#open">section 3</a>.</div>'
            '<div class="table-wrap"><table class="signals"><thead><tr><th>Stock</th><th>Pattern</th>'
            '<th class="num">Buy up to</th><th class="num">Stop loss</th><th class="num">Take profit</th>'
            f'<th>Status</th></tr></thead><tbody>{rows}</tbody></table></div>')


def _why_block(v: Mapping[str, Any]) -> str:
    when = {0: "The breakout is the last session", 1: "The breakout was 1 session ago"}.get(
        v.get("age"), f"The breakout was {v.get('age')} sessions ago")
    age = (when + (f"; the row is dropped after {v['age_limit']}" if v.get("age_limit") else "") + "."
           if v.get("age") is not None else "")
    ref = v.get("reference")
    ref_line = (f"Over eleven years of history this pattern gave {ref['trades']} signals, {ref['hit']:.0%} reached "
                f"their target, and the average result was {ref['mean_r']:+.2f} R per signal." if ref else "")
    chart = chart_svg(v["chart"], _levels(v, v["entry"]), v["pivots"], v["ticker"]) if v.get("chart") else ""
    return (f'<section class="why" id="why-{_e(v["ticker"])}">'
            f'<h3><span class="ticker">{_e(v["ticker"])}</span><span class="pattern">{_e(v["pattern"])}</span>'
            f'<span class="muted">score {_e(v["score"])} of 100</span>{_status_badge(v)}</h3>'
            f'<p>{_e(v["explained"])}</p>'
            f'<p class="details"><strong>Here:</strong> {_e(v.get("notes"))}. {_e(age)}</p>'
            + chart
            + f'<div class="chips">{"".join(_chip(t, k) for t, k in v["chips"])}</div>'
            + (f'<p class="note late">{_e(v["note"])}</p>' if v["note"] else "")
            + (f'<p class="reference">{_e(ref_line)}</p>' if ref_line else "") + "</section>")


def _watching(vm: Mapping[str, Any]) -> str:
    rows = "".join(_watch_row(w) for w in vm["watchlist"])
    watch_only = [p for p in (vm["scan"].get("watch_only_patterns") or []) if p]
    anchors = "".join(
        f'<li><strong>{_e(w["ticker"])}</strong> {_e(w.get("notes"))}'
        + (chart_svg(w["chart"], _levels(w, w["trigger"]), w["pivots"], w["ticker"]) if w.get("chart") else "")
        + "</li>" for w in vm["watchlist"] if w.get("notes") or w.get("chart"))
    table = ('<div class="table-wrap"><table><thead><tr><th>Stock</th><th>Pattern</th>'
             '<th class="num">Needs a close above</th><th class="num">Last close</th><th class="num">Distance</th>'
             '<th class="num">Stop loss if it triggers</th><th class="num">Take profit if it triggers</th>'
             f'</tr></thead><tbody>{rows}</tbody></table></div>'
             + (f'<details class="anchors"><summary>Their charts and pattern anchors</summary><ul>{anchors}'
                '</ul></details>' if anchors else "")
             if rows else '<p class="note">Nothing is being watched right now.</p>')
    removed = ", ".join(f"{c['ticker']} ({c['plain']})" for c in vm["closed"])
    only = (f' {_e(" and ".join(watch_only))} is watch-only: over ten years only 18 % of its breakouts reached '
            f'their target, so its rows are listed here for information and never become a buy signal, even after '
            f'they break out.' if watch_only else "")
    return (f'<h3 id="watching">Watching, not a signal yet<span class="count">{len(vm["watchlist"])}</span></h3>'
            '<p class="note">These patterns are complete but the stock has not closed above its trigger. Do nothing; '
            f'a stock moves up to section 1 the day it does.{only}</p>' + table
            + (f'<p class="note">Left the page since the previous scan: {_e(removed)}.</p>' if removed else ""))


def _watch_row(w: Mapping[str, Any]) -> str:
    if w.get("watch_only") and w.get("broke_out") is not None:
        n = int(w["broke_out"])
        when = "in the last session" if n == 0 else f"{n} session{'s' if n != 1 else ''} ago"
        needs = f'<td class="num">{_num(w["trigger"])}<div class="sub">broke out {when}: watch-only</div></td>'
        dist = '<td class="num">–</td>'
    else:
        needs = f'<td class="num">{_num(w["trigger"])}</td>'
        dist = f'<td class="num">{_signed(w["to_trigger_pct"], 1, " %")}</td>'
    return (f'<tr><td><strong>{_e(w["ticker"])}</strong></td><td>{_e(w["pattern"])}'
            + ('<div class="sub">watch-only</div>' if w.get("watch_only") else "") + '</td>'
            + needs + f'<td class="num">{_num(w["last_close"])}</td>' + dist
            + f'<td class="num">{_num(w["stop"])}</td><td class="num">{_num(w["target"])}</td></tr>')


def _why(vm: Mapping[str, Any]) -> str:
    head = '<h2 id="why"><span class="num">2</span>Why these stocks</h2>'
    blocks = "".join(_why_block(v) for v in vm["setups"]) or \
        '<p class="note">No stock to explain today: there is no buy signal.</p>'
    return head + blocks + _watching(vm)


def _open_row(r: Mapping[str, Any]) -> str:
    if r["label"] == "pending":
        return (f'<tr><td><strong>{_e(r["ticker"])}</strong></td><td>{_e(r["pattern"])}</td>'
                f'<td class="num">–<div class="sub">at the next open</div></td><td class="num">{_num(r["stop"])}</td>'
                f'<td class="num">{_num(r["target"])}</td><td class="num">–</td><td class="num">–</td>'
                f'<td><span class="badge badge-pending">Pending</span><div class="sub">{_e(r["text"])}</div></td>'
                f'<td class="num">0</td></tr>')
    bar = (progress_svg(r["stop"], r.get("target"), r["bought"], r["exit"])
           if r.get("bought") is not None and r.get("exit") is not None else "")
    return (f'<tr><td><strong>{_e(r["ticker"])}</strong></td><td>{_e(r["pattern"])}</td>'
            f'<td class="num">{_num(r["bought"])}<div class="sub">{_e(r.get("fill_date"))}</div></td>'
            f'<td class="num neg">{_num(r["stop"])}</td><td class="num pos">{_num(r["target"])}</td>'
            f'<td class="num">{_num(r["exit"])}<div class="sub">{_e(r.get("exit_date"))}</div></td>'
            f'<td class="num{_rcls(r["pnl_pct"])}"><strong>{_signed(r["pnl_pct"], 1, " %")}</strong></td>'
            f'<td>{bar}</td><td class="num">{_e(r.get("bars"))}</td></tr>')


def _open_trades(vm: Mapping[str, Any]) -> str:
    head = '<h2 id="open"><span class="num">3</span>Open trades</h2>'
    res = vm["results"]
    if not res["available"]:
        return head + '<p class="note">The results are not available in this build.</p>'
    if not res["open"]:
        return head + '<p class="empty">No open trade. Every signal so far has been resolved; see section 4.</p>'
    rows = "".join(_open_row(r) for r in res["open"])
    return (head
            + '<p class="note">Every signal, bought at the open after its report, until it is resolved. Sell if a day '
              'closes at or below the stop loss; take profit at the target. A trade moves to section 4 the morning '
              'after its low touches the stop, its high touches the target, or 60 sessions pass. The bar shows where '
              'the last close (blue) stands between the stop loss (red) and the take profit (green); the tick is the '
              'buy price.</p>'
              '<div class="table-wrap"><table class="open"><thead><tr><th>Stock</th><th>Pattern</th>'
              '<th class="num">Bought at</th><th class="num">Stop loss</th><th class="num">Take profit</th>'
              '<th class="num">Last close</th><th class="num">Gain / loss</th><th>Where it stands</th>'
              f'<th class="num">Days held</th></tr></thead><tbody>{rows}</tbody></table></div>')


def _results(vm: Mapping[str, Any]) -> str:
    head = '<h2 id="results"><span class="num">4</span>Closed trades: were we right?</h2>'
    res = vm["results"]
    if not res["available"]:
        return head + '<p class="note">The results are not available in this build.</p>'
    s = res["summary"]
    n_closed = len(res["closed"])
    tally = (f'{n_closed} closed trade{"s" if n_closed != 1 else ""} since {s["since"]}: '
             f'<strong>{s["wins"]} took profit</strong>, <strong>{s["losses"]} stopped out</strong>'
             + (f', {s["flat"]} closed flat' if s["flat"] else "")
             + (f', {s["not_bought"]} not bought' if s["not_bought"] else "") + "."
             + (f' Average result on the closed ones: <strong class="{_rcls(s["avg_pnl_pct"]).strip()}">'
                f'{_signed(s["avg_pnl_pct"], 1, " %")}</strong>.' if s["avg_pnl_pct"] is not None else ""))
    rows = "".join(
        f'<tr><td class="date">{_e(r["date"])}</td><td><strong>{_e(r["ticker"])}</strong></td>'
        f'<td>{_e(r["pattern"])}</td>'
        f'<td class="num">{_num(r["bought"])}</td><td class="num">{_num(r["stop"])}</td>'
        f'<td class="num">{_num(r["target"])}</td>'
        f'<td><span class="badge badge-{r["label"]}">{_e(RESULT_WORDS[r["label"]])}</span>'
        f'<div class="sub">{_e(r["text"])}</div></td>'
        f'<td class="num{_rcls(r["pnl_pct"])}"><strong>{_signed(r["pnl_pct"], 1, " %")}</strong></td></tr>'
        for r in res["closed"])
    table = ('<div class="table-wrap"><table class="results"><thead><tr><th>Signal</th><th>Stock</th><th>Pattern</th>'
             '<th class="num">Bought at</th><th class="num">Stop loss</th><th class="num">Take profit</th>'
             f'<th>Result</th><th class="num">Gain / loss</th></tr></thead><tbody>{rows}</tbody></table></div>'
             if rows else '<p class="note">No trade has been resolved yet.</p>')
    ref = vm["reference"]["overall"]
    honest = (f'<p class="note">Counted the same way as the eleven-year replay: bought at the next open after the '
              f'first report, not bought when that open was above the buy limit or below the stop, take profit and '
              f'stop loss as touched during the day. For scale, the replay made {ref["mean_r"]:+.2f} R per signal on '
              f'{ref["trades"]} signals with {ref["hit"]:.0%} reaching their target, {ref["note"]}. A live sample this '
              f'small says little either way.</p>')
    return head + f'<p class="tally">{tally}</p>' + table + honest + _technical(vm)


def _technical(vm: Mapping[str, Any]) -> str:
    """The R-based track record, folded away for the reader who wants it."""
    t = vm["track"]
    if not t["available"] or not t["rows"]:
        return ""
    s = t["summary"] or {}
    resolved = s.get("target", 0) + s.get("stop", 0)
    hit = f"{s['hit_rate']:.0%}" if s.get("hit_rate") is not None else "–"
    rows = "".join(
        f'<tr data-status="{r["status"]}"><td>{_e(r["last_date"])}</td><td><strong>{_e(r["ticker"])}</strong></td>'
        f'<td class="num">{_e(r.get("listed_days"))}</td><td class="num">{_num(r.get("fill"))}</td>'
        f'<td class="num">{_num(r.get("exit"))}</td><td class="num">{_e(r.get("bars"))}</td>'
        f'<td class="num{_rcls(r.get("r"))}">{_signed(r.get("r"))}</td></tr>' for r in t["rows"])
    return ('<details class="more"><summary>In units of risk (R), for the curious</summary>'
            f'<p class="note">Hit rate {hit} on {resolved} '
            f'resolved, mean {_signed(s.get("mean_r"))} R, total {_signed(s.get("total_r"))} R over the horizon of '
            f'{_e(t.get("horizon"))} sessions. One R is the distance from the buy price to the stop loss.</p>'
            + (sparkline(t["curve"]) if t["curve"] else "")
            + '<div class="filters" role="group" aria-label="Filter">'
              '<button type="button" data-filter="all" aria-pressed="true">All</button>'
              '<button type="button" data-filter="open" aria-pressed="false">Open</button>'
              '<button type="button" data-filter="closed" aria-pressed="false">Closed</button></div>'
              '<div class="table-wrap"><table id="track-table"><thead><tr><th>Signal</th><th>Stock</th>'
              '<th class="num">Sessions listed</th><th class="num">Bought at</th><th class="num">Exit</th>'
              f'<th class="num">Sessions held</th><th class="num">R</th></tr></thead><tbody>{rows}</tbody>'
              '</table></div></details>')


def _how(vm: Mapping[str, Any]) -> str:
    ref = vm["reference"]
    pat = "".join(f'<tr><td>{_e(p)}</td><td class="num">{v["trades"]}</td><td class="num">{v["hit"]:.0%}</td>'
                  f'<td class="num{_rcls(v["mean_r"])}">{v["mean_r"]:+.2f}</td></tr>'
                  for p, v in ref["patterns"].items())
    late = "".join(f'<tr><td>{_e(row["day"])}</td><td class="num">{row["trades"]}</td>'
                   f'<td class="num{_rcls(row["mean_r"])}">{row["mean_r"]:+.2f}</td>'
                   f'<td class="num{_rcls(row["vs_day1"])}">{_signed(row["vs_day1"])}</td></tr>'
                   for row in ref["late_entry"])
    gloss = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in GLOSSARY)
    return (f'<details class="how" id="how"><summary><h2>How to read this page</h2></summary>'
            f'<dl class="glossary">{gloss}</dl>'
            f'<h3>What the same rules did over eleven years</h3><p class="note">{_e(ref["source"])}. Index '
            f'membership as it was at the time; what remains of the survivorship bias is the symbols that no '
            f'longer trade.</p>'
            '<div class="two-col"><div class="table-wrap"><table><thead><tr><th>Pattern</th>'
            '<th class="num">Signals</th><th class="num">Reached target</th><th class="num">Mean R</th></tr></thead>'
            f'<tbody>{pat}</tbody></table></div>'
            '<div class="table-wrap"><table><thead><tr><th>Day on the list</th><th class="num">Signals</th>'
            f'<th class="num">Mean R</th><th class="num">Same signals, vs day 1</th></tr></thead><tbody>{late}</tbody>'
            '</table></div></div></details>')


def _footer(vm: Mapping[str, Any]) -> str:
    return (f'<footer><p><strong>Not investment advice.</strong> Every level comes from a pattern detector on daily '
            f'prices; check the chart yourself before trading, size the position for the stop loss, and expect losing '
            f'streaks: the replay lost 36 to 41 R inside four of eleven years.</p>'
            f'<p><a href="{REPO_URL}">Source and reports</a> · '
            f'<a href="{REPO_URL}/blob/main/output/report.md">Latest report</a> · '
            f'<a href="{REPO_URL}/wiki/03-Configuration-and-Tuning">Rules and their evidence</a> · '
            f'<a href="{REPO_URL}/wiki">How it works</a> · built {_e(vm["generated"])}</p></footer>')


def render_body(vm: Mapping[str, Any]) -> str:
    """The page's body content (inside ``<div class="wrap">``)."""
    return ('<div class="wrap">' + _header(vm) + _glance(vm) + _signals_now(vm) + _why(vm) + _open_trades(vm)
            + _results(vm) + _how(vm) + _footer(vm) + "</div>")


def _asset(name: str) -> str:
    with open(os.path.join(SITE_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def render_page(vm: Mapping[str, Any], fragment: bool = False) -> str:
    """The complete ``index.html`` (or, with ``fragment``, the same without the document wrapper)."""
    title = "SignalSync"
    head = f"<title>{title}</title>\n<style>\n{_asset('style.css')}\n</style>\n"
    body = render_body(vm) + f"\n<script>\n{_asset('app.js')}\n</script>\n"
    if fragment:
        return head + body
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="description" content="S&amp;P 500 chart-pattern buy signals with the buy limit, stop loss '
            f'and take profit, why each stock was triggered, and how past signals turned out.">\n{head}</head>\n'
            f'<body>\n{body}</body>\n</html>\n')


def build(signals_path: str, evaluation_path: Optional[str], out_dir: str, fragment: bool = False,
          today: Optional[dt.date] = None, charts_path: Optional[str] = None) -> Dict[str, Any]:
    """Read the inputs, write ``index.html`` and ``data.json`` into ``out_dir``; returns the view model."""
    with open(signals_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    evaluation = charts = None
    if evaluation_path:
        with open(evaluation_path, encoding="utf-8") as fh:
            evaluation = json.load(fh)
    if charts_path:
        with open(charts_path, encoding="utf-8") as fh:
            charts = json.load(fh)
    vm = view_model(doc, evaluation, today, charts)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(render_page(vm, fragment))
    with open(os.path.join(out_dir, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(vm, fh, indent=1)
    return vm


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--signals", default=os.path.join(ROOT, "output", "signals.json"))
    ap.add_argument("--evaluation", help="JSON from tools/evaluate_signals.py --json (the live track record)")
    ap.add_argument("--charts", help="JSON from tools/site_charts.py (the bars behind the charts)")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "_site"))
    ap.add_argument("--fragment", action="store_true", help="write the page without the document wrapper")
    ap.add_argument("--today", help="YYYY-MM-DD, the build date (default: today, UTC)")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else None
    vm = build(args.signals, args.evaluation, args.out_dir, args.fragment, today, args.charts)
    track = f"with {len(vm['results']['rows'])} signals" if vm["results"]["available"] else "absent"
    charted = sum(1 for v in vm["setups"] + vm["watchlist"] if v.get("chart"))
    print(f"{args.out_dir}/index.html: {len(vm['setups'])} buy signals, {len(vm['watchlist'])} watched, "
          f"results {track}, charts for {charted} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
