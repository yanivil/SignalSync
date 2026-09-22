# S&P 500 pattern scan — 2026-09-22 06:14

Scanned 503 of 503 symbols (daily bars, last bar 2026-09-21). Min quality score 60. Breakouts older than the per-pattern limit are dropped (bars: Cup & Handle 3, Inverse Head & Shoulders 8, Bullish Wolfe Wave 8, Double Bottom 8; H&S and Wolfe get 5 extra bars because their last pivot is only visible 5 bars after it prints). Rows with reward:risk below 1.0 are dropped. Watchlist rows whose pattern completed more than 60 bars ago are dropped (a breakout is reported whenever it comes). A confirmed row is retired after its Cup & Handle session 6, Inverse Head & Shoulders session 6, Bullish Wolfe Wave session 5, Double Bottom session 6 on the list: entries later than that showed no edge in replay. Cup & Handle is watch-only: breakouts are listed on the watchlist for information, never as a buy signal (ten-year replay +0.03 R for the cup).
Market: SPY 8.5 % above its SMA200, SMA50 > SMA200 (bull); VIX 14.9; 52% of 501 symbols above their SMA200.

## Confirmed breakouts (actionable): 1

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Day | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ECHO | Double Bottom | 95.36 | 99.7 | 83.5 | 12.43 | 107.83 | 1.05 | 67 | 0/8 | 1/6 | 1.64 | 76.2 | close below SMA200, SMA50 < SMA200, SMA200 rising/flat | L1 2026-07-29 @82.48, peak 2026-08-17 @94.95, L2 2026-08-26 @84.26, trigger 94.95 |

## Watchlist (pattern complete, waiting for a close above trigger): 5

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Day | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MO | Inverse Head & Shoulders | 70.25 | 72.38 | 66.0 | 6.06 | 76.06 | 1.36 | 82 | - | 4/6 | - | 61.5 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | LS 2026-07-31 @65.78, head 2026-08-17 @62.92, RS 2026-09-09 @66.34, neckline 68.27->69.42 (now 70.25) |
| GILD | Cup & Handle | 150.63 | 155.0 | 141.89 | 5.8 | 182.41 | 3.64 | 75 | - | - | - | 63.1 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-02-11 @154.51, bottom 2026-06-10 @119.92 (depth 22%), right rim 2026-09-02 @151.70, handle low 2026-09-11 @142.70 (depth 5.9%), trigger 150.63 |
| PH | Cup & Handle | 980.43 | 1009.98 | 921.31 | 6.03 | 1168.83 | 3.19 | 75 | - | - | - | 46.5 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-04-17 @1024.62, bottom 2026-06-01 @813.37 (depth 21%), right rim 2026-06-25 @1001.77, handle low 2026-07-07 @927.47 (depth 7.4%), trigger 980.43 |
| XOM | Inverse Head & Shoulders | 162.07 | 169.53 | 147.16 | 9.2 | 183.53 | 1.44 | 75 | - | - | - | 26.5 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | LS 2026-05-29 @143.78, head 2026-06-25 @134.08, RS 2026-08-04 @148.13, neckline 153.91->158.05 (now 162.07) |
| RTX | Cup & Handle | 199.75 | 205.49 | 188.25 | 5.75 | 233.5 | 2.94 | 71 | - | - | - | 25.9 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-04-09 @203.83, bottom 2026-05-15 @169.51 (depth 17%), right rim 2026-07-07 @203.26, handle low 2026-07-21 @189.39 (depth 6.8%), trigger 199.75 |

## Closed since the last report (2026-09-21 06:22): 0

_none_

_Max buy = the lower of trigger + 5% and the open at which the risk to the stop reaches 1.5x the planned entry-to-stop distance: if the open is above it the setup no longer qualifies. R:R = (target - entry) / (entry - stop) at the reported entry; it shrinks with every session the entry drifts above the trigger. Day = sessions on the list since the row's first report / the limit after which it is retired: in the eleven-year replay a row on its second day was as good as new, from the third the same signals paid about 0.1 R less than on day 1, and from day 7 (a Wolfe from day 6) nothing was left. F&G = the stock's own fear-and-greed reading at the last close, 0 to 100 (RSI 14, MACD-histogram percentile and Bollinger %B averaged): above 80 the stock is stretched and such breakouts replayed worst, below 20 it is washed out; information only, no rule uses it. Age = bars since the breakout close / the limit after which the row is dropped (0 = broke out on the last bar). Heuristic scan, not advice. Entry = trigger level, or the breakout close when it is above the trigger (closes more than 5% above the trigger are dropped as chasing). Stop = structural level minus 0.25 ATR, treated as an intraday touch in the backtest; exiting on a close at or below it scored higher in replay. Entry is the last close: a trade happens at the next open, so re-check that the open is still within 5% of the trigger and recompute risk from the fill. Verify on a chart before trading._