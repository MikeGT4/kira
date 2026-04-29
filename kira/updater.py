"""GitHub-Release-based update checker. Pure logic, no UI."""
from __future__ import annotations
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from packaging.version import InvalidVersion, parse as parse_version

log = logging.getLogger(__name__)

UpdateStatus = Literal["newer", "current", "local_newer", "no_asset", "failed"]
_ASSET_PREFIX = "Kira-Setup-"
_ASSET_SUFFIX = ".exe"
_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class UpdateCheckResult:
    status: UpdateStatus
    remote_version: str | None = None
    asset_url: str | None = None
    asset_name: str | None = None
    error: str | None = None


def check_for_update(local_version: str, repo: str) -> UpdateCheckResult:
    """Query GitHub Releases for the latest tag and compare to local_version.

    repo is "owner/name". Network and parsing errors collapse to status='failed'
    so callers can show a single message.
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

    # remote > local — find the setup EXE asset
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.startswith(_ASSET_PREFIX) and name.endswith(_ASSET_SUFFIX):
            return UpdateCheckResult(
                status="newer",
                remote_version=tag,
                asset_url=asset.get("browser_download_url"),
                asset_name=name,
            )
    return UpdateCheckResult(status="no_asset", remote_version=tag)


def download_asset(url: str, target: Path) -> Path:
    """Download the setup EXE to target. Caller decides where in %TEMP% it lands.

    Raises urllib.error.URLError on network failure, OSError on disk-write failure.
    Unlike check_for_update, this function does NOT collapse exceptions — the
    caller is responsible for handling them (the tray handler wraps the call
    in try/except to surface a German MessageBox to the user).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, str(target))
    return target
