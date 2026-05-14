#!/usr/bin/env pwsh
# 01_check-prerequisites.ps1 - 環境醫生 (SPORTS ITS Environment Doctor)
# [v16.13.2] PowerShell 7 (pwsh) 原生 UTF-8 支援版

[CmdletBinding()]
param([switch]$Json)

# pwsh 預設即為 UTF-8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "`n[醫生] 啟動環境健康檢查..." -ForegroundColor Cyan
Write-Host "--------------------------------------------------"
$ErrorCount = 0

# 1. 編碼檢測
Write-Host "[1/5] 檢查終端機編碼 (Code Page)..."
if ($PSVersionTable.PSVersion.Major -lt 7) {
    Write-Warning "偵測到您正在使用舊版 PowerShell，強烈建議切換至 pwsh (PS 7+)。"
}

$cp = [Console]::OutputEncoding.CodePage
if ($cp -ne 65001) {
    Write-Host "  - [!] 目前編碼為 $cp。嘗試自動修正至 65001..." -ForegroundColor Yellow
    chcp 65001 | Out-Null
    if ([Console]::OutputEncoding.CodePage -eq 65001) {
        Write-Host "  - [OK] 編碼已修正為 UTF-8。" -ForegroundColor Green
    } else {
        Write-Host "  - [X] 編碼修正失敗。" -ForegroundColor Red
        $ErrorCount++
    }
} else {
    Write-Host "  - [OK] 編碼已鎖定 (UTF-8)。" -ForegroundColor Green
}

# 2. 工具檢測
$tools = @(
    @{ Name="clasp";  Desc="Google Clasp (GAS CLI)"; Manual="npm install -g @google/clasp" },
    @{ Name="git";    Desc="Git 版本控制"; Manual="請安裝 Git for Windows" },
    @{ Name="dotnet"; Desc=".NET SDK (C# 需求)"; Manual="請安裝 .NET SDK 8.0+" }
)

$i = 2
foreach ($tool in $tools) {
    Write-Host "[$i/5] 檢查 $($tool.Desc)..."
    if (Get-Command $tool.Name -ErrorAction SilentlyContinue) {
        Write-Host "  - [OK] $($tool.Name) 已安裝。" -ForegroundColor Green
    } else {
        Write-Host "  - [X] 找不到 $($tool.Name)。建議動作：$($tool.Manual)" -ForegroundColor Red
        $ErrorCount++
    }
    $i++
}

# 5. 專案邊界
Write-Host "[5/5] 檢查專案物理邊界 (Sub-Repo Isolation)..."
$topLevel = git rev-parse --show-toplevel 2>$null
if ($topLevel -match "SPORTS問題清單$") {
    Write-Host "  - [OK] 專案物理邊界正確。" -ForegroundColor Green
} else {
    Write-Host "  - [!] 警告：目前位於共享 Repo ($topLevel)。" -ForegroundColor Yellow
}

Write-Host "--------------------------------------------------"
if ($ErrorCount -eq 0) {
    Write-Host "[結果] 環境健康狀況：良好！準備執行 DevOps。" -ForegroundColor Green
} else {
    Write-Host "[結果] 環境偵測到 $ErrorCount 項問題。請修復後再繼續。" -ForegroundColor Red
}
exit $ErrorCount