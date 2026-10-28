@echo off
setlocal
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
if not exist "data" mkdir "data"
if exist "data\stop.flag" del /q "data\stop.flag"

rem Do not start a second instance. If the pid file is stale, delete it manually.
if exist "data\service.pid" (
  echo [INFO] data\service.pid already exists. Service may be running.
  echo        If it is not running, delete data\service.pid and retry.
  exit /b 1
)

rem Try PYTHON_EXE, then pythonw, then python, then common Anaconda paths.
set "PY="
if defined PYTHON_EXE set "PY=%PYTHON_EXE%"

if not defined PY (
  pythonw -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=pythonw"
)
if not defined PY (
  python -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY if exist "D:\anaconda3\pythonw.exe" set "PY=D:\anaconda3\pythonw.exe"
if not defined PY if exist "%USERPROFILE%\anaconda3\pythonw.exe" set "PY=%USERPROFILE%\anaconda3\pythonw.exe"

if not defined PY (
  echo [ERROR] Python not found.
  echo Set PYTHON_EXE first, for example:
  echo     set PYTHON_EXE=D:\anaconda3\pythonw.exe
  exit /b 1
)

echo [INFO] Using Python: %PY%
start "" /b "%PY%" "%~dp0main.py" daemon >nul 2>&1

ping -n 3 127.0.0.1 >nul
if not exist "data\service.pid" goto no_pid

set "PID="
set /p PID=<"data\service.pid"
echo [ OK ] Service started, PID=%PID%
echo        Log: %~dp0logs\app.log
exit /b 0

:no_pid
echo [WARN] data\service.pid was not created. Check logs\app.log
exit /b 0
