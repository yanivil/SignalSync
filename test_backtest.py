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


def test_breakdown_and_render():
    def row(pattern, score, outcome, r):
        return {"ticker": "T", "pattern": pattern, "score": score, "outcome": outcome, "r": r,
                "scan_day": "2026-01-05", "entry": 100.0, "fill": 100.5, "stop": 95.0, "target": 110.0,
                "bars": 0 if outcome == "gap" else 3}
    rows = [row("Cup & Handle", 65, "target", 2.0), row("Cup & Handle", 72, "stop", -1.0),
            row("Bullish Wolfe Wave", 85, "open", 0.4), row("Cup & Handle", 91, "gap", None)]
    stats = bt.breakdown(rows)
    assert stats["overall"]["signals"] == 4 and stats["overall"]["gap"] == 1
    assert stats["overall"]["target"] == 1 and stats["overall"]["stop"] == 1 and stats["overall"]["open"] == 1
    assert stats["overall"]["hit_rate"] == 0.5 and stats["overall"]["mean_r"] == round((2.0 - 1.0 + 0.4) / 3, 3)
    assert set(stats["by_score"]) == {"60-69", "70-79", "80-89", "90-100"}
    assert stats["by_pattern"]["Bullish Wolfe Wave"]["hit_rate"] is None    # nothing resolved
    md = bt.render(rows, stats, 63, 40)
    assert "| all | 4 | 1 | 1 | 1 | 1 | 50% | +0.47 |" in md
    assert "| 2026-01-05 | T | Cup & Handle | 91 | 100.0 | 100.5 | 95.0 | 110.0 | gap | 0 | - |" in md
    assert isinstance(pd.DataFrame(rows), pd.DataFrame)
