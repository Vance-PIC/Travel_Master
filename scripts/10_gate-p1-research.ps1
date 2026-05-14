# gate-p1-research.ps1 - Audit tool for Phase 1 (Research Integrity)
# Usage: powershell .specify/scripts/powershell/gate-p1-research.ps1 <TrackID>

param (
    [Parameter(Mandatory=$true)]
    [string]$TrackID
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8


# Import common helpers
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptDir 'lib_common.ps1')

# Acquire environment paths (v16.15.6 Table-Lookup)
$envData = Get-FeaturePathsEnv -TrackID $TrackID
$ReportPath = $envData.RESEARCH
$ErrorCount = 0

Write-Host "`n[Audit] 開始 Phase 1 研究完整性審計：$TrackID" -ForegroundColor Cyan
Write-Host "--------------------------------------------------"

if (-not (Test-Path $ReportPath)) {
    Write-Host "[失敗] 找不到研究報告：$ReportPath" -ForegroundColor Red
    exit 1
}

# Use -Raw and .Contains() for maximum stability across encodings
$Content = Get-Content -Path $ReportPath -Raw

# 1. Check Core Goals
Write-Host "[1/2] 審核核心目標..."
if (-not ($Content.Contains("Project Goals") -or $Content.Contains("## 2."))) {
    Write-Host "  - [X] 遺漏區段：核心目標 (Goals)" -ForegroundColor Red
    $ErrorCount++
} else {
    # Count bullet points starting with "- "
    $GoalItems = $Content -split "`n" | Where-Object { $_ -match "^\s*-\s+" }
    if ($GoalItems.Count -lt 3) {
        Write-Host "  - [!] 目標數量不足：目前僅有 $($GoalItems.Count) 個，至少需要 3 個。" -ForegroundColor Yellow
        $ErrorCount++
    } else {
        Write-Host "  - [OK] 目標數量驗證通過：$($GoalItems.Count) 個" -ForegroundColor Green
    }
}

# 2. Check Business Scope
Write-Host "[2/2] 審核業務範圍..."
if (-not ($Content.Contains("Business Scope") -or $Content.Contains("## 3."))) {
    Write-Host "  - [X] 遺漏區段：業務範圍 (Business Scope)" -ForegroundColor Red
    $ErrorCount++
} else {
    if (-not ($Content.Contains("In Scope") -and $Content.Contains("Out Scope"))) {
        Write-Host "  - [!] 範圍定義不完整（缺少 In Scope / Out Scope 標記）。" -ForegroundColor Yellow
        $ErrorCount++
    } else {
        Write-Host "  - [OK] 範圍標記驗證通過。" -ForegroundColor Green
    }
}

Write-Host "--------------------------------------------------"
if ($ErrorCount -eq 0) {
    Write-Host "[結果] Phase 1 審計通過！" -ForegroundColor Green
    exit 0
} else {
    Write-Host "[結果] Phase 1 審計失敗（共發現 $ErrorCount 個問題）" -ForegroundColor Red
    exit 1
}
