@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   ساخت فایل نصبی STM
echo ============================================

echo.
echo [1/4] نصب پيش‌نيازهای build...
call venv\Scripts\activate.bat 2>nul
if errorlevel 1 (
    echo [!] venv پيدا نشد. اول setup.bat را اجرا کن.
    goto :done
)
pip install pyinstaller --quiet

echo.
echo [2/4] ساخت exe با PyInstaller...
rmdir /s /q build dist 2>nul
pyinstaller STM.spec --noconfirm
if errorlevel 1 goto :err

echo.
echo [3/4] جستجوی Inno Setup...
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe"     set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if "%ISCC%"=="" (
    echo.
    echo [!] Inno Setup 6 پيدا نشد.
    echo     exe در پوشهٔ dist\STM آماده است.
    echo     برای ساخت Setup.exe از https://jrsoftware.org/isdl.php نصب کن.
    goto :done
)

echo.
echo [4/4] ساخت Setup.exe...
"%ISCC%" installer.iss
if errorlevel 1 goto :err

echo.
echo ============================================
echo   ✅ فايل نصب نهايي آماده شد:
echo   dist_installer\STM_Setup_v1.0.0.exe
echo ============================================
goto :done

:err
echo.
echo ❌ خطا در ساخت — پيام بالا را بخوان.

:done
pause