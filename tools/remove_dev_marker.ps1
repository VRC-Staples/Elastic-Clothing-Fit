# remove_dev_marker.ps1
# Removes the _dev_mode marker file from elastic_fit/, disabling dev mode in Blender.

$root   = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$marker = Join-Path $root "elastic_fit\_dev_mode"

if (Test-Path $marker) {
    Remove-Item $marker -Force
    Write-Host "Dev mode disabled: $marker removed." -ForegroundColor Yellow
} else {
    Write-Host "Nothing to do: $marker does not exist." -ForegroundColor DarkGray
}
