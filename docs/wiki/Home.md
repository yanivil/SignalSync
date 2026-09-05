# 🎯 SignalSync Documentation

> **Automated, risk-defined algorithmic chart pattern screener for the S&P 500.**  
> Scans 500+ equities daily on GitHub Actions with zero paid APIs and delivers verified morning setups.

[![tests](https://github.com/yanivil/SignalSync/actions/workflows/tests.yml/badge.svg)](https://github.com/yanivil/SignalSync/actions/workflows/tests.yml)
[![daily scan](https://github.com/yanivil/SignalSync/actions/workflows/daily-scan.yml/badge.svg)](https://github.com/yanivil/SignalSync/actions/workflows/daily-scan.yml)
[![discussions](https://img.shields.io/badge/community-discussions-blue)](https://github.com/yanivil/SignalSync/discussions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/yanivil/SignalSync/blob/main/LICENSE)

---

### 💡 Why SignalSync?

* **🛡️ Strictly Defined Risk:** Every confirmed signal includes an entry price, an ATR-buffered structural stop, and a reference target. Setups requiring >15% risk are automatically dropped.
* **📐 No Forced Patterns:** Strict geometric curvature algorithms (parabolic regression vs. V-shapes) coupled with a composite quality score ($\ge 60$).
* **📈 Trend-Gated:** Built-in SMA50 / SMA200 trend gates prevent fighting dominant macro momentum.
* **🔬 Rigorously Backtested:** Includes a walk-forward replay engine and historical git signal tracker to measure real hit rates and R multiples.
* **⚡ Serverless & Free:** Runs completely within GitHub Actions free tier using Yahoo Finance data. No servers, no subscriptions.

---

### 📊 Supported Bullish Setups

| Pattern | Setup Type | Trigger Condition | Structural Stop | Reference Target |
| :--- | :--- | :--- | :--- | :--- |
| ☕ **Cup & Handle** | Continuation | Daily close above handle high | Handle low − 0.25 ATR | Entry + Cup depth |
| 👤 **Inverse Head & Shoulders** | Reversal | Daily close above neckline | Right shoulder low − 0.25 ATR | Entry + (Neckline − Head) |
| 🐺 **Bullish Wolfe Wave** | Reversal | Daily close back above line 1–3 | Point 5 low − 0.25 ATR | Line 1–4 at the ETA |

> [!TIP]
> **CONFIRMED vs WATCHLIST:** Setups breaking out on the latest bar are flagged **`CONFIRMED`**. Setups with completed geometry within 5% of their trigger wait on the **`WATCHLIST`**.

---

### 📚 Documentation Hub

Explore the full technical design, algorithms, and configuration:

* 🏗️ **[Architecture and Data Pipeline](01-Architecture-and-Data-Pipeline.md)**  
  *Constituent loading, symbol normalisation (e.g. `BRK.B` → `BRK-B`), Yahoo Finance throttling, last-bar alignment, and the nightly scan schedule.*

* 📐 **[Pattern Catalog](02-Pattern-Catalog.md)**  
  *Exact geometric criteria, parabolic R² roundness formulas, neckline tilt calculations, Wolfe EPA/ETA projections, and score composition.*

* 🎛️ **[Configuration and Tuning](03-Configuration-and-Tuning.md)**  
  *Reference guide for every threshold, quality score cutoffs, 5% watchlist proximity, age limits, and false-positive controls.*

* 🧪 **[Testing and Contributing](04-Testing-and-Contributing.md)**  
  *Offline test harness, walk-forward backtester (`tools/backtest.py`), signal outcome tracking (`tools/evaluate_signals.py`), and how to add a pattern.*

---

### 💬 Community & Quick Links

* 💬 **[GitHub Discussions](https://github.com/yanivil/SignalSync/discussions):** Join the community, suggest new patterns, and discuss setups.
* 📄 **[Latest Scan Report](https://github.com/yanivil/SignalSync/blob/main/output/report.md):** View the most recent confirmed signals and watchlist.
* 💻 **[GitHub Repository](https://github.com/yanivil/SignalSync):** View source code, open issues, or contribute.
