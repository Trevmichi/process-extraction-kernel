# ontology_audit.ps1
# Scans src/**/*.py for Action/Decision type literals not in the ontology.

$rootDir  = Split-Path -Parent $PSScriptRoot
$ontologyPath = Join-Path $rootDir "src\ontology.py"

# ---------------------------------------------------------------------------
# Parse VALID_ACTIONS / VALID_DECISIONS from src/ontology.py
# ---------------------------------------------------------------------------
$ontologyContent = Get-Content $ontologyPath -Raw

function Get-SetValues {
    param([string]$content, [string]$varName)
    # Match:  VARNAME: Set[str] = { ... }
    if ($content -match "(?s)${varName}\s*:\s*Set\[str\]\s*=\s*\{([^}]+)\}") {
        $block = $Matches[1]
        $values = [regex]::Matches($block, '"([^"]+)"') | ForEach-Object { $_.Groups[1].Value }
        return [string[]]$values
    }
    return [string[]]@()
}

$validActions   = Get-SetValues -content $ontologyContent -varName "VALID_ACTIONS"
$validDecisions = Get-SetValues -content $ontologyContent -varName "VALID_DECISIONS"

Write-Host "Loaded VALID_ACTIONS   ($($validActions.Count)): $($validActions -join ', ')"
Write-Host "Loaded VALID_DECISIONS ($($validDecisions.Count)): $($validDecisions -join ', ')"
Write-Host ""

# ---------------------------------------------------------------------------
# Grep src/**/*.py for Action(type="...") and Decision(type="...")
# ---------------------------------------------------------------------------
$srcDir  = Join-Path $rootDir "src"
$pyFiles = Get-ChildItem -Path $srcDir -Recurse -Filter "*.py"

# key = literal value, value = list of "filename:lineno" strings
$foundActions   = [ordered]@{}
$foundDecisions = [ordered]@{}

foreach ($file in $pyFiles) {
    $lineNum = 0
    foreach ($line in (Get-Content $file.FullName)) {
        $lineNum++
        $loc = "$($file.Name):$lineNum"

        # Action(type="VALUE")  or  Action(type='VALUE')
        if ($line -match "Action\s*\(\s*type\s*=\s*[`"']([^`"']+)[`"']") {
            $val = $Matches[1]
            if (-not $foundActions.Contains($val)) { $foundActions[$val] = [System.Collections.Generic.List[string]]::new() }
            $foundActions[$val].Add($loc)
        }

        # Decision(type="VALUE")  or  Decision(type='VALUE')
        if ($line -match "Decision\s*\(\s*type\s*=\s*[`"']([^`"']+)[`"']") {
            $val = $Matches[1]
            if (-not $foundDecisions.Contains($val)) { $foundDecisions[$val] = [System.Collections.Generic.List[string]]::new() }
            $foundDecisions[$val].Add($loc)
        }
    }
}

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
$issues = 0

Write-Host '=== Action(type=...) literals ==='
foreach ($val in ($foundActions.Keys | Sort-Object)) {
    $ok   = $validActions -contains $val
    $tag  = if ($ok) { "OK             " } else { "NOT IN ONTOLOGY" }
    $locs = $foundActions[$val] -join ", "
    Write-Host ("  [$tag] '$val'  --  $locs")
    if (-not $ok) { $issues++ }
}

Write-Host ""
Write-Host '=== Decision(type=...) literals ==='
foreach ($val in ($foundDecisions.Keys | Sort-Object)) {
    $ok   = $validDecisions -contains $val
    $tag  = if ($ok) { "OK             " } else { "NOT IN ONTOLOGY" }
    $locs = $foundDecisions[$val] -join ", "
    Write-Host ("  [$tag] '$val'  --  $locs")
    if (-not $ok) { $issues++ }
}

Write-Host ""
if ($issues -eq 0) {
    Write-Host "All Action/Decision type literals are in the ontology. No issues found."
} else {
    Write-Host "$issues literal(s) NOT in ontology."
    exit 1
}
