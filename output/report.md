# S&P 500 pattern scan — 2026-09-15 06:11

Scanned 503 of 503 symbols (daily bars, last bar 2026-09-14). Min quality score 60. Breakouts older than the per-pattern limit are dropped (bars: Cup & Handle 3, Inverse Head & Shoulders 8, Bullish Wolfe Wave 8; H&S and Wolfe get 5 extra bars because their last pivot is only visible 5 bars after it prints). Rows with reward:risk below 1.0 are dropped. Watchlist rows whose pattern completed more than 60 bars ago are dropped (a breakout is reported whenever it comes).
1 symbols have no complete bar on 2026-09-14 and were scanned on their own last bar.
Market: SPY 6.8 % above its SMA200, SMA50 > SMA200 (bull); VIX 17.1; 59% of 500 symbols above their SMA200.

## Confirmed breakouts (actionable): 0

_none_

## Watchlist (pattern complete, waiting for a close above trigger): 6

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NVDA | Inverse Head & Shoulders | 213.1 | 221.69 | 195.91 | 8.06 | 237.21 | 1.4 | 89 | - | - | 25.2 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | LS 2026-06-09 @199.12, head 2026-06-29 @189.59, RS 2026-07-17 @197.75, neckline 213.75->213.57 (now 213.10) |
| HAL | Inverse Head & Shoulders | 35.84 | 37.44 | 32.64 | 8.93 | 40.99 | 1.61 | 87 | - | - | 37.3 | close above SMA200, SMA50 < SMA200, SMA200 rising/flat | LS 2026-07-02 @32.44, head 2026-07-30 @30.84, RS 2026-08-26 @32.88, neckline 36.03->35.91 (now 35.84) |
| GILD | Cup & Handle | 151.48 | 155.87 | 142.69 | 5.8 | 183.43 | 3.64 | 75 | - | - | 38.4 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-02-11 @155.38, bottom 2026-06-10 @120.60 (depth 22%), right rim 2026-09-02 @152.55, handle low 2026-09-11 @143.50 (depth 5.9%), trigger 151.48 |
| RTX | Cup & Handle | 199.75 | 205.49 | 188.25 | 5.75 | 233.5 | 2.94 | 71 | - | - | 17.7 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-04-09 @203.83, bottom 2026-05-15 @169.51 (depth 17%), right rim 2026-07-07 @203.26, handle low 2026-07-21 @189.39 (depth 6.8%), trigger 199.75 |
| FCX | Cup & Handle | 70.83 | 73.79 | 64.9 | 8.37 | 86.19 | 2.59 | 69 | - | - | 24.4 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-06-17 @72.10, bottom 2026-07-08 @55.86 (depth 23%), right rim 2026-08-10 @71.22, handle low 2026-08-14 @65.57 (depth 7.9%), trigger 70.83 |
| HAS | Cup & Handle | 94.64 | 98.13 | 87.66 | 7.37 | 116.29 | 3.1 | 68 | - | - | 26.0 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-05-07 @97.30, bottom 2026-07-08 @74.63 (depth 23%), right rim 2026-07-29 @96.28, handle low 2026-08-04 @88.44 (depth 8.1%), trigger 94.64 |

## Closed since the last report (2026-09-14 06:18): 1

| Ticker | Pattern | Was | Outcome | Entry | Stop | Target | Detail |
|---|---|---|---|---|---|---|---|
| PH | Cup & Handle | WATCHLIST | FADED | 980.43 | 921.31 | 1168.83 | close 928.83 more than 5% below entry 980.43 |

_Max buy = the lower of trigger + 5% and the open at which the risk to the stop reaches 1.5x the planned entry-to-stop distance: if the open is above it the setup no longer qualifies. R:R = (target - entry) / (entry - stop) at the reported entry; it shrinks with every session the entry drifts above the trigger. F&G = the stock's own fear-and-greed reading at the last close, 0 to 100 (RSI 14, MACD-histogram percentile and Bollinger %B averaged): above 80 the stock is stretched and such breakouts replayed worst, below 20 it is washed out; information only, no rule uses it. Age = bars since the breakout close / the limit after which the row is dropped (0 = broke out on the last bar). Heuristic scan, not advice. Entry = trigger level, or the breakout close when it is above the trigger (closes more than 5% above the trigger are dropped as chasing). Stop = structural level minus 0.25 ATR, treated as an intraday touch in the backtest; exiting on a close at or below it scored higher in replay. Entry is the last close: a trade happens at the next open, so re-check that the open is still within 5% of the trigger and recompute risk from the fill. Verify on a chart before trading._