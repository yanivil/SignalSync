# S&P 500 pattern scan — 2026-09-09 06:00

Scanned 502 of 503 symbols (daily bars, last bar 2026-09-08). Min quality score 60. Breakouts older than the per-pattern limit are dropped (bars: Cup & Handle 3, Inverse Head & Shoulders 8, Bullish Wolfe Wave 8; H&S and Wolfe get 5 extra bars because their last pivot is only visible 5 bars after it prints). Rows with reward:risk below 1.0 are dropped. Watchlist rows whose pattern completed more than 60 bars ago are dropped (a breakout is reported whenever it comes).
Data errors: 1
Market: SPY 7.8 % above its SMA200, SMA50 > SMA200 (bull); VIX 15.7; 63% of 501 symbols above their SMA200.

## Confirmed breakouts (actionable): 1

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HAL | Inverse Head & Shoulders | 36.8 | 37.68 | 32.64 | 11.3 | 41.94 | 1.24 | 87 | 6/8 | 0.9 | 73.6 | close above SMA200, SMA50 < SMA200, SMA200 rising/flat | LS 2026-07-02 @32.44, head 2026-07-30 @30.84, RS 2026-08-26 @32.88, neckline 36.03->35.91 (now 35.86) |

## Watchlist (pattern complete, waiting for a close above trigger): 5

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PH | Cup & Handle | 980.43 | 1009.98 | 921.31 | 6.03 | 1168.83 | 3.19 | 75 | - | - | 20.4 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-04-17 @1024.62, bottom 2026-06-01 @813.37 (depth 21%), right rim 2026-06-25 @1001.77, handle low 2026-07-07 @927.47 (depth 7.4%), trigger 980.43 |
| XOM | Inverse Head & Shoulders | 161.09 | 168.06 | 147.16 | 8.65 | 182.56 | 1.54 | 75 | - | - | 38.5 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | LS 2026-05-29 @143.78, head 2026-06-25 @134.08, RS 2026-08-04 @148.13, neckline 153.91->158.05 (now 161.09) |
| BKR | Cup & Handle | 65.27 | 67.67 | 60.48 | 7.34 | 78.63 | 2.79 | 74 | - | - | 53.2 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-06-04 @66.00, bottom 2026-07-02 @52.08 (depth 21%), right rim 2026-08-17 @65.44, handle low 2026-08-27 @60.87 (depth 7.0%), trigger 65.27 |
| RTX | Cup & Handle | 199.75 | 205.49 | 188.25 | 5.75 | 233.5 | 2.94 | 71 | - | - | 15.3 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-04-09 @203.83, bottom 2026-05-15 @169.51 (depth 17%), right rim 2026-07-07 @203.26, handle low 2026-07-21 @189.39 (depth 6.8%), trigger 199.75 |
| HAS | Cup & Handle | 94.64 | 98.13 | 87.66 | 7.37 | 116.29 | 3.1 | 68 | - | - | 17.3 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-05-07 @97.30, bottom 2026-07-08 @74.63 (depth 23%), right rim 2026-07-29 @96.28, handle low 2026-08-04 @88.44 (depth 8.1%), trigger 94.64 |

## Closed since the last report (2026-09-08 05:59): 3

| Ticker | Pattern | Was | Outcome | Entry | Stop | Target | Detail |
|---|---|---|---|---|---|---|---|
| FIS | Inverse Head & Shoulders | WATCHLIST | FAILED | 43.12 | 39.59 | 49.65 | close 39.42 on 2026-09-08 at or below stop 39.59 |
| CBOE | Inverse Head & Shoulders | WATCHLIST | FADED | 313.77 | 269.98 | 394.16 | close 293.33 more than 5% below entry 313.77 |
| VRT | Inverse Head & Shoulders | WATCHLIST | DROPPED | 289.34 | 246.55 | 378.9 | pattern no longer qualifies |

_Max buy = the lower of trigger + 5% and the open at which the risk to the stop reaches 1.5x the planned entry-to-stop distance: if the open is above it the setup no longer qualifies. R:R = (target - entry) / (entry - stop) at the reported entry; it shrinks with every session the entry drifts above the trigger. F&G = the stock's own fear-and-greed reading at the last close, 0 to 100 (RSI 14, MACD-histogram percentile and Bollinger %B averaged): above 80 the stock is stretched and such breakouts replayed worst, below 20 it is washed out; information only, no rule uses it. Age = bars since the breakout close / the limit after which the row is dropped (0 = broke out on the last bar). Heuristic scan, not advice. Entry = trigger level, or the breakout close when it is above the trigger (closes more than 5% above the trigger are dropped as chasing). Stop = structural level minus 0.25 ATR, treated as an intraday touch in the backtest; exiting on a close at or below it scored higher in replay. Entry is the last close: a trade happens at the next open, so re-check that the open is still within 5% of the trigger and recompute risk from the fill. Verify on a chart before trading._