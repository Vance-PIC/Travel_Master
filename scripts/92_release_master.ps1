#!/usr/bin/env pwsh
# 92_release_master.ps1 - v16.14.6 (Proxy Edition)
# [SSoT] 正式 Master 環境發布工具 - 已整合至核心 release.ps1

param([switch]$SkipAudit)

& "$PSScriptRoot/release.ps1" -Env master -SkipAudit:$SkipAudit
