# Fetch a faster-whisper CTranslate2 model directly via curl into a flat
# local directory. Bypasses Hugging Face Hub's xet-CDN, which has silent
# failures for large LFS files when called from pythonw.exe (observed
# 2026-04-25: model.bin would never start downloading, Kira hung in the
# "Transcribing…" state forever).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File fetch_whisper_local.ps1
#   # or with custom repo / target:
#   powershell -ExecutionPolicy Bypass -File fetch_whisper_local.ps1 `
#     -Repo "Systran/faster-whisper-large-v3" `
#     -Target "$env:USERPROFILE\models\faster-whisper-large-v3"
#
# After the script finishes, set in %APPDATA%\Kira\config.yaml:
#   whisper:
#     model: C:/Users/<you>/models/faster-whisper-large-v3

param(
    [string]$Repo   = "Systran/faster-whisper-large-v3",
    [string]$Target = "$env:USERPROFILE\models\faster-whisper-large-v3"
)

$ErrorActionPreference = "Stop"

$Files = @("config.json", "preprocessor_config.json", "tokenizer.json", "vocabulary.json", "model.bin")
$Base  = "https://huggingface.co/$Repo/resolve/main"

New-Item -ItemType Directory -Force -Path $Target | Out-Null
Write-Host "==> Target: $Target"
Write-Host "==> Repo:   $Repo`n"

foreach ($f in $Files) {
    $dst = Join-Path $Target $f
    if (Test-Path $dst) {
        $size = (Get-Item $dst).Length
        Write-Host ("--> $f already exists ({0:N1} MB) — skipping" -f ($size / 1MB))
        continue
    }
    Write-Host "==> Downloading $f"
    & curl.exe -L --fail --retry 3 --retry-delay 5 -o $dst "$Base/$f"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "curl failed for $f (exit $LASTEXITCODE)"
        exit 1
    }
}

Write-Host "`n==> Done. Files:"
Get-ChildItem $Target | Select-Object Name, @{N="MB";E={[math]::Round($_.Length/1MB,1)}}

Write-Host "`nNext step — set in %APPDATA%\Kira\config.yaml:"
Write-Host "  whisper:"
Write-Host "    model: $($Target -replace '\\','/')"
