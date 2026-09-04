# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed (docs)
- Repository is `yanivil/SignalSync`; README and PR draft updated accordingly.

### Added
- `scan.py`: S&P 500 daily-bar scanner with three detectors — Cup & Handle,
  Inverse Head & Shoulders, Bullish Wolfe Wave — each producing entry, stop,
  risk %, reference target, quality score, trend context and anchor notes.
- Rule enforcement from the user's guide: strict geometry + quality score
  (no forced patterns), SMA50/SMA200 trend gate, close-based confirmation
  with CONFIRMED/WATCHLIST split and a 5 % no-chase limit, structural stops
  with a 15 % max-risk filter.
- JSON (`output/signals.json`) and Markdown (`output/report.md`) outputs.
- `test_scan.py`: synthetic-data tests for each detector, a random-walk
  false-positive sweep (1.5 % on 200 series), robustness and symbol tests.
- `.github/workflows/daily-scan.yml`: GitHub Actions job (02:00 UTC daily +
  manual dispatch) that runs the tests and the scan and commits
  `output/report.md` + `output/signals.json`.
- `run_daily.sh`: self-healing wrapper (venv, dependency install, dated logs)
  for local runs.
- `test_scan.py::test_main_end_to_end`: CLI run with the download mocked.
- `README.md` with rules mapping, parameters table, output schema, limitations.

### Changed
- `output/` is now committed (by CI) instead of git-ignored; `logs/` stays ignored.
- Architecture: scan runs on GitHub Actions, not on the user's machine — both
  Claude environments block market-data hosts.

### Known issues
- Validated on synthetic data only; real-market validation pending first runs.
