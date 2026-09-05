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

Method:

* Signals are taken on the session they **first** appear (keyed on ticker,
  pattern and stop, like ``evaluate_signals``), which is the day the report
  would have alerted.
* The fill is the **next session's open** (the e-mail arrives before the US
  open).  An open more than ``MAX_RUNAWAY`` above the reported entry is a
  ``gap``: no trade, counted separately.
* Outcomes use ``evaluate_signals.classify``: ``target`` / ``stop`` / ``open``
  within ``horizon`` bars after the fill bar, gaps filled at the open, R
  multiple = (exit - fill) / (fill - stop).
* No look-ahead: each scan only sees bars <= D; asserted per signal.

Caveats: the universe is today's constituents (survivorship bias: symbols
that left the index are missing), and the last ``horizon`` sessions of the
window are still ``open``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Dict, List, Optional, Sequence

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan  # noqa: E402
import evaluate_signals as ev  # noqa: E402

log = logging.getLogger("backtest")

SCORE_BUCKETS = ((60, 69), (70, 79), (80, 89), (90, 100))


def walk_forward(data: Dict[str, pd.DataFrame], days: int, horizon: int) -> List[dict]:
    """Replay the scanner over the last ``days`` sessions and score each first-seen signal.

    :param data: ``{symbol: OHLCV frame}`` as returned by ``download_history``.
    :param days: Number of most recent sessions to scan (each as if it were "today").
    :param horizon: Bars after the fill before an unresolved signal counts as ``open``.
    :returns: One dict per first-seen CONFIRMED signal with the signal fields plus
        ``fill``, ``outcome``, ``bars``, ``exit``, ``r``.

    Complexity: O(days * symbols * detector cost); ~2 ms per symbol-day.
    """
    sessions = sorted({d for df in data.values() for d in df.index})
    scan_days = sessions[-days:] if days < len(sessions) else sessions
    seen: Dict[tuple, dict] = {}
    for d in scan_days:
        for sym, df in data.items():
            hist = df[df.index <= d]
            if len(hist) < 60 or hist.index[-1] != d:
                continue                      # symbol had no bar on d (halted, listed later)
            for s in scan.scan_symbol(sym, hist):
                if s.status != "CONFIRMED":
                    continue
                assert s.last_date == str(d.date()), "look-ahead: signal dated after the scan day"
                key = (sym, s.pattern, round(s.stop, 2))
                if key in seen:
                    continue
                after = df[df.index > d]
                row = {**scan.asdict(s), "scan_day": str(d.date())}
                if after.empty:
                    row.update(fill=None, outcome="no_data", bars=0, exit=None, r=None)
                else:
                    fill = float(after["Open"].iloc[0])
                    if fill > s.entry * (1 + scan.MAX_RUNAWAY):
                        row.update(fill=round(fill, 2), outcome="gap", bars=0, exit=None, r=None)
                    else:
                        res = ev.classify(fill, s.stop, s.target, after, horizon)
                        row.update(fill=round(fill, 2), **res)
                seen[key] = row
    return list(seen.values())


def breakdown(rows: Sequence[dict]) -> dict:
    """Summary overall, per pattern and per score bucket (gaps and no_data excluded from rates)."""
    def summ(sub):
        traded = [r for r in sub if r["outcome"] in ("target", "stop", "open")]
        return {**ev.summarise(traded), "gap": sum(1 for r in sub if r["outcome"] == "gap"),
                "signals": len(sub)}
    out = {"overall": summ(rows), "by_pattern": {}, "by_score": {}}
    for p in sorted({r["pattern"] for r in rows}):
        out["by_pattern"][p] = summ([r for r in rows if r["pattern"] == p])
    for lo, hi in SCORE_BUCKETS:
        sub = [r for r in rows if lo <= r["score"] <= hi]
        if sub:
            out["by_score"][f"{lo}-{hi}"] = summ(sub)
    return out


def render(rows: Sequence[dict], stats: dict, days: int, horizon: int) -> str:
    """Markdown report (readable as a GitHub step summary)."""
    def line(name, s):
        return (f"| {name} | {s['signals']} | {s['gap']} | {s['target']} | {s['stop']} | {s['open']} | "
                f"{'-' if s['hit_rate'] is None else f'{s['hit_rate']:.0%}'} | "
                f"{'-' if s['mean_r'] is None else f'{s['mean_r']:+.2f}'} |")
    hdr = "| Slice | Signals | Gapped | Target | Stop | Open | Hit rate | Mean R |\n|---|---|---|---|---|---|---|---|"
    lines = [f"# Walk-forward backtest: last {days} sessions, horizon {horizon} bars", "",
             "Hit rate = target / (target + stop). Mean R over traded signals (open ones marked to the last close). "
             "Fill = next session's open; opens > 5 % above entry are gapped (not traded).", "",
             hdr, line("all", stats["overall"])]
    lines += [line(p, s) for p, s in stats["by_pattern"].items()]
    lines += [line(f"score {b}", s) for b, s in stats["by_score"].items()]
    lines += ["", "| Day | Ticker | Pattern | Score | Entry | Fill | Stop | Target | Outcome | Bars | R |",
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
    ap.add_argument("--period", default="2y")
    ap.add_argument("--min-score", type=int, default=None, help="override MIN_SCORE for the replay")
    ap.add_argument("--json", help="also write rows and stats here")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.min_score is not None:
        scan.MIN_SCORE = args.min_score
    symbols = ([s.strip().upper() for s in args.tickers.split(",") if s.strip()]
               if args.tickers else scan.load_sp500_symbols(args.csv))
    t0 = time.time()
    data = scan.download_history(symbols, period=args.period)
    if not data:
        print("no price data")
        return 2
    log.info("downloaded %d symbols in %.0fs; replaying %d sessions", len(data), time.time() - t0, args.days)
    rows = walk_forward(data, args.days, args.horizon)
    stats = breakdown(rows)
    log.info("replay done in %.0fs: %d first-seen confirmed signals", time.time() - t0, len(rows))
    print(render(rows, stats, args.days, args.horizon))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"days": args.days, "horizon": args.horizon, "min_score": scan.MIN_SCORE,
                       "stats": stats, "rows": rows}, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
