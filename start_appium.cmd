@echo off
rem ============================================================
rem  Appium 常驻启动器（带崩溃自动拉起）
rem  双击本文件即可。窗口请保持开启，关掉窗口 Appium 就停了。
rem  日志：_appium_stdout.txt（与本文件同目录）
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "NODE=C:\Users\pc\nodejs\node.exe"
set "APPIUM_JS=C:\Users\pc\nodejs\node_modules\appium\index.js"
set "ADB=D:\Android\platform-tools\adb.exe"
set "LOG=%~dp0_appium_stdout.txt"

if not exist "%NODE%" (
    echo [ERROR] node.exe not found: %NODE%
    pause
    exit /b 1
)
if not exist "%APPIUM_JS%" (
    echo [ERROR] appium not found: %APPIUM_JS%
    pause
    exit /b 1
)

echo ================================================
echo  Appium launcher  (auto-restart on crash)
echo  Log: %LOG%
echo  Keep this window open. Ctrl+C to stop.
echo ================================================
echo.

:loop
echo. >> "%LOG%"
echo [%date% %time%] === starting appium === >> "%LOG%"

if exist "%ADB%" (
    echo [%date% %time%] adb devices before start: >> "%LOG%"
    "%ADB%" devices >> "%LOG%" 2>&1
)

"%NODE%" "%APPIUM_JS%" --address 127.0.0.1 --port 4723 --session-override >> "%LOG%" 2>&1
set "RC=%errorlevel%"

echo [%date% %time%] === appium exited rc=%RC%, restart in 5s === >> "%LOG%"
echo.
echo [!] Appium exited (rc=%RC%). Restarting in 5s...  Press Ctrl+C to abort.
echo.
timeout /t 5 /nobreak >nul
goto loop
