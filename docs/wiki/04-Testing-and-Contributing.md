# Testing and Contributing

## Running the tests

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt pytest
```

```bash
python -m pytest -q
```

The whole suite is offline and deterministic (synthetic price paths, an in-memory `yfinance` stand-in, `time.sleep` replaced) and runs in about two seconds. `-s` shows the random-walk false-positive rate. CI runs the same command before every scheduled scan (`.github/workflows/daily-scan.yml`).

## Suite layout

| File | What it covers |
|---|---|
| `test_scan.py` | the original suite: one textbook fixture per pattern, the 200-series random-walk sweep, short/NaN robustness, symbol normalisation, CLI end-to-end with the download mocked, last-bar alignment, quote-based close filling, adjustment, exchange-time index normalisation |
| `test_patterns.py` | primitives against hand-computed values (pivots and their tie rule, ATR, roundness R², the breakout state table, trend states, volume ratio); every entry/stop/target/risk recomputed independently from the anchors in `notes` and the documented formulas; single-rule mutations that must be rejected; flat/line/random controls; missing bars, zero volume, wick spikes, an unadjusted split; determinism |
| `test_pipeline.py` | retry policy of the per-symbol download (back-off, no final sleep, delisted not retried), universe loading from CSV and the no-source error, and the end-to-end mini universe (CSV → download with one throttled and one delisted symbol → alignment → detection → JSON schema, ordering, report formatting, `--min-score`, exit code 2) |
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
   * uses `_status_from_break` (or the same three-way logic) so `CONFIRMED` / `WATCHLIST` / stale semantics match,
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
* `scan.main()` rewrites `MIN_SCORE` and `MAX_BREAKOUT_AGE`; the autouse fixture in `conftest.py` restores them, so tests may call `main()` freely.
* Keep `CHANGELOG.md` current (Keep-a-Changelog format) and record real-market observations (dates, counts) in comments when a behaviour was derived from one.

## Branching and CI

Work on a feature branch and open a PR to `main`; scheduled workflows run only from the default branch. Actions are pinned to full commit SHAs (repo policy) and updated by Dependabot. The `debug-last-bar` workflow is a read-only diagnostic you can dispatch against any branch.
