# Pattern Catalog

Every detector works on positional daily bars (`High`, `Low`, `Close` as numpy arrays), shares the same primitives, and returns `Signal` records de-duplicated to the best score per `(ticker, pattern, status)`. All thresholds are module constants; see [Configuration and Tuning](03-Configuration-and-Tuning.md) for the full table.

## Shared primitives

| Primitive | Definition | Notes |
|---|---|---|
| ATR | simple rolling mean of true range over `ATR_LEN` = 14 bars, `min_periods=1` | bar 0 is High − Low; a flat series has ATR 0 |
| Swing high / low (`find_pivots`) | bar *i* is a swing high if `high[i]` is the maximum of `[i−5, i+5]` **and** the first maximum in that window; swing lows likewise on `low` | O(n · order). The last 5 bars can never be pivots (no repainting), so any pattern whose last anchor is a pivot is seen up to 5 bars late. Flat stretches produce no pivots because the tie goes to the window's first bar. |
| Trend context | `uptrend` = close > SMA200; `strong_downtrend` = close < 0.90 × SMA200 **and** SMA200 below its value 40 bars earlier. With fewer than 200 bars, or when the SMA200 exists but not 40 bars ago (200–239 bars): SMA50 with a 0.85 factor. | continuation pattern requires `uptrend`; reversal patterns are vetoed by `strong_downtrend` |
| Breakout state (`_status_from_break`) | first close above the trigger from the pattern's completion bar; `age` = bars since | `CONFIRMED` if `age ≤ MAX_BREAKOUT_AGE + lag`, last close still above the trigger and not more than 5 % above it; `WATCHLIST` if unbroken and last close ≥ 97 % of the trigger; otherwise `STALE` (dropped) |
| Volume ratio | volume on the breakout bar / mean of the 50 bars before it | `None` before bar 20 or when the base is zero; adds +5 score when ≥ 1.3 |
| Risk filter | `risk_pct = (entry − stop) / entry × 100`; rejected if > 15 or if `stop ≥ entry` | applies to every pattern |

Entry is the breakout close when it is above the trigger (and within 5 % of it), otherwise the trigger itself (watchlist rows). Either way it is the previous session's close: a trade placed after the morning report fills at the next US open, so the reported risk % and target are estimates, and a gap-up past 5 % over the trigger is the same "runaway" condition that would have filtered the setup.

## Summary table

| Pattern | Anchors | Width (bars) | Core geometric tests | Trigger | Stop | Target |
|---|---|---|---|---|---|---|
| Cup & Handle | swing highs A, B; lowest low between; handle after B | 30–250 cup, 5–40 handle | rim B within 5 % of A; depth 12–50 % of A; bottom in the middle 60 %; ≥ 25 % advance into A; convex-quadratic R² ≥ 0.60 and ≥ the best V fit; handle ≤ 12 % deep, ≤ ½ cup depth, above the cup midpoint; close > SMA200 | close > handle high | handle low − 0.25 ATR | entry + (A − bottom) |
| Inverse H&S | consecutive swing lows LS, H, RS; neckline through the highest high of each half | 20–200 | H ≥ 1 ATR below both shoulders; shoulder gap ≤ 50 % of the shallower depth; left/right duration ratio within 2.5×; neckline tilt ≤ 15 % of price over the width; ≥ 10 % decline into LS; not a strong down-trend | close > neckline value on that bar | RS − 0.25 ATR | entry + (trigger − H) |
| Bullish Wolfe Wave | swing lows 1, 3, 5; swing highs 2, 4 | 15–200 (1→5), 5 within the last 25 bars | 3 < 1, 5 < 3, 4 < 2, 1 < 4 < 2; line 2-4 falls faster than 1-3 (converging); point 5 within [−0.5, +2] ATR of the extended 1-3 line; not a strong down-trend | close > line 1-3 after point 5 | point 5 − 0.25 ATR | line 1-4 at the ETA |

## Cup & Handle (`detect_cup_and_handle`)

**Search.** For each pair of swing highs (A, B) with `30 ≤ B − A ≤ 250` (the inner loop breaks once the width exceeds the maximum, so cost is O(P² · W) worst case, P = swing highs, W = cup width):

