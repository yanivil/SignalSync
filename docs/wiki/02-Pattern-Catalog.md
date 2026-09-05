# Pattern Catalog

Every detector works on positional daily bars (`High`, `Low`, `Close` as numpy arrays), shares the same primitives, and returns `Signal` records de-duplicated to the best score per `(ticker, pattern, status)`. All thresholds are module constants; the values below are the **spec** rule profile (the engine specification adopted on 2026-09-05). Where the previous rules differed, the **legacy** value is given in brackets; both profiles are selectable with `--profile` and are replayed side by side by the backtest. See [Configuration and Tuning](03-Configuration-and-Tuning.md) for the full table.

## Shared primitives

| Primitive | Definition | Notes |
|---|---|---|
| ATR | simple rolling mean of true range over `ATR_LEN` = 14 bars, `min_periods=1` | bar 0 is High − Low; a flat series has ATR 0 |
| Swing high / low (`find_pivots`) | bar *i* is a swing high if `high[i]` is the maximum of `[i−5, i+5]` **and** the first maximum in that window; swing lows likewise on `low` | O(n · order). The last 5 bars can never be pivots (no repainting), so any pattern whose last anchor is a pivot is seen up to 5 bars late. Flat stretches produce no pivots because the tie goes to the window's first bar. |
| Trend context | `uptrend` = close > SMA200; `strong_downtrend` = close < 0.90 × SMA200 **and** SMA200 below its value 40 bars earlier. With fewer than 200 bars, or when the SMA200 exists but not 40 bars ago (200–239 bars): close < 0.85 × SMA50, deliberately with **no** slope test, because such short histories may not have a 40-bar-old SMA50 either; the stricter level (15 % instead of 10 %) compensates. | spec: informational only (score bonus for close above SMA200). Legacy: the cup required `uptrend` and reversal patterns were vetoed by `strong_downtrend`. |
| SMA filter (`_sma_pair`) | last SMA50 and SMA200 of the close | spec trend filters: SMA50 > SMA200 satisfies the cup's prior-uptrend requirement on its own; SMA50 < SMA200 satisfies the H&S prior-downtrend requirement on its own |
| Breakout state (`evaluate_breakout`) | shared by all three detectors; the trigger is a function of the bar, so sloping necklines and Wolfe lines use the same evaluator. `age` = bars since the **first** close above the trigger after the pattern completed | last close above today's trigger: `CONFIRMED` if `age ≤ MAX_BREAKOUT_AGE + lag` and the close is not more than 5 % above the trigger at that first break, else `STALE`. Last close at or below today's trigger: `WATCHLIST` if within 5 % of it and above the pattern's floor (right-shoulder low, point 5; none for the cup), else `STALE`. A pull-back below the trigger therefore keeps the setup on the watchlist; a re-break inside the age window is still confirmed, one after it is stale. The clock deliberately does not restart on a re-break: on synthetic noise that raised the confirmed false-positive rate from about 1 % to 5 % of series. |
| Volume confirmation (`_volume_confirmed`) | breakout-bar volume / mean of the `VOLUME_AVG_LEN` = 20 [50] bars before it | spec: a breakout close is `CONFIRMED` only with ≥ 1.4× (cup) or ≥ 1.3× (H&S) average volume; otherwise the row is kept on the watchlist with the note "breakout without volume". Wolfe has no volume requirement. Legacy: volume was a +5 score bonus only. A ratio ≥ 1.3 always adds +5 to the score. |
| Risk filter | `risk_pct = (entry − stop) / entry × 100`; rejected if `stop ≥ entry` or `risk_pct > MAX_RISK_PCT[pattern]` | 12 % for the cup [15 %], 15 % for H&S and Wolfe |
| Max buy | `trigger × (1 + MAX_RUNAWAY)` | reported per row: an open above it is the same runaway condition that drops a close, so the setup no longer qualifies |
| Close-out (`close_out`) | rows in the previous report that are absent today are classified as `TARGET_REACHED`, `FAILED` (close at or below the stop), `EXPIRED`, `FADED` or `DROPPED` | the spec's `FAILED` / `TARGET_REACHED` lifecycle states, reconstructed from the previous committed report; see the output contract in [Architecture](01-Architecture-and-Data-Pipeline.md) |

