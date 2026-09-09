@echo off
setlocal
title AI Influencer Media Grabber - Desktop Shortcut Setup
echo ====================================================================
echo  Creating Native Desktop Window Shortcut for AI Media Grabber...
echo ====================================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\AI Influencer Media Grabber.lnk"
set "TARGET_VBS=%SCRIPT_DIR%launch-silent.vbs"
set "ICON_PATH=%SCRIPT_DIR%assets\app_icon.ico"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$wsh = New-Object -ComObject WScript.Shell; " ^
    "$sc = $wsh.CreateShortcut('%SHORTCUT_PATH%'); " ^
    "$sc.TargetPath = 'wscript.exe'; " ^
    "$sc.Arguments = '\"%TARGET_VBS%\"'; " ^
    "$sc.WorkingDirectory = '%SCRIPT_DIR%'; " ^
    "$sc.Description = 'AI Influencer Media Grabber (Native Desktop App)'; " ^
    "if (Test-Path '%ICON_PATH%') { $sc.IconLocation = '%ICON_PATH%,0' } else { $sc.IconLocation = 'shell32.dll,238' }; " ^
    "$sc.Save();"

echo.
echo [SUCCESS] Desktop Shortcut created successfully!
echo Location: "%SHORTCUT_PATH%"
echo.
echo Double-clicking the shortcut will launch AI Media Grabber in its own
echo sleek native window with NO command prompt and NO browser tabs!
echo.
pause
