@echo off
setlocal

set "LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Telegram Shopping Bot.cmd"
if exist "%LINK%" (
  del "%LINK%"
  echo Removed autostart entry.
) else (
  echo Autostart entry was not found.
)
pause
