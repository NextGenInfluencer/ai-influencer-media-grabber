' ====================================================================
' AI Influencer Media Grabber - Native Silent Desktop Launcher
' Boots the local engine silently (0 console windows) and opens
' the app in an independent, frameless Desktop Window.
' ====================================================================

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Get project root directory
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

' 0. Python Runner Detection: Check for embedded python runtime first, then .venv
pythonwExe = ""
If fso.FileExists(scriptDir & "\python_runtime\pythonw.exe") Then
    pythonwExe = scriptDir & "\python_runtime\pythonw.exe"
ElseIf fso.FileExists(scriptDir & "\python\pythonw.exe") Then
    pythonwExe = scriptDir & "\python\pythonw.exe"
Else
    ' Fallback to virtual environment (Original / Developer mode)
    If Not fso.FileExists(scriptDir & "\.venv\Scripts\python.exe") Then
        WshShell.Run """" & scriptDir & "\run.bat"" --setup-only", 1, True
    End If
    pythonwExe = scriptDir & "\.venv\Scripts\pythonw.exe"
    If Not fso.FileExists(pythonwExe) Then
        pythonwExe = scriptDir & "\.venv\Scripts\python.exe"
    End If
End If

appPy = scriptDir & "\app_local.py"

' Helper function: Check if http://127.0.0.1:5000 is answering
Function IsServerOnline()
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.setTimeouts 600, 600, 600, 600
    http.open "GET", "http://127.0.0.1:5000/", False
    http.send
    If Err.Number = 0 Then
        IsServerOnline = True
    Else
        IsServerOnline = False
    End If
    Set http = Nothing
    On Error Goto 0
End Function

' 1. Start Python engine silently if not already running
If Not IsServerOnline() Then
    ' Run pythonw with window mode 0 (completely hidden), no console window
    WshShell.Run """" & pythonwExe & """ """ & appPy & """ --no-browser", 0, False
    
    ' Wait up to 15 seconds for waitress server to become responsive
    For i = 1 To 30
        WScript.Sleep 500
        If IsServerOnline() Then Exit For
    Next
End If

' 2. Locate Microsoft Edge or Google Chrome for App Window mode
edgePath = WshShell.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe")
If Not fso.FileExists(edgePath) Then
    edgePath = WshShell.ExpandEnvironmentStrings("%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")
End If

chromePath = WshShell.ExpandEnvironmentStrings("%ProgramFiles%\Google\Chrome\Application\chrome.exe")
If Not fso.FileExists(chromePath) Then
    chromePath = WshShell.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe")
End If
If Not fso.FileExists(chromePath) Then
    chromePath = WshShell.ExpandEnvironmentStrings("%LocalAppData%\Google\Chrome\Application\chrome.exe")
End If

' Launch in standalone Native Desktop App Mode (no URL bar, no tabs)
appUrl = "http://127.0.0.1:5000"
windowArgs = " --app=" & appUrl & " --window-size=1380,880 --app-id=AiriStudioMediaGrabber"

If fso.FileExists(edgePath) Then
    WshShell.Run """" & edgePath & """" & windowArgs, 1, False
ElseIf fso.FileExists(chromePath) Then
    WshShell.Run """" & chromePath & """" & windowArgs, 1, False
Else
    WshShell.Run appUrl, 1, False
End If
