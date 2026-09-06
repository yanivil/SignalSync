# Configuration and Tuning

All thresholds are module-level constants at the top of `scan.py`. Two of them (`MIN_SCORE`, `MAX_BREAKOUT_AGE`) can also be set per run from the CLI; everything else is edited in the file so the rules stay auditable in one place. There are no environment variables and no API keys.

## Rule profiles

Since 2026-09-05 the pattern rules follow the engine specification (the **spec** profile, the module defaults). The rules in force before that date are kept as the **legacy** profile in `RULE_PROFILES`, so the two can be compared on the same data:

```bash
python scan.py --profile legacy            # scan with the old rules
```

```bash
gh workflow run backtest.yml -f profile=spec   # replays spec, and legacy alongside it
```

`apply_profile(name)` switches the constants at run time; `signals.json` records the profile in `meta.profile`. A value of `None` switches an optional rule off. In the tables below, **spec** is the default and **legacy** the alternative.

A third profile, **tuned**, is the spec with the four rules changed that the 2026-09-05 rule ablation showed were removing good signals: volume confirmation off (back to a score bonus), IHS side-duration symmetry off, Wolfe leg rhythm loosened to ±45 %, cup rollback cap at the spec's own 61.8 % maximum; plus, since 2026-09-06, a minimum reward:risk of 1.0 and a 60-bar patience limit on watchlist rows (see "Calibrating the review rules" below). Everything else in it is the spec. The Wolfe rhythm value was chosen on a three-point replay: ±30 % kept 8 Wolfe signals a year at +0.37 R, ±45 % 28 at +0.13 R, ±60 % 43 at +0.02 R; ±45 % lifts the whole tuned profile to 177 signals at +0.34 R.

| Profile | What it is | Confirmed signals | Hit rate | Mean R | +5 % first | IHS | Wolfe | Cup |
|---|---|---|---|---|---|---|---|---|
| legacy | rules until 2026-09-05 | 354 | 33 % | +0.06 | 64 % | 87 at +0.20 R | 142 at −0.11 R | 125 at +0.16 R |
| spec | the engine specification as written | 22 | 53 % | +0.14 | 76 % | 10 at 0.00 R | 8 at +0.37 R | 4 at +0.03 R |
| **tuned** | spec with the four relaxations above (Wolfe rhythm ±45 %) | **177** | **50 %** | **+0.34** | 72 % | 129 at +0.40 R | 28 at +0.13 R | 20 at +0.23 R |

Year-long walk-forward replay, 250 sessions to 2026-09-04, horizon 60 bars, next-open fills, intraday stops (`backtest` workflow runs 33968691768, 33973275310 and 33985398488). Read with the usual caveats: today's constituents only, one year, one regime.

### Calibrating the review rules (2026-09-06)

