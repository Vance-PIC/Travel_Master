# gate-p3-execution.ps1 - Compliance Audit for Phase 3 (Execution)
# Usage: powershell .specify/scripts/powershell/gate-p3-execution.ps1 <TrackID>

param (
    [Parameter(Mandatory=$true)]
    [string]$TrackID
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8


$ErrorCount = 0
$SourceDir = "Source Code"

# [Fix] Resolve actual track folder path (Handle suffixes like 024-name)
$TrackFolder = Get-ChildItem -Path "specs" -Directory | Where-Object { $_.Name -match "^$TrackID" } | Select-Object -First 1
if ($TrackFolder) {
    $UatPath = Join-Path $TrackFolder.FullName "UAT_CHECKLIST.md"
} else {
    $UatPath = "specs/$TrackID/UAT_CHECKLIST.md" # Fallback
}

Write-Host "`n[Audit] 開始 Phase 3 執行合規性掃描：$TrackID" -ForegroundColor Cyan
Write-Host "--------------------------------------------------"

# 1. Style Audit (Class length)
Write-Host "[1/3] 掃描硬編碼樣式（class > 255 字元）..."
$HtmlFiles = Get-ChildItem -Path $SourceDir -Filter "*.html" -Recurse | Where-Object { $_.FullName -notmatch "History" -and $_.Name -ne "90_Vendor_Resources.html" }

foreach ($file in $HtmlFiles) {
    $Lines = Get-Content -Path $file.FullName
    $lineNum = 1
    foreach ($line in $Lines) {
        # 頝喲??＊??JavaScript ?摩銵?蝛箄?
        if ($line -match '^\s*(const|let|var|return|computed|setup|watch|if|else|\})' -or $line -match '=>') {
            $lineNum++
            continue
        }

        # 閬? A: ??蝬? (:class) ??隤?????(ui-*) 摰孵? 255 摮?
        if ($line -match '(:class|ui-|badge-|btn-)="([^"]{256,})"') {
            Write-Host "  - [!] 在 $($file.Name):$lineNum 發現過長的語意化/動態類別" -ForegroundColor Yellow
            $ErrorCount++
        }
        # 閬? B: 蝝??′蝺函Ⅳ憿 (class) 摰孵? 255 摮? (?萄儐雿輻??隞?
        elseif ($line -match '(?<![:])class="([^"]{256,})"' -and $line -notmatch "ui-") {
            Write-Host "  - [!] 在 $($file.Name):$lineNum 發現硬編碼樣式超過 255 字元限制" -ForegroundColor Yellow
            $ErrorCount++
        }
        $lineNum++
    }
}
if ($ErrorCount -eq 0) { Write-Host "  - [OK] 樣式審核通過。" -ForegroundColor Green }

# 2. Structural Audit (Duplicate Include)
Write-Host "[2/3] 檢查重複資源引用..."
foreach ($file in $HtmlFiles) {
    $Includes = Select-String -Path $file.FullName -Pattern "include\('([^']+)'\)" | ForEach-Object { $_.Matches.Groups[1].Value }
    $Duplicates = $Includes | Group-Object | Where-Object { $_.Count -gt 1 }
    foreach ($dup in $Duplicates) {
        Write-Host "  - [!] 在 $($file.Name) 發現重複引用 '$($dup.Name)'" -ForegroundColor Yellow
        $ErrorCount++
    }
}
if ($ErrorCount -eq 0) { Write-Host "  - [OK] 結構審核通過。" -ForegroundColor Green }

# 3. UAT Readiness Check
Write-Host "[3/3] 驗證 UAT 驗收清單是否存在..."
if (-not (Test-Path $UatPath)) {
    Write-Host "  - [X] Track 目錄中缺少 UAT_CHECKLIST.md。" -ForegroundColor Red
    $ErrorCount++
} else {
    Write-Host "  - [OK] UAT 驗收清單驗證通過。" -ForegroundColor Green
}

Write-Host "--------------------------------------------------"
if ($ErrorCount -eq 0) {
    Write-Host "[結果] Phase 3 合規性審核通過！" -ForegroundColor Green
    exit 0
} else {
    Write-Host "[結果] Phase 3 合規性審核失敗（共發現 $ErrorCount 個問題）" -ForegroundColor Red
    exit 1
}
