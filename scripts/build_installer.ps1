# Build orchestrator for the Kira Windows installer.
# Run from PowerShell on Mike's PC. Output lands in
# C:\Users\mike\OneDrive\Desktop\Kira\Kira-Setup-v<version>.exe
#
# Pre-requisites (script halts with a clear message if missing):
#   - winget install JRSoftware.InnoSetup   (provides iscc.exe)
#   - WSL Ollama has gemma3:12b              (`ollama pull gemma3:12b`)
#   - %USERPROFILE%\models\faster-whisper-large-v3\ exists
#   - %USERPROFILE%\kira-venv exists (Mike's existing dev venv) for pip download

param(
    [switch]$SkipWheelDownload,
    [switch]$SkipModelCopy
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

# 3. Pre-flight: WSL Ollama gemma3:12b storage.
$WslManifest = "\\wsl.localhost\Ubuntu\usr\share\ollama\.ollama\models\manifests\registry.ollama.ai\library\gemma3\12b"
if (-not (Test-Path $WslManifest)) {
    throw "WSL Ollama lacks gemma3:12b. In WSL run: ollama pull gemma3:12b"
}
Write-Host "WSL Ollama gemma3:12b: ok"

# 4. Pre-flight: local whisper model.
$LocalWhisper = "$env:USERPROFILE\models\faster-whisper-large-v3"
if (-not (Test-Path "$LocalWhisper\model.bin")) {
    throw "Whisper model.bin missing at $LocalWhisper. Run scripts/fetch_whisper_local.ps1 first."
}
Write-Host "Whisper model: ok"

# 5. Pre-flight: dev venv.
if (-not (Test-Path $VenvPython)) {
    throw "Dev venv not found at $env:USERPROFILE\kira-venv. Run scripts/install_win.ps1 first."
}

# 6. Clean and prep build dirs.
if (Test-Path $BuildDir) {
    Get-ChildItem $BuildDir -Exclude "_cache" | Remove-Item -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $BuildDir, $CacheDir | Out-Null

# 7. git archive of the source tree.
# Windows Git treats UNC-mounted WSL repos as owned by another user and
# refuses to operate. -c safe.directory='*' overrides for this single
# invocation only; no global config mutation.
Write-Host ""
Write-Host "==> 1/9 git archive source"
$sourceZip = Join-Path $BuildDir "kira-source.zip"
& git -c safe.directory='*' -C $RepoRoot archive `
    --format=zip --output=$sourceZip windows-port -- `
    kira/ prompts/ assets/icon.ico assets/digitalroots-logo.png assets/kira-splash.png pyproject.toml README.md
if ($LASTEXITCODE -ne 0) { throw "git archive failed (exit $LASTEXITCODE)" }
$sourceDir = Join-Path $BuildDir "kira-source"
New-Item -ItemType Directory -Force -Path $sourceDir | Out-Null
Expand-Archive -Path $sourceZip -DestinationPath $sourceDir -Force
Remove-Item $sourceZip

# 8. Python embedded.
Write-Host ""
Write-Host "==> 2/9 Python 3.12 embedded"
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

# 9. Wheels.
# Use the freshly bootstrapped embedded Python (Step 2) instead of the dev
# venv. Mike's kira-venv was created via uv and has no pip module by
# default; the embedded python at $pyDir\python.exe just got pip installed
# from get-pip.py and is the same 3.12 minor as the target.
Write-Host ""
Write-Host "==> 3/9 wheels"
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

# 10. OllamaSetup.exe.
Write-Host ""
Write-Host "==> 4/9 OllamaSetup.exe"
$ollamaSetup = Join-Path $CacheDir "OllamaSetup.exe"
if (-not (Test-Path $ollamaSetup)) {
    & curl.exe -L --fail -o $ollamaSetup "https://ollama.com/download/OllamaSetup.exe"
    if ($LASTEXITCODE -ne 0) { throw "Failed to download OllamaSetup.exe" }
}
Copy-Item $ollamaSetup $BuildDir

# 11. Whisper model.
Write-Host ""
Write-Host "==> 5/9 Whisper model copy"
if ($SkipModelCopy) {
    Write-Host "skipped (-SkipModelCopy)"
} else {
    $whisperOut = Join-Path $BuildDir "whisper"
    & robocopy.exe $LocalWhisper $whisperOut /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "robocopy whisper failed: $LASTEXITCODE" }
}

# 12. Ollama storage gemma3:12b.
Write-Host ""
Write-Host "==> 6/9 Ollama storage (gemma3:12b)"
if ($SkipModelCopy) {
    Write-Host "skipped (-SkipModelCopy)"
} else {
    $ollamaOut = Join-Path $BuildDir "ollama-models"
    $manifestOut = Join-Path $ollamaOut "manifests\registry.ollama.ai\library\gemma3"
    $blobsOut = Join-Path $ollamaOut "blobs"
    New-Item -ItemType Directory -Force -Path $manifestOut, $blobsOut | Out-Null

    # Copy the 12b manifest.
    Copy-Item -Recurse -Force $WslManifest (Join-Path $manifestOut "12b")

    # Parse manifest for layer digests, copy each blob.
    $manifestJson = Get-Content $WslManifest -Raw | ConvertFrom-Json
    $allDigests = @()
    if ($manifestJson.config.digest) { $allDigests += $manifestJson.config.digest }
    if ($manifestJson.layers) {
        foreach ($layer in $manifestJson.layers) { $allDigests += $layer.digest }
    }
    Write-Host "Copying $($allDigests.Count) blobs..."
    $WslBlobs = "\\wsl.localhost\Ubuntu\usr\share\ollama\.ollama\models\blobs"
    foreach ($digest in $allDigests) {
        # Blob filename format: sha256-<hex> (no colon).
        $blobName = $digest -replace ':', '-'
        $src = Join-Path $WslBlobs $blobName
        if (-not (Test-Path $src)) {
            throw "blob missing in WSL Ollama: $blobName"
        }
        # Copy-Item over \\wsl.localhost\ for files > ~2 GB throws
        # "Nicht genügend Systemressourcen" — Windows tries to memory-map
        # the whole file via the SMB layer. Robocopy streams chunks and
        # is UNC-resilient. /J = unbuffered I/O (mandatory for blobs > 2 GB),
        # /NFL /NDL /NJH /NJS /NP = quiet output (no per-file/dir/header/
        # summary/percentage spam), /R:2 /W:5 = retry twice with 5s wait
        # so a transient SMB hiccup doesn't fail the build.
        $dst = Join-Path $blobsOut $blobName
        if (Test-Path $dst) { Remove-Item -Force $dst }
        & robocopy.exe $WslBlobs $blobsOut $blobName `
            /J /NFL /NDL /NJH /NJS /NP /R:2 /W:5 | Out-Null
        # Robocopy exit codes 0-7 are success, 8+ are real failures.
        if ($LASTEXITCODE -ge 8) {
            throw "robocopy failed with exit code $LASTEXITCODE while copying $blobName"
        }
    }
}

# 13. rcedit.
Write-Host ""
Write-Host "==> 7/9 rcedit"
$rcedit = Join-Path $CacheDir "rcedit-x64.exe"
if (-not (Test-Path $rcedit)) {
    & curl.exe -L --fail -o $rcedit `
        "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe"
    if ($LASTEXITCODE -ne 0) { throw "Failed to download rcedit" }
}
Copy-Item $rcedit $BuildDir

# 14. Compile installer.
Write-Host ""
Write-Host "==> 8/9 ISCC compile"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
& $iscc `
    "/DVersion=$Version" `
    "/DBuildDir=$BuildDir" `
    "/DOutputDir=$OutputDir" `
    (Join-Path $RepoRoot "installer\kira.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC compile failed" }

# 15. Result.
Write-Host ""
Write-Host "==> 9/9 done"
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