Entry is the breakout close when it is above the trigger (and within 5 % of it), otherwise the trigger itself (watchlist rows). Either way it is the previous session's close: a trade placed after the morning report fills at the next US open, so the reported risk % and target are estimates, and a gap-up past 5 % over the trigger is the same "runaway" condition that would have filtered the setup.

## Summary table

| Pattern | Anchors | Width (bars) | Core geometric tests | Trigger | Stop | Target |
|---|---|---|---|---|---|---|
| Cup & Handle | swing highs A, B; lowest low between; handle after B | 20–300 cup [30–250], 5–25 handle [5–40] and never longer than the cup | rim B within 15 % of the cup depth of A [5 % of price]; depth 12–50 % of A and ≤ 50 % of the preceding advance; bottom in the middle 50 % [60 %]; SMA50 > SMA200 or ≥ 20 % rise over the prior 60 bars [≥ 25 % over 120 bars and close > SMA200]; convex-quadratic R² ≥ 0.70 [0.60] and ≥ the best V fit; handle ≤ 12 % deep, ≤ ½ cup depth, above the cup midpoint | close > handle high on ≥ 1.4× volume | handle low − 0.25 ATR | entry + (B − bottom) [A − bottom] |
| Inverse H&S | consecutive swing lows LS, H, RS; neckline through the highest high between each pair | 20–200 | H ≥ 1 ATR below both shoulders; shoulder gap ≤ 30 % of the head height [≤ 50 % of the shallower shoulder depth]; sides LS→N1 and N2→RS within ±40 % [half-widths within 2.5×]; neckline tilt ≤ 15 % of price over the width; SMA50 < SMA200 or a decline ≥ one head height into LS [≥ 10 % decline]; no down-trend veto [vetoed in a strong down-trend] | close > neckline on ≥ 1.3× volume | RS − 0.25 ATR | entry + (neckline at the head bar − H) [neckline at the break bar − H] |
| Bullish Wolfe Wave | swing lows 1, 3, 5; swing highs 2, 4 | 15–200 (1→5), 5 within the last 25 bars | 3 < 1, 5 < 3, 4 < 2, 1 < 4 < 2; line 2-4 falls faster than 1-3 (converging); point 5 below line 1-3 **and** above the line through point 3 parallel to 2-4 (the "sweet zone") [within −0.5 … +2 ATR of line 1-3]; legs 1→2, 2→3, 3→4 within ±30 % of their mean [scored only]; no down-trend veto [vetoed] | close > line 1-3 after point 5 | point 5 − 0.25 ATR | line 1-4 at the ETA, if within 250 bars and not more than +100 % above the entry |

## Cup & Handle (`detect_cup_and_handle`)

**Trend filter.** The cup is a continuation base, so the stock must have advanced into rim A. Spec: `SMA50 > SMA200` at the scan date satisfies the filter on its own; otherwise the rise from the lowest low of the `CUP_PRIOR_LOOKBACK` = 60 bars before A to `high[A]` must be ≥ `CUP_PRIOR_ADVANCE` = 20 % (a rise from the low, not "20 % below the rim"). Legacy required a close above the SMA200 and a ≥ 25 % rise over 120 bars, with no SMA alternative.

**Search.** For each pair of swing highs (A, B) with `20 ≤ B − A ≤ 300` (the inner loop breaks once the width exceeds the maximum, so cost is O(P² · W) worst case, P = swing highs, W = cup width):

