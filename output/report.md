# S&P 500 pattern scan — 2026-09-10 05:59

Scanned 503 of 503 symbols (daily bars, last bar 2026-09-09). Min quality score 60. Breakouts older than the per-pattern limit are dropped (bars: Cup & Handle 3, Inverse Head & Shoulders 8, Bullish Wolfe Wave 8; H&S and Wolfe get 5 extra bars because their last pivot is only visible 5 bars after it prints). Rows with reward:risk below 1.0 are dropped. Watchlist rows whose pattern completed more than 60 bars ago are dropped (a breakout is reported whenever it comes).
Market: SPY 7.2 % above its SMA200, SMA50 > SMA200 (bull); VIX 16.5; 60% of 501 symbols above their SMA200.

## Confirmed breakouts (actionable): 1

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HAL | Inverse Head & Shoulders | 37.13 | 37.68 | 32.64 | 12.09 | 42.27 | 1.15 | 86 | 7/8 | 0.9 | 73.3 | close above SMA200, SMA50 < SMA200, SMA200 rising/flat | LS 2026-07-02 @32.44, head 2026-07-30 @30.84, RS 2026-08-26 @32.88, neckline 36.03->35.91 (now 35.86) |

## Watchlist (pattern complete, waiting for a close above trigger): 4

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PH | Cup & Handle | 980.43 | 1009.98 | 921.31 | 6.03 | 1168.83 | 3.19 | 75 | - | - | 20.3 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-04-17 @1024.62, bottom 2026-06-01 @813.37 (depth 21%), right rim 2026-06-25 @1001.77, handle low 2026-07-07 @927.47 (depth 7.4%), trigger 980.43 |
| BKR | Cup & Handle | 66.09 | 68.9 | 60.48 | 8.49 | 79.45 | 2.38 | 73 | - | - | 50.7 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-06-04 @66.00, bottom 2026-07-02 @52.08 (depth 21%), right rim 2026-08-17 @65.44, handle low 2026-08-27 @60.87 (depth 7.0%), trigger 66.09 |
| EXPE | Cup & Handle | 274.29 | 287.23 | 248.41 | 9.44 | 344.09 | 2.7 | 72 | - | - | 11.5 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-04-21 @278.77, bottom 2026-05-20 @205.62 (depth 26%), right rim 2026-07-07 @275.41, handle low 2026-07-23 @250.76 (depth 9.0%), trigger 274.29 |
| RTX | Cup & Handle | 199.75 | 205.49 | 188.25 | 5.75 | 233.5 | 2.94 | 71 | - | - | 15.3 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-04-09 @203.83, bottom 2026-05-15 @169.51 (depth 17%), right rim 2026-07-07 @203.26, handle low 2026-07-21 @189.39 (depth 6.8%), trigger 199.75 |

## Closed since the last report (2026-09-09 06:00): 2

| Ticker | Pattern | Was | Outcome | Entry | Stop | Target | Detail |
|---|---|---|---|---|---|---|---|
| HAS | Cup & Handle | WATCHLIST | FADED | 94.64 | 87.66 | 116.29 | close 88.97 more than 5% below entry 94.64 |
| XOM | Inverse Head & Shoulders | WATCHLIST | DROPPED | 161.09 | 147.16 | 182.56 | pattern no longer qualifies |

_Max buy = the lower of trigger + 5% and the open at which the risk to the stop reaches 1.5x the planned entry-to-stop distance: if the open is above it the setup no longer qualifies. R:R = (target - entry) / (entry - stop) at the reported entry; it shrinks with every session the entry drifts above the trigger. F&G = the stock's own fear-and-greed reading at the last close, 0 to 100 (RSI 14, MACD-histogram percentile and Bollinger %B averaged): above 80 the stock is stretched and such breakouts replayed worst, below 20 it is washed out; information only, no rule uses it. Age = bars since the breakout close / the limit after which the row is dropped (0 = broke out on the last bar). Heuristic scan, not advice. Entry = trigger level, or the breakout close when it is above the trigger (closes more than 5% above the trigger are dropped as chasing). Stop = structural level minus 0.25 ATR, treated as an intraday touch in the backtest; exiting on a close at or below it scored higher in replay. Entry is the last close: a trade happens at the next open, so re-check that the open is still within 5% of the trigger and recompute risk from the fill. Verify on a chart before trading._