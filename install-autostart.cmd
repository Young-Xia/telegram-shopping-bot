@echo off
setlocal
cd /d "%~dp0"

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LINK=%STARTUP%\Telegram Shopping Bot.cmd"

(
  echo @echo off
  echo rem Auto-start Telegram shopping bot at Windows sign-in.
  echo call "%~dp0start-bot-background.cmd"
) > "%LINK%"

echo Installed autostart:
echo   %LINK%
echo.
echo After you sign in to Windows, the bot starts in the background.
echo You can use Telegram on your phone or any device — no need to open this folder.
echo.
echo To remove autostart: uninstall-autostart.cmd
pause
