# Build orchestrator for the Kira Windows installer.
# Run from PowerShell on Mike's PC. Output lands in
# C:\Users\mike\OneDrive\Desktop\Kira\Kira-Setup-v<version>.exe
#
# v0.2.0 -- Slim-Bundle. The Whisper + Gemma model copies are gone; the
# first-run wizard (kira/setup_wizard.py) downloads them at runtime via
# huggingface_hub + ollama pull. The installer ships only the embedded
# Python, wheels, and OllamaSetup.exe (~1.5 GB total).
#
# Pre-requisites (script halts with a clear message if missing):
#   - Inno Setup 6 (provides iscc.exe; system-wide, per-user, or on PATH)
#   - %USERPROFILE%\kira-venv exists (Mike's existing dev venv) for pip download

param(
    [switch]$SkipWheelDownload
)

$ErrorActionPreference = "Stop"

# (Get-Item).FullName returns a clean filesystem path; Resolve-Path on a UNC
# returns the provider-qualified form ("Microsoft.PowerShell.Core\FileSystem::...")
# which then breaks downstream tools like git that expect a plain path.
$RepoRoot = (Get-Item (Join-Path $PSScriptRoot "..")).FullName
$BuildDir = Join-Path $RepoRoot "build"
$CacheDir = Join-Path $BuildDir "_cache"
$OutputDir = "C:\Users\mike\OneDrive\Desktop\Kira"
$VenvPython = "$env:USERPROFILE\kira-venv\Scripts\python.exe"

Write-Host "==> Kira installer build"
Write-Host "Repo:   $RepoRoot"
Write-Host "Build:  $BuildDir"
Write-Host "Cache:  $CacheDir"
Write-Host "Output: $OutputDir"

# 1. Read version from pyproject.toml.
$pyproject = Get-Content (Join-Path $RepoRoot "pyproject.toml") -Raw
if ($pyproject -notmatch 'version\s*=\s*"([^"]+)"') {
    throw "Could not parse version from pyproject.toml"
}
$Version = $Matches[1]
Write-Host "Version: $Version"

# 2. Pre-flight: ISCC.
# winget installs JRSoftware.InnoSetup either system-wide ("C:\Program Files
# (x86)\Inno Setup 6\") or per-user ("%LOCALAPPDATA%\Programs\Inno Setup 6\")
# depending on the package source. PATH may not refresh until the shell is
# restarted, so search the common spots before giving up.
$isccCmd = Get-Command iscc.exe -ErrorAction SilentlyContinue
if ($isccCmd) {
    $iscc = $isccCmd.Source
} else {
    $iscc = $null
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $iscc = $c; break }
    }
    if (-not $iscc) {
        throw "ISCC.exe not found in PATH or any of: $($candidates -join '; '). Open a fresh PowerShell (PATH refresh) or run: winget install JRSoftware.InnoSetup"
    }
}
Write-Host "ISCC:   $iscc"

# 3. Pre-flight: dev venv (only used for sanity-check; embedded python does
# the actual wheel download below, so no need for pip in this venv).
if (-not (Test-Path $VenvPython)) {
    throw "Dev venv not found at $env:USERPROFILE\kira-venv. Run scripts/install_win.ps1 first."
}

