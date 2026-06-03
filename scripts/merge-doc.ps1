# merge-doc.ps1 - Document Merger (RELEASE Edition)
# [v1.5.0] Multi-Spec Document Merger

param (
    [string]$Spec = "kumamoto",
    [string]$TargetDir = "",
    [string]$OutputFile = ""
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

# 自適應探測根目錄
$current = (Get-Item $PSScriptRoot)
$ROOT_DIR = $null
while ($current -ne $null) {
    if ((Test-Path (Join-Path $current.FullName "conductor")) -or (Test-Path (Join-Path $current.FullName "specs"))) {
        $ROOT_DIR = $current.FullName
        break
    }
    $current = $current.Parent
}
if ($null -eq $ROOT_DIR) {
    $ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
}

# 動態路徑解析
if ($TargetDir -eq "") {
    $SRC_DIR = Join-Path $ROOT_DIR "specs/$Spec/src"
    if (-not (Test-Path $SRC_DIR)) {
        $SRC_DIR = Join-Path $ROOT_DIR "src"
    }
} else {
    $SRC_DIR = Join-Path $ROOT_DIR $TargetDir
}

if ($OutputFile -eq "") {
    $OUTPUT_FILE = Join-Path $ROOT_DIR "specs/$Spec/RELEASE-$Spec.md"
    
    # 向後相容回退
    if (-not (Test-Path (Join-Path $ROOT_DIR "specs/$Spec"))) {
        if ($Spec -eq "kumamoto") {
            $OUTPUT_FILE = Join-Path $ROOT_DIR "RELEASE.md"
        } else {
            $OUTPUT_FILE = Join-Path $ROOT_DIR "RELEASE-$Spec.md"
        }
    }
} else {
    $OUTPUT_FILE = Join-Path $ROOT_DIR $OutputFile
}

Write-Host "`n[Merge] 啟動穩定錨點合併程序 (v25.00)..." -ForegroundColor Cyan
Write-Host "  - 行程 Spec: $Spec"
Write-Host "  - 來源路徑: $SRC_DIR"
Write-Host "  - 輸出檔案: $OUTPUT_FILE"

if (-not (Test-Path $SRC_DIR)) {
    Write-Host "錯誤: 找不到來源路徑 '$SRC_DIR'。" -ForegroundColor Red
    exit 1
}

$MdFiles = Get-ChildItem -Path $SRC_DIR -Filter "*.md" | Sort-Object {
    $name = $_.Name
    if ($name -match '^(\d+)\.(\d+)_') {
        $main = [int]$matches[1]
        $sub = [int]$matches[2]
    } elseif ($name -match '^(\d+)_') {
        $main = [int]$matches[1]
        $sub = 0
    } else {
        $main = 99
        $sub = 99
    }
    $main * 1000 + $sub
}
if ($MdFiles.Count -eq 0) {
    Write-Host "警告: 來源路徑中無 any Markdown 檔案。" -ForegroundColor Yellow
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
    $content = $content -replace '\.\/(\d{2})_.*\.md', '#ch-$1'
    
    [void]$FullContent.AppendLine($content)
    [void]$FullContent.AppendLine("`n---`n")
}

# 3. 寫入檔案
$finalText = $FullContent.ToString() -replace '(?m)^\s*$\n\s*$\n', "`n"
[System.IO.File]::WriteAllText($OUTPUT_FILE, $finalText, $OutputEncoding)

Write-Host ("-" * 50)
Write-Host "[成功] 已產生穩定跳轉文件: $OUTPUT_FILE" -ForegroundColor Green
