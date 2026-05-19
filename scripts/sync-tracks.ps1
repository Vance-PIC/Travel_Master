# scripts/sync-tracks.ps1
# [v1.1.1] Robust Version for Progress Sync

param (
    [string]$WP_ID = "",
    [Parameter(Mandatory=$true)]
    [string]$Status,
    [string]$Message = ""
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
$TRACKS_FILE = Join-Path $ROOT_DIR "conductor/doc-tracks.md"
$REPORT_FILE = Join-Path $ROOT_DIR "conductor/progress_report.md"

if (-not (Test-Path $TRACKS_FILE)) { Write-Host "Tracks file not found"; exit 1 }
$tracksContent = Get-Content $TRACKS_FILE -Raw -Encoding UTF8

# --- Auto Detect ---
if ($WP_ID -eq "") {
    $regexDetect = "(?m)^\|\s*(\d{2})\s*\|.*?(?:\[TRACKING\]|\[IN REVIEW\])"
    if ($tracksContent -match $regexDetect) {
        $WP_ID = $matches[1]
        Write-Host "Auto-detected WP-$WP_ID"
    } else {
        Write-Host "No active track found to sync"
        exit 1
    }
}

# --- Map status ---
$step = "Step 0"
$stat = "[PENDING]"
$audit = "⏳ PENDING"

if ($Status -eq "TRACKING") { $step = "Step 2"; $stat = "[TRACKING]"; $audit = "⏳ PENDING" }
elseif ($Status -eq "REVIEW") { $step = "Step 7"; $stat = "[IN REVIEW]"; $audit = "⏳ PENDING" }
elseif ($Status -eq "DONE") { $step = "Step 8"; $stat = "[DONE]"; $audit = "✅ PASS" }

# --- Update doc-tracks.md ---
$lineRegex = "(?m)^\|\s*$WP_ID\s*\|(.*?)\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|"
if ($tracksContent -match $lineRegex) {
    $oldLine = $matches[0]
    $chapter = $matches[1].Trim()
    $memo = $matches[4].Trim()
    if ($Message -ne "") { $memo = $Message }
    $newLine = "| $WP_ID | $chapter | **$step** | $stat | $audit | $memo |"
    $tracksContent = $tracksContent -replace [regex]::Escape($oldLine), $newLine
    $tracksContent | Set-Content $TRACKS_FILE -Encoding UTF8
    Write-Host "Updated doc-tracks.md for WP-$WP_ID"
}

# --- Update progress_report.md ---
$totalCount = ([regex]::Matches($tracksContent, "(?m)^\| \d{2} \|")).Count
$doneCount = ([regex]::Matches($tracksContent, "\[DONE\]")).Count
if ($totalCount -gt 0) {
    $pct = [math]::Round(($doneCount / $totalCount) * 100)
    if (Test-Path $REPORT_FILE) {
        $rep = Get-Content $REPORT_FILE -Raw -Encoding UTF8
        $rep = $rep -replace "總體進度】：\d+%", "總體進度】：$pct%"
        $rep = $rep -replace "\d+/\d+ 章節完工", "$doneCount/$totalCount 章節完工"
        $rep | Set-Content $REPORT_FILE -Encoding UTF8
        Write-Host "Updated progress_report.md to $pct%"
    }
}
Write-Host "Sync Complete"
