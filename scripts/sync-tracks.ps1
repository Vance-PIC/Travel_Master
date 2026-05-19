#!/usr/bin/env pwsh
# scripts/sync-tracks.ps1
# [v1.1.0] 物理同步看板與進度週報 (支援自動偵測 ID)

param (
    [Parameter(Mandatory=$false)]
    [string]$WP_ID = "",    # 例如: 07 (若留空則自動偵測)
    
    [Parameter(Mandatory=$true)]
    [ValidateSet("TRACKING", "REVIEW", "DONE", "PENDING")]
    [string]$Status,   # START -> TRACKING, PRE-REVIEW -> REVIEW, FINISH -> DONE
    
    [string]$Message   # 核心精鍊紀錄
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
$TRACKS_FILE = Join-Path $ROOT_DIR "conductor/doc-tracks.md"
$REPORT_FILE = Join-Path $ROOT_DIR "conductor/progress_report.md"

if (-not (Test-Path $TRACKS_FILE)) { Write-Host "[X] 找不到 $TRACKS_FILE"; exit 1 }
$tracksContent = Get-Content $TRACKS_FILE -Raw -Encoding UTF8

# --- 自動偵測邏輯 ---
if ($WP_ID -eq "") {
    Write-Host "[Auto-Detect] 未提供 WP_ID，嘗試尋找當前執行的 Track..." -ForegroundColor Cyan
    # 尋找當前為 TRACKING 或 IN REVIEW 的項目
    $regexDetect = "(?m)^\|\s*(\d{2})\s*\|.*?(?:\[TRACKING\]|\[IN REVIEW\])"
    if ($tracksContent -match $regexDetect) {
        $WP_ID = $matches[1]
        Write-Host "  -> 成功偵測到活動中的 Track: WP-$WP_ID" -ForegroundColor Green
    } else {
        Write-Host "[X] 無法自動偵測到活動中的 Track，請手動指定 -WP_ID" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n[Sync] 正在物理同步看板狀態 (WP-$WP_ID -> $Status)..." -ForegroundColor Cyan

# --- 對應狀態字眼 ---
$stepMap = @{
    "TRACKING" = "Step 2";
    "REVIEW"   = "Step 7";
    "DONE"     = "Step 8";
    "PENDING"  = "Step 0"
}
$statusMap = @{
    "TRACKING" = "[TRACKING]";
    "REVIEW"   = "[IN REVIEW]";
    "DONE"     = "[DONE]";
    "PENDING"  = "[PENDING]"
}
$auditMap = @{
    "TRACKING" = "⏳ PENDING";
    "REVIEW"   = "⏳ PENDING";
    "DONE"     = "✅ PASS";
    "PENDING"  = "⏳ PENDING"
}

$newStep = $stepMap[$Status]
$newStat = $statusMap[$Status]
$newAudit = $auditMap[$Status]

# --- 讀取並更新 doc-tracks.md ---
# Regex 定位該行並替換狀態 (假設 ID 在第一欄，格式 | ID |)
$regex = "(?m)^\|\s*$WP_ID\s*\|(.*?)\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|"
if ($tracksContent -match $regex) {
    $lineMatch = $matches[0]
    # 拆解欄位 (依序為: 章節名稱 | 座標 | 狀態 | 審計 | 紀錄)
    # 我們只更新 座標(2)、狀態(3)、審計(4)
    if ($Message) {
        $updatedLine = "| $WP_ID | $($matches[1].Trim()) | **$newStep** | $newStat | $newAudit | $Message |"
    } else {
        $updatedLine = "| $WP_ID | $($matches[1].Trim()) | **$newStep** | $newStat | $newAudit | $($matches[4].Trim()) |"
    }
    $tracksContent = $tracksContent -replace [regex]::Escape($lineMatch), $updatedLine
    $tracksContent | Set-Content $TRACKS_FILE -Encoding UTF8
    Write-Host "[OK] doc-tracks.md 更新完成。" -ForegroundColor Green
} else {
    Write-Host "[X] 在看板中找不到 ID: $WP_ID" -ForegroundColor Red
    exit 1
}

# --- 自動計算進度並更新 progress_report.md ---
$totalWP = ([regex]::Matches($tracksContent, "(?m)^\| \d{2} \|")).Count
$doneWP = ([regex]::Matches($tracksContent, "\[DONE\]")).Count
if ($totalWP -gt 0) {
    $percentage = [math]::Round(($doneWP / $totalWP) * 100)
} else {
    $percentage = 0
}

if (Test-Path $REPORT_FILE) {
    $reportContent = Get-Content $REPORT_FILE -Encoding UTF8
    $reportContent = $reportContent -replace "總體進度】：\d+%", "總體進度】：$percentage%"
    $reportContent = $reportContent -replace "\d+/\d+ 章節完工", "$doneWP/$totalWP 章節完工"
    $reportContent | Set-Content $REPORT_FILE -Encoding UTF8
    Write-Host "[OK] progress_report.md 進度同步為 $percentage% ($doneWP/$totalWP)。" -ForegroundColor Green
}

Write-Host ("-" * 50)
Write-Host "✅ 物理看板同步成功！" -ForegroundColor Green
