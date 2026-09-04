# SignalSync — S&P 500 Pattern Scanner

Daily scanner that checks every S&P 500 constituent (daily bars) for three
bullish chart patterns and reports actionable setups with an entry price and a
structural stop-loss:

| Pattern | Type | Trigger (confirmation) | Stop-loss | Reference target |
|---|---|---|---|---|
| Cup & Handle | continuation | daily close above the handle high | handle low − 0.25 ATR | entry + cup depth |
| Inverse Head & Shoulders | reversal | daily close above the neckline | right-shoulder low − 0.25 ATR | entry + (neckline − head) |
| Bullish Wolfe Wave | reversal | daily close back above the 1-3 line after point 5 | point-5 low − 0.25 ATR | line 1-4 at the ETA (EPA) |

It is a **heuristic screener, not trading advice**. Every hit should be checked
on a chart before acting.

## The four rules and how the code enforces them

The scanner implements the "common mistakes to avoid" rules the user supplied:

1. **Don't force a pattern that isn't there.** Each detector uses strict
   geometric thresholds (see *Parameters*), a convex-quadratic roundness test
   for cups, symmetry tests for shoulders, and Wolfe's "point 4 between 1 and
   2" rule. Every hit gets a 0–100 quality score; only hits ≥ `MIN_SCORE` (60)
   are reported, and overlapping pivot combinations are de-duplicated to the
   best one. On 200 synthetic random walks of 500 bars the detectors fire on
   1.5 % of series (see `test_scan.py`).
2. **Don't ignore the wider trend.** `trend_context()` computes SMA50/SMA200.
   Cup & Handle (a continuation pattern) requires the close above the SMA200.
   The two reversal patterns are vetoed when the stock is in a *strong*
   down-trend (close > 10 % below a falling SMA200); being above the SMA200
   adds to their score.
3. **Don't enter before confirmation.** A setup is `CONFIRMED` only when a
   daily *close* has broken its trigger level within the last
   `MAX_BREAKOUT_AGE` (3) bars (+ `PIVOT_ORDER` bars of pivot lag for H&S and
   Wolfe, whose final pivot is only knowable 5 bars after it prints). A close
   that has already run more than `MAX_RUNAWAY` (5 %) above the trigger is
   dropped as chasing. Complete-but-unbroken setups within 3 % of their
   trigger are listed separately as `WATCHLIST` with the trigger price, so
   nothing is entered early.
4. **Don't neglect risk management.** Every alert carries `entry`, `stop`,
   `risk_pct` and a reference `target`. Setups whose structural stop is more
   than 15 % away are rejected.

## Layout

```
scan.py                        detectors, data loading, reporting (single module, CLI)
test_scan.py                   synthetic-data + end-to-end tests (pytest)
.github/workflows/daily-scan.yml  GitHub Actions: daily 02:00 UTC scan, commits output/
run_daily.sh                   local wrapper (venv + deps) for running by hand
requirements.txt               pandas, numpy, yfinance
output/                        signals.json + report.md from the latest run (committed by CI)
logs/                          dated reports and logs from local runs (git-ignored)
```

## Architecture

```
GitHub Actions (02:00 UTC daily)          Claude scheduled task (04:00 UTC = 07:00 Israel*)
  checkout → pip install → pytest           curl raw.githubusercontent.com/yanivil/SignalSync/main/output/signals.json
  python scan.py  (yfinance, open internet) check meta.last_bar / meta.skipped_bar for staleness
  git commit output/report.md + signals.json  e-mail the tables via Gmail + push notification
```

The scan runs on GitHub because both the Claude cloud sandbox and the Claude
shell on the user's Mac sit behind a network policy that blocks every
market-data host (Yahoo, Stooq, Alpha Vantage, Nasdaq…); GitHub and PyPI are
reachable from both. The repo must be **public** (or the Claude task needs a
token) so `raw.githubusercontent.com` serves the report.

\* Israel is UTC+3 until 25 Oct 2026, then UTC+2 — the Claude task must move
to 05:00 UTC (and the workflow can stay at 02:00) after the clock change.

