#!/usr/bin/env pwsh
# 90_sync_dashboard.ps1 - v16.14.1 (Precision Archival Edition)
# [治理規範] 1. ID 自動補零。2. 排除歸檔路徑誤判。3. 強化狀態提取。

param(
    [Parameter(Mandatory=$true)]
    [string]$TrackID,
    [string]$Status,
    [string]$Phase,
    [int]$ManualProgress = -1,
    [string]$Message,
    [string]$DeployID # [v16.15.7] 支援同步 GAS 部署 ID
)

# 強制 UTF8 (No BOM) 輸出
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
$DASHBOARD_PATH = Join-Path $ROOT_DIR "conductor/tracks.md"

# --- [修正 1] ID 標準化 (補零至三位) ---
if ($TrackID -match "^\d+$") {
    $TrackID = $TrackID.PadLeft(3, '0')
}

Write-Host "`n[Sync] 啟動事實驅動同步 (Track: $TrackID)..." -ForegroundColor Cyan

# --- [修正 2] 精確物理定位 ---
$activeDir = Get-ChildItem -Path (Join-Path $ROOT_DIR "specs") -Directory | Where-Object { $_.Name -match "^$TrackID" } | Select-Object -First 1
$archiveDir = Get-ChildItem -Path (Join-Path $ROOT_DIR "knowledge/archive/specs") -Directory | Where-Object { $_.Name -match "^$TrackID" } | Select-Object -First 1

$targetFolder = if ($activeDir) { $activeDir } else { $archiveDir }
if (-not $targetFolder) { Write-Error "找不到物理資料夾 (TrackID: $TrackID)"; exit 1 }

$planPath = Join-Path $targetFolder.FullName "plan.md"
if (-not (Test-Path $planPath)) { Write-Error "找不到計畫面檔 (plan.md)"; exit 1 }

# 2. 物理內容審計 (提取真相)
$planContent = Get-Content $planPath -Raw -Encoding UTF8

# [v16.15.6] 分支校準檢查：確保在正確的脈絡下更新看板
$currentBranch = (git rev-parse --abbrev-ref HEAD 2>$null)
if ($currentBranch -and $currentBranch -ne "master" -and $currentBranch -notmatch "0*$($TrackID.TrimStart('0'))") {
    Write-Warning "[Guard] 目前分支 ($currentBranch) 與任務 ID ($TrackID) 不匹配！"
    Write-Warning "為了防止看板漂移，請先切換至正確的開發分支再執行同步。"
    exit 1
}

$total = ([regex]::Matches($planContent, '\[(?i)[ x]\]')).Count
$done = ([regex]::Matches($planContent, '\[(?i)x\]')).Count
$progress = if ($total -gt 0) { [math]::Floor(($done / $total) * 100) } else { 0 }
if ($ManualProgress -ge 0) { $progress = $ManualProgress }

# --- [修正 3] 強化狀態提取 Regex ---
$detectedStatus = $Status
if (-not $Status -and ($planContent -match "(?i)(狀態|Status)\s*[:：]\s*\[(?<st>.*?)\]")) {
    $detectedStatus = "[$($Matches['st'])]"
}
$st = if ($detectedStatus) { $detectedStatus } else { "[STRATEGIZING]" }

# 3. 自動歸檔邏輯 (修正路徑錨點)
# 精確檢查：必須在 specs 目錄下且不在 archive 目錄下
$isPhysicallyInActive = ($targetFolder.FullName -match "\\specs\\" -and $targetFolder.FullName -notmatch "archive")
# [v16.15.2] 靈活判定：100% 完成 或 顯式指定為 DONE 狀態
$isReadyToArchive = ($progress -eq 100 -or $st -match "DONE")

if ($isPhysicallyInActive -and $isReadyToArchive) {
    Write-Host "  - [Detected] 任務已標記為 [DONE] 或 100% 完成。" -ForegroundColor Green
    Write-Host "  - [Action] 執行自動物理歸檔 (Auto-Archiving)..." -ForegroundColor Yellow
    
    $destParent = Join-Path $ROOT_DIR "knowledge/archive/specs"
    if (-not (Test-Path $destParent)) { New-Item -ItemType Directory -Path $destParent | Out-Null }
    
    Move-Item -Path $targetFolder.FullName -Destination $destParent -Force
    # 重新整理路徑
    $targetFolder = Get-ChildItem -Path $destParent -Directory | Where-Object { $_.Name -match "^$TrackID" } | Select-Object -First 1
    Write-Host "  - [Success] 資料夾已搬移至歸檔區。" -ForegroundColor Green
}

