#!/usr/bin/env pwsh

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
# Common PowerShell functions analogous to common.sh
# [v16.13.2] Conductor-Driven Navigation (Table-Lookup Reinforced)

function Get-RepoRoot {
    # 在本專案中，根目錄應包含 conductor 或 Source Code
    $current = $PSScriptRoot
    while ($current -and -not (Test-Path (Join-Path $current "conductor")) -and -not (Test-Path (Join-Path $current "src"))) {
        $parent = Split-Path $current -Parent
        if ($parent -eq $current) { break }
        $current = $parent
    }
    if (Test-Path (Join-Path $current "conductor")) { return $current }

    # Fallback to git
    try {
        $result = git rev-parse --show-toplevel 2>$null
        if ($LASTEXITCODE -eq 0) { return $result.Trim() }
    } catch { }
    return (Resolve-Path (Join-Path $PSScriptRoot "../../..")).Path
}

function Get-CurrentBranch {
    if ($env:SPECIFY_FEATURE) { return $env:SPECIFY_FEATURE }
    try {
        $result = git rev-parse --abbrev-ref HEAD 2>$null
        if ($LASTEXITCODE -eq 0) { return $result.Trim() }
    } catch { }
    return "main"
}

function Test-HasGit {
    try {
        git rev-parse --show-toplevel 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

# --- [SSoT] 查表導航核心 ---
function Get-FeatureDir {
    param(
        [string]$RepoRoot, 
        [string]$Branch,
        [string]$ExplicitTrackID # [v16.15.0] 支援顯式傳入 ID
    )

    $dashboardPath = Join-Path $RepoRoot "conductor/tracks.md"
    $trackId = $ExplicitTrackID
    
    # 若無顯式傳入，則從分支中嘗試擷取
    if (-not $trackId) {
        if ($Branch -match "track/(\d+)") { $trackId = $Matches[1] }
        elseif ($Branch -match "^(\d{3})") { $trackId = $Matches[1] }
    }

    if ($trackId -and (Test-Path $dashboardPath)) {
        # 從看板物理資料夾欄位查找 (精準定位)
        $lines = Get-Content -LiteralPath $dashboardPath -Encoding UTF8
        foreach ($line in $lines) {
            # 支援 [032] 或 **[032]** 格式
            if ($line -match "^\s*\|\s*\*?\[0*$($trackId.TrimStart('0'))\]\*?") {
                $parts = $line -split '\|'
                
                # [v16.15.5] 智慧欄位偵測：
                # 索引 3: 開發中表格 (Folder)
                # 索引 5: 歸檔表格 (Archive Path)
                $folder = ""
                if ($parts.Count -ge 10) {
                    $folder = $parts[3].Trim().Replace('`', '').Replace('*', '')
                } elseif ($parts.Count -ge 5) {
                    $folder = $parts[5].Trim().Replace('`', '').Replace('*', '')
                }

                if ($folder) { 
                    # 若路徑已包含 specs/ 或 knowledge/，則視為相對根目錄之完整路徑
                    if ($folder -match "^(specs/|knowledge/)") {
                        return (Join-Path $RepoRoot $folder)
                    }
                    return (Join-Path $RepoRoot "specs/$folder") 
                }
            }
        }
    }

    # Fallback to old convention (specs/032-name)
    $cleanBranch = $Branch -replace "^track/", ""
    if ($trackId -and $cleanBranch -notmatch "^$trackId") {
        # 如果分支不匹配 ID，嘗試尋找 specs 中以 ID 開頭的目錄
        $found = Get-ChildItem (Join-Path $RepoRoot "specs") -Directory | Where-Object { $_.Name -like "$trackId*" } | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    
    return (Join-Path $RepoRoot "specs/$cleanBranch")
}

function Get-FeaturePathsEnv {
    param([string]$TrackID) # [v16.15.0] 支援手動指定
    
    $repoRoot = Get-RepoRoot
    $currentBranch = Get-CurrentBranch
    $hasGit = Test-HasGit
    $featureDir = Get-FeatureDir -RepoRoot $repoRoot -Branch $currentBranch -ExplicitTrackID $TrackID
    
    [PSCustomObject]@{
        REPO_ROOT     = $repoRoot
        CURRENT_BRANCH = $currentBranch
        HAS_GIT       = $hasGit
        FEATURE_DIR   = $featureDir
        TRACK_ID      = if($TrackID) { $TrackID } else { if($currentBranch -match "(\d+)") { $Matches[1] } else { "" } }
        FEATURE_SPEC  = Join-Path $featureDir 'spec.md'
        IMPL_PLAN     = Join-Path $featureDir 'plan.md'
        TASKS         = Join-Path $featureDir 'tasks.md'
        RESEARCH      = Join-Path $featureDir 'research_report.md'
        DATA_MODEL    = Join-Path $featureDir 'data-model.md'
        QUICKSTART    = Join-Path $featureDir 'quickstart.md'
        CONTRACTS_DIR = Join-Path $featureDir 'contracts'
    }
}

function Test-FileExists {
    param([string]$Path, [string]$Description)
    if (Test-Path -Path $Path -PathType Leaf) {
        Write-Output "  ✓ $Description"
        return $true
    } else {
        Write-Output "  ✗ $Description"
        return $false
    }
}

function Test-DirHasFiles {
    param([string]$Path, [string]$Description)
    if ((Test-Path -Path $Path -PathType Container) -and (Get-ChildItem -Path $Path -ErrorAction SilentlyContinue | Where-Object { -not $_.PSIsContainer } | Select-Object -First 1)) {
        Write-Output "  ✓ $Description"
        return $true
    } else {
        Write-Output "  ✗ $Description"
        return $false
    }
}
