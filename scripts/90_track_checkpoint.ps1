#!/usr/bin/env pwsh
<#
.SYNOPSIS
    90_track_checkpoint.ps1 - 任務進度物理巡檢中心 (區段感知版)
    [v2.5] 根據 plan.md 各 Phase 章節任務的完工狀況判定進度。
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$TrackID = "all"
)

# 強制控制台輸出編碼為 UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "`n[Auditor] 啟動區段感知巡檢 (V2.5 - 物理對齊)..." -ForegroundColor Cyan
Write-Host ("-" * 50)

# 動態取得專案根目錄
$ROOT_DIR = (Resolve-Path "$PSScriptRoot\..").Path
$SearchPaths = @(
    (Join-Path $ROOT_DIR "specs"),
    (Join-Path $ROOT_DIR "knowledge\archive\specs")
)

$TargetTracks = @()

# 1. 蒐集目標 Track 資料夾
foreach ($path in $SearchPaths) {
    if (Test-Path $path) {
        if ($TrackID -eq "all") {
            $TargetTracks += Get-ChildItem -Path $path -Directory | Where-Object { $_.Name -match "^\d{3}" }
        } else {
            $TargetTracks += Get-ChildItem -Path $path -Directory | Where-Object { $_.Name -match "^$TrackID" }
        }
    }
}

if ($TargetTracks.Count -eq 0) {
    Write-Host "找不到符合條件的 Track: $TrackID" -ForegroundColor Yellow
    exit 0
}

foreach ($trackFolder in $TargetTracks) {
    # 確保只萃取前三碼數字作為 Track ID
    $tid = if ($trackFolder.Name -match "^(\d{3})") { $Matches[1] } else { $trackFolder.Name }
    $planPath = Join-Path $trackFolder.FullName "plan.md"
    
    if (-not (Test-Path $planPath)) { 
        Write-Warning "略過 $tid：找不到 plan.md"
        continue 
    }

    $planContent = Get-Content -Path $planPath -Raw -Encoding UTF8

    # 1. 計算總進度 %
    $totalCount = ([regex]::Matches($planContent, '\[(?i)[ x]\]')).Count
    $doneCount = ([regex]::Matches($planContent, '\[(?i)x\]')).Count
    $overallProgress = if ($totalCount -gt 0) { [math]::Floor(($doneCount / $totalCount) * 100) } else { 0 }

    # 2. 區段完工判定
    $phases = [regex]::Split($planContent, "(?i)(?=## Phase \d)")
    $completedPhases = 0
    for ($i = 1; $i -le 5; $i++) {
        $phaseHeader = "## Phase $i"
        $phaseContent = $phases | Where-Object { $_ -match [regex]::Escape($phaseHeader) }
        if ($phaseContent) {
            # 轉換為字串陣列以防 regex 回傳多個 match 物件
            $pStr = $phaseContent -join "`n"
            $pTotal = ([regex]::Matches($pStr, '\[(?i)[ x]\]')).Count
            $pDone = ([regex]::Matches($pStr, '\[(?i)x\]')).Count
            if ($pTotal -gt 0 -and $pDone -eq $pTotal) { 
                $completedPhases = $i 
            } else { 
                break 
            }
        }
    }

    # 3. 判定狀態與 Phase
    $currentPhaseNum = $completedPhases + 1
    if ($currentPhaseNum -gt 5) { $currentPhaseNum = 5 }
    $newPhase = "Phase $currentPhaseNum"
    
    $newStatus = switch ($currentPhaseNum) {
        1 { "[RESEARCHING]" }
        2 { if ($planContent -match "\[AUTHORIZED\]") { "[AUTHORIZED]" } else { "[STRATEGIZING]" } }
        3 { "[IN EXECUTION]" }
        4 { "[VERIFYING]" }
        5 { if ($overallProgress -eq 100) { "[DONE]" } else { "[VERIFYING]" } }
    }

    # 4. 物理檔案閘門
    $gatePassed = $true
    $gateMsg = ""
    if ($currentPhaseNum -eq 3 -and -not (Test-Path (Join-Path $trackFolder.FullName "spec.md"))) {
        $gatePassed = $false
        $gateMsg = "缺少 spec.md"
    }
    if ($currentPhaseNum -eq 4 -and -not (Test-Path (Join-Path $trackFolder.FullName "UAT_CHECKLIST.md"))) {
        $gatePassed = $false
        $gateMsg = "缺少 UAT_CHECKLIST.md"
    }

    if (-not $gatePassed) {
        # 降級處理
        $currentPhaseNum -= 1
        $newPhase = "Phase $currentPhaseNum"
        # 重新評估降級後的狀態
        $newStatus = switch ($currentPhaseNum) {
            1 { "[RESEARCHING]" }
            2 { if ($planContent -match "\[AUTHORIZED\]") { "[AUTHORIZED]" } else { "[STRATEGIZING]" } }
            3 { "[IN EXECUTION]" }
            default { $newStatus }
        }
        Write-Host "  - [任務 $tid] [攔截] 進度停留在 $newPhase：$gateMsg" -ForegroundColor Red
    } else {
        Write-Host "  - [任務 $tid] 物理完工: Phase $completedPhases, 當前階段: $newPhase ($newStatus)" -ForegroundColor Cyan
    }

    # 5. 更新計畫標籤 (修復斷行問題)
    $oldStatuses = '\[RESEARCHING\]|\[STRATEGIZING\]|\[AUTHORIZED\]|\[IN EXECUTION\]|\[VERIFYING\]|\[DONE\]|\[PENDING\]|\[RESEARCHING: INCIDENT\]'
    $updatedContent = $planContent -replace "(?i)$oldStatuses", $newStatus
    
    if ($updatedContent -ne $planContent) {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($planPath, $updatedContent, $utf8NoBom)
        git add $planPath 2>$null
        Write-Host "    -> 已更新 plan.md 狀態標籤為 $newStatus" -ForegroundColor Green
    }

    # 6. 同步看板 (修復路徑依賴)
    $syncScript = Join-Path $PSScriptRoot "90_sync_dashboard.ps1"
    if (Test-Path $syncScript) {
        # 使用安全的引號包覆參數，避免路徑或字串中斷
        & pwsh -NoProfile -ExecutionPolicy Bypass -File "$syncScript" -TrackID $tid -Phase $newPhase -Status $newStatus
    } else {
        Write-Warning "找不到看板同步腳本: $syncScript"
    }
}

Write-Host ("-" * 50)