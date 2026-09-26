# S&P 500 pattern scan — 2026-09-26 06:11

Scanned 503 of 503 symbols (daily bars, last bar 2026-09-25). Min quality score 60. Breakouts older than the per-pattern limit are dropped (bars: Cup & Handle 3, Inverse Head & Shoulders 8, Bullish Wolfe Wave 8, Double Bottom 8; H&S and Wolfe get 5 extra bars because their last pivot is only visible 5 bars after it prints). Rows with reward:risk below 1.0 are dropped. Watchlist rows whose pattern completed more than 60 bars ago are dropped (a breakout is reported whenever it comes). A confirmed row is retired after its Cup & Handle session 6, Inverse Head & Shoulders session 6, Bullish Wolfe Wave session 5, Double Bottom session 6 on the list: entries later than that showed no edge in replay. Cup & Handle is watch-only: breakouts are listed on the watchlist for information, never as a buy signal (ten-year replay +0.03 R for the cup).
Market: SPY 7.9 % above its SMA200, SMA50 > SMA200 (bull); VIX 14.9; 48% of 501 symbols above their SMA200.

## Confirmed breakouts (actionable): 0

_none_

## Watchlist (pattern complete, waiting for a close above trigger): 5

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Day | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MO | Inverse Head & Shoulders | 70.51 | 72.76 | 66.0 | 6.4 | 76.31 | 1.29 | 82 | - | 8/6 | - | 52.7 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | LS 2026-07-31 @65.78, head 2026-08-17 @62.92, RS 2026-09-09 @66.34, neckline 68.27->69.42 (now 70.51) |
| PH | Cup & Handle | 980.43 | 1009.98 | 921.31 | 6.03 | 1168.83 | 3.19 | 75 | - | - | - | 73.1 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-04-17 @1024.62, bottom 2026-06-01 @813.37 (depth 21%), right rim 2026-06-25 @1001.77, handle low 2026-07-07 @927.47 (depth 7.4%), trigger 980.43 |
| XOM | Inverse Head & Shoulders | 162.51 | 170.18 | 147.16 | 9.45 | 183.97 | 1.4 | 75 | - | - | - | 32.8 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | LS 2026-05-29 @143.78, head 2026-06-25 @134.08, RS 2026-08-04 @148.13, neckline 153.91->158.05 (now 162.51) |
| EXPE | Cup & Handle | 274.29 | 287.23 | 248.41 | 9.44 | 344.09 | 2.7 | 72 | - | - | - | 24.0 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-04-21 @278.77, bottom 2026-05-20 @205.62 (depth 26%), right rim 2026-07-07 @275.41, handle low 2026-07-23 @250.76 (depth 9.0%), trigger 274.29 |
| YUM | Bullish Wolfe Wave | 138.8 | 141.57 | 133.26 | 4.0 | 181.5 | 7.7 | 67 | - | - | - | 32.6 | close below SMA200, SMA50 < SMA200, SMA200 rising/flat | 1 2026-07-21 @143.91, 2 2026-07-30 @165.33, 3 2026-08-11 @142.28, 4 2026-08-24 @157.26, 5 2026-09-18 @134.26; line 1-3 now 138.80; first target 157.26 (point 4) |

## Closed since the last report (2026-09-25 06:11): 3

| Ticker | Pattern | Was | Outcome | Entry | Stop | Target | Detail |
|---|---|---|---|---|---|---|---|
| CVX | Cup & Handle | WATCHLIST | FADED | 215.28 | 202.31 | 269.71 | close 204.45 more than 5% below entry 215.28 |
| ECHO | Double Bottom | WATCHLIST | FADED | 94.95 | 83.5 | 107.42 | close 90.11 more than 5% below entry 94.95 |
| GILD | Cup & Handle | WATCHLIST | DROPPED | 150.63 | 141.89 | 182.41 | pattern no longer qualifies |

_Max buy = the lower of trigger + 5% and the open at which the risk to the stop reaches 1.5x the planned entry-to-stop distance: if the open is above it the setup no longer qualifies. R:R = (target - entry) / (entry - stop) at the reported entry; it shrinks with every session the entry drifts above the trigger. Day = sessions on the list since the row's first report / the limit after which it is retired: in the eleven-year replay a row on its second day was as good as new, from the third the same signals paid about 0.1 R less than on day 1, and from day 7 (a Wolfe from day 6) nothing was left. F&G = the stock's own fear-and-greed reading at the last close, 0 to 100 (RSI 14, MACD-histogram percentile and Bollinger %B averaged): above 80 the stock is stretched and such breakouts replayed worst, below 20 it is washed out; information only, no rule uses it. Age = bars since the breakout close / the limit after which the row is dropped (0 = broke out on the last bar). Heuristic scan, not advice. Entry = trigger level, or the breakout close when it is above the trigger (closes more than 5% above the trigger are dropped as chasing). Stop = structural level minus 0.25 ATR, treated as an intraday touch in the backtest; exiting on a close at or below it scored higher in replay. Entry is the last close: a trade happens at the next open, so re-check that the open is still within 5% of the trigger and recompute risk from the fill. Verify on a chart before trading._