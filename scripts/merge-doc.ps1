#!/usr/bin/env pwsh
# merge-doc.ps1 - Document Merger (RELEASE Edition)
# [v1.3.0] 穩定 ID 錨點機制版

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
$SRC_DIR = Join-Path $ROOT_DIR "src"
$OUTPUT_FILE = Join-Path $ROOT_DIR "RELEASE.md"

Write-Host "`n[Merge] 啟動穩定錨點合併程序 (v24.00)..." -ForegroundColor Cyan

$MdFiles = Get-ChildItem -Path $SRC_DIR -Filter "*.md" | Sort-Object Name
$FullContent = New-Object System.Text.StringBuilder

foreach ($file in $MdFiles) {
    Write-Host "  - 正在處理: $($file.Name)"
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    
    # 取得章節編號 (例如 01, 02...)
    if ($file.Name -match "^(\d{2})") {
        $chId = $matches[1]
        # 在章節最前方插入隱形錨點
        $content = "<div id='ch-$chId'></div>`n`n" + $content
    }

    # 1. 清理導航行
    $content = $content -replace '(?m)^\[🏠 返回總目錄\].*?$', ''
    $content = $content -replace '(?m)^\[➡️ 下一頁\].*?$', ''
    $content = $content -replace '(?m)^\[⬅️ 上一頁\].*?$', ''

    # 2. 連結校準 (指向穩定 ID)
    $content = $content -replace '\.\/01_Chapter1_核心戰報與財務預算\.md', '#ch-01'
    $content = $content -replace '\.\/02_Chapter2_每日詳細作戰中心\.md', '#ch-02'
    $content = $content -replace '\.\/03_Day1_抵達熊本與櫻町放電\.md', '#ch-03'
    $content = $content -replace '\.\/04_Day2_熊本城巡禮與領車任務\.md', '#ch-04'
    $content = $content -replace '\.\/05_Day3_Greenland全日遊\.md', '#ch-05'
    $content = $content -replace '\.\/06_Day4_挺進阿蘇與農場探險\.md', '#ch-06'
    $content = $content -replace '\.\/07_Day5_農場深度玩與和牛烤肉\.md', '#ch-07'
    $content = $content -replace '\.\/08_Day6_阿蘇神社與採果大慶功\.md', '#ch-08'
    $content = $content -replace '\.\/09_Day7_機場最後衝刺\.md', '#ch-09'
    $content = $content -replace '\.\/00_Index\.md', '#ch-00'

    [void]$FullContent.AppendLine($content)
    [void]$FullContent.AppendLine("`n---`n")
}

# 3. 寫入檔案
$finalText = $FullContent.ToString() -replace '(?m)^\s*$\n\s*$\n', "`n"
[System.IO.File]::WriteAllText($OUTPUT_FILE, $finalText, $OutputEncoding)

Write-Host ("-" * 50)
Write-Host "[成功] 已產生穩定跳轉文件: RELEASE.md" -ForegroundColor Green
