# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
- `meta.last_bar` claimed the newest date reached by *any* symbol while the
  signals were computed on the previous close. Cause: Yahoo publishes the
  previous session's daily row as volume-only first (OHLC null); on
  2026-09-04 07:28 UTC 501/503 symbols had that row for 2026-09-03 and
  `dropna(subset=["Close"])` removed it, while APH and HUBB already had the
  full bar. `download_history()` now records trailing volume-only rows per
  symbol and `align_last_bar()` scans every symbol on the majority's newest
  complete bar (`LAST_BAR_MIN_FRACTION`), truncating symbols that run ahead;
  `meta` gains `last_bar_symbols`, `lagging_symbols`, `skipped_bar`,
  `skipped_bar_complete`, `skipped_bar_partial`, `last_bar_histogram`.
- Report header said "Breakouts older than 3 bars are dropped" while H&S and
  Wolfe tolerate `MAX_BREAKOUT_AGE + PIVOT_ORDER` (8) bars. The detectors now
  use `max_breakout_age(pattern)` (table `BREAKOUT_AGE_LAG`), the header
  states the limit per pattern, and `meta.max_breakout_age_by_pattern`
  exposes it.

### Added
- `tools/debug_last_bar.py` + `.github/workflows/debug-last-bar.yml`
  (manual dispatch, read-only): per-symbol last bar before/after cleaning,
  histogram, raw rows, and a dry-run scan on a GitHub runner.
- Tests for trailing/interior NaN handling in `download_history`, the
  majority rule in `align_last_bar`, and an end-to-end reproduction of the
  2026-09-04 run; synthetic series now share one end date.

### Changed (docs)
- Repository is `yanivil/SignalSync`; README and PR draft updated accordingly.

### Added
- `scan.py`: S&P 500 daily-bar scanner with three detectors — Cup & Handle,
  Inverse Head & Shoulders, Bullish Wolfe Wave — each producing entry, stop,
  risk %, reference target, quality score, trend context and anchor notes.
- Rule enforcement from the user's guide: strict geometry + quality score
  (no forced patterns), SMA50/SMA200 trend gate, close-based confirmation
  with CONFIRMED/WATCHLIST split and a 5 % no-chase limit, structural stops
  with a 15 % max-risk filter.
- JSON (`output/signals.json`) and Markdown (`output/report.md`) outputs.
- `test_scan.py`: synthetic-data tests for each detector, a random-walk
  false-positive sweep (1.5 % on 200 series), robustness and symbol tests.
- `.github/workflows/daily-scan.yml`: GitHub Actions job (02:00 UTC daily +
  manual dispatch) that runs the tests and the scan and commits
  `output/report.md` + `output/signals.json`.
- `run_daily.sh`: self-healing wrapper (venv, dependency install, dated logs)
  for local runs.
- `test_scan.py::test_main_end_to_end`: CLI run with the download mocked.
- `README.md` with rules mapping, parameters table, output schema, limitations.

### Changed
- `output/` is now committed (by CI) instead of git-ignored; `logs/` stays ignored.
- Architecture: scan runs on GitHub Actions, not on the user's machine — both
  Claude environments block market-data hosts.

### Known issues
- Validated on synthetic data only; real-market validation pending first runs.
