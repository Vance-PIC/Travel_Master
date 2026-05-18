#!/usr/bin/env pwsh
# audit-global.ps1 - Global Document Auditor
# [v1.0.0] 檢查合併後文件的全域一致性

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
$OUTPUT_FILE = Join-Path $ROOT_DIR "OUTPUT.md"

Write-Host "`n[Audit] 啟動總體級格式與一致性檢核..." -ForegroundColor Cyan
Write-Host ("-" * 50)

if (-not (Test-Path $OUTPUT_FILE)) {
    Write-Host "[失敗] 找不到合併後的 OUTPUT.md" -ForegroundColor Red
    exit 1
}

$content = Get-Content -Path $OUTPUT_FILE -Raw -Encoding UTF8

# 1. 檢查標題層級一致性
$h1Count = ([regex]::Matches($content, "^# ", "Multiline")).Count
if ($h1Count -gt 1) {
    Write-Host "  - [!] 警告: 發現多個 H1 標題 ($h1Count 個)，建議合併時調整層級。" -ForegroundColor Yellow
}

# 2. 檢查章節分隔符
$sepCount = ([regex]::Matches($content, "---")).Count
Write-Host "  - [OK] 偵測到 $sepCount 個章節分隔符。" -ForegroundColor Green

# 3. 檢查表格完整性 (全域)
$brokenTables = $content -split "`n" | Where-Object { $_.Trim().StartsWith("|") -and -not $_.Trim().EndsWith("|") }
if ($brokenTables) {
    Write-Host "  - [X] 失敗: 偵測到 $($brokenTables.Count) 行損壞的表格。" -ForegroundColor Red
}

Write-Host ("-" * 50)
Write-Host "[結果] 總體檢核完成。" -ForegroundColor Green
