@echo off
setlocal
cd /d "%~dp0"

set "PID="
if exist "data\service.pid" set /p PID=<"data\service.pid"

if not defined PID (
  echo [INFO] data\service.pid not found, service is probably not running.
  exit /b 0
)

echo [INFO] Stopping PID=%PID% ...
echo stop > "data\stop.flag"

rem The daemon removes its pid file when it exits. Wait up to 60 seconds.
for /l %%i in (1,1,60) do (
  if not exist "data\service.pid" goto stopped
  ping -n 2 127.0.0.1 >nul
)

echo [WARN] Graceful stop timed out, killing process.
taskkill /PID %PID% /F >nul 2>nul

:stopped
del /q "data\stop.flag" 2>nul
del /q "data\service.pid" 2>nul
echo [ OK ] Service stopped.
exit /b 0
