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

Year-long walk-forward replay, 250 sessions to 2026-09-04, horizon 60 bars, next-open fills, intraday stops (`backtest` workflow runs 33968691768, 33973275310 and 33985398488). Read with the usual caveats: today's constituents only, one year, one regime. The ten-year replay of the tuned profile on the index as it was each year, +0.23 R per trade with drawdowns of up to 41 R inside a year, is in the out-of-sample section below.

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

### Out-of-sample check and the rule for changing a constant (2026-09-08)

Every calibration above was judged on the year the candidate values were chosen on. The ablation that produced the tuned profile ran on 63 sessions in which the spec profile fired 4 times (run 33968787516), and the profile and its later thresholds were then confirmed on the 250 sessions that contain those 63. Nothing was scored on data the choice had not seen. The two-year replay below holds out the year before 2025-09-09, which no decision used: 500 sessions to 2026-09-04, each scan seeing 500 bars like the nightly, horizon 60, `gh workflow run backtest.yml -f profile=tuned -f period=5y -f days=500 -f bars=500 -f split=2025-09-09 -f horizon=60` (run 34186512341, 97 minutes, which replays spec alongside tuned; the legacy rows come from a local replay of the same window on 2026-09-07 that matched the run within a signal and a cent of R on every tuned and spec row).

| Profile | Window | Signals | Hit rate | Mean R | 95 % CI, month blocks | Max drawdown |
|---|---|---|---|---|---|---|
| tuned | before 2025-09-09, unseen | 167 | 36 % | +0.30 | [−0.11, +0.58] | −17 R |
| tuned | from 2025-09-09, the tuning year | 159 | 45 % | +0.28 | [+0.02, +0.51] | −10 R |
| spec | unseen | 30 | 52 % | +0.53 | [+0.11, +0.93] | −2 R |
| spec | tuning year | 22 | 54 % | +0.24 | [−0.12, +0.60] | −4 R |
| legacy (local replay) | unseen | 304 | 37 % | +0.34 | [+0.01, +0.62] | −27 R |
| legacy (local replay) | tuning year | 359 | 31 % | +0.09 | [−0.12, +0.33] | −26 R |

Per pattern under tuned: inverse H&S +0.35 R on 132 signals in the unseen year and +0.32 on 112 in the tuning year; cup +0.23 on 21 and +0.16 on 22, with a hit rate near 25 % in both; Wolfe −0.16 on 14 and +0.19 on 25. The tuned expectancy held out of sample and legacy's did not, which is the real argument for the 2026-09-05 switch; Wolfe did not hold (#102). The quality score gates but does not rank: its buckets ran +0.29, +0.25, +0.39 and −0.08 R from 60-69 to 90-100 over both years, and a model fitted on one year gives it no weight on the other (#82, #97). It stays the minimum-60 gate.

Read all of it with four caveats. Both years were mostly bull markets (70 % and 95 % of sessions in the bull regime). The universe is today's constituents. Signals cluster in time (33 in June 2025, 2 in March 2026), which is why the intervals resample months rather than trades. And the feature findings in the issues below came from one exploratory pass over ten features, so some stable-looking splits are chance.

**The rule.** A candidate value is chosen on one window and confirmed on another it never saw, with `--split` on the same replay. It becomes the default only if the sign of its effect on mean R agrees in both windows and the pooled month-block interval of the adopted variant's mean R excludes zero; a slice of fewer than about 30 traded signals decides nothing. The windows and run IDs that judged each adopted value are kept in the ledger below, and a value that fails the unseen window is reported as such, not quietly kept.

