param(
    [Parameter(Mandatory=$true, HelpMessage="請輸入退版與失敗的原因，這將被強制記錄進 LESSONS_LEARNED.md")]
    [string]$Reason,
    [string]$TargetCommit = "HEAD",
    [switch]$Force
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8


# rollback_safe.ps1 - SSoT 物理安全回滾腳本 (防範 Ghost Files 陷阱)
# 用途：將工作區安全地回滾到指定的 Commit，強制刪除所有幽靈檔案，並強制記錄失敗原因。

# --- 強制編碼鎖定 (針對 PowerShell 5.1 環境) ---

$ROOT_DIR = "$PSScriptRoot\.."
Set-Location $ROOT_DIR

Write-Host "`n--- [SPORT ITS] Safe Rollback Protocol ---" -ForegroundColor Cyan
Write-Host "Target Commit: $TargetCommit" -ForegroundColor Yellow
Write-Host "Failure Reason: $Reason" -ForegroundColor Magenta

# 強制記錄失敗原因
$logPath = "$ROOT_DIR\knowledge\LESSONS_LEARNED.md"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$branchName = git rev-parse --abbrev-ref HEAD
$logEntry = "`n### [Rollback Log] $timestamp ($branchName)`n- **退版原因**: $Reason`n- **退回目標**: $TargetCommit`n"
Add-Content -Path $logPath -Value $logEntry -Encoding UTF8
Write-Host "  - [OK] Failure reason formally logged to LESSONS_LEARNED.md" -ForegroundColor Green

if (-not $Force) {
    Write-Host "`n[WARNING] This action will DESTROY all uncommitted changes and UNTRACKED files in Source Code/." -ForegroundColor Red
    $confirm = Read-Host "Are you sure you want to proceed? (y/N)"
    if ($confirm -notmatch "^y(es)?$") {
        Write-Host "Rollback cancelled by user." -ForegroundColor Gray
        exit 0
    }
}

Write-Host "`nStep 1: Hard Reset to $TargetCommit..." -ForegroundColor Yellow
try {
    # 執行硬重置
    $resetOutput = git reset --hard $TargetCommit 2>&1 | Out-String
    Write-Host "  - $resetOutput" -ForegroundColor Gray
    
    # [關鍵防禦] 執行強制清理，清除所有未追蹤的檔案與目錄 (幽靈檔案)
    Write-Host "Step 2: Physical Clean (Eradicating Ghost Files)..." -ForegroundColor Yellow
    $cleanOutput = git clean -fd "Source Code" 2>&1 | Out-String
    if ($cleanOutput) {
        Write-Host "  - Removed ghost files:`n$cleanOutput" -ForegroundColor Magenta
    } else {
        Write-Host "  - No ghost files detected." -ForegroundColor Green
    }

    Write-Host "Step 3: Verifying Workspace Status..." -ForegroundColor Yellow
    $statusOutput = git status --porcelain
    if ($statusOutput) {
        Write-Warning "  - [!] Workspace still has modifications outside Source Code:"
        Write-Host $statusOutput -ForegroundColor DarkGray
    } else {
        Write-Host "  - [OK] Workspace is 100% pure and clean." -ForegroundColor Green
    }

    Write-Host "`n[SUCCESS] Rollback to $TargetCommit completed safely." -ForegroundColor Green

    # 4. 自動同步看板 (Auto-Sync Dashboard)
    $syncScript = "$PSScriptRoot\90_sync_dashboard.ps1"
    if (Test-Path $syncScript) {
        if ($currentBranch -match "track/(\d+)") { $tid = $Matches[1] } else { $tid = "025" }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $syncScript -TrackID $tid -Message "執行安全回滾至 $TargetCommit (原因: $Reason)"
    }

} catch {
    Write-Error "Rollback failed: $_"
    exit 1
}
