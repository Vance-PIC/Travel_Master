#!/usr/bin/env pwsh
# gate-p2-design.ps1 - Audit tool for Phase 2 (Omission Check)
# Usage: powershell scripts/gate-p2-design.ps1 -TrackID <TrackID> [-SpecFile <Name>]

# [參數區塊必須在最上方]
param (
    [Parameter(Mandatory=$true)]
    [string]$TrackID,
    
    [Parameter(Mandatory=$false)]
    [string]$SpecFile = "spec.md"
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8

# 動態取得 Git 專案根目錄，確保不同層級執行都能抓對路徑
$GitRoot = (git rev-parse --show-toplevel 2>$null)
if (-not $GitRoot) { $GitRoot = (Resolve-Path ".").Path }

$SpecPath = Join-Path $GitRoot "specs/$TrackID/$SpecFile"
$ErrorCount = 0

Write-Host "`n[Audit] 開始 Phase 2 設計遺漏審計：$TrackID ($SpecFile)" -ForegroundColor Cyan
Write-Host ("-" * 50)

if (-not (Test-Path $SpecPath -PathType Leaf)) {
    Write-Host "[失敗] 找不到規格文件 (SPEC)：$SpecPath" -ForegroundColor Red
    exit 1
}

$RawLines = Get-Content -Path $SpecPath -Encoding UTF8
$Content = $RawLines -join "`n"

# 1. Omission Keyword Scan (已修復亂碼)
Write-Host "[1/3] 掃描遺漏關鍵字 (..., 略, Unchanged)..."
$OmissionKeywords = @("...", "(略)", "(unchanged)", "(無異動)", "(待補)")

foreach ($key in $OmissionKeywords) {
    if ($Content.Contains($key)) {
        Write-Host "  - [!] 發現遺漏標記：'$key'" -ForegroundColor Yellow
        $ErrorCount++
    }
}

# 2. File List & Path Audit
Write-Host "[2/3] 審核檔案影響清單與路徑有效性..."
$HasList = $false
$Paths = @()

foreach ($line in $RawLines) {
    # 支援英文或中文的標題比對
    if ($line -match '## 2\. (File Impact List|實體檔案影響清單)') {
        $HasList = $true
    }
    # 使用單引號包覆 Regex，避免 PowerShell 將反引號當作跳脫字元
    if ($HasList -and $line -match '^\s*-\s*`([^`]+)`') {
        $Paths += $Matches[1]
    }
}

if (-not $HasList) {
    Write-Host "  - [X] 遺漏區段：## 2. 實體檔案影響清單 (File Impact List)" -ForegroundColor Red
    $ErrorCount++
} else {
    foreach ($p in $Paths) {
        $CleanPath = $p.Trim()
        if ($CleanPath -ne "" -and -not ($CleanPath -match "\((New|新增)\)")) {
            $FullPath = Join-Path $GitRoot $CleanPath
            if (-not (Test-Path $FullPath)) {
                Write-Host "  - [!] 無效路徑：$CleanPath" -ForegroundColor Yellow
                $ErrorCount++
            } else {
                Write-Host "  - [OK] 路徑有效：$CleanPath" -ForegroundColor Green
            }
        }
    }
}

Write-Host ("-" * 50)
if ($ErrorCount -eq 0) {
    Write-Host "[結果] Phase 2 審計通過！" -ForegroundColor Green
    
    # 3. 自動物理打卡與聯動巡檢 (v2.1 治理強化)
    Write-Host "[3/3] 執行物理打卡與自動巡檢..." -ForegroundColor Gray
    
    # 尋找 plan.md 並自動勾選審計任務
    $planPath = (Get-ChildItem -Path $GitRoot -Filter "plan.md" -Recurse | Where-Object { $_.FullName -match $TrackID } | Select-Object -First 1).FullName
    if ($planPath -and (Test-Path $planPath)) {
        $c = [System.IO.File]::ReadAllText($planPath, [System.Text.Encoding]::UTF8)
        $targetTask = "20_gate-p2-design.ps1"
        if ($c -match "- \[ \] .*$targetTask") {
            $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            $newC = $c -replace "- \[ \] (.*$targetTask)", "- [x] `$1"
            [System.IO.File]::WriteAllText($planPath, $newC, $utf8NoBom)
            Write-Host "  - [OK] 計畫書已完成自動打卡。" -ForegroundColor Green
        }
    }

    $checkScript = Join-Path $GitRoot "scripts\90_track_checkpoint.ps1" 
    if (Test-Path $checkScript) {
        $tid = if ($TrackID -match "^(\d{3})") { $Matches[1] } else { $TrackID }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $checkScript -TrackID $tid
    }
    
    exit 0
} else {
    Write-Host "[結果] Phase 2 審計失敗（共發現 $ErrorCount 個問題）" -ForegroundColor Red
    exit 1
}