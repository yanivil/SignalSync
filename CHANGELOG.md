# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed (calibration)
- Tuned profile: Wolfe leg rhythm ±45 % (was ±60 %). Year-long replay:
  ±30 % 8 signals at +0.37 R, ±45 % 28 at +0.13, ±60 % 43 at +0.02; the
  whole profile moves to 177 signals at +0.34 R. Cup entry stays at the
  handle peak (rim-B entry replayed worse: 19 signals at +0.17 R vs 20 at
  +0.23).

### Changed
- Report footer and output contract state that the stop is scored as an
  intraday touch in the backtest and that a close-based exit scored higher
  in replay; the choice is the trader's.

### Added
- `CUP_TRIGGER` (`handle_high`, default | `rim_b`): optional rim-clearing
  cup entry, for replay comparison. Backtest `--set KEY=VALUE` (workflow
  input `overrides`) overrides any scan constant for one replay.
- `Max buy` column and `max_buy` field: trigger + 5 %, the open above which
  a setup no longer qualifies.
- "Closed since the last report": every row of the previous committed
  report that is absent today is classified as TARGET_REACHED, FAILED
  (close at or below the stop), EXPIRED, FADED or DROPPED, with the bar and
  level that decided it; `closed` in `signals.json`, `meta.previous_run`.

### Changed (operations)
- The nightly scan runs `--profile tuned`, chosen on the year-long replay:
  192 confirmed signals, 49 % hit rate, +0.30 R, against legacy's 354 /
  33 % / +0.06 and spec's 22 / 53 % / +0.14. (It ran `legacy` for a few
  hours on 2026-09-05 while the tuned replay completed.) Background: over a
  year the spec profile confirmed 22 signals against 354, and a rule
  ablation showed four spec rules (volume confirmation, IHS side symmetry,
  Wolfe leg rhythm, cup rollback) removing signals that were better than
  the ones kept.
- New `tuned` rule profile: the spec with those four rules relaxed (volume
  as a bonus, side symmetry off, rhythm +-60 %, rollback 61.8 %).
- Backtest `--ablate`: leave-one-rule-out over the spec profile.

### Changed (detectors: engine specification adopted as the "spec" rule profile)
- Rules now follow the chart-pattern engine specification; the previous
  rules are kept as `RULE_PROFILES["legacy"]` (`--profile legacy`, replayed
  alongside by the backtest). Spec profile: cup 20-300 bars, rim within 15 %
  of the cup depth, bottom in the middle 50 %, decline <= 50 % of the
  preceding advance, R^2 >= 0.70, handle <= 25 bars and never longer than
  the cup, SMA50 > SMA200 or a 20 % rise over 60 bars as the trend filter,
  12 % risk cap, target measured from the right rim; H&S shoulders within
  30 % of the head height, side durations within 40 %, SMA50 < SMA200 or a
  one-head-height decline as the trend filter, target measured at the head
  bar, no strong-down-trend veto; Wolfe sweet zone (point 5 below line 1-3
  and above the line through 3 parallel to 2-4) and leg rhythm within 30 %.
- Volume confirmation: a breakout close is CONFIRMED only with >= 1.4x
  (cup) / 1.3x (H&S) the 20-bar average volume; otherwise the row stays on
  the watchlist marked "breakout without volume".
- Two spec statements are deliberately not followed and documented: the
  Wolfe convergence inequality is written reversed in the spec, and the
  spec's point ordering would put point 4 below point 1 (the code keeps
  Investopedia's channel rule).
- Fixtures: the textbook cup now follows a 40->100 advance (its 25-point
  decline retraces 42 %), the H&S breakout bars carry volume, and Wolfe
  point 5 sits inside the sweet zone.
- Backtest: `--profile`, and the grid replays the other profile in full
  instead of the veto-off pass (the veto is now a profile difference).

### Changed (detectors)
- Wolfe targets more than `WW_MAX_TARGET_GAIN` (+100 %) above the entry are
  dropped; the replay found +590 % and +120 % projections.

### Added
- Backtest grid: breakout-level (Investopedia) cup target and a
  veto-off pass for the reversal detectors; `scan_symbol` accepts a
  detector subset.
- Backtest: MFE / MAE, the chart-book "+5 % before a close below the stop"
  success share, and `--grid` (stop distance, stop basis, target size
  variants on the same signals).