1. Rims: `|high[B] − high[A]| / high[A] ≤ CUP_RIM_TOL` (0.05).
2. Bottom: lowest low in `[A, B]`; `depth = (high[A] − bottom) / high[A]` must be in `[0.12, 0.50]`; bottom position `(idx − A) / (B − A)` in `[0.20, 0.80]`.
3. Prior advance: the rise from the lowest low of the 120 bars before A to `high[A]` must be ≥ 25 % (`(high[A] − low) / low ≥ 0.25`, i.e. the low is at most 20 % below the rim). It is a rise test, not a "25 % below the rim" test, which would demand a 33 % rise.
4. Roundness: `R²` of a convex (a > 0) quadratic least-squares fit of the lows over `[A, B]` must be ≥ 0.60. An arch (a ≤ 0) scores 0.
5. U versus V: the best two-legged fit `a + b·|x − c|` (b > 0, vertex `c` searched within ±10 % of the width around the lowest low) may not beat the parabola's R² by more than `CUP_MAX_V_ADVANTAGE` (0). On reference shapes the parabola wins by +0.04 on a half-sine, +0.37 on a flat dish and +0.01 on a lopsided sine, and loses by 0.06 on a clean V, so a sharp reversal is rejected while any rounded or flat base passes.
6. Handle (`_find_handle`): runs from `B+1` to the bar before the first close above the handle's running high, capped at 40 bars or the end of data, and must last ≥ 5 bars (a close above the running high within the first 5 bars is still "the handle forming"). Handle depth `(high[B] − handle_low) / high[B]` ≤ 0.12, ≤ 0.50 × cup depth, and the handle low must stay above `bottom + 0.5 × (high[B] − bottom)`.
7. Trigger = the handle's highest high, which is O'Neil's buy point (the handle peak, not the cup rim: a handle normally sits below the rim, and waiting for the rim is a later, more conservative entry). Confirmation is scanned from the bar after the handle ends. Rim B is a swing high, so no bar within 5 of it can exceed it, but a wick above B later in the handle (a bar whose high spikes but whose close stays below the running handle high) raises the trigger above the rim; the setup then needs a close above that wick, which is conservative and usually leaves it on the watchlist.

**Levels.** `stop = handle_low − 0.25 × ATR[handle_low]`; `target = entry + (high[A] − bottom)` (measured move).

**Score.** 50 + 15 × (R² − 0.60)/(1 − 0.60) + 10 × (1 − |depth − 0.25| / 0.25) + 10 × (1 − handle_depth / 0.12) + 10 × (1 − risk / 15) + 5 if volume ratio ≥ 1.3, clipped to 0–100.

**Edge cases and known behaviour**

* The roundness R² alone would pass a clean symmetric V (a parabola explains `|x|` with R² ≈ 0.93); the U-versus-V comparison is what rejects it. The threshold is calibrated on reference shapes (`test_patterns.py::test_v_shape_r2_separates_rounded_bases_from_sharp_reversals`), not on market data, so watch the first live runs for cups that disappear from the report and revisit `CUP_MAX_V_ADVANTAGE` if rounded bases are being lost.
* A single wick spike inside the handle (e.g. a −20 % low) fails the handle depth rule; a spike inside the cup body fails the position/roundness rules; spikes before the pattern are irrelevant.
* Zero-volume sessions never invalidate a cup; they only remove the +5 volume bonus (ratio `None` or `0.0`).
* Missing interior bars shift nothing: detectors are positional. Levels are unchanged when rows are removed, the roundness score may move slightly.
* Because the cup's last anchor (the handle low) needs no right-side confirmation, the cup gets **no** extra breakout-age tolerance (`BREAKOUT_AGE_LAG` = 0).

## Inverse Head & Shoulders (`detect_inverse_hs`)

**Search.** Every triple of consecutive swing lows (LS, H, RS) with `20 ≤ RS − LS ≤ 200` (cost O(L · (W + n))):

1. Head depth: `low[H] < low[LS] − 1.0 × ATR[H]` and `low[H] < low[RS] − 1.0 × ATR[H]`.
2. Shoulder price symmetry: `|low[LS] − low[RS]| ≤ 0.50 × min(low[LS] − low[H], low[RS] − low[H])`.
3. Time symmetry: `(H − LS) / (RS − H)` within `[1/2.5, 2.5]`.
4. Neckline: anchors `n1 = argmax(high[LS+1..H−1])`, `n2 = argmax(high[H+1..RS−1])`, the rally peaks strictly between the anchors (a wick on a shoulder or head bar never becomes an anchor; consecutive swing lows are always more than 5 bars apart, so both interiors exist); `slope = (high[n2] − high[n1]) / (n2 − n1)`; `neck(i) = high[n1] + slope × (i − n1)`. Tilt test: `|slope × (RS − LS)| / close[H] ≤ 0.15`.
5. Prior decline: from the highest high of the 60 bars before LS down to `low[LS]` must be ≥ 10 % **of that high** (`(high − low[LS]) / high ≥ 0.10`), which is slightly stricter than "10 % above the shoulder low".
6. Confirmation: first bar `j > RS` with `close[j] > neck(j)`; trigger = `neck(j)`. Confirmed if `age ≤ MAX_BREAKOUT_AGE + 5`, the last close is still above `neck(n−1)` and not more than 5 % above the trigger. Watchlist if unbroken, last close ≥ 97 % of `neck(n−1)` and above `low[RS]`.

