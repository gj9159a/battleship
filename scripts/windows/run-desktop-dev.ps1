$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $RepoRoot

$BackendPython = Join-Path $RepoRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path $BackendPython)) {
  throw "Backend python not found: $BackendPython. Run scripts/windows/setup-dev.ps1 first."
}

$env:BATTLESHIP_BACKEND_DIR = Join-Path $RepoRoot 'backend'
$env:BATTLESHIP_PYTHON = $BackendPython

npm --prefix desktop run dev
