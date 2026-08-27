# Install CS project scheduled tasks (daily DB backup + health alert).
# Run from cs-skin-market/:  powershell -ExecutionPolicy Bypass -File install_tasks.ps1
$ErrorActionPreference = "Stop"
$python = (Get-Command python).Source
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $python) { Write-Error "python not found"; exit 1 }
$alertCmd  = '"' + $python + '" "' + $base + '\notify_alert.py" --monitor'
$noonCmd   = '"' + $python + '" "' + $base + '\run_daily_monitor.py" --noon'
# 每日备份由 run_daily_collect 收尾负责(与采集同生命周期, 数据最新); 不再注册独立 CS_DB_Backup 任务(避免每日重复备份)
schtasks /Create /TN "CS_Health_Alert" /TR $alertCmd /SC DAILY /ST 22:00 /F  # 22:00: 待 21:30 采集(含健康检查)落库后再告警, 避免读到昨日数据
schtasks /Create /TN "CS_Skin_NoonMonitor" /TR $noonCmd /SC DAILY /ST 12:00 /F  # 12:00: 午间监控(自选品K线轻量刷新 + 钉钉推送 slot=noon)
Write-Host "Tasks installed: CS_Health_Alert (22:00, 采集落库后), CS_Skin_NoonMonitor (12:00, 午间监控推送)"
Write-Host "Note: set NOTIFY_WEBHOOK_URL in .env to enable DingTalk alerts."
# 2026-08-08: collect/push decoupled - full collect 18:00 (no push), night push 21:30 separate
$collectCmd = '"' + $python + '" "' + $base + '\run_daily_collect.py"'
$nightCmd   = '"' + $python + '" "' + $base + '\run_night_push.py"'
schtasks /Create /TN "CS_Skin_DailyCollect" /TR $collectCmd /SC DAILY /ST 18:00 /F
schtasks /Create /TN "CS_Skin_NightPush" /TR $nightCmd /SC DAILY /ST 21:30 /F
# 2026-08-27 EXEC-2 自动盯盘 · 方案 B（decision-log HC）：每 2h 自选+持仓增量刷新+重算+推送（新 buy S3 钉钉）
$exec2Cmd = '"' + $python + '" "' + $base + '\exec2_auto_watch.py" --scope watchlist'
schtasks /Create /TN "CS_Skin_Exec2Watch" /TR $exec2Cmd /SC HOURLY /MO 2 /F
Write-Host "Tasks installed: CS_Skin_Exec2Watch (每2小时, EXEC-2 自动盯盘 watchlist)"
