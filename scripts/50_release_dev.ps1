#!/usr/bin/env pwsh
# 50_release_dev.ps1 - v16.14.6 (Proxy Edition)
# [SSoT] 正式 Dev 環境發布工具 - 已整合至核心 release.ps1

param(
    [switch]$SkipAudit,
    [string]$NewVersion 
)

& "$PSScriptRoot/release.ps1" -Env dev -SkipAudit:$SkipAudit -NewVersion $NewVersion
