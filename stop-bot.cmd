@echo off
setlocal
cd /d "%~dp0"

echo Stopping shopping bot processes...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pidFile = Join-Path (Resolve-Path '.').Path 'logs\bot.pid'; " ^
  "$targets = @(); " ^
  "if (Test-Path $pidFile) { " ^
  "  $raw = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1; " ^
  "  $parsed = 0; " ^
  "  if ([int]::TryParse([string]$raw, [ref]$parsed)) { " ^
  "    $proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $parsed) -ErrorAction SilentlyContinue; " ^
  "    $cmd = ([string]$proc.CommandLine).ToLower(); " ^
  "    if ($cmd -notlike '*shopping_bot.gui*' -and (($cmd -like '*shopping_bot.bot*') -or ($cmd -like '*src\shopping_bot\bot.py*') -or ($cmd -like '*src/shopping_bot/bot.py*'))) { $targets += $parsed } " ^
  "  } " ^
  "} " ^
  "$procs = Get-CimInstance Win32_Process | Where-Object { " ^
  "  $cmd = ([string]$_.CommandLine).ToLower(); " ^
  "  $cmd -notlike '*shopping_bot.gui*' -and (($cmd -like '*shopping_bot.bot*') -or ($cmd -like '*src\shopping_bot\bot.py*') -or ($cmd -like '*src/shopping_bot/bot.py*')) " ^
  "}; " ^
  "if ($procs) { $targets += @($procs | ForEach-Object { $_.ProcessId }) } " ^
  "$targets = @($targets | Sort-Object -Unique); " ^
  "foreach ($targetPid in $targets) { Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue } " ^
  "Start-Sleep -Seconds 1; " ^
  "$left = @(Get-CimInstance Win32_Process | Where-Object { " ^
  "  $cmd = ([string]$_.CommandLine).ToLower(); " ^
  "  $cmd -notlike '*shopping_bot.gui*' -and (($cmd -like '*shopping_bot.bot*') -or ($cmd -like '*src\shopping_bot\bot.py*') -or ($cmd -like '*src/shopping_bot/bot.py*')) " ^
  "}); " ^
  "if ($left.Count -gt 0) { Write-Host ('Warning: ' + $left.Count + ' bot process(es) still running.') } else { if (Test-Path $pidFile) { Remove-Item $pidFile -Force -ErrorAction SilentlyContinue }; Write-Host 'All bot processes stopped.' }"

echo Done.
