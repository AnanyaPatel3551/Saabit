<#
.SYNOPSIS
  Project tasks (stands in for a Makefile on Windows).
.EXAMPLE
  .\tasks.ps1 test
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('dev-backend', 'dev-frontend', 'test', 'test-live', 'lint', 'eval',
                 'eval-robustness')]
    [string]$Task,
    # Extra arguments for eval, e.g. .\tasks.ps1 eval --limit 5
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest = @()
)

$ErrorActionPreference = 'Stop'
$Backend = Join-Path $PSScriptRoot 'backend'
$Frontend = Join-Path $PSScriptRoot 'frontend'
$Python = Join-Path $Backend '.venv\Scripts\python.exe'

if ($Task -ne 'dev-frontend' -and -not (Test-Path $Python)) {
    Write-Error "No venv at $Python. Run: py -3.11 -m venv backend\.venv"
}

# Local secrets: uvicorn loads ..\.env itself (--env-file). The app never reads .env.
$EnvFile = Join-Path $PSScriptRoot '.env'
$EnvArgs = if (Test-Path $EnvFile) { @('--env-file', $EnvFile) } else { @() }

# eval and test-live run in this process tree, so copy KEY=VALUE lines from .env into its
# environment only.
function Import-EnvFile {
    if (-not (Test-Path $EnvFile)) { return }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            Set-Item -Path "Env:$($Matches[1])" -Value ($Matches[2].Trim('"').Trim("'"))
        }
    }
}

$Location = if ($Task -eq 'dev-frontend') { $Frontend } else { $Backend }
Push-Location $Location
try {
    switch ($Task) {
        'dev-backend'  { & $Python -m uvicorn app.main:app --reload --port 8000 --no-access-log @EnvArgs }
        'dev-frontend' { npm run dev }
        # Never the live LLM tests, even when keys are in the shell: they spend rate limits.
        'test' {
            & $Python -m pytest -m "not live" | Tee-Object -Variable testOutput
            $testCode = $LASTEXITCODE
            # Record the passed count for the "How we test" page (eval\results\tests.json).
            $summary = ($testOutput | Select-String -Pattern '(\d+) passed' | Select-Object -Last 1)
            if ($testCode -eq 0 -and $summary) {
                $passed = [int]$summary.Matches[0].Groups[1].Value
                $skippedMatch = [regex]::Match($summary.Line, '(\d+) skipped')
                $skipped = if ($skippedMatch.Success) { [int]$skippedMatch.Groups[1].Value } else { 0 }
                $record = @{ passed = $passed; skipped = $skipped; date = (Get-Date -Format 'yyyy-MM-dd') }
                $record | ConvertTo-Json | Out-File -Encoding ascii (Join-Path $PSScriptRoot 'eval\results\tests.json')
            }
            exit $testCode
        }
        'test-live' {
            Import-EnvFile
            & $Python -m pytest -m live
        }
        'lint'         { & $Python -m ruff check . }
        'eval' {
            Import-EnvFile
            & $Python (Join-Path $PSScriptRoot 'eval\eval.py') @Rest
            $evalCode = $LASTEXITCODE
            & $Python (Join-Path $PSScriptRoot 'eval\robustness.py')
            if ($evalCode -ne 0) { exit $evalCode }
        }
        'eval-robustness' { & $Python (Join-Path $PSScriptRoot 'eval\robustness.py') }
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
