@echo off
echo ==============================================
echo Creating Desktop Shortcut for Media Toolkit...
echo ==============================================

set SCRIPT="%TEMP%\%RANDOM%-%RANDOM%-%RANDOM%-%RANDOM%.vbs"
echo Set oWS = WScript.CreateObject("WScript.Shell") >> %SCRIPT%
echo sLinkFile = "%USERPROFILE%\Desktop\Media Toolkit.lnk" >> %SCRIPT%
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> %SCRIPT%
echo oLink.TargetPath = "%~dp0run.bat" >> %SCRIPT%
echo oLink.WorkingDirectory = "%~dp0" >> %SCRIPT%
echo oLink.Description = "Launch AI Media Toolkit" >> %SCRIPT%
echo oLink.IconLocation = "%SystemRoot%\System32\shell32.dll, 115" >> %SCRIPT%
echo oLink.Save >> %SCRIPT%

cscript /nologo %SCRIPT%
del %SCRIPT%

echo.
echo Success! A shortcut named "Media Toolkit" has been placed on your Desktop.
echo You can now launch the app directly from your Desktop!
echo.
pause
