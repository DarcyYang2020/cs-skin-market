@echo off
cd /d "%~dp0"
echo ==================================================
echo   CS-Market Web App
echo   http://127.0.0.1:8000
echo ==================================================
"C:\Users\81572\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m webapp.main
pause