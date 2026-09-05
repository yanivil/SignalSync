# Configuration and Tuning

All thresholds are module-level constants at the top of `scan.py`. Two of them (`MIN_SCORE`, `MAX_BREAKOUT_AGE`) can also be set per run from the CLI; everything else is edited in the file so the rules stay auditable in one place. There are no environment variables and no API keys.

## CLI

| Flag | Default | Effect |
|---|---|---|
| `--tickers A,B,C` | full S&P 500 | scan only these symbols (upper-cased) |
| `--csv path` | pinned GitHub dataset | local constituents CSV; `Symbol` column or first column |
| `--period` | `2y` | yfinance period; `2y` gives about 500 daily bars, enough for SMA200 plus a 250-bar cup |
| `--min-score` | 60 | overrides `MIN_SCORE` for the run and is echoed in `meta.min_score` |
| `--max-age` | 3 | overrides `MAX_BREAKOUT_AGE`; the effective per-pattern limits are in `meta.max_breakout_age_by_pattern` |
| `--out-dir` | `output` | destination for `signals.json` and `report.md` |
| `-v` | off | DEBUG logging, including per-symbol last-bar detail |

## Global gates

| Constant | Default | What it controls | Loosen → | Tighten → |
|---|---|---|---|---|
| `PIVOT_ORDER` | 5 | bars on each side needed to call a swing high/low | fewer bars: more (noisier) pivots, patterns visible sooner | fewer, cleaner pivots; H&S/Wolfe seen later; `BREAKOUT_AGE_LAG` follows it automatically |
| `ATR_LEN` | 14 | ATR window used for stops and the head/overshoot tests | | |
| `MIN_SCORE` | 60 | minimum quality score reported | more marginal setups | only the cleanest geometry |
| `MAX_BREAKOUT_AGE` | 3 | max bars since the confirming close (Cup); +`PIVOT_ORDER` for H&S and Wolfe | older breakouts reported | only fresh breakouts |
| `BREAKOUT_AGE_LAG` | Cup 0, H&S 5, Wolfe 5 | extra age tolerated because the last pivot lags | | |
| `MAX_RUNAWAY` | 0.05 | close more than this above the trigger = chasing, dropped | | |
| `WATCH_PROXIMITY` | 0.05 | setups whose close is within this of the trigger → watchlist (was 0.03 until 2026-09-05; at 3 % a normal down day cleared most of the list) | longer watchlist | shorter watchlist |
| `LAST_BAR_MIN_FRACTION` | 0.5 | share of symbols that must have a complete bar for it to be `meta.last_bar` | | |
| `FILL_CLOSE_MIN_AGE` | 1 h | how old the last trade must be to count as the closing print | | |
| `CONSTITUENTS_COMMIT` | 2026-08-20 hash | pinned upstream commit of the constituent CSV | | |

## Trend gate

| Constant | Default | Meaning | Tuning note |
|---|---|---|---|
| `TREND_STRONG_DOWN` | 0.90 | close below this fraction of a *falling* SMA200 = strong down-trend; reversal patterns are vetoed | 1.0 would veto any close below a falling SMA200 |
| `TREND_SLOPE_LOOKBACK` | 40 | bars back used to decide whether the SMA200 is falling | shorter reacts faster to a roll-over, longer ignores wobble |
| `TREND_STRONG_DOWN_SMA50` | 0.85 | the same test against SMA50 when fewer than 200 bars exist, or when the SMA200's slope cannot be judged yet (200–239 bars) | |

The up-trend requirement for the cup (close above SMA200) is not a constant.

## Cup & Handle

| Constant | Default | Meaning | Tuning note |
|---|---|---|---|
| `CUP_MIN_LEN` / `CUP_MAX_LEN` | 30 / 250 | rim-to-rim width in bars | O'Neil: 7 weeks to a year; 30 bars is already short |
| `CUP_MIN_DEPTH` / `CUP_MAX_DEPTH` | 0.12 / 0.50 | depth as a fraction of the left rim | the score peaks at 25 % |
| `CUP_RIM_TOL` | 0.05 | right rim within 5 % of the left rim | wider tolerance admits ascending/descending cups |
| `CUP_PRIOR_ADVANCE` | 0.25 | required rise into the left rim (120-bar look-back) | the main "it must be continuing something" filter |
| `CUP_MIN_ROUNDNESS` | 0.60 | R² of the convex quadratic fit of cup lows | rejects ragged bases; on its own it would pass a clean V (R² ≈ 0.93) |
| `CUP_MAX_V_ADVANTAGE` | 0.0 | how much the best two-legged V fit's R² may exceed the parabola's | 0 = the U must explain the lows at least as well as a V; negative values demand a clear U; ~0.07 would re-admit clean Vs |
| `HANDLE_MIN_LEN` / `HANDLE_MAX_LEN` | 5 / 40 | handle length in bars | below 5 bars a close above the running high is treated as the handle still forming |
| `HANDLE_MAX_DEPTH` | 0.12 | handle pull-back vs. the right rim | O'Neil's 12 % |
| `HANDLE_MAX_FRACTION_OF_CUP` | 0.50 | handle depth vs. cup depth | |

