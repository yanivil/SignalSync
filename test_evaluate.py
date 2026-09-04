#!/usr/bin/env python3
"""Tests for tools/evaluate_signals.py: outcome classification and the git signal log."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
import evaluate_signals as ev  # noqa: E402


def _bars(*rows):
    """rows: (high, low, close) per day."""
    idx = pd.bdate_range("2026-01-05", periods=len(rows))
    return pd.DataFrame({"Open": [r[2] for r in rows], "High": [r[0] for r in rows],
                         "Low": [r[1] for r in rows], "Close": [r[2] for r in rows]}, index=idx)


def test_classify_outcomes_and_r_multiples():
    entry, stop, target = 100.0, 90.0, 120.0
    assert ev.classify(entry, stop, target, _bars((105, 99, 104), (121, 110, 118))) == \
        {"outcome": "target", "bars": 2, "exit": 120.0, "r": 2.0}
    assert ev.classify(entry, stop, target, _bars((105, 99, 104), (100, 89, 95))) == \
        {"outcome": "stop", "bars": 2, "exit": 90.0, "r": -1.0}
    both = ev.classify(entry, stop, target, _bars((125, 88, 100)))      # touched both: stop
    assert both["outcome"] == "stop" and both["r"] == -1.0
    open_ = ev.classify(entry, stop, target, _bars((105, 99, 104), (106, 100, 105), (107, 101, 106)), horizon=2)
    assert open_ == {"outcome": "open", "bars": 2, "exit": 105.0, "r": 0.5}   # horizon respected
    assert ev.classify(entry, stop, None, _bars((150, 99, 149)))["outcome"] == "open"  # no target
    assert ev.classify(entry, stop, target, _bars()) == {"outcome": "no_data", "bars": 0, "exit": None, "r": None}
    assert ev.classify(100.0, 100.0, target, _bars((121, 99, 120)))["r"] is None    # zero risk


def test_summarise():
    rows = [{"outcome": "target", "r": 2.0}, {"outcome": "stop", "r": -1.0},
            {"outcome": "stop", "r": -1.0}, {"outcome": "open", "r": 0.5}, {"outcome": "no_data", "r": None}]
    assert ev.summarise(rows) == {"n": 5, "target": 1, "stop": 2, "open": 1, "no_data": 1,
                                  "hit_rate": 0.333, "mean_r": 0.125}
    assert ev.summarise([]) == {"n": 0, "target": 0, "stop": 0, "open": 0, "no_data": 0,
                                "hit_rate": None, "mean_r": None}


def _commit(repo, doc, day):
    os.makedirs(repo / "output", exist_ok=True)
    (repo / "output" / "signals.json").write_text(json.dumps(doc))
    env = {**os.environ, "GIT_AUTHOR_DATE": f"{day}T02:00:00Z", "GIT_COMMITTER_DATE": f"{day}T02:00:00Z",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    subprocess.run(["git", "-C", str(repo), "add", "output/signals.json"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", f"scan: {day}"], check=True, env=env)


def _sig(ticker, status, stop, last_date, entry=100.0):
    return {"ticker": ticker, "pattern": "Cup & Handle", "status": status, "entry": entry, "stop": stop,
            "risk_pct": 5.0, "target": 120.0, "score": 70, "last_close": entry, "last_date": last_date,
            "bars_since_break": 0, "volume_ratio": None, "trend": "", "notes": ""}


@pytest.fixture
def signal_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    # Day 1: AAA confirmed, BBB on the watchlist.  Day 2: the same AAA structure a bar older
    # (entry moved, stop unchanged) plus BBB now confirmed.  Day 3: unreadable file.
    _commit(tmp_path, {"meta": {}, "signals": [_sig("AAA", "CONFIRMED", 90.0, "2026-03-02"),
                                                _sig("BBB", "WATCHLIST", 80.0, "2026-03-02")]}, "2026-03-03")
    _commit(tmp_path, {"meta": {}, "signals": [_sig("AAA", "CONFIRMED", 90.0, "2026-03-03", entry=101.0),
                                                _sig("BBB", "CONFIRMED", 80.0, "2026-03-03")]}, "2026-03-04")
    (tmp_path / "output" / "signals.json").write_text("{not json")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-am", "broken"], check=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"})
    return tmp_path


def test_signal_history_dedupes_on_first_confirmed_appearance(signal_repo):
    hist = ev.signal_history(str(signal_repo))
    assert [(s["ticker"], s["last_date"], s["entry"], s["first_seen"]) for s in hist] == [
        ("AAA", "2026-03-02", 100.0, "2026-03-03"),        # first appearance kept, later ones ignored
        ("BBB", "2026-03-03", 100.0, "2026-03-04")]        # watchlist rows never count


def test_evaluate_uses_bars_after_the_signal_date_and_survives_fetch_errors(signal_repo):
    hist = ev.signal_history(str(signal_repo))
    calls = []

    def fetch(ticker, start):
        calls.append((ticker, start))
        if ticker == "BBB":
            raise RuntimeError("HTTP 429")
        idx = pd.bdate_range("2026-03-02", periods=4)                 # includes the signal day itself
        return pd.DataFrame({"Open": 100.0, "High": [100, 101, 125, 126], "Low": [50, 99, 99, 99],
                             "Close": [100, 100.5, 124, 125]}, index=idx)

    rows = ev.evaluate(hist, horizon=60, fetch=fetch)
    assert calls == [("AAA", "2026-03-02"), ("BBB", "2026-03-03")]
    aaa, bbb = rows
    assert aaa["outcome"] == "target" and aaa["bars"] == 2           # the signal-day bar (Low 50) is excluded
    assert bbb["outcome"] == "no_data"
    md = ev.render(rows, ev.summarise(rows), 60)
    assert "| AAA | Cup & Handle | 2026-03-02 | 100.0 | 90.0 | 120.0 | target | 2 | 2.0 |" in md
    assert "hit rate 1.0" in md
