#!/usr/bin/env python3
"""Tests for tools/site_charts.py: the bars behind the page's charts, cut at the scan's bar, and a lossless failure."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
import scan  # noqa: E402
import site_charts as sc  # noqa: E402


def test_bars_for_keeps_the_last_sessions_up_to_the_scan_bar(mini_universe):
    out = sc.bars_for({"CUP": mini_universe["CUP"]}, bars=50, last_bar="2025-06-02")
    assert list(out) == ["CUP"] and set(out["CUP"]) == {"dates", "open", "high", "low", "close"}
    assert len(out["CUP"]["close"]) == 50 and out["CUP"]["dates"][-1] == "2025-06-02"
    assert out["CUP"]["close"][-1] == round(float(mini_universe["CUP"]["Close"].iloc[-1]), 2)
    earlier = sc.bars_for({"CUP": mini_universe["CUP"]}, bars=50, last_bar="2025-05-30")   # the scan's own bar
    assert earlier["CUP"]["dates"][-1] == "2025-05-30" and len(earlier["CUP"]["dates"]) == 50
    assert sc.bars_for({"CUP": mini_universe["CUP"].iloc[:0]}, bars=10) == {}                # nothing to draw


def _signals(tmp_path, tickers, last_bar="2025-06-02"):
    path = tmp_path / "signals.json"
    path.write_text(json.dumps({"meta": {"last_bar": last_bar},
                                "signals": [{"ticker": t, "status": "CONFIRMED"} for t in tickers]}))
    return str(path)


def test_main_writes_the_file_and_skips_what_it_cannot_fetch(mini_universe, fake_yfinance, tmp_path, monkeypatch):
    fake_yfinance({"CUP": mini_universe["CUP"]})                       # IHS absent: "delisted", skipped
    out = tmp_path / "charts.json"
    assert sc.main(["--signals", _signals(tmp_path, ["IHS", "CUP"]), "--bars", "30", "--json", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert (doc["bars"], doc["as_of"], list(doc["symbols"])) == (30, "2025-06-02", ["CUP"])
    assert len(doc["symbols"]["CUP"]["close"]) == 30
    # A download that raises leaves an empty map, a written file and a zero exit: the page builds without charts.
    def boom(*a, **k):
        raise RuntimeError("no network")
    monkeypatch.setattr(scan, "download_history", boom)
    assert sc.main(["--signals", _signals(tmp_path, ["CUP"]), "--json", str(out)]) == 0
    assert json.loads(out.read_text())["symbols"] == {}
    # No signals at all: nothing is downloaded.
    assert sc.main(["--signals", _signals(tmp_path, []), "--json", str(out)]) == 0
    assert json.loads(out.read_text()) == {"bars": 120, "as_of": "2025-06-02", "symbols": {}}
