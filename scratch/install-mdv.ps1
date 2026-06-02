# scratch/install-mdv.ps1
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$profilePath = $PROFILE
# Let's clean the previous conflicting 'rv' text by rewriting the profile with the correct 'mdv' alias.
# Since it was newly created, we can safely overwrite it or clean it up.

$functionCode = @"
function Show-Doc (`$Path) {
    `$FullPath = (Resolve-Path `$Path).Path
    `$FileUri = "file:///" + `$FullPath.Replace('\', '/')
    Start-Process "msedge.exe" `$FileUri
}
# Using 'mdv' instead of conflicting 'rv' (Remove-Variable)
if (Test-Path alias:mdv) { Remove-Item alias:mdv -Force }
Set-Alias -Name mdv -Value Show-Doc
"@

Set-Content -Path $profilePath -Value $functionCode -Encoding UTF8
Write-Host "Successfully installed 'mdv' alias to $profilePath"
