#!/usr/bin/env python3
"""Data-layer and end-to-end pipeline tests for scan.py (offline).

* Retry / rate-limit handling of the per-symbol download.
* Universe loading from a local CSV and the no-source failure mode.
* The full chain -- universe CSV -> history download (with one throttled
  symbol and one delisted symbol) -> last-bar alignment -> detection ->
  ``signals.json`` + ``report.md`` -- on a six-symbol mini universe, checking
  data integrity, output schema and report formatting.
"""

from __future__ import annotations

import json
import dataclasses
import urllib.error

import pandas as pd
import pytest

import scan
from test_scan import END


class Throttled(Exception):
    pass


# --------------------------------------------------------------------------- #
# Download retry policy
# --------------------------------------------------------------------------- #
def test_fetch_history_retries_transient_errors_with_backoff(fake_yfinance, cup_df):
    yf = fake_yfinance({"FLAKY": cup_df},
                       failures={"FLAKY": [Throttled("HTTP Error 429: Too Many Requests")] * 2})
    res = scan._fetch_history("FLAKY", "2y")
    assert res is not None and len(res[0]) == len(cup_df)
    assert yf.history_calls("FLAKY") == 3 and yf.sleeps == [5, 10]


def test_fetch_history_gives_up_after_three_attempts_without_a_final_sleep(fake_yfinance, cup_df):
    yf = fake_yfinance({"DEAD": cup_df}, failures={"DEAD": [Throttled("timed out")] * 3})
    assert scan._fetch_history("DEAD", "2y") is None
    assert yf.history_calls("DEAD") == 3 and yf.sleeps == [5, 10]   # no 15 s sleep after the last try


def test_fetch_history_does_not_retry_a_delisted_symbol(fake_yfinance):
    yf = fake_yfinance({})
    assert scan._fetch_history("GONE", "2y") is None
    assert yf.history_calls("GONE") == 1 and yf.sleeps == []


def test_download_history_skips_a_malformed_frame_instead_of_aborting(fake_yfinance, cup_df, caplog):
    broken = cup_df.reset_index(drop=True)              # integer index: no dates to normalise
    fake_yfinance({"BAD": broken, "OK": cup_df})
    with caplog.at_level("ERROR", logger="sp500scan"):
        out = scan.download_history(["BAD", "OK"], workers=1)
    assert set(out) == {"OK"} and "BAD: unusable history" in caplog.text


def test_download_history_keeps_the_rest_of_the_universe_after_failures(fake_yfinance, cup_df):
    yf = fake_yfinance({"FLAKY": cup_df, "DEAD": cup_df, "OK": cup_df},
                       failures={"FLAKY": [Throttled("429")], "DEAD": [Throttled("429")] * 3})
    out = scan.download_history(["FLAKY", "DEAD", "GONE", "OK"], workers=2)
    assert set(out) == {"FLAKY", "OK"}
    assert yf.history_calls("OK") == 1 and yf.history_calls("GONE") == 1
    assert sorted(yf.sleeps) == [5, 5, 10]


