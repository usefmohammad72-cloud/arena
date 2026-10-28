@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "VERSION=1.0.0"
set "OUTDIR=dist_package"
set "ZIPNAME=STM_Package_v%VERSION%.zip"

echo ============================================
echo   بسته‌بندی ZIP برای توزیع
echo ============================================

REM ---- چک وجود فایل نصبی ----
if not exist "dist_installer\STM_Setup_v%VERSION%.exe" (
    echo [!] فایل نصبی پيدا نشد:
    echo     dist_installer\STM_Setup_v%VERSION%.exe
    echo     اول build.bat را اجرا کن.
    goto :done
)

REM ---- پاک‌سازی و ساخت پوشه موقت ----
if exist "%OUTDIR%" rmdir /s /q "%OUTDIR%"
mkdir "%OUTDIR%"

echo [1/4] کپی فایل نصبی به روت...
copy /y "dist_installer\STM_Setup_v%VERSION%.exe" "%OUTDIR%\"

echo [2/4] ساخت پوشه extras...
mkdir "%OUTDIR%\extras"

echo [3/4] کپی محتويات اضافی...
if exist "README.md"           copy /y "README.md"           "%OUTDIR%\extras\"
if exist "README_PORTABLE.md"  copy /y "README_PORTABLE.md"  "%OUTDIR%\extras\"

REM نسخه پرتابل (اگه می‌خوای پورتال هم داشته باشه)
if exist "dist\STM" (
    echo     کپی نسخه پرتابل ^(dist\STM^)...
    xcopy /e /i /q /y "dist\STM" "%OUTDIR%\extras\portable\"
)

echo [4/4] ساخت فایل راهنما...
(
    echo سامانه تحلیلی مقاطعه ^(STM^) - نسخه %VERSION%
    echo.
    echo ========================================
    echo   راهنمای نصب
    echo ========================================
    echo.
    echo 1^) فایل STM_Setup_v%VERSION%.exe را اجرا کن
    echo 2^) Next ^> Next ^> Install ^> Finish
    echo 3^) آیکون STM روی دسکتاپ ظاهر می‌شود
    echo 4^) دابل‌کلیک روی آیکون ^-^> مرورگر باز می‌شود
    echo 5^) ورود با:
    echo      نام کاربری: 4044588
    echo      رمز عبور:  4180261936
    echo.
    echo ----------------------------------------
    echo   محتويات پوشه extras
    echo ----------------------------------------
    echo - README.md          : مستندات پروژه
    echo - README_PORTABLE.md : راهنمای انتقال
    echo - portable\          : نسخه بدون نصب
    echo.
    echo ----------------------------------------
    echo   پشتیبان‌گیری
    echo ----------------------------------------
    echo داده‌های شما در این مسیر ذخیره می‌شود:
    echo   %%LOCALAPPDATA%%\STM\data
    echo برای پشتیبان‌گیری، همین پوشه را کپی کنید.
) > "%OUTDIR%\راهنما.txt"

echo.
echo ============================================
echo   ساخت فایل ZIP...
echo ============================================
powershell -NoProfile -Command "Compress-Archive -Path '%OUTDIR%\*' -DestinationPath '%ZIPNAME%' -Force"

echo.
echo ============================================
echo   ✅ بسته‌بندی تمام شد
echo   فایل: %ZIPNAME%
echo ============================================

:done
pause