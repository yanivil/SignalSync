#!/usr/bin/env python3
"""Replay past CONFIRMED signals against what prices did next, with the backtest's accounting.

Why: the detectors were validated on synthetic fixtures and a random-walk
false-positive rate.  What matters is whether a CONFIRMED signal reached its
target before its stop.  Every daily scan commits ``output/signals.json``, so
the git history of that file is the signal log; this tool reads it, fetches
the bars that followed each signal, and scores it the way ``tools/backtest.py``
scores a replayed one, so the live track record and the replay tables are
comparable line by line.

Usage (prices need network -- run via the ``evaluate-signals`` workflow on a
GitHub runner, or locally where Yahoo is reachable):

    python tools/evaluate_signals.py [--repo .] [--horizon 60] [--json out.json]

Accounting per signal, on the daily bars strictly after its ``last_date``:

* The **fill** is the next session's open (the report arrives before the US
  open).  An open above the row's ``max_buy`` (entry + ``MAX_RUNAWAY`` for rows
  written before that column existed) is a ``gap``; an open at or below the
  stop is ``below_stop``.  Neither is traded.
* ``target``  -- High >= target before Low <= stop, from the fill bar on
* ``stop``    -- Low <= stop first; a bar touching both counts as a stop
* ``expired`` -- neither within ``horizon`` bars: closed at that bar's close
* ``open``    -- neither yet, and fewer than ``horizon`` bars have printed;
  marked to the last close
* ``no_data`` -- no bars after ``last_date`` yet

Gaps fill at the open: a stop at the bar's Open when the Open is already
below the stop, a target at the Open when it gaps above.  R multiple =
(exit - fill) / (fill - stop): a stop is -1 R, the target is
(target - fill) / (fill - stop).  Signals are de-duplicated on
(ticker, pattern, stop): the same structure is reported on consecutive days
while its breakout ages, and the stop is the anchor that does not move; the
sessions on which it was listed are kept (``listings``), so a reader can tell
a row's first day on the list from its fifth.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from typing import Dict, List, Optional, Sequence

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import scan  # noqa: E402

log = logging.getLogger("evaluate")

TRADED = ("target", "stop", "open", "expired")   # outcomes with a position; the rest have none


def signal_history(repo: str = ".", path: str = "output/signals.json") -> List[dict]:
    """First appearance of every CONFIRMED signal in the git history of ``path``, with its listings.

    :param repo: Repository directory.
    :param path: Signals file tracked in git.
    :returns: Signals (dicts as written by ``scan.py`` at their first appearance) plus
        ``first_seen`` (commit date, ISO) and ``listings`` (the distinct ``last_date``
        values on which the same structure was CONFIRMED, oldest first) -- oldest
        first, one per (ticker, pattern, stop).
    """
    shas = subprocess.run(["git", "-C", repo, "log", "--reverse", "--format=%H %cs", "--", path],
                          check=True, capture_output=True, text=True).stdout.split("\n")
    seen: Dict[tuple, dict] = {}
    for line in filter(None, shas):
        sha, day = line.split()
        blob = subprocess.run(["git", "-C", repo, "show", f"{sha}:{path}"],
                              capture_output=True, text=True)
        if blob.returncode != 0:
            continue
        try:
            doc = json.loads(blob.stdout)
        except json.JSONDecodeError:
            log.warning("%s: unreadable %s, skipped", sha[:7], path)
            continue
        for s in doc.get("signals", []):
            if s.get("status") != "CONFIRMED":
                continue
            key = (s["ticker"], s["pattern"], round(float(s["stop"]), 2))
            if key not in seen:
                seen[key] = {**s, "first_seen": day, "listings": [s["last_date"]]}
            elif s["last_date"] not in seen[key]["listings"]:
                seen[key]["listings"].append(s["last_date"])
    for s in seen.values():
        s["listings"].sort()
    return list(seen.values())


def classify(entry: float, stop: float, target: Optional[float], bars: pd.DataFrame,
             horizon: int = 60) -> dict:
    """Outcome of one position given the daily bars from its fill bar on.

    :param entry: Fill price.
    :param stop: Stop-loss price (must be below ``entry`` for an R multiple).
    :param target: Reference target or ``None`` (then only ``stop`` / ``open`` are possible).
    :param bars: OHLC rows from the fill bar on, oldest first.
    :param horizon: Bars to wait before marking the position ``open`` at the last close.
    :returns: ``{"outcome", "bars", "exit", "r"}``; ``r`` is ``None`` when it is undefined.

    Complexity: O(min(len(bars), horizon)).
    """
    risk = entry - stop
    if bars.empty:
        return {"outcome": "no_data", "bars": 0, "exit": None, "r": None}
    window = bars.iloc[:horizon]
    opens = window["Open"] if "Open" in window.columns else window["Close"]
    for i, (op, hi, lo) in enumerate(zip(opens, window["High"], window["Low"]), start=1):
        if lo <= stop:                      # checked first: a bar touching both is a stop
            exit_ = min(float(op), stop)    # gap-down opens fill below the stop
            return {"outcome": "stop", "bars": i, "exit": exit_,
                    "r": (exit_ - entry) / risk if risk > 0 else None}
        if target is not None and hi >= target:
            exit_ = max(float(op), target)  # gap-up opens fill above the target
            return {"outcome": "target", "bars": i, "exit": exit_,
                    "r": (exit_ - entry) / risk if risk > 0 else None}
    last = float(window["Close"].iloc[-1])
    return {"outcome": "open", "bars": len(window), "exit": last,
            "r": (last - entry) / risk if risk > 0 else None}


def fill_and_classify(stop: float, target: Optional[float], max_buy: Optional[float], bars: pd.DataFrame,
                      horizon: int = 60, expire: bool = True) -> dict:
    """Fill at the first bar's open under the report's rules, then :func:`classify`.

    Shared with ``tools/backtest.py`` so a replayed signal and a live one are
    scored identically.

    :param stop: Stop-loss price.
    :param target: Reference target or ``None``.
    :param max_buy: Highest open worth filling (``None`` = no limit).
    :param bars: OHLC rows strictly after the signal's ``last_date``, oldest first.
    :param horizon: Bars after the fill before an unresolved position is closed.
    :param expire: Call an unresolved position past the horizon ``expired`` (closed
        at that bar's close); ``False`` keeps :func:`classify`'s ``open`` for it,
        the backtest's convention.
    :returns: ``{"fill", "outcome", "bars", "exit", "r"}``; ``fill`` is the unrounded
        open (``None`` without bars); ``outcome`` adds ``gap``, ``below_stop`` and
        ``expired`` to :func:`classify`'s.
    """
    none = {"bars": 0, "exit": None, "r": None}
    if bars.empty:
        return {"fill": None, "outcome": "no_data", **none}
    fill = float(bars["Open"].iloc[0])
    if max_buy is not None and fill > max_buy:
        return {"fill": fill, "outcome": "gap", **none}
    if fill <= stop:                        # already through the stop: no trade, and R would be undefined
        return {"fill": fill, "outcome": "below_stop", **none}
    res = classify(fill, stop, target, bars, horizon)
    if expire and res["outcome"] == "open" and len(bars) >= horizon:
        res["outcome"] = "expired"
    return {"fill": fill, **res}


def summarise(rows: Sequence[dict]) -> dict:
    """Outcome counts, hit rate among resolved positions and mean / total R over traded ones.

    :param rows: Dicts carrying ``outcome`` and ``r``.
    :returns: ``{"n", "target", "stop", "open", "expired", "gap", "below_stop", "no_data",
        "hit_rate", "mean_r", "total_r"}`` (the last three ``None`` when undefined).
    """
    counts = {k: sum(1 for r in rows if r["outcome"] == k)
              for k in ("target", "stop", "open", "expired", "gap", "below_stop", "no_data")}
    resolved = counts["target"] + counts["stop"]
    rs = [float(r["r"]) for r in rows if r["outcome"] in TRADED and r["r"] is not None]
    return {"n": len(rows), **counts,
            "hit_rate": round(counts["target"] / resolved, 3) if resolved else None,
            "mean_r": round(sum(rs) / len(rs), 3) if rs else None,
            "total_r": round(sum(rs), 2) if rs else None}


def _fetch(ticker: str, start: str) -> pd.DataFrame:
    import yfinance as yf  # lazy: tests never need it

    df = yf.Ticker(ticker).history(start=start, interval="1d", auto_adjust=True)
    if df.empty:
        return df
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None).normalize()
    return df[["Open", "High", "Low", "Close"]]


def evaluate(signals: Sequence[dict], horizon: int, fetch=_fetch) -> List[dict]:
    """Score every signal; ``fetch(ticker, start)`` is injectable for tests.

    :returns: One dict per signal: the reported levels, ``first_seen``,
        ``listed_days`` / ``last_listed`` (from ``listings``), ``fill`` and
        ``fill_date``, the :func:`fill_and_classify` outcome, ``exit_date`` and
        ``pnl_pct`` (exit against the fill, percent).
    """
    out: List[dict] = []
    cache: Dict[str, pd.DataFrame] = {}
    for s in signals:
        t = s["ticker"]
        if t not in cache:
            try:
                cache[t] = fetch(t, min(x["last_date"] for x in signals if x["ticker"] == t))
            except Exception as exc:  # one bad ticker must not abort the evaluation
                log.warning("%s: fetch failed: %s", t, exc)
                cache[t] = pd.DataFrame()
        bars = cache[t]
        after = bars[bars.index > pd.Timestamp(s["last_date"])] if not bars.empty else bars
        max_buy = s.get("max_buy")
        if max_buy is None:
            max_buy = float(s["entry"]) * (1 + scan.MAX_RUNAWAY)
        res = fill_and_classify(float(s["stop"]), s.get("target"), float(max_buy), after, horizon)
        fill = res.pop("fill")
        listings = s.get("listings") or [s["last_date"]]
        row = {k: s.get(k) for k in ("ticker", "pattern", "last_date", "entry", "max_buy", "stop", "target", "score")}
        row.update(first_seen=s.get("first_seen"), listed_days=len(listings), last_listed=listings[-1],
                   fill=None if fill is None else round(fill, 2),
                   fill_date=str(after.index[0].date()) if fill is not None else None,
                   **res,
                   exit_date=str(after.index[res["bars"] - 1].date()) if res["bars"] else None,
                   pnl_pct=round((res["exit"] / fill - 1) * 100, 2) if res["exit"] is not None else None)
        if row["exit"] is not None:
            row["exit"] = round(row["exit"], 2)
        out.append(row)
    return out


def _cell(x) -> str:
    return "-" if x is None else str(x)


def render(rows: Sequence[dict], summary: dict, horizon: int) -> str:
    """Markdown report (also readable as a GitHub step summary)."""
    lines = [f"# Signal evaluation ({summary['n']} confirmed signals, horizon {horizon} bars)", "",
             f"target {summary['target']} · stop {summary['stop']} · expired {summary['expired']} · "
             f"open {summary['open']} · not traded {summary['gap'] + summary['below_stop']} "
             f"(gap {summary['gap']}, below stop {summary['below_stop']}) · no data {summary['no_data']} · "
             f"hit rate {summary['hit_rate']} · mean R {summary['mean_r']} · total R {summary['total_r']}", "",
             "Fill = the next session's open; not traded = the open was above the row's Max buy (gap) or at or "
             f"below the stop. Expired = neither target nor stop within {horizon} bars, closed at that bar's close; "
             "open = still running, marked to the last close. R = (exit - fill) / (fill - stop). Listed = sessions "
             "on which the report carried the row.", "",
             "| Ticker | Pattern | Signal date | Listed | Entry | Fill | Stop | Target | Outcome | Bars | Exit | "
             "P&L % | R |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["last_date"], r["ticker"])):
        lines.append(f"| {r['ticker']} | {r['pattern']} | {r['last_date']} | {r['listed_days']} | {r['entry']} | "
                     f"{_cell(r['fill'])} | {r['stop']} | {_cell(r['target'])} | {r['outcome']} | {r['bars']} | "
                     f"{_cell(r['exit'])} | {_cell(r['pnl_pct'])} | "
                     f"{'-' if r['r'] is None else round(r['r'], 2)} |")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--horizon", type=int, default=60,
                    help="bars after the fill before an unresolved position is closed (expired)")
    ap.add_argument("--json", help="also write the rows and summary here")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signals = signal_history(args.repo)
    if not signals:
        print("no CONFIRMED signals in the history of output/signals.json")
        return 0
    rows = evaluate(signals, args.horizon)
    summary = summarise(rows)
    print(render(rows, summary, args.horizon))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "horizon": args.horizon, "rows": rows}, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
