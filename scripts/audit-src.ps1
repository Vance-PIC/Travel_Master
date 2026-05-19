# scripts/audit-src.ps1
# [v1.4.2] Simplified English Version for Encoding Compatibility

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
$ErrorCount = 0

Write-Host "--- Start Audit ---" -ForegroundColor Cyan

$MdFiles = Get-ChildItem -Path (Join-Path $ROOT_DIR "src") -Filter "*.md"
foreach ($file in $MdFiles) {
    $fName = $file.Name
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    
    # 1. Format Check
    if ($content -match "今日美食地圖") {
        if ($content -notmatch "今日美食地圖 \(定量推薦\)") {
            Write-Host "FAIL: $fName - Gourmet Map Header format error" -ForegroundColor Red
            $ErrorCount++
        }
    }
    
    if ($content -match "神隊友提醒" -and $content -notmatch "🤝 神隊友提醒") {
        Write-Host "FAIL: $fName - Reminder Icon error" -ForegroundColor Red
        $ErrorCount++
    }

    # 2. Content Check
    if ($content -match "\(略\)|（略）|\.\.\.") {
        Write-Host "FAIL: $fName - Omission detected" -ForegroundColor Red
        $ErrorCount++
    }

    if ($fName -match "Day") {
        $cats = @("早", "午", "晚", "品")
        foreach ($cat in $cats) {
            $m = [regex]::Matches($content, "(?m)^\|\s*$cat\s*\|")
            if ($m.Count -lt 3) {
                Write-Host "FAIL: $fName - $cat category only has $($m.Count) items" -ForegroundColor Red
                $ErrorCount++
            }
        }
    }
}

if ($ErrorCount -eq 0) {
    Write-Host "--- Audit PASS ---" -ForegroundColor Green
    exit 0
} else {
    Write-Host "--- Audit FAILED: $ErrorCount errors ---" -ForegroundColor Red
    exit 1
}
