param([switch]$Development)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    python -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 is recommended. Creating the virtual environment failed.' }
}
$lockFile = if ($Development) { 'requirements-dev.lock' } else { 'requirements.lock' }
& $python -m pip install -r (Join-Path $projectRoot $lockFile)
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network and retry.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
