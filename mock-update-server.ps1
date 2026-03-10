# mock-update-server.ps1
# Launches the mock GitHub releases API server for testing the auto-updater.
#
# Usage: .\mock-update-server.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host ""
Write-Host "Elastic Clothing Fit -- mock update server" -ForegroundColor Cyan
Write-Host "------------------------------------------" -ForegroundColor Cyan

python tools/mock_update_server.py
