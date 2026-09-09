#!/usr/bin/env python3
"""Fetch the recent daily bars behind the page's charts.

Usage (prices need network -- the ``pages`` workflow runs it on a GitHub runner):

    python tools/site_charts.py --signals output/signals.json --bars 120 --json charts.json

Reads the ticker of every signal in ``signals.json`` (confirmed and watchlist),
downloads their history with ``scan.download_history`` (the scan's own
cleaning), keeps the last ``bars`` sessions up to the scan's ``last_bar`` so
the chart ends on the bar the card describes, and writes them as plain lists:

    {"bars": 120, "as_of": "2026-09-08",
     "symbols": {"HAL": {"dates": [...], "open": [...], "high": [...], "low": [...], "close": [...]}}}

A chart is a convenience: any failure is logged and the symbol skipped, the
file is written regardless, and the exit code stays 0 so the page still
builds and deploys without charts.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Dict, Mapping, Optional, Sequence

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
import scan  # noqa: E402

log = logging.getLogger("site_charts")


def bars_for(frames: Mapping[str, pd.DataFrame], bars: int, last_bar: Optional[str] = None) -> Dict[str, dict]:
    """The last ``bars`` sessions of each frame, cut at ``last_bar``, as JSON-ready lists (2-decimal prices)."""
    out: Dict[str, dict] = {}
    for sym, df in frames.items():
        if last_bar:
            df = df[df.index <= pd.Timestamp(last_bar)]
        df = df.dropna(subset=["Open", "High", "Low", "Close"]).iloc[-bars:]
        if df.empty:
            continue
        out[sym] = {"dates": [str(d.date()) for d in df.index],
                    **{k.lower(): [round(float(v), 2) for v in df[k]] for k in ("Open", "High", "Low", "Close")}}
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--signals", default=os.path.join(ROOT, "output", "signals.json"))
    ap.add_argument("--bars", type=int, default=120, help="sessions to keep per symbol")
    ap.add_argument("--period", default="1y", help="yfinance history period to download")
    ap.add_argument("--json", required=True, help="where to write the bars")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with open(args.signals, encoding="utf-8") as fh:
        doc = json.load(fh)
    tickers = sorted({s["ticker"] for s in doc.get("signals", [])})
    last_bar = (doc.get("meta") or {}).get("last_bar")
    symbols: Dict[str, dict] = {}
    if tickers:
        try:
            frames = scan.download_history(tickers, period=args.period)
            symbols = bars_for(frames, args.bars, last_bar)
        except Exception as exc:  # no charts is a degraded page, not a failed build
            log.warning("charts skipped: %s", exc)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump({"bars": args.bars, "as_of": last_bar, "symbols": symbols}, fh)
    print(f"{args.json}: bars for {len(symbols)} of {len(tickers)} symbols (last {args.bars} sessions to {last_bar})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
