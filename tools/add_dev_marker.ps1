# add_dev_marker.ps1
# Creates the _dev_mode marker file in elastic_fit/, enabling dev mode in Blender.

$root   = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$marker = Join-Path $root "elastic_fit\_dev_mode"

New-Item -ItemType File -Path $marker -Force | Out-Null
Write-Host "Dev mode enabled: $marker" -ForegroundColor Green
