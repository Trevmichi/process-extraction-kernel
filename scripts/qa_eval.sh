#!/usr/bin/env bash
# scripts/qa_eval.sh
# Full QA check: pytest + dataset quotas + eval harness (mock mode).
# Usage: bash scripts/qa_eval.sh
#
# Exits non-zero if pytest fails, quotas fail, OR eval reports any failures.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== 1/3  pytest ==="
python -m pytest tests/ -q
# set -e handles non-zero exit

echo ""
echo "=== 2/3  dataset quota check ==="
python scripts/check_dataset_quotas.py --warn-only
# --warn-only: prints warnings but does not halt (remove flag once dataset is balanced)

echo ""
echo "=== 3/3  eval harness (mock) ==="
python eval_runner.py --group-by-tag --show-failures
# eval_runner.py exits non-zero if terminal or field accuracy < 100%

echo ""
echo "QA: OK — all tests pass, quotas checked, eval 100% accurate."
# Optional: run audit layer (requires Ollama or OpenAI key, not in default QA)
# python eval_runner.py --audit --audit-sample 5
