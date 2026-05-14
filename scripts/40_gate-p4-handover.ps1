#!/usr/bin/env pwsh
# 40_gate-p4-handover.ps1 - 交付合規審計 (Gate-P4)
# [v16.13.2] 修復主分支名稱與路徑定位

param($TrackID)

$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorCount = 0
$ROOT_DIR = "$PSScriptRoot\.."
$constPath = "$ROOT_DIR\Source Code\00_Config_Constants.gs"
$historyPath = "$ROOT_DIR\knowledge\RELEASE_HISTORY.md"

Write-Host "`n[Audit] 開始 Phase 4 強化交付檢查" -ForegroundColor Cyan
Write-Host "--------------------------------------------------"

# 1. 分支同步 (主分支為 master)
Write-Host "[1/5] 檢查主分支 (master) 同步狀態..."
$MergeBase = git merge-base HEAD master
$MasterTip = git rev-parse master
if ($MergeBase -ne $MasterTip) {
    Write-Host "  - 失敗：與 master 分支不同步。請先執行 git merge master。" -ForegroundColor Red
    $ErrorCount++
} else {
    Write-Host "  - 成功。" -ForegroundColor Green
}

# 2. V 版號
Write-Host "[2/5] 檢查版本號 (V)..."
if (Test-Path $constPath) {
    $constContent = Get-Content $constPath -Raw
    $LocalV = "UNKNOWN"
    if ($constContent -match 'v:\s*"([^"]+)"') { $LocalV = $Matches[1] }
    Write-Host "  - 本地版本號：$LocalV"
} else {
    Write-Host "  - [X] 找不到 Constants.gs ($constPath)" -ForegroundColor Red
    $ErrorCount++
}

# 3. Release Note
Write-Host "[3/5] 檢查發布日誌 (Release Note)..."
if (Test-Path $historyPath) {
    $HistoryContent = Get-Content $historyPath -Raw -Encoding UTF8
    if ($HistoryContent -notmatch $LocalV) {
        Write-Host "  - 失敗：RELEASE_HISTORY.md 中缺少 $LocalV 的條目。" -ForegroundColor Red
        $ErrorCount++
    } else {
        Write-Host "  - 成功。" -ForegroundColor Green
    }
} else {
    Write-Host "  - [X] 找不到 RELEASE_HISTORY.md" -ForegroundColor Red
    $ErrorCount++
}

# 4. R 號檢測
Write-Host "[4/5] 檢查修訂號 (R)..."
if ($constContent -match 'r:\s*(\d+)') { 
    $r = $Matches[1]
    Write-Host "  - 當前 R 號：$r"
}

# 5. Git Status
Write-Host "[5/5] 檢查工作區狀態 (Git Status)..."
$GitStatus = git status --porcelain | Where-Object { $_ -match "Source Code/" -or $_ -match "specs/" -or $_ -match "scripts/" }
if ($GitStatus) {
    Write-Host "  - 失敗：工作區尚有未提交的變更。" -ForegroundColor Red
    $ErrorCount++
} else {
    Write-Host "  - 成功。" -ForegroundColor Green
}

Write-Host "--------------------------------------------------"
if ($ErrorCount -eq 0) {
    Write-Host "[結果] Phase 4 交付審計通過！" -ForegroundColor Green
    exit 0
} else {
    Write-Host "[結果] Phase 4 交付審計失敗" -ForegroundColor Red
    exit 1
}