$relPath = $targetFolder.FullName.Replace($ROOT_DIR, "").TrimStart('\').Replace('\', '/')
$isArchived = $relPath -match "archive"

# 4. 構建表格行
$phMatch = [regex]::Match($planContent, 'Phase (\d)')
$ph = if ($Phase) { $Phase } elseif ($phMatch.Success) { "Phase $($phMatch.Groups[1].Value)" } else { "Phase 4" }

# --- [修正 5] 提取任務標題 ---
$missionTitle = "Unknown Mission"
if ($planContent -match "(?m)^#\s*Track\s*\d+:\s*(?<title>[^\[\r\n(]+)") {
    $missionTitle = $Matches['title'].Trim()
}
if ($missionTitle -eq "Unknown Mission" -and $planContent -match "(?m)^#\s*(?<title>[^\[\r\n(]+)") {
    $missionTitle = $Matches['title'].Trim()
}
# 過濾掉可能是腳本參數的噪音
if ($missionTitle -match "-FeatureName") {
    $missionTitle = "Mission $TrackID"
}

$hash = (git rev-parse --short HEAD 2>$null)
if (-not $hash) { $hash = "0000000" }
$commit = (git log -1 --format=%s 2>$null).Replace('|','｜')
if ($commit.Length > 25) { $commit = $commit.Substring(0, 22) + "..." }
$proof = "``$($hash): $($commit)``"
if ($Message) { $proof = $Message }
$today = Get-Date -Format "yyyy-MM-dd"

# --- [修正 6] 獲取現有 DeployID (若未傳入) ---
$existingDeployID = "-"
if (!$DeployID) {
    $existingRow = $oldLines | Select-String -Pattern "^\s*\| \s*$idRegex" | Select-Object -First 1
    if ($existingRow -and ($existingRow.ToString() -split '\|').Count -ge 5) {
        $existingDeployID = ($existingRow.ToString() -split '\|')[4].Trim()
    }
}
$finalDeployID = if ($DeployID) { $DeployID } else { $existingDeployID }

$rowContent = if ($isArchived) {
    "| [$TrackID] | [$missionTitle]($relPath/plan.md) | [DONE] | $today | ``$relPath`` |"
} else {
    "| [$TrackID] | [$missionTitle]($relPath/plan.md) | ``$relPath`` | $ph | $finalDeployID | $st | $($progress)% | $proof | - | $today |"
}

# 5. 更新 tracks.md (原子化處理)
$oldLines = Get-Content $DASHBOARD_PATH -Encoding UTF8
$finalLines = New-Object System.Collections.Generic.List[string]
$inserted = $false

# --- [修正 4] 強化移除舊行邏輯 ---
$cleanId = $TrackID.TrimStart('0')
$idRegex = "\[0*$cleanId\]"

foreach ($line in $oldLines) {
    if ($line -match "^\s*\| \s*$idRegex") { continue }
    $finalLines.Add($line)
}

$tempLines = [System.Collections.Generic.List[string]]::new($finalLines)
$finalLines.Clear()

$inArchiveSection = $false
foreach ($l in $tempLines) {
    $finalLines.Add($l)
    if ($l -match "## 💾 Archived Tracks") { $inArchiveSection = $true }
    
    if ($isArchived) {
        if ($inArchiveSection -and $l -match "\| :--- \| :--- \| :--- \| :--- \| :--- \|" -and -not $inserted) {
            $finalLines.Add($rowContent); $inserted = $true
        }
    } else {
        if (-not $inArchiveSection -and $l -match "\| :--- \| :--- \| :--- \| :--- \| :--- \| :--- \| :--- \| :--- \| :--- \| :--- \|" -and -not $inserted) {
            $finalLines.Add($rowContent); $inserted = $true
        }
    }
}

[System.IO.File]::WriteAllLines($DASHBOARD_PATH, $finalLines, $OutputEncoding)
Write-Host "看板同步完成 (ID=$TrackID, Status=$st, Progress=$progress%)。" -ForegroundColor Green
