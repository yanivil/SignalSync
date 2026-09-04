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

import numpy as np
import pandas as pd

import scan


def _ohlc_from_path(path: np.ndarray, seed: int = 0, noise: float = 0.004,
                    start: str = "2024-01-01") -> pd.DataFrame:
    """Turn a close path into a plausible OHLCV frame.

    :param path: Close prices.
    :param seed: RNG seed for the intrabar noise.
    :param noise: Intrabar range as a fraction of price.
    :param start: First business day.
    :returns: OHLCV DataFrame indexed by business days.
    """
    rng = np.random.default_rng(seed)
    n = len(path)
    close = path.astype(float)
    open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, noise / 2, n))
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, noise, n)))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, noise, n)))
    vol = rng.integers(1_000_000, 2_000_000, n).astype(float)
    idx = pd.bdate_range(start, periods=n)
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


if __name__ == "__main__":  # pragma: no cover
    import pytest
    raise SystemExit(pytest.main([__file__, "-q", "-s"]))
