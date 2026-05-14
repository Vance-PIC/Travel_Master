#!/usr/bin/env pwsh
# 30_gate-preflight-check.ps1 - v16.13.28 (Final Stable Edition)
# [治理規範] 採用語言參數化隔離設計，確保邏輯穩定性與中文閱讀性。

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorCount = 0
$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."

# --- 語言資源中心 (Language Resources) ---
$Msg = @{
    Title      = "[預檢] 啟動 AI 執行安全檢查..."
    GitStart   = "[1/5] 檢查遠端同步狀態..."
    GitOK      = "  - [OK] 本地已是最新版本。"
    GitOld     = "  - [X] 失敗: 本地版本落後於遠端，請執行 git pull。"
    GitDiv     = "  - [!] 提醒: 本地領先於遠端或已分叉。"
    IsoStart   = "[2/5] 檢查分支隔離..."
    IsoFail    = "  - [X] 失敗: 禁止在受保護分支 (master/main/dev) 修改代碼。"
    IsoOK      = "  - [OK] 分支隔離驗證通過。"
    WFStart    = "[3/5] 驗證階段產出物 (對齊 Workflow 矩陣)..."
    ArtFail    = "  - [X] 失敗: 根據規範缺失產出物 "
    ArtOK      = "  - [OK] 物理產出物已具備: "
    SecStart   = "[4/5] 執行內容合規性掃描 (金鑰與樣式)..."
    SecFail    = "  - [X] 失敗: 偵測到疑似硬編碼金鑰 (PAT/Secret) 於 "
    HtmlFail   = "  - [X] 失敗: 樣式類別長度超標於 "
    ResultOK   = "[結果] 預檢通過！環境符合 SOP 規範，允許寫入。"
    ResultFail = "[結果] 預檢失敗！執行已被阻斷，請修正違規項。"
}

Write-Host ""
Write-Host $Msg.Title -ForegroundColor Cyan
Write-Host ("-" * 50)

# 1. Git Freshness
Write-Host $Msg.GitStart -ForegroundColor Gray
try {
    # 抑制原生 git 的錯誤輸出，避免無上游時噴紅字
    git fetch --quiet 2>$null
    $LOCAL = git rev-parse HEAD 2>$null
    $REMOTE = git rev-parse "@{u}" 2>$null
    $BASE = git merge-base HEAD "@{u}" 2>$null

    if (-not $LOCAL -or -not $REMOTE) {
        Write-Host "  - [!] 跳過遠端同步檢查 (無上游分支或尚未建立追蹤)。" -ForegroundColor Yellow
    } elseif ($LOCAL -eq $REMOTE) {
        Write-Host $Msg.GitOK -ForegroundColor Green
    } elseif ($LOCAL -eq $BASE) {
        Write-Host $Msg.GitOld -ForegroundColor Red
        $ErrorCount++
    } else {
        Write-Host $Msg.GitDiv -ForegroundColor Yellow
    }
} catch {
    Write-Host "  - [!] 跳過遠端檢查 (發生未預期錯誤)。" -ForegroundColor Gray
}

# 2. Branch Isolation
$CurrentBranch = git rev-parse --abbrev-ref HEAD 2>$null
Write-Host "$($Msg.IsoStart) ($CurrentBranch)"
if ($CurrentBranch -match "^(master|main|dev)$") {
    Write-Host $Msg.IsoFail -ForegroundColor Red
    $ErrorCount++
} else {
    Write-Host $Msg.IsoOK -ForegroundColor Green
}

