"""GitHub-Release-based update checker. Pure logic, no UI.

v0.2: Multi-Asset-Bundle-Support. Kira's Inno-Installer wird mit
DiskSpanning gebaut und produziert 1 Setup-Stub + 7 .bin-Splits.
Alle 8 Files muessen vom Updater in DASSELBE Verzeichnis geladen
werden, sonst scheitert der Setup-Stub mit "missing data file".

Optional: ein SHA256SUMS-Asset im Release wird vor dem Setup-Start
gegen die runtergeladenen Files verifiziert. Fehlt es, log warning
+ proceed (Mike's Build-Pipeline kann das nachreichen ohne dass
v0.2-Clients sich daran verschlucken).
"""
from __future__ import annotations
import hashlib
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from packaging.version import InvalidVersion, parse as parse_version

log = logging.getLogger(__name__)

UpdateStatus = Literal["newer", "current", "local_newer", "no_asset", "failed"]
_SETUP_PREFIX = "Kira-Setup-"
_SETUP_SUFFIX = ".exe"
_SHA256SUMS_NAME = "SHA256SUMS.txt"
_TIMEOUT_SECONDS = 10.0

# Asset-Name-Whitelist: 'Kira-Setup-vX.Y.Z.exe' oder
# 'Kira-Setup-vX.Y.Z-N.bin' (N=1..9). Schuetzt vor Path-Traversal-Tricks
# in einem kompromittierten GitHub-Account-Release ('Kira-Setup-../evil').
# security-auditor 2026-05-09.
_VALID_ASSET_NAME = re.compile(
    r"^Kira-Setup-v\d+(?:\.\d+){1,3}(?:-\d+\.bin|\.exe)$"
)


@dataclass(frozen=True)
class ReleaseAsset:
    """Ein einzelnes Release-Asset (Setup-Stub, .bin-Split oder Hash-File)."""
    name: str
    url: str
    size: int = 0  # bytes; aus GitHub-API (0 wenn nicht da)


@dataclass(frozen=True)
class UpdateCheckResult:
    status: UpdateStatus
    remote_version: str | None = None
    # Backwards-compat (v0.1): asset_url + asset_name = der Setup-Stub.
    # Neue Felder fuer Multi-Asset-Bundle:
    asset_url: str | None = None
    asset_name: str | None = None
    bundle_assets: list[ReleaseAsset] = field(default_factory=list)
    sha256sums_url: str | None = None
    error: str | None = None


def _is_setup_stub(name: str) -> bool:
    """Setup-Stub: Kira-Setup-vX.Y.Z.exe (ohne -N im Suffix).

    Whitelist-Match (kein Path-Component, nur Version + .exe) — wer da
    durchkommt ist garantiert ein clean filename ohne '..', '/' oder '\\'.
    """
    if not _VALID_ASSET_NAME.match(name):
        return False
    return name.endswith(_SETUP_SUFFIX)


def _is_setup_split(name: str) -> bool:
    """Setup-Split: Kira-Setup-vX.Y.Z-N.bin (N=1..9 bei DiskSpanning).

    Whitelist-Match auf das gleiche Pattern — Path-Traversal-frei.
    """
    if not _VALID_ASSET_NAME.match(name):
        return False
    return name.endswith(".bin")


def check_for_update(local_version: str, repo: str) -> UpdateCheckResult:
    """Query GitHub Releases for the latest tag and compare to local_version.

    repo is "owner/name". Network and parsing errors collapse to
    status='failed' so callers can show a single message.

    Bei 'newer'-Status sammelt die Methode alle bundle-Assets:
    - asset_url/asset_name = der Setup-Stub (Backwards-Compat fuer v0.1-Code)
    - bundle_assets = ALLE Bundle-Files (Stub + alle .bin-Splits)
    - sha256sums_url = optional SHA256SUMS.txt
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "User-Agent": f"Kira/{local_version}",
        "Accept": "application/vnd.github+json",
    }
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            data = json.load(response)
    except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError) as exc:
        log.warning("update check failed: %s", exc)
        return UpdateCheckResult(status="failed", error=str(exc))

    tag = str(data.get("tag_name", "")).lstrip("v")
    try:
        remote = parse_version(tag)
        local = parse_version(local_version)
    except InvalidVersion as exc:
        log.warning("version parse failed: %s", exc)
        return UpdateCheckResult(status="failed", error=str(exc))

    if remote == local:
        return UpdateCheckResult(status="current", remote_version=tag)
    if remote < local:
        return UpdateCheckResult(status="local_newer", remote_version=tag)

    # remote > local — sammle Setup-Stub + alle .bin-Splits + optional SHA-File
    stub: ReleaseAsset | None = None
    splits: list[ReleaseAsset] = []
    sha_url: str | None = None
    for asset in data.get("assets", []):
        name = asset.get("name", "") or ""
        url_ = asset.get("browser_download_url")
        size = int(asset.get("size", 0))
        if not url_:
            continue
        if _is_setup_stub(name):
            stub = ReleaseAsset(name=name, url=url_, size=size)
        elif _is_setup_split(name):
            splits.append(ReleaseAsset(name=name, url=url_, size=size))
        elif name == _SHA256SUMS_NAME:
            sha_url = url_

    if stub is None:
        return UpdateCheckResult(status="no_asset", remote_version=tag)

    # Splits stable-sortiert nach Name → 1.bin, 2.bin, … 7.bin Reihenfolge.
    splits.sort(key=lambda a: a.name)
    bundle = [stub] + splits
    return UpdateCheckResult(
        status="newer",
        remote_version=tag,
        asset_url=stub.url,
        asset_name=stub.name,
        bundle_assets=bundle,
        sha256sums_url=sha_url,
    )


def download_asset(url: str, target: Path) -> Path:
    """Download a single asset to target. Backwards-compat fuer v0.1-Tests.

    Raises urllib.error.URLError on network failure, OSError on disk-write.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, str(target))
    return target


