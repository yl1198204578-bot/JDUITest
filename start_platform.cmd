@echo off
rem ============================================================
rem  Web 平台启动器（Flask，端口 5000）
rem  双击本文件即可。窗口请保持开启，关掉窗口平台就停了。
rem  改了 modules/*.py 或 templates/*.html 后必须重启本文件（FLASK_DEBUG=False）。
rem  日志：_flask_stdout.txt（与本文件同目录）
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY=D:\Program Files\Python37\python.exe"
set "LOG=%~dp0_flask_stdout.txt"

if not exist "%PY%" (
    echo [ERROR] python not found: %PY%
    pause
    exit /b 1
)

echo ================================================
echo  JD UI platform  http://127.0.0.1:5000/
echo  Log: %LOG%
echo  Keep this window open. Ctrl+C to stop.
echo ================================================
echo.

:loop
echo. >> "%LOG%"
echo [%date% %time%] === starting flask === >> "%LOG%"
"%PY%" app.py >> "%LOG%" 2>&1
set "RC=%errorlevel%"

echo [%date% %time%] === flask exited rc=%RC%, restart in 5s === >> "%LOG%"
echo.
echo [!] Flask exited (rc=%RC%). Restarting in 5s...  Press Ctrl+C to abort.
echo.
timeout /t 5 /nobreak >nul
goto loop
