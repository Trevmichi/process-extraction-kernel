#!/usr/bin/env bash
# scripts/qa_eval.sh
# Full QA check: pytest + eval harness (mock mode).
# Usage: bash scripts/qa_eval.sh
#
# Exits non-zero if pytest fails OR eval reports any failures.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== 1/2  pytest ==="
python -m pytest tests/ -q
# set -e handles non-zero exit

echo ""
echo "=== 2/2  eval harness (mock) ==="
python eval_runner.py --group-by-tag --show-failures
# eval_runner.py exits non-zero if terminal or field accuracy < 100%

echo ""
echo "QA: OK — all tests pass, eval 100% accurate."
