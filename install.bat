@echo off
:: WinOLS Roadrunner Bridge — Installer
:: Run as Administrator

set WINOLS=C:\Program Files\EVC\WinOLS
set PROXY_SRC=%~dp0src\proxy\ftd2xx.dll
set OLC_SRC=%~dp0src\olc

echo ============================================
echo  WinOLS Roadrunner Bridge Installer
echo ============================================
echo.

:: Check admin
net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Please run as Administrator.
    pause & exit /b 1
)

:: Check WinOLS directory
if not exist "%WINOLS%\ols.exe" (
    echo ERROR: WinOLS not found at %WINOLS%
    pause & exit /b 1
)

:: Backup original ftd2xx.dll
if not exist "%WINOLS%\ftd2xx.dll.original" (
    echo [1/3] Backing up original ftd2xx.dll...
    copy "%WINOLS%\ftd2xx.dll" "%WINOLS%\ftd2xx.dll.original"
    echo       Backup: ftd2xx.dll.original
) else (
    echo [1/3] Backup already exists, skipping.
)

:: Install proxy DLL
echo [2/3] Installing proxy ftd2xx.dll...
copy /Y "%PROXY_SRC%" "%WINOLS%\ftd2xx.dll"
echo       Installed: %WINOLS%\ftd2xx.dll

:: Install OLC profiles
echo [3/3] Installing Roadrunner OLC profiles...
for %%f in ("%OLC_SRC%\rr*.olc") do (
    copy /Y "%%f" "%WINOLS%\olc\"
    echo       Installed: %%~nxf
)

echo.
echo ============================================
echo  Installation complete!
echo ============================================
echo.
echo  In WinOLS: Extras ^> Optionen ^> Programmer
echo  Select: "Prog-Express 16"
echo.
echo  Simulator menu will show "Roadrunner : 27C512" etc.
echo.
echo  Log file: %%TEMP%%\winols_bridge.log
echo.
pause
