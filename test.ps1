$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Сначала создайте .venv" }
$env:PYTHONPATH = $PSScriptRoot
& $Python -m pytest -ra
& $Python -m scripts.smoke_test_mcp

& $Python -m scripts.smoke_test_business
