# Kira Windows venv + dependency bootstrap.
# Run from PowerShell (no admin required).
#
# Deviation from the plan's code block: the UNC path (\\wsl.localhost\...)
# cannot be cmd.exe CWD, and pip install -e <unc-path> is interpreted as
# a relative Windows path unless we pushd the UNC first. Therefore we
# use `pushd` inside a cmd /c wrapper for the install step.

$ErrorActionPreference = "Stop"

$VenvPath = "$env:USERPROFILE\kira-venv"
$RepoUnc  = "\\wsl.localhost\Ubuntu\home\mikepollow\claude_kira"

Write-Host "==> Kira Windows bootstrap"
Write-Host "Venv: $VenvPath"
Write-Host "Repo: $RepoUnc"
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
    # Ensure uv is installed as a pip package on Python 3.12
    Write-Host "  uv not on PATH — installing via pip"
    & py -3.12 -m pip install --upgrade --quiet uv
    $uvCmd = "py -3.12 -m uv"
}
Write-Host "  uv available: $uvCmd"

# 2. WSL repo reachable
if (-not (Test-Path $RepoUnc)) {
    Write-Error "Can't reach $RepoUnc. Start WSL (wsl -d Ubuntu -- true) and retry."
    exit 1
}
Write-Host "  WSL repo: reachable"

# 3. Create venv
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

# 4. Install deps — pushd to UNC so pip finds the project path
Write-Host ""
Write-Host "==> Installing Kira + windows + dev deps (this can take a few minutes)"
$pyExe = "$VenvPath\Scripts\python.exe"
if ($uvCmd -eq "uv") {
    cmd /c "pushd $RepoUnc && uv pip install --python $pyExe -e .[windows,dev] && popd"
} else {
    cmd /c "pushd $RepoUnc && py -3.12 -m uv pip install --python $pyExe -e .[windows,dev] && popd"
}

# 5. Smoke-test imports
Write-Host ""
Write-Host "==> Smoke-testing imports"
& $pyExe -c "import faster_whisper, pystray, PyQt6.QtWidgets, keyboard, win32gui, psutil; print('OK')"

# 6. Embed icon + version metadata into kira.exe / kira-once.exe.
# pip just regenerated those wrappers without resource info, so Explorer
# would show the generic Python icon. Re-run after every reinstall.
Write-Host ""
Write-Host "==> Embedding Kira icon into entry-point EXEs"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$RepoUnc\scripts\embed_icon.ps1" -VenvPath $VenvPath -RepoUnc $RepoUnc

Write-Host ""
Write-Host "==> Done."
Write-Host "Launcher: $VenvPath\Scripts\kira.exe"
Write-Host "To install autostart: powershell -ExecutionPolicy Bypass -File $RepoUnc\scripts\install_autostart.ps1"