| Adopted value | Chosen on | Confirmed on | Unseen window |
|---|---|---|---|
| tuned profile, four relaxations | 63 sessions to 2026-09-04, run 33968787516 | 250 sessions to 2026-09-04, run 33973275310 | held: +0.30 R on the unseen year (run 34186512341); +0.23 R over 2016-2026 on the point-in-time index, positive in 10 of 11 years (the eleven runs below) |
| `WW_TIME_SYM_TOL` 0.45 | 250 sessions to 2026-09-04, run 33985398488 | none | failed on 12 unseen-year rows, then held over ten years: Wolfe +0.45 R on 228 signals, positive in 8 of 11 (#102); the 0.30 alternative has not been replayed over the same years |
| `MIN_REWARD_RISK` 1.0, `MAX_WAIT_BARS` 60 | 250 sessions to 2026-09-04, runs 34023518929 to 34023527178 | none on their own | untested alone; the profile that includes them held |
| `CUP_TRIGGER` handle_high, kept | 250 sessions, run 33985391832 against 33973275310 | none | untested |
| `WATCH_PROXIMITY` 5 % | the 2026-09-04 report, 10 of 17 rows lost in a day | none | a reporting choice, not a replay question |
| `MAX_LISTED_DAYS` 6, Wolfe 5 | the eleven yearly point-in-time runs 34323013559 to 34323039560, pooled: the same signals bought on day N against day 1 (late entry, below) | the same runs year by year: days 4-9 worse in 10 of 11 years, day 2 no different in any | adopted 2026-09-15 (#115); it changes no first-seen row the replays score, only which repeat listings the report shows |
| `WATCH_ONLY_PATTERNS` cup | the eleven yearly point-in-time runs (the table below): cups +0.03 R on 305 signals, 18 % hit, against +0.23 and +0.43 for the other two | the same runs year by year: cups were the weakest pattern in most years and never the best | adopted 2026-09-17 (#109) after two of the first three live losses were cups; applied at report time, so the replay figures, which include cups, are unchanged and the pattern stays measured |
| Double Bottom in `ACTIVE_PATTERNS` | the eleven yearly point-in-time runs 35260820348 to 35260846765 (tuned, all four patterns): 215 signals, +0.13 R, interval [+0.00, +0.26] | the same runs year by year, 7 of 11 positive; the set with the reward floor off (35260849601 to 35260875301): 752 signals at +0.10 R, interval [+0.01, +0.18], 9 of 11 years | adopted 2026-09-17 (#126), the thinnest edge adopted so far; review after 30 live signals |

### Ten years on the index as it was (2026-09-08)

Eleven runs, one calendar year each from 2016 to 2026 (to 2026-09-04), tuned profile, point-in-time membership (`asof=true`, see [Testing and Contributing](04-Testing-and-Contributing.md)), `bars=500`, `horizon=60`, `grid=false`: runs 34246882614, 34246967266, 34247049007, 34247134013, 34247217621, 34247300839, 34247387000, 34247471926, 34247553575, 34247636362 and 34247722648 in that order. Coverage is the share of that year's members with Yahoo history; the rest, delisted or renamed since, is the survivorship bias that remains.

| Year | Coverage | Signals | Hit rate | Mean R | 95 % CI, month blocks | Max drawdown |
|---|---|---|---|---|---|---|
| 2016 | 77 % | 111 | 45 % | +0.39 | [−0.11, +0.76] | −17 R |
| 2017 | 80 % | 136 | 40 % | +0.60 | [+0.16, +1.07] | −15 R |
| 2018 | 80 % | 153 | 26 % | −0.14 | [−0.52, +0.15] | −41 R |
| 2019 | 84 % | 240 | 32 % | +0.26 | [−0.22, +0.73] | −37 R |
| 2020 | 84 % | 124 | 32 % | +0.15 | [−0.17, +0.56] | −17 R |
| 2021 | 88 % | 157 | 35 % | +0.16 | [−0.09, +0.45] | −19 R |
| 2022 | 91 % | 176 | 29 % | +0.03 | [−0.50, +0.43] | −38 R |
| 2023 | 94 % | 169 | 43 % | +0.40 | [−0.24, +0.92] | −36 R |
| 2024 | 95 % | 133 | 35 % | +0.16 | [−0.25, +0.58] | −19 R |
| 2025 | 97 % | 173 | 38 % | +0.27 | [−0.14, +0.60] | −15 R |
| 2026 to 09-04 | 97 % | 118 | 44 % | +0.24 | [+0.01, +0.45] | −10 R |

Pooled, weighting each year by its traded signals: 1629 traded signals, +0.23 R, 36 % hit rate, positive in 10 of 11 years. Per pattern: inverse H&S +0.23 R on 1096 signals, positive in 9 years and negative in the two bear years 2018 and 2022; Bullish Wolfe Wave +0.45 R on 228, positive in 8 years and the best detector in 2018, 2019 and 2022; Cup & Handle +0.03 R on 305 with an 18 % hit rate, positive in 5 years, 2017 alone supplying the profit (#109). By SPY regime at the scan day: bull +0.16 R on 1190, neutral +0.21 on 213, bear +0.59 on 226 (positive in 5 of the 6 years with bear sessions). VIX above 25 ran +0.50 on 142 in 8 of 8 years; a stock whose SMA50 sat more than 5 % under its SMA200 ran +0.35 on 499 against +0.15 to +0.20 elsewhere (#99, #101). Score buckets from 60-69 to 90-100 ran +0.27, +0.22, +0.22 and +0.19: the hit rate rises with the score and the mean R does not, so the score gates and does not rank (#82). Drawdowns inside the year reached 36 to 41 R in 2018, 2019, 2022 and 2023 against an expected yearly gain near 35 R (#108).

What the ten years overturned from the two-year window, each a lesson in what one exploratory pass over two bull years produces: fresh breakouts are not better (age 0 at first report +0.10 R against +0.42 for age 4 to 8; #98 closed), reward:risk above 4 is not bad (+0.45 R with a 16 % hit rate; #100 closed), a VIX below 15 is not bad (+0.21 R pooled, and 2017 at a VIX near 10 was the best year; #101 rewritten), the SMA band U-shape is one-sided (#99 rewritten), and the Wolfe verdict on 12 out-of-sample trades was noise (#102 closed as held). What survived: the tuned profile's expectancy, the score's role as a gate, and the reversal-after-washout context.

**Open questions:** #99 and #101 (the deep-down-trend and bear-regime contexts, information first, no rule), #108 (the drawdowns), #109 (cups), #113 (the Bollinger stretch gate), and #97 (a per-signal probability model, whose first revisit condition the ten years now meet).

### A second review, tested (2026-09-08)

A second external review proposed a converging-wedge check for Wolfe (already the code: the 2-4 line must fall faster than 1-3 and the target is their intersection), a convex quadratic cup fit (already the code, with the U-versus-V test the review lacks), close-based confirmation (already the code), ATR-buffered stops (already the code, at 0.25 ATR), a volume z-score gate, a reward:risk floor of 2.0, a handle volume decay rule for cups, a confirmation candle, and a macro filter inhibiting alerts below the SPY 200-day average or above VIX 25. The testable items were replayed over the same eleven years with the features recorded on every row (runs 34255129970 to 34255999955; the second set with `CUP_MIN_ROUNDNESS=0.8`; the stop variant on the two-year grid, run 34256064869):

| Proposal | Ten-year result | Verdict |
|---|---|---|
| Volume z-score of 1.5 as a gate | monotone: at or below 0 +0.16 R on 795 signals, 0-1.5 +0.25 on 520, 1.5-3 +0.31 on 171, above 3 +0.34 on 144; the gate keeps 315 of 1630 signals at +0.32 and drops 1315 at +0.20 | a feature, not a gate |
| Confirmation candle: close above the prior bar's high | with it +0.19 R on 1405; without it +0.42 R on 225, positive in 9 of 11 years | reversed |
| Strong close within the breakout bar's range | at or below 50 % +0.24, 50-80 % +0.24, above 80 % +0.21 | no effect |
| Handle volume must decay (cups) | handle over cup volume at or below 0.7 +0.06 R, 0.7-1.0 +0.01, above 1.0 +0.06; falling slope +0.05, rising +0.01 | no effect |
| Cup R² of 0.80 instead of 0.70 | cups 127 traded at −0.10 R against 307 at +0.03; the 180 removed ran +0.12 | worse |
| Larger swings (the ATR-pivot idea), read as pattern depth in ATR | at or below 3 ATR +0.26 R on 949 with a 42 % hit rate, above 10 ATR +0.26 on 116 with a 15 % hit rate | shallow patterns hit more often; no gate |
| Stop 1.2 ATR under the pivot | two-year grid on 327 signals: the reported stop (0.25 ATR under the low) +0.29 R at a 41 % hit rate; 1.25 ATR under it +0.20 R at 49 %, and the same order in both windows (+0.30 against +0.21 unseen, +0.27 against +0.19 tuning year); the risk unit grows faster than the stop-outs fall | worse per trade |
| Reward:risk floor of 2.0 | rows at or below 1.5 ran +0.20 R with a 54 % hit rate over ten years (#100) | rejected |
| Inhibit alerts in a SPY bear regime or above VIX 25 | bear regime +0.59 R on 226, VIX above 25 +0.50 R in 8 of 8 years (#101) | contradicted |

### Per-ticker fear and greed, tested (2026-09-08)

A trader's suggestion: read a per-ticker fear-and-greed indicator, as the TradingView community scripts do, to tell whether a stock is being bought or sold too hard. The replay's version, `fear_greed` in `tools/backtest.py`, is the equal-weight 0-100 composite of RSI 14, the MACD histogram's percentile within the trailing year and Bollinger %B that those scripts share, read at the scan day and at the pattern's last low, and replayed over the same eleven years (runs 34267945406 to 34268343900). The direction the trader expected is what the data shows, in both readings:

| Reading | Zone | N traded | Hit rate | Mean R | Positive years |
|---|---|---|---|---|---|
| at the scan day | fear, 20-40 | 73 | 23 % | +0.61 | 6 of 11 |
| at the scan day | neutral, 40-60 | 174 | 40 % | +0.45 | 10 of 11 |
| at the scan day | greed, 60-80 | 957 | 33 % | +0.20 | 10 of 11 |
| at the scan day | extreme greed, above 80 | 427 | 42 % | +0.12 | 8 of 11 |
| at the pattern's last low | extreme fear, below 20 | 112 | 35 % | +0.30 | 7 of 11 |
| at the pattern's last low | fear | 352 | 34 % | +0.28 | 8 of 11 |
| at the pattern's last low | neutral | 616 | 39 % | +0.24 | 10 of 11 |
| at the pattern's last low | greed | 534 | 33 % | +0.15 | 8 of 11 |

A confirmed breakout is almost never fearful by construction (one row below 20 in ten years), so at the scan day the scale runs from fear to extreme greed, and the greedier the stock at its breakout, the lower the mean R; the higher hit rate of the greediest bucket does not compensate, because its wins are smaller. Bases that formed in fear paid about twice what bases formed in greed did. Of the components, the stretch measures carry the effect and momentum does not: RSI 30-50 at the breakout ran +0.55 R on 230 signals against +0.18 for 50-70 and +0.12 above 70, the lower bucket ahead in 8 of 11 years; Bollinger %B in the lower half ran +0.53 on 185, the upper half +0.26 on 991 and a close above the upper band +0.04 on 453, the upper half ahead of the above-band bucket in 10 of 11 years (the exception, 2017, a tie at +0.44 against +0.45); the MACD percentile ran +0.18 to +0.26 across its buckets with the strongest momentum slightly best.

The one candidate rule this produces is the Bollinger stretch: a breakout bar that closes above its upper band. Leaving those 453 signals out would keep 1179 signals at +0.30 R against 1632 at +0.22, at a cost of 16 R of the ten-year total of 367. Under the protocol it remains a hypothesis: the gate has to be replayed as a rule on its own, so that its effect on the drawdown and per pattern is measured (#113). The reading itself is on every report row as the `F&G` column, one value per symbol at the last close, information only.

### Late entry, tested (2026-09-09)

The owner's question on HAL, listed as a confirmed inverse head and shoulders in every report from 2026-09-04: the rules keep an H&S or Wolfe breakout listed for up to 8 bars and re-quote the entry at each close, and #98 settled that the age at *first* report is no reason to cut that window. But every replay fills a signal once, at the open after its first report, and nothing had measured what a reader gets who buys a row on its second, third or eighth day on the list, which is what the report invites by showing the row again. `tools/backtest.py` now records every later CONFIRMED listing of an already-seen signal (`listed_day` = sessions since the first report) and fills it at the next open under the same rules, and its **Late entry** table pairs each later listing with the same signal's first report (#115; the eleven yearly point-in-time runs 34323013559 to 34323039560, tuned, `bars=500`, `horizon=60`: 1692 first-seen signals, 4915 later listings).

| Day on the list | Listed | Traded | Hit rate | Mean R | 95 % CI | Pairs | Same signals on day 1 | On day N | Difference | 95 % CI |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1692 | 1632 | 35 % | +0.22 | [+0.09, +0.36] | | | | | |
| 2 | 1140 | 1111 | 35 % | +0.28 | [+0.13, +0.45] | 1090 | +0.28 | +0.27 | −0.01 | [−0.07, +0.07] |
| 3 | 995 | 952 | 35 % | +0.22 | [+0.08, +0.36] | 928 | +0.31 | +0.22 | −0.09 | [−0.15, −0.02] |
| 4-5 | 1541 | 1479 | 36 % | +0.19 | [+0.05, +0.32] | 1440 | +0.31 | +0.18 | −0.12 | [−0.18, −0.06] |
| 6-9 | 1230 | 1169 | 36 % | +0.14 | [−0.04, +0.32] | 1135 | +0.26 | +0.14 | −0.12 | [−0.22, −0.01] |

Day by day the later entries run +0.28, +0.22, +0.18, +0.20, +0.27, +0.12, +0.05 and −0.00 R from day 2 to day 9, the paired difference −0.01, −0.09, −0.12, −0.12, −0.05, −0.14, −0.16 and −0.19 (the day-9 interval [−0.31, −0.06]). Per year, days 2-3 were worse than day 1 on the same signals in 5 of 11 years, days 4-9 in 10 of 11 (2024 the exception, +0.06). The price paid is not the reason: the quoted entry drifts only 0.3 % (day 2) to 1.2 % (day 9) above the first report's. What is gone is the move of the first sessions, which is why the signals still listed on day N had done better on day 1 (+0.26 to +0.32 R) than the whole population (+0.22): a row that survives its first days is the better population, and buying it late gives part of that back. Per pattern: an inverse H&S on its second day is as good as new (+0.01 on 748 pairs), costs 0.14 R on days 4-5 (interval [−0.21, −0.08]) and is still +0.21 R unconditionally there; a Wolfe on days 6-9 lost money, −0.45 R on 44 with a 13 % hit rate (paired −0.38, [−0.73, −0.03]); cups, near zero at any age, lose 0.07 to 0.13 R from day 2 on. Three cups re-detected weeks later with the same stop (a new handle over the same low, nine listings) are left out of the buckets.

What this settles: a row on its second day is as good as a fresh one; from the third day the same signal pays about 0.1 R less than it did on day 1, in ten of eleven years, and stays positive on average through day 6 only because survivors are a better population; from day 7 the replay shows no edge (+0.12, +0.05, −0.00, intervals spanning zero), for a Wolfe from day 6. No constant changes: the age window is a first-report question (#98). The day on the list belongs in the report and on the site next to the age, with the plain entry line reserved for days 1-2, a late note from day 3 and no entry line from day 7 (Wolfe from day 6); the rule decision was the owner's and is recorded below.

**Adopted 2026-09-15 as `MAX_LISTED_DAYS`** (6 sessions, a Wolfe 5): the scanner carries each structure's `first_listed` session across nights (keyed on ticker, pattern and stop, like the replay), counts `listed_day` from the bars, and retires a confirmed row past the limit, once, as `RETIRED` in the close-out list, then remembers it in the file's `retired` list while the detector still produces the structure so it neither returns as new nor sits on the watchlist. The breakout age limit still applies on top, which is why the limit binds only for an inverse H&S first seen at age 2 or younger and a Wolfe at age 3 or younger; a cup never reaches it. The `legacy` profile has no limit. The evidence is the table above: the rule changes no first-seen row the replays score, so the yearly figures stand, and the repeat listings it removes are exactly those the pooled and the year-by-year comparison found worthless.

### The double bottom, tested (2026-09-17)

The first candidate pattern since the cup went watch-only: two consecutive swing lows within 3 % of each other, a rally of at least 10 % between them, a close above that rally's peak as the trigger, the stop under the second low and one pattern height as the target (the [catalog](02-Pattern-Catalog.md) has the rules). Replayed over the eleven point-in-time years with all four patterns in the same runs, so the other three reproduce their known figures and the inverse H&S rows are there for the overlap count (#126; runs 35260820348 to 35260846765 under the tuned rules, 35260849601 to 35260875301 with `MIN_REWARD_RISK=None`).

| Rule set | Slice | Signals | Hit rate | Mean R | Median R | 95 % CI, month blocks | Years positive |
|---|---|---|---|---|---|---|---|
| tuned | double bottom | 215 | 58 % | +0.13 | +0.13 | [+0.00, +0.26] | 7 of 11 |
| tuned | double bottom, no H&S on the same ticker within 15 days | 208 | 58 % | +0.13 | +0.12 | [+0.00, +0.25] | 8 of 11 |
| tuned | inverse H&S in the same runs | 1095 | 39 % | +0.22 | −0.59 | [+0.07, +0.37] | |
| reward floor off | double bottom, all forms | 752 | 59 % | +0.10 | +0.27 | [+0.01, +0.18] | 9 of 11 |
| reward floor off | second low higher than the first | 424 | 60 % | +0.13 | +0.30 | [+0.04, +0.22] | |
| reward floor off | second low equal or lower | 328 | 58 % | +0.05 | +0.18 | [−0.06, +0.17] | |

Per year under the tuned rules (traded / hit / mean R): 2016 21 / 67 % / +0.31, 2017 12 / 78 % / +0.51, 2018 16 / 36 % / −0.25, 2019 14 / 50 % / −0.05, 2020 20 / 80 % / +0.36, 2021 12 / 88 % / +0.39, 2022 28 / 48 % / −0.04, 2023 28 / 40 % / −0.01, 2024 14 / 62 % / +0.24, 2025 28 / 55 % / +0.15, 2026 to 09-04 22 / 54 % / +0.10. Only 7 of the 215 signals sit within 15 calendar days of an inverse H&S signal on the same ticker: the two patterns find different bases.

What this settles: a real but thin edge. The double bottom wins often and small, because the target is one pattern height and the stop sits just under the second low, so per signal it earns about half of what the inverse H&S does and a third of the Wolfe; its bad years are the bear years, as for the H&S. With equal lows the reward is one height against a slightly larger risk, so the tuned profile's reward:risk floor keeps only the form with a higher second low, which is also the better half without the floor. Against the gate it passes narrowly: positive, incremental, positive in most years, the interval clearing zero in the larger set and touching it in the tuned set, where 215 signals is what makes it wide. **Adopted 2026-09-17** into `ACTIVE_PATTERNS` under the tuned rules, about 20 signals a year, with a review after the first 30 live signals. The random-walk false-positive rate of the scan rises from about 2 % of series to 6 % with the fourth detector (its 10 % rise rule is what holds it there; without it, 43 of 200 random walks show a W).

### The 1H Wolfe specification, replayed on its own terms (2026-09-18)

An external specification of a 1H Bullish Wolfe Wave strategy was put next to the scanner's Wolfe detector. It shares the geometry (five alternating swings, lower lows, point 4 inside the 1-2 range, converging lines with 2-4 the steeper, point 5 under the 1-3 line, entry on the first close back above it) and differs on everything around it: hourly bars, swing points three bars deep instead of five, a fixed 25-session window, a stop half an ATR under point 5 instead of a quarter, the point-4 high as the only target instead of the EPA, a binary exit with a time stop after 12 sessions instead of the listing rules, and no reward:risk floor. None of the scanner's replay figures transfer to that trade, so `tools/backtest_wolfe_spec.py` (the `backtest-wolfe-spec` workflow) replays the specification as written, on any yfinance interval, with its own constants block and its own tests (`test_backtest_wolfe_spec.py`).

**What it logs.** The specification's schema per trade (`symbol`, `trigger_time`, `bars_P1_to_P5`, the five prices, `entry_price`, `stop_loss`, `tp1_target`, `projected_RR`, `exit_reason`, `bars_held`, `realized_R`) plus the seven factors of the review, each measured at the entry bar: the trigger bar's volume over the 20-bar average, RSI 14 at point 5 above RSI 14 at point 3 (`rsi_divergence`), the trigger bar's body over its range, the projected reward:risk against the point-4 high (logged and bucketed, never filtered, as the specification asks), the close against a higher-timeframe EMA 50 (`htf_trend_4h`), an earlier swing low within 0.5 ATR of point 5 (`nearby_support`), and SPY against its daily SMA 50 with the VIX (`market_regime_spy`, `vix`). The report gives the funnel (structures with the geometry, those whose point 5 swept the line, those reclaimed in time, those with room for a trade, those skipped because a position was open, trades), the headline win rate (TP1 hits over closed trades; time exits count as closed, open trades do not), the hit rate against stops only, mean and total R, then the outcome per bucket of every factor and per year.

**Where the specification is silent, the replay reads it conservatively** and the report states the rules it ran: the entry is never anticipated (the reclaim close counts only from the bar on which point 5 is a confirmed swing low, three bars after it; a reclaim that came earlier is kept as `literal_reclaim_lag`); the reclaim must come within 25 bars of point 5 (the scanner's own figure) and the structure must fit in the window up to the entry bar; a lower low before the reclaim makes that low the structure's point 5; a bar touching both the stop and the target is a stop, gaps fill at the open; one position per symbol at a time; swing points are strict (a tie is not a swing point, which the specification's prose says and its code sketch, a rolling-max equality, does not); the 4H trend is an EMA of 200 hourly bars (EMA 50 of 4H bars) rather than resampled bars, and a weekly analogue (EMA 250) on daily bars; the SPY regime and the VIX are read at the last completed session before an intraday entry. Yahoo serves hourly bars for the last 730 days only, so a three-year request on `1h` is clamped and the report says so; the same rules on daily bars cover any span.

```bash
gh workflow run backtest-wolfe-spec.yml                                   # 1h and 1d, three years (1h: the last 730 days)
gh workflow run backtest-wolfe-spec.yml -f intervals=1h -f tickers=AAPL,MSFT,NVDA
gh workflow run backtest-wolfe-spec.yml -f overrides="--stop-atr 0.25 --max-hold-bars 40"   # a variant, one flag at a time
```

The noise floor of these rules is higher than the scanner's: on 40 geometric random walks of 1,500 hourly bars (`test_backtest_wolfe_spec.py::test_random_walks_rarely_trigger`, which prints the figure) they take 2.3 trades per 1,000 bars, against the scanner's Wolfe detector firing on about 1 % of 500-bar daily series; three-bar swings make many more structures, and the specification has no rhythm, sweet-zone or quality-score gate. Read the results with the same caveats as every replay here: today's constituents only (survivorship bias), one regime per window, and the factor tables are one exploratory pass, so a factor earns a rule only if its buckets separate outcomes on both halves of a split, and a bucket of fewer than about 30 trades decides nothing. The results of the first runs are recorded below once they exist.

**The first runs (2026-09-18, run 35362213916).** Both intervals over the S&P 500 as it is today, hourly bars clamped to the last 729 days (2024-09-19 on) and daily bars over the full three years (2023-09-18 on), 503 symbols each.

| Interval | Window | Structures | Traded | TP1 | SL | Time exit | Win rate | Mean R | Total R |
|---|---|---|---|---|---|---|---|---|---|
| 1h | 2024-09-19 to 2026-09-18 | 6225 | 3443 | 1956 | 1450 | 24 | 57.0 % | +0.03 | +104.20 |
| 1d | 2023-09-18 to 2026-09-18 | 1051 | 428 | 229 | 125 | 66 | 54.5 % | +0.09 | +38.83 |

Win rate is TP1 over closed trades (a time exit is closed; the 13 hourly and 8 daily trades still open when the data ends are not). The funnel on hourly bars: 6225 structures passed the geometry, 4788 swept the 1-3 line, 3687 reclaimed it in time (1002 made a lower low first, 99 never closed back above), 3465 left room for a trade and 22 fell to a position already open.

**What the win rate hides.** A majority of entries sit closer to the point-4 high than to the stop, so the strategy wins often and wins less than it risks. Hourly, 2100 of 3443 trades had a projected reward:risk below 1.0; they won 67.8 % of the time for +0.02 R each. The buckets run the other way on every step:

| Projected R:R | 1h trades | 1h win rate | 1h mean R | 1d trades | 1d win rate | 1d mean R |
|---|---|---|---|---|---|---|
| < 1.0 R | 2100 | 67.8 % | +0.02 | 277 | 64.6 % | +0.02 |
| 1.0-1.5 R | 661 | 46.0 % | +0.03 | 78 | 37.7 % | +0.14 |
| 1.5-2.0 R | 324 | 39.8 % | +0.04 | 39 | 43.2 % | +0.48 |
| > 2.0 R | 358 | 29.9 % | +0.08 | 34 | 21.9 % | +0.14 |

This answers the specification's own question, the one it asked the log to settle: strong impulse candles with a low initial R:R do win more often, and the higher win rate does not pay for the smaller reward. Expectancy is flat to slightly positive everywhere, which is what a near-zero-edge rule looks like once the target is placed inside the noise.

**None of the seven factors earns a rule.** Under this repository's protocol a factor has to separate outcomes on both halves of a split; here two independent windows are available, and the two strongest-looking factors reverse between them:

| Factor | 1h | 1d |
|---|---|---|
| Market regime, SPY above its SMA 50 | 56.5 % / +0.02 against 58.9 % / +0.07 below | 60.5 % / +0.15 against 41.1 % / −0.03 below |
| VIX at or below 15 | 46.6 % / −0.22, and above 25: 65.3 % / +0.24 | 63.6 % / +0.20, and above 25: 34.6 % / −0.10 |
| RSI divergence (P5 above P3) | 57.1 % / +0.00 against 57.0 % / +0.04 without | 60.2 % / +0.04 against 53.9 % / +0.12 without |
| Higher-timeframe EMA 50, close above | 60.9 % / +0.06 against 54.6 % / +0.02 below | 50.9 % / −0.04 against 53.4 % / +0.12 below |
| Nearby support within 0.5 ATR | 56.4 % / +0.00 against 57.8 % / +0.06 without | 54.1 % / +0.06 against 55.0 % / +0.14 without |

The regime and volatility readings flip sign between the two windows, so neither is a filter. RSI divergence, the factor the review ranked second, is inert on the hourly set: 57.1 % against 57.0 %. Higher-timeframe trend flips too. Nearby support is mildly negative on both, and volume is the only one pointing the same way twice, weakly (hourly, 1.3-2.0x: 62.2 % and +0.15 R on 413 trades; daily, 1.0-1.3x: 65.6 % and +0.26 R on 97), which is the same "a feature, not a gate" verdict the volume z-score got in the second review above. Per year the hourly set ran −0.02, +0.06 and +0.02 R over 2024, 2025 and 2026; the daily set +0.08, +0.23, −0.10 and +0.18 over 2023 to 2026.

**The selectivity question.** The hourly replay took 3443 trades over about 1.75 million bars, 1.97 per 1,000 bars. The offline random-walk check in `test_backtest_wolfe_spec.py` takes 2.27 per 1,000 bars on synthetic geometric noise. The two are not measured on the same generating process, so this is not proof, but the rule fires on real prices no more often than on a random walk, which is what the flat expectancy above would predict. The scanner's own Wolfe detector, with five-bar pivots, the sweet zone, the rhythm rule and the quality score, fires on about 1 % of 500-bar random series.

**Read as an answer to "is this our approach?": no, and the replay does not argue for adopting it.** Three years of the index at a flat +0.03 to +0.09 R per trade, with every proposed confirmation factor either inert or reversing between windows, does not clear the gate any rule change in this repository has to pass. What the harness is good for now is the same question asked one rule at a time: `--stop-atr`, `--max-hold-bars` and `--max-reclaim-bars` each change one thing, and the point-4 target against the scanner's EPA is the obvious next comparison.

### Market context (2026-09-08)

The report header and every backtest row carry the SPY regime (close and SMA50 against the SMA200), the VIX and the breadth of the universe, and the backtest summaries add a per-regime slice with VIX and breadth among the feature buckets. Over the ten years on the point-in-time index (the section above), signals scanned in a SPY bear regime ran +0.59 R on 226 against +0.16 on 1190 in bull regimes, positive in five of the six years with bear sessions, and signals scanned at a VIX above 25 ran +0.50 R in eight of eight years; a VIX below 15, negative in the two-year window, ran +0.21 R pooled. Nothing gates on the context; #101 tracks how the report should present it.

**The nightly scan runs `--profile tuned`**, chosen on this evidence on 2026-09-05; the default in code stays `spec`. Change the flag in `.github/workflows/daily-scan.yml` to switch. The cup entry stays at the handle peak: a rim-B entry replayed at 19 cup signals and +0.17 R against 20 and +0.23 R. The grid also shows a close-based stop (exit on the first close at or below the stop) lifting tuned's mean R to +0.35 at a 52 % hit rate; the report's stop level is unchanged, that is an execution choice.

## CLI

| Flag | Default | Effect |
|---|---|---|
| `--tickers A,B,C` | full S&P 500 | scan only these symbols (upper-cased) |
| `--csv path` | pinned GitHub dataset | local constituents CSV; `Symbol` column or first column |
| `--period` | `2y` | yfinance period; `2y` gives about 500 daily bars, enough for SMA200 plus a 250-bar cup |
| `--min-score` | 60 | overrides `MIN_SCORE` for the run and is echoed in `meta.min_score` |
| `--max-age` | 3 | overrides `MAX_BREAKOUT_AGE`; the effective per-pattern limits are in `meta.max_breakout_age_by_pattern` |
| `--profile` | `spec` | rule profile, `spec`, `tuned` or `legacy`; echoed in `meta.profile` |
| (backtest) `--patterns` | the active set | comma-separated patterns to replay, `cup`, `ihs`, `wolfe`, `db` or the full names; the way a candidate such as the double bottom is replayed before it joins the scan |
| `--out-dir` | `output` | destination for `signals.json` and `report.md` |
| `-v` | off | DEBUG logging, including per-symbol last-bar detail |

## Global gates

| Constant | Default | What it controls | Loosen → | Tighten → |
|---|---|---|---|---|
| `PIVOT_ORDER` | 5 | bars on each side needed to call a swing high/low | fewer bars: more (noisier) pivots, patterns visible sooner | fewer, cleaner pivots; H&S/Wolfe seen later; `BREAKOUT_AGE_LAG` follows it automatically |
| `ATR_LEN` | 14 | ATR window used for stops and the head/overshoot tests | | |
| `MIN_SCORE` | 60 | minimum quality score reported; a gate, not a ranking (score buckets do not order outcomes in replay, #82) | more marginal setups | only the cleanest geometry |
| `MAX_BREAKOUT_AGE` | 3 | max bars since the confirming close (Cup); +`PIVOT_ORDER` for H&S and Wolfe | older breakouts reported | only fresh breakouts |
| `MAX_LISTED_DAYS` | 6, Wolfe 5 | sessions a confirmed row stays listed from its first report (`first_listed`, carried across nights); past it the row is retired (`RETIRED`) and remembered while the scan still produces it (#115); `legacy`: no limit | rows shown longer, inviting entries the replay found worthless | rows retired sooner; 1 would drop day 2, which was as good as day 1 |
| `WATCH_ONLY_PATTERNS` | `("Cup & Handle",)` | patterns reported for information only: a breakout is listed on the watchlist with its age and a note, never as a confirmed signal (`demote_watch_only`, at report time, so the replay still measures them); `legacy`: none (#109) | more patterns listed but never traded | an empty tuple restores cup signals |
| `BREAKOUT_AGE_LAG` | Cup 0, H&S 5, Wolfe 5 | extra age tolerated because the last pivot lags | | |
| `MAX_RUNAWAY` | 0.05 | close more than this above the trigger = chasing, dropped | | |
| `WATCH_PROXIMITY` | 0.05 | setups whose close is within this of the trigger → watchlist (was 0.03 until 2026-09-05; at 3 % a normal down day cleared most of the list) | longer watchlist | shorter watchlist |
| `LAST_BAR_MIN_FRACTION` | 0.5 | share of symbols that must have a complete bar for it to be `meta.last_bar` | | |
| `FILL_CLOSE_MIN_AGE` | 1 h | how old the last trade must be to count as the closing print | | |
| `CONSTITUENTS_COMMIT` | 2026-08-20 hash | pinned upstream commit of the constituent CSV | | |
| `MARKET_INDEX` / `MARKET_VOL` | `SPY` / `^VIX` | the symbols behind `meta.market` (regime, VIX); breadth comes from the universe itself | informational: no rule reads the context | |

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

## Double Bottom

Active since 2026-09-17 (the section "The double bottom, tested" above); replayed alone with `--patterns db`. Its constants have no `legacy` value.

| Constant | Default | Meaning | Tuning note |
|---|---|---|---|
| `DB_MIN_LEN` / `DB_MAX_LEN` | 15 / 150 | bars from the first low to the second | |
| `DB_LOW_TOL` | 0.03 | the two lows within this share of the lower one, either way round | |
| `DB_MIN_RISE` | 0.10 | the peak between the lows at least this share above the higher low (Bulkowski) | the rule that keeps noise out: 43 of 200 random walks fire without it, 5 with it |
| `DB_MIN_DEPTH_ATR` | 2.0 | the peak also at least this many ATR above the higher low | rarely binding once the 10 % rule holds |
| `DB_TIME_SYM` | 3.0 | the peak's position between the lows, `(P − L1) / (L2 − P)` within `[1/3, 3]` | |
| `DB_PRIOR_DECLINE_OF_HEIGHT` / `DB_TREND_SMA_OR` | 1.0 / `True` | a decline of one height into the first low, or SMA50 < SMA200 | as for the H&S |
| `VOLUME_CONFIRM`, `MAX_RISK_PCT`, `BREAKOUT_AGE_LAG`, `MAX_LISTED_DAYS` | 1.3 (tuned none), 15, 5, 6 | as for the inverse H&S | |

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

For real-data effect, run the backtest (see [Testing and Contributing](04-Testing-and-Contributing.md)): it replays the active profile and the other one on the same prices, and re-scores the signals under stop and target variants. Any constant can be overridden for one replay without a code change: `gh workflow run backtest.yml -f overrides="CUP_TRIGGER=rim_b WW_TIME_SYM_TOL=0.45"` (locally `--set KEY=VALUE`). Change one constant, re-run, and only then change the default.

Judge a candidate on a window it was not chosen on. The backtest reports a 95 % interval of the mean R (resampling scan months, because signals cluster in time) and, with `-f split=YYYY-MM-DD`, the sessions before and from a date as separate windows: `gh workflow run backtest.yml -f period=5y -f days=500 -f bars=500 -f split=2025-09-09 -f horizon=60`. The rule a change must pass, the evidence so far and the ledger of adopted values are in the out-of-sample section above.
