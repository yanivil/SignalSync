# Contributing to SignalSync

Thank you for your interest in contributing to **SignalSync**! We welcome bug reports, geometric improvements, algorithmic refinements, and new chart pattern detectors.

---

## 1. Code of Conduct

All contributors are expected to follow our [Code of Conduct](CODE_OF_CONDUCT.md). Please be respectful and collaborative.

---

## 2. Quickstart Development Setup

SignalSync requires **Python 3.12+**. 

Set up an isolated virtual environment with hash-checked dependencies:

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install locked dependencies
pip install --require-hashes -r requirements.txt -r requirements-dev.txt
```

---

## 3. Running Tests

Before submitting any code changes, ensure all tests pass:

```bash
# Run the fast, offline unit test suite (~2 seconds)
python -m pytest -q

# Run with random-walk false-positive rate logging
python -m pytest -q -s
```

> **Note**: The entire test suite runs offline using synthetic deterministic paths and mocked market data. Tests must never touch the live network.

---

## 4. How to Submit a Pull Request (PR)

1. **Fork & Branch**: Create a feature branch off `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. **Follow Code Standards**:
   * Keep thresholds auditable as constants at the top of `scan.py` with explanatory comments.
   * Preserve full type annotations on all public functions.
   * If modifying pattern rules, update `docs/wiki/` documentation and ensure random-walk false positives stay under 5%.
3. **Commit & Push**: Use clear, concise commit messages following standard conventions.
4. **Open a PR**: Open a Pull Request against the `main` branch. Ensure the automated `tests` GitHub Actions workflow passes.

---

## 5. Adding New Patterns & In-Depth Guidelines

For detailed technical guidance on:
* Detector architecture and helper primitives
* Synthetic fixture builders (`make_cup_and_handle()`, etc.)
* Walk-forward backtesting tools (`tools/backtest.py`)
* Dependency compilation via `pip-tools`

Please read the full [Testing and Contributing Guide](docs/wiki/04-Testing-and-Contributing.md).
