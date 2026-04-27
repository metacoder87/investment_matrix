# start_app.ps1

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   CryptoInsight - Safe Start             " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Startup (No Rebuild/Volume Removal)
Write-Host "`n[1/2] Starting services..." -ForegroundColor Yellow
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error during startup. Exiting." -ForegroundColor Red
    exit 1
}

# 2. Wait for API
Write-Host "`n[2/2] Waiting for API to be ready..." -ForegroundColor Yellow
$maxRetries = 30
$retryCount = 0
$healthy = $false

while ($retryCount -lt $maxRetries) {
    Start-Sleep -Seconds 2
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/health" -Method Get -UseBasicParsing -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    }
    catch {
        Write-Host -NoNewline "."
    }
    $retryCount++
}

if (-not $healthy) {
    Write-Host "`nAPI did not become ready in time. Please check logs." -ForegroundColor Red
    exit 1
}
Write-Host "`nAPI is up and running!" -ForegroundColor Green

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   App Started!                           " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Frontend:    http://localhost:3000" -ForegroundColor Green
Write-Host "API Docs:    http://localhost:8000/docs" -ForegroundColor Green
Write-Host "Health Check: http://localhost:8000/api/health" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
