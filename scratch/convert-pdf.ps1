# convert-pdf.ps1
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$rootDir = "C:\PIC\熊本旅遊實作"
$scratchDir = Join-Path $rootDir "scratch"
$indexHtml = Join-Path $scratchDir "index.html"
$finalPdf = Join-Path $rootDir "熊本之旅行程表.pdf"

Write-Host "開始執行 PDF 轉檔程序..." -ForegroundColor Cyan

# 1. 取得系統 Temp 目錄
$tempDir = [System.IO.Path]::GetTempPath()
$tempFolder = Join-Path $tempDir "antigravity_pdf_convert"

# 2. 建立暫存資料夾
if (Test-Path $tempFolder) {
    Remove-Item -Path $tempFolder -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $tempFolder -Force | Out-Null

# 3. 複製 index.html 至暫存資料夾
$tempHtml = Join-Path $tempFolder "index.html"
Copy-Item -Path $indexHtml -Destination $tempHtml -Force
Write-Host "已將 HTML 複製到臨時目錄: $tempHtml"

# 4. 執行 Edge 進行轉換
$tempPdf = Join-Path $tempFolder "output.pdf"
$edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

Write-Host "正在呼叫 Microsoft Edge 轉檔為 PDF..."
$process = Start-Process -FilePath $edgePath -ArgumentList "--headless=new", "--disable-gpu", "--no-sandbox", "--print-to-pdf=$tempPdf", "$tempHtml" -NoNewWindow -PassThru -Wait

# 5. 驗證是否產生 PDF
if (Test-Path $tempPdf) {
    $size = (Get-Item $tempPdf).Length
    Write-Host "轉檔成功！臨時 PDF 大小: $size bytes" -ForegroundColor Green
    
    # 複製回專案目錄
    Copy-Item -Path $tempPdf -Destination $finalPdf -Force
    Write-Host "已成功將 PDF 複製回專案目錄: $finalPdf" -ForegroundColor Green
} else {
    Write-Error "轉檔失敗：臨時 PDF 檔案未產生。"
}

# 6. 清理暫存資料夾
Remove-Item -Path $tempFolder -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "暫存資料已清理完成。"
