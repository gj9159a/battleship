$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $RepoRoot

Write-Host '==> Backend: create venv and install dependencies'
if (-not (Test-Path "backend/.venv/Scripts/python.exe")) {
  py -3 -m venv backend/.venv
}
& "backend/.venv/Scripts/python.exe" -m pip install --upgrade pip
& "backend/.venv/Scripts/python.exe" -m pip install -e "backend[dev]"

Write-Host '==> Frontend: npm ci'
npm --prefix frontend ci

Write-Host '==> Desktop: npm ci'
npm --prefix desktop ci

Write-Host 'Setup completed.'
