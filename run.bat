@echo off
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
pip install -q -r requirements.txt

if "%1"=="--setup-only" (
    echo.
    echo ==============================================
    echo Core environment setup complete!
    echo (AI Pack can be enabled anytime in-app or via install_ai.bat)
    echo ==============================================
    timeout /t 2 >nul
    exit /b 0
)

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
