#!/usr/bin/env pwsh
# audit-global.ps1 - Global Document Auditor (RELEASE Edition)
# [v1.1.0] 檢查合併後 RELEASE.md 的全域一致性

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
$OUTPUT_FILE = Join-Path $ROOT_DIR "RELEASE.md"

Write-Host "`n[Audit] 啟動全域發布級檢核 (Target: RELEASE.md)..." -ForegroundColor Cyan
Write-Host ("-" * 50)

if (-not (Test-Path $OUTPUT_FILE)) {
    Write-Host "[失敗] 找不到最終發布檔 RELEASE.md" -ForegroundColor Red
    exit 1
}

$content = Get-Content -Path $OUTPUT_FILE -Raw -Encoding UTF8

# 1. 檢查標題層級一致性
$h1Count = ([regex]::Matches($content, "^# ", "Multiline")).Count
Write-Host "  - [INFO] 偵測到 $h1Count 個章節封頁。" -ForegroundColor Gray

# 2. 檢查版本號定錨 (v24.00)
if ($content -match "v24.00") {
    Write-Host "  - [OK] 版本號已正確定錨為 v24.00。" -ForegroundColor Green
} else {
    Write-Host "  - [X] 失敗: 未在文件中偵測到 v24.00 標註。" -ForegroundColor Red
}

# 3. 檢查表格完整性 (全域)
$brokenTables = $content -split "`n" | Where-Object { $_.Trim().StartsWith("|") -and -not $_.Trim().EndsWith("|") }
if ($brokenTables) {
    Write-Host "  - [X] 失敗: 偵測到 $($brokenTables.Count) 行損壞的表格。" -ForegroundColor Red
} else {
    Write-Host "  - [OK] 全域表格結構完整。" -ForegroundColor Green
}

Write-Host ("-" * 50)
Write-Host "[結果] RELEASE.md 總體檢核完成。" -ForegroundColor Green
