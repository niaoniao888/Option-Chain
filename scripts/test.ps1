$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $projectRoot "src"
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts/setup.ps1 -Development first.' }
Push-Location $projectRoot
try {
  & $python -m unittest discover -s tests -p "test_*.py"
  if ($LASTEXITCODE -ne 0) { throw 'Python tests failed.' }
  node tests/test_ui.js
  if ($LASTEXITCODE -ne 0) { throw 'UI tests failed.' }
  node tests/test_guide.js
  if ($LASTEXITCODE -ne 0) { throw 'Guide tests failed.' }
  node tests/test_bootstrap.js
  if ($LASTEXITCODE -ne 0) { throw 'Page bootstrap tests failed.' }
} finally {
  Pop-Location
}
