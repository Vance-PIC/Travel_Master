<#
.SYNOPSIS
    26_report_incident.ps1 - 事件響應與回歸研究 (IRRR) 啟動器
    [v1.0] 當實作階段 (Phase 3) 發生異常時，強制執行熔斷並回退至研究狀態。
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$Issue,
    
    [Parameter(Mandatory=$false)]
    [string]$TrackID = "028"
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "`n[🚨 INCIDENT] 偵測到實作異常: $Issue" -ForegroundColor Red
Write-Host "--------------------------------------------------"

# 1. 查找計畫檔案
$planPath = (Get-ChildItem -Path "specs" -Filter "plan.md" -Recurse | Where-Object { $_.FullName -match "$TrackID" } | Select-Object -First 1).FullName
if (-not $planPath) { Write-Error "錯誤: 找不到 Track $TrackID 的計畫書。"; exit 1 }

# 2. 物理熔斷：切換狀態至 RESEARCHING
Write-Host "[1/4] 執行物理熔斷，回退計畫狀態至 [RESEARCHING: INCIDENT]..." -ForegroundColor Yellow
$planContent = Get-Content -Path $planPath -Raw -Encoding UTF8
$planContent = $planContent -replace '\[AUTHORIZED\]|\[IN EXECUTION\]|\[VERIFYING\]|\[DONE\]|\[PENDING\]', "[RESEARCHING: INCIDENT]"
Set-Content -Path $planPath -Value $planContent -Encoding UTF8

# 3. 建立/更新日誌 (Journaling)
Write-Host "[2/4] 正在建立事件日誌軌跡..." -ForegroundColor Gray
$journalPath = Join-Path (Split-Path $planPath) "journal.md"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$incidentLog = @"

## 🚨 INCIDENT REPORT ($timestamp)
- **問題現象**: $Issue
- **觸發位置**: (AI 需於此處填寫檔案與行號)
- **初步影響評估**: 實作階段暫停，需重新執行 Phase 1 & 2。
- **證據截圖/日誌**: (AI 需於此處貼出錯誤輸出)
---
"@
Add-Content -Path $journalPath -Value $incidentLog -Encoding UTF8

# 4. 插入計畫修正區塊 (Plan Injection)
Write-Host "[3/4] 正在計畫書中插入緊急修復區塊..." -ForegroundColor Gray
$recoveryBlock = @"

### Phase 3.X: Incident Repair (緊急修復)
- [ ] **[RESEARCH]** 分析 $Issue 的根因 (Root Cause)。
- [ ] **[STRATEGY]** 提出修正策略並評估對現有設計的影響。
- [ ] **[EXECUTION]** 執行修復並更新原定計畫。
"@
$planContent = $planContent + "`n" + $recoveryBlock
Set-Content -Path $planPath -Value $planContent -Encoding UTF8

# 5. 同步看板
Write-Host "[4/4] 正在同步看板儀表板..." -ForegroundColor Gray
pwsh -NoProfile -Command "chcp 65001; scripts/90_sync_dashboard.ps1 -TrackID $TrackID"

Write-Host "--------------------------------------------------"
Write-Host "[結果] 熔斷機制已啟動。AI 寫入權限已鎖死，請重新開始 Phase 1 研究。" -ForegroundColor Red
