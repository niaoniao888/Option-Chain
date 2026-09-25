$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { & (Join-Path $PSScriptRoot 'setup.ps1') }
& $python -c 'import fastapi, uvicorn, tzdata'
if ($LASTEXITCODE -ne 0) { & (Join-Path $PSScriptRoot 'setup.ps1') }
$env:PYTHONPATH = Join-Path $projectRoot 'src'
if (-not $env:OPTIONS_APP_ROOT) { $env:OPTIONS_APP_ROOT = $projectRoot }
Push-Location $projectRoot
try {
    & $python -m options_panel @args
    if ($LASTEXITCODE -ne 0) { throw 'Panel startup failed. Check whether the port is already in use.' }
} finally { Pop-Location }
