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
  python scan.py  (yfinance, open internet) check meta.last_bar is the latest trading day
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

The constituent list is fetched from
`https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv`
(`--csv` overrides it with a local file). Prices come from Yahoo Finance via
`yfinance`. Class-share tickers are normalised (`BRK.B` → `BRK-B`).

## Output

`output/signals.json`:

```json
{"meta": {"run_date": "...", "universe": 503, "scanned": 500, "errors": 3,
          "last_bar": "2026-09-03", "min_score": 60, "max_breakout_age": 3},
 "signals": [{"ticker": "XYZ", "pattern": "Cup & Handle", "status": "CONFIRMED",
              "entry": 102.0, "stop": 93.31, "risk_pct": 8.52, "target": 128.11,
              "score": 88, "last_close": 102.0, "last_date": "2026-09-03",
              "bars_since_break": 1, "volume_ratio": 1.47,
              "trend": "close above SMA200, SMA50 > SMA200, SMA200 rising/flat",
              "notes": "left rim 2026-03-04 @100.47, ..."}]}
```

`output/report.md` is the same content as two Markdown tables (Confirmed /
Watchlist), which the scheduled task forwards by e-mail and push notification.

## Parameters

All thresholds are module-level constants at the top of `scan.py`:

| Constant | Default | Meaning |
|---|---|---|
| `PIVOT_ORDER` | 5 | bars on each side to qualify a swing high/low |
| `MIN_SCORE` | 60 | minimum quality score to report |
| `MAX_BREAKOUT_AGE` | 3 | max bars since the confirming close |
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
   it. If the file's `meta.last_bar` is older than the last trading day the
   task reports the staleness instead of sending stale alerts.