# 4. Clean and prep build dirs.
if (Test-Path $BuildDir) {
    Get-ChildItem $BuildDir -Exclude "_cache" | Remove-Item -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $BuildDir, $CacheDir | Out-Null

# 5. git archive of the source tree.
# Windows Git treats UNC-mounted WSL repos as owned by another user and
# refuses to operate. -c safe.directory='*' overrides for this single
# invocation only; no global config mutation.
Write-Host ""
Write-Host "==> 1/6 git archive source"
$sourceZip = Join-Path $BuildDir "kira-source.zip"
& git -c safe.directory='*' -C $RepoRoot archive `
    --format=zip --output=$sourceZip windows-port -- `
    kira/ prompts/ assets/icon.ico assets/digitalroots-logo.png assets/kira-splash.png pyproject.toml README.md
if ($LASTEXITCODE -ne 0) { throw "git archive failed (exit $LASTEXITCODE)" }
$sourceDir = Join-Path $BuildDir "kira-source"
New-Item -ItemType Directory -Force -Path $sourceDir | Out-Null
Expand-Archive -Path $sourceZip -DestinationPath $sourceDir -Force
Remove-Item $sourceZip

# 6. Python embedded.
Write-Host ""
Write-Host "==> 2/6 Python 3.12 embedded"
$pyEmbedZip = Join-Path $CacheDir "python-3.12-embed-amd64.zip"
if (-not (Test-Path $pyEmbedZip)) {
    Write-Host "Downloading python-3.12.10-embed-amd64.zip..."
    & curl.exe -L --fail -o $pyEmbedZip `
        "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
    if ($LASTEXITCODE -ne 0) { throw "Failed to download Python embedded" }
}
$pyDir = Join-Path $BuildDir "python"
New-Item -ItemType Directory -Force -Path $pyDir | Out-Null
Expand-Archive -Path $pyEmbedZip -DestinationPath $pyDir -Force
# Enable site.py so venv works.
$pthFile = Get-ChildItem $pyDir -Filter "python3*._pth" | Select-Object -First 1
if ($pthFile) {
    (Get-Content $pthFile.FullName) -replace '^#import site', 'import site' |
        Set-Content $pthFile.FullName
}
# Bootstrap pip into the embedded interpreter so `python -m venv` succeeds.
$getPip = Join-Path $CacheDir "get-pip.py"
if (-not (Test-Path $getPip)) {
    & curl.exe -L --fail -o $getPip "https://bootstrap.pypa.io/get-pip.py"
    if ($LASTEXITCODE -ne 0) { throw "Failed to download get-pip.py" }
}
& "$pyDir\python.exe" $getPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip.py failed in embedded python" }

# 7. Wheels.
# Use the freshly bootstrapped embedded Python (Step 2) instead of the dev
# venv. Mike's kira-venv was created via uv and has no pip module by
# default; the embedded python at $pyDir\python.exe just got pip installed
# from get-pip.py and is the same 3.12 minor as the target.
Write-Host ""
Write-Host "==> 3/6 wheels"
$wheelDir = Join-Path $BuildDir "wheels"
New-Item -ItemType Directory -Force -Path $wheelDir | Out-Null
if ($SkipWheelDownload) {
    Write-Host "skipped (-SkipWheelDownload)"
} else {
    & "$pyDir\python.exe" -m pip download `
        -d $wheelDir `
        -r (Join-Path $RepoRoot "installer\requirements-bundle.txt") `
        --platform win_amd64 `
        --python-version 3.12 `
        --implementation cp `
        --only-binary=:all:
    if ($LASTEXITCODE -ne 0) { throw "pip download failed" }
}

# 8. OllamaSetup.exe -- pulled into installer\embedded\ (committed dir,
# binary itself gitignored). Refresh if stale (>30 days) so we don't ship
# a known-CVE Ollama. Sanity-check the size to catch CDN-error pages and
# truncated downloads early.
Write-Host ""
Write-Host "==> 4/6 OllamaSetup.exe"
$OllamaSetupPath = Join-Path $RepoRoot "installer\embedded\OllamaSetup.exe"
$OllamaUrl = "https://ollama.com/download/OllamaSetup.exe"
$NeedsPull = $true
if (Test-Path $OllamaSetupPath) {
    $age = (Get-Date) - (Get-Item $OllamaSetupPath).LastWriteTime
    if ($age.TotalDays -lt 30) {
        $NeedsPull = $false
        Write-Host "  cached ($([math]::Round($age.TotalDays,1)) days old)"
    }
}
if ($NeedsPull) {
    Write-Host "  pulling fresh from $OllamaUrl..."
    New-Item -ItemType Directory -Force -Path (Split-Path $OllamaSetupPath) | Out-Null
    & curl.exe -L --fail -o $OllamaSetupPath $OllamaUrl
    if ($LASTEXITCODE -ne 0) { throw "Failed to download OllamaSetup.exe" }
}
$OllamaSetupSize = (Get-Item $OllamaSetupPath).Length
Write-Host "  size: $([math]::Round($OllamaSetupSize/1MB, 1)) MB"
if ($OllamaSetupSize -lt 100MB -or $OllamaSetupSize -gt 3GB) {
    throw "OllamaSetup.exe size sanity-check failed: $OllamaSetupSize bytes (expected 100 MB to 3 GB)"
}

# 9. rcedit.
Write-Host ""
Write-Host "==> 5/6 rcedit"
$rcedit = Join-Path $CacheDir "rcedit-x64.exe"
if (-not (Test-Path $rcedit)) {
    & curl.exe -L --fail -o $rcedit `
        "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe"
    if ($LASTEXITCODE -ne 0) { throw "Failed to download rcedit" }
}
Copy-Item $rcedit $BuildDir

# 10. Compile installer.
Write-Host ""
Write-Host "==> 6/6 ISCC compile"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
& $iscc `
    "/DVersion=$Version" `
    "/DBuildDir=$BuildDir" `
    "/DOutputDir=$OutputDir" `
    (Join-Path $RepoRoot "installer\kira.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC compile failed" }

# 11. Result.
Write-Host ""
Write-Host "==> done"
$setupExe = Join-Path $OutputDir "Kira-Setup-v$Version.exe"
if (Test-Path $setupExe) {
    $sizeMB = [math]::Round((Get-Item $setupExe).Length / 1MB, 1)
    Write-Host "Setup: $setupExe ($sizeMB MB)"
}
$splits = Get-ChildItem $OutputDir -Filter "Kira-Setup-v$Version-*.bin" -ErrorAction SilentlyContinue
if ($splits) {
    Write-Host "Disk-spanning splits:"
    foreach ($s in $splits) {
        $smb = [math]::Round($s.Length / 1MB, 1)
        Write-Host "  $($s.Name) ($smb MB)"
    }
}
Write-Host ""
Write-Host "Next steps:"
Write-Host "  gh release create v$Version $OutputDir\Kira-Setup-v$Version.exe \"
Write-Host "    --title 'Kira v$Version' --notes 'Release notes...'"