## Usage

```bash
pip install -r requirements.txt
python3 scan.py                       # full S&P 500 scan, 2 years of daily bars
python3 scan.py --tickers AAPL,MSFT   # subset
python3 scan.py --min-score 70 --max-age 2
bash run_daily.sh                     # local run with an auto-created venv
python3 -m pytest test_scan.py -q     # tests (no network needed)
```

The constituent list is fetched from the public
`datasets/s-and-p-500-companies` dataset on GitHub, pinned to a specific
commit (`CONSTITUENTS_COMMIT` in `scan.py`) rather than its `main` branch so an
upstream change cannot silently alter the scanned universe. Bump the commit
after reviewing the upstream diff to pick up index changes (`--csv` overrides
it with a local file). Prices come from Yahoo Finance via
`yfinance`. Class-share tickers are normalised (`BRK.B` → `BRK-B`).

## Output

`output/signals.json`:

```json
{"meta": {"run_date": "...", "universe": 503, "scanned": 502, "errors": 1,
          "last_bar": "2026-09-02", "last_bar_symbols": 502, "lagging_symbols": 0,
          "skipped_bar": "2026-09-03", "skipped_bar_complete": 2, "skipped_bar_partial": 500,
          "last_bar_histogram": {"2026-09-03": 2, "2026-09-02": 500},
          "min_score": 60, "max_breakout_age": 3,
          "max_breakout_age_by_pattern": {"Cup & Handle": 3,
                                          "Inverse Head & Shoulders": 8,
                                          "Bullish Wolfe Wave": 8}},
 "signals": [{"ticker": "XYZ", "pattern": "Cup & Handle", "status": "CONFIRMED",
              "entry": 102.0, "stop": 93.31, "risk_pct": 8.52, "target": 128.11,
              "score": 88, "last_close": 102.0, "last_date": "2026-09-02",
              "bars_since_break": 1, "volume_ratio": 1.47,
              "trend": "close above SMA200, SMA50 > SMA200, SMA200 rising/flat",
              "notes": "left rim 2026-03-04 @100.47, ..."}]}
```

### Which bar is scanned (`meta.last_bar`)

Yahoo publishes the previous session's daily row in two steps: first a
volume-only row (open/high/low/close null), then the prices some hours later.
At 07:30 UTC on 2026-09-04, 501 of 503 symbols still had the volume-only row
for 2026-09-03 and only two (APH, HUBB) had the complete bar. Rows without a
close are dropped per symbol, and then `align_last_bar()` picks the scan bar:

* `last_bar` is the newest date on/after which at least `LAST_BAR_MIN_FRACTION`
  (50 %) of the symbols have a complete bar, i.e. the majority's newest
  complete bar. Every signal's `last_date` is `<= last_bar`.
* Symbols that already have newer bars are truncated to `last_bar` so all
  signals are comparable; `skipped_bar` names the newest date that was seen
  but not scanned, with how many symbols had it complete
  (`skipped_bar_complete`) and how many only volume-only
  (`skipped_bar_partial`).
* Symbols whose newest complete bar is *older* than `last_bar` (halted, late)
  are scanned on their own last bar and counted in `lagging_symbols`.

So on a normal early-morning run `last_bar` is the session *before* the last
one and `skipped_bar` is the last session. The daily-scan log prints the same
histogram (`last raw bar per symbol` / `last complete bar per symbol`), and
`tools/debug_last_bar.py` (also runnable as the `debug-last-bar` workflow)
dumps the per-symbol detail.

### Breakout age

`max_breakout_age` is the base limit; `max_breakout_age_by_pattern` is the
effective limit the detectors apply. H&S and Wolfe get `PIVOT_ORDER` (5)
extra bars because their final pivot (right shoulder / point 5) is a swing
low that is only visible 5 bars after it prints, so with the defaults a
Cup & Handle breakout may be at most 3 bars old and an H&S or Wolfe breakout
at most 8. The report header states the same numbers.

`output/report.md` is the same content as two Markdown tables (Confirmed /
Watchlist), which the scheduled task forwards by e-mail and push notification.

