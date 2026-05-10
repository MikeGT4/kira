# Kira Windows venv + dependency bootstrap.
# Run from PowerShell (no admin required).
#
# Default source is the repo containing this script ($PSScriptRoot\..).
# Override with -Source to install from a different checkout (e.g. a
# WSL UNC path \\wsl.localhost\Ubuntu\home\<user>\claude_kira).

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$Source = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = "Stop"

$VenvPath = "$env:USERPROFILE\kira-venv"

if (-not (Test-Path (Join-Path $Source 'pyproject.toml'))) {
    Write-Error "Source path '$Source' is not a Kira repo (no pyproject.toml found). Pass -Source <repo-root>."
    exit 1
}

Write-Host "==> Kira Windows bootstrap"
Write-Host "Venv:   $VenvPath"
Write-Host "Source: $Source"
Write-Host ""

# 1. Prereqs
Write-Host "==> Checking prerequisites"
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Error "Python launcher 'py' not found. Install Python 3.12 from python.org or 'winget install Python.Python.3.12'."
    exit 1
}
$pyVersion = & py -3.12 --version 2>&1
if (-not $pyVersion.ToString().StartsWith("Python 3.12")) {
    Write-Error "Python 3.12 required, got: $pyVersion"
    exit 1
}
Write-Host "  Python 3.12: OK ($pyVersion)"

# uv: prefer a real `uv` on PATH; fall back to `py -3.12 -m uv`
$uvCmd = $null
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $uvCmd = "uv"
} else {
    Write-Host "  uv not on PATH — installing via pip"
    & py -3.12 -m pip install --upgrade --quiet uv
    $uvCmd = "py -3.12 -m uv"
}
Write-Host "  uv available: $uvCmd"

# 2. Create venv
if (Test-Path $VenvPath) {
    Write-Host ""
    Write-Host "==> Venv exists at $VenvPath"
    $resp = Read-Host "Recreate? (y/N)"
    if ($resp -eq "y") {
        Remove-Item -Recurse -Force $VenvPath
    }
}
if (-not (Test-Path $VenvPath)) {
    Write-Host "==> Creating venv"
    if ($uvCmd -eq "uv") {
        & uv venv $VenvPath --python 3.12
    } else {
        & py -3.12 -m uv venv $VenvPath --python 3.12
    }
}

# 3. Install Kira (editable) from $Source. UNC paths still need pushd
# inside cmd.exe; local NTFS paths work directly. Use cmd.exe pushd
# for both — handles UNC + NTFS uniformly.
# F2-13: Quote-Escape via PowerShell-Backtick damit Pfade mit Spaces
# (z.B. `OneDrive - Personal`) cmd.exe nicht zerschiessen.
Write-Host ""
Write-Host "==> Installing Kira + windows + dev deps (this can take a few minutes)"
$pyExe = "$VenvPath\Scripts\python.exe"
if ($uvCmd -eq "uv") {
    cmd /c "pushd `"$Source`" && uv pip install --python `"$pyExe`" -e .[windows,dev] && popd"
} else {
    cmd /c "pushd `"$Source`" && py -3.12 -m uv pip install --python `"$pyExe`" -e .[windows,dev] && popd"
}
if ($LASTEXITCODE -ne 0) {
    throw "uv pip install failed (exit $LASTEXITCODE)"
}

# 4. Smoke-test imports
# F2-12: Returncode-Check damit ein silent ImportError (z.B. fehlende
# CUDA-DLLs, Qt6-Plugin-Fail) den Bootstrap zum klaren Fail bringt
# statt halb-installiertes Kira zu hinterlassen.
Write-Host ""
Write-Host "==> Smoke-testing imports"
& $pyExe -c "import faster_whisper, pystray, PyQt6.QtWidgets, keyboard, win32gui, psutil; print('OK')"
if ($LASTEXITCODE -ne 0) {
    throw "Smoke test failed -- one or more imports missing (CUDA DLLs, Qt6 plugins, ...)"
}

# 5. Embed icon + version metadata into kira.exe / kira-once.exe.
Write-Host ""
Write-Host "==> Embedding Kira icon into entry-point EXEs"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\embed_icon.ps1" -VenvPath $VenvPath -Source $Source

Write-Host ""
Write-Host "==> Done."
Write-Host "Launcher: $VenvPath\Scripts\kira.exe"
Write-Host "To install autostart: powershell -ExecutionPolicy Bypass -File $PSScriptRoot\install_autostart.ps1"
