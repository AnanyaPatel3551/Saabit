<#
.SYNOPSIS
  Project tasks (stands in for a Makefile on Windows).
.EXAMPLE
  .\tasks.ps1 test
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('dev-backend', 'dev-frontend', 'test', 'lint')]
    [string]$Task
)

$ErrorActionPreference = 'Stop'
$Backend = Join-Path $PSScriptRoot 'backend'
$Frontend = Join-Path $PSScriptRoot 'frontend'
$Python = Join-Path $Backend '.venv\Scripts\python.exe'

if ($Task -ne 'dev-frontend' -and -not (Test-Path $Python)) {
    Write-Error "No venv at $Python. Run: py -3.11 -m venv backend\.venv"
}

$Location = if ($Task -eq 'dev-frontend') { $Frontend } else { $Backend }
Push-Location $Location
try {
    switch ($Task) {
        'dev-backend'  { & $Python -m uvicorn app.main:app --reload --port 8000 }
        'dev-frontend' { npm run dev }
        'test'         { & $Python -m pytest }
        'lint'         { & $Python -m ruff check . }
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
