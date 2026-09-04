# Security policy

SignalSync is a small, single-maintainer project. It handles no credentials and no user data: it reads public market data, writes a report into this repository, and nothing else.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting instead: **Security → Report a vulnerability** on this repository. You will get an acknowledgement within a few days; fixes are published as ordinary commits and noted in `CHANGELOG.md` under *Security*.

## Scope

In scope: the scanner (`scan.py`, `tools/`), the GitHub Actions workflows, and the dependency pins. Out of scope: the correctness of trading signals, which are heuristic and not advice, and issues in Yahoo Finance or yfinance themselves (report those upstream).
