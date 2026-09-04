#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_daily.sh — one-shot wrapper used by the scheduled Claude task.
#
# Why a wrapper: the scheduled task runs in a fresh shell on the user's
# machine every morning.  This script makes the run self-healing (creates the
# venv and installs dependencies if they are missing), pins the working
# directory, and writes everything to ./output so the caller only has to read
# output/report.md and output/signals.json.
#
# Usage:  bash run_daily.sh [extra scan.py args]
# Exit codes: 0 ok, 2 no price data (network problem), other = python error.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
VENV=".venv"

# Create an isolated environment on first run so we never fight system pip.
if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
. "$VENV/bin/activate"

# Install / upgrade only when requirements changed (cheap check via checksum).
# sha256sum is GNU coreutils; older macOS only has shasum.
if command -v sha256sum >/dev/null 2>&1; then
  REQ_SUM=$(sha256sum requirements.txt | cut -d' ' -f1)
else
  REQ_SUM=$(shasum -a 256 requirements.txt | cut -d' ' -f1)
fi
if [ ! -f "$VENV/.req.sum" ] || [ "$(cat "$VENV/.req.sum")" != "$REQ_SUM" ]; then
  pip install -q --upgrade pip
  pip install -q --require-hashes -r requirements.txt
  echo "$REQ_SUM" > "$VENV/.req.sum"
fi

mkdir -p output logs
STAMP=$(date +%Y-%m-%d)
# Keep a dated copy of each report for later review; output/report.md is
# always the latest.
python scan.py --out-dir output "$@" 2> "logs/scan-$STAMP.log"
cp output/report.md "logs/report-$STAMP.md"
echo "OK: report written to output/report.md (log: logs/scan-$STAMP.log)"
