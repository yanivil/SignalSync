# PR: Daily S&P 500 pattern scanner (Cup & Handle, inverse H&S, bullish Wolfe Wave)

**Branch:** `feature/sp500-pattern-scanner` → `main` (repo `yanivil/SignalSync`)

## Context / Why
Yaniv wants a 07:00 (Israel) daily alert listing S&P 500 stocks showing a
Cup & Handle, (inverse) Head & Shoulders or Bullish Wolfe Wave, with entry
price and stop-loss, filtered by four rules: no forced patterns, respect the
wider trend, enter only after confirmation, always define risk. The Claude
cloud sandbox and the Claude shell on the user's Mac both sit behind a
network policy that blocks every market-data host (verified: Yahoo, Stooq,
Alpha Vantage, Nasdaq, Tiingo, Polygon… all rejected; only GitHub/PyPI pass),
so the scan runs on GitHub Actions and the scheduled task reads the committed
report.

## Summary of changes
- New `scan.py` (single module): constituent loading (GitHub dataset, dot→dash
  symbol normalisation), batched yfinance download with retry, ATR, fractal
  pivots, SMA-based trend context, three detectors, de-duplication, quality
  scoring, CONFIRMED/WATCHLIST classification, JSON + Markdown reports, CLI.
- New `test_scan.py`: pytest suite on synthetic price paths (one textbook
  instance per pattern), random-walk false-positive sweep, short/NaN
  robustness, symbol normalisation.
- New `.github/workflows/daily-scan.yml`: 02:00 UTC daily + manual dispatch;
  runs tests, runs the scan, commits `output/`.
- New `run_daily.sh`: idempotent wrapper (venv + requirements checksum,
  dated logs) for local runs.
- New `README.md`, `CHANGELOG.md`, `requirements.txt`, `.gitignore`.

## Test steps
1. `pip install -r requirements.txt pytest`
2. `python3 -m pytest test_scan.py -q -s` → 7 passed; prints the random-walk
   false-positive rate (expected ≈ 1.5 %, must be < 5 %).
3. On a machine with internet: `python3 scan.py --tickers AAPL,MSFT,NVDA -v`
   → completes, writes `output/report.md` and `output/signals.json`.
4. `bash run_daily.sh` → prints `OK: report written to output/report.md`.
5. After merge: Actions → daily-scan → Run workflow; confirm a commit
   `scan: YYYY-MM-DD (exit 0)` appears with `meta.scanned` ≈ 500 and
   `meta.errors` small in `output/signals.json`.

## Doc impact
- `README.md` (new): usage, rules mapping, parameters, output schema,
  limitations, architecture (GitHub Actions + Claude task), scheduling note
  (04:00 UTC = 07:00 IDT; change to 05:00 UTC after the October clock change).
- `CHANGELOG.md` (new): `[Unreleased]` entry.
- No external API/schema specs exist yet; `signals.json` schema is documented
  in README → Output.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01GMZic1sqid3GLGEyB9uezx
