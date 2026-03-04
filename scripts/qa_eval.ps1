# scripts/qa_eval.ps1
# Full QA check: pytest + eval harness (mock mode).
# Usage: pwsh scripts/qa_eval.ps1
#
# Exits non-zero if pytest fails OR eval reports any failures.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Push-Location $root

try {
    Write-Host "`n=== 1/2  pytest ===" -ForegroundColor Cyan
    py -m pytest tests/ -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "pytest FAILED." -ForegroundColor Red
        exit 1
    }

    Write-Host "`n=== 2/2  eval harness (mock) ===" -ForegroundColor Cyan
    py eval_runner.py --group-by-tag --show-failures
    if ($LASTEXITCODE -ne 0) {
        Write-Host "eval harness FAILED." -ForegroundColor Red
        exit 1
    }

    Write-Host "`nQA: OK — all tests pass, eval 100% accurate." -ForegroundColor Green
}
finally {
    Pop-Location
}
