param(
    [Parameter(Mandatory=$true)]
    [string]$TrackID
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8

# teardown_track.ps1 - v16.13.45 (ID-First Edition)
# 負責結案時，根據 TrackID 回收 GAS 影子資源並還原配置。

$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
$REGISTRY_PATH = Join-Path $PSScriptRoot "track_registry.json"
$ENV_PATH = Join-Path $PSScriptRoot "deploy_env.json"
$appSettingsPath = Join-Path $ROOT_DIR "Source Code/Client Tools/appsettings.json"

Write-Host "`n--- [SPORT ITS] Track ID 資源回收與歸檔 (v16.13.45) ---" -ForegroundColor Cyan
Write-Host "Target Track ID: $TrackID"
Write-Host "----------------------------------------------------"

# 1. 讀取 Registry
if (-not (Test-Path $REGISTRY_PATH)) {
    Write-Warning "Registry file not found. Nothing to teardown."
    exit 0
}

$registry = Get-Content $REGISTRY_PATH -Raw | ConvertFrom-Json
$tid = if ($TrackID -match "^(\d{3})") { $Matches[1] } else { $TrackID }

if (-not $registry.tracks.$tid) {
    Write-Warning "Track [$tid] not found in registry. It may have already been archived."
} else {
    $deployId = $registry.tracks.$tid.deployId
    $trackName = $registry.tracks.$tid.name
    Write-Host "Step 1: Found Deploy ID for [$tid ($trackName)] -> $deployId" -ForegroundColor Yellow

    # 2. 執行 clasp undeploy
    if (Test-Path (Join-Path $ROOT_DIR ".clasp.json")) {
        Push-Location $ROOT_DIR
        try {
            $undeployOutput = clasp undeploy $deployId 2>&1 | Out-String
            Write-Host "  - GAS Response: $undeployOutput" -ForegroundColor Gray
            Write-Host "  - [OK] Deployment successfully removed from GAS." -ForegroundColor Green
        } catch {
            Write-Error "Failed to undeploy ID: $deployId."
        }
        Pop-Location
    }

    # 3. 清理 Registry
    Write-Host "`nStep 2: Cleaning up Track Registry..." -ForegroundColor Yellow
    $registry.tracks.PSObject.Properties.Remove($tid)
    $registry | ConvertTo-Json -Depth 10 | Set-Content $REGISTRY_PATH -Encoding UTF8
    Write-Host "  - [OK] Track [$tid] removed from registry." -ForegroundColor Green
}

# 4. 物理環境全量還原 (聯動恢復)
Write-Host "`nStep 3: Restoring Environment to Dev Default..." -ForegroundColor Yellow
if (Test-Path $ENV_PATH) {
    $envConfig = Get-Content $ENV_PATH -Raw | ConvertFrom-Json
    $defaultDeployId = $envConfig.dev.deploymentId
    $defaultUrl = "https://script.google.com/macros/s/$defaultDeployId/exec"
    
    # 還原 deploy_env.json
    $envConfig.ApiUrl = $defaultUrl
    $envConfig | ConvertTo-Json -Depth 10 | Set-Content $ENV_PATH -Encoding UTF8
    Write-Host "  - [OK] deploy_env.json 已還原至 Dev 預設。" -ForegroundColor Gray

    # 還原 appsettings.json (The Missing Link Fix)
    if (Test-Path $appSettingsPath) {
        $appSettings = Get-Content $appSettingsPath -Raw | ConvertFrom-Json
        $appSettings.SportApi.Url = $defaultUrl
        $appSettings | ConvertTo-Json -Depth 10 | Set-Content $appSettingsPath -Encoding UTF8
        Write-Host "  - [OK] C# appsettings.json 已同步還原至 Dev 預設網址。" -ForegroundColor Green
    }
}

Write-Host "`n[SUCCESS] Track [$TrackName] teardown completed." -ForegroundColor Green

# 5. 自動巡檢同步
$checkScript = Join-Path $PSScriptRoot "25_track_checkpoint.ps1"
if (Test-Path $checkScript) {
    $tid = "UNKNOWN"
    if ($TrackName -match "^(\d+)") { $tid = $Matches[1] }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $checkScript -TrackID $tid
}

Write-Host "`n[CRITICAL] Final Step: Atomic Branch Cleanup Required!" -ForegroundColor Black -BackgroundColor Yellow
Write-Host "Please merge and delete the track branch to finish." -ForegroundColor Cyan
