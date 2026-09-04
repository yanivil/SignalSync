#!/usr/bin/env python3
"""
Diagnose which daily bar each symbol ends on, before and after NaN cleaning.

Why: on 2026-09-04 the daily scan reported ``meta.last_bar = 2026-09-03`` while
every signal carried ``last_date = 2026-09-02``.  yfinance logged every symbol
as returning bars through 2026-09-03, so something between the batched
``yf.download`` frame and the per-symbol frame handed to the detectors loses
the newest bar for most symbols.  This script reproduces the exact download
call used by ``scan.download_history`` and prints, per symbol, the last index
date in the raw batched frame, whether that row's Close/Open/High/Low/Volume
are NaN, and the last date after ``dropna(subset=["Close"])``; then a
histogram of both, and the raw last three rows for a few symbols.

Usage (needs open internet):
    python tools/debug_last_bar.py                 # full S&P 500 universe
    python tools/debug_last_bar.py --tickers XOM,CL,ABBV,AAPL
"""

from __future__ import annotations

import argparse
import collections
import logging
import os
import sys
from typing import Optional, Sequence

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scan  # noqa: E402


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Print per-symbol last-bar diagnostics; returns the process exit code."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", help="comma separated symbols (default: full S&P 500 list)")
    ap.add_argument("--period", default="2y")
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--sample", default="XOM,CL,ABBV,HAL,VRTX",
                    help="symbols whose raw last rows are printed in full")
    ap.add_argument("-v", "--verbose", action="store_true", help="yfinance DEBUG logging")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    import yfinance as yf
    print(f"yfinance {yf.__version__}, pandas {pd.__version__}")

    symbols = ([s.strip().upper() for s in args.tickers.split(",") if s.strip()]
               if args.tickers else scan.load_sp500_symbols())
    sample = [s.strip().upper() for s in args.sample.split(",") if s.strip()]
    print(f"universe: {len(symbols)} symbols, period={args.period}, batch={args.batch}")

    before = collections.Counter()
    after = collections.Counter()
    nan_cols = collections.Counter()
    rows = []
    for i in range(0, len(symbols), args.batch):
        chunk = symbols[i:i + args.batch]
        raw = yf.download(chunk, period=args.period, interval="1d", group_by="ticker",
                          auto_adjust=True, progress=False, threads=True)
        print(f"batch {i // args.batch}: raw frame shape={raw.shape}, "
              f"index {raw.index[0]} -> {raw.index[-1]} (tz={raw.index.tz})")
        for sym in chunk:
            try:
                df = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                rows.append((sym, "MISSING", "", "", ""))
                continue
            if df.empty:
                rows.append((sym, "EMPTY", "", "", ""))
                continue
            last_raw = df.index[-1]
            last_row = df.iloc[-1]
            nan_in_last = [c for c in ("Open", "High", "Low", "Close", "Volume")
                           if c in df.columns and pd.isna(last_row[c])]
            # the newest row whose Close is not NaN (what the scanner ends up using)
            valid = df.dropna(subset=["Close"])
            last_valid = valid.index[-1] if not valid.empty else None
            before[str(last_raw.date())] += 1
            after[str(last_valid.date()) if last_valid is not None else "none"] += 1
            nan_cols[",".join(nan_in_last) or "-"] += 1
            rows.append((sym, str(last_raw.date()), ",".join(nan_in_last) or "-",
                         str(last_valid.date()) if last_valid is not None else "none",
                         int(valid["Close"].isna().sum())))
            if sym in sample:
                print(f"\n--- {sym}: raw last 3 rows (before dropna) ---")
                with pd.option_context("display.width", 200):
                    print(df.tail(3).to_string())

    print("\nper-symbol: symbol, last_raw_date, NaN columns in last raw row, last_date_after_dropna")
    for r in rows:
        print("  ", *r)
    print("\nlast index date BEFORE dropna(Close):")
    for d, c in sorted(before.items()):
        print(f"  {d}: {c}")
    print("last index date AFTER dropna(Close):")
    for d, c in sorted(after.items()):
        print(f"  {d}: {c}")
    print("NaN columns in the last raw row:")
    for k, c in nan_cols.most_common():
        print(f"  {k}: {c}")

    # Cross-check a few symbols against the single-ticker path.
    for sym in sample[:3]:
        try:
            h = yf.Ticker(sym).history(period="10d", interval="1d", auto_adjust=True)
            print(f"\n--- {sym}: yf.Ticker().history(period='10d') last 3 rows ---")
            print(h.tail(3).to_string())
        except Exception as exc:  # pragma: no cover - diagnostics only
            print(f"{sym}: single-ticker history failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
