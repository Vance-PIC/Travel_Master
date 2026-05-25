# skills/travelMaster/scripts/audit-doc.ps1
# [v1.0.1] General Document Audit Script for travelMaster Skill

param (
    [string]$TargetDir = "src",
    [string]$RulesFile = "scripts/audit_rules.json"
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

$TARGET_PATH = Join-Path $ROOT_DIR $TargetDir
$RULES_PATH = Join-Path $ROOT_DIR $RulesFile

if (-not (Test-Path $TARGET_PATH)) {
    Write-Host "Error: Target directory '$TargetDir' not found." -ForegroundColor Red
    exit 1
}

$ErrorCount = 0
Write-Host "--- Start General Document Audit on [$TargetDir] ---" -ForegroundColor Cyan

# Load Custom Rules if exists
$CustomRules = @()
if (Test-Path $RULES_PATH) {
    try {
        $rulesContent = Get-Content -Path $RULES_PATH -Raw -Encoding UTF8
        $CustomRules = ConvertFrom-Json $rulesContent
        Write-Host "Loaded custom audit rules from $RulesFile" -ForegroundColor Green
    } catch {
        Write-Host "Warning: Failed to parse audit rules JSON. Proceeding with default rules only." -ForegroundColor Yellow
    }
}

$MdFiles = Get-ChildItem -Path $TARGET_PATH -Filter "*.md"
if ($MdFiles.Count -eq 0 -and $MdFiles -eq $null) {
    Write-Host "No markdown files found in '$TargetDir'." -ForegroundColor Yellow
}

foreach ($file in $MdFiles) {
    $fName = $file.Name
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    
    # 1. Default Rule: Omission Check (Critical)
    if ($content -match "\(略\)|（略）|\.\.\.") {
        Write-Host "FAIL: $fName - Omission detected ('(略)', '（略）', or '...')" -ForegroundColor Red
        $ErrorCount++
    }
    
    # 2. Custom Rules Check
    foreach ($rule in $CustomRules) {
        $pattern = $rule.pattern
        $desc = $rule.description
        $type = $rule.type # "must_match", "must_not_match"
        
        $isMatch = $content -match $pattern
        
        if ($type -eq "must_match" -and -not $isMatch) {
            Write-Host "FAIL: $fName - $desc (Pattern: '$pattern' was not found)" -ForegroundColor Red
            $ErrorCount++
        }
        elseif ($type -eq "must_not_match" -and $isMatch) {
            Write-Host "FAIL: $fName - $desc (Pattern: '$pattern' was found but forbidden)" -ForegroundColor Red
            $ErrorCount++
        }
    }
}

if ($ErrorCount -eq 0) {
    Write-Host "--- General Audit PASS ---" -ForegroundColor Green
    exit 0
} else {
    Write-Host "--- General Audit FAILED: $ErrorCount errors ---" -ForegroundColor Red
    exit 1
}
