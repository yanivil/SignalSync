# S&P 500 pattern scan — 2026-10-07 07:15

Scanned 502 of 503 symbols (daily bars, last bar 2026-10-06). Min quality score 60. Breakouts older than the per-pattern limit are dropped (bars: Cup & Handle 3, Inverse Head & Shoulders 8, Bullish Wolfe Wave 8, Double Bottom 8; H&S and Wolfe get 5 extra bars because their last pivot is only visible 5 bars after it prints). Rows with reward:risk below 1.0 are dropped. Watchlist rows whose pattern completed more than 60 bars ago are dropped (a breakout is reported whenever it comes). A confirmed row is retired after its Cup & Handle session 6, Inverse Head & Shoulders session 6, Bullish Wolfe Wave session 5, Double Bottom session 6 on the list: entries later than that showed no edge in replay. Cup & Handle is watch-only: breakouts are listed on the watchlist for information, never as a buy signal (ten-year replay +0.03 R for the cup).
Data errors: 1
Market: SPY 8.5 % above its SMA200, SMA50 > SMA200 (bull); VIX 15.0; 50% of 500 symbols above their SMA200.

## Confirmed breakouts (actionable): 1

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Day | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ORCL | Bullish Wolfe Wave | 144.77 | 144.94 | 129.77 | 10.36 | 163.37 | 1.24 | 70 | 2/8 | 2/5 | 0.99 | 51.1 | close below SMA200, SMA50 < SMA200, SMA200 falling | 1 2026-09-02 @139.72, 2 2026-09-08 @170.70, 3 2026-09-16 @139.00, 4 2026-09-22 @153.60, 5 2026-09-28 @131.58; line 1-3 now 137.88; ETA ~2026-10-05; first target 153.60 (point 4) |

## Watchlist (pattern complete, waiting for a close above trigger): 4

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Day | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MO | Inverse Head & Shoulders | 70.96 | 73.44 | 66.0 | 6.99 | 76.76 | 1.17 | 82 | - | - | - | 44.6 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | LS 2026-07-31 @65.78, head 2026-08-17 @62.92, RS 2026-09-09 @66.34, neckline 68.27->69.42 (now 70.96) |
| GILD | Cup & Handle | 150.63 | 155.0 | 141.89 | 5.8 | 182.41 | 3.64 | 75 | - | - | - | 22.7 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-02-11 @154.51, bottom 2026-06-10 @119.92 (depth 22%), right rim 2026-09-02 @151.70, handle low 2026-09-11 @142.70 (depth 5.9%), trigger 150.63 |
| CVX | Cup & Handle | 215.28 | 223.12 | 199.61 | 7.28 | 269.71 | 3.47 | 68 | - | - | - | 39.6 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-03-30 @210.92, bottom 2026-07-01 @163.35 (depth 23%), right rim 2026-09-15 @217.78, handle low 2026-09-22 @200.78 (depth 7.8%), trigger 215.28 |
| HAS | Cup & Handle | 94.64 | 98.13 | 87.66 | 7.37 | 116.29 | 3.1 | 68 | - | - | - | 73.4 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-05-07 @97.30, bottom 2026-07-08 @74.63 (depth 23%), right rim 2026-07-29 @96.28, handle low 2026-08-04 @88.44 (depth 8.1%), trigger 94.64 |

## Closed since the last report (2026-10-06 07:35): 1

| Ticker | Pattern | Was | Outcome | Entry | Stop | Target | Detail |
|---|---|---|---|---|---|---|---|
| YUM | Bullish Wolfe Wave | WATCHLIST | DROPPED | 138.15 | 133.26 | 181.5 | pattern no longer qualifies |

_Max buy = the lower of trigger + 5% and the open at which the risk to the stop reaches 1.5x the planned entry-to-stop distance: if the open is above it the setup no longer qualifies. R:R = (target - entry) / (entry - stop) at the reported entry; it shrinks with every session the entry drifts above the trigger. Day = sessions on the list since the row's first report / the limit after which it is retired: in the eleven-year replay a row on its second day was as good as new, from the third the same signals paid about 0.1 R less than on day 1, and from day 7 (a Wolfe from day 6) nothing was left. F&G = the stock's own fear-and-greed reading at the last close, 0 to 100 (RSI 14, MACD-histogram percentile and Bollinger %B averaged): above 80 the stock is stretched and such breakouts replayed worst, below 20 it is washed out; information only, no rule uses it. Age = bars since the breakout close / the limit after which the row is dropped (0 = broke out on the last bar). Heuristic scan, not advice. Entry = trigger level, or the breakout close when it is above the trigger (closes more than 5% above the trigger are dropped as chasing). Stop = structural level minus 0.25 ATR, treated as an intraday touch in the backtest; exiting on a close at or below it scored higher in replay. Entry is the last close: a trade happens at the next open, so re-check that the open is still within 5% of the trigger and recompute risk from the fill. Verify on a chart before trading._