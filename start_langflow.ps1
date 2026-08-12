# =====================================================
#  start_langflow.ps1
#  Launches Langflow with SSRF protection OFF so it can
#  reach your local LandIQ backend on 127.0.0.1:8000
#  Save in:  C:\Users\HP\OneDrive\Desktop\ai_boardroom_v3\
#  Run with: powershell -ExecutionPolicy Bypass -File start_langflow.ps1
# =====================================================

Write-Host ""
Write-Host "=== LandIQ / Langflow launcher ===" -ForegroundColor Cyan

# ---- 1. find and activate the langflow venv ----
$candidates = @(
    "$PSScriptRoot\langflow_env\Scripts\Activate.ps1",
    "$PSScriptRoot\venv_langflow\Scripts\Activate.ps1",
    "$PSScriptRoot\langflow_server\Scripts\Activate.ps1",
    "$PSScriptRoot\langflow_server\venv\Scripts\Activate.ps1",
    "$PSScriptRoot\..\langflow_server\Scripts\Activate.ps1",
    "$PSScriptRoot\..\venv_langflow\Scripts\Activate.ps1"
)

$activated = $false
foreach ($c in $candidates) {
    if (Test-Path $c) {
        Write-Host "[venv] activating: $c" -ForegroundColor Green
        & $c
        $activated = $true
        break
    }
}
if (-not $activated) {
    Write-Host "[venv] no langflow venv found automatically." -ForegroundColor Yellow
    Write-Host "       Activate it manually first, then re-run this script." -ForegroundColor Yellow
}

# ---- 2. disable SSRF protection for local dev ----
$env:LANGFLOW_SSRF_PROTECTION_ENABLED           = "false"
$env:LANGFLOW_CONNECTOR_SSRF_VALIDATION_ENABLED = "false"
$env:LANGFLOW_CONNECTOR_SSRF_ALLOW_LOOPBACK     = "true"
$env:LANGFLOW_SSRF_ALLOWED_HOSTS                = "127.0.0.1,localhost,0.0.0.0,::1"

Write-Host "[ssrf] protection DISABLED for local dev" -ForegroundColor Green
Write-Host "[ssrf] allowed hosts: $env:LANGFLOW_SSRF_ALLOWED_HOSTS" -ForegroundColor Green

# ---- 3. start langflow ----
Write-Host ""
Write-Host "Starting Langflow on http://127.0.0.1:7860 ..." -ForegroundColor Cyan
Write-Host ""

langflow run --host 127.0.0.1 --port 7860
