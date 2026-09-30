@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==============================================
echo AI Influencer Media Grabber - Startup Script
echo ==============================================

if not exist ".venv" (
    echo Creating Python virtual environment...
    python -m venv .venv
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Verifying core dependencies...
python -m pip install -q -r requirements.txt

if /i "%~1"=="--setup-only" goto setup_complete
goto start_server

:setup_complete
echo.
echo ==============================================
echo Core environment setup complete!
echo (AI Pack can be enabled anytime in-app or via install_ai.bat)
echo ==============================================
timeout /t 2 >nul
exit /b 0

:start_server
:start
echo Starting Flask server...
python app_local.py

if %ERRORLEVEL% EQU 42 (
    echo.
    echo [UI] Restart command received! Rebooting server...
    echo.
    goto start
)

pause