**Levels.** `stop = low[RS] − 0.25 × ATR[RS]`; `target = entry + (trigger − low[H])`.

**Score.** 50 + 15 × (1 − |LS − RS| / (0.5 × shallower depth)) + 10 × (1 − |ln ratio| / ln 2.5) + 10 × (1 − tilt / 0.15) + 5 if close > SMA200 + 5 × (1 − risk / 15) + 5 if volume ratio ≥ 1.3.

**Edge cases**

* RS is a swing low, so the pattern is first visible 5 bars after RS prints; that is why the age limit is 3 + 5 = 8 bars.
* A sloping neckline gives a trigger that moves every bar; `notes` reports both anchor values and the current neckline.
* A strong down-trend vetoes the whole detector before any triple is examined.

## Bullish Wolfe Wave (`detect_bullish_wolfe`)

**Search.** Every triple of consecutive swing lows (1, 3, 5) with `15 ≤ p5 − p1 ≤ 200` and point 5 within the last 25 bars:

1. Lower lows: `low[3] < low[1]`, `low[5] < low[3]`.
2. Points 2 and 4: the highest swing high strictly inside (1, 3) and (3, 5); both must exist. `high[4] < high[2]` and Wolfe's rule `low[1] < high[4] < high[2]`.
3. Slopes `s13 = (low[3] − low[1]) / (p3 − p1)`, `s24 = (high[4] − high[2]) / (p4 − p2)`; require `s24 < s13` (upper line falls faster, so the lines converge ahead).
4. Point 5 vs. the extended 1-3 line: `overshoot = line13(p5) − low[5]` must satisfy `−0.5 × ATR ≤ overshoot ≤ 2.0 × ATR` (touch or false breakdown, not a real breakdown).
5. Confirmation: first bar `j > p5` with `close[j] > line13(j)`; trigger = `line13(j)`. Confirmed if `age ≤ MAX_BREAKOUT_AGE + 5`, the last close is still above `line13(n−1)` and within 5 % of the trigger. Watchlist if unbroken, last close ≥ 97 % of `line13(n−1)` and above `low[5]`.

**Levels.** `stop = low[5] − 0.25 × ATR[5]`. ETA is where lines 1-3 and 2-4 meet: solving `v1 + s13 (x − p1) = v2 + s24 (x − p2)` gives `x = [(v2 − s24·p2) − (v1 − s13·p1)] / (s13 − s24)` (denominator positive). Target (EPA) = line 1-4 at the ETA, `v1 + s14 × (ETA − p1)`, reported only when the ETA lies after point 5 and within `WW_MAX_ETA_BARS` (250) of it, and the target is above the entry; otherwise `null`. Near-parallel lines would otherwise project the ETA, and the target, arbitrarily far out.

**Score.** 50 + 15 × (1 − |overshoot| / (2 ATR)) + 10 × (1 − |ln((p3 − p1)/(p5 − p3))| / ln 3) + 10 × (1 − risk / 15) + 5 if close > SMA200 + 5 if volume ratio ≥ 1.3.

**Edge cases**

* Point 5 is a swing low, so the setup is first visible 5 bars after it; with the default rebound the confirming close is typically already 5 bars old when reported, which is why the age limit is 8.
* If point 4 sits above point 2 or point 5 undercuts the line by more than 2 ATR the structure is rejected outright.
* `notes` includes `ETA ~date` only when the ETA bar falls inside the loaded history.

## What the negative controls establish

`test_patterns.py` and `test_scan.py` pin these facts: flat bars, a straight line and a seeded random walk produce nothing; on 200 random walks of 500 bars the three detectors fire on 1.5 % of series; each single-rule mutation of a textbook fixture (no prior advance, no handle, handle too deep, cup too shallow, rim mismatch, runaway, stale, below SMA200, symmetric V bottom; shallow head, asymmetric shoulders, strong down-trend; point 4 above 2, real breakdown, no rebound) is rejected; and an unadjusted 2:1 split breaks detection until `adjust_ohlc` restores the geometry.
