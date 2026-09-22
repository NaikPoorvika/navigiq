# Start NavigIQ for local development: services, backend and frontend.
# Usage (from the repo root):  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1

$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"

Write-Host "Starting database, Redis and OSRM..."
docker compose -f (Join-Path $root "infrastructure\docker-compose.yml") up -d db redis osrm-car osrm-foot
if ($LASTEXITCODE -ne 0) { Write-Host "Docker failed - is Docker Desktop running?" -ForegroundColor Red; exit 1 }

Write-Host "Starting backend on http://localhost:8000 ..."
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$root\backend'; `$host.UI.RawUI.WindowTitle = 'NavigIQ backend'; " +
  "`$env:DATABASE_URL = 'postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq'; " +
  "& '$python' -m uvicorn app.main:app --port 8000 --reload"
)

Write-Host "Starting frontend on http://localhost:3000 ..."
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$root\frontend'; `$host.UI.RawUI.WindowTitle = 'NavigIQ frontend'; npm run dev"
)

Write-Host "Waiting for the backend..."
for ($i = 0; $i -lt 30; $i++) {
  try { Invoke-RestMethod http://localhost:8000/api/v1/pois/categories -TimeoutSec 2 | Out-Null; break }
  catch { Start-Sleep -Seconds 1 }
}
Start-Process "http://localhost:3000"
Write-Host "Ready. Close the two NavigIQ windows to stop." -ForegroundColor Green