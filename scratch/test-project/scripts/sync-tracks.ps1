# skills/travelMaster/scripts/sync-tracks.ps1
# [v1.0.0] General Progress Sync Script for travelMaster Skill

param (
    [string]$WP_ID = "",
    [Parameter(Mandatory=$true)]
    [string]$Status,
    [string]$Message = "",
    [string]$TracksFile = "conductor/doc-tracks.md",
    [string]$ReportFile = "conductor/progress_report.md"
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$current = (Get-Item $PSScriptRoot)
$ROOT_DIR = $null
while ($current -ne $null) {
    if ((Test-Path (Join-Path $current.FullName "conductor")) -or (Test-Path (Join-Path $current.FullName "src"))) {
        $ROOT_DIR = $current.FullName
        break
    }
    $current = $current.Parent
}
if ($null -eq $ROOT_DIR) {
    $ROOT_DIR = (Get-Item $PSScriptRoot).Parent.FullName
}

$TRACKS_PATH = Join-Path $ROOT_DIR $TracksFile
$REPORT_PATH = Join-Path $ROOT_DIR $ReportFile

if (-not (Test-Path $TRACKS_PATH)) {
    Write-Host "Error: Tracks file not found at '$TracksFile'" -ForegroundColor Red
    exit 1
}

$tracksContent = Get-Content $TRACKS_PATH -Raw -Encoding UTF8

# --- Auto Detect WP_ID ---
if ($WP_ID -eq "") {
    # Match any numeric or alphabetic task ID that is active (TRACKING or REVIEW)
    $regexDetect = "(?m)^\|\s*([a-zA-Z0-9_-]+)\s*\|.*?(?:\[TRACKING\]|\[IN REVIEW\])"
    if ($tracksContent -match $regexDetect) {
        $WP_ID = $matches[1]
        Write-Host "Auto-detected Active Task: WP-$WP_ID" -ForegroundColor Green
    } else {
        Write-Host "No active track found to sync. Please specify -WP_ID." -ForegroundColor Yellow
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
$lineRegex = "(?m)^\|\s*$WP_ID\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|"
if ($tracksContent -match $lineRegex) {
    $oldLine = $matches[0]
    $chapter = $matches[1].Trim()
    $memo = $matches[5].Trim()
    if ($Message -ne "") { $memo = $Message }
    $newLine = "| $WP_ID | $chapter | **$step** | $stat | $audit | $memo |"
    $tracksContent = $tracksContent -replace [regex]::Escape($oldLine), $newLine
    $tracksContent | Set-Content $TRACKS_PATH -Encoding UTF8
    Write-Host "Updated progress in $TracksFile for task $WP_ID to $Status" -ForegroundColor Green
} else {
    Write-Host "Error: Task ID '$WP_ID' not found in tracks file." -ForegroundColor Red
    exit 1
}

# --- Update progress_report.md ---
$totalCount = ([regex]::Matches($tracksContent, "(?m)^\| \d+ \|")).Count
if ($totalCount -eq 0) {
    # Fallback to general table row count if not matched by digits
    $totalCount = ([regex]::Matches($tracksContent, "(?m)^\|\s*[^|#-]+\s*\|")).Count - 2 # Exclude header & separator
}
$doneCount = ([regex]::Matches($tracksContent, "\[DONE\]")).Count

if ($totalCount -gt 0 -and (Test-Path $REPORT_PATH)) {
    $pct = [math]::Round(($doneCount / $totalCount) * 100)
    $rep = Get-Content $REPORT_PATH -Raw -Encoding UTF8
    
    # Replace percent indicators
    if ($rep -match "總體進度】：\d+%") {
        $rep = $rep -replace "總體進度】：\d+%", "總體進度】：$pct%"
    }
    if ($rep -match "\d+/\d+ 章節完工") {
        $rep = $rep -replace "\d+/\d+ 章節完工", "$doneCount/$totalCount 章節完工"
    }
    
    $rep | Set-Content $REPORT_PATH -Encoding UTF8
    Write-Host "Updated progress report at $ReportFile to $pct% ($doneCount/$totalCount completed)" -ForegroundColor Green
}

Write-Host "Sync Complete" -ForegroundColor Green
