# S&P 500 pattern scan — 2026-09-08 05:59

Scanned 502 of 503 symbols (daily bars, last bar 2026-09-04). Min quality score 60. Breakouts older than the per-pattern limit are dropped (bars: Cup & Handle 3, Inverse Head & Shoulders 8, Bullish Wolfe Wave 8; H&S and Wolfe get 5 extra bars because their last pivot is only visible 5 bars after it prints). Rows with reward:risk below 1.0 are dropped. Watchlist rows whose pattern completed more than 60 bars ago are dropped (a breakout is reported whenever it comes).
Data errors: 1
Market: SPY 8.5 % above its SMA200, SMA50 > SMA200 (bull); VIX 14.5; 67% of 501 symbols above their SMA200.

## Confirmed breakouts (actionable): 1

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Vol× | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HAL | Inverse Head & Shoulders | 37.07 | 37.68 | 32.64 | 11.95 | 42.21 | 1.16 | 86 | 5/8 | 0.9 | close above SMA200, SMA50 < SMA200, SMA200 rising/flat | LS 2026-07-02 @32.44, head 2026-07-30 @30.84, RS 2026-08-26 @32.88, neckline 36.03->35.91 (now 35.86) |

## Watchlist (pattern complete, waiting for a close above trigger): 7

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Vol× | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CBOE | Inverse Head & Shoulders | 313.77 | 329.46 | 269.98 | 13.95 | 394.16 | 1.84 | 78 | - | - | close above SMA200, SMA50 < SMA200, SMA200 rising/flat | LS 2026-06-02 @269.21, head 2026-06-29 @226.52, RS 2026-08-19 @272.60, neckline 305.34->310.20 (now 313.77) |
| FIS | Inverse Head & Shoulders | 43.12 | 44.89 | 39.59 | 8.2 | 49.65 | 1.85 | 78 | - | - | close below SMA200, SMA50 < SMA200, SMA200 falling | LS 2026-05-15 @40.86, head 2026-06-22 @37.42, RS 2026-07-23 @39.96, neckline 44.29->43.67 (now 43.12) |
| HAS | Cup & Handle | 95.99 | 98.28 | 91.41 | 4.77 | 118.7 | 4.96 | 75 | - | - | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-05-07 @97.30, bottom 2026-07-08 @74.63 (depth 23%), right rim 2026-08-14 @97.34, handle low 2026-08-20 @92.01 (depth 5.5%), trigger 95.99 |
| PH | Cup & Handle | 980.43 | 1009.98 | 921.31 | 6.03 | 1168.83 | 3.19 | 75 | - | - | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-04-17 @1024.62, bottom 2026-06-01 @813.37 (depth 21%), right rim 2026-06-25 @1001.77, handle low 2026-07-07 @927.47 (depth 7.4%), trigger 980.43 |
| XOM | Inverse Head & Shoulders | 160.98 | 167.9 | 147.16 | 8.59 | 182.45 | 1.55 | 75 | - | - | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | LS 2026-05-29 @143.78, head 2026-06-25 @134.08, RS 2026-08-04 @148.13, neckline 153.91->158.05 (now 160.98) |
| BKR | Cup & Handle | 65.27 | 67.67 | 60.48 | 7.34 | 78.63 | 2.79 | 74 | - | - | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-06-04 @66.00, bottom 2026-07-02 @52.08 (depth 21%), right rim 2026-08-17 @65.44, handle low 2026-08-27 @60.87 (depth 7.0%), trigger 65.27 |
| VRT | Inverse Head & Shoulders | 289.34 | 303.81 | 246.55 | 14.79 | 378.9 | 2.09 | 62 | - | - | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | LS 2026-07-17 @272.93, head 2026-07-29 @220.92, RS 2026-08-24 @249.97, neckline 313.61->300.30 (now 289.34) |

## Closed since the last report (2026-09-07 06:07): 0

_none_

_Max buy = the lower of trigger + 5% and the open at which the risk to the stop reaches 1.5x the planned entry-to-stop distance: if the open is above it the setup no longer qualifies. R:R = (target - entry) / (entry - stop) at the reported entry; it shrinks with every session the entry drifts above the trigger. Age = bars since the breakout close / the limit after which the row is dropped (0 = broke out on the last bar). Heuristic scan, not advice. Entry = trigger level, or the breakout close when it is above the trigger (closes more than 5% above the trigger are dropped as chasing). Stop = structural level minus 0.25 ATR, treated as an intraday touch in the backtest; exiting on a close at or below it scored higher in replay. Entry is the last close: a trade happens at the next open, so re-check that the open is still within 5% of the trigger and recompute risk from the fill. Verify on a chart before trading._