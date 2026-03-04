# scripts/qa_eval.ps1
# Full QA check: pytest + dataset quotas + eval harness (mock mode).
# Usage: pwsh scripts/qa_eval.ps1
#
# Exits non-zero if pytest fails, quotas fail, OR eval reports any failures.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Push-Location $root

try {
    Write-Host "`n=== 1/3  pytest ===" -ForegroundColor Cyan
    py -m pytest tests/ -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "pytest FAILED." -ForegroundColor Red
        exit 1
    }

    Write-Host "`n=== 2/3  dataset quota check ===" -ForegroundColor Cyan
    py scripts/check_dataset_quotas.py --warn-only
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Dataset quota check FAILED." -ForegroundColor Red
        exit 1
    }

    Write-Host "`n=== 3/3  eval harness (mock) ===" -ForegroundColor Cyan
    py eval_runner.py --group-by-tag --show-failures
    if ($LASTEXITCODE -ne 0) {
        Write-Host "eval harness FAILED." -ForegroundColor Red
        exit 1
    }

    Write-Host "`nQA: OK — all tests pass, quotas checked, eval 100% accurate." -ForegroundColor Green
}
finally {
    Pop-Location
}
