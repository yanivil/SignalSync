# S&P 500 pattern scan — 2026-10-23 06:03

Scanned 501 of 503 symbols (daily bars, last bar 2026-10-22). Min quality score 60. Breakouts older than the per-pattern limit are dropped (bars: Cup & Handle 3, Inverse Head & Shoulders 8, Bullish Wolfe Wave 8, Double Bottom 8; H&S and Wolfe get 5 extra bars because their last pivot is only visible 5 bars after it prints). Rows with reward:risk below 1.0 are dropped. Watchlist rows whose pattern completed more than 60 bars ago are dropped (a breakout is reported whenever it comes). A confirmed row is retired after its Cup & Handle session 6, Inverse Head & Shoulders session 6, Bullish Wolfe Wave session 5, Double Bottom session 6 on the list: entries later than that showed no edge in replay. Cup & Handle is watch-only: breakouts are listed on the watchlist for information, never as a buy signal (ten-year replay +0.03 R for the cup).
Data errors: 2
Market: SPY 5.6 % above its SMA200, SMA50 > SMA200 (bull); VIX 19.0; 60% of 499 symbols above their SMA200.

## Confirmed breakouts (actionable): 0

_none_

## Watchlist (pattern complete, waiting for a close above trigger): 3

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Day | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DVA | Double Bottom | 195.75 | 205.54 | 172.54 | 11.86 | 220.1 | 1.05 | 71 | - | - | - | 72.0 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | L1 2026-08-24 @171.40, peak 2026-09-17 @195.75, L2 2026-10-01 @173.95, trigger 195.75 |
| NXPI | Double Bottom | 248.86 | 261.3 | 216.77 | 12.9 | 281.06 | 1.0 | 71 | - | - | - | 60.1 | close below SMA200, SMA50 < SMA200, SMA200 rising/flat | L1 2026-09-16 @216.66, peak 2026-10-02 @248.86, L2 2026-10-14 @218.64, trigger 248.86 |
| ZBRA | Cup & Handle | 389.72 | 402.91 | 363.34 | 6.77 | 444.12 | 2.06 | 69 | - | - | - | 55.4 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-08-12 @386.23, bottom 2026-09-10 @336.40 (depth 13%), right rim 2026-10-06 @390.80, handle low 2026-10-15 @365.76 (depth 6.4%), trigger 389.72 |

## Closed since the last report (2026-10-22 06:08): 4

| Ticker | Pattern | Was | Outcome | Entry | Stop | Target | Detail |
|---|---|---|---|---|---|---|---|
| FCX | Cup & Handle | WATCHLIST | FAILED | 70.68 | 64.76 | 86.0 | close 64.59 on 2026-10-22 at or below stop 64.76 |
| VTR | Bullish Wolfe Wave | CONFIRMED | EXPIRED | 85.38 | 79.43 | 100.01 | breakout 9 bars old, limit 8 |
| ECHO | Double Bottom | WATCHLIST | FADED | 94.95 | 83.5 | 107.42 | close 85.79 more than 5% below entry 94.95 |
| HAL | Inverse Head & Shoulders | WATCHLIST | FADED | 35.72 | 32.64 | 40.87 | close 33.19 more than 5% below entry 35.72 |

_Max buy = the lower of trigger + 5% and the open at which the risk to the stop reaches 1.5x the planned entry-to-stop distance: if the open is above it the setup no longer qualifies. R:R = (target - entry) / (entry - stop) at the reported entry; it shrinks with every session the entry drifts above the trigger. Day = sessions on the list since the row's first report / the limit after which it is retired: in the eleven-year replay a row on its second day was as good as new, from the third the same signals paid about 0.1 R less than on day 1, and from day 7 (a Wolfe from day 6) nothing was left. F&G = the stock's own fear-and-greed reading at the last close, 0 to 100 (RSI 14, MACD-histogram percentile and Bollinger %B averaged): above 80 the stock is stretched and such breakouts replayed worst, below 20 it is washed out; information only, no rule uses it. Age = bars since the breakout close / the limit after which the row is dropped (0 = broke out on the last bar). Heuristic scan, not advice. Entry = trigger level, or the breakout close when it is above the trigger (closes more than 5% above the trigger are dropped as chasing). Stop = structural level minus 0.25 ATR, treated as an intraday touch in the backtest; exiting on a close at or below it scored higher in replay. Entry is the last close: a trade happens at the next open, so re-check that the open is still within 5% of the trigger and recompute risk from the fill. Verify on a chart before trading._