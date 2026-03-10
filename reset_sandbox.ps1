Set-Location (Join-Path $PSScriptRoot "..")
Remove-Item -Path .\process-extraction-kernel-sandbox\* -Recurse -Force
$BannedItems = @(".git", ".venv", "__pycache__", ".pytest_cache", "secret_key.txt", ".env")
Copy-Item -Path .\process-extraction-kernel\* -Destination .\process-extraction-kernel-sandbox -Recurse -Exclude $BannedItems
Write-Host "Sandbox reset complete!" -ForegroundColor Green
