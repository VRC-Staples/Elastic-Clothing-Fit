# dev-install.ps1
# Uninstalls elastic_fit if present, packages the current source,
# and reinstalls it into Blender. Run from any directory.
#
# Usage: .\dev-install.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host ""
Write-Host "Elastic Clothing Fit -- dev install" -ForegroundColor Cyan
Write-Host "------------------------------------" -ForegroundColor Cyan

python tools/deploy.py install

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Done. Reload scripts in Blender to pick up the new build." -ForegroundColor Green
    Write-Host "(Edit > Preferences > Add-ons > Elastic Clothing Fit > Reload)" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "Install failed -- check output above." -ForegroundColor Red
    exit $LASTEXITCODE
}
