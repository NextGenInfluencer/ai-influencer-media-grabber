@echo off
cd /d "%~dp0"
echo ========================================================
echo  AI Influencer Media Grabber - Setup Builder (Inno Setup)
echo ========================================================
echo.

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    echo [ERROR] Python not found. Please run run.bat first!
    pause
    exit /b 1
)

"%PY%" build_staging.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

pause
