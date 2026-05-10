# Create a shortcut in the user's Startup folder that launches Kira
# at Windows login.
#
# Default source is the repo containing this script ($PSScriptRoot\..).
# Override with -Source to point WorkingDirectory at a different checkout.
#
# Uninstall: delete $env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Kira.lnk

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$Source = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = "Stop"

$VenvPath   = "$env:USERPROFILE\kira-venv"
$StartupDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$LinkPath   = Join-Path $StartupDir "Kira.lnk"
$IconPath   = Join-Path $Source "assets\icon-branded.ico"
if (-not (Test-Path $IconPath)) {
    $IconPath = Join-Path $Source "assets\icon.ico"
}

if (-not (Test-Path (Join-Path $Source 'kira'))) {
    Write-Error "Source path '$Source' has no kira/ module dir. Pass -Source <repo-root>."
    exit 1
}
if (-not (Test-Path "$VenvPath\Scripts\kira.exe")) {
    Write-Error "Kira venv not found at $VenvPath. Run install_win.ps1 first."
    exit 1
}

Write-Host "==> Creating autostart shortcut: $LinkPath"
Write-Host "  WorkingDirectory: $Source"

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($LinkPath)
$lnk.TargetPath       = "$VenvPath\Scripts\kira.exe"
$lnk.WorkingDirectory = $Source
$lnk.Description      = "Kira voice-to-text (auto-start)"
if (Test-Path $IconPath) {
    $lnk.IconLocation = "$IconPath,0"
}
$lnk.Save()

Write-Host "==> Autostart installed."
Write-Host "Kira will launch at next login."
Write-Host ""
Write-Host "To remove: del `"$LinkPath`""
