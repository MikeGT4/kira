# Embed assets/icon-branded.ico + version metadata into kira.exe and
# kira-once.exe.
#
# Why this exists: hatch/setuptools generate the entry-point wrappers
# (kira.exe, kira-once.exe) without an icon resource, so Explorer / the
# desktop / Alt-Tab show the generic Python icon. Run this AFTER each
# `pip install` since pip re-creates the wrappers and wipes any embedded
# icon.
#
# icon-branded.ico = source icon.ico + yellow rounded-square background
# (regenerated via scripts/regenerate_branded_icon.py). The branded
# variant matches the runtime tray icon and stays visible on dark
# Windows-11 backgrounds.
#
# Tooling: electron/rcedit-x64.exe (MIT-licensed, ~1.3 MB PE binary).
# Downloaded once into %USERPROFILE%\tools\ on first run.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File embed_icon.ps1

param(
    [string]$VenvPath = "$env:USERPROFILE\kira-venv",
    [string]$RepoUnc  = "\\wsl.localhost\Ubuntu\home\mikepollow\claude_kira"
)

$ErrorActionPreference = "Stop"

$Tools  = "$env:USERPROFILE\tools"
$Rcedit = "$Tools\rcedit-x64.exe"
$Icon   = Join-Path $RepoUnc "assets\icon-branded.ico"

if (-not (Test-Path $Icon)) {
    Write-Error "Icon not found at $Icon"
    exit 1
}

if (-not (Test-Path $Rcedit)) {
    New-Item -ItemType Directory -Force -Path $Tools | Out-Null
    Write-Host "==> Downloading rcedit-x64.exe v2.0.0 (electron/rcedit, MIT)"
    & curl.exe -L --fail -o $Rcedit "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to download rcedit"
        exit 1
    }
}

# rcedit can't write to a running EXE; stop Kira first.
Write-Host "==> Stopping any running Kira processes"
Get-Process | Where-Object {
    $_.ProcessName -match "^kira$" -or
    ($_.ProcessName -eq "pythonw" -and $_.Path -like "*kira-venv*")
} | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

foreach ($exe in @("kira.exe", "kira-once.exe")) {
    $path = "$VenvPath\Scripts\$exe"
    if (-not (Test-Path $path)) {
        Write-Host "skip: $path (not present -- run pip install first)"
        continue
    }
    Write-Host "==> Embedding into $exe"
    & $Rcedit $path `
        --set-icon $Icon `
        --set-version-string "FileDescription" "Kira voice-to-text" `
        --set-version-string "ProductName" "Kira" `
        --set-version-string "CompanyName" "DigitalRoots" `
        --set-version-string "OriginalFilename" $exe
    if ($LASTEXITCODE -ne 0) {
        Write-Error "rcedit failed on $exe"
        exit 1
    }
}

Write-Host "`n==> Done. Explorer / desktop / Alt-Tab will now show the Kira icon."
