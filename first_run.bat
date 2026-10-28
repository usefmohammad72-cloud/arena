@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

if not exist venv (
    echo First-time run detected - setting up...
    echo.
    call setup.bat
    if errorlevel 1 exit /b 1
)

call venv\Scripts\activate.bat

echo ============================================================
echo   Starting STM ...
echo   Browser will open at: http://127.0.0.1:5000
echo   Press Ctrl+C to stop.
echo ============================================================
echo.

python web\app.py

pause
