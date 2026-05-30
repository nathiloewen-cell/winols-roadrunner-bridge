@echo off
set WINOLS=C:\Program Files\EVC\WinOLS
set SRC=C:\dev\winols-roadrunner-bridge\src\proxy\wdapi1100.dll

net session >nul 2>&1
if errorlevel 1 ( echo Bitte als Administrator ausfuehren. & pause & exit /b 1 )

echo [1/2] Backup original wdapi1100.dll...
if not exist "%WINOLS%\wdapi1100_real.dll" (
    rename "%WINOLS%\wdapi1100.dll" "wdapi1100_real.dll"
    echo       OK: wdapi1100_real.dll
) else (
    echo       Backup existiert bereits.
)

echo [2/2] Proxy installieren...
copy /Y "%SRC%" "%WINOLS%\wdapi1100.dll"
echo       OK: wdapi1100.dll ^(Proxy^)

echo.
dir "%WINOLS%\wdapi1100*"
echo.
echo Log nach WinOLS-Start: %TEMP%\winols_wdapi.log
pause
