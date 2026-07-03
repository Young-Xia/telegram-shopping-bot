@echo off
setlocal
cd /d "%~dp0"

echo Installing GUI dependencies (one-time)...
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || (
    echo Failed to create virtual environment.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install -q -U pip
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
".venv\Scripts\python.exe" -m pip install -q -e .
if errorlevel 1 (
  echo pip install failed.
  pause
  exit /b 1
)

echo Done. Launching control panel...
wscript //B "%~dp0start-gui.vbs"
