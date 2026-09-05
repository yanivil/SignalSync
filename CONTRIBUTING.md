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
