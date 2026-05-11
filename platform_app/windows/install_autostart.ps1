param(
    [string]$ExePath = "",
    [string]$Name = "LocalPhotoSharingTray"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent (Split-Path -Parent $ScriptDir)
if ([string]::IsNullOrWhiteSpace($ExePath)) {
    $ExePath = Join-Path $RootDir "dist\LocalPhotoSharingTray.exe"
}

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "EXE not found: $ExePath"
}

$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "$Name.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExePath
$Shortcut.WorkingDirectory = Split-Path -Parent $ExePath
$Shortcut.WindowStyle = 7
$Shortcut.Save()

Write-Host "Autostart shortcut created: $ShortcutPath"