1. Depth: bottom = lowest low in `[A, B]`; `depth = (high[A] − bottom) / high[A]` in `[0.12, 0.50]`. The spec is silent on a minimum; 12 % is ours.
2. Rims: `|high[B] − high[A]| ≤ CUP_RIM_TOL_OF_DEPTH × (high[A] − bottom)`, i.e. within 15 % of the cup depth [legacy: within 5 % of the price].
3. Bottom position: `(idx − A) / (B − A)` in `[0.25, 0.75]` [0.20, 0.80].
4. Rollback: the decline `high[A] − bottom` may not exceed `CUP_MAX_RETRACE` = 50 % of the preceding advance, measured from the lowest low of the `CUP_ADVANCE_LOOKBACK` = 250 bars before A to `high[A]`. The spec does not say over what window the "preceding uptrend move" is measured; a year is our interpretation, so that a long, gradual advance counts. Legacy had no rollback rule.
5. Roundness: `R²` of a convex (a > 0) quadratic least-squares fit of the lows over `[A, B]` must be ≥ 0.70 [0.60]. An arch (a ≤ 0) scores 0.
6. U versus V: the best two-legged fit `a + b·|x − c|` (b > 0, vertex `c` searched within ±10 % of the width around the lowest low) may not beat the parabola's R² by more than `CUP_MAX_V_ADVANTAGE` (0). On reference shapes the parabola wins by +0.04 on a half-sine, +0.37 on a flat dish and +0.01 on a lopsided sine, and loses by 0.06 on a clean V, so a sharp reversal is rejected while any rounded or flat base passes.
7. Handle (`_find_handle`): runs from `B+1` to the bar before the first close above the handle's running high, capped at `min(HANDLE_MAX_LEN = 25, cup width)` bars [40, no cup-relative cap] or the end of data, and must last ≥ 5 bars (a close above the running high within the first 5 bars is still "the handle forming"). Handle depth `(high[B] − handle_low) / high[B]` ≤ 0.12, ≤ 0.50 × cup depth, and the handle low must stay above `bottom + 0.5 × (high[B] − bottom)`.
8. Trigger = the handle's highest high, which is O'Neil's buy point (the handle peak, not the cup rim: a handle normally sits below the rim, and waiting for the rim is a later, more conservative entry). Confirmation is scanned from the bar after the handle ends. Rim B is a swing high, so no bar within 5 of it can exceed it, but a wick above B later in the handle (a bar whose high spikes but whose close stays below the running handle high) raises the trigger above the rim; the setup then needs a close above that wick, which is conservative and usually leaves it on the watchlist.
9. Volume: the confirming close needs ≥ 1.4× the 20-bar average volume; without it the row stays on the watchlist with the note "breakout without volume (x.xx×)".

**Levels.** `stop = handle_low − 0.25 × ATR[handle_low]`; `target = entry + (high[B] − bottom)` (spec: bottom to the right rim) [legacy: `high[A] − bottom`; Investopedia: bottom to the handle breakout level, available in the backtest as the `breakout` target variant]. Risk over 12 % is rejected [15 %].

**Score.** 50 + 15 × (R² − 0.70)/(1 − 0.70) + 10 × (1 − |depth − 0.25| / 0.25) + 10 × (1 − handle_depth / 0.12) + 10 × (1 − risk / 12) + 5 if volume ratio ≥ 1.3, clipped to 0–100.

**Edge cases and known behaviour**

* The roundness R² alone would pass a clean symmetric V (a parabola explains `|x|` with R² ≈ 0.93); the U-versus-V comparison is what rejects it. The threshold is calibrated on reference shapes (`test_patterns.py::test_v_shape_r2_separates_rounded_bases_from_sharp_reversals`), not on market data, so watch the first live runs for cups that disappear from the report and revisit `CUP_MAX_V_ADVANTAGE` if rounded bases are being lost.
* Under the spec profile the SMA50 > SMA200 alternative is easy to satisfy after any cup, so the prior-advance rise rarely decides; the rollback rule is what limits depth relative to the advance. A 25 %-deep cup needs a preceding advance of at least twice its depth.
* A single wick spike inside the handle (e.g. a −20 % low) fails the handle depth rule; a spike inside the cup body fails the position/roundness rules; spikes before the pattern are irrelevant.
* Zero-volume sessions never invalidate a cup, but a zero-volume breakout bar cannot confirm it (watchlist instead).
* Missing interior bars shift nothing: detectors are positional. Levels are unchanged when rows are removed, the roundness score may move slightly.
* Because the cup's last anchor (the handle low) needs no right-side confirmation, the cup gets **no** extra breakout-age tolerance (`BREAKOUT_AGE_LAG` = 0).

