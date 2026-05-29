@echo off
:: Build script for ftd2xx.dll proxy (32-bit, matches WinOLS)
:: Requires: MSYS2 + mingw-w64-i686-gcc
set GCC=C:\msys64\mingw32\bin\i686-w64-mingw32-gcc.exe
set OUT=ftd2xx.dll

echo [BUILD] Compiling 32-bit proxy DLL...

"%GCC%" -shared -o "%OUT%" ftd2xx.c ^
    -Wl,--out-implib,ftd2xx.lib ^
    -Wl,--kill-at ^
    -Wall -Wextra ^
    -DWINVER=0x0601 -D_WIN32_WINNT=0x0601 ^
    -lkernel32 -luser32

if errorlevel 1 (
    echo [ERROR] Build failed.
    exit /b 1
)

echo [OK] Built %OUT%
echo.
echo To install: copy ftd2xx.dll "C:\Program Files\EVC\WinOLS\"
echo Log file:   %%TEMP%%\winols_bridge.log
