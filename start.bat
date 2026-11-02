@echo off
setlocal
cd /d "%~dp0"
title Dubbly - setup and start

rem Already installed: just start the program
if exist ".venv\Scripts\pythonw.exe" if exist ".venv\.ready" goto run

rem 1. Look for a suitable Python (3.12, 3.11, 3.10 or 3.13)
set "PY="
for %%V in (3.12 3.11 3.10 3.13) do (
  if not defined PY (
    py -%%V --version >nul 2>&1 && set "PY=py -%%V"
  )
)

rem 2. Not found: install Python 3.12 with winget
if not defined PY (
  echo Python was not found. Installing Python 3.12 with winget...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
)
if not defined PY goto nopython

rem 3. Virtual environment and libraries (first run only)
echo Installing libraries - first run only, a few minutes...
%PY% -m venv .venv || goto fail

rem Old pip cannot use an https:// system proxy and crashes with a long error.
rem If a system proxy is configured, download directly first and use the proxy only as a fallback.
set "DIRECT="
if defined HTTP_PROXY set "DIRECT=1"
if defined HTTPS_PROXY set "DIRECT=1"
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable 2>nul | find "0x1" >nul && set "DIRECT=1"

if defined DIRECT (
  echo System proxy detected, downloading directly...
  set "NO_PROXY=*"
  call :pipsetup
  if errorlevel 1 (
    echo Direct download failed. Trying through the system proxy...
    set "NO_PROXY="
    call :pipsetup
    if errorlevel 1 goto fail
  )
) else (
  call :pipsetup
  if errorlevel 1 goto fail
)
echo ok> ".venv\.ready"

:run
start "" ".venv\Scripts\pythonw.exe" main.py
exit /b 0

:nopython
echo.
echo Could not install Python automatically.
echo Install Python 3.12 from python.org and tick Add python.exe to PATH,
echo then run this file again.
pause
exit /b 1

:fail
echo.
echo Setup failed. Check your internet connection or turn off VPN and proxy,
echo then run this file again.
pause
exit /b 1

:pipsetup
rem Upgrading pip is optional and its errors are hidden; only the libraries matter
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
exit /b %errorlevel%
