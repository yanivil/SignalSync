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
| `test_universe_history.py` | `tools/universe_history.py`: the commit list of a temporary dataset repository, the snapshot in force on a date (the commit day itself, dates before the first commit, commits that do not touch the file), Yahoo-format symbols, the union over a window, per-year coverage, and the cached bare clone with its refresh |
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

`tools/backtest.py` is the fast path: for each of the last N sessions it truncates every symbol's history at that day, runs the scanner exactly as the nightly job would have, takes each `CONFIRMED` signal on the day it first appears, fills at the next session's open, and classifies the outcome within a horizon. Two kinds of open are not traded and counted separately: one above the row's Max buy (`gap`) and one at or below the stop (`below_stop`, where nobody buys and R would be undefined). Output, overall, per pattern and per score bucket: hit rate, mean R, median R, standard deviation, total R, the deepest drawdown of the cumulative R curve (1 R per trade, in scan order), a 95 % bootstrap interval of the mean R and the drawdown exceeded in only 5 % of resamples, the chart-book "+5 % before a close below the stop" success share and mean MFE / MAE; then every signal; and (with `--grid`) the same signals re-scored under stop-distance, stop-basis and target variants (reported measured move, half of it, and the Investopedia bottom-to-breakout measure for cups), plus a second full walk-forward under the other rule profile (`spec` vs `legacy`) so both rule sets are compared on the same data, per pattern and per score bucket. `--profile` picks the primary profile.

The bootstrap resamples scan **months**, not trades: signals arrive in clusters (33 in one month and 2 in another over 2024-26), so treating them as independent draws would make the interval far too narrow. An interval is only printed with at least two months and five trades.

Two more tables follow each summary. **Excursions by horizon** gives, overall and per pattern, the median MFE and MAE within the first 5, 10, 20, 40 and 60 bars after the fill, in percent and in ATR, and the share of signals that had reached the target, hit the stop or done neither by then (medians, because a few runaway winners dominate the means). **Outcome by feature** buckets the traded signals by features measured at the scan day from the history the scan saw: breakout volume ratio, close vs SMA200, SMA50 vs SMA200, the SMA200's change over 40 bars, the distance from the SMA200 in ATR, the stop distance in ATR, risk %, reward:risk, the bars from the pattern's last anchor to the breakout, and the breakout age when first reported. Bucket edges are fixed (`FEATURE_BUCKETS` in `tools/backtest.py`) so two replays, or the two windows of a split, compare bucket by bucket; each row shows N, hit rate, mean and median R and the month-block interval. Nothing is added to `signals.json` or the report: the features exist to be tested, and a feature earns a rule only if its buckets separate outcomes by more than their intervals on both windows of a split.

**Out-of-sample check.** `--split YYYY-MM-DD` prints every table three times: all sessions, the sessions before the date, and the sessions from it. A rule chosen on one window is judged on the other; how the windows are used is the protocol in [Configuration and Tuning](03-Configuration-and-Tuning.md). `--bars 500` makes each scan see only its last 500 bars, which is what the nightly's `2y` download gives it, so a `--period 5y --days 500` replay reproduces two years of nightly runs rather than scans with ever-longer histories. Caveats: today's constituents only (survivorship bias), the last `horizon` sessions are still open, and both replayed years to 2026-09 were mostly bull markets.

**Point-in-time universe.** By default a replay scans today's constituents, so symbols that left the index during the window are missing and symbols that joined are present before they joined: survivorship bias, which flatters bullish patterns (the dataset's 2016 snapshot holds 179 symbols that are not members today). `--constituents-asof` (workflow input `asof=true`) reconstructs the membership as of each scan day from the git history of the constituent dataset the scanner already pins: `tools/universe_history.py` makes a bare, blobless clone of `datasets/s-and-p-500-companies` under `.cache/` (under 1 MB, refreshed by a fetch on later runs), reads `data/constituents.csv` at the last commit on or before each day, downloads the union of members over the window, and scans a symbol only on the days it was a member. The report opens with a coverage table: members per year and how many of them have Yahoo history. Two limits remain. The dataset records a change some days after the index does, with about weekly commits since 2020 but one a year in 2017-2019. And a symbol that no longer trades, or was renamed, has no Yahoo history, so the replay still cannot trade it; the coverage table is the measure of the survivorship bias that is left (a transient Yahoo miss counts the same way, so compare the share across runs before reading much into one). Eleven such runs, one per calendar year from 2016 to 2026, are the multi-year evidence on the [tuning page](03-Configuration-and-Tuning.md): the tuned profile at +0.23 R per trade, positive in ten of eleven years, with drawdowns of up to 41 R inside a year. `--end YYYY-MM-DD` (input `end`) replays the `--days` sessions on or before a date, so a past year is one dispatch, and `grid=false` skips the variants and the other profile's pass when only the primary profile matters. The download must reach the window: `period=10y` for anything from 2016 on.

A runner replays about 5 seconds per session per profile over the full index, and the workflow runs `--grid` unless `grid=false`, which adds the other profile's pass:

```bash
gh workflow run backtest.yml -f days=63 -f horizon=40                                              # about 10 minutes
```

```bash
gh workflow run backtest.yml -f period=5y -f days=500 -f bars=500 -f split=2025-09-09 -f horizon=60   # two years, about 90 minutes
```

```bash
gh workflow run backtest.yml -f period=10y -f end=2022-12-30 -f days=250 -f bars=500 -f asof=true -f grid=false -f horizon=60   # 2022 as it was, about 25 minutes
```

`tools/evaluate_signals.py` reads every version of `output/signals.json` from git history (the daily scan commits one per run), keeps the first appearance of each `CONFIRMED` signal keyed on `(ticker, pattern, stop)`, fetches the bars that followed, and classifies each as `target` (High reached the target before Low touched the stop), `stop`, `open` (neither within the horizon, marked to the last close) or `no_data`. R multiples are `(exit − entry) / (entry − stop)`. Run it on GitHub (`gh workflow run evaluate-signals.yml -f horizon=60`) because market-data hosts may be blocked locally.