Not configurable but relevant: the cup bottom must sit in the middle 60 % of the cup, and the handle low must stay in the upper half of the cup.

## Inverse Head & Shoulders

| Constant | Default | Meaning | Tuning note |
|---|---|---|---|
| `IHS_MIN_LEN` / `IHS_MAX_LEN` | 20 / 200 | shoulder-to-shoulder width | |
| `IHS_MIN_HEAD_ATR` | 1.0 | head at least this many ATR below both shoulders | the scale-free "is there really a head" test |
| `IHS_SHOULDER_SYM` | 0.50 | shoulder gap as a fraction of the shallower shoulder depth | |
| `IHS_TIME_SYM` | 2.5 | max ratio of left-half to right-half duration | |
| `IHS_MAX_NECK_SLOPE` | 0.15 | neckline change over the width, as a fraction of the head price | beyond this it is a trend line |
| `IHS_PRIOR_DECLINE` | 0.10 | required decline into the left shoulder as a share of the 60-bar high | |

## Bullish Wolfe Wave

| Constant | Default | Meaning | Tuning note |
|---|---|---|---|
| `WW_MIN_LEN` / `WW_MAX_LEN` | 15 / 200 | point-1 to point-5 width | |
| `WW_MAX_OVERSHOOT_ATR` | 2.0 | max undercut of line 1-3 by point 5 | more = accepts deeper false breakdowns; the −0.5 ATR "must reach the line" floor is fixed |
| `WW_MAX_BARS_SINCE_P5` | 25 | point 5 must be within the last 25 bars | |
| `WW_MAX_ETA_BARS` | 250 | lines 1-3 and 2-4 must meet within this many bars after point 5 for a target to be reported | guards against near-parallel lines projecting absurd targets |
| `WW_MAX_TARGET_GAIN` | 1.0 | no target when line 1-4 at the ETA is more than +100 % above the entry | a year of replay produced +590 % and +120 % "targets" |

## False-positive filters, in the order they act

1. **Trend gate** — the cheapest filter; runs before any pivot search. Cups need an up-trend; reversal patterns are vetoed in a strong down-trend.
2. **Geometry** — the width/depth/symmetry/slope rules above. Each is a hard reject.
3. **Prior move** — a cup must continue a ≥ 25 % advance, an inverse H&S must reverse a ≥ 10 % decline.
4. **Roundness** (cup only) — R² ≥ 0.60 and the parabola must fit at least as well as a V.
5. **Confirmation state** — stale (> age limit), failed (closed back below the trigger) and runaway (> 5 % above) breakouts are dropped; setups more than 5 % below the trigger are dropped.
6. **Risk** — stop above entry or risk > 15 % is dropped.
7. **Score** — everything surviving with a score below `MIN_SCORE` is dropped.
8. **De-duplication** — only the best-scoring signal per `(ticker, pattern, status)` is kept, so overlapping pivot combinations never inflate the count.

## Measuring the effect of a change

The random-walk sweep in `test_scan.py::test_random_walk_false_positive_rate` prints the share of 200 synthetic 500-bar series on which any detector fires (baseline 1.5 %, hard limit 5 %):

```bash
python -m pytest test_scan.py -k random_walk -q -s
```

For sensitivity, run the negative-control mutations (`test_patterns.py -k violations`) after loosening a threshold: each mutation names the rule it violates, so a newly passing mutation tells you which rule you have effectively removed.

```bash
python -m pytest test_patterns.py -k "violations or controls" -q
```

Suggested procedure for a real-data tuning pass: run the scan on a date range with `--tickers` on a small set, compare `notes` against the chart, adjust one constant, re-run both commands above, and only then re-scan.
