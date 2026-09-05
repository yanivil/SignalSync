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
* Per signal it also records the maximum favourable / adverse excursion over
  the horizon and the chart-book style ``success5``: did the high reach +5 %
  above the fill before any *close* below the stop (no target, no intraday
  stop), which is what published "pattern success rates" measure.
* ``--grid`` re-scores the same signals under stop / target variants: extra
  ATR below the reported stop (0 / 0.25 / 0.75, i.e. ~0.25 / 0.5 / 1.0 ATR
  under the structural low), intraday vs close-based stops, and full vs half
  measured-move targets.

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
GRID = [(extra, basis, tfrac) for extra in (0.0, 0.25, 0.75) for basis in ("intraday", "close") for tfrac in (1.0, 0.5)]


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


def grid(rows: Sequence[dict], data: Dict[str, pd.DataFrame], horizon: int) -> List[dict]:
    """Re-score the traded signals under every stop / target variant in ``GRID``."""
    out = []
    traded = [r for r in rows if r["outcome"] in ("target", "stop", "open")]
    for extra, basis, tfrac in GRID:
        scored = []
        for r in traded:
            bars = data[r["ticker"]]
            after = bars[bars.index > pd.Timestamp(r["scan_day"])]
            stop = r["stop"] - extra * r["atr"]
            target = r["fill"] + tfrac * (r["target"] - r["fill"]) if r["target"] is not None else None
            scored.append(classify_variant(r["fill"], stop, target, after, horizon, basis))
        s = ev.summarise(scored)
        out.append({"stop_extra_atr": extra, "stop_basis": basis, "target_fraction": tfrac, **s})
    return out


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
                row = {**scan.asdict(s), "scan_day": str(d.date()),
                       "atr": round(float(scan.atr(hist).iloc[-1]), 4)}
                if after.empty:
                    row.update(fill=None, outcome="no_data", bars=0, exit=None, r=None,
                               mfe=None, mae=None, success5=None)
                else:
                    fill = float(after["Open"].iloc[0])
                    if fill > s.entry * (1 + scan.MAX_RUNAWAY):
                        row.update(fill=round(fill, 2), outcome="gap", bars=0, exit=None, r=None,
                                   mfe=None, mae=None, success5=None)
                    else:
                        res = ev.classify(fill, s.stop, s.target, after, horizon)
                        row.update(fill=round(fill, 2), **res, **excursions(fill, s.stop, after, horizon))
                seen[key] = row
    return list(seen.values())


def breakdown(rows: Sequence[dict]) -> dict:
    """Summary overall, per pattern and per score bucket (gaps and no_data excluded from rates)."""
    def summ(sub):
        traded = [r for r in sub if r["outcome"] in ("target", "stop", "open")]
        decided = [r["success5"] for r in traded if r.get("success5") is not None]
        return {**ev.summarise(traded), "gap": sum(1 for r in sub if r["outcome"] == "gap"),
                "signals": len(sub),
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


def _pct(x, signed=False):
    return "-" if x is None else (f"{x:+.1%}" if signed else f"{x:.0%}")


def render(rows: Sequence[dict], stats: dict, days: int, horizon: int,
           grid_rows: Optional[Sequence[dict]] = None) -> str:
    """Markdown report (readable as a GitHub step summary)."""
    def line(name, s):
        return (f"| {name} | {s['signals']} | {s['gap']} | {s['target']} | {s['stop']} | {s['open']} | "
                f"{_pct(s['hit_rate'])} | {'-' if s['mean_r'] is None else f'{s['mean_r']:+.2f}'} | "
                f"{_pct(s['success5'])} | {_pct(s['mfe'], True)} | {_pct(s['mae'], True)} |")
    hdr = ("| Slice | Signals | Gapped | Target | Stop | Open | Hit rate | Mean R | +5% first | MFE | MAE |\n"
           "|---|---|---|---|---|---|---|---|---|---|---|")
    lines = [f"# Walk-forward backtest: last {days} sessions, horizon {horizon} bars", "",
             "Hit rate = target / (target + stop). Mean R over traded signals (open ones marked to the last close). "
             "Fill = next session's open; opens > 5 % above entry are gapped (not traded). "
             "+5% first = share of signals whose high reached +5 % above the fill before any close below the stop "
             "(the chart-book success definition). MFE / MAE = mean best / worst excursion from the fill "
             "within the horizon.",
             "", hdr, line("all", stats["overall"])]
    lines += [line(p, s) for p, s in stats["by_pattern"].items()]
    lines += [line(f"score {b}", s) for b, s in stats["by_score"].items()]
    if grid_rows:
        lines += ["", "## Stop / target variants (same signals)", "",
                  "Extra ATR = distance added below the reported stop (which already sits 0.25 ATR under the "
                  "structural low). Half target = halfway from the fill to the measured-move target.", "",
                  "| Extra ATR | Stop basis | Target | Target | Stop | Open | Hit rate | Mean R |",
                  "|---|---|---|---|---|---|---|---|"]
        for g in grid_rows:
            size = "full" if g["target_fraction"] == 1.0 else "half"
            lines.append(f"| {g['stop_extra_atr']} | {g['stop_basis']} | {size} | "
                         f"{g['target']} | {g['stop']} | {g['open']} | {_pct(g['hit_rate'])} | "
                         f"{'-' if g['mean_r'] is None else f'{g['mean_r']:+.2f}'} |")
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
    ap.add_argument("--grid", action="store_true", help="also re-score under stop / target variants")
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
    grid_rows = grid(rows, data, args.horizon) if args.grid else None
    print(render(rows, stats, args.days, args.horizon, grid_rows))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"days": args.days, "horizon": args.horizon, "min_score": scan.MIN_SCORE,
                       "stats": stats, "grid": grid_rows, "rows": rows}, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
