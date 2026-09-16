# S&P 500 pattern scan — 2026-09-16 06:02

Scanned 503 of 503 symbols (daily bars, last bar 2026-09-15). Min quality score 60. Breakouts older than the per-pattern limit are dropped (bars: Cup & Handle 3, Inverse Head & Shoulders 8, Bullish Wolfe Wave 8; H&S and Wolfe get 5 extra bars because their last pivot is only visible 5 bars after it prints). Rows with reward:risk below 1.0 are dropped. Watchlist rows whose pattern completed more than 60 bars ago are dropped (a breakout is reported whenever it comes). A confirmed row is retired after its Cup & Handle session 6, Inverse Head & Shoulders session 6, Bullish Wolfe Wave session 5 on the list: entries later than that showed no edge in replay.
Market: SPY 6.2 % above its SMA200, SMA50 > SMA200 (bull); VIX 17.2; 57% of 501 symbols above their SMA200.

## Confirmed breakouts (actionable): 0

_none_

## Watchlist (pattern complete, waiting for a close above trigger): 6

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Day | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NVDA | Inverse Head & Shoulders | 213.09 | 221.67 | 195.91 | 8.06 | 237.19 | 1.4 | 89 | - | - | - | 26.2 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | LS 2026-06-09 @199.12, head 2026-06-29 @189.59, RS 2026-07-17 @197.75, neckline 213.75->213.57 (now 213.09) |
| HAL | Inverse Head & Shoulders | 35.84 | 37.44 | 32.64 | 8.92 | 40.98 | 1.61 | 87 | - | - | - | 41.9 | close above SMA200, SMA50 < SMA200, SMA200 rising/flat | LS 2026-07-02 @32.44, head 2026-07-30 @30.84, RS 2026-08-26 @32.88, neckline 36.03->35.91 (now 35.84) |
| GILD | Cup & Handle | 150.63 | 155.0 | 141.89 | 5.8 | 182.41 | 3.64 | 75 | - | - | - | 40.4 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-02-11 @154.51, bottom 2026-06-10 @119.92 (depth 22%), right rim 2026-09-02 @151.70, handle low 2026-09-11 @142.70 (depth 5.9%), trigger 150.63 |
| RTX | Cup & Handle | 199.75 | 205.49 | 188.25 | 5.75 | 233.5 | 2.94 | 71 | - | - | - | 19.8 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-04-09 @203.83, bottom 2026-05-15 @169.51 (depth 17%), right rim 2026-07-07 @203.26, handle low 2026-07-21 @189.39 (depth 6.8%), trigger 199.75 |
| FCX | Cup & Handle | 70.83 | 73.79 | 64.9 | 8.37 | 86.19 | 2.59 | 69 | - | - | - | 23.8 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-06-17 @72.10, bottom 2026-07-08 @55.86 (depth 23%), right rim 2026-08-10 @71.22, handle low 2026-08-14 @65.57 (depth 7.9%), trigger 70.83 |
| HAS | Cup & Handle | 94.64 | 98.13 | 87.66 | 7.37 | 116.29 | 3.1 | 68 | - | - | - | 24.7 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-05-07 @97.30, bottom 2026-07-08 @74.63 (depth 23%), right rim 2026-07-29 @96.28, handle low 2026-08-04 @88.44 (depth 8.1%), trigger 94.64 |

## Closed since the last report (2026-09-15 06:11): 0

_none_

_Max buy = the lower of trigger + 5% and the open at which the risk to the stop reaches 1.5x the planned entry-to-stop distance: if the open is above it the setup no longer qualifies. R:R = (target - entry) / (entry - stop) at the reported entry; it shrinks with every session the entry drifts above the trigger. Day = sessions on the list since the row's first report / the limit after which it is retired: in the eleven-year replay a row on its second day was as good as new, from the third the same signals paid about 0.1 R less than on day 1, and from day 7 (a Wolfe from day 6) nothing was left. F&G = the stock's own fear-and-greed reading at the last close, 0 to 100 (RSI 14, MACD-histogram percentile and Bollinger %B averaged): above 80 the stock is stretched and such breakouts replayed worst, below 20 it is washed out; information only, no rule uses it. Age = bars since the breakout close / the limit after which the row is dropped (0 = broke out on the last bar). Heuristic scan, not advice. Entry = trigger level, or the breakout close when it is above the trigger (closes more than 5% above the trigger are dropped as chasing). Stop = structural level minus 0.25 ATR, treated as an intraday touch in the backtest; exiting on a close at or below it scored higher in replay. Entry is the last close: a trade happens at the next open, so re-check that the open is still within 5% of the trigger and recompute risk from the fill. Verify on a chart before trading._