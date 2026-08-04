# merge-doc.ps1 - Document Merger (RELEASE Edition)
# [v1.6.0] Multi-Spec Document Merger & PDF Export

param (
    [string]$Spec = "kumamoto",
    [string]$TargetDir = "",
    [string]$OutputFile = "",
    [switch]$Pdf
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

# 自適應探測根目錄
$ScriptPath = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $ScriptPath) { $ScriptPath = (Get-Location).Path }

$current = Get-Item $ScriptPath
$ROOT_DIR = $null
while ($current -ne $null) {
    if ((Test-Path (Join-Path $current.FullName "specs")) -or (Test-Path (Join-Path $current.FullName "conductor"))) {
        $ROOT_DIR = $current.FullName
        break
    }
    $current = $current.Parent
}
if ($null -eq $ROOT_DIR) {
    $ROOT_DIR = Split-Path -Parent $ScriptPath
}

Write-Host "  [Debug] ScriptPath: $ScriptPath"
Write-Host "  [Debug] ROOT_DIR: $ROOT_DIR"

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

$MdFiles = @(Get-ChildItem -LiteralPath $SRC_DIR -Filter "*.md" -File | Sort-Object -Property Name)
Write-Host "  [Debug] Get-ChildItem 找到 $($MdFiles.Count) 個 MD 檔案"

if ($MdFiles.Count -eq 0) {
    Write-Host "警告: 來源路徑中無 any Markdown 檔案。" -ForegroundColor Yellow
    exit 0
}

Write-Host "  [Debug] 排序後共 $($MdFiles.Count) 個 MD 檔案"
$FullContent = New-Object System.Text.StringBuilder

foreach ($file in $MdFiles) {
    Write-Host "  - 正在處理: $($file.Name)"
    $content = [System.IO.File]::ReadAllText($file.FullName, [System.Text.Encoding]::UTF8)
    
    # 取得章節編號 (例如 01, 02.01...)
    if ($file.Name -match "^(\d{2})\.(\d{2})") {
        $chId = "$($matches[1]).$($matches[2])"
        # 在章節最前方插入隱形錨點
        $content = "<div id='ch-$chId'></div>`n`n" + $content
    } elseif ($file.Name -match "^(\d{2})") {
        $chId = $matches[1]
        # 在章節最前方插入隱形錨點
        $content = "<div id='ch-$chId'></div>`n`n" + $content
    }

    # 1. 清理導航行 (只要行內包含 上一頁、下一頁 或 返回總目錄，整行徹底清除)
    $content = $content -replace '(?m)^.*?(上一頁|下一頁|返回總目錄).*?$', ''

    # 2. 連結校準 (指向穩定 ID)
    $content = $content -replace '\.\/(\d{2})\.(\d{2})_.*\.md', '#ch-$1.$2'
    $content = $content -replace '\.\/(\d{2})_.*\.md', '#ch-$1'
    # src 內的附件連結在 RELEASE 輸出位置需少一層
    $content = $content -replace '\.\.\/attachments\/', './attachments/'

    # 依表頭加入 PDF 排版用類型標記，讓不同用途的表格可使用各自的欄寬
    $content = $content -replace '(\| 抵達-離開時間 \| 地點 / 活動 \| 交通方式 \| 距離/時間 \| 重點摘要 \|)', "<div class='table-itinerary'></div>`n`n`$1"
    $content = $content -replace '(\| 餐 \| 推薦餐廳 \(Google Map\) \| 營業時間 / 評分 \| [^\|]+ \| [^\|]+ \|)', "<div class='table-food'></div>`n`n`$1"
    $content = $content -replace '(\| 專櫃／店家 \| 地點 \(Google Map\) \| 營業時間 \| 交通與相對位置 \| 目標與推薦購買 \| 優先 \| 現場策略與備註 \|)', "<div class='table-shopping'></div>`n`n`$1"
    $content = $content -replace '(\| 景點名稱 \(Google Map\) \| 營業時間 / 門票 \| 交通與相對位置 \| 親子亮點 / 防雷備註 \|)', "<div class='table-attractions'></div>`n`n`$1"
    $content = $content -replace '(\| 類別 \| 項目名稱 \| 估算金額 \(日圓\) \| 備註說明 \|)', "<div class='table-budget'></div>`n`n`$1"
    
    [void]$FullContent.AppendLine($content)
    [void]$FullContent.AppendLine("---")
}

