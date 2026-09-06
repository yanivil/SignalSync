# Architecture and Data Pipeline

SignalSync is a single Python module, `scan.py`, organised top to bottom as: tunable constants → `Signal` data class → universe and data loading → indicators and pivots → three detectors → orchestration and reporting → CLI. This page covers everything up to the detectors; the detectors are in [Pattern Catalog](02-Pattern-Catalog.md).

```
load_sp500_symbols ─► download_history ─► align_last_bar ─► scan_symbol (×N) ─► render_markdown / signals.json
                        │
                        ├─ _fetch_history      one yfinance chart request per symbol, retried
                        ├─ fill_missing_close  newest close from the last-trade quote
                        ├─ adjust_ohlc         split / dividend ratio
                        └─ NaN cleaning        trailing rows without a close → "partial bars"
```

## 1. Universe

`load_sp500_symbols(csv_path=None)`

* **Source priority:** a local CSV passed with `--csv` (any file with a `Symbol` column, or the first column as a fallback), otherwise the public dataset `datasets/s-and-p-500-companies` on GitHub.
* **Pinned, not floating.** The dataset is fetched from a fixed commit (`CONSTITUENTS_COMMIT`, currently 2026-08-20) rather than `main`, so an upstream change or compromise cannot silently alter the scanned universe. To pick up index changes, review the upstream diff and bump the commit hash.
* **Normalisation:** whitespace stripped, dots replaced by dashes (`BRK.B` → `BRK-B`, Yahoo's convention), de-duplicated and sorted. The symbol case is preserved as given.
* **Failure mode:** if neither source is readable, `RuntimeError` is raised and the process exits non-zero. A CSV path that does not exist falls through to the network silently (with a warning only if the download also fails).

## 2. Ingestion

`download_history(symbols, period="2y", workers=8, now=None)`

Each symbol is fetched with `yfinance.Ticker(sym).history(period, interval="1d", auto_adjust=False, actions=False)` on a thread pool of 8 workers. Per-symbol `Ticker.history` is used instead of the batched `yf.download` because it exposes the chart metadata (`get_history_metadata()`) that the close-filling step needs; yfinance issues one chart request per symbol either way.

### Throttling and retries

| Situation | Behaviour |
|---|---|
| Transient error (HTTP 429, 5xx, timeout, any other exception) | retried up to 3 attempts with a linear back-off of 5 s then 10 s; no sleep after the final failure |
| Error text contains "delisted" or "no data", or the exception type contains "Missing" | final: symbol skipped immediately, no retry |
| All attempts fail | symbol skipped, counted in `meta.errors`; the rest of the universe continues |

There is **no client-side rate limiter** beyond the worker count and the back-off. In practice 8 threads over ~500 symbols complete within the 30-minute job timeout on GitHub runners. If Yahoo tightens throttling, the first knob is `workers` (a function argument; the CLI uses the default).

### Caching

There is **no persistent price cache**. Every run downloads the full history for every symbol. The only caching in the system is GitHub Actions' pip cache for dependencies. A local cache was deliberately not built: the scan runs once a day on a fresh runner, and stale-cache bugs would be worse than the ~1 minute of downloads.

### Per-symbol cleaning, in order

1. **`fill_missing_close(df, meta)`** — after the US close, Yahoo's chart row for that session has open/high/low/volume but a null close (and adjusted close) until about 08:00 UTC the next day. The chart *quote* fields already carry the closing print (`regularMarketPrice` at `regularMarketTime`, 16:00 New York). If the newest row lacks a close, the last trade falls on that row's date, and the trade is at least `FILL_CLOSE_MIN_AGE` (1 h) old (so a live intraday tick is never mistaken for a close), the price is written as the close; High/Low are widened to include it, a missing Open is set to it. `meta.filled_close_symbols` counts symbols completed this way.
2. **`adjust_ohlc(df)`** — multiplies Open/High/Low/Close by `Adj Close / Close`, treating a missing ratio as 1.0. yfinance's own `auto_adjust=True` would blank the whole newest row when `adjclose` is not yet published; nothing later can have adjusted the newest bar, so 1.0 is correct by definition. Volume is never rescaled.
3. **Index normalisation** — `Ticker.history` indexes in exchange time (America/New_York); the index is made tz-naive and normalised to midnight so date comparisons downstream are consistent.
4. **NaN handling** — rows without a close are dropped. Trailing rows dropped this way (Yahoo's not-yet-published bar) are recorded in `df.attrs["partial_bars"]`; interior holes are dropped silently. Detectors are positional, so a missing bar shifts nothing except pivot windows.
5. **Minimum history** — fewer than 60 remaining bars → symbol skipped (counted in `meta.errors`).

## 3. Which bar is scanned

`align_last_bar(data, min_fraction=0.5)`

Yahoo publishes the newest daily bar per symbol at different times (volume first, prices later), so scanning each symbol on "whatever it has" would produce a report whose headline date is the newest date *any* symbol reached while most signals were computed on the previous close. Instead:

* `last_bar` = the newest date on or after which at least `LAST_BAR_MIN_FRACTION` (50 %) of symbols have a complete bar — the majority's newest complete bar.
* Symbols with bars **newer** than `last_bar` are truncated to it so every signal is comparable. The dropped date is reported as `skipped_bar` with counts of how many symbols had it complete (`skipped_bar_complete`) and how many had only Yahoo's volume-only row (`skipped_bar_partial`).
* Symbols whose newest complete bar is **older** than `last_bar` (halted, late) are scanned as they are and counted in `lagging_symbols`; their signals carry their own `last_date`.

`meta.last_bar_histogram` gives the newest-complete-bar date per symbol before alignment. `tools/debug_last_bar.py` (also runnable as the `debug-last-bar` GitHub workflow) prints the per-symbol detail, raw last rows and a dry-run scan.

## 4. Output contract

`output/signals.json`:

```json
{"meta": {"run_date": "2026-09-04 08:25", "universe": 503, "scanned": 502, "errors": 1,
          "last_bar": "2026-09-03", "last_bar_symbols": 502, "lagging_symbols": 0,
          "skipped_bar": null, "skipped_bar_complete": 0, "skipped_bar_partial": 0,
          "last_bar_histogram": {"2026-09-03": 502}, "filled_close_symbols": 0,
          "profile": "spec", "min_score": 60, "max_breakout_age": 3,
          "max_breakout_age_by_pattern": {"Cup & Handle": 3, "Inverse Head & Shoulders": 8, "Bullish Wolfe Wave": 8},
          "min_reward_risk": null, "max_wait_bars": null, "max_buy_risk_mult": 1.5,
          "previous_run": "2026-09-03 08:25", "previous_profile": "spec"},
 "signals": [{"ticker": "CL", "pattern": "Bullish Wolfe Wave", "status": "CONFIRMED",
              "entry": 90.09, "stop": 88.67, "risk_pct": 1.58, "target": 107.98, "score": 84,
              "last_close": 90.09, "last_date": "2026-09-03", "bars_since_break": 8,
              "volume_ratio": 0.97, "trend": "close above SMA200, SMA50 > SMA200, SMA200 rising/flat",
              "notes": "1 2026-07-23 @89.25, ... 5 2026-08-21 @89.16; line 1-3 now 88.95"}]}
```

| Field | Meaning |
|---|---|
| `status` | `CONFIRMED` (a close broke the trigger within the per-pattern age limit, today's close is still above it, and the breakout bar had the required volume) or `WATCHLIST` (pattern complete, close at or below the trigger but within 5 % of it, whether it never broke out or broke out and pulled back; or a breakout close without the required volume, marked "breakout without volume" in `notes`) |
| `entry` | the trigger level, or the breakout close when it is above the trigger (closes more than 5 % above are dropped as chasing) |
| `stop` | structural level minus 0.25 ATR(14). A level, not an order type: the backtest scores it as an intraday touch; the year-long grid shows exiting on a close at or below it instead lifts mean R (tuned profile +0.30 → +0.35), so the choice of a resting order versus a close-based mental stop is the trader's |
| `risk_pct` | `(entry − stop) / entry × 100`; setups above 15 % are rejected |
| `target` | measured-move reference; `null` for a Wolfe whose lines do not converge ahead |
| `score` | 0–100 quality score, minimum `min_score` |
| `bars_since_break` | 0 = the confirming close is the last bar; `null` for watchlist rows |
| `volume_ratio` | breakout-day volume / trailing 50-bar average; `null` when unavailable |
| `notes` | anchor dates and levels used by the detector (parseable, see tests); "breakout without volume (x.xx×)" when a breakout was watch-listed for lack of volume |
| `max_buy` | the open above which the setup no longer qualifies: the lower of trigger × 1.05 (the runaway rule applied to the open) and `stop + MAX_BUY_RISK_MULT × (entry − stop)`, the fill at which the risk reaches 1.5× the planned risk. The second cap binds for tight structural stops (Wolfe point 5, shallow handles); the first for wide ones (H&S shoulders) |
| `reward_risk` | `(target − entry) / (entry − stop)` at the reported entry, 2 decimals; `null` without a target. Rows below `MIN_REWARD_RISK` (when set) are not reported. It falls as the entry drifts above the trigger, so a late confirmed row can show a poor R:R on an otherwise clean pattern |

Signals are sorted `CONFIRMED` first, then by score descending. `output/report.md` renders the same rows as two Markdown tables (Ticker, Pattern, Entry, Max buy, Stop, Risk %, Target, R:R, Score, Age, Vol×, Trend, Details) with a header stating the scanned bar, effective age limits, skipped/lagging counts and data errors. **Age** is `bars_since_break / limit`, e.g. `1/3` for a cup that broke out yesterday and will be dropped after two more sessions; `-` for watchlist rows.

**Closed since the last report.** A stateless scan only knows what qualifies today, so each run also reads the previous committed `signals.json` (the nightly job has it in the checkout) and explains every row that disappeared, using the bars since that row's `last_date`. The list is `closed` in `signals.json` (ticker, pattern, was, since, entry, stop, target, outcome, detail) and a third table in the report; `meta.previous_run` names the report it was compared with.

| Outcome | Rule |
|---|---|
| `TARGET_REACHED` | a high at or above the target |
| `FAILED` | a close at or below the stop (the spec's invalidation; a bar touching both levels counts as FAILED) |
| `EXPIRED` | a confirmed breakout aged past `max_breakout_age` |
| `FADED` | the close fell more than `WATCH_PROXIMITY` (5 %) below the entry |
| `DROPPED` | none of the above: the pattern itself no longer qualifies, or no price data. When one of today's reward or patience rules would reject the old row on its own levels and anchors, the detail says so ("reward:risk 0.36 below the minimum 1.5", "no breakout within 60 bars of the right shoulder on 2026-01-29 (156 bars)") |

## 5. Scheduling

```
GitHub Actions (01:17 UTC daily, main only)      Claude desktop scheduled task (08:45 Israel time, daily)
  checkout → pip install → pytest -q              fetch raw output/signals.json + report.md from GitHub
  python scan.py -v (open internet)               fresh? run_date is today and last_bar is the last US session
  commit output/report.md + signals.json          e-mail the Confirmed / Watchlist tables via Gmail
```

* The scan runs on GitHub because the Claude environments sit behind a network policy that blocks market-data hosts; GitHub and PyPI are reachable from both. The repo must stay public (or the task needs a token) for `raw.githubusercontent.com` to serve the report.
* Exit code 2 (no data) is captured, still committed if the files changed, and then fails the job so the failure is visible.
* The cron is deliberately off the top of the hour: GitHub delays scheduled workflows most at :00 (on 2026-09-05 the 02:00 run started at 06:36 UTC, after the e-mail had already gone out flagged STALE). Delays can still happen; the STALE flag in the e-mail is the safety net.
* Delivery is a scheduled task in the Claude desktop app on the user's Mac (`signalsync-daily-email`, 08:45 local time). Its cron runs in local time, so the Israel clock change needs no adjustment. It only fires while the desktop app is open; if the app is closed at 08:45 the run happens at the next launch. A stale report (older run, or `last_bar` not the previous US session) is sent with a "STALE" prefix rather than silently. Weekend runs re-send Friday's session marked "Weekend".
* Dependabot keeps the pinned action SHAs and Python lower bounds current (weekly).
