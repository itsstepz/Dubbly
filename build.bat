@echo off
setlocal
cd /d "%~dp0"
rem Builds Dubbly.exe (run on Windows, Python 3.11 or 3.12)
python -m venv .venv || goto fail
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || goto fail
pyinstaller --noconfirm --windowed --name Dubbly --icon assets\icon.ico --add-data "assets;assets" ^
  --collect-all faster_whisper --collect-all ctranslate2 ^
  --collect-all imageio_ffmpeg --collect-data certifi ^
  --exclude-module tkinter --exclude-module matplotlib --exclude-module pandas ^
  --exclude-module scipy --exclude-module IPython --exclude-module pytest ^
  main.py || goto fail
echo.
echo Done: dist\Dubbly\Dubbly.exe
pause
exit /b 0

:fail
echo.
echo Build failed.
pause
exit /b 1
