#!/usr/bin/env pwsh

# 00_create-new-feature.ps1 - v16.15.5 (SOP Reinforced Edition)
# [治理加固] 一鍵啟動任務：整合文件初始化、看板同步與內容智慧預填。

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$FeatureDescription,
    [switch]$Json,
    [string]$ShortName,
    [int]$Number = 0,
    [switch]$Help
)

$featureDesc = $FeatureDescription.Trim()

# --- Helper Functions ---
function Find-RepositoryRoot {
    param([string]$StartDir)
    $current = Resolve-Path $StartDir
    while ($true) {
        if (Test-Path (Join-Path $current ".git")) { return $current }
        $parent = Split-Path $current -Parent
        if ($parent -eq $current) { return $null }
        $current = $parent
    }
}

function Get-HighestNumberFromSpecs {
    param([string]$SpecsDir)
    $highest = 0
    $paths = @($SpecsDir, (Join-Path $SpecsDir "../knowledge/archive/specs"))
    foreach ($p in $paths) {
        if (Test-Path $p) {
            Get-ChildItem -Path $p -Directory | ForEach-Object {
                if ($_.Name -match '^(\d{3})') {
                    $num = [int]$matches[1]
                    if ($num -gt $highest) { $highest = $num }
                }
            }
        }
    }
    return $highest
}

function Get-NextBranchNumber {
    param([string]$SpecsDir)
    $maxNum = Get-HighestNumberFromSpecs -SpecsDir $SpecsDir
    return $maxNum + 1
}

function ConvertTo-CleanBranchName {
    param([string]$Name)
    return $Name.ToLower() -replace '[^a-z0-9]', '-' -replace '-{2,}', '-' -replace '^-', '' -replace '-$', ''
}

function Get-BranchName {
    param([string]$Description)
    $cleanName = $Description.ToLower() -replace '[^a-z0-9\s]', ' '
    $words = $cleanName -split '\s+' | Where-Object { $_.Length -ge 3 } | Select-Object -First 3
    return ($words -join '-')
}

# --- Main Logic ---
$repoRoot = (Find-RepositoryRoot -StartDir $PSScriptRoot)
Set-Location $repoRoot
$specsDir = Join-Path $repoRoot 'specs'
$hasGit = (Test-Path (Join-Path $repoRoot ".git"))

if ($ShortName) { $branchSuffix = ConvertTo-CleanBranchName -Name $ShortName }
else { $branchSuffix = Get-BranchName -Description $featureDesc }

$featureNum = $null
# [智慧偵測] 優先對齊現有分支
if ($hasGit) {
    $existingBranch = git branch --list "*$branchSuffix*" | ForEach-Object { $_.Trim().Replace('* ', '') } | Select-Object -First 1
    if ($existingBranch) {
        Write-Host "[Identity] 偵測到現有軌道：$existingBranch" -ForegroundColor Cyan
        git checkout $existingBranch | Out-Null
        if ($existingBranch -match '(\d{3})') { $featureNum = $Matches[1]; $branchName = $existingBranch }
    }
}

# [ID 分配] 若無現有分支則建立新任務
if (!$featureNum) {
    if ($Number -eq 0) { $Number = Get-NextBranchNumber -SpecsDir $specsDir }
    $featureNum = ('{0:000}' -f $Number)
    $branchName = "$featureNum-$branchSuffix"
    if ($hasGit) { git checkout -b $branchName | Out-Null }
}

# [物理對齊] 磁碟目錄永遠僅使用數字 ID
$featureDir = Join-Path $specsDir $featureNum
if (!(Test-Path $featureDir)) { New-Item -ItemType Directory -Path $featureDir -Force | Out-Null }

# --- [加固 1] P1 文件全量初始化 ---
$templatesDir = Join-Path $repoRoot ".specify/templates"
$fileMappings = @{
    "plan-template.md" = "plan.md"
    "spec-template.md" = "spec.md"
    "research-report-template.md" = "research_report.md"
}

foreach ($tmpl in $fileMappings.Keys) {
    $tmplPath = Join-Path $templatesDir $tmpl
    $destPath = Join-Path $featureDir $fileMappings[$tmpl]
    if (!(Test-Path $destPath) -and (Test-Path $tmplPath)) {
        Copy-Item $tmplPath $destPath -Force
        
        # --- [加固 2] 智慧內容預填 ---
        $content = Get-Content $destPath -Raw
        $content = $content -replace '\[TrackID\]', $featureNum
        $content = $content -replace '\[Track ID\]', $featureNum
        $content = $content -replace '\[任務名稱\]', $featureDesc
        # 修正標題中的參數洩漏
        $content = $content -replace '# Track \d+:.*\(實作計畫\)', "# Track ${featureNum}: $featureDesc (實作計畫)"
        Set-Content $destPath $content -Encoding UTF8
    }
}

# 初始化日誌
$journalFile = Join-Path $featureDir "journal.md"
if (!(Test-Path $journalFile)) {
    @"
# Development Journal: Track $featureNum ($featureDesc)

## 任務摘要
$featureDesc

---
## 實作記錄
### [$(Get-Date -Format "yyyy-MM-dd")] Phase 1: Research
- 任務自動初始化。
"@ | Out-File -FilePath $journalFile -Encoding utf8
}

# --- [加固 3] 整合看板原子同步 ---
Write-Host "[Sync] 正在註冊新任務至看板..." -ForegroundColor Yellow
& pwsh -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot/90_sync_dashboard.ps1" -TrackID $featureNum -Status "[RESEARCHING]" -Phase "Phase 1"

$env:SPECIFY_FEATURE = $branchName
Write-Host "`n[SUCCESS] 任務 $featureNum 已成功啟動並註冊。" -ForegroundColor Green
Write-Output "BRANCH: $branchName"
Write-Output "FOLDER: $featureDir"
