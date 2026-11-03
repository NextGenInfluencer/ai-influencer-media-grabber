@echo off
setlocal
echo ========================================================
echo AI Influencer Media Grabber - AI Engine Pack Installer
echo ========================================================
echo.
echo This installs the optional AI Engine libraries (speech, lyric alignment,
echo vision captions, face tools and the built-in offline assistant).
echo The best pack for this PC is chosen automatically:
echo  - NVIDIA GPU with 6 GB or more: CUDA build (about 2.9 GB download)
echo  - Intel/AMD graphics: CPU build with DirectML (about 0.3 GB)
echo  - Otherwise: CPU build (about 0.3 GB)
echo The exact list, sizes and licenses are shown before anything downloads.
echo Model files are separate and each one asks before downloading.
echo.

cd /d "%~dp0"
set "APP_PYTHON=%~dp0python_runtime\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
    echo Run the core setup first.
    exit /b 1
)

rem Optional: install_ai.bat cpu ^| directml ^| gpu  to override the recommended pack.
if "%~1"=="" (
    "%APP_PYTHON%" -m assets.ai_setup --install
) else (
    "%APP_PYTHON%" -m assets.ai_setup --install --pack %~1
)
if errorlevel 1 (
    echo.
    echo [ERROR] The AI Engine Pack was not installed. Review the messages above.
    pause
    exit /b 1
)

echo.
echo ========================================================
echo Restart the app before using AI features.
echo ========================================================
echo.
pause