def download_bundle(
    assets: list[ReleaseAsset],
    target_dir: Path,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> list[Path]:
    """Download alle Assets in target_dir.

    Wichtig: Inno's Disk-Spanning erwartet ALLE Files mit ihren originalen
    Namen IM SELBEN Verzeichnis wie der Stub. Wir behalten daher die
    Asset-Namen 1:1 bei (kein Renaming).

    on_progress(asset_name, bytes_done, bytes_total): wird pro Chunk
    waehrend Downloads gerufen. bytes_total kann -1 sein wenn der Server
    keinen Content-Length-Header schickt — UI-Code muss damit umgehen.

    Raises urllib.error.URLError / OSError beim ersten Fehler. Caller
    ist verantwortlich fuer Cleanup partiell heruntergeladener Files.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for asset in assets:
        # Defense-in-depth: asset.name kommt von GitHub-API, vertraut
        # eigentlich auf check_for_update's Whitelist-Filter — aber bei
        # kompromittiertem Account ist das die letzte Verteidigung.
        if not _VALID_ASSET_NAME.match(asset.name):
            raise ValueError(
                f"asset name nicht whitelist-konform: {asset.name!r}"
            )
        target = target_dir / asset.name
        # Resume-Skip: wenn target existiert UND die size matched, ueber-
        # spring ihn. Erlaubt einen Retry vom Settings-Dialog ohne das
        # ganze 13 GB-Bundle erneut zu pullen. code-reviewer 2026-05-09.
        if (
            asset.size > 0
            and target.exists()
            and target.stat().st_size == asset.size
        ):
            log.info(
                "resume-skip (%s already complete: %d bytes)",
                asset.name, asset.size,
            )
            paths.append(target)
            if on_progress is not None:
                on_progress(asset.name, asset.size, asset.size)
            continue
        log.info("downloading asset %s -> %s", asset.name, target)

        def _hook(block_num: int, block_size: int, total_size: int,
                  _name: str = asset.name) -> None:
            if on_progress is None:
                return
            done = block_num * block_size
            on_progress(_name, done, total_size)

        urllib.request.urlretrieve(asset.url, str(target), reporthook=_hook)
        paths.append(target)
    return paths


def verify_sha256sums(
    sha256sums_path: Path, files_dir: Path,
) -> tuple[bool, list[str]]:
    """Verify alle Files im files_dir gegen die SHA256SUMS-Datei.

    SHA256SUMS-Format ist GNU coreutils Standard:
        <hex-digest>  <filename>
    pro Zeile (zwei Spaces zwischen Hash und Name; Filename relativ).

    Returns (ok, errors). ok=True nur wenn ALLE im SHA256SUMS gelisteten
    Files vorhanden + ihr SHA256 stimmt. Files im files_dir die NICHT im
    SHA256SUMS gelistet sind, sind OK (nicht alle Bundle-Versionen muessen
    Hash-coverage haben — das ist Mike's Verantwortung beim Build).
    """
    errors: list[str] = []
    try:
        content = sha256sums_path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, [f"SHA256SUMS lesefehler: {exc}"]

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # GNU-Format: '<hash>  <filename>' (zwei Leerzeichen)
        parts = line.split(None, 1)
        if len(parts) != 2:
            errors.append(f"unparsable line: {line!r}")
            continue
        expected_hash, filename = parts[0].lower(), parts[1].strip()
        # Filename darf "*" als Binary-Marker haben (z.B. "*Setup.exe")
        if filename.startswith("*"):
            filename = filename[1:]
        target = files_dir / filename
        if not target.exists():
            errors.append(f"file fehlt: {filename}")
            continue
        actual = _file_sha256(target)
        if actual != expected_hash:
            errors.append(
                f"hash mismatch fuer {filename}: "
                f"erwartet {expected_hash[:12]}…, ist {actual[:12]}…"
            )

    return (len(errors) == 0), errors


def _file_sha256(path: Path) -> str:
    """SHA256 hex-digest. Streaming (1 MB chunks) — unsere Bundle-Files sind
    bis zu 2 GiB gross, single-shot read wuerde 2 GiB RAM allokieren."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
