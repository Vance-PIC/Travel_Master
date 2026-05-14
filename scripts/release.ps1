#!/usr/bin/env pwsh
# release.ps1 - v16.16.0 (Strategic Versioning Edition)
# [SSoT] 1. Track: R++ | 2. Dev: V++ & R=1 | 3. Master: Freeze.

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("track", "dev", "master")]
    [string]$Env = "track",
    [string]$TrackID,
    [string]$NewVersion,
    [switch]$SkipAudit
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
$ConstantsPath = Join-Path $ROOT_DIR "Source Code/00_Config_Constants.gs"
$DashboardPath = Join-Path $ROOT_DIR "conductor/tracks.md"
$EnvConfigPath = Join-Path $PSScriptRoot "deploy_env.json"

Write-Host "`n--- [SPORT ITS] 統一發布引擎 (v16.16.0) ---" -ForegroundColor Cyan
Write-Host "目標環境：$($Env.ToUpper())"

# --- 1. 提取事實 (SSoT Extraction) ---
$constantsRaw = Get-Content $ConstantsPath -Raw -Encoding UTF8
if ($constantsRaw -match 'v: "(?<v>[\d.]+)"') { $oldV = $Matches['v'] }
if ($constantsRaw -match 'r: (?<r>\d+)') { $oldR = [int]$Matches['r'] }

# [v16.16.0] 專業版號流轉策略
$newV = $oldV
$newR = $oldR

if ($Env -eq "track") {
    $newR = $oldR + 1
} elseif ($Env -eq "dev") {
    # 自動晉升 Patch 位 (例如 16.15.3 -> 16.15.4)
    if ($oldV -match "(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)") {
        $patch = [int]$Matches['patch'] + 1
        $newV = "$($Matches['major']).$($Matches['minor']).$patch"
        $newR = 1
    }
    if ($NewVersion) { $newV = $NewVersion; $newR = 1 }
}
# Master 保持 $oldV, $oldR 不變 (版號凍結)

$envLabel = if ($Env -eq "track") { "Track $TrackID" } else { $Env }
$tag = "v$newV.r$newR ($envLabel)"

# --- 2. 兩階段 Hash 校準 ---
$targetHash = git rev-parse --short HEAD
Write-Host "[SSoT] 鎖定邏輯基準 Hash: $targetHash" -ForegroundColor Green

$constantsRaw = $constantsRaw -replace "v: `".*?`"", "v: `"$newV`""
$constantsRaw = $constantsRaw -replace "r: \d+", "r: $newR"
$constantsRaw = $constantsRaw -replace "environment: `".*?`"", "environment: `"$Env`""
$constantsRaw = $constantsRaw -replace "last_commit_hash: `".*?`"", "last_commit_hash: `"$targetHash`""
[System.IO.File]::WriteAllText($ConstantsPath, $constantsRaw, $OutputEncoding)

# --- 3. 全環境 ID 偵測 ---
$existingId = $null
if ($Env -eq "track") {
    if ($TrackID -and (Test-Path $DashboardPath)) {
        $dashboardLines = Get-Content $DashboardPath
        foreach ($line in $dashboardLines) {
            if ($line -match "\[0*$($TrackID.TrimStart('0'))\]") {
                $parts = $line -split '\|'
                foreach ($part in $parts) {
                    $foundId = $part.Trim().Replace('`', '')
                    if ($foundId -match "^AKfy") { $existingId = $foundId; break }
                }
                if ($existingId) { break }
            }
        }
    }
} else {
    if (Test-Path $EnvConfigPath) {
        $envCfg = Get-Content $EnvConfigPath -Raw | ConvertFrom-Json
        if ($Env -eq "dev") { $existingId = $envCfg.dev.deploymentId }
        elseif ($Env -eq "master") { $existingId = $envCfg.master.deploymentId }
    }
}

# --- 4. 執行同步與部署 ---
Write-Host "[Step 2] 執行 Clasp PUSH 與 Deploy..." -ForegroundColor Yellow
clasp push -f
if ($LASTEXITCODE -ne 0) { Write-Error "Push 失敗！"; exit 1 }

if ($existingId) {
    Write-Host "  - [Action] 執行原地更新 (Update Deployment): $existingId" -ForegroundColor Green
    $deployOutput = clasp deploy -i $existingId -d "$tag"
} else {
    $deployOutput = clasp deploy -d "$tag"
}

if ($deployOutput -match "(?<id>AKfy[\w-]+)") {
    $deployId = $Matches['id']
    Write-Host "  - [OK] 部署成功：$deployId" -ForegroundColor Green
    if ($Env -eq "track" -and $TrackID) {
        & pwsh -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot/90_sync_dashboard.ps1" -TrackID $TrackID -DeployID $deployId
    }
} else {
    Write-Error "部署失敗！"; exit 1
}

Write-Host "`n[成功] $Env 發布作業完成：v$newV.r$newR" -ForegroundColor Green
