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
echo Total download size: approx. 1.2 GB - 1.8 GB.
echo.

if not exist ".venv" (
    echo [ERROR] Virtual environment (.venv) not found.
    echo Please run run.bat first to initialize the core app!
    pause
    exit /b 1
)

echo Activating Python virtual environment...
call .venv\Scripts\activate.bat

echo.
echo Installing AI Engine dependencies (this may take a few minutes)...
pip install -r requirements-ai.txt

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
