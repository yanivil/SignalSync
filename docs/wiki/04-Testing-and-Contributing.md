# Testing and Contributing

## Running the tests

```bash
python -m venv .venv && . .venv/bin/activate && pip install --require-hashes -r requirements.txt -r requirements-dev.txt
```

```bash
python -m pytest -q
```

The whole suite is offline and deterministic (synthetic price paths, an in-memory `yfinance` stand-in, `time.sleep` replaced) and runs in about two seconds. `-s` shows the random-walk false-positive rate. The `tests` workflow runs lint (`ruff check --select E,F,W --line-length 120 .`), the suite and a coverage report on every pull request and push to `main`; the daily scan runs the suite again before scanning.

## Suite layout

| File | What it covers |
|---|---|
| `test_scan.py` | the original suite: one textbook fixture per pattern, the 200-series random-walk sweep, short/NaN robustness, symbol normalisation, CLI end-to-end with the download mocked, last-bar alignment, quote-based close filling, adjustment, exchange-time index normalisation |
| `test_patterns.py` | primitives against hand-computed values (pivots and their tie rule, ATR, roundness R², the breakout state table, trend states, volume ratio); every entry/stop/target/risk recomputed independently from the anchors in `notes` and the documented spec-profile formulas (rollback, rim-of-depth, head height, sweet zone, rhythm, volume confirmation); single-rule mutations that must be rejected; legacy-only rules (prior-advance rise, down-trend veto, volume as a bonus) checked under the `legacy` profile; flat/line/random controls; missing bars, zero volume, wick spikes, an unadjusted split; determinism |
| `test_pipeline.py` | retry policy of the per-symbol download (back-off, no final sleep, delisted not retried), universe loading from CSV and the no-source error, the end-to-end mini universe (CSV → download with one throttled and one delisted symbol → alignment → detection → JSON schema, ordering, report formatting incl. the Max buy and Age columns, `--min-score`, exit code 2), the close-out classification of vanished rows, and a second run that reports what happened to the first run's rows |
| `test_evaluate.py` | `tools/evaluate_signals.py`: outcome classification (target / stop / open / no data, R multiples, horizon), summary statistics, and the git signal log built from a temporary repository (de-duplication on first confirmed appearance, unreadable commits skipped) |
| `conftest.py` | fixtures: fresh fixture frames, `flat_df`, `mini_universe`, and `fake_yfinance(frames, metas, failures)` which installs a fake `yfinance` module and records history calls and sleeps |

### Fixture builders

`test_scan.py` owns the synthetic path builders and `conftest.py` re-exports them:

* `_ohlc_from_path(path, seed, noise, end)` turns a close path into an OHLCV frame on business days ending at `END` (2025-06-02). Every synthetic series must end on the same date, otherwise `align_last_bar` treats the longest one as running ahead and truncates it.
* `make_cup_and_handle()`, `make_inverse_hs()`, `make_bullish_wolfe()` each contain exactly one textbook instance, confirmed on the last bars.
* `test_patterns.py` exposes `cup_variant`, `ihs_variant`, `wolfe_variant` which rebuild the same fixture with one component swapped, for rule-boundary tests.
* `_close_print(day, price)` builds Yahoo chart meta for a 16:00 New York closing print.

## Adding a new pattern

1. **Constants** at the top of `scan.py`, in a clearly labelled block, with a one-line "why" comment per threshold.
2. **Detector** `detect_<name>(df: pd.DataFrame, ticker: str) -> List[Signal]` that:
   * bails out early on insufficient bars and on the trend gate,
   * builds anchors from `find_pivots`, applies hard geometric rejects, then computes trigger, entry, stop, target and a 0–100 score with the same 50-base convention,
   * uses `evaluate_breakout` with the trigger as a function of the bar index (constant or sloping) and the pattern's floor, so `CONFIRMED` / `WATCHLIST` / stale semantics match,
   * enforces `stop < entry` and `risk_pct ≤ 15`,
   * writes parseable anchor dates and levels into `notes`,
   * returns `_dedupe(signals)`.
3. **Register** it in `scan_symbol`'s detector tuple and add its pivot lag to `BREAKOUT_AGE_LAG` (0 if its last anchor needs no right-side confirmation, `PIVOT_ORDER` if it is a swing point).
4. **Tests**: a `make_<name>()` fixture in `test_scan.py` with one textbook instance; a formula-verification test in `test_patterns.py` that recomputes the levels from `notes`; a parametrised list of single-rule mutations that must return `[]`; make sure the random-walk sweep stays under 5 %.
5. **Docs**: a section in [Pattern Catalog](02-Pattern-Catalog.md) with the exact criteria and formulas, a row in the README table, and the constants in [Configuration and Tuning](03-Configuration-and-Tuning.md).

