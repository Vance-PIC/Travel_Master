# scratch/install-rv.ps1
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$profilePath = $PROFILE
if (-not (Test-Path $profilePath)) {
    Write-Host "Creating new profile: $profilePath"
    New-Item -Type File -Path $profilePath -Force
}

$functionCode = @"

function Show-Doc (`$Path) {
    `$FullPath = (Resolve-Path `$Path).Path
    `$FileUri = "file:///" + `$FullPath.Replace('\', '/')
    Start-Process "msedge.exe" `$FileUri
}
Set-Alias -Name rv -Value Show-Doc
"@

Add-Content -Path $profilePath -Value $functionCode
Write-Host "Successfully installed 'rv' alias to $profilePath"
