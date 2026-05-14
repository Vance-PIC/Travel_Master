#!/usr/bin/env pwsh
# 32_release_track.ps1 - v16.14.6 (Proxy Edition)
# [SSoT] 影子部署工具 - 已整合至核心 release.ps1

param([switch]$SkipAudit)

& "$PSScriptRoot/release.ps1" -Env track -SkipAudit:$SkipAudit
