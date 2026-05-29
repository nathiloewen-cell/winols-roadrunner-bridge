@echo off
:: WinOLS Roadrunner Bridge — Uninstaller

set WINOLS=C:\Program Files\EVC\WinOLS

net session >nul 2>&1
if errorlevel 1 ( echo Run as Administrator. & pause & exit /b 1 )

echo Restoring original ftd2xx.dll...
if exist "%WINOLS%\ftd2xx.dll.original" (
    copy /Y "%WINOLS%\ftd2xx.dll.original" "%WINOLS%\ftd2xx.dll"
    del "%WINOLS%\ftd2xx.dll.original"
    echo Restored.
) else (
    echo No backup found.
)

echo Removing Roadrunner OLC profiles...
del /Q "%WINOLS%\olc\rr*.olc" 2>nul
echo Done.
pause
