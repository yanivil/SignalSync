# S&P 500 pattern scan — 2026-10-24 05:54

Scanned 501 of 503 symbols (daily bars, last bar 2026-10-23). Min quality score 60. Breakouts older than the per-pattern limit are dropped (bars: Cup & Handle 3, Inverse Head & Shoulders 8, Bullish Wolfe Wave 8, Double Bottom 8; H&S and Wolfe get 5 extra bars because their last pivot is only visible 5 bars after it prints). Rows with reward:risk below 1.0 are dropped. Watchlist rows whose pattern completed more than 60 bars ago are dropped (a breakout is reported whenever it comes). A confirmed row is retired after its Cup & Handle session 6, Inverse Head & Shoulders session 6, Bullish Wolfe Wave session 5, Double Bottom session 6 on the list: entries later than that showed no edge in replay. Cup & Handle is watch-only: breakouts are listed on the watchlist for information, never as a buy signal (ten-year replay +0.03 R for the cup).
Data errors: 2
Market: SPY 5.0 % above its SMA200, SMA50 > SMA200 (bull); VIX 19.4; 58% of 499 symbols above their SMA200.

## Confirmed breakouts (actionable): 0

_none_

## Watchlist (pattern complete, waiting for a close above trigger): 2

| Ticker | Pattern | Entry | Max buy | Stop | Risk % | Target | R:R | Score | Age | Day | Vol× | F&G | Trend | Details |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HAL | Inverse Head & Shoulders | 35.71 | 37.25 | 32.64 | 8.61 | 40.86 | 1.67 | 83 | - | - | - | 82.2 | close below SMA200, SMA50 < SMA200, SMA200 rising/flat | LS 2026-07-02 @32.44, head 2026-07-30 @30.84, RS 2026-08-26 @32.88, neckline 36.03->35.91 (now 35.71) |
| ZBRA | Cup & Handle | 389.72 | 402.91 | 363.34 | 6.77 | 444.12 | 2.06 | 69 | - | - | - | 58.9 | close above SMA200, SMA50 > SMA200, SMA200 rising/flat | left rim 2026-08-12 @386.23, bottom 2026-09-10 @336.40 (depth 13%), right rim 2026-10-06 @390.80, handle low 2026-10-15 @365.76 (depth 6.4%), trigger 389.72 |

## Closed since the last report (2026-10-23 06:03): 2

| Ticker | Pattern | Was | Outcome | Entry | Stop | Target | Detail |
|---|---|---|---|---|---|---|---|
| DVA | Double Bottom | WATCHLIST | FADED | 195.75 | 172.54 | 220.1 | close 183.64 more than 5% below entry 195.75 |
| NXPI | Double Bottom | WATCHLIST | FADED | 248.86 | 216.77 | 281.06 | close 234.92 more than 5% below entry 248.86 |

_Max buy = the lower of trigger + 5% and the open at which the risk to the stop reaches 1.5x the planned entry-to-stop distance: if the open is above it the setup no longer qualifies. R:R = (target - entry) / (entry - stop) at the reported entry; it shrinks with every session the entry drifts above the trigger. Day = sessions on the list since the row's first report / the limit after which it is retired: in the eleven-year replay a row on its second day was as good as new, from the third the same signals paid about 0.1 R less than on day 1, and from day 7 (a Wolfe from day 6) nothing was left. F&G = the stock's own fear-and-greed reading at the last close, 0 to 100 (RSI 14, MACD-histogram percentile and Bollinger %B averaged): above 80 the stock is stretched and such breakouts replayed worst, below 20 it is washed out; information only, no rule uses it. Age = bars since the breakout close / the limit after which the row is dropped (0 = broke out on the last bar). Heuristic scan, not advice. Entry = trigger level, or the breakout close when it is above the trigger (closes more than 5% above the trigger are dropped as chasing). Stop = structural level minus 0.25 ATR, treated as an intraday touch in the backtest; exiting on a close at or below it scored higher in replay. Entry is the last close: a trade happens at the next open, so re-check that the open is still within 5% of the trigger and recompute risk from the fill. Verify on a chart before trading._