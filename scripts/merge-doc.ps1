# merge-doc.ps1 - Document Merger (RELEASE Edition)
# [v1.4.0] 參數化與根目錄探測自適應版

param (
    [string]$TargetDir = "src",
    [string]$OutputFile = "RELEASE.md"
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

# 自適應探測根目錄
$current = (Get-Item $PSScriptRoot)
$ROOT_DIR = $null
while ($current -ne $null) {
    if ((Test-Path (Join-Path $current.FullName "conductor")) -or (Test-Path (Join-Path $current.FullName "src"))) {
        $ROOT_DIR = $current.FullName
        break
    }
    $current = $current.Parent
}
if ($null -eq $ROOT_DIR) {
    $ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
}

$SRC_DIR = Join-Path $ROOT_DIR $TargetDir
$OUTPUT_FILE = Join-Path $ROOT_DIR $OutputFile

Write-Host "`n[Merge] 啟動穩定錨點合併程序 (v24.00)..." -ForegroundColor Cyan
Write-Host "  - 來源路徑: $SRC_DIR"
Write-Host "  - 輸出檔案: $OUTPUT_FILE"

if (-not (Test-Path $SRC_DIR)) {
    Write-Host "錯誤: 找不到來源路徑 '$SRC_DIR'。" -ForegroundColor Red
    exit 1
}

$MdFiles = Get-ChildItem -Path $SRC_DIR -Filter "*.md" | Sort-Object Name
if ($MdFiles.Count -eq 0 -and $MdFiles -eq $null) {
    Write-Host "警告: 來源路徑中無任何 Markdown 檔案。" -ForegroundColor Yellow
    exit 0
}

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

    # 1. 清理導航行 (只要行內包含 上一頁、下一頁 或 返回總目錄，整行徹底清除)
    $content = $content -replace '(?m)^.*?(上一頁|下一頁|返回總目錄).*?$', ''

    # 2. 連結校準 (指向穩定 ID)
    # 通用校準：將符合 ./XX_*.md 的連結轉換為對應的錨點 #ch-XX
    $content = $content -replace '\.\/(\d{2})_.*\.md', '#ch-$1'
    
    # 傳統特定檔案名校準 (保證相容舊連結)
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
Write-Host "[成功] 已產生穩定跳轉文件: $OUTPUT_FILE" -ForegroundColor Green
