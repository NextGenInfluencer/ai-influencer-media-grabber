@echo off
setlocal
echo ========================================================
echo AI Influencer Media Grabber - AI Engine Pack Installer
echo ========================================================
echo.
echo This script will install the optional AI Engine dependencies:
echo  - PyTorch ^& Transformers (BLIP Vision Prompt Extractor)
echo  - OpenAI Whisper (Local Audio Transcription ^& Subtitles)
echo  - LLaMA GGUF (Local AI Assistant ^& Summarization)
echo.
echo Total download size: several GB, plus model files.
echo.

cd /d "%~dp0"
set "APP_PYTHON=%~dp0python_runtime\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
    echo Run the core setup first.
    exit /b 1
)
"%APP_PYTHON%" -m pip install -r requirements-ai.txt

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Failed to install some AI dependencies.
    echo Please check your internet connection and try again.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ========================================================
echo [SUCCESS] AI Engine Pack installed successfully!
echo You can now use all AI features inside the app.
echo ========================================================
echo.
pause
