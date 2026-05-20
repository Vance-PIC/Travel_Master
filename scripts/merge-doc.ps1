#!/usr/bin/env pwsh
# merge-doc.ps1 - Document Merger (RELEASE Edition)
# [v1.1.0] 依照檔名順序將 src/*.md 合併為最終的 RELEASE.md

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
$SRC_DIR = Join-Path $ROOT_DIR "src"
$OUTPUT_FILE = Join-Path $ROOT_DIR "RELEASE.md"

Write-Host "`n[Merge] 啟動最終文件合併程序 (v24.00)..." -ForegroundColor Cyan

$MdFiles = Get-ChildItem -Path $SRC_DIR -Filter "*.md" | Sort-Object Name
$FullContent = New-Object System.Text.StringBuilder

foreach ($file in $MdFiles) {
    Write-Host "  - 正在讀取: $($file.Name)"
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    [void]$FullContent.AppendLine($content)
    [void]$FullContent.AppendLine("`n---`n")
}

[System.IO.File]::WriteAllText($OUTPUT_FILE, $FullContent.ToString(), $OutputEncoding)

Write-Host ("-" * 50)
Write-Host "[成功] 已產生最終發布文件: RELEASE.md" -ForegroundColor Green
