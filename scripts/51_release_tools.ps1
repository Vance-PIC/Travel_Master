#!/usr/bin/env pwsh
# release_tools.ps1 - v16.13.40 (Quality-First Edition)
# 負責發布 C# Client Tools，具備單元測試強檢。

param(
    [switch]$SkipTests # 除非緊急狀況，否則發布前必須通過測試
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8

$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
$PROJECT_DIR = Join-Path $ROOT_DIR "Source Code/Client Tools"
$TEST_DIR = Join-Path $ROOT_DIR "Source Code/AdoSyncTool.Tests"
$RELEASE_DIR = Join-Path $ROOT_DIR "Tools"
$PROJECT_FILE = Join-Path $PROJECT_DIR "AdoSyncTool.csproj"

Write-Host "`n================================================" -ForegroundColor Cyan
Write-Host "   Starting Client Tools Release (v16.13.40)     " -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# 1. 品質強檢 (Quality Gate)
if (-not $SkipTests -and (Test-Path $TEST_DIR)) {
    Write-Host "步驟 1：執行全量單元測試..." -ForegroundColor Yellow
    Push-Location $TEST_DIR
    dotnet test --nologo --verbosity quiet
    $testResult = $LASTEXITCODE
    Pop-Location
    
    if ($testResult -ne 0) {
        Write-Host "`n[嚴重錯誤] 單元測試未通過！發布已取消。" -ForegroundColor Red
        Write-Host "請修復 C# 邏輯後再行發布。" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "  - [OK] 所有單元測試皆已通過。" -ForegroundColor Green
} else {
    Write-Warning "  - [!] 略過測試階段。"
}

# 2. 執行編譯發布 (Publish)
Write-Host "`n步驟 2：正在編譯單一執行檔 (win-x64)..." -ForegroundColor Yellow
dotnet publish $PROJECT_FILE -c Release -o $RELEASE_DIR -r win-x64 -p:PublishSingleFile=true --self-contained false --nologo

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[失敗] Publish 程序出錯！" -ForegroundColor Red
    exit $LASTEXITCODE
}

# 3. 環境清理
Write-Host "步驟 3：清理非必要檔案 (pdb/json)..." -ForegroundColor Yellow
Get-ChildItem -Path $RELEASE_DIR -Include *.pdb, *.dev.json, *.deps.json -Recurse | Remove-Item -Force

Write-Host "`n[成功] Client Tools 已發布至 $RELEASE_DIR" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