## Parameters

All thresholds are module-level constants at the top of `scan.py`:

| Constant | Default | Meaning |
|---|---|---|
| `PIVOT_ORDER` | 5 | bars on each side to qualify a swing high/low |
| `MIN_SCORE` | 60 | minimum quality score to report |
| `MAX_BREAKOUT_AGE` | 3 | max bars since the confirming close (Cup & Handle; +`PIVOT_ORDER` for H&S and Wolfe, see `BREAKOUT_AGE_LAG`) |
| `LAST_BAR_MIN_FRACTION` | 0.5 | share of symbols that must have a complete bar on/after a date for it to be `meta.last_bar` |
| `MAX_RUNAWAY` | 0.05 | max close/trigger excess before it counts as chasing |
| `WATCH_PROXIMITY` | 0.03 | unbroken setups within this of trigger → watchlist |
| `CUP_MIN_LEN / CUP_MAX_LEN` | 30 / 250 | cup width in bars |
| `CUP_MIN_DEPTH / CUP_MAX_DEPTH` | 0.12 / 0.50 | cup depth vs left rim |
| `CUP_RIM_TOL` | 0.05 | right rim within 5 % of left rim |
| `CUP_PRIOR_ADVANCE` | 0.25 | ≥ 25 % rise into the left rim |
| `CUP_MIN_ROUNDNESS` | 0.60 | R² of convex quadratic fit of cup lows |
| `HANDLE_MIN_LEN / HANDLE_MAX_LEN` | 5 / 40 | handle length in bars |
| `HANDLE_MAX_DEPTH` | 0.12 | handle depth vs right rim |
| `HANDLE_MAX_FRACTION_OF_CUP` | 0.50 | handle depth vs cup depth |
| `IHS_MIN_LEN / IHS_MAX_LEN` | 20 / 200 | shoulder-to-shoulder width |
| `IHS_MIN_HEAD_ATR` | 1.0 | head below shoulders by ≥ 1 ATR |
| `IHS_SHOULDER_SYM` | 0.50 | shoulder price asymmetry vs shallower depth |
| `IHS_TIME_SYM` | 2.5 | left/right duration ratio limit |
| `IHS_MAX_NECK_SLOPE` | 0.15 | neckline slope over pattern, fraction of price |
| `IHS_PRIOR_DECLINE` | 0.10 | ≥ 10 % decline into the left shoulder |
| `WW_MIN_LEN / WW_MAX_LEN` | 15 / 200 | point-1 to point-5 width |
| `WW_MAX_OVERSHOOT_ATR` | 2.0 | max undercut of line 1-3 by point 5 |
| `WW_MAX_BARS_SINCE_P5` | 25 | point 5 must be recent |

## Known limitations

* Pattern recognition is heuristic; parameters follow common practice (O'Neil,
  Bulkowski, Wolfe) but there is no industry standard. Expect some false
  positives and misses — check the chart.
* Swing points are only recognised `PIVOT_ORDER` bars after they print, so
  H&S and Wolfe confirmations are reported with a lag of up to 5 bars.
* Yahoo Finance data is unofficial and occasionally incomplete; symbols with
  fewer than 60 bars are skipped and counted in `meta.errors`.
* The detectors were validated on synthetic data only (the development
  environment had no market-data access); the first real runs should be
  reviewed against charts and thresholds tuned if needed.

## Scheduling & first-time setup

1. The public GitHub repo is `yanivil/SignalSync`; push
   this project (feature branch → PR → merge to `main`; scheduled workflows
   only run from the default branch).
2. In the repo, *Actions* → *daily-scan* → *Run workflow* once to verify the
   runner can download data; it commits `output/report.md`.
3. The Claude scheduled task (04:00 UTC daily) reads that file and e-mails
   it. Because Yahoo has usually not published the last session's prices by
   then, `meta.last_bar` is normally the session *before* the last one and
   `meta.skipped_bar` is the last session (see "Which bar is scanned"); the
   task should treat the file as stale only when `last_bar` is older than
   that, or when `run_date` is not today.