- `tools/backtest.py` + `backtest` workflow: walk-forward replay of the
  scanner over the last N sessions (first-seen confirmed signals, next-open
  fills, gap filter, outcomes and R multiples overall / per pattern / per
  score bucket). `test_backtest.py` pins no-look-ahead and the fill rules.

### Changed
- `WATCH_PROXIMITY` 3 % → 5 %: a setup stays on the watchlist while its close
  is within 5 % below the trigger. At 3 %, ten of the 17 watchlist rows of
  2026-09-04 fell out on one ordinary down day.
- Nightly scan cron moved from 02:00 to 01:17 UTC: off the top of the hour,
  where GitHub delays scheduled runs most (the 2026-09-05 run started 4.5 h
  late), and with more margin before the 08:45 Israel e-mail.

### Added
- `Age` column in the report tables: bars since the breakout close over the
  pattern's limit (`1/3`), so a confirmed row shows whether it is fresh or
  about to expire; `-` for watchlist rows. Footer explains it.

### Fixed
- `daily-scan` rebases on `main` before pushing, so a PR merged while the
  scan runs no longer fails the run with a non-fast-forward push.
- `debug-last-bar` builds its commands as bash arrays (no word splitting
  or globbing of dispatch inputs).
- The constituent download is capped at `CONSTITUENTS_MAX_BYTES` (5 MB).
- `load_sp500_symbols` upper-cases symbols from a local CSV, matching `--tickers`.
- Tests: a W-shaped base is not a cup across its full span; zero-price bars
  never raise.

### Changed (detectors)
- One breakout evaluator (`evaluate_breakout`, trigger as a function of the
  bar) replaces `_status_from_break` plus the two inline copies in the H&S
  and Wolfe detectors. One behaviour change: a setup that broke out and
  pulled back below its trigger stays on the watchlist while within 3 % of
  it (it was dropped). The breakout clock still starts at the first close
  above the trigger; restarting it on every re-break was tried and rejected
  because it raised the confirmed false-positive rate on synthetic noise
  from about 1 % to 5 % of series. Fixture outputs unchanged.

### Fixed
- Inverse H&S neckline anchors are the rally peaks strictly between the
  shoulders and the head; a long upper wick on a shoulder or head bar no
  longer becomes an anchor. No change on the fixtures or 200 random walks.
- Strong-down-trend veto silently switched off for symbols with 200-239
  bars of history (SMA200 existed but not 40 bars earlier); it now falls
  back to the SMA50 test used for short histories.
- Wolfe targets are only reported when lines 1-3 and 2-4 meet within
  `WW_MAX_ETA_BARS` (250) after point 5; near-parallel lines no longer
  project absurd targets.
- One malformed history frame aborted the whole download; per-symbol
  cleaning (`_clean_history`) is now guarded, logged and skipped.
- `tools/evaluate_signals.py` fills stops and targets at the bar's open when
  the open gaps beyond the level, instead of assuming a fill at the level.
- `run_daily.sh` falls back to `shasum -a 256` where `sha256sum` is absent.
- Tests: fat-tailed (Student-t) noise sweep; `adjust_ohlc` documents why
  volume is intentionally not rescaled.

### Fixed (docs)
- Pattern catalog stated two gating rules with the wrong denominator: the
  cup prior-advance is a >= 25 % *rise* from the 120-bar low (not "low 25 %
  below the rim"), and the H&S prior-decline is >= 10 % *of the prior high*.
  It also claimed the cup trigger is <= rim B "by construction"; a wick above
  B later in the handle raises it. Tests now pin all three.
- Report footer and the catalog state that entry is the previous close and
  a trade fills at the next open.

### Added
- `LICENSE` (MIT) and a license badge / section in the README.

### Security
- Dependencies are hash-pinned: `requirements.txt` / `requirements-dev.txt`
  are compiled from `.in` files with pip-tools and every workflow and
  `run_daily.sh` install with `--require-hashes`. The nightly job (which
  pushes to `main` with a write token) previously resolved 23 packages
  fresh from PyPI on each run.
- Workflow-dispatch inputs in `debug-last-bar` and `evaluate-signals` are
  passed through `env:` instead of being interpolated into `run:` scripts.
- `SECURITY.md` added; `.gitignore` covers `.env*`, `.coverage`, `htmlcov/`.

### Changed (delivery)
- The report is e-mailed by a Claude desktop scheduled task at 08:45 Israel
  time (local-time cron, so no clock-change adjustment), replacing the
  04:00 UTC task. Docs and the workflow header updated; the e-mail marks
  stale and weekend reports.

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
