@echo off
setlocal
cd /d "%~dp0"

if not exist ".env" (
  echo Missing .env. Open the control panel and complete initial setup first.
  exit /b 1
)

if not exist ".venv\Scripts\pythonw.exe" (
  echo Missing virtual environment. Run bootstrap-gui.cmd first.
  exit /b 1
)

call stop-bot.cmd
timeout /t 2 /nobreak >nul

if not exist "logs" mkdir logs

set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
start "" /MIN ".venv\Scripts\pythonw.exe" -m shopping_bot.bot

echo Bot started in background (no window needed).
echo Log file: %CD%\logs\bot.log
echo Stop with: stop-bot.cmd
