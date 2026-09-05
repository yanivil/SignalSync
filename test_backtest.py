#!/usr/bin/env python3
"""Tests for tools/backtest.py: no look-ahead, first-seen signals, fills and breakdowns (offline)."""

from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
import backtest as bt  # noqa: E402
import scan  # noqa: E402
from test_scan import make_cup_and_handle  # noqa: E402


def test_walk_forward_finds_the_cup_on_its_breakout_day_without_look_ahead(mini_universe):
    cup = make_cup_and_handle()
    (today,) = scan.detect_cup_and_handle(cup, "CUP")          # breaks out at bar -2 (age 1 today)
    rows = bt.walk_forward(mini_universe, days=5, horizon=10)
    cups = [r for r in rows if r["ticker"] == "CUP"]
    assert len(cups) == 1                                        # one structure, seen once
    r = cups[0]
    assert r["scan_day"] == str(cup.index[-2].date()) == r["last_date"]   # first seen on the breakout day
    assert r["bars_since_break"] == 0 and r["stop"] == today.stop
    assert r["fill"] == round(float(cup["Open"].iloc[-1]), 2)   # filled at the next session's open
    assert r["outcome"] in ("open", "stop", "target") and r["bars"] == 1   # one bar after the fill exists
    for row in rows:
        assert row["last_date"] == row["scan_day"]               # nothing dated after its scan day
    assert {r["ticker"] for r in rows} <= {"CUP", "IHS", "WW"}   # controls never fire


def test_walk_forward_marks_gaps_and_no_data(mini_universe):
    cup = mini_universe["CUP"].copy()
    cup.loc[cup.index[-1], "Open"] = cup["Close"].iloc[-2] * 1.08     # opens 8 % above: no trade
    rows = bt.walk_forward({"CUP": cup}, days=5, horizon=10)
    assert [r["outcome"] for r in rows] == ["gap"] and rows[0]["r"] is None
    rows = bt.walk_forward({"CUP": cup.iloc[:-1]}, days=3, horizon=10)  # breakout on the very last bar
    assert [r["outcome"] for r in rows] == ["no_data"]


def _bars(*rows):
    """rows: (open, high, low, close) per day."""
    idx = pd.bdate_range("2026-01-05", periods=len(rows))
    return pd.DataFrame({"Open": [r[0] for r in rows], "High": [r[1] for r in rows],
                         "Low": [r[2] for r in rows], "Close": [r[3] for r in rows]}, index=idx)


def test_excursions_and_chart_book_success():
    fill, stop = 100.0, 95.0
    # +5 % reached on bar 2 before any close below the stop -> success, even though bar 3 later closes below.
    b = _bars((100, 101, 99, 100), (101, 105.5, 100, 104), (104, 104, 90, 92))
    assert bt.excursions(fill, stop, b, 10) == {"mfe": 0.055, "mae": -0.1, "success5": True}
    # A close below the stop first -> failure, although an intraday low would not have mattered.
    b = _bars((100, 101, 94, 94.5), (95, 106, 94, 105))
    assert bt.excursions(fill, stop, b, 10)["success5"] is False
    # Intraday touch of the stop without a close below it is NOT a failure under this definition.
    b = _bars((100, 101, 94, 99), (99, 106, 98, 105))
    assert bt.excursions(fill, stop, b, 10)["success5"] is True
    assert bt.excursions(fill, stop, _bars((100, 102, 99, 101)), 10)["success5"] is None   # undecided


def test_classify_variant_close_vs_intraday_stops():
    fill, stop, target = 100.0, 95.0, 110.0
    wick = _bars((100, 101, 94, 99), (99, 111, 98, 110))          # bar 1 wicks through the stop, closes above
    assert bt.classify_variant(fill, stop, target, wick, 10, "intraday")["outcome"] == "stop"
    close = bt.classify_variant(fill, stop, target, wick, 10, "close")
    assert close["outcome"] == "target" and close["bars"] == 2 and close["r"] == 2.0
    dive = _bars((100, 101, 93, 93.5),)                           # closes below: exit at the close, not the stop
    assert bt.classify_variant(fill, stop, target, dive, 10, "close") == {
        "outcome": "stop", "bars": 1, "exit": 93.5, "r": -1.3}


def test_grid_rescores_the_same_signals(mini_universe):
    rows = bt.walk_forward(mini_universe, days=5, horizon=10)
    g = bt.grid(rows, mini_universe, 10)
    assert len(g) == len(bt.GRID) == 12
    assert {(x["stop_extra_atr"], x["stop_basis"], x["target_fraction"]) for x in g} == set(bt.GRID)
    traded = sum(1 for r in rows if r["outcome"] in ("target", "stop", "open"))
    assert all(x["n"] == traded for x in g)
    md = bt.render(rows, bt.breakdown(rows), 5, 10, g)
    assert "## Stop / target variants" in md and "| 0.75 | close | half |" in md


def test_breakdown_and_render():
    def row(pattern, score, outcome, r):
        return {"ticker": "T", "pattern": pattern, "score": score, "outcome": outcome, "r": r,
                "scan_day": "2026-01-05", "entry": 100.0, "fill": 100.5, "stop": 95.0, "target": 110.0,
                "bars": 0 if outcome == "gap" else 3, "atr": 1.0,
                "mfe": 0.08 if outcome != "gap" else None, "mae": -0.02 if outcome != "gap" else None,
                "success5": {"target": True, "stop": False, "open": None}.get(outcome)}
    rows = [row("Cup & Handle", 65, "target", 2.0), row("Cup & Handle", 72, "stop", -1.0),
            row("Bullish Wolfe Wave", 85, "open", 0.4), row("Cup & Handle", 91, "gap", None)]
    stats = bt.breakdown(rows)
    assert stats["overall"]["signals"] == 4 and stats["overall"]["gap"] == 1
    assert stats["overall"]["target"] == 1 and stats["overall"]["stop"] == 1 and stats["overall"]["open"] == 1
    assert stats["overall"]["hit_rate"] == 0.5 and stats["overall"]["mean_r"] == round((2.0 - 1.0 + 0.4) / 3, 3)
    assert set(stats["by_score"]) == {"60-69", "70-79", "80-89", "90-100"}
    assert stats["by_pattern"]["Bullish Wolfe Wave"]["hit_rate"] is None    # nothing resolved
    assert stats["overall"]["success5"] == 0.5 and stats["overall"]["mfe"] == 0.08
    md = bt.render(rows, stats, 63, 40)
    assert "| all | 4 | 1 | 1 | 1 | 1 | 50% | +0.47 | 50% | +8.0% | -2.0% |" in md
    assert "| 2026-01-05 | T | Cup & Handle | 91 | 100.0 | 100.5 | 95.0 | 110.0 | gap | 0 | - |" in md
    assert isinstance(pd.DataFrame(rows), pd.DataFrame)
