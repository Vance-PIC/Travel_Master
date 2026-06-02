# 1. 記憶目前的專案路徑
$currentProjectDir = Get-Location

# 2. 將 gcloud 總機切換為個人帳號
gcloud config configurations activate personal

# 3. 【強制指派】繞過所有干擾，直接把 Google 官方標準的個人認證路徑強行餵給 agy
$env:GOOGLE_APPLICATION_CREDENTIALS = "$env:APPDATA\gcloud\legacy_credentials\vancechen521.nordvpn@gmail.com\adc.json"

# 如果上行路徑因版本不同不存在，改用標準全域個人路徑：
if (-not (Test-Path $env:GOOGLE_APPLICATION_CREDENTIALS)) {
    $env:GOOGLE_APPLICATION_CREDENTIALS = "$env:APPDATA\gcloud\application_default_credentials.json"
}

# 4. 回到專案目錄
Set-Location $currentProjectDir

Write-Host "=== 已載入 agy 個人帳號環境 ===" -ForegroundColor Cyan
Write-Host "已透過手動憑證路徑鎖定個人帳號軌道！" -ForegroundColor Yellow
Write-Host "正在啟動 Antigravity CLI..." -ForegroundColor Green

# 5. 正式啟動 agy
agy