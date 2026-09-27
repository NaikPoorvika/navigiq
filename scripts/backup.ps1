# Bundles everything needed to rebuild NavigIQ on another machine.
#
# Included: all source, configuration, migrations, docs, tests, and the
# category photos. Also .env files, which git deliberately ignores - they
# hold secrets, so keep this archive off GitHub and off shared drives.
#
# Excluded: node_modules, __pycache__, the venv, OSRM graphs and the OSM
# extract. Those are rebuilt from the pipelines, and they are gigabytes.
#
#   powershell -ExecutionPolicy Bypass -File scripts\backup.ps1

$root = Split-Path $PSScriptRoot -Parent
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$out = Join-Path $HOME "navigiq-backup-$stamp.zip"
$staging = Join-Path $env:TEMP "navigiq-backup-$stamp"

$include = @(
  "backend\app", "backend\tests", "backend\alembic", "backend\conftest.py",
  "backend\requirements.txt", "backend\pyproject.toml", "backend\alembic.ini",
  "backend\Dockerfile", "backend\.env",
  "frontend\src", "frontend\e2e", "frontend\public",
  "frontend\package.json", "frontend\package-lock.json", "frontend\tsconfig.json",
  "frontend\vite.config.ts", "frontend\index.html", "frontend\playwright.config.ts",
  "frontend\Dockerfile", "frontend\.gitignore",
  "data\pipelines", "data\config", "data\mappings",
  "infrastructure\docker-compose.yml", "infrastructure\database",
  "infrastructure\.env",
  "scripts",
  "README.md", "DECISIONS.md", "TASKS.md", "ARCHITECTURE.md", "CLAUDE.md",
  ".gitignore"
)

Write-Host "Collecting..."
New-Item -ItemType Directory -Force $staging | Out-Null
$missing = @()
foreach ($rel in $include) {
  $src = Join-Path $root $rel
  if (-not (Test-Path $src)) { $missing += $rel; continue }
  $dest = Join-Path $staging $rel
  New-Item -ItemType Directory -Force (Split-Path $dest -Parent) | Out-Null
  if (Test-Path $src -PathType Container) {
    # /XD skips folders that are rebuilt, never backed up.
    robocopy $src $dest /E /NFL /NDL /NJH /NJS /NP `
      /XD node_modules __pycache__ .pytest_cache .vite dist .output `
          test-results playwright-report cache | Out-Null
  } else {
    Copy-Item $src $dest
  }
}

if ($missing) { Write-Host "Not found (skipped): $($missing -join ', ')" -ForegroundColor Yellow }

Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $out -Force
Remove-Item -Recurse -Force $staging

$size = [math]::Round((Get-Item $out).Length / 1MB, 1)
Write-Host "`nSaved $out  ($size MB)" -ForegroundColor Green
Write-Host "Contains .env files - do not commit or share this archive." -ForegroundColor Yellow