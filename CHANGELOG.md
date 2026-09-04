# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed (detectors)
- Cup & Handle rejects V-shaped bases: the convex-quadratic roundness fit
  must now explain the cup lows at least as well as the best two-legged V fit
  (`_v_shape_r2`, `CUP_MAX_V_ADVANTAGE` = 0). Calibrated on reference shapes
  (half-sine +0.04, flat dish +0.37, clean V −0.06); watch the first live runs.
- Trend-gate thresholds are constants: `TREND_STRONG_DOWN` (0.90),
  `TREND_SLOPE_LOOKBACK` (40), `TREND_STRONG_DOWN_SMA50` (0.85). Behaviour unchanged.
- `--csv` pointing at a missing file now logs a warning before falling back
  to the pinned GitHub list.

### Added (tooling)
- `tools/evaluate_signals.py` + `evaluate-signals` workflow: replay every
  committed `CONFIRMED` signal against later prices (target / stop / open,
  R multiples, hit rate); `test_evaluate.py` covers the classification and
  the git log reader.
- `tests` workflow: lint, tests and coverage on pull requests and pushes to
  `main` (previously the suite only ran inside the nightly scan).
- `sync-wiki` workflow plus `docs/wiki/Home.md` and `_Sidebar.md`: the
  GitHub wiki is mirrored from `docs/wiki/`.
- README badges point at the real workflows; the coverage badge is gone
  (coverage is printed in the `tests` workflow log).

### Removed
- `PR_DRAFT.md` (stale description of the first PR).

### Fixed
- Report footer claimed entries are "capped 3% above trigger"; the rule is
  that closes more than `MAX_RUNAWAY` (5 %) above the trigger are dropped as
  chasing. The footer now states that and takes the value from the constant.
- `_as_utc()` treated a numpy integer epoch as nanoseconds (→ 1970) and so
  silently declined to fill the close; numpy integer/float epochs are now
  accepted like Python ones.
- `_fetch_history()` slept 15 s after its third and final failed attempt;
  the back-off is now 5 s then 10 s with no sleep after the last try.

### Added
- `test_patterns.py`: primitives against hand-computed values, every
  entry/stop/target/risk recomputed from the reported anchors and the
  documented formulas, single-rule mutations of each textbook fixture that
  must be rejected, and data boundaries (missing bars, zero volume, wick
  spikes, unadjusted split, determinism).
- `test_pipeline.py`: retry/back-off policy, universe CSV loading, and an
  end-to-end six-symbol mini universe with one throttled and one delisted
  symbol, checking the JSON schema, ordering, report formatting, `--min-score`
  and exit code 2.
- `conftest.py`: shared fixtures and an offline `yfinance` stand-in.
- `docs/wiki/`: architecture and data pipeline, pattern catalog with exact
  criteria and formulas, configuration and tuning, testing and contributing.
- Docstrings now state algorithmic complexity; score composition, neckline
  tilt and the Wolfe ETA/EPA algebra are annotated in the detectors; bare
  `dict` annotations replaced by typed generics.

### Changed
- README rewritten as a project overview (pipeline flowchart, quickstart,
  sample output, links to the wiki); the operational detail moved to
  `docs/wiki/01-Architecture-and-Data-Pipeline.md`.
- CI runs the whole suite (`python -m pytest -q`) instead of `test_scan.py` only.
- `_u_shape_r2` docstring and the cup detector comment now say what the
  roundness test does and does not reject (a clean symmetric V passes with
  R² ≈ 0.93).

### Changed (earlier)
- The newest daily bar's close is filled from Yahoo's last-trade quote
  (`fill_missing_close()`): after the US close the chart row has no close
  until ~08:00 UTC, but `regularMarketPrice`/`regularMarketTime` already hold
  the closing print. The 02:00 UTC scan therefore runs on the last completed
  session instead of the one before it. Guards: the trade must fall on the
  row's date and be at least `FILL_CLOSE_MIN_AGE` (1 h) old.
  `meta.filled_close_symbols` reports how many symbols were completed this way.
- History is downloaded per symbol with `Ticker.history(auto_adjust=False)`
  (so the chart metadata is available) and adjusted by `adjust_ohlc()`, which
  treats a missing adjusted close as ratio 1.0 instead of blanking the row.

### Security
- The S&P 500 constituent CSV is now fetched from a pinned commit of
  `datasets/s-and-p-500-companies` (`CONSTITUENTS_COMMIT`) instead of the
  moving `main` branch, so an upstream change cannot silently alter the
  scanned universe.

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
