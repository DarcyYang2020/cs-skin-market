# Install CS project scheduled tasks (daily DB backup + health alert).
# Run from cs-skin-market/:  powershell -ExecutionPolicy Bypass -File install_tasks.ps1
$ErrorActionPreference = "Stop"
$python = (Get-Command python).Source
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $python) { Write-Error "python not found"; exit 1 }
$backupCmd = '"' + $python + '" "' + $base + '\backup_db.py" --keep 14'
$alertCmd  = '"' + $python + '" "' + $base + '\notify_alert.py" --monitor'
schtasks /Create /TN "CS_DB_Backup" /TR $backupCmd /SC DAILY /ST 23:30 /F
schtasks /Create /TN "CS_Health_Alert" /TR $alertCmd /SC DAILY /ST 21:30 /F
Write-Host "Tasks installed: CS_DB_Backup (23:30), CS_Health_Alert (21:30)"
Write-Host "Note: set NOTIFY_WEBHOOK_URL in .env to enable DingTalk alerts."