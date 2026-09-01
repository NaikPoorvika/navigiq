# setup_osrm.ps1
# Script to download a lightweight OSM map and preprocess it for OSRM

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectDir = Split-Path -Parent $ScriptDir
$DataDir = Join-Path $ProjectDir "infrastructure\osrm-data"

# Create data directory if it doesn't exist
if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
}

Write-Host "Running OSRM Extract..." -ForegroundColor Cyan
docker run --rm -t -v "$($DataDir):/data" osrm/osrm-backend:latest osrm-extract -p /opt/car.lua /data/map.osm

Write-Host "Running OSRM Partition..." -ForegroundColor Cyan
docker run --rm -t -v "$($DataDir):/data" osrm/osrm-backend:latest osrm-partition /data/map.osrm

Write-Host "Running OSRM Customize..." -ForegroundColor Cyan
docker run --rm -t -v "$($DataDir):/data" osrm/osrm-backend:latest osrm-customize /data/map.osrm

Write-Host "OSRM pre-processing complete! You can now start the osrm service using docker-compose." -ForegroundColor Green
