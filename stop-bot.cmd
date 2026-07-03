@echo off

setlocal

echo Stopping shopping bot processes...

powershell -NoProfile -Command ^

  "$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*shopping_bot.bot*' }; " ^

  "if ($procs) { $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }; " ^

  "Start-Sleep -Seconds 2; " ^

  "$left = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*shopping_bot.bot*' }); " ^

  "if ($left.Count -gt 0) { Write-Host ('Warning: ' + $left.Count + ' bot process(es) still running.') } else { Write-Host 'All bot processes stopped.' }"

echo Done.

