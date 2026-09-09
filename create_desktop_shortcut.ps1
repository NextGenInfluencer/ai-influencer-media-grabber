# Create Desktop Shortcut for AI Influencer Media Grabber
$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [System.Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path -Path $DesktopPath -ChildPath "AI Influencer Media Grabber.lnk"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ScriptDir) { $ScriptDir = (Get-Location).Path }
$TargetVBS = Join-Path -Path $ScriptDir -ChildPath "launch-silent.vbs"
$IconPath = Join-Path -Path $ScriptDir -ChildPath "assets\app_icon.ico"

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "wscript.exe"
$Shortcut.Arguments = "`"$TargetVBS`""
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.Description = "AI Influencer Media Grabber (Native Desktop App)"

if (Test-Path $IconPath) {
    $Shortcut.IconLocation = "$IconPath,0"
} else {
    $Shortcut.IconLocation = "shell32.dll,238"
}

$Shortcut.Save()
Write-Host "[SUCCESS] Desktop shortcut created successfully at:"
Write-Host "  $ShortcutPath" -ForegroundColor Green
