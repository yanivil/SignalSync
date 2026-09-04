"""Shared fixtures for the SignalSync test suite.

The synthetic price-path builders live in ``test_scan.py`` (the original
suite) and are reused here rather than duplicated.  This file adds:

* fresh per-test copies of the three textbook fixtures,
* negative-control series (flat bars, a straight line, a random walk),
* a six-symbol mini universe for the end-to-end pipeline tests, and
* an in-memory stand-in for the ``yfinance`` module so every test runs
  offline with zero latency and can script throttling / delisting failures.

An autouse fixture restores ``MIN_SCORE`` / ``MAX_BREAKOUT_AGE`` after each
test because ``scan.main()`` rewrites those module globals from the CLI.
"""

from __future__ import annotations

import sys
import time
import types
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytest

import scan
from test_scan import (END, _close_print, _ohlc_from_path, make_bullish_wolfe,  # noqa: F401
                       make_cup_and_handle, make_inverse_hs)


@pytest.fixture(autouse=True)
def _restore_tunables(monkeypatch):
    """``scan.main()`` mutates these globals; keep every test independent."""
    monkeypatch.setattr(scan, "MIN_SCORE", scan.MIN_SCORE)
    monkeypatch.setattr(scan, "MAX_BREAKOUT_AGE", scan.MAX_BREAKOUT_AGE)


# --------------------------------------------------------------------------- #
# Synthetic series
# --------------------------------------------------------------------------- #
@pytest.fixture
def cup_df() -> pd.DataFrame:
    return make_cup_and_handle()


@pytest.fixture
def ihs_df() -> pd.DataFrame:
    return make_inverse_hs()


@pytest.fixture
def wolfe_df() -> pd.DataFrame:
    return make_bullish_wolfe()


def make_flat(n: int = 400, price: float = 50.0) -> pd.DataFrame:
    """Constant OHLC: no pivots, zero ATR, nothing to detect."""
    idx = pd.bdate_range(end=END, periods=n)
    return pd.DataFrame({"Open": price, "High": price, "Low": price, "Close": price,
                         "Volume": 1e6}, index=idx)


def make_random_walk(seed: int = 0, n: int = 500, sigma: float = 0.015) -> pd.DataFrame:
    """Geometric random walk; the default seed produces no signal (asserted in tests)."""
    rng = np.random.default_rng(seed)
    path = 100 * np.exp(np.cumsum(rng.normal(0, sigma, n)))
    return _ohlc_from_path(path, seed=seed)


@pytest.fixture
def flat_df() -> pd.DataFrame:
    return make_flat()


@pytest.fixture
def mini_universe() -> Dict[str, pd.DataFrame]:
    """Five tickers with history: three textbook setups plus two negative controls."""
    return {"CUP": make_cup_and_handle(), "IHS": make_inverse_hs(), "WW": make_bullish_wolfe(),
            "NOISE": make_random_walk(0), "FLAT": make_flat()}


# --------------------------------------------------------------------------- #
# Offline yfinance stand-in
# --------------------------------------------------------------------------- #
class FakeYFinance:
    """Record of one installed fake ``yfinance`` module.

    :ivar calls: ``(symbol, kwargs)`` per ``Ticker.history`` call, in order.
    :ivar sleeps: seconds passed to ``time.sleep`` by the retry loop.
    """

    def __init__(self) -> None:
        self.calls: List[Tuple[str, dict]] = []
        self.sleeps: List[float] = []

    def history_calls(self, sym: str) -> int:
        return sum(1 for s, _ in self.calls if s == sym)


@pytest.fixture
def fake_yfinance(monkeypatch) -> Callable[..., FakeYFinance]:
    """Factory: ``install(frames, metas=None, failures=None)``.

    :param frames: ``{symbol: DataFrame}`` served by ``Ticker.history``; a
        symbol absent from it raises yfinance's "delisted" error.
    :param metas: ``{symbol: chart meta}`` for ``get_history_metadata``.
    :param failures: ``{symbol: [Exception, ...]}`` raised, one per call, before
        the frame is served -- simulates throttling.  Never popped for
        symbols not listed.
    ``time.sleep`` inside ``scan`` is replaced by a recorder so retries cost
    nothing.
    """
    def install(frames: Dict[str, pd.DataFrame], metas: Optional[Dict[str, dict]] = None,
                failures: Optional[Dict[str, List[Exception]]] = None) -> FakeYFinance:
        rec = FakeYFinance()
        pending = {k: list(v) for k, v in (failures or {}).items()}
        fake = types.ModuleType("yfinance")

        class FakeTicker:
            def __init__(self, sym: str) -> None:
                self.sym = sym

            def history(self, **kwargs):
                rec.calls.append((self.sym, kwargs))
                if pending.get(self.sym):
                    raise pending[self.sym].pop(0)
                if self.sym not in frames:
                    raise ValueError(f"{self.sym}: No data found, symbol may be delisted")
                return frames[self.sym].copy()

            def get_history_metadata(self):
                return dict((metas or {}).get(self.sym, {}))

        fake.Ticker = FakeTicker
        monkeypatch.setitem(sys.modules, "yfinance", fake)
        monkeypatch.setattr(scan, "time", types.SimpleNamespace(sleep=rec.sleeps.append,
                                                                 time=time.time))
        return rec

    return install
