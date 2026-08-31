$ErrorActionPreference = "SilentlyContinue"

function Check-Command {
    param([string]$cmd, [string]$args)
    Write-Host "Checking $cmd..." -NoNewline
    try {
        $output = & $cmd $args 2>&1
        if ($LASTEXITCODE -eq 0 -or $?) {
            Write-Host " [OK] $output" -ForegroundColor Green
            return $output
        } else {
            Write-Host " [FAILED] Command returned exit code $LASTEXITCODE" -ForegroundColor Red
            return $null
        }
    } catch {
        Write-Host " [MISSING] Not found in PATH" -ForegroundColor Red
        return $null
    }
}

Write-Host "--- NavigIQ Environment Verification ---"
$env_status = @()

$env_status += "## Host Environment Verification"
$env_status += "Date: $(Get-Date)"
$env_status += ""

$env_status += "### Software Prerequisites"
$python = Check-Command "py" "--version"
$env_status += "- Python: $($python -join ' ')"

$node = Check-Command "node" "--version"
$env_status += "- Node.js: $($node -join ' ')"

$npm = Check-Command "npm" "--version"
$env_status += "- npm: $($npm -join ' ')"

$docker = Check-Command "docker" "--version"
$env_status += "- Docker: $($docker -join ' ')"

$git = Check-Command "git" "--version"
$env_status += "- Git: $($git -join ' ')"

$ollama = Check-Command "ollama" "--version"
$env_status += "- Ollama: $($ollama -join ' ')"

$env_status += ""
$env_status += "### Hardware Prerequisites"
$nvidia = Check-Command "nvidia-smi" "--query-gpu=name,memory.total --format=csv,noheader"
if ($nvidia) {
    $env_status += "- GPU: $($nvidia -join ' | ')"
} else {
    $env_status += "- GPU: [MISSING] nvidia-smi not found or failed"
}

$env_status | Out-File -FilePath "..\docs\environment_status.md" -Encoding utf8
Write-Host "Environment verification complete. Results saved to docs\environment_status.md"
