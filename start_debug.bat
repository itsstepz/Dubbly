@echo off
cd /d "%~dp0"
rem Starts Dubbly with a console window so error messages stay visible
".venv\Scripts\python.exe" main.py
pause
