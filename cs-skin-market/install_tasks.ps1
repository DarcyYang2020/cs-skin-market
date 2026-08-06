# Install CS project scheduled tasks (daily DB backup + health alert).
# Run from cs-skin-market/:  powershell -ExecutionPolicy Bypass -File install_tasks.ps1
$ErrorActionPreference = "Stop"
$python = (Get-Command python).Source
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $python) { Write-Error "python not found"; exit 1 }
$backupCmd = '"' + $python + '" "' + $base + '\backup_db.py" --keep 14'
$alertCmd  = '"' + $python + '" "' + $base + '\notify_alert.py" --monitor'
schtasks /Create /TN "CS_DB_Backup" /TR $backupCmd /SC DAILY /ST 23:30 /F
schtasks /Create /TN "CS_Health_Alert" /TR $alertCmd /SC DAILY /ST 22:00 /F  # 22:00: 待 21:30 采集(含健康检查)落库后再告警, 避免读到昨日数据
Write-Host "Tasks installed: CS_DB_Backup (23:30), CS_Health_Alert (22:00, 采集落库后)"
Write-Host "Note: set NOTIFY_WEBHOOK_URL in .env to enable DingTalk alerts."