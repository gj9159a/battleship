$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $RepoRoot

$Launcher = Join-Path $RepoRoot 'scripts/windows/Start-Battleship.cmd'
if (-not (Test-Path $Launcher)) {
  throw "Launcher not found: $Launcher"
}

cmd /c $Launcher
