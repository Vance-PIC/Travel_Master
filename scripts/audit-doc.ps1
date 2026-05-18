#!/usr/bin/env pwsh
# audit-doc.ps1 - Markdown Quality Auditor
# [v1.0.0] 專注於文件完整性與格式審計

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorCount = 0
$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."

Write-Host "`n[Audit] 啟動文件品質審計..." -ForegroundColor Cyan
Write-Host ("-" * 50)

# 1. 掃描所有 Markdown 檔案
$MdFiles = Get-ChildItem -Path (Join-Path $ROOT_DIR "src") -Filter "*.md" -Recurse

foreach ($file in $MdFiles) {
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    
    # 1.1 零省略檢查 (Rule 1)
    if ($content -match "\((略)\)|（略）|\.\.\.") {
        Write-Host "  - [X] 失敗: 偵測到省略記號於 $($file.Name)" -ForegroundColor Red
        $ErrorCount++
    }

    # 1.2 表格格式初步檢查 (檢查是否包含未閉合的 |)
    $lines = Get-Content -Path $file.FullName
    $ln = 0
    foreach ($line in $lines) {
        $ln++
        if ($line.Trim().StartsWith("|") -and -not $line.Trim().EndsWith("|")) {
             Write-Host "  - [!] 警告: 疑似損壞的表格行於 $($file.Name):$ln" -ForegroundColor Yellow
        }
    }
}

Write-Host ("-" * 50)
if ($ErrorCount -eq 0) {
    Write-Host "[結果] 審計通過！文件品質符合 Doc-Gov 規範。" -ForegroundColor Green
    exit 0
} else {
    Write-Host "[結果] 審計失敗，請修正上述問題。" -ForegroundColor Red
    exit 1
}