An external review of the 2026-09-04 report (HAL entered late at R:R 1.16 on a 12 % stop; TXN's Max buy carrying 2.7× the planned risk) led to three candidate rules. Each was replayed alone on the tuned profile, 250 sessions to 2026-09-04, horizon 60 (`backtest` runs 34023518929 to 34023527178):

| Variant | Signals | Gapped | Hit rate | Mean R | +5 % first | Decision |
|---|---|---|---|---|---|---|
| tuned, no new rule | 177 | 11 | 48 % | +0.28 | 71 % | reference |
| `MIN_REWARD_RISK` 1.0 | 158 | 6 | 46 % | +0.29 | 71 % | **adopted** |
| `MIN_REWARD_RISK` 1.5 | 113 | 5 | 38 % | +0.30 | 65 % | expectancy-neutral, a third of the flow gone |
| `MIN_REWARD_RISK` 2.0 | 77 | 4 | 33 % | +0.29 | 67 % | Wolfe collapses to +0.05 R |
| `MAX_WAIT_BARS` 40 on all rows | 169 | 9 | 46 % | +0.25 | 70 % | the 8 removed breakouts averaged +1.1 R |
| `MAX_WAIT_BARS` 60 on all rows | 172 | 11 | 47 % | +0.26 | 70 % | same direction |
| `MAX_WAIT_BARS` 90 on all rows | 175 | 11 | 47 % | +0.27 | 70 % | same direction |

Reading: a reward:risk minimum trades hit rate for payoff almost exactly (small targets are hit more often and pay less), so it is set at 1.0, where it removes only rows whose target is below one risk unit at no cost in mean R. A patience limit on *breakouts* is wrong in every variant: the longer a base waited, the better its eventual breakout did. The limit therefore applies to watchlist rows only, where it costs nothing (a breakout is reported whenever it comes) and where 97 % of the year's eventual breakouts would have survived a 60-bar limit anyway.

**The nightly scan runs `--profile tuned`**, chosen on this evidence on 2026-09-05; the default in code stays `spec`. Change the flag in `.github/workflows/daily-scan.yml` to switch. The cup entry stays at the handle peak: a rim-B entry replayed at 19 cup signals and +0.17 R against 20 and +0.23 R. The grid also shows a close-based stop (exit on the first close at or below the stop) lifting tuned's mean R to +0.35 at a 52 % hit rate; the report's stop level is unchanged, that is an execution choice.

## CLI

| Flag | Default | Effect |
|---|---|---|
| `--tickers A,B,C` | full S&P 500 | scan only these symbols (upper-cased) |
| `--csv path` | pinned GitHub dataset | local constituents CSV; `Symbol` column or first column |
| `--period` | `2y` | yfinance period; `2y` gives about 500 daily bars, enough for SMA200 plus a 250-bar cup |
| `--min-score` | 60 | overrides `MIN_SCORE` for the run and is echoed in `meta.min_score` |
| `--max-age` | 3 | overrides `MAX_BREAKOUT_AGE`; the effective per-pattern limits are in `meta.max_breakout_age_by_pattern` |
| `--profile` | `spec` | rule profile, `spec` or `legacy`; echoed in `meta.profile` |
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

## Volume and risk (all patterns)

| Constant | spec | legacy | Meaning |
|---|---|---|---|
| `VOLUME_AVG_LEN` | 20 | 50 | bars in the average that the breakout-bar volume is compared with |
| `VOLUME_CONFIRM` | cup 1.4, H&S 1.3, Wolfe none | none | a breakout close is `CONFIRMED` only with at least this volume ratio; otherwise the row stays on the watchlist with the note "breakout without volume". A ratio ≥ 1.3 always adds +5 to the score. |
| `MAX_RISK_PCT` | cup 12, H&S 15, Wolfe 15 | 15 for all | reject setups whose stop is further than this below the entry |
| `MIN_REWARD_RISK` | off (tuned 1.0) | off | reject setups whose `(target − entry) / (entry − stop)` is below this; rows without a target are not judged |
| `MAX_WAIT_BARS` | off (tuned 60) | off | drop a **watchlist** row whose last anchor (handle low, right shoulder, point 5) is more than this many bars old; a breakout is reported whenever it comes |
| `MAX_BUY_RISK_MULT` | 1.5 | off | Max buy is also capped where the risk at the fill reaches this multiple of the planned risk; the backtest gaps fills above Max buy |

## Trend context

| Constant | Default | Meaning | Tuning note |
|---|---|---|---|
| `TREND_VETO_REVERSALS` | spec `False`, legacy `True` | reject H&S and Wolfe setups when `strong_downtrend` holds | the spec expects reversals in down-trends; the backtest's profile comparison shows what the veto costs |
| `TREND_STRONG_DOWN` | 0.90 | close below this fraction of a *falling* SMA200 = strong down-trend | only used by the veto and the trend description |
| `TREND_SLOPE_LOOKBACK` | 40 | bars back used to decide whether the SMA200 is falling | shorter reacts faster to a roll-over, longer ignores wobble |
| `TREND_STRONG_DOWN_SMA50` | 0.85 | the same test against SMA50 when fewer than 200 bars exist, or when the SMA200's slope cannot be judged yet (200–239 bars) | |
| `CUP_REQUIRE_CLOSE_ABOVE_SMA200` | spec `False`, legacy `True` | the cup's legacy gate | under spec the cup's trend filter is the SMA50/advance test below |

## Cup & Handle

| Constant | spec | legacy | Meaning | Tuning note |
|---|---|---|---|---|
| `CUP_MIN_LEN` / `CUP_MAX_LEN` | 20 / 300 | 30 / 250 | rim-to-rim width in bars | spec: minimum 20, typically 35–300 |
| `CUP_MIN_DEPTH` / `CUP_MAX_DEPTH` | 0.12 / 0.50 | same | depth as a fraction of the left rim | the spec is silent on a minimum; the score peaks at 25 % |
| `CUP_MAX_RETRACE` | 0.50 | off | the cup decline may not exceed this share of the preceding advance | the spec's "not more than 50 % (61.8 % absolute max)"; the rule that limits depth relative to the run-up |
| `CUP_ADVANCE_LOOKBACK` | 250 | – | window before rim A in which the preceding advance's low is sought | the spec does not define the window; a year lets a gradual advance count |
| `CUP_RIM_TOL_OF_DEPTH` | 0.15 | off | right rim within this share of the cup depth of the left rim | stricter than 5 % of price for shallow cups, looser for deep ones |
| `CUP_RIM_TOL` | 0.05 | 0.05 | right rim within 5 % of the left rim's price; used only when `CUP_RIM_TOL_OF_DEPTH` is off | |
| `CUP_BOTTOM_ZONE` | (0.25, 0.75) | (0.20, 0.80) | the lowest low must sit in this part of the span | |
| `CUP_PRIOR_ADVANCE` / `CUP_PRIOR_LOOKBACK` | 0.20 / 60 | 0.25 / 120 | required rise from the look-back low into the left rim | |
| `CUP_TREND_SMA_OR` | `True` | `False` | SMA50 > SMA200 satisfies the trend filter on its own | easy to satisfy after any cup, so under spec the rollback rule does most of the work |
| `CUP_MIN_ROUNDNESS` | 0.70 | 0.60 | R² of the convex quadratic fit of cup lows | rejects ragged bases; on its own it would pass a clean V (R² ≈ 0.93) |
| `CUP_MAX_V_ADVANTAGE` | 0.0 | 0.0 | how much the best two-legged V fit's R² may exceed the parabola's | 0 = the U must explain the lows at least as well as a V; ~0.07 would re-admit clean Vs |
| `HANDLE_MIN_LEN` / `HANDLE_MAX_LEN` | 5 / 25 | 5 / 40 | handle length in bars | below 5 bars a close above the running high is treated as the handle still forming |
| `HANDLE_MAX_LEN_OF_CUP` | 1.0 | off | handle bars ≤ cup bars × this | spec: the handle never outlasts the cup |
| `HANDLE_MAX_DEPTH` | 0.12 | same | handle pull-back vs. the right rim | O'Neil's 12 % |
| `HANDLE_MAX_FRACTION_OF_CUP` | 0.50 | same | handle depth vs. cup depth | |
| `CUP_TARGET_BASE` | `right_rim` | `left_rim` | the measured move is bottom → this level, added to the entry (`trigger` = Investopedia's breakout-level measure) | |
| `CUP_TRIGGER` | `handle_high` | same | breakout level: the handle peak (O'Neil's buy point) or `rim_b`, the higher of the handle peak and rim B, so the close must also clear the rim | a later, more conservative entry; compare with `gh workflow run backtest.yml -f overrides="CUP_TRIGGER=rim_b"` |

Not configurable: the handle low must stay in the upper half of the cup.

## Inverse Head & Shoulders

| Constant | spec | legacy | Meaning | Tuning note |
|---|---|---|---|---|
| `IHS_MIN_LEN` / `IHS_MAX_LEN` | 20 / 200 | same | shoulder-to-shoulder width | |
| `IHS_MIN_HEAD_ATR` | 1.0 | same | head at least this many ATR below both shoulders | the scale-free "is there really a head" test; the spec only asks for strictly lower |
| `IHS_SHOULDER_SYM_OF_HEIGHT` | 0.30 | off | shoulder gap as a share of the head height (neckline at the head bar minus head) | |
| `IHS_SHOULDER_SYM` | off | 0.50 | shoulder gap as a share of the shallower shoulder depth | |
| `IHS_SIDE_SYM_TOL` | 0.40 | off | the durations LS→N1 and N2→RS within this of each other | |
| `IHS_TIME_SYM` | 2.5 | same | max ratio of left-half to right-half duration (sanity bound) | |
| `IHS_MAX_NECK_SLOPE` | 0.15 | same | neckline change over the width, as a fraction of the head price | the spec's angle limits are scale-dependent; this is the usable form |
| `IHS_PRIOR_DECLINE_OF_HEIGHT` | 1.0 | off | required decline into LS, in head heights | |
| `IHS_PRIOR_DECLINE` | off | 0.10 | required decline into LS as a share of the 60-bar high | |
| `IHS_TREND_SMA_OR` | `True` | `False` | SMA50 < SMA200 satisfies the trend filter on its own | |
| `IHS_TARGET_AT_HEAD` | `True` | `False` | measured move uses the neckline at the head bar (spec) rather than at the break bar | identical for a flat neckline |

## Bullish Wolfe Wave

| Constant | spec | legacy | Meaning | Tuning note |
|---|---|---|---|---|
| `WW_MIN_LEN` / `WW_MAX_LEN` | 15 / 200 | same | point-1 to point-5 width | |
| `WW_SWEET_ZONE` | `True` | `False` | point 5 must be below line 1-3 and above the line through point 3 parallel to 2-4 | the classic Wolfe rule |
| `WW_MAX_OVERSHOOT_ATR` | 2.0 | 2.0 | legacy band: max undercut of line 1-3 by point 5 (also scales the score's overshoot term) | with the sweet zone on, only the score uses it |
| `WW_TIME_SYM_TOL` | 0.30 (tuned 0.45) | off | legs 1→2, 2→3, 3→4 each within this of their mean | replay: 0.30 → 8 signals at +0.37 R, 0.45 → 28 at +0.13, 0.60 → 43 at +0.02 |
| `WW_MAX_BARS_SINCE_P5` | 25 | same | point 5 must be within the last 25 bars | |
| `WW_MAX_ETA_BARS` | 250 | same | lines 1-3 and 2-4 must meet within this many bars after point 5 for a target to be reported | guards against near-parallel lines projecting absurd targets |
| `WW_MAX_TARGET_GAIN` | 1.0 | same | no target when line 1-4 at the ETA is more than +100 % above the entry | a year of replay produced +590 % and +120 % "targets" |

## False-positive filters, in the order they act

1. **Trend filter** — spec: the cup needs SMA50 > SMA200 or a 20 % rise into rim A; H&S needs SMA50 < SMA200 or a one-head-height decline into LS. Legacy: cups needed an up-trend and reversal patterns were vetoed in a strong down-trend.
2. **Geometry** — the width/depth/symmetry/slope/sweet-zone/rhythm rules above. Each is a hard reject.
3. **Rollback** (cup) — the decline may not exceed half the preceding advance.
4. **Roundness** (cup only) — R² ≥ 0.70 and the parabola must fit at least as well as a V.
5. **Confirmation state** — stale (> age limit) and runaway (> 5 % above) breakouts are dropped; setups more than 5 % below the trigger are dropped.
6. **Volume** — a breakout close without ≥ 1.4× (cup) or ≥ 1.3× (H&S) average volume is watch-listed, not confirmed.
7. **Risk** — stop above entry or risk above `MAX_RISK_PCT` is dropped.
8. **Patience** — a watchlist row whose last anchor is more than `MAX_WAIT_BARS` old is dropped (confirmed breakouts are exempt).
9. **Reward:risk** — a target less than `MIN_REWARD_RISK` planned risks above the entry is dropped.
10. **Score** — everything surviving with a score below `MIN_SCORE` is dropped.
11. **De-duplication** — only the best-scoring signal per `(ticker, pattern, status)` is kept, so overlapping pivot combinations never inflate the count.

## Measuring the effect of a change

The random-walk sweeps in `test_scan.py::test_random_walk_false_positive_rate` and `test_patterns.py::test_fat_tailed_noise_false_positive_rate` print the share of 200 synthetic 500-bar series on which any detector fires (spec profile: 4 and 3 of 200, all watchlist; hard limit 5 %):

```bash
python -m pytest test_scan.py -k random_walk -q -s
```

For sensitivity, run the negative-control mutations (`test_patterns.py -k violations`) after loosening a threshold: each mutation names the rule it violates, so a newly passing mutation tells you which rule you have effectively removed.

```bash
python -m pytest test_patterns.py -k "violations or controls" -q
```

For real-data effect, run the backtest (see [Testing and Contributing](04-Testing-and-Contributing.md)): it replays the active profile and the other one on the same year of prices, and re-scores the signals under stop and target variants. Any constant can be overridden for one replay without a code change: `gh workflow run backtest.yml -f overrides="CUP_TRIGGER=rim_b WW_TIME_SYM_TOL=0.45"` (locally `--set KEY=VALUE`). Change one constant, re-run, and only then change the default.
