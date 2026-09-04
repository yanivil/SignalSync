#!/usr/bin/env python3
"""
Synthetic-data tests for scan.py.

Why synthetic: the development sandbox has no market-data access, so each
detector is exercised on a hand-built price path containing exactly one
textbook instance of its pattern, plus a random-walk sweep to measure how often
the detectors fire on noise (rule 1: don't force patterns).

Run:  python3 -m pytest test_scan.py -q      or      python3 test_scan.py
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pandas as pd

import scan

# All synthetic series end on the same business day, as real symbols do; the
# last-bar alignment in scan.main() would otherwise treat the longest series
# as "running ahead" and truncate it.
END = "2025-06-02"


def _ohlc_from_path(path: np.ndarray, seed: int = 0, noise: float = 0.004,
                    end: str = END) -> pd.DataFrame:
    """Turn a close path into a plausible OHLCV frame.

    :param path: Close prices.
    :param seed: RNG seed for the intrabar noise.
    :param noise: Intrabar range as a fraction of price.
    :param end: Last business day.
    :returns: OHLCV DataFrame indexed by business days.
    """
    rng = np.random.default_rng(seed)
    n = len(path)
    close = path.astype(float)
    open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, noise / 2, n))
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, noise, n)))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, noise, n)))
    vol = rng.integers(1_000_000, 2_000_000, n).astype(float)
    idx = pd.bdate_range(end=end, periods=n)
    return pd.DataFrame({"Open": open_, "High": hi, "Low": lo, "Close": close, "Volume": vol}, index=idx)


def _uptrend_prefix(n: int, start: float, end: float, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = np.linspace(start, end, n)
    return base * (1 + rng.normal(0, 0.003, n)).cumprod() ** 0.3


def make_cup_and_handle() -> pd.DataFrame:
    """Uptrend, 100-bar rounded cup 25% deep, 15-bar handle 6% deep, breakout today."""
    pre = _uptrend_prefix(220, 60, 100)                      # 220 bars up-trend to 100
    t = np.linspace(0, np.pi, 100)
    cup = 100 - 25 * np.sin(t)                               # 100 -> 75 -> 100
    handle = np.concatenate([np.linspace(100, 94, 8), np.linspace(94, 97, 7)])
    brk = np.array([101.5, 102.0])                           # close above handle high
    path = np.concatenate([pre, cup, handle, brk])
    df = _ohlc_from_path(path, seed=3)
    df.loc[df.index[-2], "Volume"] *= 2.0                    # breakout volume
    return df


def make_inverse_hs() -> pd.DataFrame:
    """Decline, LS at 80, head at 70, RS at 81, flat neckline ~90, breakout today."""
    pre = np.linspace(120, 92, 80)                           # prior decline (rule: reversing something)
    ls = np.concatenate([np.linspace(92, 80, 12), np.linspace(80, 90, 12)])
    head = np.concatenate([np.linspace(90, 70, 15), np.linspace(70, 90.5, 15)])
    rs = np.concatenate([np.linspace(90.5, 81, 12), np.linspace(81, 89, 12)])
    brk = np.array([90.0, 92.5, 93.0])
    path = np.concatenate([pre, ls, head, rs, brk])
    # pad with a gentle 200+ bar base so SMA200 exists but is not "strong downtrend"
    base = np.linspace(112, 120, 160)
    return _ohlc_from_path(np.concatenate([base, path]), seed=5)


def make_bullish_wolfe() -> pd.DataFrame:
    """Falling wedge 1-2-3-4-5 with point 5 undercutting line 1-3, then a close back above."""
    base = np.linspace(95, 105, 230)
    p = [(0, 100.0), (10, 108.0), (22, 96.0), (32, 103.0), (46, 90.5)]  # (bar, price)
    seg = []
    for (b0, v0), (b1, v1) in zip(p[:-1], p[1:]):
        seg.append(np.linspace(v0, v1, b1 - b0, endpoint=False))
    wedge = np.concatenate(seg + [[90.5]])
    # line 1-3 at bar 46: 100 + (96-100)/22*46 = 91.64 ; point 5 = 90.5 undercuts by ~1.1
    rebound = np.array([91.0, 92.0, 92.8, 93.5, 94.0, 94.8, 95.5])  # 5 bars later swing low confirmed, then above line
    path = np.concatenate([base, wedge, rebound])
    return _ohlc_from_path(path, seed=7, noise=0.002)


def test_cup_and_handle_detected():
    df = make_cup_and_handle()
    sig = scan.detect_cup_and_handle(df, "TEST")
    assert sig, "cup & handle not detected"
    s = sig[0]
    assert s.status == "CONFIRMED", s
    assert s.stop < s.entry
    assert 0 < s.risk_pct <= 15


def test_inverse_hs_detected():
    df = make_inverse_hs()
    sig = scan.detect_inverse_hs(df, "TEST")
    assert sig, "inverse H&S not detected"
    s = sig[0]
    assert s.status == "CONFIRMED", s
    assert s.stop < s.entry


def test_bullish_wolfe_detected():
    df = make_bullish_wolfe()
    sig = scan.detect_bullish_wolfe(df, "TEST")
    assert sig, "wolfe wave not detected"
    s = sig[0]
    assert s.status in ("CONFIRMED", "WATCHLIST"), s
    assert s.stop < s.entry


def test_random_walk_false_positive_rate():
    """Detectors should rarely fire on pure noise (target: < 5% of series)."""
    rng = np.random.default_rng(42)
    fired = 0
    trials = 200
    for k in range(trials):
        path = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, 500)))
        df = _ohlc_from_path(path, seed=k)
        if scan.scan_symbol(f"RW{k}", df):
            fired += 1
    rate = fired / trials
    print(f"random-walk false-positive rate: {rate:.1%}")
    assert rate < 0.05, rate


def test_short_and_nan_series_do_not_crash():
    df = make_cup_and_handle().iloc[:40]
    assert scan.scan_symbol("SHORT", df) == []
    df2 = make_cup_and_handle()
    df2.loc[df2.index[100:110], "Volume"] = np.nan
    scan.scan_symbol("NAN", df2)  # must not raise


def test_symbol_normalisation(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("Symbol,Security\nBRK.B,Berkshire\nAAPL,Apple\nAAPL,dup\n")
    assert scan.load_sp500_symbols(str(p)) == ["AAPL", "BRK-B"]


def test_main_end_to_end(tmp_path, monkeypatch):
    """main() with the network download mocked: files written, report has both sections."""
    import json

    def fake_download(symbols, period="2y", batch=100):
        return {"CUP": make_cup_and_handle(), "IHS": make_inverse_hs(), "WW": make_bullish_wolfe()}

    monkeypatch.setattr(scan, "download_history", fake_download)
    monkeypatch.setattr(scan, "MAX_BREAKOUT_AGE", scan.MAX_BREAKOUT_AGE)  # main() mutates it
    out = tmp_path / "out"
    rc = scan.main(["--tickers", "CUP,IHS,WW", "--out-dir", str(out)])
    assert rc == 0
    data = json.loads((out / "signals.json").read_text())
    assert data["meta"]["scanned"] == 3
    tickers = {s["ticker"] for s in data["signals"]}
    assert {"CUP", "IHS", "WW"} <= tickers
    report = (out / "report.md").read_text()
    assert "## Confirmed breakouts" in report and "## Watchlist" in report
    for s in data["signals"]:
        assert s["stop"] < s["entry"] and 0 < s["risk_pct"] <= 15
    # meta.last_bar is the bar the signals were actually computed on.
    meta = data["meta"]
    assert meta["last_bar"] == END
    assert all(s["last_date"] == END for s in data["signals"])
    assert meta["last_bar_symbols"] == 3 and meta["lagging_symbols"] == 0
    assert meta["skipped_bar"] is None
    # The effective breakout-age limit is stated per pattern, not just the base value.
    assert meta["max_breakout_age"] == scan.MAX_BREAKOUT_AGE
    assert meta["max_breakout_age_by_pattern"] == {
        "Cup & Handle": 3, "Inverse Head & Shoulders": 8, "Bullish Wolfe Wave": 8}
    assert "Cup & Handle 3, Inverse Head & Shoulders 8, Bullish Wolfe Wave 8" in report
    assert "older than 3 bars are dropped" not in report


# --------------------------------------------------------------------------- #
# Last-bar handling
#
# Why: Yahoo publishes the previous session's daily row in two steps (volume
# first, OHLC hours later).  On 2026-09-04 the scan reported last_bar
# 2026-09-03 (2 symbols had the complete bar) while all 19 signals were computed
# on 2026-09-02 (501 symbols had a volume-only row that dropna removed).
# --------------------------------------------------------------------------- #
def _batched_frame(frames: dict) -> pd.DataFrame:
    """Mimic ``yf.download(group_by="ticker")``: columns (ticker, field), union index."""
    return pd.concat(frames.values(), axis=1, keys=frames.keys(), names=["Ticker", "Price"])


def _install_fake_yfinance(monkeypatch, raw: pd.DataFrame, calls: list):
    fake = types.ModuleType("yfinance")

    def download(tickers, **kwargs):
        calls.append((list(tickers), kwargs))
        return raw

    fake.download = download
    monkeypatch.setitem(sys.modules, "yfinance", fake)


def test_download_history_drops_only_trailing_rows_without_close(monkeypatch):
    base = make_cup_and_handle()
    d_last = base.index[-1]
    partial = base.copy()                      # Yahoo's not-yet-published bar:
    partial.loc[d_last, ["Open", "High", "Low", "Close"]] = np.nan   # volume only
    complete = base.copy()
    late = base.iloc[:-2].copy()                # no row at all for the last two days
    short = base.iloc[-30:].copy()              # too little history -> excluded
    calls: list = []
    _install_fake_yfinance(monkeypatch, _batched_frame(
        {"AAA": partial, "BBB": partial, "CCC": complete, "LATE": late, "SHORT": short}), calls)

    out = scan.download_history(["AAA", "BBB", "CCC", "LATE", "SHORT", "MISSING"],
                                period="2y", batch=100)

    assert calls and calls[0][1]["group_by"] == "ticker"
    assert set(out) == {"AAA", "BBB", "CCC", "LATE"}
    # batch-index padding (all-NaN rows) is dropped but is not a "partial" bar
    assert out["LATE"].index[-1] == base.index[-3]
    assert out["LATE"].attrs["partial_bars"] == []
    prev = base.index[-2]
    for sym in ("AAA", "BBB"):
        assert out[sym].index[-1] == prev, sym
        assert out[sym].attrs["partial_bars"] == [str(d_last.date())]
        assert not out[sym]["Close"].isna().any()
    assert out["CCC"].index[-1] == d_last
    assert out["CCC"].attrs["partial_bars"] == []
    assert list(out["CCC"].columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_download_history_interior_nan_is_not_a_partial_bar(monkeypatch):
    base = make_cup_and_handle()
    holed = base.copy()
    holed.loc[holed.index[-10], "Close"] = np.nan  # a hole in the middle, newest bar intact
    _install_fake_yfinance(monkeypatch, _batched_frame({"AAA": holed}), [])
    out = scan.download_history(["AAA"])
    assert out["AAA"].index[-1] == base.index[-1]
    assert len(out["AAA"]) == len(base) - 1
    assert out["AAA"].attrs["partial_bars"] == []


def test_align_last_bar_uses_majority_bar_and_truncates_leaders():
    base = make_cup_and_handle()
    d_last, d_prev = base.index[-1], base.index[-2]
    majority = {}
    for sym in ("A", "B", "C"):
        df = base.iloc[:-1].copy()              # newest complete bar = d_prev ...
        df.attrs["partial_bars"] = [str(d_last.date())]   # ... d_last arrived volume-only
        majority[sym] = df
    leader = base.copy()                        # already has the complete d_last bar
    leader.attrs["partial_bars"] = []
    lagging = base.iloc[:-3].copy()             # e.g. halted; three bars behind
    lagging.attrs["partial_bars"] = []
    data = {**majority, "LEAD": leader, "LAG": lagging}

    aligned, info = scan.align_last_bar(data)

    assert info["last_bar"] == str(d_prev.date())
    assert set(aligned) == set(data)
    assert aligned["LEAD"].index[-1] == d_prev          # nothing runs ahead of last_bar
    assert aligned["LAG"].index[-1] == base.index[-4]   # lagging symbols are kept as-is
    assert info["last_bar_symbols"] == 4 and info["lagging_symbols"] == 1
    assert info["skipped_bar"] == str(d_last.date())
    assert info["skipped_bar_complete"] == 1 and info["skipped_bar_partial"] == 3
    assert info["last_bar_histogram"] == {str(d_last.date()): 1, str(d_prev.date()): 3,
                                          str(base.index[-4].date()): 1}
    # every symbol's signals are now computed on a bar <= last_bar
    for df in aligned.values():
        assert df.index[-1] <= d_prev


def test_align_last_bar_when_every_symbol_is_complete():
    base = make_cup_and_handle()
    data = {s: base.copy() for s in ("A", "B", "C")}
    aligned, info = scan.align_last_bar(data)
    assert info["last_bar"] == str(base.index[-1].date())
    assert info["skipped_bar"] is None
    assert info["last_bar_symbols"] == 3 and info["lagging_symbols"] == 0
    assert all(len(aligned[s]) == len(base) for s in data)
    assert scan.align_last_bar({}) == ({}, {"last_bar": None})


def test_main_reports_the_bar_actually_scanned(tmp_path, monkeypatch):
    """Reproduction of 2026-09-04: most symbols have a volume-only newest row."""
    import json

    def fake_download(symbols, period="2y", batch=100):
        cup, ihs, ww = make_cup_and_handle(), make_inverse_hs(), make_bullish_wolfe()
        d_last = cup.index[-1]
        frames = {}
        for sym, df in (("CUP", cup), ("IHS", ihs), ("WW", ww)):
            partial = df.copy()
            partial.loc[d_last, ["Open", "High", "Low", "Close"]] = np.nan
            frames[sym] = partial
        frames["APH"] = cup.copy()       # one symbol already has the complete bar
        return _batched_frame(frames)

    monkeypatch.setitem(sys.modules, "yfinance",
                        types.SimpleNamespace(download=lambda tickers, **kw: fake_download(tickers)))
    monkeypatch.setattr(scan, "MAX_BREAKOUT_AGE", scan.MAX_BREAKOUT_AGE)  # main() mutates it
    out = tmp_path / "out"
    rc = scan.main(["--tickers", "CUP,IHS,WW,APH", "--out-dir", str(out), "--max-age", "2"])
    assert rc == 0
    data = json.loads((out / "signals.json").read_text())
    meta = data["meta"]
    prev = str(pd.bdate_range(end=END, periods=2)[0].date())
    assert meta["last_bar"] == prev, meta
    assert meta["skipped_bar"] == END
    assert meta["skipped_bar_partial"] == 3 and meta["skipped_bar_complete"] == 1
    assert meta["last_bar_symbols"] == 4 and meta["lagging_symbols"] == 0
    assert data["signals"], "the previous bar still carries the synthetic setups"
    assert {s["last_date"] for s in data["signals"]} == {prev}
    assert meta["max_breakout_age"] == 2
    assert meta["max_breakout_age_by_pattern"] == {
        "Cup & Handle": 2, "Inverse Head & Shoulders": 7, "Bullish Wolfe Wave": 7}
    report = (out / "report.md").read_text()
    assert f"last bar {prev}" in report
    assert f"Newest bar {END} not scanned: complete for 1 symbols, still missing OHLC at Yahoo for 3." in report


if __name__ == "__main__":  # pragma: no cover
    import pytest
    raise SystemExit(pytest.main([__file__, "-q", "-s"]))
