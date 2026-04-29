# Create a shortcut in the user's Startup folder that launches Kira
# at Windows login.
#
# Uninstall: delete $env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Kira.lnk

$ErrorActionPreference = "Stop"

$VenvPath   = "$env:USERPROFILE\kira-venv"
$RepoUnc    = "\\wsl.localhost\Ubuntu\home\mikepollow\claude_kira"
$StartupDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$LinkPath   = Join-Path $StartupDir "Kira.lnk"
$IconPath   = Join-Path $RepoUnc "assets\icon.ico"

if (-not (Test-Path "$VenvPath\Scripts\kira.exe")) {
    Write-Error "Kira venv not found at $VenvPath. Run install_win.ps1 first."
    exit 1
}

Write-Host "==> Creating autostart shortcut: $LinkPath"

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($LinkPath)
$lnk.TargetPath       = "$VenvPath\Scripts\kira.exe"
$lnk.WorkingDirectory = $RepoUnc
$lnk.Description      = "Kira voice-to-text (auto-start)"
if (Test-Path $IconPath) {
    $lnk.IconLocation = "$IconPath,0"
}
$lnk.Save()

Write-Host "==> Autostart installed."
Write-Host "Kira will launch at next login."
Write-Host ""
Write-Host "To remove: del `"$LinkPath`""
