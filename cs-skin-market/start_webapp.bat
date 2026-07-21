@echo off
cd /d "%~dp0"
echo ==================================================
echo   CS-Market Web App
echo   http://127.0.0.1:8000
echo ==================================================
python run_server.py
pause
