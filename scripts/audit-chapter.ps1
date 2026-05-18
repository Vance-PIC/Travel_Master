#!/usr/bin/env pwsh
# audit-chapter.ps1 - Chapter-Specific Auditor (Quantitative Edition)
# [v1.2.0] 實現定量推薦 (每餐 3 筆) 與必備模組 (含神隊友提醒) 審計

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorCount = 0
$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."

Write-Host "`n[Audit] 啟動章節級「定量與明細」合規性檢核..." -ForegroundColor Cyan
Write-Host ("-" * 50)

$MdFiles = Get-ChildItem -Path (Join-Path $ROOT_DIR "src") -Filter "*.md"

foreach ($file in $MdFiles) {
    Write-Host "[檢查] $($file.Name)" -ForegroundColor Gray
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    
    # 1. 通用檢查：零省略
    if ($content -match "\((略)\)|（略）|\.\.\.") {
        Write-Host "  - [X] 失敗: 偵測到省略記號。" -ForegroundColor Red
        $ErrorCount++
    }

    # 2. 預算章節 (Type A) 檢查
    if ($file.Name -match "Chapter1") {
        if ($content -notmatch "全境財務預算明細") {
            Write-Host "  - [X] 失敗: 缺少「全境財務預算明細」表格。" -ForegroundColor Red
            $ErrorCount++
        }
        # 明細化檢查：若出現「住宿費用 (D1-D6)」等合併字眼則警告
        if ($content -match "住宿.*[D\d]-[D\d]") {
            Write-Host "  - [!] 警告: 偵測到疑似合併的住宿明細，請拆分為一筆一行。" -ForegroundColor Yellow
        }
    }

    # 3. 每日行程 (Type B) 檢查
    if ($file.Name -match "Day") {
        # 3.1 必備模組全量檢查 (Red Blocker)
        $requiredModules = @("📍 今日行程表", "🍴 今日美食地圖", "🛍️ 今日購物攻略", "🏟️ 推薦景點表", "🤝 神隊友提醒|💡 重點筆記")
        foreach ($mod in $requiredModules) {
            if ($content -notmatch $mod) {
                Write-Host "  - [X] 失敗: 缺失必備模組 「$($mod.Replace('|','/'))」" -ForegroundColor Red
                $ErrorCount++
            }
        }

        # 3.2 美食定量檢查 (每餐 3 筆)
        if ($content -match "🍴 今日美食地圖") {
            $categories = @("午", "晚", "宵", "品") # 早餐通常較少，先查核心餐別
            foreach ($cat in $categories) {
                # 統計該餐別在表格中出現的次數
                $matches = [regex]::Matches($content, "(?m)^\|\s*$cat\s*\|")
                if ($matches.Count -lt 3) {
                    Write-Host "  - [!] 警告: 「$cat」餐別僅有 $($matches.Count) 筆推薦 (規格要求至少 3 筆)。" -ForegroundColor Yellow
                }
            }
        }
    }
}

Write-Host ("-" * 50)
if ($ErrorCount -eq 0) {
    Write-Host "[結果] 章節檢核通過！內容符合「鋼鐵紀律」與「定量推薦」規範。" -ForegroundColor Green
    exit 0
} else {
    Write-Host "[結果] 發現 $ErrorCount 個嚴重錯誤，請修正。" -ForegroundColor Red
    exit 1
}
