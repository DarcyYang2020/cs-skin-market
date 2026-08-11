# CS-Market Windows Server one-shot deploy (run as Administrator on the server)
# Pre: Python 3.11 installed (Add to PATH), cs-skin-market copied to $base
$ErrorActionPreference = "Stop"
$base = "C:\cs-market"
Set-Location $base

Write-Host "[1/5] install Python deps..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host "[2/5] install Playwright chromium..."
python -m playwright install chromium

Write-Host "[3/5] register collect/push scheduled tasks (18:00/12:00/21:30/22:00)..."
powershell -ExecutionPolicy Bypass -File install_tasks.ps1

Write-Host "[4/5] register web service auto-start (ONSTART, SYSTEM)..."
$py = (Get-Command python).Source
$cmd = '"' + $py + '" "' + $base + '\run_server.py"'
schtasks /Create /TN "CS_Market_Web" /TR $cmd /SC ONSTART /RU SYSTEM /RL HIGHEST /F

Write-Host "[5/5] first full collect (verifies csQAQ IP binding + kline)..."
python run_daily_collect.py

Write-Host "Deploy done. Web: http://127.0.0.1:8000/  (restart machine once to confirm auto-start)"