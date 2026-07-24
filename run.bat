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

echo Installing dependencies...
pip install -q -r requirements.txt

:start
echo Starting Flask server...
python app.py

if %ERRORLEVEL% EQU 42 (
    echo.
    echo [UI] Restart command received! Rebooting server...
    echo.
    goto start
)

pause
