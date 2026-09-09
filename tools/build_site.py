#!/usr/bin/env python3
"""Build the SignalSync web page: today's setups with a plan for each, the watchlist and the live track record.

Why: the nightly scan commits ``output/signals.json`` and a Markdown report;
an e-mail relayed the tables, which was fragile.  A static page rebuilt after
every scan needs no server, no database and no mail: GitHub Pages serves it
for free.

Usage:

    python tools/build_site.py --signals output/signals.json [--evaluation evaluation.json] --out-dir _site

``--evaluation`` is the JSON written by ``tools/evaluate_signals.py --json``
(the live track record, scored with the backtest's accounting); without it
the page says the track record is not available yet.  ``--fragment`` writes
the page without the document wrapper, for a preview host that supplies its
own.  The stylesheet and the script in ``site/`` are inlined, so the output
is one self-contained ``index.html`` plus ``data.json`` (the view model).

What the page says, and where it comes from:

* Every number on a setup card is the scanner's own: entry, Max buy, stop,
  target, reward:risk, score, age, volume ratio, fear-and-greed, trend.  The
  action line restates the report's rule (buy at the next open only inside
  the buy zone; exit on a close at or below the stop) and is graded by the
  row's day on the list, from the late-entry replay (#115): days 1-2 enter,
  days 3-6 late (about 0.1 R less than on day 1 over eleven years), from day 7
  no entry (a Wolfe from day 6).  Nothing here is a new rule or a probability.
* The track record counts every signal once, at its first report, filled at
  the next open (``tools/evaluate_signals.py``), so it is comparable with the
  replay figures shown next to it (``REPLAY_REFERENCE``, the tuning page).
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SITE_DIR = os.path.join(ROOT, "site")
REPO_URL = "https://github.com/yanivil/SignalSync"

LATE_FROM = 3                                             # day on the list from which an entry is "late"
NO_ENTRY_FROM = {"Bullish Wolfe Wave": 6, "default": 7}   # ... and from which the replay found no edge left
FG_ZONES = ((20.0, "extreme fear"), (40.0, "fear"), (60.0, "neutral"), (80.0, "greed"), (float("inf"), "extreme greed"))
OUTCOME_LABELS = {"target": "Target hit", "stop": "Stopped", "expired": "Time exit", "open": "Open",
                  "gap": "Not traded: gap", "below_stop": "Not traded: below stop", "no_data": "No data yet"}
OUTCOME_STATUS = {"target": "closed", "stop": "closed", "expired": "closed", "open": "open",
                  "gap": "none", "below_stop": "none", "no_data": "none"}
CLOSED_LABELS = {"TARGET_REACHED": "Target reached", "FAILED": "Stop hit", "EXPIRED": "Expired", "FADED": "Faded",
                 "DROPPED": "Dropped"}
# The tuning page's figures the page quotes next to the live numbers (docs/wiki/03-Configuration-and-Tuning.md).
REPLAY_REFERENCE: Dict[str, Any] = {
    "source": "eleven yearly replays on the index as it was, 2016 to 2026, tuned profile, runs 34323013559 to "
              "34323039560 (2026-09-09)",
    "overall": {"trades": 1632, "hit": 0.35, "mean_r": 0.22,
                "note": "positive in ten of eleven years; drawdowns of 36 to 41 R inside four of them"},
    "patterns": {"Inverse Head & Shoulders": {"trades": 1097, "hit": 0.39, "mean_r": 0.23},
                 "Cup & Handle": {"trades": 305, "hit": 0.18, "mean_r": 0.03},
                 "Bullish Wolfe Wave": {"trades": 230, "hit": 0.36, "mean_r": 0.43}},
    "late_entry": [{"day": "1", "trades": 1632, "mean_r": 0.22, "vs_day1": None},
                   {"day": "2", "trades": 1111, "mean_r": 0.28, "vs_day1": -0.01},
                   {"day": "3", "trades": 952, "mean_r": 0.22, "vs_day1": -0.09},
                   {"day": "4 to 5", "trades": 1479, "mean_r": 0.19, "vs_day1": -0.12},
                   {"day": "6 to 9", "trades": 1169, "mean_r": 0.14, "vs_day1": -0.12}],
}
GLOSSARY = (
    ("Entry", "The trigger level, or the breakout close when it is above the trigger. It is the last close: a trade "
              "happens at the next open."),
    ("Buy zone", "From the entry up to Max buy, the lower of trigger + 5 % and the open at which the risk to the "
                 "stop reaches 1.5 times the planned entry-to-stop distance. An open above it no longer qualifies."),
    ("Stop", "The structural level (handle low, right-shoulder low, point 5) minus 0.25 ATR. Exiting on a close at "
             "or below it scored higher in replay than an intraday touch."),
    ("Target", "The pattern's measured move. R:R = (target − entry) / (entry − stop); it shrinks with every session "
               "the entry drifts above the trigger."),
    ("Score", "0 to 100, the cleanliness of the geometry. Rows below 60 are not reported."),
    ("Age", "Bars since the breakout close and the limit after which the row is dropped (3 for a cup, 8 for an "
            "inverse H&S or a Wolfe, whose last pivot is only visible five bars after it prints)."),
    ("Day on the list", "Sessions since the row was first reported. In the eleven-year replay a row on its second "
                        "day was as good as new; from the third day the same signals paid about 0.1 R less than on "
                        "day 1; from day 7 (a Wolfe from day 6) no edge was left for late buyers."),
    ("Vol×", "Breakout-day volume against the 20-day average."),
    ("F&G", "The stock's own fear-and-greed reading at the last close, 0 to 100 (RSI 14, MACD-histogram percentile "
            "and Bollinger %B averaged). Above 80 the stock is stretched and such breakouts replayed worst; below "
            "20 it is washed out. Information only, no rule uses it."),
    ("Track record", "Every confirmed signal the nightly scan committed, counted once at its first report, filled at "
                     "the next session's open. Not traded when that open was above Max buy or through the stop. "
                     "Target and stop are intraday touches (a bar touching both is a stop); after 60 bars a position "
                     "still open is closed at that close (time exit). R = (exit − fill) / (fill − stop)."),
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
    """Sessions since the signal was first reported, from the track record's ``listed_days``.

    ``None`` when the track record does not know the row, or was built before
    the signal's own session (its ``last_listed`` is older than ``last_date``).
    """
    for r in evaluation_rows:
        if _key(r) == _key(signal):
            return int(r["listed_days"]) if r.get("last_listed") == signal["last_date"] else None
    return None


def grade(pattern: str, day: Optional[int]) -> Tuple[str, str]:
    """``(grade, badge)``: ``enter`` / ``late`` / ``skip`` by the day on the list (see #115)."""
    no_entry = NO_ENTRY_FROM.get(pattern, NO_ENTRY_FROM["default"])
    if day is None:
        return "enter", "First report unknown"
    if day == 1:
        return "enter", "New today"
    if day < LATE_FROM:
        return "enter", f"Day {day} on the list"
    if day >= no_entry:
        return "skip", f"Day {day} on the list: no entry"
    return "late", f"Day {day} on the list: late"


def action_text(signal: Mapping[str, Any], grade_: str, day: Optional[int]) -> str:
    """The plan for a setup, in words: the report's rule graded by the day on the list."""
    zone_hi = signal.get("max_buy") or signal["entry"]
    stop, target = signal["stop"], signal.get("target")
    exit_rule = f"Stop {stop:.2f}: exit on a close at or below it."
    goal = f" Take profit at {target:.2f}." if target else ""
    if grade_ == "enter":
        return (f"Buy at the next open only if it prints at or below {zone_hi:.2f}. If the open is higher, the "
                f"setup no longer qualifies. {exit_rule}{goal}")
    if grade_ == "late":
        return (f"Late entry, day {day} on the list. In the eleven-year replay the same signals bought this late "
                f"paid about 0.1 R less than on their first day, still positive on average. Only at or below "
                f"{zone_hi:.2f} at the open. {exit_rule}{goal}")
    no_entry = NO_ENTRY_FROM.get(signal["pattern"], NO_ENTRY_FROM["default"])
    return (f"No entry, day {day} on the list. From day {no_entry} the eleven-year replay found no edge left for "
            f"late buyers of this pattern. Keep watching; the row stays until it expires.")


def _pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 1)


