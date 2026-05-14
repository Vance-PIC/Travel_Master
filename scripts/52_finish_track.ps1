#!/usr/bin/env pwsh
# 52_finish_track.ps1 - 原子化結案終極工具 (Atomic Closure CLI)
# [v16.13.2] 加入結案前強制 Commit 邏輯，確保分支切換不中斷

param(
    [Parameter(Mandatory=$true)]
    [string]$TrackID,
    [switch]$Force
)

$OutputEncoding = [System.Text.Encoding]::UTF8
$ROOT_DIR = "$PSScriptRoot\.."
$DASHBOARD_PATH = "$ROOT_DIR\conductor\tracks.md"
$ARCHIVE_BASE = "$ROOT_DIR\knowledge\archive\specs"

Write-Host "`n--- [SPORT ITS] Atomic Track Closure Protocol ---" -ForegroundColor Cyan
Write-Host "目標任務 ID: $TrackID"
Write-Host "--------------------------------------------------"

# 1. 交付合規審計 (Gate-P4)
Write-Host "步驟 1: 安全審計 (Gate-P4)..." -ForegroundColor Yellow
if (-not $Force) {
    & pwsh -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\40_gate-p4-handover.ps1" $TrackID
    if ($LASTEXITCODE -ne 0) {
        Write-Error "審計失敗！結案中斷。"
        exit 1
    }
}

# 2. 雲端資源釋放 (Teardown)
Write-Host "`n步驟 2: 釋放雲端影子部署資源..." -ForegroundColor Yellow
& pwsh -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\53_teardown_track.ps1" $TrackID

# 3. 物理檔案搬移 (specs -> archive)
Write-Host "`n步驟 3: 物理歸檔 (Moving specs to Archive)..." -ForegroundColor Yellow
$trackFolder = Get-ChildItem "$ROOT_DIR\specs" -Directory | Where-Object { $_.Name -match "^$TrackID" } | Select-Object -First 1
if ($trackFolder) {
    if (-not (Test-Path $ARCHIVE_BASE)) { New-Item -Path $ARCHIVE_BASE -ItemType Directory -Force | Out-Null }
    Move-Item -Path $trackFolder.FullName -Destination $ARCHIVE_BASE -Force
    Write-Host "  - [OK] 已搬移 $($trackFolder.Name) 至歸檔區。" -ForegroundColor Green
}

# 4. 更新看板導航 (v16.15.0 Precision Update)
Write-Host "`n步驟 4: 更新看板導航與狀態..." -ForegroundColor Yellow
if (Test-Path $DASHBOARD_PATH) {
    # 使用標準化同步工具執行結案打卡，這會自動處理歸檔路徑與狀態變更
    & pwsh -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\90_sync_dashboard.ps1" -TrackID $TrackID -Status "[DONE]" -Phase "Phase 5"
    Write-Host "  - [OK] 看板已透過標準化工具同步至 DONE 狀態。" -ForegroundColor Green
}

# 5. 【關鍵加固】鎖定結案事實 (Closure Snapshot)
Write-Host "`n步驟 5: 鎖定結案物理快照 (Commit before branch switch)..." -ForegroundColor Yellow
git add -A  # 同步新增、修改與刪除
git commit -m "[Governance] Closure Snapshot for $TrackID" --no-verify
if ($LASTEXITCODE -ne 0 -and -not $Force) {
    Write-Warning "無變更需要提交或 Commit 失敗。"
}

# 6. Git 原子化收尾
Write-Host "`n步驟 6: Git 主線合併與分支清理..." -ForegroundColor Yellow
$currentBranch = git rev-parse --abbrev-ref HEAD
if ($currentBranch -match "^track/") {
    git checkout master
    git merge $currentBranch --no-ff -m "[Closure] Atomically closed track $TrackID"
    git branch -d $currentBranch
    Write-Host "  - [OK] 已完成合併與分支清理。" -ForegroundColor Green
} else {
    Write-Host "  - 目前已在 master 分支，跳過合併動作。" -ForegroundColor Gray
}

Write-Host "`n[成功] 任務 $TrackID 已完成原子化結案。" -ForegroundColor Green