' ====================================================================
' AI Influencer Media Grabber - Native Silent Desktop Launcher
' Boots the local engine silently (0 console windows) and opens
' the app in an independent, frameless Desktop Window.
' ====================================================================

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

' 0. Python Runner Detection: Check for embedded python runtime first, then .venv
pythonExe = ""
If fso.FileExists(scriptDir & "\python_runtime\python.exe") Then
    pythonExe = scriptDir & "\python_runtime\python.exe"
ElseIf fso.FileExists(scriptDir & "\python_runtime\pythonw.exe") Then
    pythonExe = scriptDir & "\python_runtime\pythonw.exe"
ElseIf fso.FileExists(scriptDir & "\python\python.exe") Then
    pythonExe = scriptDir & "\python\python.exe"
ElseIf fso.FileExists(scriptDir & "\python\pythonw.exe") Then
    pythonExe = scriptDir & "\python\pythonw.exe"
Else
    ' Fallback to virtual environment (Original / Developer mode)
    If Not fso.FileExists(scriptDir & "\.venv\Scripts\python.exe") Then
        WshShell.Run """" & scriptDir & "\run.bat"" --setup-only", 1, True
    End If
    pythonExe = scriptDir & "\.venv\Scripts\python.exe"
    If Not fso.FileExists(pythonExe) Then
        pythonExe = scriptDir & "\.venv\Scripts\pythonw.exe"
    End If
End If

appPy = scriptDir & "\app_local.py"

' Helper function: Check if http://127.0.0.1:5000 is answering and up to date
Function IsServerOnline()
    IsServerOnline = False
    On Error Resume Next
    Dim http
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.setTimeouts 500, 500, 500, 500
    http.open "GET", "http://127.0.0.1:5000/api/health_check", False
    http.send
    If Err.Number = 0 Then
        If http.Status = 200 Then
            If InStr(http.responseText, """needs_restart"":true") > 0 Then
                http.open "POST", "http://127.0.0.1:5000/api/shutdown", False
                http.send
                WScript.Sleep 1000
                IsServerOnline = False
            Else
                IsServerOnline = True
            End If
        End If
    End If
    Set http = Nothing
    On Error Goto 0
End Function

' 1. Start Python engine silently if not already running
If Not IsServerOnline() Then
    cmd = """" & pythonExe & """ """ & appPy & """ --no-browser"
    WshShell.Run cmd, 0, False
    
    ' Wait up to 30 seconds for waitress server to become responsive
    For i = 1 To 60
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

If fso.FileExists(chromePath) Then
    WshShell.Run """" & chromePath & """" & windowArgs, 1, False
ElseIf fso.FileExists(edgePath) Then
    WshShell.Run """" & edgePath & """" & windowArgs, 1, False
Else
    WshShell.Run appUrl, 1, False
End If
