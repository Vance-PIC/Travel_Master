#!/usr/bin/env pwsh
# scripts/30_gate-preflight-check.ps1
# [v1.4.0] 職人級終極審計 (整合格式/內容/流程/表格安全)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
$ErrorCount = 0

function Write-Section($title) {
    Write-Host "`n=== $title ===" -ForegroundColor Cyan
}

# 1. 📂 格式與結構審計 (Format Check)
Write-Section "1. 📂 格式與結構審計"
$MdFiles = Get-ChildItem -Path (Join-Path $ROOT_DIR "src") -Filter "*.md"
foreach ($file in $MdFiles) {
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    
    # [1.1] 必備標題格式檢查
    if ($content -match "🍴 今日美食地圖" -and $content -notmatch "🍴 今日美食地圖 \(定量推薦\)") {
        Write-Host "[X] $($file.Name): 美食地圖標題不符 (應含「定量推薦」)" -ForegroundColor Red
        $ErrorCount++
    }
    if ($content -match "神隊友提醒" -and $content -notmatch "🤝 神隊友提醒") {
        Write-Host "[X] $($file.Name): 神隊友提醒圖示錯誤 (應使用 🤝)" -ForegroundColor Red
        $ErrorCount++
    }
    
    # [1.2] 表格安全性檢查 (防止破損表格)
    $lines = Get-Content -Path $file.FullName
    $ln = 0
    foreach ($line in $lines) {
        $ln++
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith("|") -and -not $trimmed.EndsWith("|")) {
             Write-Host "[X] $($file.Name):$ln 偵測到損壞表格行 (未閉合)" -ForegroundColor Red
             $ErrorCount++
        }
    }
}

# 2. 🥩 內容與定量審計 (Content Check)
Write-Section "2. 🥩 內容與定量審計"
foreach ($file in $MdFiles) {
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    
    # [2.1] 零省略紀律
    if ($content -match "\(略\)|（略）|\.\.\.") {
        Write-Host "[X] $($file.Name): 偵測到省略號 (略)" -ForegroundColor Red
        $ErrorCount++
    }

    # [2.2] Day 章節定量檢查 (每餐 3 筆)
    if ($file.Name -match "Day") {
        $categories = @("早", "午", "晚", "品")
        foreach ($cat in $categories) {
            $matches = [regex]::Matches($content, "(?m)^\|\s*$cat\s*\|")
            if ($matches.Count -lt 3) {
                Write-Host "[X] $($file.Name): 「$cat」餐別僅 $($matches.Count) 筆 (要求 3 筆以上)" -ForegroundColor Red
                $ErrorCount++
            } else {
                Write-Host "[OK] $($file.Name): 「$cat」餐別 $($matches.Count) 筆" -ForegroundColor Green
            }
        }
    }

    # [2.3] Chapter 1 預算表檢查
    if ($file.Name -match "Chapter1") {
        if ($content -notmatch "全境財務預算明細") {
            Write-Host "[X] $($file.Name): 缺失「全境財務預算明細」表格" -ForegroundColor Red
            $ErrorCount++
        }
    }
}

# 3. 🛡️ 流程實體證據審計 (Process Check)
Write-Section "3. 🛡️ 流程實體證據審計"
$gitStatus = git status --porcelain
if ($gitStatus -match "src/.*\.md") {
    Write-Host "[OK] 偵測到待提交之實體變更。" -ForegroundColor Green
} else {
    Write-Host "[!] 警告: 目前無任何 src 變更，請確認是否已儲存盤案。" -ForegroundColor Yellow
}

Write-Host ("-" * 50)
if ($ErrorCount -eq 0) {
    Write-Host "✅ 審計全數通過！請填寫 Checklist 並請求 Review。" -ForegroundColor Green
    exit 0
} else {
    Write-Host "❌ 發現 $ErrorCount 個嚴重錯誤！請修正後再執行。" -ForegroundColor Red
    exit 1
}