## Code style

* One module, sections separated by the existing banner comments. Keep the constants block auditable: no magic numbers inside detectors that are not either a constant or explained in a comment.
* Docstrings use the file's existing Sphinx field style (`:param:`, `:returns:`, `:raises:`) and state complexity where it is not obvious. Comments explain **why**, not what; the geometry is annotated where it is non-trivial (roundness, neckline tilt, Wolfe ETA/EPA, score composition).
* Full type hints on every public function; `Dict[str, pd.DataFrame]` rather than bare `dict`.
* Tests never touch the network. Mock at the `yfinance` module boundary with the `fake_yfinance` fixture, not inside `scan`.
* `scan.main()` rewrites `MIN_SCORE` and `MAX_BREAKOUT_AGE`, and tests may call `scan.apply_profile("legacy")`; the autouse fixture in `conftest.py` restores the tunables and re-applies the `spec` profile after every test.
* A rule change goes into the constants block with a one-line "why", and the previous value into `RULE_PROFILES["legacy"]` if the behaviour differs; the backtest then compares both on the same data before the default is switched.
* Keep `CHANGELOG.md` current (Keep-a-Changelog format) and record real-market observations (dates, counts) in comments when a behaviour was derived from one.

## Dependencies

`requirements.txt` and `requirements-dev.txt` are compiled with hashes from `requirements.in` / `requirements-dev.in` (pip-tools), and every workflow and `run_daily.sh` install with `--require-hashes`, so a new upstream release can never enter a run until it has been compiled in here and merged through a pull request. Dependabot proposes those bumps weekly. To change a dependency, edit the `.in` file and recompile:

```bash
pip install pip-tools && pip-compile --generate-hashes --strip-extras -o requirements.txt requirements.in && pip-compile --generate-hashes --strip-extras -c requirements.txt -o requirements-dev.txt requirements-dev.in
```

## Branching and CI

Work on a feature branch and open a PR to `main`; the `tests` workflow must pass. Scheduled workflows run only from the default branch. Actions are pinned to full commit SHAs (repo policy) and updated by Dependabot.

| Workflow | Trigger | Purpose |
|---|---|---|
| `tests` | pull requests, pushes to `main` | lint, tests, coverage |
| `daily-scan` | 01:17 UTC daily, manual | tests, full scan, commit `output/` |
| `debug-last-bar` | manual, pushes touching its files | read-only per-symbol bar diagnostics |
| `evaluate-signals` | manual | replay every committed `CONFIRMED` signal against later prices; Markdown table in the job summary |
| `backtest` | manual, pushes touching its files | walk-forward replay of the scanner over the last N sessions; overall / per-pattern / per-score-bucket hit rates and R multiples in the job summary |
| `sync-wiki` | pushes to `main` touching `docs/wiki/`, manual | mirror `docs/wiki/` into the GitHub wiki |

## Measuring signal outcomes

`tools/backtest.py` is the fast path: for each of the last N sessions it truncates every symbol's history at that day, runs the scanner exactly as the nightly job would have, takes each `CONFIRMED` signal on the day it first appears, fills at the next session's open (opens above the row's Max buy are "gapped", not traded), and classifies the outcome within a horizon. Output: overall, per-pattern and per-score-bucket hit rates and mean R, the chart-book "+5 % before a close below the stop" success share and mean MFE / MAE, every signal, and (with `--grid`) the same signals re-scored under stop-distance, stop-basis and target variants (reported measured move, half of it, and the Investopedia bottom-to-breakout measure for cups), plus a second full walk-forward under the other rule profile (`spec` vs `legacy`) so both rule sets are compared on the same data, per pattern and per score bucket. `--profile` picks the primary profile. Caveats: today's constituents only (survivorship bias), and the last `horizon` sessions are still open. Dispatch with `gh workflow run backtest.yml -f days=63 -f horizon=40`; about 2 minutes for the full index.

`tools/evaluate_signals.py` reads every version of `output/signals.json` from git history (the daily scan commits one per run), keeps the first appearance of each `CONFIRMED` signal keyed on `(ticker, pattern, stop)`, fetches the bars that followed, and classifies each as `target` (High reached the target before Low touched the stop), `stop`, `open` (neither within the horizon, marked to the last close) or `no_data`. R multiples are `(exit − entry) / (entry − stop)`. Run it on GitHub (`gh workflow run evaluate-signals.yml -f horizon=60`) because market-data hosts may be blocked locally.