# --------------------------------------------------------------------------- #
# Universe loading
# --------------------------------------------------------------------------- #
def test_load_symbols_from_csv_handles_header_variants_and_junk(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("Ticker,Name\nbrk.b,Berkshire\n AAPL ,Apple\n,blank\nAAPL,dup\n")
    assert scan.load_sp500_symbols(str(p)) == ["AAPL", "BRK-B"]   # first column when no 'Symbol'; upper-cased


def test_load_symbols_rejects_an_oversized_download(monkeypatch):
    import io

    class Big(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(scan.urllib.request, "urlopen",
                        lambda *a, **k: Big(b"Symbol\n" + b"A\n" * (scan.CONSTITUENTS_MAX_BYTES // 2 + 1)))
    with pytest.raises(RuntimeError, match="exceeds"):
        scan.load_sp500_symbols()


def test_load_symbols_without_any_source_raises_and_warns_about_missing_csv(monkeypatch, tmp_path, caplog):
    def blocked(*a, **k):
        raise urllib.error.URLError("network policy")
    monkeypatch.setattr(scan.urllib.request, "urlopen", blocked)
    with pytest.raises(RuntimeError), caplog.at_level("WARNING", logger="sp500scan"):
        scan.load_sp500_symbols(str(tmp_path / "missing.csv"))
    assert "missing.csv not found" in caplog.text            # a wrong path never scans silently


# --------------------------------------------------------------------------- #
# End to end on the mini universe
# --------------------------------------------------------------------------- #
@pytest.fixture
def universe_csv(tmp_path):
    p = tmp_path / "universe.csv"
    p.write_text("Symbol,Security\nCUP,Cup Co\nIHS,Shoulders Inc\nWW,Wolfe Ltd\n"
                 "NOISE,Random Walk plc\nFLAT,Flatline SA\nGONE,Delisted Corp\n")
    return str(p)


def _run(tmp_path, universe_csv, extra=()):
    out = tmp_path / "out"
    rc = scan.main(["--csv", universe_csv, "--out-dir", str(out), *extra])
    data = json.loads((out / "signals.json").read_text()) if rc == 0 else None
    report = (out / "report.md").read_text() if rc == 0 else None
    return rc, data, report


def test_end_to_end_mini_universe(tmp_path, universe_csv, fake_yfinance, mini_universe):
    yf = fake_yfinance(mini_universe, failures={"WW": [Throttled("HTTP Error 429")]})
    rc, data, report = _run(tmp_path, universe_csv)
    assert rc == 0
    meta, signals = data["meta"], data["signals"]

    # Universe -> ingest: six listed, one delisted, one throttled once and recovered.
    assert (meta["universe"], meta["scanned"], meta["errors"]) == (6, 5, 1)
    assert yf.history_calls("WW") == 2 and yf.history_calls("GONE") == 1 and yf.sleeps == [5]
    assert meta["last_bar"] == END and meta["skipped_bar"] is None
    assert meta["last_bar_symbols"] == 5 and meta["lagging_symbols"] == 0
    assert meta["filled_close_symbols"] == 0
    assert meta["min_score"] == scan.MIN_SCORE and meta["max_breakout_age"] == scan.MAX_BREAKOUT_AGE

    # Detection: the three setups fire, the two controls stay silent.
    by_ticker = {s["ticker"]: s for s in signals}
    assert set(by_ticker) == {"CUP", "IHS", "WW"}
    assert {by_ticker[t]["pattern"] for t in by_ticker} == set(scan.BREAKOUT_AGE_LAG)

    # Schema and integrity of every signal.
    fields = [f.name for f in dataclasses.fields(scan.Signal)]
    for s in signals:
        assert list(s) == fields
        assert s["status"] in ("CONFIRMED", "WATCHLIST")
        assert isinstance(s["score"], int) and scan.MIN_SCORE <= s["score"] <= 100
        assert s["stop"] < s["entry"] and 0 < s["risk_pct"] <= 15
        assert s["target"] is None or s["target"] > s["entry"]
        assert s["last_date"] == END and s["notes"] and s["trend"]
        assert (s["bars_since_break"] is not None) == (s["status"] == "CONFIRMED")
        assert s["risk_pct"] == pytest.approx((s["entry"] - s["stop"]) / s["entry"] * 100, abs=0.02)
    # Sorted: confirmed first, then by score descending.
    keys = [(s["status"] != "CONFIRMED", -s["score"]) for s in signals]
    assert keys == sorted(keys)

    # Report formatting.
    assert report.startswith("# S&P 500 pattern scan — ")
    assert "Scanned 5 of 6 symbols" in report and f"last bar {END}" in report
    assert "Data errors: 1" in report
    n_conf = sum(s["status"] == "CONFIRMED" for s in signals)
    n_watch = len(signals) - n_conf
    assert f"## Confirmed breakouts (actionable): {n_conf}" in report
    assert f"## Watchlist (pattern complete, waiting for a close above trigger): {n_watch}" in report
    rows = [ln for ln in report.splitlines() if ln.startswith("| ") and not ln.startswith("| Ticker")]
    assert len(rows) == len(signals)
    for ln in rows:
        assert ln.count("|") == 13, ln                       # 12 columns
    by_row = {ln.split(" | ")[0].lstrip("| "): ln for ln in rows}
    for s in signals:                                        # Age column: bars/limit for confirmed, '-' otherwise
        cells = by_row[s["ticker"]].split(" | ")
        assert cells[8] == (f"{s['bars_since_break']}/{scan.max_breakout_age(s['pattern'])}"
                            if s["status"] == "CONFIRMED" else "-"), by_row[s["ticker"]]
        assert float(cells[3]) == s["max_buy"] and s["max_buy"] > s["entry"] * 0.99   # Max buy = trigger + 5 %
    assert "## Closed since the last report" in report and data["closed"] == []   # first run: nothing to close
    for s in signals:
        assert f"| {s['ticker']} | {s['pattern']} | {s['entry']} | {s['max_buy']} | {s['stop']} |" in report
    assert f"{scan.MAX_RUNAWAY:.0%} above the trigger" in report   # footer states the real rule


def _frame(*rows, start="2026-03-02"):
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame({"Open": [r[0] for r in rows], "High": [r[1] for r in rows],
                         "Low": [r[2] for r in rows], "Close": [r[3] for r in rows]}, index=idx)


def test_close_out_classifies_every_vanished_setup():
    prev = lambda t, status, entry=100.0, stop=95.0, target=110.0, age=1: {  # noqa: E731
        "ticker": t, "pattern": "Cup & Handle", "status": status, "entry": entry, "stop": stop,
        "target": target, "last_date": "2026-02-27", "bars_since_break": age if status == "CONFIRMED" else None}
    previous = [prev("HIT", "CONFIRMED"), prev("STOP", "CONFIRMED"), prev("BOTH", "CONFIRMED"),
                prev("OLD", "CONFIRMED", age=2), prev("FADE", "WATCHLIST"), prev("GONE", "WATCHLIST"),
                prev("STILL", "CONFIRMED"), prev("NODATA", "WATCHLIST"), prev("NOBARS", "WATCHLIST")]
    data = {
        "HIT": _frame((101, 104, 100, 103), (104, 111, 103, 108)),          # high reaches 110 on bar 2
        "STOP": _frame((100, 101, 96, 97), (97, 98, 93, 94.5)),             # close 94.5 <= 95 on bar 2
        "BOTH": _frame((100, 112, 90, 94)),                                 # touches both: stop wins
        "OLD": _frame((100, 102, 99, 101), (101, 103, 100, 102)),           # age 2 + 2 bars = 4 > limit 3
        "FADE": _frame((100, 101, 95.5, 96), (96, 97, 95.2, 94.0)),        # ends at or below the stop: FAILED
        "GONE": _frame((100, 101, 98, 99)),                                 # near the entry, no event
        "STILL": _frame((100, 101, 99, 100)),
        "NOBARS": _frame((100, 101, 99, 100), start="2026-02-27"),          # no bars after last_date
    }
    current = [scan.Signal("STILL", "Cup & Handle", "CONFIRMED", 100, 95, 5, 110, 70, 100, "2026-03-03",
                           2, None, "", "")]
    closed = {c["ticker"]: c for c in scan.close_out(previous, current, data)}
    assert "STILL" not in closed
    assert closed["HIT"]["outcome"] == "TARGET_REACHED" and "2026-03-03" in closed["HIT"]["detail"]
    assert closed["STOP"]["outcome"] == "FAILED" and "94.50" in closed["STOP"]["detail"]
    assert closed["BOTH"]["outcome"] == "FAILED"                              # same bar: conservative
    assert closed["OLD"]["outcome"] == "EXPIRED" and "4 bars old" in closed["OLD"]["detail"]
    assert closed["FADE"]["outcome"] == "FAILED"                              # 94.0 <= stop 95: stop before fade
    assert closed["GONE"]["outcome"] == "DROPPED" and closed["GONE"]["detail"] == "pattern no longer qualifies"
    assert closed["NODATA"]["outcome"] == "DROPPED" and closed["NODATA"]["detail"] == "no price data"
    assert closed["NOBARS"]["outcome"] == "DROPPED" and "no bars" in closed["NOBARS"]["detail"]
    # A genuine fade: close 6 % below the entry but above the stop.
    faded = scan.close_out([prev("F2", "WATCHLIST", entry=100.0, stop=90.0)], [], {"F2": _frame((100, 101, 94, 94))})
    assert faded[0]["outcome"] == "FADED" and "5%" in faded[0]["detail"]


def test_second_run_reports_what_happened_to_yesterdays_rows(tmp_path, universe_csv, fake_yfinance, mini_universe):
    fake_yfinance(mini_universe)
    rc, first, _ = _run(tmp_path, universe_csv)
    assert rc == 0 and first["closed"] == []
    cup_target = next(s["target"] for s in first["signals"] if s["ticker"] == "CUP")
    # Three more sessions for everyone; CUP spikes through its target on the first of them.
    later = {}
    for sym, df in mini_universe.items():
        last = df.iloc[-1]
        extra = pd.DataFrame({c: [last[c]] * 3 for c in df.columns},
                             index=pd.bdate_range(df.index[-1], periods=4)[1:])
        if sym == "CUP":
            extra.loc[extra.index[0], "High"] = cup_target * 1.01
        later[sym] = pd.concat([df, extra])
    fake_yfinance(later)
    rc, second, report = _run(tmp_path, universe_csv)
    assert rc == 0 and second["meta"]["previous_run"] == first["meta"]["run_date"]
    closed = {c["ticker"]: c for c in second["closed"]}
    assert "CUP" in closed and closed["CUP"]["outcome"] == "TARGET_REACHED" and closed["CUP"]["was"] == "CONFIRMED"
    assert "## Closed since the last report" in report
    assert "| CUP | Cup & Handle | CONFIRMED | TARGET_REACHED | " in report


def test_end_to_end_min_score_filters_and_is_reported(tmp_path, universe_csv, fake_yfinance, mini_universe):
    fake_yfinance(mini_universe)
    scores = {sym: max(s.score for s in scan.scan_symbol(sym, df)) for sym, df in mini_universe.items()
              if scan.scan_symbol(sym, df)}
    cut = max(scores.values())                                   # keep only the best-scoring setup
    rc, data, _ = _run(tmp_path, universe_csv, ["--min-score", str(cut)])
    assert rc == 0 and data["meta"]["min_score"] == cut and data["meta"]["profile"] == "spec"
    assert all(s["score"] >= cut for s in data["signals"])
    assert {s["ticker"] for s in data["signals"]} == {t for t, v in scores.items() if v >= cut}
    assert len(data["signals"]) < len(scores)                    # something was filtered


def test_end_to_end_is_deterministic(tmp_path, universe_csv, fake_yfinance, mini_universe):
    fake_yfinance(mini_universe)
    _, first, _ = _run(tmp_path / "a", universe_csv)
    _, second, _ = _run(tmp_path / "b", universe_csv)
    assert first["signals"] == second["signals"]
    assert {k: v for k, v in first["meta"].items() if k != "run_date"} == \
           {k: v for k, v in second["meta"].items() if k != "run_date"}


def test_end_to_end_exit_code_2_when_nothing_downloads(tmp_path, universe_csv, fake_yfinance):
    fake_yfinance({})                                           # every symbol "delisted"
    rc, data, report = _run(tmp_path, universe_csv)
    assert rc == 2 and data is None and not (tmp_path / "out").exists()
