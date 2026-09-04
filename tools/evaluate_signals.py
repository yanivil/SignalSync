#!/usr/bin/env python3
"""Replay past CONFIRMED signals against what prices did next.

Why: the detectors were validated on synthetic fixtures and a random-walk
false-positive rate.  What matters is whether a CONFIRMED signal reached its
target before its stop.  Every daily scan commits ``output/signals.json``, so
the git history of that file is the signal log; this tool reads it, fetches
the bars that followed each signal, and classifies the outcome.

Usage (prices need network -- run via the ``evaluate-signals`` workflow on a
GitHub runner, or locally where Yahoo is reachable):

    python tools/evaluate_signals.py [--repo .] [--horizon 60] [--json out.json]

Outcome per signal, walking the daily bars strictly after ``last_date``:

* ``target``  -- High >= target before Low <= stop
* ``stop``    -- Low <= stop first; a bar touching both counts as a stop
* ``open``    -- neither within ``horizon`` bars; marked to the last close
* ``no_data`` -- no bars after ``last_date`` yet

R multiple = (exit - entry) / (entry - stop): a stop is -1 R, the target is
(target - entry) / (entry - stop).  Signals are de-duplicated on
(ticker, pattern, stop): the same structure is reported on consecutive days
while its breakout ages, and the stop is the anchor that does not move.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from typing import Dict, List, Optional, Sequence

import pandas as pd

log = logging.getLogger("evaluate")


def signal_history(repo: str = ".", path: str = "output/signals.json") -> List[dict]:
    """First appearance of every CONFIRMED signal in the git history of ``path``.

    :param repo: Repository directory.
    :param path: Signals file tracked in git.
    :returns: Signals (dicts as written by ``scan.py``) plus ``first_seen`` (commit
        date, ISO) -- oldest first, one per (ticker, pattern, stop).
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
                seen[key] = {**s, "first_seen": day}
    return list(seen.values())


def classify(entry: float, stop: float, target: Optional[float], bars: pd.DataFrame,
             horizon: int = 60) -> dict:
    """Outcome of one signal given the daily bars that followed it.

    :param entry: Entry price.
    :param stop: Stop-loss price (must be below ``entry`` for an R multiple).
    :param target: Reference target or ``None`` (then only ``stop`` / ``open`` are possible).
    :param bars: OHLC rows strictly after the signal's ``last_date``, oldest first.
    :param horizon: Bars to wait before marking the signal ``open`` at the last close.
    :returns: ``{"outcome", "bars", "exit", "r"}``; ``r`` is ``None`` when it is undefined.

    Complexity: O(min(len(bars), horizon)).
    """
    risk = entry - stop
    if bars.empty:
        return {"outcome": "no_data", "bars": 0, "exit": None, "r": None}
    window = bars.iloc[:horizon]
    for i, (hi, lo) in enumerate(zip(window["High"], window["Low"]), start=1):
        if lo <= stop:                      # checked first: a bar touching both is a stop
            return {"outcome": "stop", "bars": i, "exit": stop, "r": -1.0 if risk > 0 else None}
        if target is not None and hi >= target:
            return {"outcome": "target", "bars": i, "exit": target,
                    "r": (target - entry) / risk if risk > 0 else None}
    last = float(window["Close"].iloc[-1])
    return {"outcome": "open", "bars": len(window), "exit": last,
            "r": (last - entry) / risk if risk > 0 else None}


def summarise(rows: Sequence[dict]) -> dict:
    """Aggregate outcome counts, hit rate among resolved signals and mean R.

    :param rows: Dicts carrying ``outcome`` and ``r`` (from :func:`classify`).
    :returns: ``{"n", "target", "stop", "open", "no_data", "hit_rate", "mean_r"}``
        (``hit_rate`` and ``mean_r`` are ``None`` when undefined).
    """
    counts = {k: sum(1 for r in rows if r["outcome"] == k) for k in ("target", "stop", "open", "no_data")}
    resolved = counts["target"] + counts["stop"]
    rs = [r["r"] for r in rows if r["r"] is not None]
    return {"n": len(rows), **counts,
            "hit_rate": round(counts["target"] / resolved, 3) if resolved else None,
            "mean_r": round(sum(rs) / len(rs), 3) if rs else None}


def _fetch(ticker: str, start: str) -> pd.DataFrame:
    import yfinance as yf  # lazy: tests never need it

    df = yf.Ticker(ticker).history(start=start, interval="1d", auto_adjust=True)
    if df.empty:
        return df
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None).normalize()
    return df[["Open", "High", "Low", "Close"]]


def evaluate(signals: Sequence[dict], horizon: int, fetch=_fetch) -> List[dict]:
    """Classify every signal; ``fetch(ticker, start)`` is injectable for tests."""
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
        res = classify(float(s["entry"]), float(s["stop"]), s.get("target"), after, horizon)
        out.append({k: s[k] for k in ("ticker", "pattern", "last_date", "entry", "stop", "target", "score")}
                   | {"first_seen": s.get("first_seen")} | res)
    return out


def render(rows: Sequence[dict], summary: dict, horizon: int) -> str:
    """Markdown report (also readable as a GitHub step summary)."""
    lines = [f"# Signal evaluation ({summary['n']} confirmed signals, horizon {horizon} bars)", "",
             f"target {summary['target']} · stop {summary['stop']} · open {summary['open']} · "
             f"no data {summary['no_data']} · hit rate {summary['hit_rate']} · mean R {summary['mean_r']}", "",
             "| Ticker | Pattern | Signal date | Entry | Stop | Target | Outcome | Bars | R |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["last_date"]):
        lines.append(f"| {r['ticker']} | {r['pattern']} | {r['last_date']} | {r['entry']} | {r['stop']} | "
                     f"{r['target'] if r['target'] is not None else '-'} | {r['outcome']} | {r['bars']} | "
                     f"{'-' if r['r'] is None else round(r['r'], 2)} |")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--horizon", type=int, default=60, help="bars before an unresolved signal is 'open'")
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