# 3. 寫入檔案 (直接寫入，不做額外 regex 處理)
$finalText = $FullContent.ToString()
Write-Host "  [Debug] StringBuilder 總字元數: $($finalText.Length)"
[System.IO.File]::WriteAllText($OUTPUT_FILE, $finalText, $OutputEncoding)

Write-Host ("-" * 50)
Write-Host "[成功] 已產生穩定跳轉文件: $OUTPUT_FILE" -ForegroundColor Green

# 4. PDF 轉換 (當指定 -Pdf 參數時)
if ($Pdf) {
    Write-Host "`n[PDF] 正在啟動 md-to-pdf 轉檔作業..." -ForegroundColor Cyan
    $PdfFile = $OUTPUT_FILE -replace '\.md$', '.pdf'
    $ConfigFile = Join-Path (Split-Path -Parent $OUTPUT_FILE) "md-to-pdf.config.json"
    
    try {
        if (Test-Path $ConfigFile) {
            Write-Host "  - 使用設定檔: $ConfigFile"
        } else {
            Write-Host "  - 未發現設定檔"
        }
        
        $npxCacheDir = Join-Path $env:LOCALAPPDATA "npm-cache\_npx"
        $nodeModulesDir = ""
        if (Test-Path $npxCacheDir) {
            $latestFolder = Get-ChildItem $npxCacheDir -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($latestFolder) {
                $candidate = Join-Path $latestFolder.FullName "node_modules"
                if (Test-Path $candidate) { $nodeModulesDir = $candidate }
            }
        }

        if ($nodeModulesDir) {
            $env:NODE_PATH = $nodeModulesDir
            $escapedMdPath = $OUTPUT_FILE.Replace('\', '/')
            $escapedPdfPath = $PdfFile.Replace('\', '/')
            $escapedConfigPath = $ConfigFile.Replace('\', '/')

            $nodeScript = @"
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const marked = require('marked');

(async () => {
  try {
    const mdPath = '$escapedMdPath';
    const pdfPath = '$escapedPdfPath';
    const configPath = '$escapedConfigPath';
    
    let customCss = '';
    if (fs.existsSync(configPath)) {
      const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
      customCss = config.css || '';
    }

    const browser = await puppeteer.launch({
      executablePath: 'C:\\\\Program Files\\\\Google\\\\Chrome\\\\Application\\\\chrome.exe',
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    const page = await browser.newPage();
    const md = fs.readFileSync(mdPath, 'utf8');
    
    const htmlContent = '<!DOCTYPE html><html><head><meta charset="utf-8"><style>' + customCss + '</style></head><body>' + marked.parse(md) + '</body></html>';

    await page.setContent(htmlContent, { waitUntil: 'networkidle0' });
    await page.pdf({
      path: pdfPath,
      format: 'A4',
      margin: { top: '12mm', bottom: '12mm', left: '12mm', right: '12mm' },
      printBackground: true
    });
    await browser.close();
  } catch (e) {
    console.error(e);
    process.exit(1);
  }
})();
"@
            $tempJs = Join-Path $env:TEMP "render_pdf_temp.cjs"
            Set-Content -Path $tempJs -Value $nodeScript -Encoding UTF8
            node $tempJs
            if (Test-Path $tempJs) { Remove-Item $tempJs -Force }
        } else {
            npx -y md-to-pdf "$OUTPUT_FILE" --config-file "$ConfigFile"
        }

        if (Test-Path $PdfFile) {
            Write-Host "[成功] 已成功產生 PDF 文件: $PdfFile" -ForegroundColor Green
        } else {
            Write-Host "[失敗] 轉換完成，但未發現 PDF 檔案: $PdfFile" -ForegroundColor Red
        }
    } catch {
        Write-Host "錯誤: 執行 md-to-pdf 轉檔時發生例外: $_" -ForegroundColor Red
    }
}