## Inverse Head & Shoulders (`detect_inverse_hs`)

**Trend filter.** A reversal needs something to reverse. Spec: `SMA50 < SMA200` at the scan date satisfies it on its own; otherwise the decline from the highest high of the 60 bars before LS to `low[LS]` must be at least one head height. The spec has no strong-down-trend veto (reversals form in down-trends by definition); legacy vetoed the pattern when the close was 10 % below a falling SMA200 and required a ≥ 10 % decline measured as a share of the prior high.

**Search.** Every triple of consecutive swing lows (LS, H, RS) with `20 ≤ RS − LS ≤ 200` (cost O(L · (W + n))):

1. Head depth: `low[H] < low[LS] − 1.0 × ATR[H]` and `low[H] < low[RS] − 1.0 × ATR[H]` (the spec only asks for "strictly lower"; the ATR margin is ours).
2. Half-width sanity: `(H − LS) / (RS − H)` within `[1/2.5, 2.5]`.
3. Neckline: anchors `n1 = argmax(high[LS+1..H−1])`, `n2 = argmax(high[H+1..RS−1])`, the rally peaks strictly between the anchors (a wick on a shoulder or head bar never becomes an anchor; consecutive swing lows are always more than 5 bars apart, so both interiors exist); `slope = (high[n2] − high[n1]) / (n2 − n1)`; `neck(i) = high[n1] + slope × (i − n1)`. Tilt test: `|slope × (RS − LS)| / close[H] ≤ 0.15`. The spec states slope limits in degrees, which have no meaning without a fixed chart scale; this is the scale-free form.
4. Head height (spec): `neck(H) − low[H]`, the neckline read at the head bar.
5. Shoulder symmetry (spec): `|low[LS] − low[RS]| ≤ 0.30 × head height` [legacy: ≤ 0.50 × the shallower shoulder depth].
6. Side symmetry (spec): the durations `n1 − LS` and `RS − n2` must be within ±40 % of each other: `|left − right| / max(left, right) ≤ 0.40` [legacy: no such rule].
7. Prior decline: see the trend filter above.
8. Confirmation via `evaluate_breakout` with `neck(j)` as the trigger, from `RS + 1`, floor `low[RS]`: first close above the neckline after RS sets the clock, `age ≤ MAX_BREAKOUT_AGE + 5`, trigger = `neck` at that bar; otherwise watchlist within 5 % of `neck(n−1)` while above the right-shoulder low.
9. Volume: the confirming close needs ≥ 1.3× the 20-bar average volume; otherwise the row is watch-listed with the note "breakout without volume".

**Levels.** `stop = low[RS] − 0.25 × ATR[RS]`; `target = entry + head height` (spec: neckline at the head bar minus head) [legacy: neckline at the break bar minus head; identical for a flat neckline].

**Score.** 50 + 15 × (1 − |LS − RS| / (0.30 × head height)) + 10 × (1 − |ln ratio| / ln 2.5) + 10 × (1 − tilt / 0.15) + 5 if close > SMA200 + 5 × (1 − risk / 15) + 5 if volume ratio ≥ 1.3.

**Edge cases**

* RS is a swing low, so the pattern is first visible 5 bars after RS prints; that is why the age limit is 3 + 5 = 8 bars.
* A sloping neckline gives a trigger that moves every bar; `notes` reports both anchor values and the current neckline.
* The spec's pivots N1 and N2 are required to be swing highs; we take the highest high of each interior, which is the same bar whenever a swing high exists there and is defined even when the rally is too short to form one.

## Bullish Wolfe Wave (`detect_bullish_wolfe`)

**Search.** Every triple of consecutive swing lows (1, 3, 5) with `15 ≤ p5 − p1 ≤ 200` and point 5 within the last 25 bars:

