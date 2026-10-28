@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   STM - Setup (one-time)
echo ============================================================
echo.

REM --- Check Python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    echo         Install from https://python.org
    echo         and enable "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [OK] Python %PYVER% detected.
echo.

REM --- Create venv if needed ---
if not exist venv (
    echo [1/4] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv. Check permissions.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Virtual environment already exists. Skipping.
)

call venv\Scripts\activate.bat

REM --- Upgrade pip ---
echo [2/4] Upgrading pip...
python -m pip install --upgrade pip --quiet

REM --- Install requirements ---
echo [3/4] Installing requirements...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)

REM --- Init DB ---
echo [4/4] Initializing database...
if not exist data mkdir data
python -c "import sys; sys.path.insert(0,'.'); from db.database import init_db; init_db('data/app.db'); print('  DB initialized at data/app.db')"
if errorlevel 1 (
    echo [WARN] DB init reported an error - check the app.
)

echo.
echo ============================================================
echo   Setup complete!
echo   Run "run.bat" to start the app.
echo ============================================================
pause