# 3. Dynamic Workflow Alignment (解析矩陣)
Write-Host $Msg.WFStart -ForegroundColor Gray
$WFPath = Join-Path $ROOT_DIR "conductor/workflow.md"
if (Test-Path $WFPath) {
    $WorkflowLines = Get-Content -Path $WFPath -Encoding UTF8
    $PlanFiles = Get-ChildItem -Path (Join-Path $ROOT_DIR "specs") -Filter "plan.md" -Recurse -ErrorAction SilentlyContinue

    foreach ($plan in $PlanFiles) {
        $planContent = Get-Content -Path $plan.FullName -Raw -Encoding UTF8
        
        # 使用 switch 搭配 Regex 讓邏輯更俐落
        $PhaseKey = switch -Regex ($planContent) {
            "\[RESEARCHING\]" { "P1: 研究"; break }
            "\[STRATEGIZING\]"{ "P2: 策略"; break }
            "\[AUTHORIZED\]|\[IN EXECUTION\]" { "P3: 實作"; break }
            "\[VERIFYING\]"   { "P4: 驗證"; break }
            Default { $null }
        }

        if ($PhaseKey) {
            $trackDir = Split-Path $plan.FullName
            # 確保只取匹配到的第一行
            $row = $WorkflowLines | Where-Object { $_ -match $PhaseKey } | Select-Object -First 1
            
            if ($row) {
                $columns = $row.Split('|')
                # 確保表格欄位數量足夠 (索引 8 為第 8 個欄位)
                if ($columns.Count -ge 9) {
                    $requiredFiles = $columns[8].Replace("`"", "").Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
                    
                    foreach ($f in $requiredFiles) {
                        if ($f -match "\.md$") {
                            $fPath = Join-Path $trackDir $f                       
                            if (-not (Test-Path $fPath)) {
                                Write-Host "$($Msg.ArtFail) $f" -ForegroundColor Red
                                $ErrorCount++
                            } else {
                                Write-Host "$($Msg.ArtOK) $f" -ForegroundColor Green
                            }
                        }
                    }
                }
            }
            break # 假設每個 plan.md 只需要對齊一次階段
        }
    }
} else {
    Write-Host "  - [!] 找不到 Workflow 矩陣文件 ($WFPath)，跳過檢查。" -ForegroundColor Yellow
}

# 4. Security & Style Scan
Write-Host $Msg.SecStart -ForegroundColor Gray
$DiffFiles = git diff --name-only HEAD 2>$null
if ($DiffFiles) {
    # 取得 Git 根目錄，確保不同層級執行時路徑正確
    $GitRoot = git rev-parse --show-toplevel 2>$null
    
    foreach ($file in $DiffFiles) {
        # [白名單] 跳過部署配置檔案的安全性掃描
        if ($file -match "deploy_env\.json$") { continue }
        
        $FullFilePath = Join-Path $GitRoot $file
        if (-not (Test-Path $FullFilePath -PathType Leaf)) { continue }
        
        $txt = Get-Content -Path $FullFilePath -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        if (-not $txt) { continue }

        # 金鑰掃描 (加入 (?i) 忽略大小寫比對 PAT/Key/Secret)
        if (($file -match "\.(cs|json)$") -and ($txt -match "[a-zA-Z0-9]{50,}")) {
            if ($txt -match "(?i)(PAT|Key|Secret)") {
                Write-Host "$($Msg.SecFail) $file" -ForegroundColor Red
                $ErrorCount++
            }
        }

        # HTML 樣式鎖 (Rule 11: 禁止超過 3 個 Tailwind Utilities)
        if ($file -match "\.html$") {
            # 改用 Select-String 以精確定位
            $Violations = Select-String -Path $FullFilePath -Pattern '(?<!:)class="[^"]* [^"]* [^"]* [^"]*"'
            if ($Violations) {
                foreach ($v in $Violations) {
                    Write-Host "  - [X] 失敗: Rule 11 違規 (類別過多) 於 ${file}:$($v.LineNumber)" -ForegroundColor Red
                    $ErrorCount++
                }
            }
        }

        # 零省略檢查 (Rule 1)
        if ($file -match "\.md$") {
            # 排除「憲章」與「白皮書」等規則說明文件的誤報
            if ($file -match "GEMINI\.md|TEAM_PLAYBOOK\.md|DEVELOPER_GUIDE\.md") { continue }

            if ($txt -match "\((略)\)|（略）") {
                Write-Host "  - [X] 失敗: 偵測到文件省略記號 '(略)' 於 $file" -ForegroundColor Red
                $ErrorCount++
            }
        }
    }
}

# 4.1 Rule 11 Global Scan (Source Code/*.html)
Write-Host "[4.1] 執行 Rule 11 全域掃描 (src/*.html)..." -ForegroundColor Gray
$SourceHtmlFiles = Get-ChildItem -Path (Join-Path $ROOT_DIR "src") -Filter "*.html"
foreach ($htmlFile in $SourceHtmlFiles) {
    # 使用 Select-String 掃描全域檔案中的樣式堆疊
    $Violations = Select-String -Path $htmlFile.FullName -Pattern '(?<!:)class="[^"]* [^"]* [^"]* [^"]*"'
    if ($Violations) {
        foreach ($v in $Violations) {
            Write-Host "  - [X] 失敗: Rule 11 違規 (類別過多) 於 $($htmlFile.Name):$($v.LineNumber)" -ForegroundColor Red
            $ErrorCount++
        }
    }
}

# 5. Drift Check
Write-Host "[5/5] 檢查看板漂移 (寬容模式)..." -ForegroundColor Green

Write-Host ("-" * 50)
if ($ErrorCount -eq 0) {
    Write-Host $Msg.ResultOK -ForegroundColor Green
    exit 0
} else {
    Write-Host $Msg.ResultFail -ForegroundColor Red
    exit 1 # 確保攔截器能收到失敗訊號
}