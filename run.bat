@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==============================================
echo AI Influencer Media Grabber - Startup Script
echo ==============================================

if not exist ".venv" (
    echo Creating Python virtual environment...
    python -m venv .venv
    if errorlevel 1 exit /b 1
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat

rem Re-sync core packages whenever requirements.txt changes (hash stamp, not a one-time marker).
set "REQ_STAMP=.venv\.core-requirements.sha256"
set "REQ_HASH="
set "OLD_HASH="
for /f "usebackq delims=" %%H in (`python -c "import hashlib; print(hashlib.sha256(open('requirements.txt', 'rb').read()).hexdigest())"`) do set "REQ_HASH=%%H"
if exist "%REQ_STAMP%" set /p OLD_HASH=<"%REQ_STAMP%"
set "HAD_ENV="
if exist ".venv\.core-ready" set "HAD_ENV=1"
if defined OLD_HASH set "HAD_ENV=1"

if not "!REQ_HASH!"=="!OLD_HASH!" (
    echo Syncing core dependencies with requirements.txt...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        if not defined HAD_ENV exit /b 1
        echo [WARNING] Core dependencies could not be updated. Starting with the installed packages.
    ) else (
        >"%REQ_STAMP%" echo !REQ_HASH!
        if exist ".venv\.core-ready" del /q ".venv\.core-ready"
    )
)

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
echo Starting Flask server...
rem The in-app Restart button starts a fresh server process itself, so no restart loop is needed.
python app_local.py
echo.
echo Server process exited (code %ERRORLEVEL%). If you restarted from the app, it keeps running in the background.
pause