1. Lower lows: `low[3] < low[1]`, `low[5] < low[3]`.
2. Points 2 and 4: the highest swing high strictly inside (1, 3) and (3, 5); both must exist. `high[4] < high[2]` and the channel rule `low[1] < high[4] < high[2]` (Investopedia: waves 3 and 4 stay inside the channel of waves 1 and 2). The engine spec's ordering `P2 > P1 > P4 > P3 > P5` would put point 4 *below* point 1; both readings exist in the Wolfe literature and the code follows the channel rule.
3. Slopes `s13 = (low[3] − low[1]) / (p3 − p1)`, `s24 = (high[4] − high[2]) / (p4 − p2)`; require `s24 < s13 < 0` (upper line falls faster, so the lines converge ahead). The engine spec writes this inequality the other way round, which would make the lines diverge; the code follows the geometry.
4. Sweet zone (spec): point 5 must penetrate below line 1-3 (`line13(p5) − low[5] ≥ 0`) **and** hold above the line through point 3 parallel to line 2-4: `low[5] ≥ low[3] + s24 × (p5 − p3)`. A close below that auxiliary line is a real breakdown, not a Wolfe false break. [Legacy: `overshoot` within −0.5 … +2 ATR of line 1-3.]
5. Rhythm (spec): legs 1→2, 2→3 and 3→4 must each be within ±30 % of their mean [legacy: scored, not required].
6. Confirmation via `evaluate_breakout` with `line13(j)` as the trigger, from `p5 + 1`, floor `low[5]`: first close back above line 1-3 after point 5 sets the clock, `age ≤ MAX_BREAKOUT_AGE + 5`, trigger = the line at that bar; otherwise watchlist within 5 % of `line13(n−1)` while above point 5. No volume requirement.

**Levels.** `stop = low[5] − 0.25 × ATR[5]`. ETA is where lines 1-3 and 2-4 meet: solving `v1 + s13 (x − p1) = v2 + s24 (x − p2)` gives `x = [(v2 − s24·p2) − (v1 − s13·p1)] / (s13 − s24)` (denominator positive). Target (EPA) = line 1-4 at the ETA, `v1 + s14 × (ETA − p1)`, reported only when the ETA lies after point 5 and within `WW_MAX_ETA_BARS` (250) of it, and the target is above the entry but not more than `WW_MAX_TARGET_GAIN` (+100 %) above it; otherwise `null`. Near-parallel lines would otherwise project the ETA, and the target, arbitrarily far out.

**Score.** 50 + 15 × (1 − |overshoot| / (2 ATR)) + 10 × (1 − |ln((p3 − p1)/(p5 − p3))| / ln 3) + 10 × (1 − risk / 15) + 5 if close > SMA200 + 5 if volume ratio ≥ 1.3.

**Edge cases**

* Point 5 is a swing low, so the setup is first visible 5 bars after it; with the default rebound the confirming close is typically already 5 bars old when reported, which is why the age limit is 8.
* Investopedia's entry is at point 5 itself; ours waits for the close back above line 1-3, which enters later against the same stop. The backtest's stop-distance grid exists to quantify that trade-off.
* `notes` includes `ETA ~date` only when the ETA bar falls inside the loaded history.

## What the negative controls establish

`test_patterns.py` and `test_scan.py` pin these facts: flat bars, a straight line and a seeded random walk produce nothing; on 200 Gaussian and 200 Student-t random walks of 500 bars the spec profile confirms nothing and watch-lists 4 and 3 series (legacy: 2 and 1 confirmed, 7 and 5 watch-listed); each single-rule mutation of a textbook fixture (no handle, handle too deep, cup too shallow, rim mismatch, runaway, stale, symmetric V bottom, rollback beyond half the advance, breakout without volume; shallow head, asymmetric shoulders; point 4 above 2, real breakdown, no rebound) is rejected; a W-shaped base is never a cup across its full span; and an unadjusted 2:1 split breaks detection until `adjust_ohlc` restores the geometry.
