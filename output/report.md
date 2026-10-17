# S&P 500 pattern scan — 2026-10-17 05:37

Scanned 501 of 503 symbols (daily bars, last bar 2026-10-16). Min quality score 60. Breakouts older than the per-pattern limit are dropped (bars: Cup & Handle 3, Inverse Head & Shoulders 8, Bullish Wolfe Wave 8, Double Bottom 8; H&S and Wolfe get 5 extra bars because their last pivot is only visible 5 bars after it prints). Rows with reward:risk below 1.0 are dropped. Watchlist rows whose pattern completed more than 60 bars ago are dropped (a breakout is reported whenever it comes). A confirmed row is retired after its Cup & Handle session 6, Inverse Head & Shoulders session 6, Bullish Wolfe Wave session 5, Double Bottom session 6 on the list: entries later than that showed no edge in replay. Cup & Handle is watch-only: breakouts are listed on the watchlist for information, never as a buy signal (ten-year replay +0.03 R for the cup).
Data errors: 2
Market: SPY 5.7 % above its SMA200, SMA50 > SMA200 (bull); VIX 20.0; 55% of 499 symbols above their SMA200.

## Confirmed breakouts (actionable): 1

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Day | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NOC | Bullish Wolfe Wave | 519.86 | 532.46 | 467.14 | 10.14 | - | - | 65 | 0/8 | 1/5 | 1.3 | 79.8 | close below SMA200, SMA50 < SMA200, SMA200 falling | 1 2026-07-30 @517.42, 2 2026-08-18 @591.82, 3 2026-09-04 @512.54, 4 2026-09-15 @536.62, 5 2026-10-02 @470.06; line 1-3 now 507.10; ETA ~2026-09-28 |

## Watchlist (pattern complete, waiting for a close above trigger): 4

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Day | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GILD | Cup & Handle | 156.19 | 160.63 | 141.73 | 9.25 | 190.47 | 2.37 | 72 | 2/3 | - | 0.97 | 81.2 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-02-11 @154.51, bottom 2026-06-10 @119.92 (depth 22%), right rim 2026-09-23 @154.20, handle low 2026-10-06 @142.60 (depth 7.5%), trigger 152.98; breakout listed for information: watch-only pattern |
| DVA | Double Bottom | 195.75 | 205.54 | 172.54 | 11.86 | 220.1 | 1.05 | 71 | - | - | - | 80.1 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | L1 2026-08-24 @171.40, peak 2026-09-17 @195.75, L2 2026-10-01 @173.95, trigger 195.75 |
| FCX | Cup & Handle | 70.68 | 73.63 | 64.76 | 8.37 | 86.0 | 2.59 | 69 | - | - | - | 28.2 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-06-17 @71.95, bottom 2026-07-08 @55.74 (depth 23%), right rim 2026-08-10 @71.07, handle low 2026-08-14 @65.43 (depth 7.9%), trigger 70.68 |
| CVX | Cup & Handle | 224.99 | 227.5 | 199.61 | 11.28 | 279.42 | 2.14 | 64 | 3/3 | - | 0.79 | 88.9 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-03-30 @210.92, bottom 2026-07-01 @163.35 (depth 23%), right rim 2026-09-15 @217.78, handle low 2026-09-22 @200.78 (depth 7.8%), trigger 216.67; breakout listed for information: watch-only pattern |

## Closed since the last report (2026-10-16 05:53): 4

| Ticker | Pattern | Was | Outcome | Entry | Stop | Target | Detail |
|---|---|---|---|---|---|---|---|
| ORCL | Bullish Wolfe Wave | WATCHLIST | FAILED | 136.81 | 129.29 | 162.77 | close 128.23 on 2026-10-16 at or below stop 129.29 |
| ZBRA | Cup & Handle | WATCHLIST | FADED | 389.72 | 363.34 | 444.12 | close 369.01 more than 5% below entry 389.72 |
| CME | Double Bottom | CONFIRMED | DROPPED | 289.46 | 257.43 | 322.38 | pattern no longer qualifies |
| VTR | Bullish Wolfe Wave | CONFIRMED | DROPPED | 84.86 | 79.43 | 100.01 | pattern no longer qualifies |

_Max buy = the lower of trigger + 5% and the open at which the risk to the stop reaches 1.5x the planned entry-to-stop distance: if the open is above it the setup no longer qualifies. R:R = (target - entry) / (entry - stop) at the reported entry; it shrinks with every session the entry drifts above the trigger. Day = sessions on the list since the row's first report / the limit after which it is retired: in the eleven-year replay a row on its second day was as good as new, from the third the same signals paid about 0.1 R less than on day 1, and from day 7 (a Wolfe from day 6) nothing was left. F&G = the stock's own fear-and-greed reading at the last close, 0 to 100 (RSI 14, MACD-histogram percentile and Bollinger %B averaged): above 80 the stock is stretched and such breakouts replayed worst, below 20 it is washed out; information only, no rule uses it. Age = bars since the breakout close / the limit after which the row is dropped (0 = broke out on the last bar). Heuristic scan, not advice. Entry = trigger level, or the breakout close when it is above the trigger (closes more than 5% above the trigger are dropped as chasing). Stop = structural level minus 0.25 ATR, treated as an intraday touch in the backtest; exiting on a close at or below it scored higher in replay. Entry is the last close: a trade happens at the next open, so re-check that the open is still within 5% of the trigger and recompute risk from the fill. Verify on a chart before trading._