def setup_view(signal: Mapping[str, Any], meta: Mapping[str, Any],
               evaluation_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """One confirmed row as the card shows it."""
    day = day_on_list(signal, evaluation_rows)
    g, badge = grade(signal["pattern"], day)
    entry, stop, target = float(signal["entry"]), float(signal["stop"]), signal.get("target")
    limits = meta.get("max_breakout_age_by_pattern") or {}
    vr = signal.get("volume_ratio")
    chips: List[Tuple[str, str]] = []
    market = meta.get("market") or {}
    if market.get("regime"):
        chips.append((f"Market: {market['regime']} regime", {"bull": "good", "bear": "bad"}.get(market["regime"], "")))
    for part in (signal.get("trend") or "").split(", "):
        if part:
            chips.append((part[0].upper() + part[1:], "warn" if "below SMA200" in part or "falling" in part else ""))
    if vr is not None:
        chips.append((f"Volume {vr:.1f}× average" if vr >= 1.0 else f"Volume {vr:.1f}×, below average",
                      "" if vr >= 1.0 else "warn"))
    fg = signal.get("fear_greed")
    zone = fg_zone(fg)
    if fg is not None:
        chips.append((f"Fear and greed {fg:.0f}, {zone}", "bad" if fg >= 80 else ("warn" if fg >= 60 else "")))
    ref = REPLAY_REFERENCE["patterns"].get(signal["pattern"])
    return {"ticker": signal["ticker"], "pattern": signal["pattern"], "score": signal["score"], "day": day,
            "grade": g, "badge": badge, "entry": entry, "max_buy": signal.get("max_buy"), "stop": stop,
            "target": target, "risk_pct": round(-_pct(stop, entry), 1),
            "reward_pct": _pct(float(target), entry) if target else None, "reward_risk": signal.get("reward_risk"),
            "last_close": signal.get("last_close"), "age": signal.get("bars_since_break"),
            "age_limit": limits.get(signal["pattern"]), "volume_ratio": vr, "fear_greed": fg, "fg_zone": zone,
            "trend": signal.get("trend"), "notes": signal.get("notes"), "chips": chips,
            "action": action_text(signal, g, day), "reference": ref}


def watch_view(signal: Mapping[str, Any]) -> Dict[str, Any]:
    """One watchlist row as the table shows it."""
    entry, last = float(signal["entry"]), signal.get("last_close")
    return {"ticker": signal["ticker"], "pattern": signal["pattern"], "score": signal["score"], "trigger": entry,
            "max_buy": signal.get("max_buy"), "last_close": last,
            "to_trigger_pct": _pct(entry, float(last)) if last else None, "stop": float(signal["stop"]),
            "target": signal.get("target"), "reward_risk": signal.get("reward_risk"),
            "fear_greed": signal.get("fear_greed"), "fg_zone": fg_zone(signal.get("fear_greed")),
            "trend": signal.get("trend"), "notes": signal.get("notes")}


def track_view(evaluation: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The live track record: rows in signal order with a status, the summary and the cumulative-R curve."""
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
        out.append({**r, "status": status, "label": OUTCOME_LABELS.get(r["outcome"], r["outcome"])})
    return {"available": True, "rows": out, "summary": evaluation.get("summary"), "curve": curve,
            "horizon": evaluation.get("horizon"), "since": rows[0]["last_date"] if rows else None}


def view_model(doc: Mapping[str, Any], evaluation: Optional[Mapping[str, Any]],
               today: Optional[dt.date] = None) -> Dict[str, Any]:
    """Everything the page shows, as plain data (also written as ``data.json``)."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    meta = doc.get("meta", {})
    ev_rows = (evaluation or {}).get("rows", [])
    signals = doc.get("signals", [])
    last_bar = meta.get("last_bar")
    stale_days = (today - dt.date.fromisoformat(last_bar)).days if last_bar else None
    setups = sorted((setup_view(s, meta, ev_rows) for s in signals if s.get("status") == "CONFIRMED"),
                    key=lambda v: (-v["score"]))
    watch = sorted((watch_view(s) for s in signals if s.get("status") == "WATCHLIST"), key=lambda v: -v["score"])
    return {"generated": today.isoformat(),
            "scan": {k: meta.get(k) for k in ("run_date", "last_bar", "scanned", "universe", "errors", "profile",
                                               "previous_run", "skipped_bar", "lagging_symbols", "min_score")}
            | {"stale_days": stale_days},
            "market": meta.get("market"), "setups": setups, "watchlist": watch,
            "closed": [{**c, "label": CLOSED_LABELS.get(c.get("outcome"), c.get("outcome"))}
                       for c in doc.get("closed") or []],
            "track": track_view(evaluation), "reference": REPLAY_REFERENCE}


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


def _header(vm: Mapping[str, Any]) -> str:
    scan, market = vm["scan"], vm.get("market") or {}
    bits = [f"Scan {scan['run_date']} UTC" if scan.get("run_date") else "No scan yet",
            f"bars through {scan['last_bar']}" if scan.get("last_bar") else "",
            f"{scan['scanned']} of {scan['universe']} symbols" if scan.get("scanned") else "",
            f"profile {scan['profile']}" if scan.get("profile") else ""]
    meta_line = " · ".join(b for b in bits if b)
    notes = []
    if scan.get("stale_days") is not None and scan["stale_days"] > 4:
        notes.append(f"The last bar is {scan['stale_days']} days old: the scan may not have run.")
    if scan.get("skipped_bar"):
        notes.append(f"Newest bar {scan['skipped_bar']} not scanned (incomplete at the data source).")
    if scan.get("errors"):
        notes.append(f"Data errors: {scan['errors']}.")
    strip = []
    if market:
        strip.append(_chip(f"{market.get('index', 'SPY')} {market['index_vs_sma200_pct']:+.1f} % vs SMA200"))
        strip.append(_chip(f"{market['regime'].capitalize()} regime",
                           {"bull": "good", "bear": "bad", "neutral": "info"}.get(market["regime"], "")))
        if market.get("vix") is not None:
            strip.append(_chip(f"VIX {market['vix']:.1f}", "warn" if market["vix"] >= 25 else ""))
        if market.get("breadth") is not None:
            strip.append(_chip(f"{market['breadth']:.0%} of stocks above their SMA200"))
    return (f'<header class="top"><div><h1>SignalSync <small>S&amp;P 500 daily chart patterns</small></h1>'
            f'<div class="meta">{_e(meta_line)}</div></div>'
            f'<nav class="sections"><a href="#setups">Setups</a><a href="#watchlist">Watchlist</a>'
            f'<a href="#track">Track record</a><a href="#how">How to read</a></nav></header>'
            + (f'<p class="callout">{_e(" ".join(notes))}</p>' if notes else "")
            + (f'<div class="strip">{"".join(strip)}</div>' if strip else ""))


def _metrics(vm: Mapping[str, Any]) -> str:
    track = vm["track"]
    s = track.get("summary") or {}
    cards = [("Confirmed today", str(len(vm["setups"]))), ("Watchlist", str(len(vm["watchlist"])))]
    if track["available"] and s:
        traded = s["target"] + s["stop"] + s["expired"] + s["open"]
        cards.append((f"Signals since {track['since']}" if track.get("since") else "Signals", str(s["n"])))
        mean = f'<span class="{_rcls(s.get("mean_r")).strip()}">{_signed(s.get("mean_r"))}</span>'
        cards.append(("Mean R so far", mean if traded else "–"))
    return '<div class="cards-4">' + "".join(
        f'<div class="metric"><div class="label">{_e(label)}</div><div class="value">{value}</div></div>'
        for label, value in cards) + "</div>"


def _setup_card(v: Mapping[str, Any]) -> str:
    zone = f"{_num(v['entry'])} to {_num(v['max_buy'])}" if v.get("max_buy") else _num(v["entry"])
    target = (f'<div class="level target"><div class="label">Take profit</div><div class="value">{_num(v["target"])}'
              f'</div><div class="sub">{_signed(v["reward_pct"], 1, " %")} from entry'
              + (f' · {_num(v["reward_risk"])} R' if v.get("reward_risk") is not None else "") + "</div></div>"
              if v.get("target") else '<div class="level target"><div class="label">Take profit</div>'
                                      '<div class="value">–</div><div class="sub">no measured move</div></div>')
    age = (f"Breakout {v['age']} bars ago" + (f", listed until {v['age_limit']}" if v.get("age_limit") else "")
           if v.get("age") is not None else "")
    ref = v.get("reference")
    ref_line = (f"Eleven-year replay, this pattern: {ref['trades']} trades, {ref['hit']:.0%} hit, "
                f"{ref['mean_r']:+.2f} R per trade." if ref else "")
    return (f'<article class="card setup grade-{v["grade"]}" id="setup-{_e(v["ticker"])}">'
            f'<header class="card-head"><div><span class="ticker">{_e(v["ticker"])}</span>'
            f'<span class="pattern">{_e(v["pattern"])}</span></div>'
            f'<div class="head-right"><span class="badge badge-{v["grade"]}">{_e(v["badge"])}</span>'
            f'<span class="muted">Score {_e(v["score"])}</span></div></header>'
            f'<div class="levels"><div class="level"><div class="label">Buy zone at the open</div>'
            f'<div class="value">{zone}</div><div class="sub">last close {_num(v["last_close"])}</div></div>'
            f'<div class="level stop"><div class="label">Stop loss</div><div class="value">{_num(v["stop"])}</div>'
            f'<div class="sub">{_num(v["risk_pct"], 1)} % below entry</div></div>{target}</div>'
            f'<p class="action {v["grade"]}">{_e(v["action"])}</p>'
            f'<div class="chips">{"".join(_chip(t, k) for t, k in v["chips"])}</div>'
            f'<p class="details">{_e(age)}{" · " if age and v.get("notes") else ""}{_e(v.get("notes"))}</p>'
            + (f'<p class="reference">{_e(ref_line)}</p>' if ref_line else "") + "</article>")


def _setups(vm: Mapping[str, Any]) -> str:
    body = "".join(_setup_card(v) for v in vm["setups"]) or \
        '<p class="note">No confirmed breakout in the last scan. The watchlist below shows the patterns that are ' \
        'complete and waiting for a close above their trigger.</p>'
    return f'<h2 id="setups">Today\'s setups<span class="count">{len(vm["setups"])}</span></h2>{body}'


def _watchlist(vm: Mapping[str, Any]) -> str:
    rows = "".join(
        f'<tr><td><strong>{_e(w["ticker"])}</strong></td><td>{_e(w["pattern"])}</td>'
        f'<td class="num">{_num(w["trigger"])}</td><td class="num">{_num(w["last_close"])}</td>'
        f'<td class="num">{_signed(w["to_trigger_pct"], 1, " %")}</td><td class="num">{_num(w["stop"])}</td>'
        f'<td class="num">{_num(w["target"])}</td><td class="num">{_num(w["reward_risk"])}</td>'
        f'<td class="num">{_e(w["score"])}</td>'
        f'<td>{_num(w["fear_greed"], 0)}{" " + _e(w["fg_zone"]) if w.get("fg_zone") else ""}</td></tr>'
        for w in vm["watchlist"])
    anchors = "".join(f'<li><strong>{_e(w["ticker"])}</strong> {_e(w.get("notes"))}</li>'
                      for w in vm["watchlist"] if w.get("notes"))
    table = ('<div class="table-wrap"><table><thead><tr><th>Ticker</th><th>Pattern</th><th class="num">Trigger</th>'
             '<th class="num">Last close</th><th class="num">To trigger</th><th class="num">Stop</th>'
             '<th class="num">Target</th><th class="num">R:R</th><th class="num">Score</th><th>F&amp;G</th>'
             f'</tr></thead><tbody>{rows}</tbody></table></div>'
             + (f'<details class="anchors"><summary>Pattern anchors, for checking on a chart</summary><ul>{anchors}'
                '</ul></details>' if anchors else "")
             if rows else '<p class="note">Nothing on the watchlist.</p>')
    return (f'<h2 id="watchlist">Watchlist<span class="count">{len(vm["watchlist"])}</span></h2>'
            '<p class="note">Not a buy yet: a row moves up to the setups only after a daily close above its trigger. '
            'Stop and target are what the setup would have if it triggers today.</p>' + table)


def _closed(vm: Mapping[str, Any]) -> str:
    if not vm["closed"]:
        return ""
    rows = "".join(
        f'<tr><td><strong>{_e(c["ticker"])}</strong></td><td>{_e(c["pattern"])}</td><td>{_e(c["was"].capitalize())}</td>'
        f'<td>{_e(c["label"])}</td><td class="num">{_num(c["entry"])}</td><td class="num">{_num(c["stop"])}</td>'
        f'<td class="num">{_num(c.get("target"))}</td><td class="wrap-cell">{_e(c.get("detail"))}</td></tr>'
        for c in vm["closed"])
    return (f'<h2 id="closed">Closed since the previous report<span class="count">{len(vm["closed"])}</span></h2>'
            '<div class="table-wrap"><table><thead><tr><th>Ticker</th><th>Pattern</th><th>Was</th><th>Outcome</th>'
            '<th class="num">Entry</th><th class="num">Stop</th><th class="num">Target</th><th>Detail</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def _track(vm: Mapping[str, Any]) -> str:
    t = vm["track"]
    head = '<h2 id="track">Track record</h2>'
    if not t["available"]:
        return head + '<p class="note">The track record is not available in this build.</p>'
    s = t["summary"] or {}
    resolved = s.get("target", 0) + s.get("stop", 0)
    intro = (f'<p class="note">Every confirmed signal the nightly scan has committed since {_e(t["since"])}, counted '
             f'once at its first report and filled at the next open, with the same accounting as the replays. '
             f'{s.get("n", 0)} signals: {s.get("target", 0)} reached the target, {s.get("stop", 0)} stopped, '
             f'{s.get("expired", 0)} timed out, {s.get("open", 0)} open, {s.get("gap", 0) + s.get("below_stop", 0)} '
             f'not traded, {s.get("no_data", 0)} without bars yet. Hit rate '
             f'{f"{s["hit_rate"]:.0%}" if s.get("hit_rate") is not None else "–"} on {resolved} resolved, '
             f'mean {_signed(s.get("mean_r"))} R, total {_signed(s.get("total_r"))} R.</p>')
    ref = vm["reference"]["overall"]
    compare = (f'<p class="callout">For scale: the eleven-year replay of the same rules made {ref["mean_r"]:+.2f} R '
               f'per trade on {ref["trades"]} trades at a {ref["hit"]:.0%} hit rate, {ref["note"]}. A live sample '
               f'this small says little either way.</p>')
    spark = sparkline(t["curve"]) if t["curve"] else ""
    filters = ('<div class="filters" role="group" aria-label="Filter">'
               '<button type="button" data-filter="all" aria-pressed="true">All</button>'
               '<button type="button" data-filter="open" aria-pressed="false">Open</button>'
               '<button type="button" data-filter="closed" aria-pressed="false">Closed</button></div>')
    rows = "".join(
        f'<tr data-status="{r["status"]}"><td>{_e(r["last_date"])}</td><td><strong>{_e(r["ticker"])}</strong></td>'
        f'<td>{_e(r["pattern"])}</td><td class="num">{_e(r.get("listed_days"))}</td>'
        f'<td class="num">{_num(r.get("fill"))}</td><td class="num">{_num(r["stop"])}</td>'
        f'<td class="num">{_num(r.get("target"))}</td>'
        f'<td><span class="badge badge-{ {"closed": "none", "open": "open", "none": "none"}[r["status"]]}'
        f'{" badge-win" if r["outcome"] == "target" else (" badge-loss" if r["outcome"] == "stop" else "")}">'
        f'{_e(r["label"])}</span></td><td class="num">{_e(r.get("bars"))}</td>'
        f'<td class="num">{_num(r.get("exit"))}</td>'
        f'<td class="num{_rcls(r.get("pnl_pct"))}">{_signed(r.get("pnl_pct"), 1, " %")}</td>'
        f'<td class="num{_rcls(r.get("r"))}">{_signed(r.get("r"))}</td></tr>' for r in t["rows"])
    table = ('<div class="table-wrap"><table id="track-table"><thead><tr><th>Signal</th><th>Ticker</th><th>Pattern</th>'
             '<th class="num">Listed</th><th class="num">Fill</th><th class="num">Stop</th><th class="num">Target</th>'
             '<th>Outcome</th><th class="num">Bars</th><th class="num">Exit</th><th class="num">P&amp;L</th>'
             f'<th class="num">R</th></tr></thead><tbody>{rows}</tbody></table></div>'
             if rows else '<p class="note">No signal has been logged yet.</p>')
    return head + intro + compare + spark + filters + table


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
    return (f'<h2 id="how">How to read this page</h2><dl class="glossary">{gloss}</dl>'
            f'<h3>What the same rules did over eleven years</h3><p class="note">{_e(ref["source"])}. Point-in-time '
            f'index membership; the survivorship bias that remains is symbols that no longer trade.</p>'
            '<div class="two-col"><div class="table-wrap"><table><thead><tr><th>Pattern</th><th class="num">Trades</th>'
            f'<th class="num">Hit</th><th class="num">Mean R</th></tr></thead><tbody>{pat}</tbody></table></div>'
            '<div class="table-wrap"><table><thead><tr><th>Day on the list</th><th class="num">Trades</th>'
            f'<th class="num">Mean R</th><th class="num">Same signals, vs day 1</th></tr></thead><tbody>{late}</tbody>'
            '</table></div></div>')


def _footer(vm: Mapping[str, Any]) -> str:
    return (f'<footer><p><strong>Heuristic scan, not investment advice.</strong> Every level comes from a pattern '
            f'detector on daily bars; verify on a chart before trading, size for the stop, and expect losing streaks: '
            f'the replay lost 36 to 41 R inside four of eleven years.</p>'
            f'<p><a href="{REPO_URL}">Source and reports</a> · '
            f'<a href="{REPO_URL}/blob/main/output/report.md">Latest report</a> · '
            f'<a href="{REPO_URL}/wiki/03-Configuration-and-Tuning">Rules and their evidence</a> · '
            f'<a href="{REPO_URL}/wiki">How it works</a> · built {_e(vm["generated"])}</p></footer>')


def render_body(vm: Mapping[str, Any]) -> str:
    """The page's body content (inside ``<div class="wrap">``)."""
    return ('<div class="wrap">' + _header(vm) + _metrics(vm) + _setups(vm) + _watchlist(vm) + _closed(vm)
            + _track(vm) + _how(vm) + _footer(vm) + "</div>")


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
            f'<meta name="description" content="S&amp;P 500 chart-pattern setups with entry, stop and target, and '
            f'the live track record of every signal.">\n{head}</head>\n<body>\n{body}</body>\n</html>\n')


def build(signals_path: str, evaluation_path: Optional[str], out_dir: str, fragment: bool = False,
          today: Optional[dt.date] = None) -> Dict[str, Any]:
    """Read the inputs, write ``index.html`` and ``data.json`` into ``out_dir``; returns the view model."""
    with open(signals_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    evaluation = None
    if evaluation_path:
        with open(evaluation_path, encoding="utf-8") as fh:
            evaluation = json.load(fh)
    vm = view_model(doc, evaluation, today)
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
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "_site"))
    ap.add_argument("--fragment", action="store_true", help="write the page without the document wrapper")
    ap.add_argument("--today", help="YYYY-MM-DD, the build date (default: today, UTC)")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else None
    vm = build(args.signals, args.evaluation, args.out_dir, args.fragment, today)
    track = f"with {len(vm['track']['rows'])} signals" if vm["track"]["available"] else "absent"
    print(f"{args.out_dir}/index.html: {len(vm['setups'])} setups, {len(vm['watchlist'])} on the watchlist, "
          f"track record {track}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
