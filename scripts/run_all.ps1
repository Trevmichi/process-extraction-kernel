# scripts/run_all.ps1
# One-command "real run": test → patch → batch → UI
# Usage: pwsh scripts/run_all.ps1
#
# Stops on first failure (pytest or patch_logic).
# batch_runner and streamlit are best-effort.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Push-Location $root

try {
    Write-Host "`n=== 1/4  pytest ===" -ForegroundColor Cyan
    py -m pytest tests/ -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "pytest FAILED — aborting." -ForegroundColor Red
        exit 1
    }

    Write-Host "`n=== 2/4  patch_logic ===" -ForegroundColor Cyan
    py patch_logic.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "patch_logic FAILED — aborting." -ForegroundColor Red
        exit 1
    }

    Write-Host "`n=== 3/4  batch_runner ===" -ForegroundColor Cyan
    py -m batch_runner
    # Non-fatal: batch_runner may fail if Ollama is not running
    if ($LASTEXITCODE -ne 0) {
        Write-Host "batch_runner returned non-zero (Ollama down?) — continuing." -ForegroundColor Yellow
    }

    Write-Host "`n=== 4/4  streamlit ===" -ForegroundColor Cyan
    Write-Host "Launching Streamlit UI (Ctrl+C to stop) ..." -ForegroundColor Green
    streamlit run app.py
}
finally {
    Pop-Location
}
